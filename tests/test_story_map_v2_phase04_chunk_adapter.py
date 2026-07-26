"""Failing-first integration coverage for A1 StoryPlan to A2 chunk planning."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, replace
import json
from pathlib import Path

import pytest

from renpy_story_mapper.canonical_graph import build_canonical_graph
from renpy_story_mapper.canonical_graph_contract import CanonicalGraph, source_generation
from renpy_story_mapper.control_flow import analyze_control_flow
from renpy_story_mapper.graph import build_graph
from renpy_story_mapper.m11_scene_projection import build_scene_model
from renpy_story_mapper.parser import parse_script
from renpy_story_mapper.route_map import project_route_map
from renpy_story_mapper.semantic import build_semantic_story
from renpy_story_mapper.state import extract_state
from renpy_story_mapper.story_map_v2.contracts import canonical_hash, canonical_json
from renpy_story_mapper.story_map_v2.phase04_chunk_adapter import (
    ChunkPlanningAdaptationError,
    adapt_chunk_planning_projection,
    atomic_group_identity,
)
from renpy_story_mapper.story_map_v2.phase04_chunk_plan import plan_story_chunks
from renpy_story_mapper.story_map_v2.phase04_chunk_plan import (
    FrozenPlanMismatch,
    deserialize_story_chunk_plan,
    serialize_chunk_request,
    serialize_story_chunk_plan,
)
from renpy_story_mapper.story_map_v2.source_adapter import adapt_story_scope
from renpy_story_mapper.story_map_v2.story_plan import (
    StoryPlacement,
    StoryPlan,
    build_story_plan,
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


def _planned():  # type: ignore[no-untyped-def]
    graph = _authority()
    scene_model = build_scene_model(graph)
    source = adapt_story_scope(
        graph,
        scene_model=scene_model,
        source_identity="phase04-public-occurrence-plan",
    )
    story_plan = build_story_plan(graph, scene_model=scene_model, source_scope=source)
    return source, story_plan


def _expected_placement_ids(plan: StoryPlan) -> tuple[str, ...]:
    return tuple(
        placement_id
        for scope in plan.scopes
        for placement_id in scope.placement_ids
    )


def test_adapter_freezes_exact_a1_placements_groups_scopes_and_mechanics() -> None:
    source, story_plan = _planned()

    projection = adapt_chunk_planning_projection(story_plan, source)
    chunk_plan = plan_story_chunks(projection)

    expected_placement_ids = _expected_placement_ids(story_plan)
    assert projection.story_plan_identity == story_plan.identity
    assert tuple(
        placement.placement_id
        for scope in projection.scopes
        for placement in scope.placements
    ) == expected_placement_ids
    assert chunk_plan.covered_placement_ids == expected_placement_ids
    assert len(chunk_plan.covered_placement_ids) == len(
        set(chunk_plan.covered_placement_ids)
    )
    assert tuple(binding.scope_id for binding in chunk_plan.scope_bindings) == tuple(
        scope.id for scope in story_plan.scopes
    )
    assert tuple(binding.parent_scope_id for binding in chunk_plan.scope_bindings) == tuple(
        scope.parent_scope_id for scope in story_plan.scopes
    )
    assert tuple(binding.lane_id for binding in chunk_plan.scope_bindings) == tuple(
        scope.lane_id for scope in story_plan.scopes
    )
    assert tuple(binding.lane_kind for binding in chunk_plan.scope_bindings) == tuple(
        scope.lane_kind.value for scope in story_plan.scopes
    )

    source_spans = {span.key: span for span in source.spans}
    story_placements = {placement.id: placement for placement in story_plan.placements}
    for scope in projection.scopes:
        current_group_key: (
            tuple[str, str, tuple[str, ...], tuple[tuple[str, int], ...]] | None
        ) = None
        group_ordinal = 0
        for placement in scope.placements:
            authority = story_placements[placement.placement_id]
            span = source_spans[authority.span_key]
            group_key = (
                authority.scene_id,
                authority.context_scene_id,
                authority.occurrence_path,
                tuple(
                    (step.choice_key, step.arm_order)
                    for step in authority.arm_lineage
                ),
            )
            if group_key != current_group_key:
                group_ordinal += 1
                current_group_key = group_key
            assert placement.raw_text == span.raw_text
            assert placement.raw_tokens == span.estimated_tokens
            assert placement.atomic_group_id == atomic_group_identity(
                authority,
                group_ordinal,
            )

    grouped: dict[str, list[str]] = defaultdict(list)
    for scope in projection.scopes:
        for placement in scope.placements:
            grouped[placement.atomic_group_id].append(placement.placement_id)
    assert tuple(
        placement_id
        for group in chunk_plan.atomic_groups
        for placement_id in group.placement_ids
    ) == expected_placement_ids
    assert {group.id: list(group.placement_ids) for group in chunk_plan.atomic_groups} == grouped

    span_counts = Counter(placement.span_key for placement in story_plan.placements)
    shared_span_key = next(key for key, count in span_counts.items() if count > 1)
    shared = tuple(
        placement
        for placement in story_plan.placements
        if placement.span_key == shared_span_key
    )
    adapted_group_by_id = {
        placement.placement_id: placement.atomic_group_id
        for scope in projection.scopes
        for placement in scope.placements
    }
    assert len({adapted_group_by_id[placement.id] for placement in shared}) == len(shared)

    source_choices = {choice.key: choice for choice in source.choices}
    assert {
        parent.choice_key: parent.canonical_mechanics
        for parent in chunk_plan.choice_parents
    } == {
        key: canonical_json(asdict(choice)).decode("utf-8")
        for key, choice in source_choices.items()
    }
    boundary_kinds = {
        boundary.boundary_kind
        for scope in projection.scopes
        for placement in scope.placements
        for boundary in placement.choice_arms
    }
    assert boundary_kinds == {"local", "nested", "persistent"}
    structural_flags = {
        flag
        for scope in projection.scopes
        for placement in scope.placements
        for flag in placement.structural_flags
    }
    assert {"persistent_lane", "loop", "terminal", "unresolved"} <= structural_flags


def test_adapter_fails_closed_on_missing_extra_or_drifted_exact_spans() -> None:
    source, story_plan = _planned()

    with pytest.raises(ChunkPlanningAdaptationError, match="missing or extra"):
        adapt_chunk_planning_projection(
            story_plan,
            replace(source, spans=source.spans[:-1]),
        )

    extra = replace(source.spans[-1], key="span_public_synthetic_extra")
    with pytest.raises(ChunkPlanningAdaptationError, match="missing or extra"):
        adapt_chunk_planning_projection(
            story_plan,
            replace(source, spans=(*source.spans, extra)),
        )

    drifted = replace(source.spans[0], raw_text=source.spans[0].raw_text + "1: drift\n")
    with pytest.raises(ChunkPlanningAdaptationError, match="identity has drifted"):
        adapt_chunk_planning_projection(
            story_plan,
            replace(source, spans=(drifted, *source.spans[1:])),
        )

    with pytest.raises(ChunkPlanningAdaptationError, match="source identity"):
        adapt_chunk_planning_projection(
            story_plan,
            replace(source, source_identity="different-public-source"),
        )


def test_oversized_multispan_atomic_group_uses_whole_group_structural_fallback() -> None:
    source, story_plan = _planned()
    placement_span_counts = Counter(
        placement.span_key for placement in story_plan.placements
    )
    grouped: list[tuple[StoryPlacement, ...]] = []
    for scope in story_plan.scopes:
        current: list[StoryPlacement] = []
        current_key: tuple[str, str, tuple[str, ...]] | None = None
        placements_by_id = {item.id: item for item in story_plan.placements}
        for placement_id in scope.placement_ids:
            placement = placements_by_id[placement_id]
            key = (
                placement.scene_id,
                placement.context_scene_id,
                placement.occurrence_path,
            )
            if current and key != current_key:
                grouped.append(tuple(current))
                current = []
            current.append(placement)
            current_key = key
        if current:
            grouped.append(tuple(current))
    target = next(
        items
        for items in grouped
        if len(items) >= 2
        and all(placement_span_counts[item.span_key] == 1 for item in items)
    )
    target_span_keys = {item.span_key for item in target}
    oversized_spans = tuple(
        replace(span, estimated_tokens=6_000)
        if span.key in target_span_keys
        else span
        for span in source.spans
    )
    oversized_source = replace(source, spans=oversized_spans)
    exact_plan = replace(
        story_plan,
        source_scope_identity=canonical_hash(asdict(oversized_source)),
    )

    projection = adapt_chunk_planning_projection(exact_plan, oversized_source)
    chunk_plan = plan_story_chunks(projection)

    target_ids = tuple(item.id for item in target)
    target_group_id = next(
        placement.atomic_group_id
        for scope in projection.scopes
        for placement in scope.placements
        if placement.placement_id == target_ids[0]
    )
    frozen_group = next(group for group in chunk_plan.atomic_groups if group.id == target_group_id)
    assert frozen_group.placement_ids == target_ids
    assert all(
        placement.raw_tokens < chunk_plan.maximum_request_tokens
        for scope in projection.scopes
        for placement in scope.placements
        if placement.placement_id in set(target_ids)
    )
    assert sum(
        placement.raw_tokens
        for scope in projection.scopes
        for placement in scope.placements
        if placement.placement_id in set(target_ids)
    ) > chunk_plan.maximum_request_tokens

    containing = tuple(
        chunk
        for chunk in chunk_plan.chunks
        if target_group_id in chunk.atomic_group_ids
    )
    assert len(containing) == 1
    fallback = containing[0]
    assert fallback.structural_fallback_only
    assert fallback.structural_fallback_reason == (
        "atomic_scene_request_exceeds_hard_ceiling"
    )
    assert fallback.atomic_group_ids == (target_group_id,)
    assert fallback.placement_ids == target_ids


def test_same_scene_local_arm_runs_split_before_safe_material_can_fallback() -> None:
    source, story_plan = _planned()
    placements_by_id = {item.id: item for item in story_plan.placements}
    scene_runs: list[tuple[StoryPlacement, ...]] = []
    for scope in story_plan.scopes:
        current: list[StoryPlacement] = []
        current_key: tuple[str, str, tuple[str, ...]] | None = None
        for placement_id in scope.placement_ids:
            placement = placements_by_id[placement_id]
            key = (
                placement.scene_id,
                placement.context_scene_id,
                placement.occurrence_path,
            )
            if current and key != current_key:
                scene_runs.append(tuple(current))
                current = []
            current.append(placement)
            current_key = key
        if current:
            scene_runs.append(tuple(current))
    target = next(
        run
        for run in scene_runs
        if len(run) == 4
        and len({item.arm_lineage for item in run}) == 2
        and all(item.arm_lineage for item in run)
    )
    target_span_keys = {item.span_key for item in target}
    oversized_source = replace(
        source,
        spans=tuple(
            replace(span, estimated_tokens=3_000)
            if span.key in target_span_keys
            else span
            for span in source.spans
        ),
    )
    exact_plan = replace(
        story_plan,
        source_scope_identity=canonical_hash(asdict(oversized_source)),
    )

    projection = adapt_chunk_planning_projection(exact_plan, oversized_source)
    chunk_plan = plan_story_chunks(projection)
    target_ids = tuple(item.id for item in target)
    adapted = tuple(
        placement
        for scope in projection.scopes
        for placement in scope.placements
        if placement.placement_id in set(target_ids)
    )
    target_group_ids = tuple(dict.fromkeys(item.atomic_group_id for item in adapted))

    assert len(target_group_ids) == 2
    assert [
        tuple(
            placement.placement_id
            for placement in adapted
            if placement.atomic_group_id == group_id
        )
        for group_id in target_group_ids
    ] == [target_ids[:2], target_ids[2:]]
    assert all(
        sum(item.raw_tokens for item in adapted if item.atomic_group_id == group_id)
        < chunk_plan.maximum_request_tokens
        for group_id in target_group_ids
    )
    target_chunks = tuple(
        chunk
        for chunk in chunk_plan.chunks
        if set(chunk.atomic_group_ids) & set(target_group_ids)
    )
    assert target_chunks
    assert all(not chunk.structural_fallback_only for chunk in target_chunks)
    assert tuple(
        placement_id
        for chunk in target_chunks
        for placement_id in chunk.placement_ids
    ) == target_ids
    assert chunk_plan.covered_placement_ids == _expected_placement_ids(exact_plan)

    choice_key = target[-1].arm_lineage[-1].choice_key
    frozen_parents = tuple(
        parent for parent in chunk_plan.choice_parents if parent.choice_key == choice_key
    )
    assert len(frozen_parents) == 1
    source_choice = next(choice for choice in oversized_source.choices if choice.key == choice_key)
    assert frozen_parents[0].canonical_mechanics == canonical_json(
        asdict(source_choice)
    ).decode("utf-8")


def test_atomic_group_drift_fails_closed_on_deserialize_and_request_rebuild() -> None:
    source, story_plan = _planned()
    projection = adapt_chunk_planning_projection(story_plan, source)
    chunk_plan = plan_story_chunks(projection)
    payload = json.loads(serialize_story_chunk_plan(chunk_plan))
    group_a = next(group for group in payload["atomic_groups"] if len(group["placement_ids"]) > 1)
    group_a_index = payload["atomic_groups"].index(group_a)
    group_b = payload["atomic_groups"][group_a_index + 1]
    moved_id = group_a["placement_ids"].pop()
    group_b["placement_ids"].insert(0, moved_id)
    with pytest.raises(ValueError, match="StoryChunkPlan identity"):
        deserialize_story_chunk_plan(
            json.dumps(payload, sort_keys=True, separators=(",", ":"))
        )

    frozen_groups = {group.id: group for group in chunk_plan.atomic_groups}
    chunk = next(
        item
        for item in chunk_plan.chunks
        if not item.structural_fallback_only
        and len(item.atomic_group_ids) > 1
        and len(frozen_groups[item.atomic_group_ids[0]].placement_ids) > 1
    )
    first_group = frozen_groups[chunk.atomic_group_ids[0]]
    second_group_id = chunk.atomic_group_ids[1]
    drifted_placement_id = first_group.placement_ids[-1]
    drifted_projection = replace(
        projection,
        scopes=tuple(
            replace(
                scope,
                placements=tuple(
                    replace(placement, atomic_group_id=second_group_id)
                    if placement.placement_id == drifted_placement_id
                    else placement
                    for placement in scope.placements
                ),
            )
            for scope in projection.scopes
        ),
    )
    with pytest.raises(FrozenPlanMismatch, match="atomic group membership"):
        serialize_chunk_request(chunk_plan, chunk.chunk_id, drifted_projection)
