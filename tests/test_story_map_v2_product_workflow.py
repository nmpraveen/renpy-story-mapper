from __future__ import annotations

import json
from pathlib import Path

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
from renpy_story_mapper.story_map_v2.product_workflow import (
    MAPPING_ADAPTER_VERSION,
    ProductWorkflowValidator,
    persist_product_workflow_preview,
    prepare_product_workflow_from_authority,
)
from renpy_story_mapper.story_map_v2.workflow_contracts import (
    CLOUD_MODEL,
    CLOUD_REASONING,
    GLOBAL_SUBMISSION_SLOTS,
    ProviderMode,
    ProviderSettings,
)
from renpy_story_mapper.story_map_v2.workflow_http_projection import (
    WORKFLOW_HTTP_CONTRACT,
    workflow_success_envelope,
)
from renpy_story_mapper.story_map_v2.workflow_repository_adapter import (
    DurableWorkflowRepositoryAdapter,
)

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
