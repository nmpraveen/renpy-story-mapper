"""Bounded, deterministic, native Qt story-graph canvas.

The canvas deliberately consumes only a bounded prefix of any supplied iterable.  Its caller owns
querying/projecting the canonical graph and responds to expansion requests with another bounded
slice.  Drawing is done by two custom graphics-item types (cards and edges), so text and badges do
not silently inflate the scene item count beyond ``max_rendered_items``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import IntEnum
from itertools import islice
from math import hypot

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
    QGraphicsView,
    QStyleOptionGraphicsItem,
    QWidget,
)


class SemanticLevel(IntEnum):
    """The three meaningfully different story-map projections."""

    OVERVIEW = 1
    EVENTS = 2
    EVIDENCE = 3


@dataclass(frozen=True)
class SourceEvidence:
    """Physical source evidence associated with a visible graph item."""

    source_path: str
    start_line: int
    end_line: int
    text: str = ""


@dataclass(frozen=True)
class GraphNodeSpec:
    """Display-only node record supplied by the shell's bounded query model."""

    id: str
    kind: str
    title: str
    summary: str = ""
    detail: str = ""
    semantic_levels: frozenset[SemanticLevel] = field(
        default_factory=lambda: frozenset(SemanticLevel)
    )
    requirements: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()
    variables: frozenset[str] = frozenset()
    categories: frozenset[str] = frozenset()
    evidence: tuple[SourceEvidence, ...] = ()
    expandable: bool = False
    expanded: bool = False


@dataclass(frozen=True)
class GraphEdgeSpec:
    """A typed connection between two nodes in the same bounded slice."""

    source: str
    target: str
    kind: str = "flow"


@dataclass(frozen=True)
class NodeVisualStyle:
    """Testable visual classification independent of paint-system internals."""

    fill: str
    border: str
    accent: str
    dashed: bool = False


_STYLES: dict[str, NodeVisualStyle] = {
    "story": NodeVisualStyle("#EAF2FF", "#315C9B", "#4385D1"),
    "container": NodeVisualStyle("#E8F1F5", "#315D70", "#4A8DA8"),
    "event": NodeVisualStyle("#EDF7F0", "#356B49", "#54A66F"),
    "choice": NodeVisualStyle("#FFF4D8", "#8A6418", "#D49A25"),
    "gate": NodeVisualStyle("#F4ECFF", "#6D3D98", "#9B62C7"),
    "effect": NodeVisualStyle("#E8FAF7", "#26766B", "#3DA99A"),
    "merge": NodeVisualStyle("#EAF0FB", "#445D8B", "#6686BF"),
    "loop": NodeVisualStyle("#FFF0E5", "#965425", "#D27B3D"),
    "shared_call": NodeVisualStyle("#F1ECFF", "#5D4A91", "#8873BF"),
    "ending": NodeVisualStyle("#FCE8EC", "#8E3849", "#C4576D"),
    "technical": NodeVisualStyle("#ECEFF2", "#606A73", "#7C8790", dashed=True),
    "unresolved": NodeVisualStyle("#FFF0F0", "#A13333", "#D44A4A", dashed=True),
}
_DEFAULT_STYLE = NodeVisualStyle("#F3F4F6", "#4B5563", "#6B7280")


def visual_style_for(kind: str) -> NodeVisualStyle:
    """Return a stable style for every supported semantic classification."""

    return _STYLES.get(kind, _DEFAULT_STYLE)


def semantic_level_for_scale(scale: float) -> SemanticLevel:
    """Map view scale to a semantic projection using stable, testable thresholds."""

    if scale < 0.65:
        return SemanticLevel.OVERVIEW
    if scale < 1.35:
        return SemanticLevel.EVENTS
    return SemanticLevel.EVIDENCE


class _NodeItem(QGraphicsObject):
    WIDTH = 260.0
    HEIGHT = 132.0

    def __init__(self, spec: GraphNodeSpec) -> None:
        super().__init__()
        self.spec = spec
        self.semantic_level = SemanticLevel.EVENTS
        self.search_highlighted = False
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setToolTip(spec.detail or spec.summary or spec.title)

    def boundingRect(self) -> QRectF:
        return QRectF(0.0, 0.0, self.WIDTH, self.HEIGHT)

    def paint(
        self,
        painter: QPainter,
        _option: QStyleOptionGraphicsItem,
        _widget: QWidget | None = None,
    ) -> None:
        style = visual_style_for(self.spec.kind)
        border = QColor("#1A73E8") if self.isSelected() else QColor(style.border)
        if self.search_highlighted and not self.isSelected():
            border = QColor("#C77700")
        pen = QPen(border, 3.0 if self.isSelected() or self.search_highlighted else 1.5)
        if style.dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(QColor(style.fill))
        painter.drawRoundedRect(self.boundingRect(), 9.0, 9.0)

        painter.fillRect(QRectF(0.0, 0.0, 7.0, self.HEIGHT), QColor(style.accent))
        painter.setPen(QColor("#18202A"))
        title_font = painter.font()
        title_font.setBold(True)
        title_font.setPointSize(10)
        painter.setFont(title_font)
        painter.drawText(QRectF(15.0, 10.0, 230.0, 24.0), self._elide(self.spec.title, 36))

        body_font = painter.font()
        body_font.setBold(False)
        body_font.setPointSize(8)
        painter.setFont(body_font)
        if self.semantic_level >= SemanticLevel.EVENTS:
            painter.setPen(QColor("#35404C"))
            painter.drawText(
                QRectF(15.0, 38.0, 230.0, 36.0),
                Qt.TextFlag.TextWordWrap,
                self._elide(self.spec.summary, 82),
            )
            self._paint_badges(painter)
        if self.semantic_level == SemanticLevel.EVIDENCE:
            painter.setPen(QColor("#59636E"))
            evidence = self.spec.detail
            if not evidence and self.spec.evidence:
                first = self.spec.evidence[0]
                evidence = f"{first.source_path}:{first.start_line}"
            painter.drawText(
                QRectF(15.0, 102.0, 230.0, 22.0), self._elide(evidence, 48)
            )

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        canvas = self.scene().views()[0] if self.scene() and self.scene().views() else None
        if isinstance(canvas, GraphCanvas) and self.spec.expandable:
            canvas.request_expansion(self.spec.id, not self.spec.expanded)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    @staticmethod
    def _elide(text: str, maximum: int) -> str:
        compact = " ".join(text.split())
        return compact if len(compact) <= maximum else compact[: maximum - 1] + "…"

    def _paint_badges(self, painter: QPainter) -> None:
        badges = tuple(f"Req: {value}" for value in self.spec.requirements[:1]) + tuple(
            f"Effect: {value}" for value in self.spec.effects[:1]
        )
        x = 15.0
        for badge in badges:
            width = min(108.0, 12.0 + len(badge) * 5.2)
            painter.setPen(QColor("#59636E"))
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawRoundedRect(QRectF(x, 79.0, width, 18.0), 5.0, 5.0)
            painter.drawText(QRectF(x + 5.0, 81.0, width - 9.0, 14.0), self._elide(badge, 19))
            x += width + 6.0


class _EdgeItem(QGraphicsPathItem):
    def __init__(self, spec: GraphEdgeSpec) -> None:
        super().__init__()
        self.spec = spec
        color = "#9A4D24" if spec.kind == "loop" else "#75808C"
        pen = QPen(QColor(color), 1.5)
        if spec.kind in {"call", "shared_call", "unresolved"}:
            pen.setStyle(Qt.PenStyle.DashLine)
        self.setPen(pen)
        self.setZValue(-1.0)


class GraphCanvas(QGraphicsView):
    """A virtualized native graph canvas for a shell-supplied bounded slice.

    ``set_slice`` never consumes more than ``max_rendered_items + 1`` records across nodes and
    edges.  Expansion is intentionally request-based: the project/query layer chooses which
    bounded replacement slice to return.
    """

    selection_changed = Signal(object)
    semantic_level_changed = Signal(int)
    expansion_requested = Signal(str, bool)
    source_evidence_selected = Signal(str, object)
    render_limit_reached = Signal(int)
    filters_changed = Signal(object, object)

    def __init__(self, parent: QWidget | None = None, *, max_rendered_items: int = 240) -> None:
        if max_rendered_items < 1:
            raise ValueError("max_rendered_items must be positive")
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.max_rendered_items = max_rendered_items
        self._node_items: dict[str, _NodeItem] = {}
        self._edge_items: list[_EdgeItem] = []
        self._selected_id: str | None = None
        self._semantic_level = SemanticLevel.EVENTS
        self._variable_filter: frozenset[str] = frozenset()
        self._category_filter: frozenset[str] = frozenset()
        self._hidden_kinds: frozenset[str] = frozenset()
        self._search_results: frozenset[str] = frozenset()
        self._panning = False
        self._pan_origin = QPoint()

        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Story graph canvas")
        self._scene.selectionChanged.connect(self._on_scene_selection_changed)

    @property
    def semantic_level(self) -> SemanticLevel:
        return self._semantic_level

    @property
    def selected_node_id(self) -> str | None:
        return self._selected_id

    @property
    def rendered_item_count(self) -> int:
        return len(self._node_items) + len(self._edge_items)

    @property
    def rendered_node_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._node_items))

    def set_slice(
        self,
        nodes: Iterable[GraphNodeSpec],
        edges: Iterable[GraphEdgeSpec],
        *,
        preserve_navigation: bool = True,
    ) -> None:
        """Replace the scene from bounded prefixes while optionally preserving place/selection."""

        old_center = self.mapToScene(self.viewport().rect().center())
        old_selected = self._selected_id if preserve_navigation else None
        node_prefix = list(islice(nodes, self.max_rendered_items + 1))
        truncated = len(node_prefix) > self.max_rendered_items
        accepted_nodes = sorted(node_prefix[: self.max_rendered_items], key=lambda node: node.id)
        remaining = self.max_rendered_items - len(accepted_nodes)
        edge_prefix = list(islice(edges, remaining + 1))
        truncated = truncated or len(edge_prefix) > remaining
        known_ids = {node.id for node in accepted_nodes}
        accepted_edges = sorted(
            (
                edge
                for edge in edge_prefix[:remaining]
                if edge.source in known_ids and edge.target in known_ids
            ),
            key=lambda edge: (edge.source, edge.target, edge.kind),
        )

        self._scene.clear()
        self._node_items.clear()
        self._edge_items.clear()
        for node_spec in accepted_nodes:
            item = _NodeItem(node_spec)
            item.semantic_level = self._semantic_level
            item.search_highlighted = node_spec.id in self._search_results
            self._scene.addItem(item)
            self._node_items[node_spec.id] = item
        self._layout_nodes()
        for edge_spec in accepted_edges:
            edge_item = _EdgeItem(edge_spec)
            self._scene.addItem(edge_item)
            self._edge_items.append(edge_item)
        self._update_edges()
        self._apply_visibility()
        self._scene.setSceneRect(self._scene.itemsBoundingRect().adjusted(-60, -60, 60, 60))

        self._selected_id = old_selected
        if old_selected in self._node_items and self._node_items[old_selected].isVisible():
            self._node_items[old_selected].setSelected(True)
        if preserve_navigation and not old_center.isNull():
            self.centerOn(old_center)
        if truncated:
            self.render_limit_reached.emit(self.rendered_item_count)

    def set_semantic_level(self, level: SemanticLevel | int) -> None:
        """Switch semantic projection without changing transform, center, or logical selection."""

        semantic_level = SemanticLevel(level)
        if semantic_level == self._semantic_level:
            return
        center = self.mapToScene(self.viewport().rect().center())
        self._semantic_level = semantic_level
        for item in self._node_items.values():
            item.semantic_level = semantic_level
            item.update()
        self._apply_visibility()
        self.centerOn(center)
        self.semantic_level_changed.emit(int(semantic_level))

    def set_variable_filter(self, variables: Iterable[str]) -> None:
        self._variable_filter = frozenset(variables)
        self._filters_updated()

    def set_category_filter(self, categories: Iterable[str]) -> None:
        self._category_filter = frozenset(categories)
        self._filters_updated()

    def set_kind_visible(self, kind: str, visible: bool) -> None:
        hidden = set(self._hidden_kinds)
        hidden.discard(kind) if visible else hidden.add(kind)
        self._hidden_kinds = frozenset(hidden)
        self._apply_visibility()

    def set_search_results(self, node_ids: Iterable[str]) -> None:
        self._search_results = frozenset(node_ids)
        for node_id, item in self._node_items.items():
            item.search_highlighted = node_id in self._search_results
            item.update()

    def focus_search_result(self, node_id: str) -> bool:
        item = self._node_items.get(node_id)
        if item is None:
            return False
        self._search_results = frozenset({node_id})
        self.set_search_results(self._search_results)
        if item.isVisible():
            self._select_item(item)
            self.centerOn(item)
            self.ensureVisible(item, 40, 40)
            return True
        return False

    def fit_all(self) -> None:
        visible = [item for item in self._node_items.values() if item.isVisible()]
        if not visible:
            return
        bounds = visible[0].sceneBoundingRect()
        for item in visible[1:]:
            bounds = bounds.united(item.sceneBoundingRect())
        self.fitInView(bounds.adjusted(-30, -30, 30, 30), Qt.AspectRatioMode.KeepAspectRatio)
        self._sync_semantic_level_to_scale()

    def fit_selection(self) -> None:
        item = self._node_items.get(self._selected_id or "")
        if item is not None and item.isVisible():
            self.fitInView(
                item.sceneBoundingRect().adjusted(-80, -80, 80, 80),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
            self._sync_semantic_level_to_scale()

    def request_expansion(self, node_id: str, expanded: bool) -> None:
        item = self._node_items.get(node_id)
        if item is not None and item.spec.expandable:
            self.expansion_requested.emit(node_id, expanded)

    def request_selected_evidence(self) -> None:
        item = self._node_items.get(self._selected_id or "")
        if item is not None:
            self.source_evidence_selected.emit(item.spec.id, item.spec.evidence)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.18 if event.angleDelta().y() > 0 else 1.0 / 1.18
        candidate = self.transform().m11() * factor
        if 0.18 <= candidate <= 4.5:
            self.scale(factor, factor)
            self._sync_semantic_level_to_scale()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_origin = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._panning:
            delta = event.position().toPoint() - self._pan_origin
            self._pan_origin = event.position().toPoint()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3):
            self.set_semantic_level(SemanticLevel(key - Qt.Key.Key_0))
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.scale(1.18, 1.18)
            self._sync_semantic_level_to_scale()
        elif key == Qt.Key.Key_Minus:
            self.scale(1.0 / 1.18, 1.0 / 1.18)
            self._sync_semantic_level_to_scale()
        elif key == Qt.Key.Key_F:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.fit_selection()
            else:
                self.fit_all()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.request_selected_evidence()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._navigate(key)
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def _layout_nodes(self) -> None:
        """Lay out a bounded slice deterministically by stable identifier."""

        columns = 4
        x_spacing = _NodeItem.WIDTH + 90.0
        y_spacing = _NodeItem.HEIGHT + 70.0
        for index, node_id in enumerate(sorted(self._node_items)):
            row, column = divmod(index, columns)
            self._node_items[node_id].setPos(column * x_spacing, row * y_spacing)

    def _update_edges(self) -> None:
        for edge in self._edge_items:
            source = self._node_items[edge.spec.source]
            target = self._node_items[edge.spec.target]
            start = source.sceneBoundingRect().center()
            end = target.sceneBoundingRect().center()
            path = QPainterPath(start)
            if edge.spec.kind == "loop" or source is target:
                path.cubicTo(start + QPointF(120, -90), start + QPointF(-120, -90), end)
            else:
                middle_x = (start.x() + end.x()) / 2.0
                path.cubicTo(QPointF(middle_x, start.y()), QPointF(middle_x, end.y()), end)
            edge.setPath(path)

    def _apply_visibility(self) -> None:
        for item in self._node_items.values():
            spec = item.spec
            variable_match = not self._variable_filter or bool(
                spec.variables & self._variable_filter
            )
            category_match = not self._category_filter or bool(
                spec.categories & self._category_filter
            )
            visible = (
                self._semantic_level in spec.semantic_levels
                and spec.kind not in self._hidden_kinds
                and variable_match
                and category_match
            )
            item.setVisible(visible)
        for edge in self._edge_items:
            edge.setVisible(
                self._node_items[edge.spec.source].isVisible()
                and self._node_items[edge.spec.target].isVisible()
            )

    def _filters_updated(self) -> None:
        self._apply_visibility()
        self.filters_changed.emit(self._variable_filter, self._category_filter)

    def _sync_semantic_level_to_scale(self) -> None:
        self.set_semantic_level(semantic_level_for_scale(self.transform().m11()))

    def _on_scene_selection_changed(self) -> None:
        selected = [item for item in self._scene.selectedItems() if isinstance(item, _NodeItem)]
        if selected:
            self._selected_id = selected[0].spec.id
            self.selection_changed.emit(self._selected_id)
            self.source_evidence_selected.emit(self._selected_id, selected[0].spec.evidence)
        elif self._selected_id is None:
            self.selection_changed.emit(None)

    def _select_item(self, item: _NodeItem) -> None:
        self._scene.clearSelection()
        item.setSelected(True)
        item.setFocus(Qt.FocusReason.OtherFocusReason)

    def _navigate(self, key: int) -> None:
        visible = [item for item in self._node_items.values() if item.isVisible()]
        if not visible:
            return
        current = self._node_items.get(self._selected_id or "")
        if current is None or not current.isVisible():
            self._select_item(sorted(visible, key=lambda item: item.spec.id)[0])
            return
        origin = current.sceneBoundingRect().center()

        def in_direction(item: _NodeItem) -> bool:
            point = item.sceneBoundingRect().center()
            if key == Qt.Key.Key_Left:
                return point.x() < origin.x()
            if key == Qt.Key.Key_Right:
                return point.x() > origin.x()
            if key == Qt.Key.Key_Up:
                return point.y() < origin.y()
            return point.y() > origin.y()

        candidates = [item for item in visible if item is not current and in_direction(item)]
        if candidates:
            nearest = min(
                candidates,
                key=lambda item: (
                    hypot(
                        item.sceneBoundingRect().center().x() - origin.x(),
                        item.sceneBoundingRect().center().y() - origin.y(),
                    ),
                    item.spec.id,
                ),
            )
            self._select_item(nearest)
            self.ensureVisible(nearest, 30, 30)


__all__ = [
    "GraphCanvas",
    "GraphEdgeSpec",
    "GraphNodeSpec",
    "NodeVisualStyle",
    "SemanticLevel",
    "SourceEvidence",
    "semantic_level_for_scale",
    "visual_style_for",
]
