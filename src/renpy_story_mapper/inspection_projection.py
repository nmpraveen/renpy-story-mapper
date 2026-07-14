"""Deterministic human-oriented projection of the M10 canonical graph.

This module owns presentation simplification only.  It never mutates canonical records and
every projected or suppressed item retains a canonical escape path.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from renpy_story_mapper.canonical_graph_contract import (
    CanonicalGraph,
    CanonicalNode,
    CanonicalRegion,
    stable_canonical_id,
)
from renpy_story_mapper.route_map import RouteEdge, RouteMap, RouteNode
from renpy_story_mapper.storage import canonical_json

INSPECTION_PROJECTION_SCHEMA_VERSION = 1
INSPECTION_PROJECTION_SCHEMA = f"m10-inspection-projection-v{INSPECTION_PROJECTION_SCHEMA_VERSION}"


@dataclass(frozen=True)
class InspectionNode:
    id: str
    kind: str
    title: str
    order: int
    lane_id: str
    canonical_node_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    attributes: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "order": self.order,
            "lane_id": self.lane_id,
            "canonical_node_ids": sorted(self.canonical_node_ids),
            "evidence_ids": sorted(self.evidence_ids),
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class InspectionEdge:
    id: str
    source_id: str
    target_id: str
    roles: tuple[str, ...]
    canonical_edge_ids: tuple[str, ...]
    route_edge_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    fact_ids: tuple[str, ...]
    technical_hops: int

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "roles": sorted(self.roles),
            "canonical_edge_ids": sorted(self.canonical_edge_ids),
            "route_edge_ids": list(self.route_edge_ids),
            "evidence_ids": sorted(self.evidence_ids),
            "fact_ids": sorted(self.fact_ids),
            "technical_hops": self.technical_hops,
        }


@dataclass(frozen=True)
class SuppressedRecord:
    route_node_id: str
    canonical_node_ids: tuple[str, ...]
    reason: str
    represented_by_node_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "route_node_id": self.route_node_id,
            "canonical_node_ids": sorted(self.canonical_node_ids),
            "reason": self.reason,
        }
        if self.represented_by_node_id is not None:
            value["represented_by_node_id"] = self.represented_by_node_id
        return value


@dataclass(frozen=True)
class InspectionRegion:
    canonical_region_id: str
    kind: str
    split_node_id: str | None
    merge_node_id: str | None
    outcome_node_ids: tuple[str, ...]
    canonical_member_node_ids: tuple[str, ...]
    persistence_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_region_id": self.canonical_region_id,
            "kind": self.kind,
            "split_node_id": self.split_node_id,
            "merge_node_id": self.merge_node_id,
            "outcome_node_ids": list(self.outcome_node_ids),
            "canonical_member_node_ids": sorted(self.canonical_member_node_ids),
            "persistence_reasons": sorted(self.persistence_reasons),
        }


@dataclass(frozen=True)
class InspectionProjection:
    source_generation: str
    canonical_graph_hash: str
    route_map_hash: str
    nodes: tuple[InspectionNode, ...]
    edges: tuple[InspectionEdge, ...]
    regions: tuple[InspectionRegion, ...]
    suppressed: tuple[SuppressedRecord, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": INSPECTION_PROJECTION_SCHEMA_VERSION,
            "schema": INSPECTION_PROJECTION_SCHEMA,
            "source_generation": self.source_generation,
            "canonical_graph_hash": self.canonical_graph_hash,
            "route_map_hash": self.route_map_hash,
            "nodes": [item.to_dict() for item in sorted(self.nodes, key=lambda item: item.id)],
            "edges": [item.to_dict() for item in sorted(self.edges, key=lambda item: item.id)],
            "regions": [
                item.to_dict()
                for item in sorted(self.regions, key=lambda item: item.canonical_region_id)
            ],
            "suppressed": [
                item.to_dict()
                for item in sorted(
                    self.suppressed,
                    key=lambda item: (item.route_node_id, item.reason),
                )
            ],
        }

    def normalized_bytes(self) -> bytes:
        return canonical_json(self.to_dict())

    @property
    def authority_hash(self) -> str:
        return hashlib.sha256(self.normalized_bytes()).hexdigest()

    def validate(self, canonical_graph: CanonicalGraph) -> None:
        node_ids = _unique((item.id for item in self.nodes), "inspection node")
        _unique((item.id for item in self.edges), "inspection edge")
        canonical_ids = {item.id for item in canonical_graph.nodes}
        for node in self.nodes:
            if not node.canonical_node_ids or not set(node.canonical_node_ids) <= canonical_ids:
                raise ValueError(f"inspection node {node.id} lacks valid canonical records")
        for edge in self.edges:
            if edge.source_id not in node_ids or edge.target_id not in node_ids:
                raise ValueError(f"inspection edge {edge.id} has an unknown endpoint")
        for item in self.suppressed:
            if not item.canonical_node_ids or not set(item.canonical_node_ids) <= canonical_ids:
                raise ValueError("suppression ledger must retain valid canonical records")
            if (
                item.represented_by_node_id is not None
                and item.represented_by_node_id not in node_ids
            ):
                raise ValueError("suppression representative must be a projected node")


def project_inspection_graph(
    canonical_graph: CanonicalGraph, route_map: RouteMap
) -> InspectionProjection:
    """Build a stable simplified quotient while preserving canonical escape paths."""

    canonical_by_graph = {item.graph_node_id: item for item in canonical_graph.nodes}
    canonical_by_id = {item.id: item for item in canonical_graph.nodes}
    canonical_edge_by_origin = _canonical_edges_by_route_origin(canonical_graph)
    outcomes, outcome_by_route, outcome_by_arm = _choice_outcomes(canonical_graph)

    projected: list[InspectionNode] = list(outcomes)
    route_to_projection: dict[str, str | None] = dict(outcome_by_route)
    suppressed: list[SuppressedRecord] = []
    for route_node in route_map.nodes:
        canonical = canonical_by_graph[route_node.control_node_id]
        if route_node.id in outcome_by_route:
            represented_by = outcome_by_route[route_node.id]
            suppressed.append(
                SuppressedRecord(
                    route_node.id,
                    (canonical.id,),
                    "choice_outcome_represented",
                    represented_by,
                )
            )
            continue
        reason = _suppression_reason(route_node, canonical)
        if reason is not None:
            route_to_projection[route_node.id] = None
            suppressed.append(SuppressedRecord(route_node.id, (canonical.id,), reason))
            continue
        node_id = stable_canonical_id("viewnode", "route", route_node.id, canonical.id)
        route_to_projection[route_node.id] = node_id
        projected.append(
            InspectionNode(
                node_id,
                route_node.kind.value,
                route_node.title,
                route_node.order * 100,
                route_node.lane_id,
                (canonical.id,),
                canonical.evidence_ids,
                {
                    "route_node_id": route_node.id,
                    "reachability": canonical.reachability.value,
                    "terminal_kind": route_node.terminal_kind,
                    "unresolved": route_node.unresolved,
                    "canonical_escape_id": canonical.id,
                    "source_kind": canonical.attributes.get("source_kind"),
                    "metadata": canonical.attributes.get("metadata"),
                },
            )
        )

    edges = _contract_route_edges(
        route_map.edges,
        route_to_projection,
        canonical_edge_by_origin,
    )
    regions = _project_regions(
        canonical_graph.regions,
        canonical_by_id,
        route_to_projection,
        outcome_by_arm,
    )
    result = InspectionProjection(
        canonical_graph.source_generation,
        canonical_graph.authority_hash,
        route_map.authority_hash,
        tuple(projected),
        tuple(edges),
        tuple(regions),
        tuple(suppressed),
    )
    result.validate(canonical_graph)
    return result


def _choice_outcomes(
    canonical_graph: CanonicalGraph,
) -> tuple[list[InspectionNode], dict[str, str], dict[str, str]]:
    canonical_by_id = {item.id: item for item in canonical_graph.nodes}
    canonical_edges = {item.id: item for item in canonical_graph.edges}
    outcomes: list[InspectionNode] = []
    by_route: dict[str, str] = {}
    by_arm: dict[str, str] = {}
    for region in canonical_graph.regions:
        split = canonical_by_id[region.split_node_id]
        if str(split.attributes.get("source_kind")) != "menu":
            continue
        for arm in _records(region.attributes.get("arms"), "canonical region arms"):
            entry = canonical_by_id[_text(arm, "entry_node_id")]
            caption = _caption(entry)
            arm_id = _text(arm, "id")
            node_id = stable_canonical_id("viewnode", "choice_outcome", region.id, arm_id)
            entry_edge = canonical_edges[_text(arm, "edge_id")]
            member_ids = tuple(
                sorted({_text(arm, "entry_node_id"), *_strings(arm.get("member_node_ids"))})
            )
            fact_ids = tuple(
                sorted(
                    {
                        *_strings(entry.attributes.get("fact_ids")),
                        *_strings(entry_edge.attributes.get("gate_ids")),
                        *_strings(entry_edge.attributes.get("effect_ids")),
                    }
                )
            )
            route = entry.attributes.get("route")
            route_id = _text(route, "id") if isinstance(route, Mapping) else ""
            if route_id:
                by_route[route_id] = node_id
            by_arm[arm_id] = node_id
            outcomes.append(
                InspectionNode(
                    node_id,
                    "choice_outcome",
                    caption,
                    _integer(arm, "ordinal") + _route_order(entry) * 100,
                    _route_lane(entry),
                    member_ids,
                    tuple(sorted({*entry.evidence_ids, *entry_edge.evidence_ids})),
                    {
                        "canonical_region_id": region.id,
                        "canonical_arm_id": arm_id,
                        "canonical_entry_node_id": entry.id,
                        "canonical_edge_id": entry_edge.id,
                        "canonical_escape_id": entry.id,
                        "ordinal": _integer(arm, "ordinal"),
                        "condition": _metadata_text(entry, "condition"),
                        "fact_ids": list(fact_ids),
                        "terminal_summary": str(arm.get("terminal_summary", "none")),
                        "unresolved": bool(arm.get("unresolved", False)),
                        "merge_node_id": region.merge_node_id,
                        "source_kind": entry.attributes.get("source_kind"),
                        "metadata": entry.attributes.get("metadata"),
                    },
                )
            )
    return outcomes, by_route, by_arm


def _contract_route_edges(
    route_edges: Sequence[RouteEdge],
    route_to_projection: Mapping[str, str | None],
    canonical_edge_by_origin: Mapping[str, str],
) -> list[InspectionEdge]:
    outgoing: dict[str, list[RouteEdge]] = defaultdict(list)
    for edge in sorted(route_edges, key=lambda item: item.id):
        outgoing[edge.source_id].append(edge)
    materialized: dict[tuple[str, str, tuple[str, ...]], InspectionEdge] = {}
    for route_source, projected_source in sorted(route_to_projection.items()):
        if projected_source is None:
            continue
        stack: list[tuple[str, tuple[RouteEdge, ...], frozenset[str]]] = [
            (route_source, (), frozenset())
        ]
        while stack:
            current, path, visited = stack.pop()
            for edge in reversed(outgoing.get(current, ())):
                if edge.id in visited:
                    continue
                next_path = (*path, edge)
                projected_target = route_to_projection.get(edge.target_id)
                if projected_target is None:
                    stack.append((edge.target_id, next_path, visited | {edge.id}))
                    continue
                if projected_target == projected_source:
                    continue
                route_ids = tuple(item.id for item in next_path)
                identity = (projected_source, projected_target, route_ids)
                canonical_ids = tuple(
                    sorted(
                        {
                            canonical_edge_by_origin[control_id]
                            for item in next_path
                            for control_id in item.control_edge_ids
                            if control_id in canonical_edge_by_origin
                        }
                    )
                )
                edge_id = stable_canonical_id(
                    "viewedge", projected_source, projected_target, *route_ids
                )
                materialized[identity] = InspectionEdge(
                    edge_id,
                    projected_source,
                    projected_target,
                    tuple(sorted({item.role for item in next_path})),
                    canonical_ids,
                    route_ids,
                    tuple(sorted({value for item in next_path for value in item.evidence_ids})),
                    tuple(
                        sorted(
                            {
                                value
                                for item in next_path
                                for value in (*item.gate_ids, *item.effect_ids)
                            }
                        )
                    ),
                    sum(item.technical_hops for item in next_path) + len(next_path) - 1,
                )
    return sorted(materialized.values(), key=lambda item: item.id)


def _project_regions(
    regions: Sequence[CanonicalRegion],
    canonical_by_id: Mapping[str, CanonicalNode],
    route_to_projection: Mapping[str, str | None],
    outcome_by_arm: Mapping[str, str],
) -> list[InspectionRegion]:
    result: list[InspectionRegion] = []
    for region in regions:
        split = _projection_id(canonical_by_id[region.split_node_id], route_to_projection)
        merge = (
            _projection_id(canonical_by_id[region.merge_node_id], route_to_projection)
            if region.merge_node_id is not None
            else None
        )
        arm_ids = [
            _text(arm, "id")
            for arm in _records(region.attributes.get("arms"), "canonical region arms")
        ]
        result.append(
            InspectionRegion(
                region.id,
                region.kind,
                split,
                merge,
                tuple(outcome_by_arm[item] for item in arm_ids if item in outcome_by_arm),
                region.member_node_ids,
                _strings(region.attributes.get("persistence_reasons")),
            )
        )
    return result


def _suppression_reason(route_node: RouteNode, canonical: CanonicalNode) -> str | None:
    if route_node.unresolved or route_node.kind.value == "unresolved":
        return None
    if route_node.terminal_kind in {"module_end", "procedure_return_boundary"}:
        return "support_only_terminal"
    source_kind = str(canonical.attributes.get("source_kind", ""))
    if (
        source_kind == "label"
        and route_node.kind.value == "milestone"
        and not route_node.evidence_ids
    ):
        return "routing_alias"
    if (
        bool(canonical.attributes.get("hidden")) or bool(canonical.attributes.get("synthetic"))
    ) and route_node.kind.value not in {"merge", "terminal", "unresolved"}:
        return "technical_record"
    return None


def _projection_id(
    canonical: CanonicalNode, route_to_projection: Mapping[str, str | None]
) -> str | None:
    route = canonical.attributes.get("route")
    if not isinstance(route, Mapping):
        return None
    return route_to_projection.get(_text(route, "id"))


def _canonical_edges_by_route_origin(canonical_graph: CanonicalGraph) -> dict[str, str]:
    result: dict[str, str] = {}
    for edge in canonical_graph.edges:
        for origin in edge.origins:
            if origin.collection == "m06_control_flow":
                result[origin.record_id] = edge.id
    return result


def _caption(node: CanonicalNode) -> str:
    caption = _metadata_text(node, "caption")
    if caption:
        return caption
    source_text = str(node.attributes.get("source_text", "")).strip()
    return source_text or node.label


def _metadata_text(node: CanonicalNode, key: str) -> str | None:
    metadata = node.attributes.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    value = metadata.get(key)
    return str(value) if isinstance(value, str) and value else None


def _route_order(node: CanonicalNode) -> int:
    route = node.attributes.get("route")
    return _integer(route, "order") if isinstance(route, Mapping) else 0


def _route_lane(node: CanonicalNode) -> str:
    route = node.attributes.get("route")
    return _text(route, "lane_id") if isinstance(route, Mapping) else "lane_unassigned"


def _records(value: object, name: str) -> tuple[Mapping[str, object], ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{name} must contain records")
    return cast(tuple[Mapping[str, object], ...], tuple(value))


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str))


def _text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} must be non-empty text")
    return item


def _integer(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"{key} must be an integer")
    return item


def _unique(values: Iterable[str], name: str) -> set[str]:
    materialized = list(values)
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"{name} ids must be unique")
    return set(materialized)
