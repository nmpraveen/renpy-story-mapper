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
from renpy_story_mapper.narrative.pipeline import run_complete_narrative
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
            claim_class = "interpretive" if job_kind == "character" else "factual"
            outputs.append(
                ProviderOutputItem(
                    item.logical_job_id,
                    index,
                    {
                        "logical_job_id": item.logical_job_id,
                        "title": f"{job_kind.replace('_', ' ').title()} {index + 1}",
                        "summary": f"Bounded {job_kind} result {index + 1}.",
                        "claims": [
                            {
                                "claim_class": claim_class,
                                "text": f"Supported {job_kind} claim {index + 1}.",
                                "evidence_handles": ["E1"] if scene else [],
                                "child_claim_handles": [] if scene else ["C1"],
                                "subject": job_kind,
                                "predicate": "has supported result",
                                "polarity": "positive",
                                "normalized_value": str(index + 1),
                            }
                        ],
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
