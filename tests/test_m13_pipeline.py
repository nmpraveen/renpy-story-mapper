from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from renpy_story_mapper.m12_service import M12RouteService
from renpy_story_mapper.narrative.authority import load_narrative_authority
from renpy_story_mapper.narrative.batching import BatchLimits
from renpy_story_mapper.narrative.contracts import (
    BudgetLimits,
    ProviderIdentity,
    ProviderSettings,
)
from renpy_story_mapper.narrative.persistence import LookupState, RecordKind
from renpy_story_mapper.narrative.pipeline import (
    _m12_leaves,
    _route_specs,
    project_scene_placements,
    run_complete_narrative,
)
from renpy_story_mapper.narrative.projection import NarrativeInputMode
from renpy_story_mapper.narrative.provider import (
    PROMPT_TEMPLATE_VERSION,
    RESPONSE_SCHEMA_VERSION,
    ProviderOutputItem,
    ProviderRequest,
    ProviderResponse,
    ProviderStatus,
    ProviderUsage,
)
from renpy_story_mapper.narrative.scheduler import SchedulerPolicy
from renpy_story_mapper.narrative.workflow import (
    grant_narrative_consent,
    prepare_narrative_scene_run,
)
from renpy_story_mapper.project import Project, create_ingested_project

FIXTURE = Path(__file__).parent / "fixtures" / "m12" / "route_targets.rpy"


@dataclass
class CompleteHierarchyProvider:
    requests: list[ProviderRequest] = field(default_factory=list)
    refused_scene_title: str | None = None

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            True,
            "approved-test-cloud",
            "test-structured-adapter",
            "test-adapter-v1",
            "test-cli-v1",
        )

    def submit(self, request: ProviderRequest, cancelled: object) -> ProviderResponse:
        del cancelled
        self.requests.append(request)
        identity = ProviderIdentity(
            "approved-test-cloud",
            "test-structured-adapter",
            "test-adapter-v1",
            request.requested_model,
            request.requested_model,
            ProviderSettings(),
        )
        outputs: list[ProviderOutputItem] = []
        for index, item in enumerate(request.items):
            payload = item.payload
            job_kind = str(payload["job_kind"])
            scene = job_kind == "scene"
            if scene and payload.get("deterministic_title") == self.refused_scene_title:
                outputs.append(
                    ProviderOutputItem(
                        item.logical_job_id,
                        index,
                        None,
                        error_code="content_refusal",
                    )
                )
                continue
            claim_class = "interpretive" if job_kind == "character" else "factual"
            child_handles = [
                str(claim["handle"])
                for child in payload.get("child_artifacts", [])
                for claim in child.get("claims", [])
            ] + [
                str(claim["handle"])
                for claim in payload.get("exact_m12_authority_claims", [])
            ]
            claims = []
            if scene or child_handles:
                claims = [
                    {
                        "claim_class": claim_class,
                        "text": f"Supported {job_kind} claim {index + 1}.",
                        "evidence_handles": ["E1"] if scene else [],
                        "child_claim_handles": [] if scene else [child_handles[0]],
                        "subject": job_kind,
                        "predicate": "has supported result",
                        "polarity": "positive",
                        "normalized_value": str(index + 1),
                    }
                ]
            outputs.append(
                ProviderOutputItem(
                    item.logical_job_id,
                    index,
                    {
                        "logical_job_id": item.logical_job_id,
                        "title": f"{job_kind.replace('_', ' ').title()} {index + 1}",
                        "summary": f"Bounded {job_kind} result {index + 1}.",
                        "claims": claims,
                    },
                )
            )
        return ProviderResponse(
            request.request_id,
            identity,
            tuple(outputs),
            ProviderUsage(50, 25, 5),
            PROMPT_TEMPLATE_VERSION,
            RESPONSE_SCHEMA_VERSION,
        )

    def cancel(self) -> None:
        return


def _project(tmp_path: Path) -> Project:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    project = create_ingested_project(tmp_path / "m13-pipeline.rsmproj", source)
    service = M12RouteService(project)
    destination = next(
        item for item in service.destinations(limit=50)["nodes"] if item["kind"] == "generic_scene"
    )
    outcome = service.solve(service.prepare(destination["kind"], destination["target_id"]))
    assert outcome.result is not None
    return project


def _limits() -> BudgetLimits:
    return BudgetLimits(500, 20_000_000, 20_000_000, 40_000_000, 300, 4)


def _batch_limits() -> BatchLimits:
    return BatchLimits(16, 500_000, 100_000)


def _run(
    project: Project,
    provider: CompleteHierarchyProvider,
    run_id: str,
):
    prepared = prepare_narrative_scene_run(
        project,
        provider,
        run_id=run_id,
        requested_model="runtime-selected-model",
        mode=NarrativeInputMode.FACT_ONLY,
        include_m12_material=True,
        limits=_limits(),
        batch_limits=_batch_limits(),
    )
    consent = grant_narrative_consent(project, prepared)
    return run_complete_narrative(
        project,
        provider,
        prepared,
        consent,
        policy=SchedulerPolicy(_batch_limits()),
    )


def test_complete_pipeline_publishes_route_aware_plot_and_exact_m12_leaf(
    tmp_path: Path,
) -> None:
    provider = CompleteHierarchyProvider()
    with _project(tmp_path) as project:
        source_hashes = tuple((item.path, item.content_hash) for item in project.sources())
        authority_before = load_narrative_authority(project, include_m12=True).binding
        result = _run(project, provider, "complete-pipeline")
        authority_after = load_narrative_authority(project, include_m12=True).binding

        assert result.record.state.value == "succeeded"
        assert result.artifacts.plot_artifact_id is not None
        assert result.artifacts.segment_artifact_ids
        assert result.artifacts.chapter_artifact_ids
        assert result.artifacts.route_artifact_ids
        assert result.artifacts.ending_artifact_ids
        assert provider.requests
        assert source_hashes == tuple(
            (item.path, item.content_hash) for item in project.sources()
        )
        assert authority_before == authority_after

        plot = project.m13_persistence().lookup(
            RecordKind.ARTIFACT,
            result.artifacts.plot_artifact_id,
        )
        assert plot.state is LookupState.HIT
        assert plot.payload is not None
        hierarchy = plot.payload["hierarchy"]
        assert isinstance(hierarchy, dict)
        assert hierarchy["chronology_policy"] == "shared_then_separate_routes_and_endings"
        entries = hierarchy["section_entries"]
        assert isinstance(entries, list)
        assert all(item["job_kind"] != "scene" for item in entries)
        assert {item["path"]["section"] for item in entries} >= {
            "common_shared_story",
            "persistent_route",
            "ending",
        }

        m12_claims = [
            item.payload
            for item in project.m13_persistence().list_records(RecordKind.CLAIM)
            if item.state is LookupState.HIT
            and item.payload is not None
            and item.payload.get("job_kind") == "authority_fact"
        ]
        assert m12_claims
        exact_text = {str(item["text"]) for item in m12_claims}
        assert {"incomplete_solve", "Best known route"} <= exact_text


def test_complete_pipeline_exact_replay_makes_zero_provider_calls(tmp_path: Path) -> None:
    project_path = tmp_path / "m13-pipeline.rsmproj"
    first_provider = CompleteHierarchyProvider()
    with _project(tmp_path) as project:
        first = _run(project, first_provider, "pipeline-first")
    assert first_provider.requests

    replay_provider = CompleteHierarchyProvider()
    with Project.open(project_path) as project:
        replay = _run(project, replay_provider, "pipeline-replay")

        assert replay_provider.requests == []
        assert replay.record.usage.provider_calls == 0
        assert replay.artifacts == first.artifacts
        assert all(item.cache_replay for item in replay.jobs)


def test_content_refusal_is_job_local_and_retry_reuses_valid_artifacts(
    tmp_path: Path,
) -> None:
    first_provider = CompleteHierarchyProvider(refused_scene_title="Blue Route")
    with _project(tmp_path) as project:
        first = _run(project, first_provider, "pipeline-local-refusal")

        assert first.record.state.value == "partial"
        assert first.record.refused_jobs == 1
        assert first.artifacts.plot_artifact_id is not None
        refused = [item for item in first.jobs if item.state.value == "refused"]
        assert len(refused) == 1
        published_before = {
            item.record_id
            for item in project.m13_persistence().list_records(RecordKind.ARTIFACT)
            if item.state is LookupState.HIT
        }

        recovery_provider = CompleteHierarchyProvider()
        recovered = _run(project, recovery_provider, "pipeline-refusal-retry")
        published_after = {
            item.record_id
            for item in project.m13_persistence().list_records(RecordKind.ARTIFACT)
            if item.state is LookupState.HIT
        }

        assert recovered.record.state.value == "succeeded"
        assert recovery_provider.requests
        assert len(recovery_provider.requests) < len(first_provider.requests)
        assert any(item.cache_replay for item in recovered.jobs)
        assert published_before <= published_after


def test_selected_scene_scope_does_not_plan_unselected_persistent_routes(
    tmp_path: Path,
) -> None:
    provider = CompleteHierarchyProvider()
    with _project(tmp_path) as project:
        authority = load_narrative_authority(project, include_m12=True)
        placement = next(
            item
            for item in project_scene_placements(authority.scene_model)
            if item.path.route_id is None and item.path.ending_id is None
        )
        prepared = prepare_narrative_scene_run(
            project,
            provider,
            run_id="selected-common-scene",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=True,
            limits=_limits(),
            batch_limits=_batch_limits(),
            selected_scene_ids=(placement.scene_id,),
        )
        consent = grant_narrative_consent(project, prepared)
        result = run_complete_narrative(
            project,
            provider,
            prepared,
            consent,
            policy=SchedulerPolicy(_batch_limits()),
        )

        assert len(prepared.scene_run.jobs) == 1
        assert result.record.state.value == "succeeded"
        assert result.artifacts.route_artifact_ids == ()
        assert result.artifacts.ending_artifact_ids == ()
        assert result.artifacts.plot_artifact_id is not None


def test_m12_leaf_projection_keeps_multiple_relevant_result_identities(
    tmp_path: Path,
) -> None:
    with _project(tmp_path) as project:
        authority = load_narrative_authority(project, include_m12=True)
        original = dict(authority.m12_results[0])
        duplicate = dict(original)
        duplicate["request_identity"] = f"{original['request_identity']}-second"
        routes = _route_specs(authority.scene_model)

        leaves = _m12_leaves(
            (original, duplicate),
            routes,
            locale="en-US",
            perspective="reader",
        )

        relevant = next(items for items in leaves.values() if items)
        assert len(relevant) == 2
        assert {item.authority.result_identity for item in relevant} == {
            str(original["request_identity"]),
            str(duplicate["request_identity"]),
        }
        assert all(item.authority.status.value == original["status"] for item in relevant)


def test_character_artifacts_keep_common_and_route_specific_roles_separate(
    tmp_path: Path,
) -> None:
    source = tmp_path / "game"
    source.mkdir()
    story = FIXTURE.read_text(encoding="utf-8")
    story = 'define ava = Character("Ava")\ndefine ben = Character("Ben")\n\n' + story
    story = story.replace(
        '    "The route begins in the foyer."',
        '    ava "The route begins in the foyer."',
    ).replace(
        '    "The red commitment stays separate."',
        '    ava "The red commitment stays separate."',
    ).replace(
        '    "The blue commitment stays separate."',
        '    ben "The blue commitment stays separate."',
    ).replace(
        '    "The red route ends here."',
        '    ava "The red route ends here."',
    ).replace(
        '    "The blue route ends here."',
        '    ben "The blue route ends here."',
    )
    (source / "story.rpy").write_text(story, encoding="utf-8")
    provider = CompleteHierarchyProvider()
    with create_ingested_project(tmp_path / "characters.rsmproj", source) as project:
        authority = load_narrative_authority(project, include_m12=True)
        placements = {
            item.scene_id: item for item in project_scene_placements(authority.scene_model)
        }
        prepared = prepare_narrative_scene_run(
            project,
            provider,
            run_id="route-aware-characters",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=True,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        expected_routes: dict[str, set[str]] = {"ava": set(), "ben": set()}
        for item in prepared.scene_run.jobs:
            context = item.payload["structural_context"]
            assert isinstance(context, dict)
            participation = context["m13_character_participation"]
            assert isinstance(participation, dict)
            for speaker in participation["character_ids"]:
                route_id = placements[item.job.spec.owner_id].path.route_id
                if route_id is not None:
                    expected_routes[str(speaker)].add(route_id)
                support_records = item.payload["support_records"]
                assert isinstance(support_records, list)
                matching = [
                    support
                    for support in support_records
                    if speaker in support["record"].get("character_ids", [])
                ]
                assert matching
                assert all(support["record"]["source_text"] is None for support in matching)
        consent = grant_narrative_consent(project, prepared)
        result = run_complete_narrative(
            project,
            provider,
            prepared,
            consent,
            policy=SchedulerPolicy(_batch_limits()),
        )

        assert len(result.artifacts.character_artifact_ids) == 2
        artifacts = []
        for artifact_id in result.artifacts.character_artifact_ids:
            lookup = project.m13_persistence().lookup(RecordKind.ARTIFACT, artifact_id)
            assert lookup.state is LookupState.HIT
            assert lookup.payload is not None
            artifacts.append(lookup.payload)
        observed_routes: set[frozenset[str]] = set()
        for artifact in artifacts:
            assert artifact["job_kind"] == "character"
            assert artifact["claims"][0]["claim_class"] == "interpretive"
            hierarchy = artifact["hierarchy"]
            assert (
                hierarchy["chronology_policy"]
                == "shared_then_separate_routes_and_endings"
            )
            route_ids = {
                entry["path"]["route_id"]
                for entry in hierarchy["section_entries"]
                if entry["path"]["route_id"] is not None
            }
            assert len(route_ids) == 1
            observed_routes.add(frozenset(route_ids))
        assert observed_routes == {
            frozenset(route_ids) for route_ids in expected_routes.values()
        }
