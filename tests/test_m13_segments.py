from __future__ import annotations

from dataclasses import fields, replace

import pytest

from renpy_story_mapper.narrative.segments import (
    SegmentChild,
    SegmentPartitionConfig,
    SegmentStructuralContext,
    plan_summary_segments,
)


def _context(
    *,
    chapter: str = "chapter-1",
    chronology: str = "chronology-1",
    lane: str | None = "shared",
    container: str | None = None,
    arm: str | None = None,
    occurrence: str | None = None,
    call_context: str | None = None,
    loop: str | None = None,
) -> SegmentStructuralContext:
    return SegmentStructuralContext(
        chapter_id=chapter,
        chronology_anchor_id=chronology,
        persistent_lane_id=lane,
        temporary_container_id=container,
        temporary_arm_id=arm,
        occurrence_id=occurrence,
        call_context_id=call_context,
        loop_id=loop,
    )


def _children(
    count: int,
    *,
    context: SegmentStructuralContext | None = None,
    token_count: int = 50,
    prefix: str = "scene-artifact",
) -> tuple[SegmentChild, ...]:
    owned_context = context or _context()
    return tuple(
        SegmentChild(
            artifact_id=f"{prefix}-{index}",
            chronology_index=index,
            estimated_tokens=token_count,
            context=owned_context,
        )
        for index in range(count)
    )


def _config(**changes: object) -> SegmentPartitionConfig:
    base: dict[str, object] = {"locale": "en-US", "perspective": "reader"}
    base.update(changes)
    return SegmentPartitionConfig(**base)  # type: ignore[arg-type]


def test_segment_identity_binds_order_context_partition_locale_and_perspective() -> None:
    children = _children(3)
    baseline = plan_summary_segments(children, _config()).roots[0]

    reordered_children = (
        replace(children[1], chronology_index=0),
        replace(children[0], chronology_index=1),
        children[2],
    )
    variants = (
        plan_summary_segments(reordered_children, _config()).roots[0],
        plan_summary_segments(
            tuple(replace(child, context=_context(chapter="chapter-2")) for child in children),
            _config(),
        ).roots[0],
        plan_summary_segments(children, _config(partition_version="partition-v2")).roots[0],
        plan_summary_segments(children, _config(locale="fr-FR")).roots[0],
        plan_summary_segments(children, _config(perspective="character-a")).roots[0],
    )

    assert plan_summary_segments(children, _config()).roots[0].segment_id == baseline.segment_id
    assert all(variant.segment_id != baseline.segment_id for variant in variants)


def test_count_partitioning_stays_in_approximate_range_without_tiny_tail() -> None:
    plan = plan_summary_segments(_children(50), _config(maximum_input_tokens=100_000))

    assert [len(descriptor.child_artifact_ids) for descriptor in plan.roots] == [17, 17, 16]
    assert all(
        16 <= len(descriptor.child_artifact_ids) <= 32 for descriptor in plan.roots
    )


def test_token_preflight_may_lower_fan_in_below_minimum_but_never_exceeds_limit() -> None:
    config = _config(
        maximum_input_tokens=1_256,
        prompt_overhead_tokens=256,
        estimated_segment_output_tokens=400,
    )
    plan = plan_summary_segments(_children(10, token_count=400), config)
    level_zero = tuple(descriptor for descriptor in plan.descriptors if descriptor.level == 0)

    assert [len(descriptor.child_artifact_ids) for descriptor in level_zero] == [2, 2, 2, 2, 2]
    assert all(descriptor.estimated_input_tokens <= 1_256 for descriptor in plan.descriptors)


def test_every_m11_structural_and_chronology_boundary_is_hard() -> None:
    contexts = (
        _context(chronology="shared-before"),
        _context(
            chronology="temporary-a",
            container="temporary-1",
            arm="arm-a",
        ),
        _context(
            chronology="temporary-b",
            container="temporary-1",
            arm="arm-b",
        ),
        _context(chronology="lane-a", lane="persistent-a"),
        _context(chronology="lane-b", lane="persistent-b"),
        _context(
            chronology="occurrence-a",
            occurrence="occurrence-a",
            call_context="call-a",
        ),
        _context(chronology="loop-a", loop="loop-a"),
        _context(chapter="chapter-2", chronology="chapter-2"),
    )
    children = tuple(
        SegmentChild(
            artifact_id=f"artifact-{index}",
            chronology_index=0,
            estimated_tokens=50,
            context=context,
        )
        for index, context in enumerate(contexts)
    )

    plan = plan_summary_segments(children, _config())

    assert len(plan.roots) == len(contexts)
    assert [root.context for root in plan.roots] == list(contexts)
    assert all(len(root.child_artifact_ids) == 1 for root in plan.roots)
    assert all(
        len(
            {
                descriptor.context
                for descriptor in plan.descriptors
                if child_id in descriptor.child_artifact_ids
            }
        )
        == 1
        for child_id in (child.artifact_id for child in children)
    )


def test_mutually_exclusive_persistent_lanes_and_temporary_arms_never_mix() -> None:
    lane_a = _context(chronology="lane-a", lane="lane-a")
    lane_b = _context(chronology="lane-b", lane="lane-b")
    arm_a = _context(
        chronology="arm-a", lane="shared", container="temporary", arm="arm-a"
    )
    arm_b = _context(
        chronology="arm-b", lane="shared", container="temporary", arm="arm-b"
    )
    blocks = (
        _children(20, context=lane_a, prefix="lane-a"),
        _children(20, context=lane_b, prefix="lane-b"),
        _children(20, context=arm_a, prefix="arm-a"),
        _children(20, context=arm_b, prefix="arm-b"),
    )

    plan = plan_summary_segments(tuple(child for block in blocks for child in block), _config())

    assert {root.context for root in plan.roots} == {lane_a, lane_b, arm_a, arm_b}
    for descriptor in plan.descriptors:
        prefixes = {child_id.rsplit("-", 1)[0] for child_id in descriptor.child_artifact_ids}
        if descriptor.level == 0:
            assert len(prefixes) == 1


def test_large_run_forms_deterministic_recursive_fan_in_and_linear_descriptors() -> None:
    children = _children(800, token_count=10)
    config = _config(maximum_input_tokens=100_000)

    first = plan_summary_segments(children, config)
    replay = plan_summary_segments(children, config)
    level_zero = [descriptor for descriptor in first.descriptors if descriptor.level == 0]
    level_one = [descriptor for descriptor in first.descriptors if descriptor.level == 1]

    assert first == replay
    assert len(level_zero) == 34
    assert len(level_one) == 2
    assert first.roots == tuple(level_one)
    assert all(len(descriptor.child_artifact_ids) <= 32 for descriptor in first.descriptors)
    assert len(first.descriptors) == 36
    assert len(first.descriptors) < len(children) / 10


def test_missing_children_and_transitive_coverage_are_exact_without_flattening() -> None:
    base = _children(800, token_count=10)
    missing = {"scene-artifact-2", "scene-artifact-401", "scene-artifact-799"}
    children = tuple(
        replace(child, available=False, covered_leaf_count=0)
        if child.artifact_id in missing
        else child
        for child in base
    )
    plan = plan_summary_segments(children, _config(maximum_input_tokens=100_000))
    leaves = tuple(descriptor for descriptor in plan.descriptors if descriptor.level == 0)

    assert {
        missing_id
        for descriptor in leaves
        for missing_id in descriptor.missing_child_artifact_ids
    } == missing
    assert all(
        not descriptor.missing_child_artifact_ids
        for descriptor in plan.descriptors
        if descriptor.level > 0
    )
    assert sum(root.expected_leaf_count for root in plan.roots) == 800
    assert sum(root.covered_leaf_count for root in plan.roots) == 797
    weighted_coverage = sum(
        root.coverage_percentage * root.expected_leaf_count / 100 for root in plan.roots
    )
    assert weighted_coverage == pytest.approx(797)


def test_segment_descriptors_cannot_masquerade_as_m11_scene_membership() -> None:
    descriptor = plan_summary_segments(_children(1), _config()).roots[0]
    field_names = {field.name for field in fields(descriptor)}

    assert "scene_ids" not in field_names
    assert "member_ids" not in field_names
    assert "m11_membership" not in field_names
    assert descriptor.child_artifact_ids == ("scene-artifact-0",)


def test_invalid_child_relationships_order_and_context_reentry_are_rejected() -> None:
    with pytest.raises(ValueError, match="temporary_arm_id requires"):
        _context(container=None, arm="arm-a")
    with pytest.raises(ValueError, match="call_context_id requires"):
        _context(call_context="call-a")

    context = _context()
    duplicate = _children(2, context=context)
    with pytest.raises(ValueError, match="globally unique"):
        plan_summary_segments((duplicate[0], duplicate[0]), _config())
    with pytest.raises(ValueError, match="increase strictly"):
        plan_summary_segments(
            (duplicate[0], replace(duplicate[1], chronology_index=0)), _config()
        )

    context_b = _context(chronology="context-b")
    with pytest.raises(ValueError, match="cannot reappear"):
        plan_summary_segments(
            (
                duplicate[0],
                replace(duplicate[1], context=context_b, chronology_index=0),
                SegmentChild("scene-artifact-2", 1, 10, context),
            ),
            _config(),
        )


def test_oversized_single_child_fails_token_preflight() -> None:
    with pytest.raises(ValueError, match="exceeds the segment token limit"):
        plan_summary_segments(
            _children(1, token_count=1_001),
            _config(
                maximum_input_tokens=1_256,
                prompt_overhead_tokens=256,
                estimated_segment_output_tokens=400,
            ),
        )
