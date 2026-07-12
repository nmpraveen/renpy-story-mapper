from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any

import pytest

from renpy_story_mapper.ui.story_layout import (
    ABSOLUTE_RENDERED_ITEM_LIMIT,
    DEFAULT_CARD_LIMIT,
    LayoutConfig,
    LayoutEdge,
    LayoutInput,
    LayoutNode,
    LayoutResult,
    Rect,
    layout_story_events,
    semantic_style,
)

FIXTURES = Path(__file__).parent / "fixtures" / "m05" / "layout"


def _representative() -> LayoutInput:
    payload = json.loads((FIXTURES / "representative_graphs.json").read_text(encoding="utf-8"))
    return LayoutInput(
        tuple(LayoutNode(**node) for node in payload["nodes"]),
        tuple(LayoutEdge(**edge) for edge in payload["edges"]),
    )


def _generated(case_name: str) -> LayoutInput:
    cases: dict[str, Any] = json.loads(
        (FIXTURES / "bounded_generators.json").read_text(encoding="utf-8")
    )
    case = cases[case_name]
    node_count = int(case["node_count"])
    edge_count = int(case["edge_count"])
    nodes = tuple(LayoutNode(f"safety-{index:03}", index) for index in range(node_count))
    edges = [
        LayoutEdge(
            f"safety-edge-{index:03}",
            f"safety-{index:03}",
            f"safety-{index + 1:03}",
            "flow",
            order=index,
        )
        for index in range(min(node_count - 1, edge_count))
    ]
    if len(edges) < edge_count:
        edges.append(
            LayoutEdge(
                "safety-unresolved-return",
                f"safety-{node_count - 1:03}",
                "safety-000",
                "dynamic",
                authoritative=False,
                order=edge_count,
            )
        )
    return LayoutInput(nodes, tuple(edges))


def _cards(result: LayoutResult) -> dict[str, Any]:
    return {card.id: card for card in result.cards}


def _edges(result: LayoutResult) -> dict[str, Any]:
    return {edge.id: edge for edge in result.edges}


def _overlap(left: Rect, right: Rect) -> bool:
    return not (
        left.x + left.width <= right.x
        or right.x + right.width <= left.x
        or left.y + left.height <= right.y
        or right.y + right.height <= left.y
    )


def test_scc_collapse_ranks_cycles_self_loops_and_disconnected_components() -> None:
    result = layout_story_events(_representative())
    cards = _cards(result)

    assert cards["linear-01"].rank < cards["linear-02"].rank
    assert cards["loop-a"].rank == cards["loop-b"].rank
    assert cards["loop-a"].component == cards["loop-b"].component
    assert cards["disconnected"].rank == 0
    assert len(result.cards) == 20
    assert len(result.edges) == 19


def test_chronological_and_permutation_stability_with_explicit_tie_breakers() -> None:
    fixture = _representative()
    expected = layout_story_events(fixture)
    permuted = LayoutInput(tuple(reversed(fixture.nodes)), tuple(reversed(fixture.edges)))
    actual = layout_story_events(permuted)

    assert actual.canonical_json() == expected.canonical_json()
    assert actual.digest() == expected.digest()
    assert _cards(expected)["diamond-start"].rank < _cards(expected)["diamond-left"].rank


def test_choice_and_nested_choice_branches_have_distinct_lanes_and_routes() -> None:
    result = layout_story_events(_representative())
    cards = _cards(result)
    edges = _edges(result)

    assert cards["diamond-left"].lane != cards["diamond-right"].lane
    assert cards["nested-a"].lane != cards["nested-b"].lane
    assert cards["nested-a1"].lane != cards["nested-a2"].lane
    assert edges["diamond-choice-a"].points != edges["diamond-choice-b"].points
    assert edges["diamond-choice-a"].style.glyph == "fork"
    assert edges["diamond-choice-a"].style.label == "Choice"


def test_semantic_styles_use_palette_roles_and_non_color_signals() -> None:
    styles = {name: semantic_style(name) for name in (
        "flow", "choice", "requirement", "effect", "unresolved", "merge", "call",
        "return", "loop", "ending",
    )}

    assert styles["flow"].role == "flow"
    assert styles["choice"].role == "choice"
    assert styles["requirement"].role == "requirement"
    assert styles["effect"].role == "effect"
    assert styles["unresolved"].role == "unresolved"
    assert styles["merge"].glyph == "merge" and styles["merge"].line_pattern == "double"
    assert styles["call"].glyph == "call" and styles["call"].line_pattern == "dashed"
    assert styles["return"].glyph == "return" and styles["return"].line_pattern == "dotted"
    assert styles["loop"].glyph == "loop"
    assert styles["ending"].glyph == "stop" and styles["ending"].label == "Ending"
    assert all(style.glyph and style.label and style.line_pattern for style in styles.values())

    result_edges = _edges(layout_story_events(_representative()))
    assert result_edges["diamond-merge-a"].kind == "merge"
    assert result_edges["loop-back"].kind == "loop"
    assert result_edges["self-loop"].kind == "loop"
    assert result_edges["ending-edge"].kind == "ending"
    assert result_edges["dynamic-edge"].kind == "unresolved"


def test_cards_never_overlap_and_loop_routes_leave_card_bounds() -> None:
    result = layout_story_events(_representative())
    cards = list(result.cards)
    for index, card in enumerate(cards):
        for other in cards[index + 1 :]:
            assert not _overlap(card.bounds, other.bounds)

    loop = _edges(result)["self-loop"]
    source = _cards(result)["loop-a"].bounds
    assert min(point.y for point in loop.points) < source.y
    assert all(
        0 <= point.x <= result.width and 0 <= point.y <= result.height
        for edge in result.edges
        for point in edge.points
    )


def test_default_card_bound_and_absolute_rendered_item_cap() -> None:
    default_case = layout_story_events(_generated("default_card_case"))
    assert DEFAULT_CARD_LIMIT == 30
    assert len(default_case.cards) == 30
    assert default_case.omitted_cards == 6
    assert default_case.truncated

    safety_input = _generated("safety_case")
    safety = layout_story_events(
        safety_input,
        LayoutConfig(max_cards=120, max_rendered_items=ABSOLUTE_RENDERED_ITEM_LIMIT),
    )
    assert len(safety.cards) + len(safety.edges) == 240
    assert not safety.truncated
    with pytest.raises(ValueError, match="between 1 and 240"):
        LayoutConfig(max_cards=241)
    with pytest.raises(ValueError, match="between 1 and 240"):
        LayoutConfig(max_rendered_items=241)


def test_geometry_is_readable_and_scales_exactly_at_100_and_200_percent() -> None:
    fixture = _representative()
    normal = layout_story_events(fixture, LayoutConfig(zoom=1.0))
    doubled = layout_story_events(fixture, LayoutConfig(zoom=2.0))
    normal_cards = _cards(normal)
    doubled_cards = _cards(doubled)

    assert normal.width > 0 and normal.height > 0
    assert doubled.width == normal.width * 2
    assert doubled.height == normal.height * 2
    for node_id, card in normal_cards.items():
        scaled = doubled_cards[node_id]
        assert scaled.bounds.width == card.bounds.width * 2
        assert scaled.bounds.height == card.bounds.height * 2
        assert scaled.bounds.x == card.bounds.x * 2
        assert scaled.bounds.y == card.bounds.y * 2
    with pytest.raises(ValueError, match=r"between 1\.0 and 2\.0"):
        LayoutConfig(zoom=2.01)


def test_serialized_output_hash_is_stable() -> None:
    result = layout_story_events(_representative())
    assert result.digest() == "369cf3be135d2b7a0aa45c8b4baaee9bf0b789123ab8e87c187e25898896d256"
    assert result.canonical_json().isascii()


def test_240_item_fixture_performance_regression_bound() -> None:
    fixture = _generated("safety_case")
    config = LayoutConfig(max_cards=120, max_rendered_items=240)
    started = perf_counter()
    results = [layout_story_events(fixture, config) for _ in range(5)]
    elapsed = perf_counter() - started

    assert elapsed < 1.0
    assert len({result.digest() for result in results}) == 1
    assert all(len(result.cards) + len(result.edges) == 240 for result in results)
