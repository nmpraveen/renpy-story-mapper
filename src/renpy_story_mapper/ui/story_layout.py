"""Pure deterministic layout contracts for the Level-2 story-event graph.

The module deliberately knows nothing about Qt, persistence, or AI output.  Callers adapt
accepted ``StoryEvent`` and locally derived ``StoryEdge`` records into the small immutable input
types below.  Every ordering decision has an explicit stable tie-breaker.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

PaletteRole = Literal[
    "flow", "choice", "requirement", "effect", "unresolved", "neutral"
]
RouteKind = Literal[
    "flow", "choice", "merge", "call", "return", "loop", "ending", "unresolved"
]

DEFAULT_CARD_LIMIT = 30
ABSOLUTE_RENDERED_ITEM_LIMIT = 240


@dataclass(frozen=True)
class LayoutNode:
    """Accepted story event projected into renderer-neutral layout data."""

    id: str
    order: int
    kind: str = "event"
    has_requirement: bool = False
    has_effect: bool = False


@dataclass(frozen=True)
class LayoutEdge:
    """Locally derived authoritative connection between accepted story events."""

    id: str
    source_id: str
    target_id: str
    kind: str = "flow"
    authoritative: bool = True
    order: int = 0


@dataclass(frozen=True)
class LayoutInput:
    nodes: tuple[LayoutNode, ...]
    edges: tuple[LayoutEdge, ...]


@dataclass(frozen=True)
class LayoutConfig:
    """Geometry and safety bounds; dimensions are device-independent pixels."""

    zoom: float = 1.0
    max_cards: int = DEFAULT_CARD_LIMIT
    max_rendered_items: int = ABSOLUTE_RENDERED_ITEM_LIMIT
    card_width: float = 260.0
    card_height: float = 158.0
    rank_gap: float = 150.0
    lane_gap: float = 70.0
    margin: float = 48.0
    order_passes: int = 4

    def __post_init__(self) -> None:
        if not 1.0 <= self.zoom <= 2.0:
            raise ValueError("zoom must be between 1.0 and 2.0")
        if not 1 <= self.max_cards <= ABSOLUTE_RENDERED_ITEM_LIMIT:
            raise ValueError("max_cards must be between 1 and 240")
        if not 1 <= self.max_rendered_items <= ABSOLUTE_RENDERED_ITEM_LIMIT:
            raise ValueError("max_rendered_items must be between 1 and 240")
        if self.order_passes < 0:
            raise ValueError("order_passes cannot be negative")
        dimensions = (self.card_width, self.card_height, self.rank_gap, self.lane_gap, self.margin)
        if any(value <= 0 for value in dimensions):
            raise ValueError("geometry dimensions must be positive")


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class SemanticStyle:
    """Visual role plus redundant non-color signals for accessible rendering."""

    role: PaletteRole
    color: str
    line_pattern: Literal["solid", "dashed", "dotted", "double"]
    glyph: str
    label: str


@dataclass(frozen=True)
class PositionedCard:
    id: str
    rank: int
    lane: int
    component: int
    bounds: Rect
    style: SemanticStyle


@dataclass(frozen=True)
class RoutedEdge:
    id: str
    source_id: str
    target_id: str
    kind: RouteKind
    source_lane: int
    target_lane: int
    points: tuple[Point, ...]
    style: SemanticStyle


@dataclass(frozen=True)
class LayoutResult:
    cards: tuple[PositionedCard, ...]
    edges: tuple[RoutedEdge, ...]
    width: float
    height: float
    truncated: bool
    omitted_cards: int
    omitted_edges: int

    def canonical_json(self) -> str:
        """Return stable serialized output for snapshots, caching, and regression hashes."""

        def point(value: Point) -> list[float]:
            return [value.x, value.y]

        def style(value: SemanticStyle) -> dict[str, str]:
            return {
                "color": value.color,
                "glyph": value.glyph,
                "label": value.label,
                "line_pattern": value.line_pattern,
                "role": value.role,
            }

        payload = {
            "cards": [
                {
                    "bounds": [
                        card.bounds.x,
                        card.bounds.y,
                        card.bounds.width,
                        card.bounds.height,
                    ],
                    "component": card.component,
                    "id": card.id,
                    "lane": card.lane,
                    "rank": card.rank,
                    "style": style(card.style),
                }
                for card in self.cards
            ],
            "edges": [
                {
                    "id": edge.id,
                    "kind": edge.kind,
                    "points": [point(value) for value in edge.points],
                    "source_id": edge.source_id,
                    "source_lane": edge.source_lane,
                    "style": style(edge.style),
                    "target_id": edge.target_id,
                    "target_lane": edge.target_lane,
                }
                for edge in self.edges
            ],
            "height": self.height,
            "omitted_cards": self.omitted_cards,
            "omitted_edges": self.omitted_edges,
            "truncated": self.truncated,
            "width": self.width,
        }
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)

    def digest(self) -> str:
        return sha256(self.canonical_json().encode("utf-8")).hexdigest()


_STYLES: dict[str, SemanticStyle] = {
    "flow": SemanticStyle("flow", "#0891B2", "solid", "arrow", "Flow"),
    "choice": SemanticStyle("choice", "#7C3AED", "solid", "fork", "Choice"),
    "requirement": SemanticStyle(
        "requirement", "#D97706", "dashed", "lock", "Requirement"
    ),
    "effect": SemanticStyle("effect", "#16A34A", "solid", "plus", "Effect"),
    "unresolved": SemanticStyle(
        "unresolved", "#DC2626", "dotted", "question", "Unresolved"
    ),
    "neutral": SemanticStyle("neutral", "#64748B", "solid", "dot", "Event"),
    "merge": SemanticStyle("flow", "#0891B2", "double", "merge", "Merge"),
    "call": SemanticStyle("neutral", "#64748B", "dashed", "call", "Call"),
    "return": SemanticStyle("neutral", "#64748B", "dotted", "return", "Return"),
    "loop": SemanticStyle("flow", "#0891B2", "dashed", "loop", "Loop"),
    "ending": SemanticStyle("neutral", "#64748B", "double", "stop", "Ending"),
}


def semantic_style(kind: str) -> SemanticStyle:
    """Map domain vocabulary to the approved restrained palette and redundant signals."""

    normalized = kind.casefold().replace("-", "_")
    if "unresolved" in normalized or "dynamic" in normalized:
        return _STYLES["unresolved"]
    if "require" in normalized or "gate" in normalized:
        return _STYLES["requirement"]
    if "effect" in normalized:
        return _STYLES["effect"]
    if "choice" in normalized or "branch" in normalized or "menu" in normalized:
        return _STYLES["choice"]
    for name in ("merge", "return", "call", "loop", "ending"):
        if name in normalized or (name == "ending" and normalized in {"end", "terminal"}):
            return _STYLES[name]
    if normalized in {"flow", "fallthrough", "jump"}:
        return _STYLES["flow"]
    return _STYLES["neutral"]


def _route_kind(kind: str, *, loop: bool, merge: bool, ending: bool) -> RouteKind:
    normalized = kind.casefold().replace("-", "_")
    if loop:
        return "loop"
    if "unresolved" in normalized or "dynamic" in normalized:
        return "unresolved"
    if "return" in normalized:
        return "return"
    if "call" in normalized:
        return "call"
    if "choice" in normalized or "branch" in normalized or "menu" in normalized:
        return "choice"
    if ending:
        return "ending"
    if merge:
        return "merge"
    return "flow"


def _validate(layout_input: LayoutInput) -> None:
    node_ids = [node.id for node in layout_input.nodes]
    edge_ids = [edge.id for edge in layout_input.edges]
    if any(not value for value in (*node_ids, *edge_ids)):
        raise ValueError("layout IDs cannot be empty")
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("layout node IDs must be unique")
    if len(edge_ids) != len(set(edge_ids)):
        raise ValueError("layout edge IDs must be unique")


def _bounded_input(
    layout_input: LayoutInput, config: LayoutConfig
) -> tuple[list[LayoutNode], list[LayoutEdge], int, int]:
    nodes = sorted(layout_input.nodes, key=lambda node: (node.order, node.id))
    accepted_nodes = nodes[: min(config.max_cards, config.max_rendered_items)]
    accepted_ids = {node.id for node in accepted_nodes}
    remaining = config.max_rendered_items - len(accepted_nodes)
    eligible_edges = sorted(
        (
            edge
            for edge in layout_input.edges
            if edge.source_id in accepted_ids and edge.target_id in accepted_ids
        ),
        key=lambda edge: (edge.order, edge.source_id, edge.target_id, edge.kind, edge.id),
    )
    accepted_edges = eligible_edges[:remaining]
    omitted_cards = len(nodes) - len(accepted_nodes)
    omitted_edges = len(layout_input.edges) - len(accepted_edges)
    return accepted_nodes, accepted_edges, omitted_cards, omitted_edges


def _strong_components(
    nodes: Sequence[LayoutNode], edges: Sequence[LayoutEdge]
) -> tuple[tuple[str, ...], ...]:
    """Deterministic iterative-order Tarjan SCC decomposition."""

    known = {node.id for node in nodes}
    adjacency: dict[str, list[str]] = {node.id: [] for node in nodes}
    for edge in edges:
        if edge.authoritative and edge.source_id in known and edge.target_id in known:
            adjacency[edge.source_id].append(edge.target_id)
    for values in adjacency.values():
        values.sort()

    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    result: list[tuple[str, ...]] = []

    def visit(node_id: str) -> None:
        nonlocal index
        indices[node_id] = index
        lowlinks[node_id] = index
        index += 1
        stack.append(node_id)
        on_stack.add(node_id)
        for target_id in adjacency[node_id]:
            if target_id not in indices:
                visit(target_id)
                lowlinks[node_id] = min(lowlinks[node_id], lowlinks[target_id])
            elif target_id in on_stack:
                lowlinks[node_id] = min(lowlinks[node_id], indices[target_id])
        if lowlinks[node_id] == indices[node_id]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node_id:
                    break
            result.append(tuple(sorted(component)))

    for node_id in sorted(adjacency):
        if node_id not in indices:
            visit(node_id)
    return tuple(result)


def _component_ranks(
    components: Sequence[tuple[str, ...]],
    nodes_by_id: Mapping[str, LayoutNode],
    edges: Sequence[LayoutEdge],
) -> tuple[dict[str, int], dict[str, int]]:
    component_by_node = {
        node_id: component_index
        for component_index, component in enumerate(components)
        for node_id in component
    }
    component_key = {
        index: min((nodes_by_id[node_id].order, node_id) for node_id in component)
        for index, component in enumerate(components)
    }
    successors: dict[int, set[int]] = defaultdict(set)
    predecessors: dict[int, set[int]] = defaultdict(set)
    for edge in edges:
        if not edge.authoritative:
            continue
        source = component_by_node[edge.source_id]
        target = component_by_node[edge.target_id]
        if source != target:
            successors[source].add(target)
            predecessors[target].add(source)
    indegree = {index: len(predecessors[index]) for index in range(len(components))}
    ready = sorted(
        (index for index, degree in indegree.items() if degree == 0),
        key=lambda value: component_key[value],
    )
    ranks = {index: 0 for index in range(len(components))}
    while ready:
        current = ready.pop(0)
        for target in sorted(successors[current], key=lambda value: component_key[value]):
            ranks[target] = max(ranks[target], ranks[current] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort(key=lambda value: component_key[value])
    node_ranks = {node_id: ranks[index] for node_id, index in component_by_node.items()}
    return component_by_node, node_ranks


def _ordered_lanes(
    nodes: Sequence[LayoutNode], edges: Sequence[LayoutEdge], ranks: Mapping[str, int], passes: int
) -> dict[str, int]:
    by_rank: dict[int, list[str]] = defaultdict(list)
    node_key = {node.id: (node.order, node.id) for node in nodes}
    for node in nodes:
        by_rank[ranks[node.id]].append(node.id)
    for values in by_rank.values():
        values.sort(key=lambda value: node_key[value])
    incoming: dict[str, set[str]] = defaultdict(set)
    outgoing: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if edge.authoritative and edge.source_id != edge.target_id:
            outgoing[edge.source_id].add(edge.target_id)
            incoming[edge.target_id].add(edge.source_id)

    def sweep(rank_order: Iterable[int], neighbors: Mapping[str, set[str]]) -> None:
        positions = {
            node_id: index
            for rank in sorted(by_rank)
            for index, node_id in enumerate(by_rank[rank])
        }
        for rank in rank_order:
            def key(node_id: str) -> tuple[float, int, str]:
                adjacent = sorted(neighbors[node_id])
                barycenter = (
                    sum(positions[value] for value in adjacent) / len(adjacent)
                    if adjacent
                    else float(positions[node_id])
                )
                order, stable_id = node_key[node_id]
                return barycenter, order, stable_id

            by_rank[rank].sort(key=key)

    ordered_ranks = sorted(by_rank)
    for _ in range(passes):
        sweep(ordered_ranks[1:], incoming)
        sweep(reversed(ordered_ranks[:-1]), outgoing)
    return {
        node_id: index
        for rank in ordered_ranks
        for index, node_id in enumerate(by_rank[rank])
    }


def _node_style(node: LayoutNode) -> SemanticStyle:
    if node.has_requirement:
        return semantic_style("requirement")
    if node.has_effect:
        return semantic_style("effect")
    return semantic_style(node.kind)


def layout_story_events(
    layout_input: LayoutInput, config: LayoutConfig | None = None
) -> LayoutResult:
    """Lay out a bounded event graph deterministically, including cycles and disconnected parts."""

    effective = config or LayoutConfig()
    _validate(layout_input)
    nodes, edges, omitted_cards, omitted_edges = _bounded_input(layout_input, effective)
    if not nodes:
        return LayoutResult((), (), 0.0, 0.0, bool(omitted_edges), omitted_cards, omitted_edges)

    nodes_by_id = {node.id: node for node in nodes}
    components = _strong_components(nodes, edges)
    component_by_node, ranks = _component_ranks(components, nodes_by_id, edges)
    lanes = _ordered_lanes(nodes, edges, ranks, effective.order_passes)
    scale = effective.zoom
    card_width = effective.card_width * scale
    card_height = effective.card_height * scale
    horizontal_step = (effective.card_width + effective.rank_gap) * scale
    vertical_step = (effective.card_height + effective.lane_gap) * scale
    margin = effective.margin * scale
    route_clearance = (effective.lane_gap + 36.0) * scale
    origin = margin + route_clearance

    cards = tuple(
        PositionedCard(
            id=node.id,
            rank=ranks[node.id],
            lane=lanes[node.id],
            component=component_by_node[node.id],
            bounds=Rect(
                origin + ranks[node.id] * horizontal_step,
                origin + lanes[node.id] * vertical_step,
                card_width,
                card_height,
            ),
            style=_node_style(node),
        )
        for node in sorted(nodes, key=lambda value: (ranks[value.id], lanes[value.id], value.id))
    )
    cards_by_id = {card.id: card for card in cards}
    incoming_count: dict[str, int] = defaultdict(int)
    outgoing_count: dict[str, int] = defaultdict(int)
    for edge in edges:
        incoming_count[edge.target_id] += 1
        outgoing_count[edge.source_id] += 1

    routed: list[RoutedEdge] = []
    for edge in edges:
        source = cards_by_id[edge.source_id]
        target = cards_by_id[edge.target_id]
        is_loop = component_by_node[edge.source_id] == component_by_node[edge.target_id]
        kind = _route_kind(
            edge.kind,
            loop=is_loop,
            merge=incoming_count[edge.target_id] > 1,
            ending=outgoing_count[edge.target_id] == 0 and "end" in edge.kind.casefold(),
        )
        source_right = Point(
            source.bounds.x + source.bounds.width,
            source.bounds.y + source.bounds.height / 2,
        )
        target_left = Point(target.bounds.x, target.bounds.y + target.bounds.height / 2)
        points: tuple[Point, ...]
        if is_loop:
            top_y = min(source.bounds.y, target.bounds.y) - route_clearance
            points = (
                source_right,
                Point(source_right.x + route_clearance, source_right.y),
                Point(source_right.x + route_clearance, top_y),
                Point(target_left.x - route_clearance, top_y),
                Point(target_left.x - route_clearance, target_left.y),
                target_left,
            )
        else:
            middle_x = (source_right.x + target_left.x) / 2
            points = (
                source_right,
                Point(middle_x, source_right.y),
                Point(middle_x, target_left.y),
                target_left,
            )
        routed.append(
            RoutedEdge(
                edge.id,
                edge.source_id,
                edge.target_id,
                kind,
                source.lane,
                target.lane,
                points,
                semantic_style(kind),
            )
        )
    max_right = max(
        max(card.bounds.x + card.bounds.width for card in cards),
        max((point.x for edge in routed for point in edge.points), default=0.0),
    )
    max_bottom = max(
        max(card.bounds.y + card.bounds.height for card in cards),
        max((point.y for edge in routed for point in edge.points), default=0.0),
    )
    return LayoutResult(
        cards,
        tuple(sorted(routed, key=lambda edge: edge.id)),
        max_right + margin,
        max_bottom + margin,
        bool(omitted_cards or omitted_edges),
        omitted_cards,
        omitted_edges,
    )


__all__ = [
    "ABSOLUTE_RENDERED_ITEM_LIMIT",
    "DEFAULT_CARD_LIMIT",
    "LayoutConfig",
    "LayoutEdge",
    "LayoutInput",
    "LayoutNode",
    "LayoutResult",
    "Point",
    "PositionedCard",
    "Rect",
    "RoutedEdge",
    "SemanticStyle",
    "layout_story_events",
    "semantic_style",
]
