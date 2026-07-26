from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from renpy_story_mapper.canonical_graph import build_canonical_graph
from renpy_story_mapper.canonical_graph_contract import CanonicalGraph, source_generation
from renpy_story_mapper.control_flow import analyze_control_flow
from renpy_story_mapper.graph import build_graph
from renpy_story_mapper.m11_scene_model import LaneKind
from renpy_story_mapper.m11_scene_projection import build_scene_model
from renpy_story_mapper.parser import parse_script
from renpy_story_mapper.route_map import project_route_map
from renpy_story_mapper.semantic import build_semantic_story
from renpy_story_mapper.state import extract_state
from renpy_story_mapper.story_map_v2.contracts import canonical_json
from renpy_story_mapper.story_map_v2.source_adapter import (
    SourceAdaptationError,
    adapt_story_scope,
)
from renpy_story_mapper.story_map_v2.story_plan import (
    PlacementRole,
    StoryScopeKind,
    build_story_plan,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "story_map_v2"
    / "phase04_occurrence_plan.rpy"
)
OUT_OF_DEFINITION_ORDER = (
    Path(__file__).parent / "fixtures" / "m11" / "out_of_definition_order.rpy"
)


def _authority(
    fixture: Path = FIXTURE,
    relative_path: str = "game/phase04_occurrence_plan.rpy",
) -> CanonicalGraph:
    module = parse_script(
        relative_path,
        fixture.read_text(encoding="utf-8").splitlines(keepends=True),
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
    plan = build_story_plan(graph, scene_model=scene_model, source_scope=source)
    by_key = {span.key: span for span in source.spans}
    return graph, scene_model, source, plan, by_key


def _placements_with(plan, by_key, text: str):  # type: ignore[no-untyped-def]
    return tuple(
        placement
        for placement in plan.placements
        if text in by_key[placement.span_key].raw_text
    )


def test_plan_is_m11_first_and_shared_callee_occurrences_are_distinct() -> None:
    _graph, scene_model, source, first, by_key = _planned()
    second = build_story_plan(
        _graph,
        scene_model=scene_model,
        source_scope=source,
    )

    opening = _placements_with(first, by_key, "story begins after physically earlier")[0]
    ending = _placements_with(first, by_key, "ending is defined before")[0]
    shared = _placements_with(first, by_key, "same memory is visited")

    assert first == second
    assert first.identity == second.identity
    assert first.canonical_hash == _graph.authority_hash
    assert first.scene_model_hash == scene_model.structural_hash
    assert opening.start_line > ending.start_line
    assert first.placements.index(opening) < first.placements.index(ending)
    assert len(shared) == 2
    assert len({item.occurrence_path for item in shared}) == 2
    assert len({item.id for item in shared}) == 2
    assert len({item.anchor_id for item in shared}) == 2
    assert len({item.coverage_identity for item in shared}) == 2
    assert len({item.span_key for item in shared}) == 1
    assert all(item.role is PlacementRole.CALL_OCCURRENCE for item in shared)


def test_same_lane_narrative_order_precedes_reversed_physical_definition_order() -> None:
    graph = _authority(OUT_OF_DEFINITION_ORDER, "game/out_of_definition_order.rpy")
    scene_model = build_scene_model(graph)
    source = adapt_story_scope(graph, scene_model=scene_model)
    plan = build_story_plan(graph, scene_model=scene_model, source_scope=source)
    by_key = {span.key: span for span in source.spans}

    story_lines = [
        placement.start_line
        for placement in plan.placements
        if any(
            text in by_key[placement.span_key].raw_text
            for text in ('"Start."', '"Later."', '"Ending."')
        )
    ]

    assert story_lines == [3, 13, 8]


def test_persistent_lanes_are_child_scopes_and_never_flatten_into_the_spine() -> None:
    _graph, scene_model, _source, plan, by_key = _planned()
    scope_by_id = {scope.id: scope for scope in plan.scopes}
    placement_by_id = {placement.id: placement for placement in plan.placements}
    lane_by_id = {lane.id: lane for lane in scene_model.lanes}

    persistent = tuple(
        scope for scope in plan.scopes if scope.kind is StoryScopeKind.PERSISTENT_LANE
    )
    assert persistent
    assert all(scope.parent_scope_id in scope_by_id for scope in persistent)
    assert all(scope.split_anchor_id for scope in persistent)
    assert all(
        lane_by_id[scope.lane_id].kind
        in {LaneKind.PERSISTENT_ROUTE, LaneKind.TERMINAL_SPLIT}
        for scope in persistent
    )

    red = _placements_with(plan, by_key, "red route owns its second child scene")[0]
    red_scope = scope_by_id[red.scope_id]
    parent = scope_by_id[red_scope.parent_scope_id or ""]
    assert red_scope.kind is StoryScopeKind.PERSISTENT_LANE
    assert red.id in red_scope.placement_ids
    assert red.id not in parent.placement_ids
    assert all(placement_by_id[item].scope_id == red_scope.id for item in red_scope.placement_ids)


def test_choice_context_loops_endings_and_unresolved_placements_remain_explicit() -> None:
    _graph, _scene_model, source, plan, by_key = _planned()
    unresolved = _placements_with(plan, by_key, "unresolved nested route")[0]
    known = _placements_with(plan, by_key, "known nested route")[0]
    ending = _placements_with(plan, by_key, "ending is defined before")[0]
    repeatable = _placements_with(plan, by_key, "repeatable stop is represented once")[0]

    assert len(known.arm_lineage) == 2
    assert len(unresolved.arm_lineage) == 2
    assert unresolved.choice_keys == tuple(
        step.choice_key for step in unresolved.arm_lineage
    )
    assert unresolved.unresolved_node_ids
    assert ending.terminal_node_ids
    assert repeatable.loop_id is not None
    assert len(plan.loops) == 1
    loop = plan.loops[0]
    assert loop.id == repeatable.loop_id
    assert loop.repeatable is True
    assert loop.placement_ids
    assert len(loop.placement_ids) == len(set(loop.placement_ids))

    nested_choice = next(
        item for item in source.choices if item.key == unresolved.choice_keys[-1]
    )
    assert nested_choice.parent_lineage
    assert nested_choice.key in unresolved.choice_keys
    assert any(arm.unresolved_warnings for arm in nested_choice.arms)


def test_choice_parent_lineage_never_contains_the_choice_itself() -> None:
    _graph, _scene_model, source, plan, _by_key = _planned()
    loop_choice = next(choice for choice in source.choices if choice.line == 54)

    assert loop_choice.parent_lineage == ()
    assert all(
        len({step.choice_key for step in choice.parent_lineage})
        == len(choice.parent_lineage)
        and all(step.choice_key != choice.key for step in choice.parent_lineage)
        for choice in source.choices
    )

    nested_placement = next(
        placement for placement in plan.placements if len(placement.arm_lineage) == 2
    )
    assert len({step.choice_key for step in nested_placement.arm_lineage}) == 2
    plan.validate()


def test_plan_rejects_duplicate_or_self_choice_keys_in_placement_lineage() -> None:
    _graph, _scene_model, _source, plan, _by_key = _planned()
    target = next(placement for placement in plan.placements if placement.arm_lineage)
    forged = replace(
        target,
        arm_lineage=(*target.arm_lineage, target.arm_lineage[-1]),
    )

    with pytest.raises(ValueError, match="repeats a choice in its arm lineage"):
        replace(
            plan,
            placements=tuple(
                forged if placement.id == target.id else placement
                for placement in plan.placements
            ),
        ).validate()


def test_plan_coverage_has_no_omission_or_accidental_duplication() -> None:
    _graph, _scene_model, source, plan, _by_key = _planned()

    plan.validate()
    assert set(plan.source_span_keys) == {span.key for span in source.spans}
    assert {placement.span_key for placement in plan.placements} == set(plan.source_span_keys)
    assert len({placement.id for placement in plan.placements}) == len(plan.placements)
    assert len({placement.anchor_id for placement in plan.placements}) == len(plan.placements)
    assert len({placement.coverage_identity for placement in plan.placements}) == len(
        plan.placements
    )
    assert sorted(
        placement_id for scope in plan.scopes for placement_id in scope.placement_ids
    ) == sorted(placement.id for placement in plan.placements)
    assert plan.source_coverage_identity
    assert plan.placement_coverage_identity
    assert (len(plan.scopes), len(plan.placements), len(plan.loops)) == (3, 56, 1)
    assert plan.source_scope_identity == (
        "a15df52d62844ea6ebdfb2c70430ed0304fbd94d474fea7f233188c127762f60"
    )
    assert plan.source_coverage_identity == (
        "956f18b5d4876f94ec8da49ca71e24b104fff6f9cc9a20cb22dee53879433ef6"
    )
    assert plan.placement_coverage_identity == (
        "6ace0b703271448342277ef83b2e0649c3d6de09c3d8fe47d749690f9a4f8297"
    )
    assert plan.identity == (
        "c42dda548dfaf32a1fdf459e344e63f0b4a7e78fb311956b641d56fde8046ad3"
    )
    normalized = canonical_json(plan.normalized_dict())
    assert b"The story begins" not in normalized
    assert str(FIXTURE.parent).encode() not in normalized


def test_plan_rejects_stale_bindings_and_mutated_coverage() -> None:
    graph, scene_model, source, plan, _by_key = _planned()

    with pytest.raises(SourceAdaptationError, match="StoryScope does not match"):
        build_story_plan(
            graph,
            scene_model=scene_model,
            source_scope=replace(source, canonical_hash="f" * 64),
        )
    with pytest.raises(SourceAdaptationError, match="M11 scene binding does not match"):
        build_story_plan(
            graph,
            scene_model=replace(
                scene_model,
                binding=replace(scene_model.binding, canonical_hash="f" * 64),
            ),
            source_scope=source,
        )
    with pytest.raises(ValueError, match="invalid placement"):
        replace(
            plan,
            placements=plan.placements[:-1],
            placement_coverage_identity="stale",
        ).validate()


def test_plan_rejects_caller_mutated_story_scope_content() -> None:
    graph, scene_model, source, _plan, _by_key = _planned()
    first_span = source.spans[0]
    first_choice = source.choices[0]
    first_arm = first_choice.arms[0]
    forged_scopes = (
        replace(
            source,
            spans=(
                replace(first_span, raw_text=f'{first_span.raw_text}\n"forged"\n'),
                *source.spans[1:],
            ),
        ),
        replace(
            source,
            spans=(
                replace(first_span, estimated_tokens=first_span.estimated_tokens + 1),
                *source.spans[1:],
            ),
        ),
        replace(
            source,
            choices=(
                replace(
                    first_choice,
                    arms=(
                        replace(first_arm, caption=f"{first_arm.caption} (forged)"),
                        *first_choice.arms[1:],
                    ),
                ),
                *source.choices[1:],
            ),
        ),
    )

    for forged_scope in forged_scopes:
        with pytest.raises(
            SourceAdaptationError,
            match="exact graph-derived StoryScope",
        ):
            build_story_plan(
                graph,
                scene_model=scene_model,
                source_scope=forged_scope,
            )
