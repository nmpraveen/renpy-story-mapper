from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import NoReturn

import pytest
from jsonschema import Draft202012Validator

from renpy_story_mapper.canonical_graph import build_canonical_graph
from renpy_story_mapper.canonical_graph_contract import CanonicalGraph, source_generation
from renpy_story_mapper.control_flow import analyze_control_flow
from renpy_story_mapper.graph import build_graph
from renpy_story_mapper.m11_scene_projection import build_scene_model
from renpy_story_mapper.parser import parse_script
from renpy_story_mapper.project import Project
from renpy_story_mapper.route_map import project_route_map
from renpy_story_mapper.semantic import build_semantic_story
from renpy_story_mapper.state import extract_state
from renpy_story_mapper.story_map_v2.contracts import canonical_json
from renpy_story_mapper.story_map_v2.phase04_sections import (
    SECTION_SYNTHESIS_ADAPTER_VERSION,
    SECTION_SYNTHESIS_PROMPT_VERSION,
    SECTION_SYNTHESIS_SCHEMA_VERSION,
    assemble_derived_semantics,
    build_derived_semantic_plan,
)
from renpy_story_mapper.story_map_v2.phase04_semantics import assemble_semantic_corridors
from renpy_story_mapper.story_map_v2.product_vertical import (
    execute_product_vertical,
    project_workflow_reader_status,
)
from renpy_story_mapper.story_map_v2.product_workflow import (
    MAPPING_ADAPTER_VERSION,
    FrozenProductRequestMaterializer,
    ProductWorkflowValidator,
    adapt_derived_semantic_job,
    create_product_workflow_service,
    persist_product_workflow_preview,
    prepare_product_workflow_from_authority,
)
from renpy_story_mapper.story_map_v2.reader import StoryMapReader
from renpy_story_mapper.story_map_v2.reader_store import DurableStoryMapReaderSource
from renpy_story_mapper.story_map_v2.workflow_contracts import (
    CLOUD_FAST_MODE,
    CLOUD_MODEL,
    CLOUD_PROVIDER,
    CLOUD_REASONING,
    GLOBAL_SUBMISSION_SLOTS,
    AttemptAccounting,
    ProviderCallKind,
    ProviderCallResult,
    ProviderInputIdentity,
    ProviderMode,
    ProviderSettings,
    SerializedRequestIdentity,
    WorkflowDerivedSemanticJobDescriptor,
    workflow_digest,
)
from renpy_story_mapper.story_map_v2.workflow_http_projection import (
    WORKFLOW_HTTP_CONTRACT,
    WORKFLOW_HTTP_ROUTES,
    workflow_success_envelope,
)
from renpy_story_mapper.story_map_v2.workflow_repository_adapter import (
    DurableWorkflowRepositoryAdapter,
)
from renpy_story_mapper.web.api import ApiProblem, ProjectApi
from renpy_story_mapper.web.state import UserStateStore

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "story_map_v2"
    / "phase04_occurrence_plan.rpy"
)


def _authority() -> CanonicalGraph:
    module = parse_script(
        "game/phase04_occurrence_plan.rpy",
        FIXTURE.read_text(encoding="utf-8").splitlines(keepends=True),
    )
    graph = build_graph([module])
    semantic = build_semantic_story(graph)
    state = extract_state([module])
    control = analyze_control_flow(
        graph,
        semantic,
        state.requirements,
        state.effects,
    ).to_dict()
    route = project_route_map(control, semantic, state.requirements, state.effects)
    return build_canonical_graph(
        graph,
        semantic,
        control,
        route,
        state,
        source_generation=source_generation(((module.path, "4" * 64),)),
    )


def _authority_with_effect() -> CanonicalGraph:
    source = FIXTURE.read_text(encoding="utf-8").replace(
        '        "Continue directly":\n            "The direct local arm stays visible."',
        '        "Continue directly":\n'
        '            $ route_flag = True\n'
        '            "The direct local arm stays visible."',
    )
    module = parse_script(
        "game/phase04_effect.rpy",
        source.splitlines(keepends=True),
    )
    graph = build_graph([module])
    semantic = build_semantic_story(graph)
    state = extract_state([module])
    control = analyze_control_flow(
        graph, semantic, state.requirements, state.effects
    ).to_dict()
    route = project_route_map(control, semantic, state.requirements, state.effects)
    return build_canonical_graph(
        graph,
        semantic,
        control,
        route,
        state,
        source_generation=source_generation(((module.path, "5" * 64),)),
    )


def test_product_prepare_freezes_exact_provider_free_workflow() -> None:
    graph = _authority()
    scene_model = build_scene_model(graph)

    prepared = prepare_product_workflow_from_authority(
        graph,
        scene_model,
        run_id="run:public-product",
    )

    chunk_plan = prepared.frozen_plans.story_chunk_plan
    assert prepared.plan.plan_id == chunk_plan.identity
    assert prepared.plan.authority_identity.value == graph.authority_hash
    assert prepared.policy.cloud.model == CLOUD_MODEL
    assert prepared.policy.cloud.reasoning == CLOUD_REASONING
    assert prepared.policy.cloud.fast_mode is False
    assert prepared.policy.cloud.adapter_version == MAPPING_ADAPTER_VERSION
    assert prepared.policy.loopback is None
    assert prepared.ceilings.submission_slots == GLOBAL_SUBMISSION_SLOTS
    assert prepared.ceilings.mapping_calls == len(prepared.plan.jobs)
    assert prepared.ceilings.review_calls == len(prepared.plan.jobs)
    assert prepared.ceilings.fallback_calls == 0
    assert prepared.ceilings.section_synthesis_calls == len(chunk_plan.chunks)
    assert all(
        chunk.complete_request_tokens is None
        or chunk.complete_request_tokens <= chunk_plan.maximum_request_tokens
        for chunk in chunk_plan.chunks
    )
    requests = prepared.materialized_requests()
    assert len(requests) == len(prepared.plan.jobs)
    for job in prepared.plan.jobs:
        request = requests[job.serialized_request_identity.value]
        job.serialized_request_identity.verify(request)
        packet = json.loads(request)
        assert packet["task"].startswith("Return exactly one JSON object")
        assert packet["raw_story"]
        assert job.cache_identity == prepared.policy.input_identity(
            job.serialized_request_identity
        ).cache_identity


def test_product_prepare_discloses_optional_loopback_in_same_frozen_ceiling() -> None:
    graph = _authority()
    scene_model = build_scene_model(graph)
    loopback = ProviderSettings(
        provider="lm-studio-loopback",
        model="qwen-local",
        reasoning=None,
        fast_mode=None,
        mode=ProviderMode.LOOPBACK,
        adapter_version="story-map-v2-phase04-loopback-v1",
    )

    prepared = prepare_product_workflow_from_authority(
        graph,
        scene_model,
        run_id="run:public-loopback",
        loopback=loopback,
    )

    assert prepared.policy.loopback == loopback
    assert prepared.policy.allow_refusal_fallback
    assert prepared.ceilings.fallback_calls == len(prepared.plan.jobs)
    assert prepared.ceilings.indeterminate_retry_calls == (
        len(prepared.plan.jobs)
        + prepared.ceilings.section_synthesis_calls
        + prepared.ceilings.rollup_synthesis_calls
    )


def test_product_validator_overlays_authority_onto_provider_prose() -> None:
    graph = _authority()
    prepared = prepare_product_workflow_from_authority(
        graph,
        build_scene_model(graph),
        run_id="run:provider-prose",
    )
    job = prepared.plan.jobs[0]
    chunk = next(
        item
        for item in prepared.frozen_plans.story_chunk_plan.chunks
        if item.chunk_id == job.chunk_id
    )
    prose = {
        "title": "Story opening",
        "overview": "The opening events establish the current situation.",
        "review_requested": False,
        "events": [
            {
                "key": "opening",
                "placement_ids": list(chunk.placement_ids),
                "title": "Opening events",
                "summary": "The characters move through the opening sequence.",
                "characters": [],
            }
        ],
        "branch_summaries": [
            {
                "choice_key": segment.choice_key,
                "arm_orders": list(segment.arm_orders),
                "summary": "The available responses briefly diverge before continuing.",
            }
            for segment in chunk.choice_segments
        ],
    }

    result = ProductWorkflowValidator(prepared).validate(
        job,
        json.dumps(prose).encode(),
        cached=False,
    )
    normalized = json.loads(result.normalized_payload)

    assert normalized["story_chunk_plan_identity"] == prepared.plan.plan_id
    assert normalized["chunk_id"] == job.chunk_id
    assert normalized["request_hash"] == job.serialized_request_identity.sha256
    assert normalized["scope_id"] == job.scope_id


def test_approved_product_runner_accepts_all_mapping_jobs_without_live_provider(
    tmp_path: Path,
) -> None:
    graph = _authority()
    prepared = prepare_product_workflow_from_authority(
        graph,
        build_scene_model(graph),
        run_id="run:approved-mapping",
    )
    chunks = {
        chunk.chunk_id: chunk for chunk in prepared.frozen_plans.story_chunk_plan.chunks
    }

    class ProseProvider:
        def submit(self, request: bytes) -> ProviderCallResult:
            packet = json.loads(request)
            chunk = chunks[packet["chunk_id"]]
            prose = {
                "title": "Mapped story chunk",
                "overview": "The supplied events are summarized in chronological order.",
                "review_requested": False,
                "events": [
                    {
                        "key": "event",
                        "placement_ids": list(chunk.placement_ids),
                        "title": "Story events",
                        "summary": "The characters progress through this part of the story.",
                        "characters": [],
                    }
                ],
                "branch_summaries": [
                    {
                        "choice_key": segment.choice_key,
                        "arm_orders": list(segment.arm_orders),
                        "summary": "The choice paths diverge locally as described by Python.",
                    }
                    for segment in chunk.choice_segments
                ],
            }
            return ProviderCallResult(
                payload=canonical_json(prose),
                accounting=AttemptAccounting(1, 100, 40, 10),
                resolved_provider=CLOUD_PROVIDER,
                resolved_model=CLOUD_MODEL,
                resolved_reasoning=CLOUD_REASONING,
                resolved_fast_mode=CLOUD_FAST_MODE,
            )

        def cancel(self) -> None:
            return None

    path = tmp_path / "approved-mapping.rsmproj"
    with Project.create(path) as project:
        preview = persist_product_workflow_preview(project, prepared)
        service = create_product_workflow_service(
            project,
            prepared,
            cloud_factory=ProseProvider,
        )
        service.approve(prepared.run_id, preview.identity)
        status = service.execute(
            prepared.run_id,
            preview_identity=preview.identity,
            authority_identity=prepared.plan.authority_identity,
        )

    assert status.pending_jobs == 0
    assert status.accepted_jobs == len(prepared.plan.jobs)
    assert status.structural_fallback_jobs == 0
    assert status.accounting.calls == len(prepared.plan.jobs)


def test_product_validator_binds_contiguous_section_prose_to_derived_job() -> None:
    graph = _authority()
    prepared = prepare_product_workflow_from_authority(
        graph,
        build_scene_model(graph),
        run_id="run:derived-section",
    )
    semantic = prepared.plan.derived_semantic_plan
    assert semantic is not None
    request = b'{"call_kind":"section_synthesis"}'
    identity = SerializedRequestIdentity(
        "request:derived-section",
        hashlib.sha256(request).hexdigest(),
        len(request),
    )
    provider_input = ProviderInputIdentity(
        identity,
        SECTION_SYNTHESIS_PROMPT_VERSION,
        SECTION_SYNTHESIS_SCHEMA_VERSION,
        SECTION_SYNTHESIS_ADAPTER_VERSION,
        CLOUD_PROVIDER,
        CLOUD_MODEL,
        CLOUD_REASONING,
        CLOUD_FAST_MODE,
        ProviderMode.CLOUD,
    )
    job = WorkflowDerivedSemanticJobDescriptor(
        plan_id=prepared.plan.plan_id,
        semantic_plan_identity=semantic.semantic_plan_identity,
        story_chunk_plan_identity=semantic.story_chunk_plan_identity,
        candidate_generation_identity=workflow_digest("candidate:section"),
        authority_identity=prepared.plan.authority_identity,
        job_id="derived:section:one",
        call_kind=ProviderCallKind.SECTION_SYNTHESIS,
        node_role=None,
        corridor_id=semantic.corridors[0].corridor_id,
        route_owner=semantic.corridors[0].route_owner,
        child_ids=("event:one", "event:two"),
        child_prose_hashes=(workflow_digest("one"), workflow_digest("two")),
        ordinal=0,
        serialized_request_identity=identity,
        provider_input_identity=provider_input,
        cache_identity=provider_input.cache_identity,
    )
    prose = {
        "title": "Opening sequence",
        "summary": "The opening events establish the story.",
        "sections": [
            {
                "first_event_id": "event:one",
                "last_event_id": "event:two",
                "title": "The beginning",
                "summary": "Two events form one continuous opening section.",
            }
        ],
    }
    validator = ProductWorkflowValidator(prepared)

    result = validator.validate(job, canonical_json(prose), cached=False)
    normalized = json.loads(result.normalized_payload)

    assert normalized["semantic_plan_identity"] == semantic.semantic_plan_identity
    assert normalized["ordered_child_ids"] == ["event:one", "event:two"]
    assert validator.validate(job, result.normalized_payload, cached=True) == result


def test_published_mapping_events_unlock_durable_section_jobs(tmp_path: Path) -> None:
    graph = _authority()
    prepared = prepare_product_workflow_from_authority(
        graph,
        build_scene_model(graph),
        run_id="run:durable-sections",
    )
    chunks = {
        chunk.chunk_id: chunk for chunk in prepared.frozen_plans.story_chunk_plan.chunks
    }

    class MappingAndSectionProvider:
        def submit(self, request: bytes) -> ProviderCallResult:
            packet = json.loads(request)
            if packet.get("call_kind") == "section_synthesis":
                child_ids = [child["id"] for child in packet["children"]]
                prose: dict[str, object] = {
                    "title": "Meaningful story corridor",
                    "summary": "The related events form a continuous part of the story.",
                    "sections": [
                        {
                            "first_event_id": child_ids[0],
                            "last_event_id": child_ids[-1],
                            "title": "A continuous sequence",
                            "summary": "The ordered events progress through one narrative beat.",
                        }
                    ],
                }
            else:
                chunk = chunks[packet["chunk_id"]]
                prose = {
                    "title": "Mapped story chunk",
                    "overview": "The supplied events are summarized in chronological order.",
                    "review_requested": False,
                    "events": [
                        {
                            "key": "event",
                            "placement_ids": list(chunk.placement_ids),
                            "title": "Story events",
                            "summary": "The characters progress through this part of the story.",
                            "characters": [],
                        }
                    ],
                    "branch_summaries": [
                        {
                            "choice_key": segment.choice_key,
                            "arm_orders": list(segment.arm_orders),
                            "summary": "The choice paths briefly diverge.",
                        }
                        for segment in chunk.choice_segments
                    ],
                }
            return ProviderCallResult(
                payload=canonical_json(prose),
                accounting=AttemptAccounting(1, 100, 40, 10),
                resolved_provider=CLOUD_PROVIDER,
                resolved_model=CLOUD_MODEL,
                resolved_reasoning=CLOUD_REASONING,
                resolved_fast_mode=CLOUD_FAST_MODE,
            )

        def cancel(self) -> None:
            return None

    path = tmp_path / "durable-sections.rsmproj"
    with Project.create(path) as project:
        preview = persist_product_workflow_preview(project, prepared)
        materializer = FrozenProductRequestMaterializer(prepared)
        service = create_product_workflow_service(
            project,
            prepared,
            cloud_factory=MappingAndSectionProvider,
            request_materializer=materializer,
        )
        service.approve(prepared.run_id, preview.identity)
        service.execute(
            prepared.run_id,
            preview_identity=preview.identity,
            authority_identity=prepared.plan.authority_identity,
        )
        repository = DurableWorkflowRepositoryAdapter.from_project(project)
        mapping_payloads = tuple(
            result.normalized_payload
            for job in prepared.plan.jobs
            if (result := repository.load_published_result(prepared.run_id, job.job_id))
            is not None
        )
        semantic_assembly = assemble_semantic_corridors(
            prepared.frozen_plans.story_chunk_plan,
            mapping_payloads,
        )
        derived_plan = build_derived_semantic_plan(
            prepared.frozen_plans.story_chunk_plan,
            prepared.plan.authority_identity.value,
        )
        derived = assemble_derived_semantics(
            derived_plan,
            semantic_assembly,
            workflow_digest("candidate:durable-sections"),
        )
        for semantic_job in derived.section_jobs:
            durable_job = adapt_derived_semantic_job(prepared, semantic_job)
            materializer.register(durable_job.serialized_request_identity, semantic_job.request)
            service.register_derived_job(
                prepared.run_id,
                preview_identity=preview.identity,
                job=durable_job,
            )
        status = service.execute(
            prepared.run_id,
            preview_identity=preview.identity,
            authority_identity=prepared.plan.authority_identity,
        )

    assert status.pending_jobs == 0
    assert status.accepted_jobs == len(prepared.plan.jobs) + len(derived.section_jobs)
    assert all(
        repository.load_published_result(prepared.run_id, job.job_id) is not None
        for job in (adapt_derived_semantic_job(prepared, item) for item in derived.section_jobs)
    )


def test_product_preview_persists_exact_plans_with_zero_provider_construction(
    tmp_path: Path,
) -> None:
    graph = _authority()
    prepared = prepare_product_workflow_from_authority(
        graph,
        build_scene_model(graph),
        run_id="run:durable-product",
    )
    path = tmp_path / "product-preview.rsmproj"

    with Project.create(path) as project:
        preview = persist_product_workflow_preview(project, prepared)
        assert preview.identity
        assert DurableWorkflowRepositoryAdapter.from_project(project).status(
            prepared.run_id
        ).pending_jobs == len(prepared.plan.jobs)

    with Project.open(path) as project:
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        reopened = adapter.load_preview(prepared.run_id)
        frozen = adapter.load_frozen_plans(prepared.run_id)

    assert reopened.identity == preview.identity
    assert frozen is not None
    assert frozen.story_plan_bytes == prepared.frozen_plans.story_plan_bytes
    assert (
        frozen.story_chunk_plan_bytes
        == prepared.frozen_plans.story_chunk_plan_bytes
    )


def test_product_prepare_projects_exact_privacy_safe_http_v2_envelope(
    tmp_path: Path,
) -> None:
    graph = _authority()
    prepared = prepare_product_workflow_from_authority(
        graph,
        build_scene_model(graph),
        run_id="run:http-product",
    )
    path = tmp_path / "http-preview.rsmproj"
    with Project.create(path) as project:
        preview = persist_product_workflow_preview(project, prepared)
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        envelope = workflow_success_envelope(
            "prepare",
            preview,
            adapter.status(prepared.run_id),
            None,
        )

    schema_path = (
        Path(__file__).parents[1]
        / "src"
        / "renpy_story_mapper"
        / "story_map_v2"
        / "schemas"
        / "story_map_workflow_http_v2.schema.json"
    )
    root_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    success_schema = {
        "$schema": root_schema["$schema"],
        "$defs": root_schema["$defs"],
        "$ref": "#/$defs/successEnvelope",
    }
    assert not tuple(Draft202012Validator(success_schema).iter_errors(envelope))
    assert envelope["contract"] == WORKFLOW_HTTP_CONTRACT
    serialized = json.dumps(envelope, sort_keys=True)
    assert "raw_story" not in serialized
    assert "serialized_request_identity" not in serialized


def test_approved_vertical_publishes_reader_with_effects_rejoins_and_ai_overview(
    tmp_path: Path,
) -> None:
    graph = _authority_with_effect()
    prepared = prepare_product_workflow_from_authority(
        graph,
        build_scene_model(graph),
        run_id="run:vertical-reader",
    )
    chunks = {
        chunk.chunk_id: chunk for chunk in prepared.frozen_plans.story_chunk_plan.chunks
    }

    class FakeProvider:
        def submit(self, request: bytes) -> ProviderCallResult:
            packet = json.loads(request)
            call_kind = packet.get("call_kind")
            if call_kind == "section_synthesis":
                child_ids = [child["id"] for child in packet["children"]]
                prose: dict[str, object] = {
                    "title": "Chronological section",
                    "summary": "The story events remain in their exact order.",
                    "sections": [
                        {
                            "first_event_id": child_ids[0],
                            "last_event_id": child_ids[-1],
                            "title": "Story section",
                            "summary": "A concise part of the whole story.",
                        }
                    ],
                }
            elif call_kind == "rollup_synthesis":
                prose = {
                    "title": "Whole story",
                    "summary": "The routes split, progress, and reach their known outcomes.",
                }
            else:
                chunk = chunks[packet["chunk_id"]]
                prose = {
                    "title": "Mapped chunk",
                    "overview": "This chunk advances the story.",
                    "review_requested": False,
                    "events": [
                        {
                            "key": "event",
                            "placement_ids": list(chunk.placement_ids),
                            "title": "Story events",
                            "summary": "The characters move through this part of the story.",
                            "characters": [],
                        }
                    ],
                    "branch_summaries": [
                        {
                            "choice_key": segment.choice_key,
                            "arm_orders": list(segment.arm_orders),
                            "summary": "The known outcomes diverge and may rejoin.",
                        }
                        for segment in chunk.choice_segments
                    ],
                }
            return ProviderCallResult(
                payload=canonical_json(prose),
                accounting=AttemptAccounting(1, 100, 40, 10),
                resolved_provider=CLOUD_PROVIDER,
                resolved_model=CLOUD_MODEL,
                resolved_reasoning=CLOUD_REASONING,
                resolved_fast_mode=CLOUD_FAST_MODE,
            )

        def cancel(self) -> None:
            return None

    path = tmp_path / "vertical-reader.rsmproj"
    with Project.create(path) as project:
        preview = persist_product_workflow_preview(project, prepared)
        service = create_product_workflow_service(
            project,
            prepared,
            cloud_factory=FakeProvider,
        )
        service.approve(prepared.run_id, preview.identity)

    execute_product_vertical(
        path,
        prepared,
        preview_identity=preview.identity,
        cloud_factory=FakeProvider,
        authority_graph=graph,
    )

    with Project.open(path) as project:
        source = DurableStoryMapReaderSource(
            project.story_map_v2_repository(),
            workflow_status=project_workflow_reader_status,
        )
        reader = StoryMapReader(source)
        manifest = reader.manifest()
        assert reader.status()["state"] == "complete"
        assert manifest["overview"] == {
            "title": "Whole story",
            "summary": "The routes split, progress, and reach their known outcomes.",
        }
        revision = manifest["map_revision"]
        assert isinstance(revision, int)
        branch_ids: list[str] = []
        visible_event_effects: list[str] = []
        for section in manifest["sections"]:
            assert isinstance(section, dict)
            page = reader.section_page(
                map_revision=revision,
                section_id=str(section["id"]),
            )
            branch_ids.extend(
                str(item["id"])
                for item in page["items"]
                if isinstance(item, dict) and item.get("kind") == "choice"
            )
            visible_event_effects.extend(
                effect
                for item in page["items"]
                if isinstance(item, dict) and item.get("kind") in {"event", "ending"}
                for effect in item["effects"]
            )
        branches = [
            reader.branch_page(map_revision=revision, branch_id=branch_id)
            for branch_id in branch_ids
        ]
        arms = [item for branch in branches for item in branch["items"]]
        shells = [shell for branch in branches for shell in branch["shells"]]
        assert any("route_flag = True" in item["effects"] for item in arms)
        assert "route_flag = True" in visible_event_effects
        assert all(item["destination_id"] for item in arms)
        assert any(shell["rejoin_selection_id"] for shell in shells)
        selected = next(item["selection_id"] for item in arms if item["effects"])
        assert reader.selection_navigation(
            map_revision=revision,
            selection_id=str(selected),
        ) is not None


def test_project_api_advertises_only_frozen_workflow_routes_and_safe_errors(
    tmp_path: Path,
) -> None:
    class Dialogs:
        def choose_source(self, _kind: str) -> None:
            return None

        def choose_open_project(self) -> None:
            return None

        def choose_save_project(self) -> None:
            return None

    provider_constructions = 0

    def provider_trap() -> NoReturn:
        nonlocal provider_constructions
        provider_constructions += 1
        raise AssertionError("bootstrap and invalid requests must not construct a provider")

    api = ProjectApi(
        Dialogs(),
        state_store=UserStateStore(tmp_path / "state.json"),
        phase04_cloud_factory=provider_trap,
    )
    try:
        bootstrap = api.dispatch("GET", "/api/v1/bootstrap", {})
        assert isinstance(bootstrap, dict)
        assert bootstrap["routes"]["story_map_v2_workflow"] == WORKFLOW_HTTP_ROUTES
        with pytest.raises(ApiProblem) as caught:
            api.dispatch(
                "POST",
                WORKFLOW_HTTP_ROUTES["prepare"],
                {"contract": "foreign-contract"},
            )
        assert caught.value.status == 400
        assert caught.value.payload == {
            "contract": WORKFLOW_HTTP_CONTRACT,
            "error": {
                "code": "invalid_workflow_request",
                "message": "The workflow request is invalid.",
                "sanitized_reason": "invalid_request",
            },
        }
        assert provider_constructions == 0
    finally:
        api.close()


def test_vertical_publishes_structural_reader_when_all_prose_is_invalid(
    tmp_path: Path,
) -> None:
    graph = _authority()
    prepared = prepare_product_workflow_from_authority(
        graph,
        build_scene_model(graph),
        run_id="run:vertical-structural",
    )

    class InvalidProvider:
        def submit(self, _request: bytes) -> ProviderCallResult:
            return ProviderCallResult(
                payload=canonical_json({"invalid": True}),
                accounting=AttemptAccounting(1, 10, 5, 1),
                resolved_provider=CLOUD_PROVIDER,
                resolved_model=CLOUD_MODEL,
                resolved_reasoning=CLOUD_REASONING,
                resolved_fast_mode=CLOUD_FAST_MODE,
            )

        def cancel(self) -> None:
            return None

    path = tmp_path / "vertical-structural.rsmproj"
    with Project.create(path) as project:
        preview = persist_product_workflow_preview(project, prepared)
        create_product_workflow_service(
            project,
            prepared,
            cloud_factory=InvalidProvider,
        ).approve(prepared.run_id, preview.identity)
    execute_product_vertical(
        path,
        prepared,
        preview_identity=preview.identity,
        cloud_factory=InvalidProvider,
        authority_graph=graph,
    )
    with Project.open(path) as project:
        reader = StoryMapReader(
            DurableStoryMapReaderSource(
                project.story_map_v2_repository(),
                workflow_status=project_workflow_reader_status,
            )
        )
        manifest = reader.manifest()
        assert manifest["status"] == "complete"
        assert manifest["sections"]
        assert manifest["overview"]["title"] == "Whole story overview"
        assert manifest["overview"]["summary"]
