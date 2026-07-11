from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from renpy_story_mapper.ui.graph_canvas import (
    GraphCanvas,
    GraphEdgeSpec,
    GraphNodeSpec,
    SemanticLevel,
    SourceEvidence,
    elide_visible_text,
    semantic_level_for_scale,
    visual_style_for,
)

FIXTURE = Path(__file__).parent / "fixtures" / "m04" / "canvas" / "bounded_slice.json"


@pytest.fixture(scope="session")
def app() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def _node(node_id: str, kind: str = "story", **kwargs: Any) -> GraphNodeSpec:
    return GraphNodeSpec(id=node_id, kind=kind, title=f"Node {node_id}", **kwargs)


def _fixture_slice() -> tuple[list[GraphNodeSpec], list[GraphEdgeSpec]]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    nodes = [
        GraphNodeSpec(
            id=record["id"],
            kind=record["kind"],
            title=record["title"],
            semantic_levels=frozenset(SemanticLevel(value) for value in record["levels"]),
        )
        for record in data["nodes"]
    ]
    edges = [GraphEdgeSpec(**record) for record in data["edges"]]
    return nodes, edges


def test_semantic_thresholds_and_true_projection_visibility(app: QApplication) -> None:
    assert semantic_level_for_scale(0.64) is SemanticLevel.OVERVIEW
    assert semantic_level_for_scale(0.65) is SemanticLevel.EVENTS
    assert semantic_level_for_scale(1.34) is SemanticLevel.EVENTS
    assert semantic_level_for_scale(1.35) is SemanticLevel.EVIDENCE

    canvas = GraphCanvas()
    nodes, edges = _fixture_slice()
    canvas.set_slice(nodes, edges)
    canvas.set_semantic_level(SemanticLevel.OVERVIEW)
    visible_overview = [
        item.spec.id
        for item in canvas.scene().items()
        if hasattr(item, "spec") and item.isVisible()
    ]
    assert visible_overview == ["arc"]
    canvas.set_semantic_level(SemanticLevel.EVIDENCE)
    visible = {
        item.spec.id
        for item in canvas.scene().items()
        if hasattr(item, "spec")
        and item.isVisible()
        and isinstance(item.spec, GraphNodeSpec)
    }
    assert visible == {"arc", "choice", "gate", "evidence"}


def test_elided_visible_text_is_ascii_and_contains_no_mojibake() -> None:
    visible = elide_visible_text("A deliberately long story title", 12)
    assert visible == "A deliber..."
    assert visible.isascii()


def test_hard_bound_stops_consuming_and_materializing(app: QApplication) -> None:
    consumed = 0

    def endless_nodes() -> Iterator[GraphNodeSpec]:
        nonlocal consumed
        index = 0
        while True:
            consumed += 1
            yield _node(f"node-{index:04}")
            index += 1

    canvas = GraphCanvas(max_rendered_items=7)
    limits: list[int] = []
    canvas.render_limit_reached.connect(limits.append)
    canvas.set_slice(endless_nodes(), ())
    assert consumed == 8
    assert canvas.rendered_item_count == 7
    assert len(canvas.scene().items()) == 7
    assert limits == [7]


def test_expansion_requests_are_independent_and_bounded(app: QApplication) -> None:
    canvas = GraphCanvas()
    canvas.set_slice(
        [
            _node("arc-a", "container", expandable=True),
            _node("arc-b", "container", expandable=True),
        ],
        [],
    )
    requests: list[tuple[str, bool]] = []
    canvas.expansion_requested.connect(
        lambda node_id, expanded: requests.append((node_id, expanded))
    )
    canvas.request_expansion("arc-b", True)
    canvas.request_expansion("arc-a", False)
    assert requests == [("arc-b", True), ("arc-a", False)]
    assert canvas.rendered_node_ids == ("arc-a", "arc-b")


def test_selection_and_view_center_survive_semantic_transition_and_slice(app: QApplication) -> None:
    canvas = GraphCanvas()
    canvas.resize(700, 500)
    nodes = [_node("keep"), _node("other")]
    canvas.set_slice(nodes, [])
    assert canvas.focus_search_result("keep")
    canvas.centerOn(QPointF(123.0, 77.0))
    before = canvas.mapToScene(canvas.viewport().rect().center())
    canvas.set_semantic_level(SemanticLevel.EVIDENCE)
    assert canvas.selected_node_id == "keep"
    after_level = canvas.mapToScene(canvas.viewport().rect().center())
    assert abs(after_level.x() - before.x()) < 2
    assert abs(after_level.y() - before.y()) < 2
    selection_events: list[object] = []
    canvas.selection_changed.connect(selection_events.append)
    canvas.set_slice(reversed(nodes), [], preserve_navigation=True)
    assert canvas.selected_node_id == "keep"
    assert selection_events == []


def test_fit_operations_preserve_the_explicit_semantic_level(app: QApplication) -> None:
    canvas = GraphCanvas()
    canvas.resize(700, 500)
    canvas.set_slice([_node(f"node-{index}") for index in range(8)], [])
    canvas.set_semantic_level(SemanticLevel.EVENTS)
    assert canvas.focus_search_result("node-0")

    canvas.fit_all()
    assert canvas.semantic_level is SemanticLevel.EVENTS
    canvas.fit_selection()
    assert canvas.semantic_level is SemanticLevel.EVENTS


def test_each_semantic_level_restores_its_prior_view_center(app: QApplication) -> None:
    canvas = GraphCanvas()
    canvas.resize(700, 500)
    canvas.set_slice([_node("one"), _node("two")], [])
    canvas.set_semantic_level(SemanticLevel.OVERVIEW)
    canvas.centerOn(QPointF(123.0, 77.0))
    overview_center = canvas.mapToScene(canvas.viewport().rect().center())

    canvas.set_semantic_level(SemanticLevel.EVENTS)
    canvas.centerOn(QPointF(420.0, 260.0))
    canvas.set_semantic_level(SemanticLevel.OVERVIEW)
    restored = canvas.mapToScene(canvas.viewport().rect().center())

    assert abs(restored.x() - overview_center.x()) < 2
    assert abs(restored.y() - overview_center.y()) < 2


def test_genuine_scene_deselection_clears_logical_selection(app: QApplication) -> None:
    canvas = GraphCanvas()
    canvas.set_slice([_node("selected")], [])
    assert canvas.focus_search_result("selected")
    selection_events: list[object] = []
    canvas.selection_changed.connect(selection_events.append)

    canvas.scene().clearSelection()

    assert canvas.selected_node_id is None
    assert selection_events == [None]


def test_deterministic_layout_for_identical_bounded_input(app: QApplication) -> None:
    nodes = [_node("z"), _node("a"), _node("m"), _node("b")]
    first = GraphCanvas()
    second = GraphCanvas()
    first.set_slice(nodes, [])
    second.set_slice(reversed(nodes), [])

    def positions(canvas: GraphCanvas) -> dict[str, tuple[float, float]]:
        return {
            item.spec.id: (item.pos().x(), item.pos().y())
            for item in canvas.scene().items()
            if hasattr(item, "spec") and isinstance(item.spec, GraphNodeSpec)
        }

    assert positions(first) == positions(second)


def test_all_required_kinds_have_distinct_visual_treatment() -> None:
    kinds = (
        "story", "container", "event", "choice", "gate", "effect", "merge", "loop",
        "jump", "call", "return", "shared_call", "ending", "technical", "unresolved",
    )
    styles = [visual_style_for(kind) for kind in kinds]
    signatures = {(style.fill, style.border, style.accent, style.dashed) for style in styles}
    assert len(signatures) == len(kinds)
    assert visual_style_for("technical").dashed
    assert visual_style_for("unresolved").dashed


def test_search_filters_and_source_evidence_signal(app: QApplication) -> None:
    evidence = (SourceEvidence("story/prologue.rpy", 12, 14, 'ian "Hello"'),)
    love = _node(
        "love",
        variables=frozenset({"love"}),
        categories=frozenset({"relationship"}),
        evidence=evidence,
        requirements=("Wits > 0",),
        effects=("Love +1",),
    )
    money = _node("money", variables=frozenset({"money"}), categories=frozenset({"resource"}))
    canvas = GraphCanvas()
    canvas.set_slice([love, money], [])
    canvas.set_variable_filter({"love"})
    visible = {
        item.spec.id
        for item in canvas.scene().items()
        if hasattr(item, "spec") and item.isVisible()
    }
    assert visible == {"love"}
    canvas.set_variable_filter(set())
    canvas.set_category_filter({"resource"})
    assert canvas.focus_search_result("money")
    canvas.set_category_filter(set())
    emitted: list[tuple[str, object]] = []
    canvas.source_evidence_selected.connect(lambda node_id, value: emitted.append((node_id, value)))
    assert canvas.focus_search_result("love")
    canvas.request_selected_evidence()
    assert emitted[-1] == ("love", evidence)
