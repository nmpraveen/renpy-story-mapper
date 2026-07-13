"""Deterministic, product-neutral bounded narrative windows over a complete route map."""

from __future__ import annotations

import hashlib
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from renpy_story_mapper.storage import canonical_json

BOUNDED_WINDOW_SCHEMA_VERSION = 1
MAX_WINDOW_NODES = 64
MAX_WINDOW_INTERNAL_EDGES = 256
MAX_WINDOW_BOUNDARY_EDGES = 256
MAX_WINDOW_EVIDENCE = 2_048
MAX_WINDOW_FACTS = 1_024


class BoundedWindowError(ValueError):
    """Raised when a requested window cannot be proven exact and bounded."""


@dataclass(frozen=True)
class WindowLimits:
    max_nodes: int = MAX_WINDOW_NODES
    max_internal_edges: int = MAX_WINDOW_INTERNAL_EDGES
    max_boundary_edges: int = MAX_WINDOW_BOUNDARY_EDGES
    max_evidence: int = MAX_WINDOW_EVIDENCE
    max_facts: int = MAX_WINDOW_FACTS

    def __post_init__(self) -> None:
        if min(
            self.max_nodes,
            self.max_internal_edges,
            self.max_boundary_edges,
            self.max_evidence,
            self.max_facts,
        ) <= 0:
            raise BoundedWindowError("bounded-window limits must be positive")


DEFAULT_WINDOW_LIMITS = WindowLimits()


@dataclass(frozen=True)
class BoundedNarrativeWindow:
    """Exact route authority selected for one short, consent-gated AI unit."""

    id: str
    selection_kind: str
    entry_node_id: str | None
    exit_node_id: str | None
    node_ids: tuple[str, ...]
    internal_edge_ids: tuple[str, ...]
    boundary_node_ids: tuple[str, ...]
    boundary_edge_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    fact_ids: tuple[str, ...]
    input_hash: str
    authority_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": BOUNDED_WINDOW_SCHEMA_VERSION,
            "id": self.id,
            "selection_kind": self.selection_kind,
            "entry_node_id": self.entry_node_id,
            "exit_node_id": self.exit_node_id,
            "node_ids": list(self.node_ids),
            "internal_edge_ids": list(self.internal_edge_ids),
            "boundary_node_ids": list(self.boundary_node_ids),
            "boundary_edge_ids": list(self.boundary_edge_ids),
            "evidence_ids": list(self.evidence_ids),
            "fact_ids": list(self.fact_ids),
            "input_hash": self.input_hash,
            "authority_hash": self.authority_hash,
        }

    def expectation(self) -> dict[str, object]:
        """Return the complete drift guard a later preparation request must echo."""

        return {
            key: value
            for key, value in self.to_dict().items()
            if key
            in {
                "id",
                "node_ids",
                "internal_edge_ids",
                "boundary_node_ids",
                "boundary_edge_ids",
                "evidence_ids",
                "fact_ids",
                "input_hash",
                "authority_hash",
            }
        }

    def selection_request(self) -> dict[str, object]:
        """Return an exact selection plus complete expectations for consent preparation."""

        selector: dict[str, object]
        if self.selection_kind == "anchors":
            selector = {
                "entry_node_id": self.entry_node_id,
                "exit_node_id": self.exit_node_id,
            }
        else:
            selector = {"node_ids": list(self.node_ids)}
        return {**selector, "expected": self.expectation()}


@dataclass(frozen=True)
class _RouteAuthority:
    authority_hash: str
    nodes: tuple[dict[str, object], ...]
    edges: tuple[dict[str, object], ...]
    evidence: tuple[dict[str, object], ...]
    nodes_by_id: dict[str, dict[str, object]]
    edges_by_id: dict[str, dict[str, object]]
    evidence_by_id: dict[str, dict[str, object]]
    node_order: dict[str, tuple[int, str]]


def build_bounded_narrative_window(
    route_map: Mapping[str, object],
    *,
    node_ids: Sequence[str] = (),
    entry_node_id: str | None = None,
    exit_node_id: str | None = None,
    expected: Mapping[str, object] | None = None,
    require_expected: bool = False,
    limits: WindowLimits = DEFAULT_WINDOW_LIMITS,
) -> BoundedNarrativeWindow:
    """Resolve and validate one exact induced window from complete RouteMap JSON.

    Explicit IDs select exactly those nodes. Anchor selection includes every node that is both
    reachable from ``entry_node_id`` and can reach ``exit_node_id``. The builder never adds a
    path or infers an edge: internal and boundary topology comes exclusively from RouteMap.
    """

    route = _validate_route_map(route_map)
    explicit = _unique_nonempty_strings(node_ids, "node_ids")
    uses_anchors = entry_node_id is not None or exit_node_id is not None
    if not explicit and not uses_anchors:
        raise BoundedWindowError("bounded narrative windows cannot be empty")
    if bool(explicit) == uses_anchors:
        raise BoundedWindowError(
            "select exactly one of explicit node_ids or entry_node_id/exit_node_id anchors"
        )
    if uses_anchors:
        entry = _required_id(entry_node_id, "entry_node_id")
        exit_ = _required_id(exit_node_id, "exit_node_id")
        _require_known(entry, route.nodes_by_id, "entry node")
        _require_known(exit_, route.nodes_by_id, "exit node")
        selected = _nodes_between_anchors(route, entry, exit_)
        selection_kind = "anchors"
    else:
        entry = None
        exit_ = None
        for node_id in explicit:
            _require_known(node_id, route.nodes_by_id, "route node")
        selected = set(explicit)
        selection_kind = "node_ids"

    if selected == set(route.nodes_by_id):
        raise BoundedWindowError("bounded narrative windows cannot expand to the full route map")
    ordered_nodes = tuple(sorted(selected, key=route.node_order.__getitem__))
    internal = tuple(
        edge
        for edge in route.edges
        if _text(edge, "source_id") in selected and _text(edge, "target_id") in selected
    )
    if len(ordered_nodes) > 1 and not _weakly_connected(ordered_nodes, internal):
        raise BoundedWindowError(
            "bounded narrative window node_ids are disconnected or non-contiguous"
        )
    boundary = tuple(
        edge
        for edge in route.edges
        if (_text(edge, "source_id") in selected) != (_text(edge, "target_id") in selected)
    )
    boundary_nodes = {
        endpoint
        for edge in boundary
        for endpoint in (_text(edge, "source_id"), _text(edge, "target_id"))
        if endpoint not in selected
    }
    ordered_boundary_nodes = tuple(sorted(boundary_nodes, key=route.node_order.__getitem__))
    internal_ids = tuple(_text(item, "id") for item in internal)
    boundary_ids = tuple(_text(item, "id") for item in boundary)
    evidence_ids = tuple(
        sorted(
            {
                evidence_id
                for item in (
                    *(route.nodes_by_id[node_id] for node_id in ordered_nodes),
                    *internal,
                    *boundary,
                )
                for evidence_id in _string_ids(item.get("evidence_ids"), "evidence_ids")
            }
        )
    )
    fact_ids = tuple(
        sorted(
            {
                fact_id
                for edge in (*internal, *boundary)
                for key in ("gate_ids", "effect_ids")
                for fact_id in _string_ids(edge.get(key), key)
            }
        )
    )
    _enforce_limits(
        ordered_nodes,
        internal_ids,
        boundary_ids,
        evidence_ids,
        fact_ids,
        limits,
    )
    material = {
        "schema_version": BOUNDED_WINDOW_SCHEMA_VERSION,
        "selection_kind": selection_kind,
        "entry_node_id": entry,
        "exit_node_id": exit_,
        "node_ids": list(ordered_nodes),
        "internal_edge_ids": list(internal_ids),
        "boundary_node_ids": list(ordered_boundary_nodes),
        "boundary_edge_ids": list(boundary_ids),
        "evidence_ids": list(evidence_ids),
        "fact_ids": list(fact_ids),
        "authority_hash": route.authority_hash,
    }
    input_hash = hashlib.sha256(canonical_json(material)).hexdigest()
    result = BoundedNarrativeWindow(
        id=f"bounded_window_{input_hash[:20]}",
        selection_kind=selection_kind,
        entry_node_id=entry,
        exit_node_id=exit_,
        node_ids=ordered_nodes,
        internal_edge_ids=internal_ids,
        boundary_node_ids=ordered_boundary_nodes,
        boundary_edge_ids=boundary_ids,
        evidence_ids=evidence_ids,
        fact_ids=fact_ids,
        input_hash=input_hash,
        authority_hash=route.authority_hash,
    )
    _validate_expectation(result, expected, require_expected=require_expected)
    return result


def build_window_from_request(
    route_map: Mapping[str, object],
    request: Mapping[str, object],
    *,
    require_expected: bool = True,
    limits: WindowLimits = DEFAULT_WINDOW_LIMITS,
) -> BoundedNarrativeWindow:
    """Build from the JSON-neutral request emitted by :meth:`selection_request`."""

    allowed = {"node_ids", "entry_node_id", "exit_node_id", "expected"}
    unknown = set(request) - allowed
    if unknown:
        raise BoundedWindowError(f"unknown bounded-window request fields: {sorted(unknown)}")
    raw_node_ids = request.get("node_ids", ())
    if not isinstance(raw_node_ids, Sequence) or isinstance(raw_node_ids, (str, bytes)):
        raise BoundedWindowError("node_ids must be an array of strings")
    raw_expected = request.get("expected")
    if raw_expected is not None and not isinstance(raw_expected, Mapping):
        raise BoundedWindowError("expected must be an object")
    entry = request.get("entry_node_id")
    exit_ = request.get("exit_node_id")
    if entry is not None and not isinstance(entry, str):
        raise BoundedWindowError("entry_node_id must be a string")
    if exit_ is not None and not isinstance(exit_, str):
        raise BoundedWindowError("exit_node_id must be a string")
    return build_bounded_narrative_window(
        route_map,
        node_ids=cast(Sequence[str], raw_node_ids),
        entry_node_id=entry,
        exit_node_id=exit_,
        expected=cast(Mapping[str, object] | None, raw_expected),
        require_expected=require_expected,
        limits=limits,
    )


def _validate_route_map(route_map: Mapping[str, object]) -> _RouteAuthority:
    if route_map.get("schema_version") != 1:
        raise BoundedWindowError("unsupported or incomplete RouteMap schema")
    nodes = _records(route_map.get("nodes"), "nodes")
    edges = _records(route_map.get("edges"), "edges")
    evidence = _records(route_map.get("evidence"), "evidence")
    if not nodes:
        raise BoundedWindowError("complete RouteMap payload has no nodes")
    nodes_by_id = _unique_records(nodes, "node")
    edges_by_id = _unique_records(edges, "edge")
    evidence_by_id = _unique_records(evidence, "evidence")
    orders: dict[int, str] = {}
    node_order: dict[str, tuple[int, str]] = {}
    for node_id, node in nodes_by_id.items():
        order = node.get("order")
        if not isinstance(order, int) or isinstance(order, bool) or order < 0:
            raise BoundedWindowError(f"route node {node_id} has an invalid order")
        if order in orders:
            raise BoundedWindowError("route node orders must be unique")
        orders[order] = node_id
        node_order[node_id] = (order, node_id)
        _validate_evidence_references(node, evidence_by_id, f"route node {node_id}")
    for edge_id, edge in edges_by_id.items():
        _require_known(_text(edge, "source_id"), nodes_by_id, f"edge {edge_id} source")
        _require_known(_text(edge, "target_id"), nodes_by_id, f"edge {edge_id} target")
        _validate_evidence_references(edge, evidence_by_id, f"route edge {edge_id}")
        _string_ids(edge.get("gate_ids"), "gate_ids")
        _string_ids(edge.get("effect_ids"), "effect_ids")
    return _RouteAuthority(
        hashlib.sha256(canonical_json(route_map)).hexdigest(),
        nodes,
        edges,
        evidence,
        nodes_by_id,
        edges_by_id,
        evidence_by_id,
        node_order,
    )


def _nodes_between_anchors(route: _RouteAuthority, entry: str, exit_: str) -> set[str]:
    outgoing: dict[str, set[str]] = {node_id: set() for node_id in route.nodes_by_id}
    incoming: dict[str, set[str]] = {node_id: set() for node_id in route.nodes_by_id}
    for edge in route.edges:
        source = _text(edge, "source_id")
        target = _text(edge, "target_id")
        outgoing[source].add(target)
        incoming[target].add(source)
    forward = _reachable(entry, outgoing)
    if exit_ not in forward:
        raise BoundedWindowError("exit_node_id is not reachable from entry_node_id")
    return forward & _reachable(exit_, incoming)


def _reachable(start: str, adjacency: Mapping[str, set[str]]) -> set[str]:
    found = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for candidate in adjacency[current]:
            if candidate not in found:
                found.add(candidate)
                queue.append(candidate)
    return found


def _weakly_connected(
    node_ids: Sequence[str], edges: Sequence[Mapping[str, object]]
) -> bool:
    selected = set(node_ids)
    adjacent: dict[str, set[str]] = {item: set() for item in node_ids}
    for edge in edges:
        source = _text(edge, "source_id")
        target = _text(edge, "target_id")
        adjacent[source].add(target)
        adjacent[target].add(source)
    return _reachable(node_ids[0], adjacent) == selected


def _validate_expectation(
    result: BoundedNarrativeWindow,
    expected: Mapping[str, object] | None,
    *,
    require_expected: bool,
) -> None:
    keys = {
        "id",
        "node_ids",
        "internal_edge_ids",
        "boundary_node_ids",
        "boundary_edge_ids",
        "evidence_ids",
        "fact_ids",
        "input_hash",
        "authority_hash",
    }
    if expected is None:
        if require_expected:
            raise BoundedWindowError("complete expected bounded-window IDs and hashes are required")
        return
    if set(expected) != keys:
        raise BoundedWindowError("expected bounded-window IDs and hashes are incomplete")
    actual = result.expectation()
    for key in keys:
        value = expected[key]
        if key.endswith("_ids"):
            if not isinstance(value, list):
                raise BoundedWindowError(f"expected {key} must be an array")
            _unique_nonempty_strings(value, f"expected {key}")
        elif not isinstance(value, str) or not value:
            raise BoundedWindowError(f"expected {key} must be a non-empty string")
        if value != actual[key]:
            raise BoundedWindowError(f"bounded-window selection drifted at {key}")


def _enforce_limits(
    node_ids: Sequence[str],
    internal_edge_ids: Sequence[str],
    boundary_edge_ids: Sequence[str],
    evidence_ids: Sequence[str],
    fact_ids: Sequence[str],
    limits: WindowLimits,
) -> None:
    counts = {
        "nodes": (len(node_ids), limits.max_nodes),
        "internal edges": (len(internal_edge_ids), limits.max_internal_edges),
        "boundary edges": (len(boundary_edge_ids), limits.max_boundary_edges),
        "evidence records": (len(evidence_ids), limits.max_evidence),
        "facts": (len(fact_ids), limits.max_facts),
    }
    for name, (actual, maximum) in counts.items():
        if actual > maximum:
            raise BoundedWindowError(
                f"bounded narrative window exceeds {name} limit ({actual} > {maximum})"
            )


def _records(value: object, name: str) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise BoundedWindowError(f"complete RouteMap {name} must be an array of objects")
    return tuple(dict(item) for item in value)


def _unique_records(
    records: Sequence[dict[str, object]], name: str
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for record in records:
        identifier = _text(record, "id")
        if identifier in result:
            raise BoundedWindowError(f"duplicate {name} ID: {identifier}")
        result[identifier] = record
    return result


def _validate_evidence_references(
    record: Mapping[str, object],
    evidence_by_id: Mapping[str, object],
    owner: str,
) -> None:
    for evidence_id in _string_ids(record.get("evidence_ids"), "evidence_ids"):
        if evidence_id not in evidence_by_id:
            raise BoundedWindowError(f"{owner} references unknown evidence: {evidence_id}")


def _string_ids(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise BoundedWindowError(f"{name} must be an array of strings")
    return _unique_nonempty_strings(value, name)


def _unique_nonempty_strings(value: Sequence[object], name: str) -> tuple[str, ...]:
    if any(not isinstance(item, str) or not item for item in value):
        raise BoundedWindowError(f"{name} must contain non-empty strings")
    result = cast(tuple[str, ...], tuple(value))
    if len(set(result)) != len(result):
        raise BoundedWindowError(f"{name} contains duplicate IDs")
    return result


def _text(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise BoundedWindowError(f"{key} must be a non-empty string")
    return value


def _required_id(value: str | None, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise BoundedWindowError(f"{name} must be a non-empty string")
    return value


def _require_known(identifier: str, records: Mapping[str, object], name: str) -> None:
    if identifier not in records:
        raise BoundedWindowError(f"unknown {name} ID: {identifier}")
