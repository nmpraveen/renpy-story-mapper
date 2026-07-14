"""Bounded browser projections for the persisted M10 read models."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from renpy_story_mapper.storage import canonical_json

MAX_INSPECTION_NODES = 30
MAX_INSPECTION_EDGES = 180
MAX_DETAIL_RECORDS = 60
INSPECTION_VIEWS = frozenset({"simplified", "canonical"})


def inspection_page(
    projection: Mapping[str, object],
    canonical: Mapping[str, object],
    analysis_state: Mapping[str, object],
    *,
    view: str,
    offset: int,
    limit: int,
    edge_offset: int,
    edge_limit: int,
) -> dict[str, object]:
    if view not in INSPECTION_VIEWS:
        raise ValueError("inspection view must be simplified or canonical")
    if limit < 1 or limit > MAX_INSPECTION_NODES:
        raise ValueError("inspection node limit is outside the rendering boundary")
    if edge_limit < 1 or edge_limit > MAX_INSPECTION_EDGES:
        raise ValueError("inspection edge limit is outside the rendering boundary")

    nodes, edges = (
        _simplified_records(projection) if view == "simplified" else _canonical_records(canonical)
    )
    ordered_nodes = sorted(nodes, key=_node_order)
    node_slice = ordered_nodes[offset : offset + limit]
    node_ids = {str(item["id"]) for item in node_slice}
    incident = sorted(
        (
            item
            for item in edges
            if str(item["source_id"]) in node_ids or str(item["target_id"]) in node_ids
        ),
        key=lambda item: str(item["id"]),
    )
    edge_slice = incident[edge_offset : edge_offset + edge_limit]
    next_edge = (
        edge_offset + len(edge_slice) if edge_offset + len(edge_slice) < len(incident) else None
    )
    next_node = offset + len(node_slice) if offset + len(node_slice) < len(nodes) else None
    if next_edge is not None:
        next_node = None
    generation = _generation_status(projection, canonical, analysis_state, view)
    lanes = _lanes(node_slice)
    suppressed = _records(projection.get("suppressed"), "projection.suppressed")
    return {
        "schema_version": 1,
        "level": "route_map",
        "view": view,
        "source_generation": generation["source_generation"],
        "generation_status": generation,
        "authority_hash": _authority_hash(projection if view == "simplified" else canonical),
        "offset": offset,
        "limit": limit,
        "next_offset": next_node,
        "edge_offset": edge_offset,
        "edge_limit": edge_limit,
        "edge_next_offset": next_edge,
        "page_edge_total": len(incident),
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "nodes": node_slice,
        "edges": edge_slice,
        "lanes": lanes,
        "coverage": {
            "control_nodes": len(_records(canonical.get("nodes"), "canonical.nodes")),
            "visible_nodes": len(nodes),
            "technical_nodes": len(suppressed),
            "suppressed_records": len(suppressed),
        },
        "navigation": {
            "next": ({"offset": next_node, "edge_offset": 0} if next_node is not None else None)
        },
    }


def inspection_detail(
    projection: Mapping[str, object],
    canonical: Mapping[str, object],
    analysis_state: Mapping[str, object],
    *,
    view: str,
    element_id: str,
) -> dict[str, object]:
    if view not in INSPECTION_VIEWS:
        raise ValueError("inspection view must be simplified or canonical")
    nodes, edges = (
        _simplified_records(projection) if view == "simplified" else _canonical_records(canonical)
    )
    element = next((item for item in (*nodes, *edges) if item["id"] == element_id), None)
    if element is None:
        raise KeyError(element_id)
    is_node = any(item["id"] == element_id for item in nodes)
    if is_node:
        predecessors = [item["source_id"] for item in edges if item["target_id"] == element_id]
        successors = [item["target_id"] for item in edges if item["source_id"] == element_id]
        canonical_ids = _strings(element.get("canonical_node_ids"))
        evidence_ids = _strings(element.get("evidence_ids"))
        fact_ids = _strings(_attributes(element).get("fact_ids"))
    else:
        predecessors = [str(element["source_id"])]
        successors = [str(element["target_id"])]
        canonical_ids = _strings(element.get("canonical_edge_ids"))
        evidence_ids = _strings(element.get("evidence_ids"))
        fact_ids = _strings(element.get("fact_ids"))

    canonical_nodes = _records(canonical.get("nodes"), "canonical.nodes")
    canonical_edges = _records(canonical.get("edges"), "canonical.edges")
    canonical_records = [
        item for item in (*canonical_nodes, *canonical_edges) if item.get("id") in canonical_ids
    ]
    evidence_by_id = {
        str(item["id"]): item for item in _records(canonical.get("evidence"), "canonical.evidence")
    }
    facts_by_id = {
        str(item["id"]): item for item in _records(canonical.get("facts"), "canonical.facts")
    }
    evidence = [
        {**evidence_by_id[item], "kind": "source"}
        for item in evidence_ids
        if item in evidence_by_id
    ][:MAX_DETAIL_RECORDS]
    facts = [_display_fact(facts_by_id[item]) for item in fact_ids if item in facts_by_id][
        :MAX_DETAIL_RECORDS
    ]
    canonical_view_nodes, _ = _canonical_records(canonical)
    focus_id = _canonical_focus_id(element, canonical_ids, canonical_nodes, canonical_edges)
    focus_index = next(
        (
            index
            for index, item in enumerate(sorted(canonical_view_nodes, key=_node_order))
            if item["id"] == focus_id
        ),
        0,
    )
    return {
        "schema_version": 1,
        "level": "detail_evidence",
        "view": view,
        "element": element,
        "predecessor_ids": predecessors[:MAX_DETAIL_RECORDS],
        "successor_ids": successors[:MAX_DETAIL_RECORDS],
        "evidence_ids": list(evidence_ids),
        "evidence": evidence,
        "facts": facts,
        "requirements": [item for item in facts if item.get("kind") == "requirement"],
        "effects": [item for item in facts if item.get("kind") == "effect"],
        "canonical_escape_ids": list(canonical_ids),
        "canonical_records": canonical_records[:MAX_DETAIL_RECORDS],
        "canonical_record_total": len(canonical_records),
        "canonical_records_truncated": len(canonical_records) > MAX_DETAIL_RECORDS,
        "canonical_focus_id": focus_id,
        "canonical_focus_offset": (focus_index // MAX_INSPECTION_NODES) * MAX_INSPECTION_NODES,
        "generation_status": _generation_status(projection, canonical, analysis_state, view),
    }


def _canonical_focus_id(
    element: Mapping[str, object],
    canonical_ids: Sequence[str],
    canonical_nodes: Sequence[Mapping[str, object]],
    canonical_edges: Sequence[Mapping[str, object]],
) -> str | None:
    node_ids = {str(item["id"]) for item in canonical_nodes}
    attributes = _attributes(element)
    preferred = attributes.get("canonical_escape_id")
    if isinstance(preferred, str) and preferred in node_ids:
        return preferred
    direct = next((item for item in canonical_ids if item in node_ids), None)
    if direct is not None:
        return direct
    edge = next((item for item in canonical_edges if item.get("id") in canonical_ids), None)
    return str(edge["source_id"]) if edge is not None else None


def _simplified_records(
    projection: Mapping[str, object],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    nodes: list[dict[str, object]] = []
    for item in _records(projection.get("nodes"), "projection.nodes"):
        attributes = _attributes(item)
        nodes.append(
            {
                **dict(item),
                "lane_kind": _lane_kind(str(item.get("lane_id", ""))),
                "lane_label": _lane_label(str(item.get("lane_id", ""))),
                "summary": _summary(item, attributes),
                "unresolved": bool(attributes.get("unresolved", False)),
                "reachability": attributes.get("reachability"),
                "fact_ids": list(_strings(attributes.get("fact_ids"))),
                "gate_ids": list(_strings(attributes.get("fact_ids"))),
            }
        )
    edges: list[dict[str, object]] = []
    for item in _records(projection.get("edges"), "projection.edges"):
        roles = _strings(item.get("roles"))
        edges.append(
            {
                **dict(item),
                "role": roles[0] if roles else "transition",
                "gate_ids": list(_strings(item.get("fact_ids"))),
                "effect_ids": [],
            }
        )
    return nodes, edges


def _canonical_records(
    canonical: Mapping[str, object],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    nodes: list[dict[str, object]] = []
    order_fallback = 1_000_000
    for index, item in enumerate(_records(canonical.get("nodes"), "canonical.nodes")):
        attributes = _attributes(item)
        route = attributes.get("route")
        route_value = route if isinstance(route, Mapping) else {}
        lane_id = str(route_value.get("lane_id", "canonical-technical"))
        nodes.append(
            {
                "id": item["id"],
                "kind": item.get("kind", "script_unit"),
                "title": item.get("label", "Technical record"),
                "summary": _summary(item, attributes),
                "order": route_value.get("order", order_fallback + index),
                "lane_id": lane_id,
                "lane_kind": _lane_kind(lane_id),
                "lane_label": _lane_label(lane_id),
                "canonical_node_ids": [item["id"]],
                "evidence_ids": item.get("evidence_ids", []),
                "reachability": item.get("reachability"),
                "unresolved": item.get("kind") == "unresolved",
                "attributes": attributes,
            }
        )
    edges: list[dict[str, object]] = []
    for item in _records(canonical.get("edges"), "canonical.edges"):
        attributes = _attributes(item)
        edges.append(
            {
                "id": item["id"],
                "source_id": item["source_id"],
                "target_id": item["target_id"],
                "role": item.get("kind", "transition"),
                "canonical_edge_ids": [item["id"]],
                "evidence_ids": item.get("evidence_ids", []),
                "fact_ids": [
                    *_strings(attributes.get("gate_ids")),
                    *_strings(attributes.get("effect_ids")),
                ],
                "gate_ids": list(_strings(attributes.get("gate_ids"))),
                "effect_ids": list(_strings(attributes.get("effect_ids"))),
                "technical_hops": 0,
                "reachability": item.get("reachability"),
                "resolved": item.get("resolved"),
            }
        )
    return nodes, edges


def _generation_status(
    projection: Mapping[str, object],
    canonical: Mapping[str, object],
    state: Mapping[str, object],
    view: str,
) -> dict[str, object]:
    current = str(state.get("source_generation", ""))
    generation = str(
        (projection if view == "simplified" else canonical).get("source_generation", "")
    )
    return {
        "source_generation": generation,
        "current_source_generation": current,
        "freshness": "current" if generation and generation == current else "stale",
        "analysis_status": state.get("status", "unknown"),
        "canonical_availability": state.get("canonical_availability", "none"),
    }


def _display_fact(item: Mapping[str, object]) -> dict[str, object]:
    attributes = _attributes(item)
    expression = attributes.get("original_expression") or attributes.get("expression")
    return {
        **dict(item),
        "label": expression or item.get("kind", "fact"),
        "expression": expression or "",
    }


def _summary(item: Mapping[str, object], attributes: Mapping[str, object]) -> str:
    parts = [
        str(item.get("reachability") or attributes.get("reachability") or "").replace("_", " "),
        str(attributes.get("terminal_kind") or "").replace("_", " "),
        "unresolved" if attributes.get("unresolved") else "",
    ]
    return " · ".join(part for part in parts if part)


def _lanes(nodes: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    values: dict[str, dict[str, str]] = {}
    for item in nodes:
        lane_id = str(item.get("lane_id", "canonical-technical"))
        values[lane_id] = {
            "id": lane_id,
            "kind": str(item.get("lane_kind", _lane_kind(lane_id))),
            "label": str(item.get("lane_label", _lane_label(lane_id))),
        }
    return [values[key] for key in sorted(values)]


def _lane_kind(lane_id: str) -> str:
    return "spine" if lane_id in {"lane_spine", "canonical-technical"} else "detour"


def _lane_label(lane_id: str) -> str:
    if lane_id == "lane_spine":
        return "Story spine"
    if lane_id == "canonical-technical":
        return "Canonical technical graph"
    return "Branch"


def _node_order(item: Mapping[str, object]) -> tuple[int, str]:
    order = item.get("order")
    return (
        order if isinstance(order, int) and not isinstance(order, bool) else 1_000_000,
        str(item["id"]),
    )


def _authority_hash(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _attributes(item: Mapping[str, object]) -> Mapping[str, object]:
    value = item.get("attributes")
    return value if isinstance(value, Mapping) else {}


def _records(value: object, name: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{name} must contain records")
    return tuple(item for item in value if isinstance(item, Mapping))


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, str))
