from __future__ import annotations

from dataclasses import fields, replace

import pytest

from renpy_story_mapper.m12_model import RouteBadge, TechnicalStatus
from renpy_story_mapper.narrative.contracts import (
    AuthoritySystem,
    LogicalJobKind,
    SupportKind,
)
from renpy_story_mapper.narrative.hierarchy import (
    ChronologyPolicy,
    EndingSpec,
    HierarchyArtifactInput,
    HierarchyJobDescriptor,
    HierarchyPartitionConfig,
    HierarchyPathContext,
    M12RouteAuthority,
    PersistentRouteSpec,
    StorySection,
    accepted_hierarchy_output,
    make_m12_authority_leaf,
    plan_chapter_jobs,
    plan_character_role_job,
    plan_common_story_job,
    plan_ending_job,
    plan_persistent_route_job,
    plan_plot_job,
)


def _config(**changes: object) -> HierarchyPartitionConfig:
    values: dict[str, object] = {
        "locale": "en-US",
        "perspective": "reader",
    }
    values.update(changes)
    return HierarchyPartitionConfig(**values)  # type: ignore[arg-type]


def _common_path() -> HierarchyPathContext:
    return HierarchyPathContext(StorySection.COMMON, persistent_lane_id="lane-spine")


def _route_path(route_id: str) -> HierarchyPathContext:
    return HierarchyPathContext(
        StorySection.PERSISTENT_ROUTE,
        persistent_lane_id=f"lane-{route_id}",
        route_id=route_id,
    )


def _temporary_path(
    arm_id: str,
    *,
    route_id: str | None = None,
) -> HierarchyPathContext:
    lane_id = "lane-spine" if route_id is None else f"lane-{route_id}"
    return HierarchyPathContext(
        StorySection.TEMPORARY_BRANCH,
        persistent_lane_id=lane_id,
        route_id=route_id,
        temporary_container_id="temporary-container",
        temporary_arm_id=arm_id,
        rejoin_anchor_id="merge-node",
    )


def _ending_path(ending_id: str, route_id: str | None = None) -> HierarchyPathContext:
    return HierarchyPathContext(
        StorySection.ENDING,
        persistent_lane_id=None if route_id is None else f"lane-{route_id}",
        route_id=route_id,
        ending_id=ending_id,
    )


def _segment(
    artifact_id: str,
    *,
    path: HierarchyPathContext,
    chapter: int = 0,
    chronology: int = 0,
    tokens: int = 100,
    available: bool = True,
    claim_count: int = 1,
) -> HierarchyArtifactInput:
    return HierarchyArtifactInput(
        artifact_id=artifact_id,
        job_kind=LogicalJobKind.SUMMARY_SEGMENT,
        claim_ids=(
            tuple(f"claim-{artifact_id}-{index}" for index in range(claim_count))
            if available
            else ()
        ),
        estimated_tokens=tokens,
        path=path,
        chronology_index=chronology,
        temporal_anchor=f"anchor-{chapter}",
        chapter_id=f"chapter-{chapter}",
        chapter_ordinal=chapter,
        available=available,
    )


def _accepted(
    descriptor: HierarchyJobDescriptor,
    *,
    artifact_id: str,
    claim_id: str,
    tokens: int = 100,
) -> HierarchyArtifactInput:
    return accepted_hierarchy_output(
        descriptor,
        artifact_id=artifact_id,
        claim_ids=(claim_id,),
        estimated_tokens=tokens,
    )


def _m12(route_id: str = "route-a") -> M12RouteAuthority:
    return M12RouteAuthority(
        result_identity=f"result-{route_id}",
        route_id=route_id,
        persistent_lane_id=f"lane-{route_id}",
        status=TechnicalStatus.BEST_KNOWN,
        badge=RouteBadge.BEST_KNOWN,
        prerequisite_texts=("Prerequisite: finish the shared occurrence before committing.",),
        conclusion_texts=("This remains the best-known route; completeness is not proven.",),
    )


def test_m12_authority_leaf_preserves_exact_status_badge_and_prerequisite_language() -> None:
    authority = _m12()
    leaf = make_m12_authority_leaf(
        authority,
        locale="en-US",
        perspective="reader",
    )

    assert tuple(claim.text for claim in leaf.claims) == (
        TechnicalStatus.BEST_KNOWN.value,
        RouteBadge.BEST_KNOWN.value,
        *authority.prerequisite_texts,
        *authority.conclusion_texts,
    )
    assert all(claim.claim_class.value == "factual" for claim in leaf.claims)
    assert tuple(claim.semantics.predicate for claim in leaf.claims if claim.semantics) == (
        "status",
        "badge",
        "prerequisite:0",
        "conclusion:0",
    )
    assert all(
        claim.semantics is not None
        and claim.semantics.polarity.value == "neutral"
        and claim.semantics.normalized_value == claim.text
        for claim in leaf.claims
    )
    assert all(claim.support.kind is SupportKind.DIRECT_EVIDENCE for claim in leaf.claims)
    assert all(
        claim.support.direct_evidence[0].authority is AuthoritySystem.M12
        and claim.support.direct_evidence[0].record_id == authority.result_identity
        and claim.support.direct_evidence[0].owner_id == leaf.job.owner_id
        for claim in leaf.claims
    )
    assert (
        make_m12_authority_leaf(
            authority,
            locale="en-US",
            perspective="reader",
        )
        == leaf
    )
    changed = make_m12_authority_leaf(
        replace(authority, prerequisite_texts=("Different exact prerequisite.",)),
        locale="en-US",
        perspective="reader",
    )
    assert changed.job.job_id != leaf.job.job_id


@pytest.mark.parametrize(
    ("status", "badge"),
    (
        (TechnicalStatus.PREREQUISITES, RouteBadge.PREREQUISITES),
        (TechnicalStatus.BEST_KNOWN, RouteBadge.BEST_KNOWN),
        (TechnicalStatus.INCOMPLETE, RouteBadge.NO_PROVEN),
        (TechnicalStatus.DYNAMIC_POSSIBILITY, RouteBadge.NO_PROVEN),
        (TechnicalStatus.STATE_INFEASIBLE, RouteBadge.NO_PROVEN),
        (TechnicalStatus.NO_STATIC_ROUTE, RouteBadge.NO_PROVEN),
    ),
)
def test_m12_nonconfirmed_statuses_are_never_upgraded(
    status: TechnicalStatus,
    badge: RouteBadge,
) -> None:
    authority = replace(_m12(), status=status, badge=badge)
    leaf = make_m12_authority_leaf(
        authority,
        locale="en-US",
        perspective="reader",
    )

    assert leaf.authority.status is status
    assert leaf.authority.badge is badge
    assert leaf.claims[0].text == status.value
    assert leaf.claims[1].text == badge.value
    assert leaf.claims[0].semantics is not None
    assert leaf.claims[0].semantics.normalized_value == status.value


def test_chapter_jobs_are_segment_only_and_never_mix_exclusive_paths() -> None:
    inputs = (
        _segment("common-1", path=_common_path(), chronology=0),
        _segment("common-2", path=_common_path(), chronology=1),
        _segment("temporary-a", path=_temporary_path("arm-a"), chronology=2),
        _segment("temporary-b", path=_temporary_path("arm-b"), chronology=2),
        _segment("route-a", path=_route_path("route-a"), chronology=3),
        _segment("route-b", path=_route_path("route-b"), chronology=3),
    )

    plan = plan_chapter_jobs(tuple(reversed(inputs)), _config())
    replay = plan_chapter_jobs(inputs, _config())

    assert plan == replay
    assert plan.complete
    assert len(plan.jobs) == 5
    for descriptor in plan.jobs:
        assert {entry.path.identity for entry in descriptor.section_entries} == {
            descriptor.path.identity
        }
        assert all(
            entry.job_kind is LogicalJobKind.SUMMARY_SEGMENT for entry in descriptor.section_entries
        )
        assert descriptor.spec.context.structural_fingerprint is not None
    route_jobs = {
        descriptor.path.route_id: descriptor
        for descriptor in plan.jobs
        if descriptor.path.section is StorySection.PERSISTENT_ROUTE
    }
    assert route_jobs["route-a"].child_artifact_ids == ("route-a",)
    assert route_jobs["route-b"].child_artifact_ids == ("route-b",)
    assert {
        descriptor.path.temporary_arm_id
        for descriptor in plan.jobs
        if descriptor.path.section is StorySection.TEMPORARY_BRANCH
    } == {"arm-a", "arm-b"}

    raw_scene = replace(inputs[0], job_kind=LogicalJobKind.SCENE)
    with pytest.raises(ValueError, match="never raw scene"):
        plan_chapter_jobs((raw_scene,), _config())


def test_shared_story_is_planned_once_and_persistent_route_uses_immediate_claims() -> None:
    chapter_plan = plan_chapter_jobs(
        (
            _segment("common", path=_common_path()),
            _segment("temporary-a", path=_temporary_path("arm-a"), chronology=1),
            _segment("temporary-b", path=_temporary_path("arm-b"), chronology=1),
            _segment("route-a", path=_route_path("route-a"), chronology=2),
            _segment("route-b", path=_route_path("route-b"), chronology=2),
        ),
        _config(),
    )
    outputs = tuple(
        _accepted(
            descriptor,
            artifact_id=f"chapter-artifact-{index}",
            claim_id=f"chapter-claim-{index}",
        )
        for index, descriptor in enumerate(chapter_plan.jobs)
    )
    shared_chapters = tuple(child for child in outputs if child.path.route_id is None)
    common_plan = plan_common_story_job(shared_chapters, _config())
    common_descriptor = common_plan.jobs[0]
    common_artifact = _accepted(
        common_descriptor,
        artifact_id="common-story-artifact",
        claim_id="common-story-claim",
    )
    route_a_chapters = tuple(child for child in outputs if child.path.route_id == "route-a")
    leaf = make_m12_authority_leaf(_m12(), locale="en-US", perspective="reader")
    route_plan = plan_persistent_route_job(
        PersistentRouteSpec("route-a", "lane-route-a", 0, "Route A"),
        common_artifact,
        route_a_chapters,
        _config(),
        m12_authority_leaf=leaf,
    )
    descriptor = route_plan.jobs[0]

    assert common_descriptor.chronology_policy is ChronologyPolicy.STRUCTURED_ALTERNATIVES
    assert common_artifact.contains_structured_alternatives
    assert common_artifact.structure_manifest_id == common_descriptor.structure_manifest_id
    assert descriptor.child_artifact_ids[0] == "common-story-artifact"
    assert descriptor.path.route_id == "route-a"
    assert descriptor.route_ids == ("route-a",)
    assert descriptor.child_claim_ids == (
        "common-story-claim",
        *(child.claim_ids[0] for child in route_a_chapters),
    )
    assert descriptor.authority_leaf_claim_ids == leaf.claim_ids
    assert descriptor.m12_authority == (_m12(),)
    assert descriptor.provenance_edge_count == len(descriptor.allowed_support_claim_ids)
    assert "evidence_ids" not in {field.name for field in fields(descriptor)}

    route_b_chapter = next(child for child in outputs if child.path.route_id == "route-b")
    with pytest.raises(ValueError, match="another route"):
        plan_persistent_route_job(
            PersistentRouteSpec("route-a", "lane-route-a", 0, "Route A"),
            common_artifact,
            (route_b_chapter,),
            _config(),
        )


def test_route_job_preserves_every_bounded_m12_result_without_flattening() -> None:
    common_chapter = plan_chapter_jobs(
        (_segment("common", path=_common_path()),),
        _config(),
    ).jobs[0]
    common = _accepted(
        plan_common_story_job(
            (
                _accepted(
                    common_chapter,
                    artifact_id="common-chapter-artifact",
                    claim_id="common-chapter-claim",
                ),
            ),
            _config(),
        ).jobs[0],
        artifact_id="common-story-artifact",
        claim_id="common-story-claim",
    )
    first = make_m12_authority_leaf(_m12(), locale="en-US", perspective="reader")
    second_authority = replace(
        _m12(),
        result_identity="result-route-a-second-target",
        status=TechnicalStatus.PREREQUISITES,
        badge=RouteBadge.PREREQUISITES,
        prerequisite_texts=("Exact second-target prerequisite.",),
    )
    second = make_m12_authority_leaf(
        second_authority,
        locale="en-US",
        perspective="reader",
    )

    descriptor = plan_persistent_route_job(
        PersistentRouteSpec("route-a", "lane-route-a", 0, "Route A"),
        common,
        (),
        _config(),
        m12_authority_leaves=(first, second),
    ).jobs[0]

    assert descriptor.m12_authority == (first.authority, second.authority)
    assert descriptor.authority_leaf_claim_ids == first.claim_ids + second.claim_ids
    assert "Exact second-target prerequisite." in {
        claim.text for claim in (*first.claims, *second.claims)
    }
    with pytest.raises(ValueError, match="either one"):
        plan_persistent_route_job(
            PersistentRouteSpec("route-a", "lane-route-a", 0, "Route A"),
            common,
            (),
            _config(),
            m12_authority_leaf=first,
            m12_authority_leaves=(second,),
        )


def test_ending_and_plot_keep_routes_endings_and_missing_coverage_separate() -> None:
    common_chapter = plan_chapter_jobs(
        (_segment("common", path=_common_path()),),
        _config(),
    ).jobs[0]
    route_chapter = plan_chapter_jobs(
        (_segment("route", path=_route_path("route-a")),),
        _config(),
    ).jobs[0]
    common_story_descriptor = plan_common_story_job(
        (
            _accepted(
                common_chapter,
                artifact_id="common-chapter-artifact",
                claim_id="common-chapter-claim",
            ),
        ),
        _config(),
    ).jobs[0]
    common_story = _accepted(
        common_story_descriptor,
        artifact_id="common-story-artifact",
        claim_id="common-story-claim",
    )
    route_descriptor = plan_persistent_route_job(
        PersistentRouteSpec("route-a", "lane-route-a", 0, "Route A"),
        common_story,
        (
            _accepted(
                route_chapter,
                artifact_id="route-chapter-artifact",
                claim_id="route-chapter-claim",
            ),
        ),
        _config(),
    ).jobs[0]
    route_artifact = _accepted(
        route_descriptor,
        artifact_id="route-artifact",
        claim_id="route-claim",
    )
    ending_segment = _segment(
        "ending-segment",
        path=_ending_path("ending-a", "route-a"),
        chapter=2,
    )
    leaf = make_m12_authority_leaf(_m12(), locale="en-US", perspective="reader")
    ending_descriptor = plan_ending_job(
        EndingSpec("ending-a", 0, "Ending A", "route-a", "lane-route-a"),
        (ending_segment,),
        _config(),
        route_artifact=route_artifact,
        m12_authority_leaf=leaf,
    ).jobs[0]
    ending_artifact = _accepted(
        ending_descriptor,
        artifact_id="ending-artifact",
        claim_id="ending-claim",
    )
    unresolved = replace(
        _segment("unresolved-segment", path=_common_path(), chapter=3),
        path=HierarchyPathContext(
            StorySection.UNRESOLVED,
            persistent_lane_id="lane-spine",
        ),
        available=False,
        claim_ids=(),
        covered_leaf_count=0,
    )
    plot = plan_plot_job(
        common_story,
        (route_artifact,),
        (ending_artifact,),
        (unresolved,),
        _config(),
    ).jobs[0]

    assert ending_descriptor.m12_authority[0].prerequisite_texts == _m12().prerequisite_texts
    assert plot.spec.kind is LogicalJobKind.PLOT
    assert plot.chronology_policy is ChronologyPolicy.ROUTE_AWARE
    assert plot.child_artifact_ids == (
        "common-story-artifact",
        "route-artifact",
        "ending-artifact",
        "unresolved-segment",
    )
    assert plot.route_ids == ("route-a",)
    assert plot.ending_ids == ("ending-a",)
    assert plot.missing_child_artifact_ids == ("unresolved-segment",)
    assert plot.coverage_percentage < 100
    assert (
        plot.section_entries[0].structure_manifest_id
        == common_story_descriptor.structure_manifest_id
    )
    assert all(
        entry.job_kind
        in {
            LogicalJobKind.ROUTE,
            LogicalJobKind.ENDING,
            LogicalJobKind.SUMMARY_SEGMENT,
            LogicalJobKind.CHAPTER,
        }
        for entry in plot.section_entries
    )

    raw_scene = replace(
        unresolved,
        job_kind=LogicalJobKind.SCENE,
        available=True,
        claim_ids=("scene-claim",),
        covered_leaf_count=1,
    )
    with pytest.raises(ValueError, match="bounded chapter or segment"):
        plan_plot_job(common_story, (route_artifact,), (ending_artifact,), (raw_scene,), _config())


def test_oversized_or_over_token_groups_request_reduction_without_creating_a_job() -> None:
    children = tuple(
        _segment(f"segment-{index}", path=_common_path(), chronology=index) for index in range(33)
    )
    count_plan = plan_chapter_jobs(children, _config())
    replay = plan_chapter_jobs(tuple(reversed(children)), _config())

    assert not count_plan.complete
    assert count_plan.jobs == ()
    assert count_plan.reductions[0].reason_codes == ("child_count_limit",)
    assert count_plan.reductions[0].request_id == replay.reductions[0].request_id
    assert (
        count_plan.reductions[0].request_id
        != plan_chapter_jobs(
            children,
            _config(locale="fr-FR"),
        )
        .reductions[0]
        .request_id
    )
    assert (
        count_plan.reductions[0].request_id
        != plan_chapter_jobs(
            children,
            _config(partition_version="hierarchy-partition-v2"),
        )
        .reductions[0]
        .request_id
    )

    token_plan = plan_chapter_jobs(
        (
            _segment("large-a", path=_common_path(), chronology=0, tokens=600),
            _segment("large-b", path=_common_path(), chronology=1, tokens=600),
        ),
        _config(maximum_input_tokens=1_000, prompt_overhead_tokens=100),
    )
    assert token_plan.jobs == ()
    assert token_plan.reductions[0].reason_codes == ("input_token_limit",)


def test_character_role_plan_is_bounded_and_route_aware_without_claiming_an_arc() -> None:
    route_a = replace(
        _segment("route-a-segment", path=_route_path("route-a")),
        job_kind=LogicalJobKind.ROUTE,
    )
    route_b = replace(
        _segment("route-b-segment", path=_route_path("route-b")),
        job_kind=LogicalJobKind.ROUTE,
    )
    descriptor = plan_character_role_job(
        "character-a",
        (route_b, route_a),
        _config(),
    ).jobs[0]

    assert descriptor.spec.kind is LogicalJobKind.CHARACTER
    assert descriptor.chronology_policy is ChronologyPolicy.ROUTE_AWARE
    assert descriptor.route_ids == ("route-a", "route-b")
    assert descriptor.child_artifact_ids == ("route-a-segment", "route-b-segment")


def _scale_shape(per_chapter: int) -> tuple[int, int, int]:
    config = _config(maximum_input_tokens=100_000)
    paths = (_common_path(), _route_path("route-a"), _route_path("route-b"))
    segments = tuple(
        _segment(
            f"segment-{path_index}-{chapter}-{index}",
            path=path,
            chapter=chapter,
            chronology=index,
        )
        for path_index, path in enumerate(paths)
        for chapter in range(6)
        for index in range(per_chapter)
    )
    chapter_plan = plan_chapter_jobs(segments, config)
    assert chapter_plan.complete
    chapters = tuple(
        _accepted(
            descriptor,
            artifact_id=f"chapter-output-{index}",
            claim_id=f"chapter-output-claim-{index}",
        )
        for index, descriptor in enumerate(chapter_plan.jobs)
    )
    common_descriptor = plan_common_story_job(
        tuple(child for child in chapters if child.path.section is StorySection.COMMON),
        config,
    ).jobs[0]
    common = _accepted(
        common_descriptor,
        artifact_id="common-output",
        claim_id="common-output-claim",
    )
    route_descriptors = tuple(
        plan_persistent_route_job(
            PersistentRouteSpec(route_id, f"lane-{route_id}", ordinal, route_id),
            common,
            tuple(child for child in chapters if child.path.route_id == route_id),
            config,
        ).jobs[0]
        for ordinal, route_id in enumerate(("route-a", "route-b"))
    )
    routes = tuple(
        _accepted(
            descriptor,
            artifact_id=f"route-output-{index}",
            claim_id=f"route-output-claim-{index}",
        )
        for index, descriptor in enumerate(route_descriptors)
    )
    ending_descriptors = tuple(
        plan_ending_job(
            EndingSpec(
                f"ending-{index}",
                index,
                f"Ending {index}",
                route.path.route_id,
                route.path.persistent_lane_id,
            ),
            (
                _segment(
                    f"ending-segment-{index}",
                    path=_ending_path(f"ending-{index}", route.path.route_id),
                    chapter=6,
                ),
            ),
            config,
            route_artifact=route,
        ).jobs[0]
        for index, route in enumerate(routes)
    )
    endings = tuple(
        _accepted(
            descriptor,
            artifact_id=f"ending-output-{index}",
            claim_id=f"ending-output-claim-{index}",
        )
        for index, descriptor in enumerate(ending_descriptors)
    )
    plot = plan_plot_job(common, routes, endings, (), config).jobs[0]
    descriptors = (
        *chapter_plan.jobs,
        common_descriptor,
        *route_descriptors,
        *ending_descriptors,
        plot,
    )
    direct_edges = sum(descriptor.provenance_edge_count for descriptor in descriptors)
    artifact_records = len(segments) + len(descriptors)
    return len(segments), artifact_records, direct_edges


def test_hierarchy_artifacts_and_claim_dag_edges_grow_approximately_linearly() -> None:
    small_inputs, small_artifacts, small_edges = _scale_shape(8)
    large_inputs, large_artifacts, large_edges = _scale_shape(16)

    assert large_inputs == small_inputs * 2
    assert 1.75 <= large_artifacts / small_artifacts <= 2.05
    assert 1.75 <= large_edges / small_edges <= 2.05
    assert small_edges <= small_inputs + 40
    assert large_edges <= large_inputs + 40
