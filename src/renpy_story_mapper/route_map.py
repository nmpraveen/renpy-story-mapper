"""Deterministic two-level route-map projection over M06 control-flow facts.

The projection is intentionally presentation-neutral.  It exposes one bounded Route Map and
one directly addressable Detail/Evidence record; semantic beats remain evidence, never a third
public navigation level.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from renpy_story_mapper.storage import canonical_json

ROUTE_MAP_SCHEMA_VERSION = 1
DEFAULT_INITIAL_NODE_LIMIT = 30
MAX_ROUTE_PAGE_NODES = 30
MAX_ROUTE_PAGE_EDGES = 180
MAX_ROUTE_PAGE_ITEMS = 240


class RouteNodeKind(StrEnum):
    MILESTONE = "milestone"
    CHOICE = "choice"
    MERGE = "merge"
    LOOP = "loop"
    TERMINAL = "terminal"
    UNRESOLVED = "unresolved"


class RouteLaneKind(StrEnum):
    SPINE = "spine"
    DETOUR = "detour"
    PERSISTENT = "persistent"


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode()).hexdigest()[:20]
    return f"{prefix}_{digest}"


@dataclass(frozen=True)
class RouteCoverage:
    control_nodes: int
    visible_nodes: int
    technical_nodes: int
    unresolved_nodes: int
    corridor_count: int

    def to_dict(self) -> dict[str, int]:
        return {
            "control_nodes": self.control_nodes,
            "visible_nodes": self.visible_nodes,
            "technical_nodes": self.technical_nodes,
            "unresolved_nodes": self.unresolved_nodes,
            "corridor_count": self.corridor_count,
        }


@dataclass(frozen=True)
class RouteNode:
    id: str
    control_node_id: str
    kind: RouteNodeKind
    title: str
    lane_id: str
    lane_kind: RouteLaneKind
    order: int
    evidence_ids: tuple[str, ...]
    region_ids: tuple[str, ...] = ()
    terminal_kind: str | None = None
    unresolved: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "control_node_id": self.control_node_id,
            "kind": self.kind.value,
            "title": self.title,
            "lane_id": self.lane_id,
            "lane_kind": self.lane_kind.value,
            "order": self.order,
            "evidence_ids": list(self.evidence_ids),
            "region_ids": list(self.region_ids),
            "terminal_kind": self.terminal_kind,
            "unresolved": self.unresolved,
        }


@dataclass(frozen=True)
class RouteEdge:
    id: str
    source_id: str
    target_id: str
    role: str
    lane_id: str
    control_edge_ids: tuple[str, ...]
    control_node_ids: tuple[str, ...]
    gate_ids: tuple[str, ...]
    effect_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    technical_hops: int = 0
    proven_merge: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "role": self.role,
            "lane_id": self.lane_id,
            "control_edge_ids": list(self.control_edge_ids),
            "control_node_ids": list(self.control_node_ids),
            "gate_ids": list(self.gate_ids),
            "effect_ids": list(self.effect_ids),
            "evidence_ids": list(self.evidence_ids),
            "technical_hops": self.technical_hops,
            "proven_merge": self.proven_merge,
        }


@dataclass(frozen=True)
class RouteScope:
    id: str
    ordinal: int
    lane_id: str
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    input_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "ordinal": self.ordinal,
            "lane_id": self.lane_id,
            "node_ids": list(self.node_ids),
            "edge_ids": list(self.edge_ids),
            "evidence_ids": list(self.evidence_ids),
            "input_hash": self.input_hash,
        }


@dataclass(frozen=True)
class RouteEvidence:
    id: str
    kind: str
    source: Mapping[str, object] | None
    text: str
    payload: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "source": None if self.source is None else dict(self.source),
            "text": self.text,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class RouteMap:
    nodes: tuple[RouteNode, ...]
    edges: tuple[RouteEdge, ...]
    scopes: tuple[RouteScope, ...]
    coverage: RouteCoverage
    initial_node_limit: int = DEFAULT_INITIAL_NODE_LIMIT
    evidence: tuple[RouteEvidence, ...] = ()

    @property
    def initial_node_ids(self) -> tuple[str, ...]:
        """Stable bounded first viewport; authoritative topology remains complete."""

        ordered = sorted(self.nodes, key=lambda node: (node.order, node.id))
        return tuple(node.id for node in ordered[: self.initial_node_limit])

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": ROUTE_MAP_SCHEMA_VERSION,
            "presentation_levels": ["route_map", "detail_evidence"],
            "initial_node_limit": self.initial_node_limit,
            "initial_node_ids": list(self.initial_node_ids),
            "page_limits": {
                "nodes": MAX_ROUTE_PAGE_NODES,
                "edges": MAX_ROUTE_PAGE_EDGES,
                "items": MAX_ROUTE_PAGE_ITEMS,
            },
            "nodes": [item.to_dict() for item in self.nodes],
            "edges": [item.to_dict() for item in self.edges],
            "scopes": [item.to_dict() for item in self.scopes],
            "coverage": self.coverage.to_dict(),
            "evidence": [item.to_dict() for item in self.evidence],
        }

    def canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @property
    def authority_hash(self) -> str:
        return hashlib.sha256(self.canonical_json()).hexdigest()

    def detail(self, element_id: str) -> dict[str, object]:
        """Return the sole public detail/evidence contract for a map element."""

        evidence_by_id = {item.id: item for item in self.evidence}
        for node in self.nodes:
            if node.id == element_id:
                predecessors = tuple(e.source_id for e in self.edges if e.target_id == node.id)
                successors = tuple(e.target_id for e in self.edges if e.source_id == node.id)
                return {
                    "level": "detail_evidence",
                    "element": node.to_dict(),
                    "predecessor_ids": list(predecessors),
                    "successor_ids": list(successors),
                    "evidence_ids": list(node.evidence_ids),
                    "evidence": [
                        evidence_by_id[item].to_dict()
                        for item in node.evidence_ids
                        if item in evidence_by_id
                    ],
                    "back_target": "route_map",
                }
        for edge in self.edges:
            if edge.id == element_id:
                return {
                    "level": "detail_evidence",
                    "element": edge.to_dict(),
                    "predecessor_ids": [edge.source_id],
                    "successor_ids": [edge.target_id],
                    "evidence_ids": list(edge.evidence_ids),
                    "evidence": [
                        evidence_by_id[item].to_dict()
                        for item in edge.evidence_ids
                        if item in evidence_by_id
                    ],
                    "gate_ids": list(edge.gate_ids),
                    "effect_ids": list(edge.effect_ids),
                    "back_target": "route_map",
                }
        raise KeyError(f"unknown route-map element: {element_id}")

    def page(
        self,
        *,
        offset: int = 0,
        limit: int = DEFAULT_INITIAL_NODE_LIMIT,
        edge_offset: int = 0,
        edge_limit: int = MAX_ROUTE_PAGE_EDGES,
    ) -> dict[str, object]:
        """Return a hard-bounded deterministic slice without hiding authoritative topology."""

        return page_route_map_payload(
            self.to_dict(),
            offset=offset,
            limit=limit,
            edge_offset=edge_offset,
            edge_limit=edge_limit,
        )


def page_route_map_payload(
    route: Mapping[str, object],
    *,
    offset: int = 0,
    limit: int = DEFAULT_INITIAL_NODE_LIMIT,
    edge_offset: int = 0,
    edge_limit: int = MAX_ROUTE_PAGE_EDGES,
) -> dict[str, object]:
    """Page a persisted authoritative route payload under browser hard limits."""

    nodes = _records(route.get("nodes"), "route.nodes")
    edges = _records(route.get("edges"), "route.edges")
    ordered_nodes = tuple(sorted(nodes, key=_page_node_key))
    ordered_edges = tuple(
        sorted(
            edges,
            key=lambda edge: (
                _text(edge, "source_id"),
                _text(edge, "target_id"),
                _text(edge, "id"),
            ),
        )
    )
    if offset < 0:
        raise ValueError("page offset cannot be negative")
    if limit < 1 or limit > MAX_ROUTE_PAGE_NODES:
        raise ValueError("page limit must be between 1 and 30")
    if edge_offset < 0:
        raise ValueError("edge offset cannot be negative")
    if edge_limit < 1 or edge_limit > MAX_ROUTE_PAGE_EDGES:
        raise ValueError("edge limit must be between 1 and 180")
    page_nodes = ordered_nodes[offset : offset + limit]
    node_ids = {_text(node, "id") for node in page_nodes}
    candidate_edges = tuple(
        edge
        for edge in ordered_edges
        if edge.get("source_id") in node_ids or edge.get("target_id") in node_ids
    )
    item_edge_limit = min(edge_limit, MAX_ROUTE_PAGE_ITEMS - len(page_nodes))
    page_edges = candidate_edges[edge_offset : edge_offset + item_edge_limit]
    next_offset = offset + len(page_nodes)
    edge_next_offset = edge_offset + len(page_edges)
    nodes_remaining = max(0, len(ordered_nodes) - next_offset)
    edges_remaining = max(0, len(candidate_edges) - edge_next_offset)
    return {
        "level": "route_map",
        "offset": offset,
        "limit": limit,
        "edge_offset": edge_offset,
        "edge_limit": edge_limit,
        "total_nodes": len(ordered_nodes),
        "total_edges": len(ordered_edges),
        "page_edge_total": len(candidate_edges),
        "node_ids": [_text(node, "id") for node in page_nodes],
        "nodes": [dict(node) for node in page_nodes],
        "edges": [dict(edge) for edge in page_edges],
        "item_count": len(page_nodes) + len(page_edges),
        "next_offset": next_offset if nodes_remaining else None,
        "edge_next_offset": edge_next_offset if edges_remaining else None,
        "overflow": {
            "has_more_nodes": bool(nodes_remaining),
            "has_more_edges": bool(edges_remaining),
            "nodes_remaining": nodes_remaining,
            "edges_remaining": edges_remaining,
        },
        "limits": {
            "nodes": MAX_ROUTE_PAGE_NODES,
            "edges": MAX_ROUTE_PAGE_EDGES,
            "items": MAX_ROUTE_PAGE_ITEMS,
        },
    }


def _page_node_key(node: Mapping[str, object]) -> tuple[int, str]:
    order = node.get("order")
    if not isinstance(order, int):
        raise ValueError("route node order must be an integer")
    return order, _text(node, "id")


def project_route_map(
    control_flow: Mapping[str, object],
    semantic_story: Mapping[str, object],
    requirements: object = (),
    effects: object = (),
    *,
    initial_node_limit: int = DEFAULT_INITIAL_NODE_LIMIT,
) -> RouteMap:
    """Project M06 authority into a bounded, stable route map and pre-AI scopes."""

    if initial_node_limit < 1 or initial_node_limit > DEFAULT_INITIAL_NODE_LIMIT:
        raise ValueError("initial_node_limit must be between 1 and 30")
    raw_nodes = _records(control_flow.get("nodes"), "control_flow.nodes")
    raw_edges = _records(control_flow.get("edges"), "control_flow.edges")
    regions = _records(control_flow.get("regions"), "control_flow.regions")
    arms = _records(control_flow.get("arms"), "control_flow.arms")
    loops = _records(control_flow.get("loops"), "control_flow.loops")
    terminals = _records(control_flow.get("terminals"), "control_flow.terminals")
    beats = _records(semantic_story.get("beats"), "semantic_story.beats")
    if control_flow.get("schema_version") != 1 or semantic_story.get("schema_version") != 1:
        raise ValueError("unsupported deterministic authority schema")

    node_by_id = {_text(item, "id"): item for item in raw_nodes}
    edge_by_id = {_text(item, "id"): item for item in raw_edges}
    beat_by_control: dict[str, list[dict[str, object]]] = defaultdict(list)
    for beat in beats:
        for control_id in _strings(beat.get("graph_node_ids")):
            beat_by_control[control_id].append(beat)

    terminal_by_node = {_text(item, "node_id"): _text(item, "kind") for item in terminals}
    loop_nodes = {node for loop in loops for node in _strings(loop.get("node_ids"))}
    loop_entries = {
        entry
        for loop in loops
        for entry in (_strings(loop.get("entry_node_ids")) or _strings(loop.get("node_ids"))[:1])
    }
    regions_by_node: dict[str, list[dict[str, object]]] = defaultdict(list)
    meaningful: set[str] = set(terminal_by_node) | loop_entries
    for region in regions:
        split = _text(region, "split_node_id")
        meaningful.add(split)
        merge = region.get("merge_node_id")
        if isinstance(merge, str):
            meaningful.add(merge)
        for node_id in _strings(region.get("node_ids")):
            regions_by_node[node_id].append(region)
    meaningful.update(_text(arm, "entry_node_id") for arm in arms)
    unresolved_control: set[str] = set()
    for edge in raw_edges:
        if not bool(edge.get("resolved", True)) or _text(edge, "role") == "unresolved":
            endpoints = (_text(edge, "source"), _text(edge, "target"))
            meaningful.update(endpoints)
            unresolved_control.update(endpoints)
    # Labels anchor the spine. Routine narrative and technical chains stay inside
    # evidence-bearing corridors rather than becoming singleton route cards.
    meaningful.update(
        node_id for node_id, node in node_by_id.items() if str(node.get("kind")) == "label"
    )

    order_key = {
        node_id: _node_order(node, beat_by_control.get(node_id, []))
        for node_id, node in node_by_id.items()
    }
    selected = sorted(
        (node for node in meaningful if node in node_by_id), key=lambda item: order_key[item]
    )
    selected_set = set(selected)

    arms_by_node: dict[str, list[dict[str, object]]] = defaultdict(list)
    for arm in arms:
        owned = {
            _text(arm, "entry_node_id"),
            *_strings(arm.get("node_ids")),
            *_strings(arm.get("terminal_node_ids")),
        }
        for node_id in owned:
            arms_by_node[node_id].append(arm)
    route_nodes: list[RouteNode] = []
    control_to_route: dict[str, str] = {}
    lane_by_control: dict[str, tuple[str, RouteLaneKind]] = {}
    for ordinal, control_id in enumerate(selected):
        raw = node_by_id[control_id]
        owned_regions = sorted(
            regions_by_node.get(control_id, []), key=lambda item: _text(item, "id")
        )
        kind = _node_kind(control_id, raw, owned_regions, terminal_by_node, loop_nodes)
        lane_id, lane_kind = _lane(control_id, regions, arms_by_node)
        lane_by_control[control_id] = (lane_id, lane_kind)
        evidence_ids = tuple(
            sorted({_text(beat, "id") for beat in beat_by_control.get(control_id, [])})
        )
        route_id = _stable_id("route_node", control_id)
        control_to_route[control_id] = route_id
        unresolved = control_id in unresolved_control or any(
            _text(region, "classification") == "unresolved" for region in owned_regions
        )
        route_nodes.append(
            RouteNode(
                route_id,
                control_id,
                kind,
                _node_title(raw, beat_by_control.get(control_id, [])),
                lane_id,
                lane_kind,
                ordinal,
                evidence_ids,
                tuple(_text(item, "id") for item in owned_regions),
                terminal_by_node.get(control_id),
                unresolved,
            )
        )

    fact_requirements = _facts(requirements, node_by_id)
    fact_effects = _facts(effects, node_by_id)
    outgoing: dict[str, list[dict[str, object]]] = defaultdict(list)
    for edge in raw_edges:
        outgoing[_text(edge, "source")].append(edge)
    for values in outgoing.values():
        values.sort(key=lambda item: _text(item, "id"))
    route_edges: list[RouteEdge] = []
    seen_paths: set[tuple[str, str, tuple[str, ...]]] = set()
    for source in selected:
        queue: deque[tuple[str, tuple[str, ...]]] = deque(
            (_text(edge, "target"), (_text(edge, "id"),)) for edge in outgoing[source]
        )
        visited: set[str] = set()
        while queue:
            target, path = queue.popleft()
            if target in selected_set:
                key = (source, target, path)
                if source != target and key not in seen_paths:
                    seen_paths.add(key)
                    path_edges = [edge_by_id[item] for item in path]
                    route_edges.append(
                        _route_edge(
                            control_to_route,
                            source,
                            target,
                            path_edges,
                            fact_requirements,
                            fact_effects,
                            regions,
                            beat_by_control,
                            lane_by_control,
                        )
                    )
                continue
            if target in visited:
                continue
            visited.add(target)
            for edge in outgoing.get(target, []):
                if len(path) <= len(raw_nodes):
                    queue.append((_text(edge, "target"), (*path, _text(edge, "id"))))

    route_edges.sort(key=lambda item: (item.source_id, item.target_id, item.id))
    scopes = _build_scopes(route_nodes, route_edges)
    referenced_evidence = {
        evidence_id for node in route_nodes for evidence_id in node.evidence_ids
    } | {evidence_id for edge in route_edges for evidence_id in edge.evidence_ids}
    evidence = _evidence_records(beats, raw_edges, referenced_evidence)
    unresolved_count = sum(node.unresolved for node in route_nodes)
    coverage = RouteCoverage(
        len(raw_nodes),
        len(route_nodes),
        len(raw_nodes) - len(route_nodes),
        unresolved_count,
        sum(edge.technical_hops > 0 for edge in route_edges),
    )
    return RouteMap(
        tuple(route_nodes),
        tuple(route_edges),
        scopes,
        coverage,
        initial_node_limit,
        evidence,
    )


def _records(value: object, name: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{name} must be a list of objects")
    return [dict(item) for item in value]


def _text(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return ()
    return tuple(value)


def _node_order(
    node: Mapping[str, object], beats: Sequence[Mapping[str, object]]
) -> tuple[object, ...]:
    source = node.get("source")
    if isinstance(source, Mapping):
        start = source.get("start")
        if isinstance(start, Mapping):
            return (
                str(source.get("path", "")),
                int(start.get("line", 0)),
                int(start.get("column", 0)),
                _text(node, "id"),
            )
    for beat in beats:
        source = beat.get("source")
        if isinstance(source, Mapping):
            start = source.get("start")
            if isinstance(start, Mapping):
                return (
                    str(source.get("path", "")),
                    int(start.get("line", 0)),
                    0,
                    _text(node, "id"),
                )
    return ("~", 0, 0, _text(node, "id"))


def _node_kind(
    control_id: str,
    node: Mapping[str, object],
    regions: Sequence[Mapping[str, object]],
    terminals: Mapping[str, str],
    loop_nodes: set[str],
) -> RouteNodeKind:
    if control_id in terminals:
        return RouteNodeKind.TERMINAL
    if any(_text(region, "split_node_id") == control_id for region in regions):
        return RouteNodeKind.CHOICE
    if any(region.get("merge_node_id") == control_id for region in regions):
        return RouteNodeKind.MERGE
    if control_id in loop_nodes:
        return RouteNodeKind.LOOP
    if str(node.get("kind")) == "unresolved" or (
        not bool(node.get("hidden", False)) and "unresolved" in str(node.get("kind"))
    ):
        return RouteNodeKind.UNRESOLVED
    return RouteNodeKind.MILESTONE


def _lane(
    control_id: str,
    regions: Sequence[Mapping[str, object]],
    arms_by_node: Mapping[str, Sequence[Mapping[str, object]]],
) -> tuple[str, RouteLaneKind]:
    region_by_id = {_text(region, "id"): region for region in regions}
    owned_arms = arms_by_node.get(control_id, ())
    if owned_arms:
        # A nested local detour inside a persistent route stays in its persistent parent lane.
        arm = min(
            owned_arms,
            key=lambda item: (
                _text(region_by_id[_text(item, "region_id")], "classification")
                not in {"persistent_route", "terminal_split"},
                len(_strings(item.get("node_ids"))),
                _text(item, "id"),
            ),
        )
        region_id = _text(arm, "region_id")
        classification = _text(region_by_id[region_id], "classification")
        kind = (
            RouteLaneKind.PERSISTENT
            if classification in {"persistent_route", "terminal_split"}
            else RouteLaneKind.DETOUR
        )
        return _stable_id("lane", region_id, _text(arm, "id")), kind
    return "lane_spine", RouteLaneKind.SPINE


def _node_title(node: Mapping[str, object], beats: Sequence[Mapping[str, object]]) -> str:
    for beat in beats:
        content = beat.get("content")
        if isinstance(content, list):
            for item in content:
                if (
                    isinstance(item, Mapping)
                    and isinstance(item.get("text"), str)
                    and str(item["text"]).strip()
                ):
                    return str(item["text"]).strip()[:80]
    label = node.get("label")
    return str(label if isinstance(label, str) and label else node.get("kind", "Milestone"))[:80]


def _facts(
    value: object, node_by_id: Mapping[str, Mapping[str, object]]
) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = defaultdict(list)
    nodes_by_location: dict[tuple[str, int], list[str]] = defaultdict(list)
    for node_id, node in node_by_id.items():
        source = node.get("source")
        if not isinstance(source, Mapping):
            continue
        start = source.get("start")
        if isinstance(start, Mapping) and isinstance(start.get("line"), int):
            nodes_by_location[(str(source.get("path", "")), int(start["line"]))].append(node_id)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return {}
    for raw in value:
        converter = getattr(raw, "to_dict", None)
        if callable(converter):
            raw = converter()
        if not isinstance(raw, Mapping):
            continue
        fact_id = raw.get("id")
        if not isinstance(fact_id, str):
            continue
        evidence = raw.get("evidence")
        if isinstance(evidence, Mapping):
            evidence_node_id = evidence.get("graph_node_id") or evidence.get("node_id")
            if isinstance(evidence_node_id, str):
                result[evidence_node_id].append(fact_id)
                continue
            source_file = evidence.get("source_file")
            physical_line = evidence.get("physical_line")
            if isinstance(source_file, str) and isinstance(physical_line, int):
                for matched in nodes_by_location.get((source_file, physical_line), ()):
                    result[matched].append(fact_id)
    return {key: tuple(sorted(values)) for key, values in result.items()}


def _route_edge(
    control_to_route: Mapping[str, str],
    source: str,
    target: str,
    edges: Sequence[Mapping[str, object]],
    requirements: Mapping[str, tuple[str, ...]],
    effects: Mapping[str, tuple[str, ...]],
    regions: Sequence[Mapping[str, object]],
    beat_by_control: Mapping[str, Sequence[Mapping[str, object]]],
    lane_by_control: Mapping[str, tuple[str, RouteLaneKind]],
) -> RouteEdge:
    edge_ids = tuple(_text(edge, "id") for edge in edges)
    roles = tuple(_text(edge, "role") for edge in edges)
    traversed = (source, *(str(edge.get("target")) for edge in edges))
    gate_ids = tuple(sorted({item for node in traversed for item in requirements.get(node, ())}))
    effect_ids = tuple(sorted({item for node in traversed for item in effects.get(node, ())}))
    evidence_ids = tuple(
        sorted(
            {
                _stable_id("edge_evidence", _text(edge, "id"), str(ordinal))
                for edge in edges
                for ordinal, _item in enumerate(_edge_evidence(edge))
            }
            | {
                _text(beat, "id")
                for node_id in traversed
                for beat in beat_by_control.get(node_id, ())
            }
        )
    )
    proven_merge = any(region.get("merge_node_id") == target for region in regions)
    persistent_lane = _persistent_edge_lane(source, target, lane_by_control)
    role = _projected_edge_role(
        source,
        target,
        roles,
        regions,
        persistent=persistent_lane is not None,
    )
    lane_id = (
        persistent_lane
        if persistent_lane is not None
        else _stable_id("edge_lane", source, target, role)
    )
    edge_id = _stable_id(
        "route_edge", control_to_route[source], control_to_route[target], *edge_ids
    )
    return RouteEdge(
        edge_id,
        control_to_route[source],
        control_to_route[target],
        role,
        lane_id,
        edge_ids,
        tuple(traversed),
        gate_ids,
        effect_ids,
        evidence_ids,
        max(0, len(edges) - 1),
        proven_merge,
    )


def _persistent_edge_lane(
    source: str,
    target: str,
    lane_by_control: Mapping[str, tuple[str, RouteLaneKind]],
) -> str | None:
    source_lane, source_kind = lane_by_control[source]
    target_lane, target_kind = lane_by_control[target]
    if source_kind is RouteLaneKind.PERSISTENT and target_kind is RouteLaneKind.PERSISTENT:
        return source_lane if source_lane != target_lane else target_lane
    if target_kind is RouteLaneKind.PERSISTENT:
        return target_lane
    if source_kind is RouteLaneKind.PERSISTENT:
        return source_lane
    return None


def _projected_edge_role(
    source: str,
    target: str,
    roles: tuple[str, ...],
    regions: Sequence[Mapping[str, object]],
    *,
    persistent: bool,
) -> str:
    if len(roles) == 1:
        return roles[0]
    if not persistent:
        return "corridor"
    candidates: list[tuple[int, str, str]] = []
    for region in regions:
        owned = {
            _text(region, "split_node_id"),
            *_strings(region.get("node_ids")),
        }
        merge = region.get("merge_node_id")
        if isinstance(merge, str):
            owned.add(merge)
        if source in owned and target in owned:
            candidates.append((len(owned), _text(region, "id"), _text(region, "classification")))
    if candidates:
        return min(candidates)[2]
    return "persistent_route"


def _edge_evidence(edge: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    raw = edge.get("evidence")
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def _evidence_records(
    beats: Sequence[Mapping[str, object]],
    edges: Sequence[Mapping[str, object]],
    referenced: set[str],
) -> tuple[RouteEvidence, ...]:
    result: list[RouteEvidence] = []
    for beat in beats:
        beat_id = _text(beat, "id")
        if beat_id not in referenced:
            continue
        source = beat.get("source")
        result.append(
            RouteEvidence(
                beat_id,
                str(beat.get("kind", "beat")),
                source if isinstance(source, Mapping) else None,
                _evidence_text(beat),
                beat,
            )
        )
    for edge in edges:
        edge_id = _text(edge, "id")
        for ordinal, item in enumerate(_edge_evidence(edge)):
            evidence_id = _stable_id("edge_evidence", edge_id, str(ordinal))
            if evidence_id not in referenced:
                continue
            source = item.get("source")
            result.append(
                RouteEvidence(
                    evidence_id,
                    str(item.get("kind", edge.get("role", "edge"))),
                    source if isinstance(source, Mapping) else None,
                    str(item.get("source_text", item.get("kind", "Control transition"))),
                    item,
                )
            )
    return tuple(sorted(result, key=lambda item: item.id))


def _evidence_text(record: Mapping[str, object]) -> str:
    content = record.get("content")
    if isinstance(content, list):
        values = [
            str(item.get("text"))
            for item in content
            if isinstance(item, Mapping) and isinstance(item.get("text"), str)
        ]
        if values:
            return "\n".join(values)
    return str(record.get("kind", "Story evidence"))


def _build_scopes(nodes: Sequence[RouteNode], edges: Sequence[RouteEdge]) -> tuple[RouteScope, ...]:
    nodes_by_lane: dict[str, list[RouteNode]] = defaultdict(list)
    for node in nodes:
        nodes_by_lane[node.lane_id].append(node)
    result: list[RouteScope] = []
    for ordinal, (lane_id, lane_nodes) in enumerate(sorted(nodes_by_lane.items())):
        node_ids = tuple(item.id for item in sorted(lane_nodes, key=lambda item: item.order))
        node_set = set(node_ids)
        lane_edges = tuple(
            edge.id for edge in edges if edge.source_id in node_set or edge.target_id in node_set
        )
        evidence = tuple(
            sorted(
                {evidence for node in lane_nodes for evidence in node.evidence_ids}
                | {
                    evidence
                    for edge in edges
                    if edge.id in lane_edges
                    for evidence in edge.evidence_ids
                }
            )
        )
        scope_id = _stable_id("route_scope", lane_id, *node_ids, *lane_edges)
        payload = {
            "node_ids": list(node_ids),
            "edge_ids": list(lane_edges),
            "evidence_ids": list(evidence),
        }
        result.append(
            RouteScope(
                scope_id,
                ordinal,
                lane_id,
                node_ids,
                lane_edges,
                evidence,
                hashlib.sha256(canonical_json(payload)).hexdigest(),
            )
        )
    return tuple(result)
