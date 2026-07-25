from __future__ import annotations

import json
from dataclasses import replace

from renpy_story_mapper.canonical_graph import build_canonical_graph
from renpy_story_mapper.canonical_graph_contract import (
    CanonicalGraph,
    ReachabilityStatus,
    source_generation,
)
from renpy_story_mapper.control_flow import analyze_control_flow
from renpy_story_mapper.graph import build_graph
from renpy_story_mapper.parser import parse_script
from renpy_story_mapper.route_map import project_route_map
from renpy_story_mapper.semantic import build_semantic_story
from renpy_story_mapper.state import extract_state
from renpy_story_mapper.story_map_v2.contracts import (
    ArmLineageStep,
    ArmMechanic,
    ChoiceMechanic,
    ChunkProfile,
    Reachability,
    SourceSpan,
    StoryScope,
)
from renpy_story_mapper.story_map_v2.planner import (
    ChunkPlanningError,
    mechanics_digest,
    plan_chunks,
)
from renpy_story_mapper.story_map_v2.source_adapter import adapt_story_scope


def _authority(source: str) -> CanonicalGraph:
    module = parse_script("story/day.rpy", source.splitlines(keepends=True))
    graph = build_graph([module])
    semantic = build_semantic_story(graph)
    state = extract_state([module])
    control = analyze_control_flow(graph, semantic, state.requirements, state.effects).to_dict()
    route = project_route_map(control, semantic, state.requirements, state.effects)
    return build_canonical_graph(
        graph,
        semantic,
        control,
        route,
        state,
        source_generation=source_generation(((module.path, "1" * 64),)),
    )


def _span(
    key: str,
    start: int,
    tokens: int,
    *,
    choice_keys: tuple[str, ...] = (),
    lineage: tuple[ArmLineageStep, ...] = (),
    boundary: bool = True,
) -> SourceSpan:
    return SourceSpan(
        key=key,
        relative_path="story/day.rpy",
        start_line=start,
        end_line=start,
        raw_text=f"{start}: Story line {key}.\n",
        estimated_tokens=tokens,
        canonical_node_ids=(f"node:{key}",),
        reachability=Reachability.REACHABLE,
        choice_keys=choice_keys,
        arm_lineage=lineage,
        natural_boundary_after=boundary,
    )


def _arm(
    order: int,
    start: int,
    *,
    rejoin: str | None = "node:rejoin",
    warnings: tuple[str, ...] = (),
) -> ArmMechanic:
    return ArmMechanic(
        order=order,
        caption=f"Option {order}",
        start_line=start,
        end_line=start + 4,
        condition="ready" if order == 1 else None,
        effects=(f"route_{order} = True",),
        destination_id=f"node:arm-{order}",
        rejoin_node_id=rejoin,
        rejoin_line=40 if rejoin is not None else None,
        reachability=(Reachability.UNRESOLVED if warnings else Reachability.REACHABLE),
        unresolved_warnings=warnings,
    )


def _choice(
    key: str,
    line: int,
    *,
    rejoin: str | None = "node:rejoin",
    parent: tuple[ArmLineageStep, ...] = (),
) -> ChoiceMechanic:
    return ChoiceMechanic(
        key=key,
        relative_path="story/day.rpy",
        line=line,
        arms=(_arm(1, line + 1, rejoin=rejoin), _arm(2, line + 6, rejoin=rejoin)),
        parent_lineage=parent,
    )


def _scope(spans: tuple[SourceSpan, ...], choices: tuple[ChoiceMechanic, ...] = ()) -> StoryScope:
    return StoryScope("source", "generation", "a" * 64, spans, choices)


def test_adapter_projects_linear_source_identity_order_and_stable_keys() -> None:
    graph = _authority(
        """label start:
    "First moment."
    "Second moment."
    return
"""
    )

    first = adapt_story_scope(graph)
    second = adapt_story_scope(graph)

    assert first == second
    assert first.source_generation == graph.source_generation
    assert first.canonical_hash == graph.authority_hash
    assert first.source_identity
    assert [span.start_line for span in first.spans] == sorted(
        span.start_line for span in first.spans
    )
    assert all(span.key.startswith("span_") for span in first.spans)
    assert all(span.raw_text.startswith(f"{span.start_line}: ") for span in first.spans)


def test_adapter_projects_exact_conditional_choice_effects_and_local_rejoin() -> None:
    graph = _authority(
        """label start:
    menu:
        "Offer help" if ready:
            $ trust += 1
        "Walk away":
            $ trust -= 1
    "Together again."
    return
"""
    )

    scope = adapt_story_scope(graph, source_identity="synthetic-local-rejoin")

    assert len(scope.choices) == 1
    choice = scope.choices[0]
    assert choice.key == "story/day.rpy:2"
    assert [arm.caption for arm in choice.arms] == ["Offer help", "Walk away"]
    assert choice.arms[0].condition == "ready"
    assert choice.arms[0].effects == ("trust += 1",)
    assert choice.arms[1].effects == ("trust -= 1",)
    assert {arm.rejoin_node_id for arm in choice.arms} != {None}
    assert all(arm.destination_id is not None for arm in choice.arms)
    assert any(span.shared_continuation for span in scope.spans if choice.key in span.choice_keys)


def test_adapter_includes_conditional_descendant_effects_and_lineage_in_menu_arm() -> None:
    graph = _authority(
        """label start:
    menu:
        "Help":
            if ready:
                $ trust += 1
        "Leave":
            pass
    "Together again."
    return
"""
    )

    scope = adapt_story_scope(graph)
    choice = next(item for item in scope.choices if item.line == 2)
    help_arm = choice.arms[0]
    effect_span = next(item for item in scope.spans if "trust += 1" in item.raw_text)

    assert help_arm.effects == ("trust += 1",)
    assert effect_span.arm_lineage == (ArmLineageStep(choice.key, 1),)


def test_adapter_keeps_setup_and_conditional_hint_controls_non_story() -> None:
    for source in (
        """label start:
    menu:
        "Enable Hints":
            $ hints = True
        "Disable Hints":
            $ hints = False
    return
""",
        """label start:
    menu:
        "Enable Hints" if can_configure:
            $ hints = True
        "Leave Hints Alone":
            pass
    return
""",
    ):
        choice = adapt_story_scope(_authority(source)).choices[0]
        assert choice.story_choice is False


def test_adapter_preserves_nested_outer_to_inner_lineage() -> None:
    graph = _authority(
        """label start:
    menu:
        "Enter":
            menu:
                "Climb":
                    "High path."
                "Descend":
                    "Low path."
        "Wait":
            "Quiet path."
    "Afterward."
    return
"""
    )

    scope = adapt_story_scope(graph)
    outer = next(choice for choice in scope.choices if choice.line == 2)
    nested = next(choice for choice in scope.choices if choice.line == 4)
    nested_story = next(span for span in scope.spans if "High path" in span.raw_text)

    assert nested.parent_lineage == (ArmLineageStep(outer.key, 1),)
    assert nested_story.arm_lineage == (
        ArmLineageStep(outer.key, 1),
        ArmLineageStep(nested.key, 1),
    )


def test_adapter_keeps_persistent_terminal_arms_without_false_rejoin() -> None:
    graph = _authority(
        """label start:
    menu:
        "North":
            jump north_end
        "South":
            jump south_end

label north_end:
    "North ending."
    return

label south_end:
    "South ending."
    return
"""
    )

    choice = adapt_story_scope(graph).choices[0]

    assert all(arm.rejoin_node_id is None for arm in choice.arms)
    assert all(arm.rejoin_line is None for arm in choice.arms)


def test_adapter_marks_dynamic_conditional_arm_honestly_unresolved() -> None:
    graph = _authority(
        """label start:
    menu:
        "Attempt" if compute_gate():
            "Uncertain route."
        "Decline":
            "Known route."
    return
"""
    )

    choice = adapt_story_scope(graph).choices[0]
    uncertain = choice.arms[0]

    assert uncertain.condition == "compute_gate()"
    assert uncertain.reachability is Reachability.UNRESOLVED
    assert uncertain.unresolved_warnings


def test_adapter_aggregates_exact_spine_reachability_and_retains_warnings() -> None:
    graph = _authority(
        """label start:
    "A spine moment."
    return
"""
    )
    baseline = adapt_story_scope(graph)
    target = next(span for span in baseline.spans if span.start_line == 2)

    def projected(status: ReachabilityStatus):
        target_ids = set(target.canonical_node_ids)
        changed = replace(
            graph,
            nodes=tuple(
                replace(node, reachability=status) if node.id in target_ids else node
                for node in graph.nodes
            ),
        )
        return next(
            span
            for span in adapt_story_scope(changed).spans
            if set(span.canonical_node_ids) == target_ids
        )

    reachable = projected(ReachabilityStatus.PROVEN_REACHABLE)
    unreachable = projected(ReachabilityStatus.PROVEN_UNREACHABLE)
    unresolved = projected(ReachabilityStatus.UNRESOLVED_DYNAMIC_BEHAVIOR)

    assert reachable.reachability is Reachability.REACHABLE
    assert reachable.unresolved_warnings == ()
    assert unreachable.reachability is Reachability.UNREACHABLE
    assert unreachable.unresolved_warnings == ()
    assert unresolved.reachability is Reachability.UNRESOLVED
    assert unresolved.unresolved_warnings


def test_planner_long_linear_scope_prefers_last_boundary_below_target() -> None:
    scope = _scope(tuple(_span(f"linear-{index}", index, 2_000) for index in range(1, 7)))

    chunks = plan_chunks(scope)

    assert [chunk.raw_tokens for chunk in chunks] == [8_000, 4_000]
    assert chunks[0].span_keys == tuple(f"linear-{index}" for index in range(1, 5))
    assert chunks[0].raw_text.startswith(
        '@@SOURCE {"end_line":1,"path":"story/day.rpy","start_line":1}\n1: Story line linear-1.'
    )


def test_planner_mechanics_follow_exact_first_span_choice_order() -> None:
    outer_key = "story/day.rpy:2"
    later_key = "story/day.rpy:40"
    nested_key = "story/day.rpy:11"
    outer_step = ArmLineageStep(outer_key, 1)
    choices = (
        _choice(outer_key, 2),
        _choice(nested_key, 11, parent=(outer_step,)),
        _choice(later_key, 40),
    )
    spans = (
        _span("outer", 2, 100, choice_keys=(outer_key,)),
        _span(
            "nested",
            11,
            100,
            choice_keys=(nested_key,),
            lineage=(*choices[1].parent_lineage, ArmLineageStep(nested_key, 1)),
        ),
        _span("later", 40, 100, choice_keys=(later_key,)),
    )

    chunk = plan_chunks(_scope(spans, choices))[0]
    keys = tuple(item["key"] for item in json.loads(chunk.mechanics)["choices"])

    assert keys == chunk.choice_keys == (outer_key, nested_key, later_key)


def test_planner_keeps_full_fitting_persistent_arm_ranges_indivisible() -> None:
    key = "story/day.rpy:10"
    mechanic = _choice(key, 10, rejoin=None)
    mechanic = replace(
        mechanic,
        arms=(
            replace(mechanic.arms[0], start_line=11, end_line=30),
            replace(mechanic.arms[1], start_line=31, end_line=50),
        ),
    )
    spans = (
        _span("menu", 10, 1_000, choice_keys=(key,)),
        _span(
            "north-middle",
            20,
            4_500,
            choice_keys=(key,),
            lineage=(ArmLineageStep(key, 1),),
        ),
        _span(
            "south-middle",
            40,
            4_500,
            choice_keys=(key,),
            lineage=(ArmLineageStep(key, 2),),
        ),
    )

    chunks = plan_chunks(_scope(spans, (mechanic,)))

    assert len(chunks) == 1
    assert chunks[0].raw_tokens == 10_000
    assert chunks[0].span_keys == ("menu", "north-middle", "south-middle")


def test_planner_branch_density_uses_lower_target_and_binds_mechanics_digest() -> None:
    first_key = "story/day.rpy:10"
    second_key = "story/day.rpy:30"
    first_choice = _choice(first_key, 10, rejoin=None)
    second_choice = _choice(second_key, 30, rejoin=None)
    spans = (
        _span("opening", 1, 2_000),
        _span("menu-one", 10, 1_500, choice_keys=(first_key,)),
        _span(
            "arm-one-a",
            11,
            1_500,
            choice_keys=(first_key,),
            lineage=(ArmLineageStep(first_key, 1),),
        ),
        _span("menu-two", 30, 1_500, choice_keys=(second_key,)),
        _span(
            "arm-two-a",
            31,
            1_500,
            choice_keys=(second_key,),
            lineage=(ArmLineageStep(second_key, 1),),
        ),
        _span("closing", 50, 2_000),
    )
    scope = _scope(spans, (first_choice, second_choice))

    chunks = plan_chunks(scope)

    assert max(chunk.raw_tokens for chunk in chunks) <= ChunkProfile().branch_target_tokens
    first_packet = next(chunk for chunk in chunks if first_key in chunk.choice_keys)
    digest = mechanics_digest(scope, first_packet.choice_keys)
    assert first_packet.mechanics == digest
    assert '"caption":"Option 1"' in digest
    changed = _scope(spans, (_choice(first_key, 10), second_choice))
    changed_packet = next(chunk for chunk in plan_chunks(changed) if first_key in chunk.choice_keys)
    assert changed_packet.mechanics != first_packet.mechanics
    assert changed_packet.packet_hash != first_packet.packet_hash


def test_planner_fails_honestly_for_nested_indivisible_oversize_cluster() -> None:
    outer_key = "story/day.rpy:10"
    nested_key = "story/day.rpy:20"
    parent = (ArmLineageStep(outer_key, 1),)
    choices = (_choice(outer_key, 10), _choice(nested_key, 20, parent=parent))
    spans = (
        _span("outer", 10, 2_500, choice_keys=(outer_key,)),
        _span(
            "nested",
            20,
            8_500,
            choice_keys=(outer_key, nested_key),
            lineage=(*parent, ArmLineageStep(nested_key, 1)),
        ),
    )

    try:
        plan_chunks(_scope(spans, choices))
    except ChunkPlanningError as exc:
        assert "ceiling" in str(exc)
    else:
        raise AssertionError("oversized nested coherent cluster must fail")
