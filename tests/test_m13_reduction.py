from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from renpy_story_mapper.m12_model import RouteBadge, TechnicalStatus
from renpy_story_mapper.narrative.authority import load_narrative_authority
from renpy_story_mapper.narrative.batching import BatchLimits
from renpy_story_mapper.narrative.contracts import (
    BudgetLimits,
    ConsentManifest,
    CostConfidence,
    LogicalJobKind,
    PrivacyMode,
    ProviderIdentity,
    ProviderSettings,
    RunEstimate,
)
from renpy_story_mapper.narrative.hierarchy import (
    HierarchyArtifactInput,
    HierarchyPartitionConfig,
    HierarchyPathContext,
    M12RouteAuthority,
    PersistentRouteSpec,
    StorySection,
    make_m12_authority_leaf,
    plan_chapter_jobs,
    plan_common_story_job,
    plan_persistent_route_job,
    plan_plot_job,
)
from renpy_story_mapper.narrative.persistence import LookupState, RecordKind
from renpy_story_mapper.narrative.provider import (
    PROMPT_TEMPLATE_VERSION,
    RESPONSE_SCHEMA_VERSION,
    ProviderOutputItem,
    ProviderRequest,
    ProviderResponse,
    ProviderStatus,
    ProviderUsage,
)
from renpy_story_mapper.narrative.reduction import (
    RuntimeNarrativeArtifact,
    execute_hierarchy_jobs,
    prepare_hierarchy_job,
)
from renpy_story_mapper.narrative.scheduler import SchedulerPolicy, SchedulerUsage
from renpy_story_mapper.project import Project, create_ingested_project
from renpy_story_mapper.storage import canonical_json

FIXTURE = Path(__file__).parent / "fixtures" / "m12" / "route_targets.rpy"


@dataclass
class ChildClaimProvider:
    requests: list[ProviderRequest] = field(default_factory=list)
    claim_count: int = 1

    def status(self) -> ProviderStatus:
        return ProviderStatus(True, "test-cloud", "test-adapter", "test-adapter-v1")

    def submit(self, request: ProviderRequest, cancelled: object) -> ProviderResponse:
        del cancelled
        self.requests.append(request)
        identity = _provider_identity(request.requested_model)
        return ProviderResponse(
            request.request_id,
            identity,
            tuple(
                ProviderOutputItem(
                    item.logical_job_id,
                    index,
                    {
                        "logical_job_id": item.logical_job_id,
                        "title": "Chapter summary",
                        "summary": "The chapter preserves its bounded child chronology.",
                        "claims": [
                            {
                                "claim_class": "factual",
                                "context_scope": "atomic",
                                "text": f"The chapter includes supported child event {ordinal}.",
                                "evidence_handles": [],
                                "child_claim_handles": ["C1"],
                                "subject": f"chapter-{ordinal}",
                                "predicate": "includes child event",
                                "polarity": "positive",
                                "normalized_value": "included",
                            }
                            for ordinal in range(self.claim_count)
                        ],
                    },
                )
                for index, item in enumerate(request.items)
            ),
            ProviderUsage(25, 15, 4),
            PROMPT_TEMPLATE_VERSION,
            RESPONSE_SCHEMA_VERSION,
        )

    def cancel(self) -> None:
        return


def _provider_identity(model: str = "runtime-model") -> ProviderIdentity:
    return ProviderIdentity(
        "test-cloud",
        "test-adapter",
        "test-adapter-v1",
        model,
        model,
        ProviderSettings(),
    )


def _project(tmp_path: Path) -> Project:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    return create_ingested_project(tmp_path / "m13-reduction.rsmproj", source)


def _claim(claim_id: str) -> dict[str, object]:
    return {
        "claim_id": claim_id,
        "logical_job_id": "child-job",
        "job_kind": "summary_segment",
        "ordinal": 0,
        "claim_class": "factual",
        "context_scope": "atomic",
        "text": "A supported child event occurs.",
        "support": {"kind": "child_claims", "direct_evidence": [], "child_claim_ids": ["leaf"]},
        "semantics": {
            "subject": "event",
            "predicate": "occurs",
            "polarity": "positive",
            "normalized_value": "yes",
        },
    }


def test_hierarchy_execution_uses_only_c_handles_and_persists_direct_claim_edges(
    tmp_path: Path,
) -> None:
    path = HierarchyPathContext(StorySection.COMMON, persistent_lane_id="lane-spine")
    child_id = "child-artifact-a"
    child_claim_id = "child-claim-a"
    child_payload = {
        "title": "Child",
        "summary": "Bounded child summary.",
        "claims": [_claim(child_claim_id)],
    }
    runtime = RuntimeNarrativeArtifact(
        child_id,
        "child-job",
        child_payload,
        (child_claim_id,),
        100,
        path,
        0,
        "scene:0",
        chapter_id="chapter-1",
        chapter_ordinal=0,
    )
    plan = plan_chapter_jobs(
        (
            HierarchyArtifactInput(
                artifact_id=child_id,
                job_kind=LogicalJobKind.SUMMARY_SEGMENT,
                claim_ids=(child_claim_id,),
                estimated_tokens=100,
                path=path,
                chronology_index=0,
                temporal_anchor="scene:0",
                chapter_id="chapter-1",
                chapter_ordinal=0,
            ),
        ),
        HierarchyPartitionConfig("en-US", "reader"),
    )
    descriptor = plan.jobs[0]
    provider = ChildClaimProvider()
    identity = _provider_identity()
    with _project(tmp_path) as project:
        authority = load_narrative_authority(project, include_m12=True)
        prepared = prepare_hierarchy_job(
            descriptor,
            {child_id: runtime},
            authority,
            scope_id="selected-scope",
            ordinal=0,
            deterministic_title="Chapter 1",
            deterministic_summary="Chapter summary unavailable.",
        )
        encoded = canonical_json(prepared.payload)
        assert child_claim_id.encode() not in encoded
        assert b'"handle":"C1"' in encoded
        child_context = dict(prepared.claim_contexts)[child_claim_id]
        assert child_context.chapter_id == "chapter-1"
        assert child_context.temporal_anchor == "scene:0"
        assert child_context.lane_id == "lane-spine"
        consent = ConsentManifest(
            run_id="hierarchy-run",
            provider=identity,
            selected_scope_ids=("selected-scope",),
            privacy_mode=PrivacyMode.FACT_ONLY,
            includes_m12_material=False,
            estimate=RunEstimate(10, 10, 100_000, 100_000, None, CostConfidence.UNAVAILABLE),
            limits=BudgetLimits(20, 200_000, 200_000, 400_000, 300, 2),
            consent_granted=True,
        )
        result = execute_hierarchy_jobs(
            project,
            provider,
            (prepared,),
            consent,
            policy=SchedulerPolicy(BatchLimits(4, 500_000, 100_000)),
            initial_usage=SchedulerUsage(
                provider_calls=2,
                input_tokens=10,
                output_tokens=5,
                elapsed_ms=3,
                cost_micros=0,
                peak_concurrency=1,
            ),
        )

        assert result.scheduler.record.usage.provider_calls == 3
        assert len(result.artifacts) == 1
        parent_claim_id = result.artifacts[0].claim_ids[0]
        claim = project.m13_persistence().lookup(
            RecordKind.CLAIM,
            parent_claim_id,
            authority_binding=authority.binding.to_dict(),
        )
        assert claim.state is LookupState.HIT
        assert claim.payload is not None
        support = claim.payload["support"]
        assert isinstance(support, dict)
        assert support["child_claim_ids"] == [child_claim_id]
        parent_runtime = result.artifacts[0]
        claim_contexts = parent_runtime.payload["claim_contexts"]
        assert isinstance(claim_contexts, list)
        assert claim_contexts[0]["claim_id"] == parent_claim_id
        assert claim_contexts[0]["context"]["temporal_anchor"] == "scene:0"
        next_input = HierarchyArtifactInput(
            artifact_id=parent_runtime.artifact_id,
            job_kind=LogicalJobKind.CHAPTER,
            claim_ids=parent_runtime.claim_ids,
            estimated_tokens=parent_runtime.estimated_tokens,
            path=parent_runtime.path,
            chronology_index=parent_runtime.chronology_index,
            temporal_anchor=parent_runtime.temporal_anchor,
            chapter_id=parent_runtime.chapter_id,
            chapter_ordinal=parent_runtime.chapter_ordinal,
        )
        next_descriptor = plan_common_story_job(
            (next_input,),
            HierarchyPartitionConfig("en-US", "reader"),
        ).jobs[0]
        next_prepared = prepare_hierarchy_job(
            next_descriptor,
            {parent_runtime.artifact_id: parent_runtime},
            authority,
            scope_id="selected-scope",
            ordinal=1,
            deterministic_title="Common story",
            deterministic_summary="Common story summary unavailable.",
        )
        next_children = next_prepared.payload["child_artifacts"]
        assert isinstance(next_children, list)
        nested_claims = next_children[0]["claims"]
        assert isinstance(nested_claims, list)
        assert nested_claims[0]["structural_context"]["temporal_anchor"] == "scene:0"
        edges = project.m13_persistence().list_records(
            RecordKind.CLAIM_EDGE,
            authority_binding=authority.binding.to_dict(),
        )
        assert len(edges) == 1
        assert provider.requests[0].consent_manifest_id == consent.manifest_id


def test_exact_m12_claims_are_reserved_in_the_32_claim_propagation_window(
    tmp_path: Path,
) -> None:
    path = HierarchyPathContext(StorySection.COMMON, persistent_lane_id="lane-spine")
    child_id = "common-story-artifact"
    child_claim_id = "common-story-claim"
    runtime = RuntimeNarrativeArtifact(
        child_id,
        "common-story-job",
        {
            "title": "Common story",
            "summary": "Bounded common story.",
            "claims": [_claim(child_claim_id)],
        },
        (child_claim_id,),
        100,
        path,
        0,
        "common-story",
    )
    shared = HierarchyArtifactInput(
        artifact_id=child_id,
        job_kind=LogicalJobKind.ROUTE,
        claim_ids=(child_claim_id,),
        estimated_tokens=100,
        path=path,
        chronology_index=0,
        temporal_anchor="common-story",
    )
    leaf = make_m12_authority_leaf(
        M12RouteAuthority(
            result_identity="result-route-a",
            route_id="route-a",
            persistent_lane_id="lane-route-a",
            status=TechnicalStatus.BEST_KNOWN,
            badge=RouteBadge.BEST_KNOWN,
            prerequisite_texts=("Prerequisite remains conditional.",),
        ),
        locale="en-US",
        perspective="reader",
    )
    descriptor = plan_persistent_route_job(
        PersistentRouteSpec("route-a", "lane-route-a", 0, "Route A"),
        shared,
        (),
        HierarchyPartitionConfig("en-US", "reader"),
        m12_authority_leaf=leaf,
    ).jobs[0]
    provider = ChildClaimProvider(claim_count=32)
    identity = _provider_identity()
    with _project(tmp_path) as project:
        authority = load_narrative_authority(project, include_m12=True)
        prepared = prepare_hierarchy_job(
            descriptor,
            {child_id: runtime},
            authority,
            scope_id="selected-scope",
            ordinal=0,
            deterministic_title="Route A",
            deterministic_summary="Route summary unavailable.",
            authority_claims={claim.claim_id: claim for claim in leaf.claims},
        )
        consent = ConsentManifest(
            run_id="route-hierarchy-run",
            provider=identity,
            selected_scope_ids=("selected-scope",),
            privacy_mode=PrivacyMode.FACT_ONLY,
            includes_m12_material=True,
            estimate=RunEstimate(1, 1, 100_000, 100_000, None, CostConfidence.UNAVAILABLE),
            limits=BudgetLimits(5, 200_000, 200_000, 400_000, 300, 1),
            consent_granted=True,
        )
        result = execute_hierarchy_jobs(
            project,
            provider,
            (prepared,),
            consent,
            policy=SchedulerPolicy(BatchLimits(1, 500_000, 100_000)),
        )

        runtime_result = result.artifacts[0]
        assert len(runtime_result.claim_ids) == 32
        propagated = set(runtime_result.claim_ids)
        represented: set[str] = set()
        for claim in runtime_result.payload["claims"]:
            if claim["claim_id"] not in propagated:
                continue
            represented.update(
                set(claim["support"]["child_claim_ids"]).intersection(leaf.claim_ids)
            )
        assert represented == set(leaf.claim_ids)

        route_input = HierarchyArtifactInput(
            artifact_id=runtime_result.artifact_id,
            job_kind=LogicalJobKind.ROUTE,
            claim_ids=runtime_result.claim_ids,
            mandatory_claim_ids=runtime_result.mandatory_claim_ids,
            estimated_tokens=runtime_result.estimated_tokens,
            path=runtime_result.path,
            chronology_index=runtime_result.chronology_index,
            temporal_anchor=runtime_result.temporal_anchor,
        )
        plot_descriptor = plan_plot_job(
            shared,
            (route_input,),
            (),
            (),
            HierarchyPartitionConfig("en-US", "reader"),
        ).jobs[0]
        assert set(plot_descriptor.mandatory_child_claim_ids) == set(
            runtime_result.mandatory_claim_ids
        )
        plot_prepared = prepare_hierarchy_job(
            plot_descriptor,
            {
                child_id: runtime,
                runtime_result.artifact_id: runtime_result,
            },
            authority,
            scope_id="selected-scope",
            ordinal=1,
            deterministic_title="Whole plot",
            deterministic_summary="Plot summary unavailable.",
        )
        plot_result = execute_hierarchy_jobs(
            project,
            ChildClaimProvider(),
            (plot_prepared,),
            consent,
            policy=SchedulerPolicy(BatchLimits(1, 500_000, 100_000)),
        )
        plot_runtime = plot_result.artifacts[0]
        assert len(plot_runtime.mandatory_claim_ids) == len(
            runtime_result.mandatory_claim_ids
        )
        plot_claims = {
            claim["claim_id"]: claim for claim in plot_runtime.payload["claims"]
        }
        represented_route_claims = {
            child_claim_id
            for claim_id in plot_runtime.mandatory_claim_ids
            for child_claim_id in plot_claims[claim_id]["support"]["child_claim_ids"]
        }
        assert represented_route_claims == set(runtime_result.mandatory_claim_ids)


def test_hierarchy_descriptor_accepts_mandatory_authority_above_optional_window() -> None:
    path = HierarchyPathContext(StorySection.COMMON, persistent_lane_id="lane-spine")
    mandatory = tuple(f"mandatory-{ordinal}" for ordinal in range(33))
    child = HierarchyArtifactInput(
        artifact_id="bounded-authority-artifact",
        job_kind=LogicalJobKind.SUMMARY_SEGMENT,
        claim_ids=mandatory,
        mandatory_claim_ids=mandatory,
        estimated_tokens=100,
        path=path,
        chronology_index=0,
        temporal_anchor="bounded-authority",
    )

    descriptor = plan_common_story_job(
        (child,),
        HierarchyPartitionConfig("en-US", "reader"),
    ).jobs[0]

    assert descriptor.mandatory_child_claim_ids == mandatory
