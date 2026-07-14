"""Bounded browser projections for the persisted M10 read models."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from renpy_story_mapper.storage import canonical_json

MAX_INSPECTION_NODES = 30
MAX_INSPECTION_EDGES = 180
MAX_DETAIL_RECORDS = 60
MAX_SEARCH_RESULTS = 50
INSPECTION_VIEWS = frozenset({"simplified", "canonical"})


def inspection_page(
    projection: Mapping[str, object] | None,
    canonical: Mapping[str, object] | None,
    analysis_state: Mapping[str, object],
    *,
    view: str,
    offset: int,
    limit: int,
    edge_offset: int,
    edge_limit: int,
    query: str | None = None,
    focus: str | None = None,
    projection_unavailable_reason: str | None = None,
) -> dict[str, object]:
    if view not in INSPECTION_VIEWS:
        raise ValueError("inspection view must be simplified or canonical")
    if limit < 1 or limit > MAX_INSPECTION_NODES:
        raise ValueError("inspection node limit is outside the rendering boundary")
    if edge_limit < 1 or edge_limit > MAX_INSPECTION_EDGES:
        raise ValueError("inspection edge limit is outside the rendering boundary")

    if view == "simplified" and (projection is None or canonical is None):
        return _unavailable_response(
            view,
            projection_unavailable_reason or "projection_missing",
            analysis_state,
        )
    if view == "canonical" and canonical is None:
        return _unavailable_response(view, "canonical_missing", analysis_state)
    selected = projection if view == "simplified" else canonical
    assert selected is not None
    if view == "simplified":
        assert projection is not None
        nodes, edges = _simplified_records(projection)
    else:
        assert canonical is not None
        nodes, edges = _canonical_records(canonical)
    ordered_nodes = sorted(nodes, key=_node_order)
    search = None
    if canonical is not None and (query or focus):
        search = _search_records(
            projection,
            canonical,
            requested_view=view,
            query=query,
            focus=focus,
            page_size=limit,
        )
        search_focus = search.get("focus")
        if isinstance(search_focus, Mapping) and search_focus.get("target_view") == view:
            resolved_offset = search_focus.get("offset")
            if isinstance(resolved_offset, int) and not isinstance(resolved_offset, bool):
                offset = resolved_offset
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
    generation = _generation_status(selected, analysis_state)
    lanes = _lanes(node_slice)
    suppressed = (
        _records(projection.get("suppressed"), "projection.suppressed")
        if projection is not None
        else ()
    )
    canonical_nodes = (
        _records(canonical.get("nodes"), "canonical.nodes")
        if canonical is not None
        else ()
    )
    result: dict[str, object] = {
        "schema_version": 1,
        "status": "available",
        "level": "route_map",
        "view": view,
        "source_generation": generation["source_generation"],
        "generation_status": generation,
        "authority_hash": _authority_hash(selected),
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
            "control_nodes": len(canonical_nodes),
            "visible_nodes": len(nodes),
            "technical_nodes": len(suppressed),
            "suppressed_records": len(suppressed),
        },
        "navigation": {
            "next": ({"offset": next_node, "edge_offset": 0} if next_node is not None else None)
        },
    }
    if search is not None:
        result["search"] = search
    return result


def inspection_detail(
    projection: Mapping[str, object] | None,
    canonical: Mapping[str, object] | None,
    analysis_state: Mapping[str, object],
    *,
    view: str,
    element_id: str,
    projection_unavailable_reason: str | None = None,
) -> dict[str, object]:
    if view not in INSPECTION_VIEWS:
        raise ValueError("inspection view must be simplified or canonical")
    if view == "simplified" and (projection is None or canonical is None):
        return _unavailable_response(
            view,
            projection_unavailable_reason or "projection_missing",
            analysis_state,
        )
    if view == "canonical" and canonical is None:
        return _unavailable_response(view, "canonical_missing", analysis_state)
    selected = projection if view == "simplified" else canonical
    assert selected is not None and canonical is not None
    auxiliary = _auxiliary_detail(
        canonical,
        element_id,
        view=view,
        generation_status=_generation_status(selected, analysis_state),
    )
    if auxiliary is not None:
        return auxiliary
    nodes, edges = (
        _simplified_records(selected) if view == "simplified" else _canonical_records(canonical)
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
        fact_ids = tuple(
            sorted(
                {
                    *_strings(_attributes(element).get("fact_ids")),
                    *_strings(element.get("fact_ids")),
                }
            )
        )
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
    evidence_id_set = set(evidence_ids)
    fact_id_set = set(fact_ids)
    proof_id_set: set[str] = set()
    origins: list[Mapping[str, object]] = []
    for record in canonical_records:
        evidence_id_set.update(_strings(record.get("evidence_ids")))
        proof_id_set.update(_strings(record.get("proof_ids")))
        attributes = _attributes(record)
        fact_id_set.update(_strings(attributes.get("fact_ids")))
        fact_id_set.update(_strings(attributes.get("gate_ids")))
        fact_id_set.update(_strings(attributes.get("effect_ids")))
        origins.extend(_records(record.get("origins"), "canonical record origins"))
    evidence_by_id = {
        str(item["id"]): item for item in _records(canonical.get("evidence"), "canonical.evidence")
    }
    facts_by_id = {
        str(item["id"]): item for item in _records(canonical.get("facts"), "canonical.facts")
    }
    related_regions = _related_regions(canonical, canonical_ids)
    for region in related_regions:
        proof_id_set.update(_strings(region.get("proof_ids")))
        origins.extend(_records(region.get("origins"), "canonical region origins"))
    proofs_by_id = {
        str(item["id"]): item for item in _records(canonical.get("proofs"), "canonical.proofs")
    }
    for fact_id in fact_id_set:
        fact = facts_by_id.get(fact_id)
        if fact is not None:
            evidence_id_set.update(_strings(fact.get("evidence_ids")))
            origins.extend(_records(fact.get("origins"), "canonical fact origins"))
    evidence_ids = tuple(sorted(evidence_id_set))
    fact_ids = tuple(sorted(fact_id_set))
    proof_ids = tuple(sorted(proof_id_set))
    evidence = [
        {**evidence_by_id[item], "kind": "source"}
        for item in evidence_ids
        if item in evidence_by_id
    ][:MAX_DETAIL_RECORDS]
    facts = [_display_fact(facts_by_id[item]) for item in fact_ids if item in facts_by_id][
        :MAX_DETAIL_RECORDS
    ]
    proofs = [dict(proofs_by_id[item]) for item in proof_ids if item in proofs_by_id][
        :MAX_DETAIL_RECORDS
    ]
    linked_records = _linked_records(related_regions, facts, evidence, proofs)
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
        "status": "available",
        "level": "detail_evidence",
        "view": view,
        "element": element,
        "predecessor_ids": predecessors[:MAX_DETAIL_RECORDS],
        "successor_ids": successors[:MAX_DETAIL_RECORDS],
        "evidence_ids": list(evidence_ids),
        "evidence": evidence,
        "facts": facts,
        "proofs": proofs,
        "origins": _unique_mappings(origins)[:MAX_DETAIL_RECORDS],
        "regions": related_regions[:MAX_DETAIL_RECORDS],
        "linked_records": linked_records,
        "requirements": [item for item in facts if item.get("kind") == "requirement"],
        "effects": [item for item in facts if item.get("kind") == "effect"],
        "canonical_escape_ids": list(canonical_ids),
        "canonical_records": canonical_records[:MAX_DETAIL_RECORDS],
        "canonical_record_total": len(canonical_records),
        "canonical_records_truncated": len(canonical_records) > MAX_DETAIL_RECORDS,
        "canonical_focus_id": focus_id,
        "canonical_focus_offset": (focus_index // MAX_INSPECTION_NODES) * MAX_INSPECTION_NODES,
        "generation_status": _generation_status(selected, analysis_state),
    }


def _auxiliary_detail(
    canonical: Mapping[str, object],
    element_id: str,
    *,
    view: str,
    generation_status: Mapping[str, object],
) -> dict[str, object] | None:
    nodes = _records(canonical.get("nodes"), "canonical.nodes")
    edges = _records(canonical.get("edges"), "canonical.edges")
    regions = _records(canonical.get("regions"), "canonical.regions")
    facts = _records(canonical.get("facts"), "canonical.facts")
    evidence = _records(canonical.get("evidence"), "canonical.evidence")
    proofs = _records(canonical.get("proofs"), "canonical.proofs")
    region = next((item for item in regions if item.get("id") == element_id), None)
    fact = next((item for item in facts if item.get("id") == element_id), None)
    evidence_item = next((item for item in evidence if item.get("id") == element_id), None)
    proof = next((item for item in proofs if item.get("id") == element_id), None)
    if all(item is None for item in (region, fact, evidence_item, proof)):
        return None

    canonical_records: list[Mapping[str, object]] = []
    related_regions: list[dict[str, object]] = []
    fact_values: list[dict[str, object]] = []
    evidence_values: list[dict[str, object]] = []
    proof_values: list[dict[str, object]] = []
    origins: list[Mapping[str, object]] = []
    escape_ids: set[str] = set()
    enriched_region: dict[str, object] | None = None

    if region is not None:
        enriched_region = _region_detail(canonical, region)
        related_regions = [enriched_region]
        escape_ids.update(_strings(enriched_region.get("canonical_escape_ids")))
        canonical_records.extend(
            item for item in (*nodes, *edges) if str(item.get("id")) in escape_ids
        )
        fact_ids = set(_strings(enriched_region.get("fact_ids")))
        fact_values = [_display_fact(item) for item in facts if str(item["id"]) in fact_ids]
        proof_ids = set(_strings(region.get("proof_ids")))
        proof_values = [dict(item) for item in proofs if str(item["id"]) in proof_ids]
        origins.extend(_records(region.get("origins"), "canonical region origins"))
        element = {
            "id": element_id,
            "kind": "branch_region",
            "title": f"{str(region.get('kind', 'branch')).replace('_', ' ')} region",
            "summary": " · ".join(_strings(enriched_region.get("persistence_reasons")))
            or "Deterministic M06 branch region",
        }
        predecessors = [str(region["split_node_id"])]
        successors = [str(region["merge_node_id"])] if region.get("merge_node_id") else []
    elif fact is not None:
        fact_values = [_display_fact(fact)]
        fact_id = str(fact["id"])
        canonical_records = [
            item
            for item in (*nodes, *edges)
            if fact_id in _record_fact_ids(item)
        ]
        escape_ids.update(_record_escape_ids(canonical_records))
        related_regions = _related_regions(
            canonical, tuple(str(item["id"]) for item in canonical_records)
        )
        evidence_ids = set(_strings(fact.get("evidence_ids")))
        evidence_values = [
            {**item, "kind": "source"}
            for item in evidence
            if str(item["id"]) in evidence_ids
        ]
        origins.extend(_records(fact.get("origins"), "canonical fact origins"))
        display = _display_fact(fact)
        element = {
            "id": element_id,
            "kind": "fact",
            "title": str(display.get("label", "State fact")),
            "summary": str(fact.get("kind", "fact")).replace("_", " "),
        }
        predecessors = []
        successors = []
    elif evidence_item is not None:
        evidence_values = [{**evidence_item, "kind": "source"}]
        canonical_records = [
            item
            for item in (*nodes, *edges)
            if element_id in _strings(item.get("evidence_ids"))
        ]
        escape_ids.update(_record_escape_ids(canonical_records))
        origins.extend(_records(evidence_item.get("origins"), "canonical evidence origins"))
        source = evidence_item.get("source")
        path = source.get("path") if isinstance(source, Mapping) else None
        element = {
            "id": element_id,
            "kind": "evidence",
            "title": str(path or "Source evidence"),
            "summary": str(evidence_item.get("source_text", "Exact source evidence")),
        }
        predecessors = []
        successors = []
    else:
        assert proof is not None
        proof_values = [dict(proof)]
        canonical_records = [
            item
            for item in (*nodes, *edges, *regions)
            if element_id in _strings(item.get("proof_ids"))
        ]
        escape_ids.update(_record_escape_ids(canonical_records))
        related_regions = [dict(item) for item in canonical_records if item in regions]
        origins.extend(_records(proof.get("origins"), "canonical proof origins"))
        element = {
            "id": element_id,
            "kind": "proof",
            "title": str(proof.get("kind", "derivation proof")).replace("_", " "),
            "summary": str(proof.get("explanation", "Deterministic derivation")),
        }
        predecessors = []
        successors = []

    for fact_value in fact_values:
        evidence_ids = set(_strings(fact_value.get("evidence_ids")))
        evidence_values.extend(
            {**item, "kind": "source"}
            for item in evidence
            if str(item["id"]) in evidence_ids
        )
    focus_id, focus_offset = _focus_details(canonical, tuple(sorted(escape_ids)))
    linked_records = _linked_records(
        related_regions,
        fact_values,
        _unique_mappings(evidence_values),
        proof_values,
    )
    result: dict[str, object] = {
        "schema_version": 1,
        "status": "available",
        "level": "detail_evidence",
        "view": view,
        "element": element,
        "predecessor_ids": predecessors[:MAX_DETAIL_RECORDS],
        "successor_ids": successors[:MAX_DETAIL_RECORDS],
        "evidence_ids": [str(item["id"]) for item in evidence_values][
            :MAX_DETAIL_RECORDS
        ],
        "evidence": _unique_mappings(evidence_values)[:MAX_DETAIL_RECORDS],
        "facts": fact_values[:MAX_DETAIL_RECORDS],
        "requirements": [item for item in fact_values if item.get("kind") == "requirement"],
        "effects": [item for item in fact_values if item.get("kind") == "effect"],
        "proofs": proof_values[:MAX_DETAIL_RECORDS],
        "origins": _unique_mappings(origins)[:MAX_DETAIL_RECORDS],
        "regions": related_regions[:MAX_DETAIL_RECORDS],
        "linked_records": linked_records,
        "canonical_escape_ids": sorted(escape_ids)[:MAX_DETAIL_RECORDS],
        "canonical_records": [dict(item) for item in canonical_records][
            :MAX_DETAIL_RECORDS
        ],
        "canonical_record_total": len(canonical_records),
        "canonical_records_truncated": len(canonical_records) > MAX_DETAIL_RECORDS,
        "canonical_focus_id": focus_id,
        "canonical_focus_offset": focus_offset,
        "generation_status": dict(generation_status),
    }
    if enriched_region is not None:
        result["region"] = enriched_region
    return result


def _region_detail(
    canonical: Mapping[str, object], region: Mapping[str, object]
) -> dict[str, object]:
    nodes = {
        str(item["id"]): item for item in _records(canonical.get("nodes"), "canonical.nodes")
    }
    edges = {
        str(item["id"]): item for item in _records(canonical.get("edges"), "canonical.edges")
    }
    facts = {
        str(item["id"]): item for item in _records(canonical.get("facts"), "canonical.facts")
    }
    attributes = _attributes(region)
    arms: list[dict[str, object]] = []
    fact_ids: set[str] = set()
    escape_ids = {
        str(region["split_node_id"]),
        *_strings(region.get("member_node_ids")),
    }
    if region.get("merge_node_id") is not None:
        escape_ids.add(str(region["merge_node_id"]))
    region_fact_ids = _record_fact_ids(region)
    fact_ids.update(region_fact_ids)
    for arm in sorted(
        _records(attributes.get("arms"), "canonical region arms"),
        key=_arm_ordinal,
    ):
        edge_id = str(arm["edge_id"])
        entry_id = str(arm["entry_node_id"])
        edge = edges.get(edge_id, {})
        member_ids = {entry_id, *_strings(arm.get("member_node_ids"))}
        arm_fact_ids = _record_fact_ids(edge)
        for member_id in member_ids:
            arm_fact_ids.update(_record_fact_ids(nodes.get(member_id, {})))
        for candidate in edges.values():
            if candidate.get("source_id") in member_ids:
                arm_fact_ids.update(_record_fact_ids(candidate))
        fact_ids.update(arm_fact_ids)
        escape_ids.update((edge_id, *member_ids))
        arm_facts = [
            _display_fact(facts[item]) for item in sorted(arm_fact_ids) if item in facts
        ]
        arms.append(
            {
                **dict(arm),
                "member_count": len(_strings(arm.get("member_node_ids"))),
                "facts": arm_facts,
                "gate_facts": [
                    item for item in arm_facts if item.get("kind") == "requirement"
                ],
                "effect_facts": [item for item in arm_facts if item.get("kind") == "effect"],
            }
        )
    return {
        "id": region["id"],
        "classification": region.get("kind"),
        "kind": region.get("kind"),
        "split_node_id": region["split_node_id"],
        "merge_node_id": region.get("merge_node_id"),
        "ordered_arms": arms,
        "persistence_reasons": list(_strings(attributes.get("persistence_reasons"))),
        "single_entry": bool(attributes.get("single_entry", False)),
        "single_exit": bool(attributes.get("single_exit", False)),
        "unresolved_arm_count": sum(bool(item.get("unresolved")) for item in arms),
        "terminal_summaries": [str(item.get("terminal_summary", "none")) for item in arms],
        "fact_ids": sorted(fact_ids),
        "proof_ids": list(_strings(region.get("proof_ids"))),
        "origins": [dict(item) for item in _records(region.get("origins"), "region origins")],
        "canonical_escape_ids": sorted(escape_ids),
    }


def _record_fact_ids(record: Mapping[str, object]) -> set[str]:
    attributes = _attributes(record)
    return {
        *_strings(attributes.get("fact_ids")),
        *_strings(attributes.get("gate_ids")),
        *_strings(attributes.get("effect_ids")),
    }


def _arm_ordinal(arm: Mapping[str, object]) -> int:
    value = arm.get("ordinal")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _record_escape_ids(records: Sequence[Mapping[str, object]]) -> set[str]:
    result: set[str] = set()
    for record in records:
        record_id = record.get("id")
        if isinstance(record_id, str) and record_id.startswith("cnode_"):
            result.add(record_id)
        for key in ("source_id", "target_id", "split_node_id", "merge_node_id"):
            value = record.get(key)
            if isinstance(value, str) and value.startswith("cnode_"):
                result.add(value)
    return result


def _focus_details(
    canonical: Mapping[str, object], escape_ids: Sequence[str]
) -> tuple[str | None, int]:
    canonical_view_nodes, _ = _canonical_records(canonical)
    ordered = sorted(canonical_view_nodes, key=_node_order)
    escape = set(escape_ids)
    for index, node in enumerate(ordered):
        node_id = str(node["id"])
        if node_id in escape:
            return node_id, (index // MAX_INSPECTION_NODES) * MAX_INSPECTION_NODES
    return None, 0


def _related_regions(
    canonical: Mapping[str, object], canonical_ids: Sequence[str]
) -> list[dict[str, object]]:
    selected = set(canonical_ids)
    result: list[dict[str, object]] = []
    for region in _records(canonical.get("regions"), "canonical.regions"):
        attributes = _attributes(region)
        node_ids = {
            str(region["split_node_id"]),
            *_strings(region.get("member_node_ids")),
        }
        if region.get("merge_node_id") is not None:
            node_ids.add(str(region["merge_node_id"]))
        edge_ids = {
            str(arm["edge_id"])
            for arm in _records(attributes.get("arms"), "canonical region arms")
        }
        if not selected.intersection(node_ids | edge_ids):
            continue
        result.append(
            {
                **dict(region),
                "title": f"{str(region.get('kind', 'branch')).replace('_', ' ')} region",
                "persistence_reasons": list(
                    _strings(attributes.get("persistence_reasons"))
                ),
            }
        )
    return result


def _linked_records(
    regions: Sequence[Mapping[str, object]],
    facts: Sequence[Mapping[str, object]],
    evidence: Sequence[Mapping[str, object]],
    proofs: Sequence[Mapping[str, object]],
) -> list[dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for item in regions:
        item_id = str(item["id"])
        result[item_id] = {
            "id": item_id,
            "kind": "region",
            "title": str(item.get("title", item.get("kind", "Branch region"))).replace(
                "_", " "
            ),
        }
    for item in facts:
        item_id = str(item["id"])
        result[item_id] = {
            "id": item_id,
            "kind": "fact",
            "title": str(item.get("label", item.get("kind", "Fact"))),
        }
    for item in evidence:
        item_id = str(item["id"])
        result[item_id] = {"id": item_id, "kind": "evidence", "title": "Source evidence"}
    for item in proofs:
        item_id = str(item["id"])
        result[item_id] = {
            "id": item_id,
            "kind": "proof",
            "title": str(item.get("kind", "Derivation proof")).replace("_", " "),
        }
    return [result[key] for key in sorted(result)][:MAX_DETAIL_RECORDS]


def _unique_mappings(
    values: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    result: dict[bytes, dict[str, object]] = {}
    for item in values:
        materialized = dict(item)
        result[canonical_json(materialized)] = materialized
    return [result[key] for key in sorted(result)]


def _search_records(
    projection: Mapping[str, object] | None,
    canonical: Mapping[str, object],
    *,
    requested_view: str,
    query: str | None,
    focus: str | None,
    page_size: int,
) -> dict[str, object]:
    requested = (focus or query or "").strip()
    normalized = requested.casefold()
    exact_only = bool(focus)
    query_value = (query or focus or "").strip().casefold()
    canonical_nodes = _records(canonical.get("nodes"), "canonical.nodes")
    canonical_edges = _records(canonical.get("edges"), "canonical.edges")
    canonical_node_by_id = {str(item["id"]): item for item in canonical_nodes}
    evidence = {
        str(item["id"]): item
        for item in _records(canonical.get("evidence"), "canonical.evidence")
    }
    facts = {
        str(item["id"]): item for item in _records(canonical.get("facts"), "canonical.facts")
    }
    canonical_view_nodes, _canonical_view_edges = _canonical_records(canonical)
    ordered_canonical_nodes = sorted(canonical_view_nodes, key=_node_order)
    canonical_node_index = {
        str(item["id"]): index for index, item in enumerate(ordered_canonical_nodes)
    }
    ordered_simplified_nodes: list[dict[str, object]] = []
    simplified_representative: dict[str, str] = {}
    simplified_edge_representative: dict[str, str] = {}
    if projection is not None:
        simplified_nodes, simplified_edges = _simplified_records(projection)
        ordered_simplified_nodes = sorted(simplified_nodes, key=_node_order)
        simplified_ids = {str(item["id"]) for item in ordered_simplified_nodes}
        for node in ordered_simplified_nodes:
            for canonical_id in _strings(node.get("canonical_node_ids")):
                simplified_representative.setdefault(canonical_id, str(node["id"]))
        for suppression in _records(projection.get("suppressed"), "projection.suppressed"):
            representative = suppression.get("represented_by_node_id")
            if not isinstance(representative, str) or representative not in simplified_ids:
                continue
            for canonical_id in _strings(suppression.get("canonical_node_ids")):
                simplified_representative.setdefault(canonical_id, representative)
        for edge in simplified_edges:
            source_id = str(edge["source_id"])
            if source_id not in simplified_ids:
                source_id = str(edge["target_id"])
            for canonical_id in _strings(edge.get("canonical_edge_ids")):
                simplified_edge_representative.setdefault(canonical_id, source_id)
    simplified_node_index = {
        str(item["id"]): index for index, item in enumerate(ordered_simplified_nodes)
    }

    matches: list[tuple[int, int, dict[str, object]]] = []

    def search_authority_record(
        *,
        candidates: Sequence[tuple[str, str, str, str, bool, int]],
        canonical_id: str,
        canonical_page_target_id: str,
        title: str,
        record_order: int,
        representative_id: str | None,
    ) -> None:
        target_view = (
            "canonical"
            if requested_view == "canonical" or representative_id is None
            else "simplified"
        )
        canonical_offset = (
            canonical_node_index.get(canonical_page_target_id, 0) // page_size
        ) * page_size
        target_index = (
            simplified_node_index.get(representative_id, 0)
            if target_view == "simplified" and representative_id is not None
            else canonical_node_index.get(canonical_page_target_id, 0)
        )
        target_id = (
            representative_id
            if target_view == "simplified" and representative_id is not None
            else canonical_page_target_id
        )
        best: tuple[int, dict[str, object]] | None = None
        for value, field, record_id, record_kind, focusable, exact_priority in candidates:
            compared = value.casefold()
            if normalized == compared and (focusable or not exact_only):
                score = exact_priority
            elif not exact_only and normalized and compared.startswith(normalized):
                score = 4
            elif not exact_only and normalized and normalized in compared:
                score = 5
            else:
                continue
            match: dict[str, object] = {
                "element_id": target_id,
                "matched_record_id": record_id,
                "record_kind": record_kind,
                "canonical_id": canonical_id,
                "target_view": target_view,
                "offset": (target_index // page_size) * page_size,
                "canonical_page_target_id": canonical_page_target_id,
                "canonical_page_offset": canonical_offset,
                "visible_simplified_representative_id": representative_id,
                "field": field,
                "title": title,
            }
            candidate = (score, match)
            if best is None or (score, record_id, field) < (
                best[0],
                str(best[1]["matched_record_id"]),
                str(best[1]["field"]),
            ):
                best = candidate
        if best is not None:
            matches.append((best[0], record_order, best[1]))

    def add_candidate(
        candidates: list[tuple[str, str, str, str, bool, int]],
        value: object,
        field: str,
        record_id: str,
        record_kind: str,
        *,
        focusable: bool = False,
        exact_priority: int = 3,
    ) -> None:
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            text = str(value).strip()
            if text:
                candidates.append(
                    (text, field, record_id, record_kind, focusable, exact_priority)
                )

    def add_evidence_and_facts(
        candidates: list[tuple[str, str, str, str, bool, int]],
        record: Mapping[str, object],
    ) -> None:
        attributes = _attributes(record)
        for evidence_id in _strings(record.get("evidence_ids")):
            source_evidence = evidence.get(evidence_id)
            if source_evidence is None:
                continue
            add_candidate(
                candidates,
                source_evidence.get("source_text"),
                "source_text",
                evidence_id,
                "evidence",
            )
            source = source_evidence.get("source")
            if isinstance(source, Mapping):
                for field, value in _search_scalars(source, prefix="source"):
                    add_candidate(candidates, value, field, evidence_id, "evidence")
                path = source.get("path")
                start = source.get("start")
                if isinstance(path, str) and isinstance(start, Mapping):
                    line = start.get("line")
                    if isinstance(line, int) and not isinstance(line, bool):
                        add_candidate(
                            candidates,
                            f"{path}:{line}",
                            "source_location",
                            evidence_id,
                            "evidence",
                        )
        fact_ids = {
            *_strings(attributes.get("fact_ids")),
            *_strings(attributes.get("gate_ids")),
            *_strings(attributes.get("effect_ids")),
        }
        for fact_id in sorted(fact_ids):
            fact = facts.get(fact_id)
            if fact is not None:
                for field, value in _search_scalars(_attributes(fact), prefix="fact"):
                    add_candidate(candidates, value, field, fact_id, "fact")

    for index, raw in enumerate(canonical_nodes):
        canonical_id = str(raw["id"])
        candidates: list[tuple[str, str, str, str, bool, int]] = []
        add_candidate(
            candidates,
            canonical_id,
            "canonical_id",
            canonical_id,
            "canonical_node",
            focusable=True,
            exact_priority=0,
        )
        add_candidate(
            candidates,
            raw.get("graph_node_id"),
            "graph_node_id",
            canonical_id,
            "canonical_node",
            focusable=True,
            exact_priority=1,
        )
        add_candidate(
            candidates,
            raw.get("label"),
            "label",
            canonical_id,
            "canonical_node",
            focusable=True,
            exact_priority=2,
        )
        for field, value in _search_scalars(_attributes(raw)):
            add_candidate(candidates, value, field, canonical_id, "canonical_node")
        add_evidence_and_facts(candidates, raw)
        search_authority_record(
            candidates=candidates,
            canonical_id=canonical_id,
            canonical_page_target_id=canonical_id,
            title=str(raw.get("label") or "Technical record"),
            record_order=index,
            representative_id=simplified_representative.get(canonical_id),
        )

    edge_order_base = len(canonical_nodes)
    for index, raw in enumerate(canonical_edges):
        canonical_id = str(raw["id"])
        source_id = str(raw["source_id"])
        candidates = []
        add_candidate(
            candidates,
            canonical_id,
            "canonical_id",
            canonical_id,
            "canonical_edge",
            focusable=True,
            exact_priority=0,
        )
        add_candidate(
            candidates,
            raw.get("kind"),
            "edge_kind",
            canonical_id,
            "canonical_edge",
        )
        for field, value in _search_scalars(_attributes(raw)):
            add_candidate(candidates, value, field, canonical_id, "canonical_edge")
        add_evidence_and_facts(candidates, raw)
        source = canonical_node_by_id.get(source_id, {})
        search_authority_record(
            candidates=candidates,
            canonical_id=canonical_id,
            canonical_page_target_id=source_id,
            title=f"{source.get('label') or 'Technical'!s} edge",
            record_order=edge_order_base + index,
            representative_id=simplified_edge_representative.get(canonical_id),
        )

    matches.sort(key=lambda item: (item[0], item[1], str(item[2]["matched_record_id"])))
    materialized = [item[2] for item in matches[:MAX_SEARCH_RESULTS]]
    result: dict[str, object] = {
        "query": query_value,
        "requested": requested,
        "total_matches": len(matches),
        "matches": materialized,
        "truncated": len(matches) > MAX_SEARCH_RESULTS,
        "element_ids": (
            [materialized[0]["element_id"]]
            if materialized and materialized[0]["target_view"] == requested_view
            else []
        ),
    }
    if materialized:
        result["focus"] = materialized[0]
    return result


def _search_scalars(
    value: Mapping[str, object], *, prefix: str = "attributes"
) -> list[tuple[str, object]]:
    result: list[tuple[str, object]] = []
    pending: list[tuple[str, object]] = [(prefix, value)]
    while pending and len(result) < 200:
        path, item = pending.pop()
        if isinstance(item, Mapping):
            for key, nested in sorted(item.items(), reverse=True):
                pending.append((f"{path}.{key}", nested))
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            for index, nested in reversed(list(enumerate(item[:50]))):
                pending.append((f"{path}.{index}", nested))
        elif isinstance(item, (str, int)) and not isinstance(item, bool):
            result.append((path, item))
    return result


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
        unsupported_status = _unsupported_creator_status(attributes)
        nodes.append(
            {
                **dict(item),
                "source_kind": attributes.get("source_kind"),
                "lane_kind": _lane_kind(str(item.get("lane_id", ""))),
                "lane_label": _lane_label(str(item.get("lane_id", ""))),
                "summary": _summary(item, attributes),
                "unsupported_status": unsupported_status,
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
        unsupported_status = _unsupported_creator_status(attributes)
        route = attributes.get("route")
        route_value = route if isinstance(route, Mapping) else {}
        lane_id = str(route_value.get("lane_id", "canonical-technical"))
        nodes.append(
            {
                "id": item["id"],
                "kind": item.get("kind", "script_unit"),
                "source_kind": attributes.get("source_kind"),
                "title": item.get("label", "Technical record"),
                "summary": _summary(item, attributes),
                "unsupported_status": unsupported_status,
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
    selected: Mapping[str, object], state: Mapping[str, object]
) -> dict[str, object]:
    current = str(state.get("source_generation", ""))
    generation = str(selected.get("source_generation", ""))
    value: dict[str, object] = {
        "source_generation": generation,
        "current_source_generation": current,
        "freshness": "current" if generation and generation == current else "stale",
        "analysis_status": state.get("status", "unknown"),
        "canonical_availability": state.get("canonical_availability", "none"),
        "simplified_availability": state.get("simplified_availability", "none"),
        "last_known_good": bool(generation and generation != current),
        "completed_phases": _completed_phases(state),
    }
    failure = state.get("failure")
    if isinstance(failure, Mapping):
        value["failure"] = dict(failure)
    return value


def _unavailable_response(
    view: str,
    reason: str,
    state: Mapping[str, object],
) -> dict[str, object]:
    generation: dict[str, object] = {
        "source_generation": None,
        "current_source_generation": state.get("source_generation"),
        "freshness": "unavailable",
        "analysis_status": state.get("status", "unknown"),
        "canonical_availability": state.get("canonical_availability", "none"),
        "simplified_availability": state.get("simplified_availability", "none"),
        "last_known_good": False,
        "completed_phases": _completed_phases(state),
    }
    failure = state.get("failure")
    if isinstance(failure, Mapping):
        generation["failure"] = dict(failure)
    return {
        "schema_version": 1,
        "status": "unavailable",
        "view": view,
        "reason": reason,
        "generation_status": generation,
    }


def _completed_phases(state: Mapping[str, object]) -> list[str]:
    result: list[str] = []
    for item in _records(state.get("phases"), "analysis_state.phases"):
        phase = item.get("phase")
        if isinstance(phase, str):
            result.append(phase)
    return result


def _display_fact(item: Mapping[str, object]) -> dict[str, object]:
    attributes = _attributes(item)
    expression = attributes.get("original_expression") or attributes.get("expression")
    return {
        **dict(item),
        "label": expression or item.get("kind", "fact"),
        "expression": expression or "",
    }


def _summary(item: Mapping[str, object], attributes: Mapping[str, object]) -> str:
    unsupported_status = _unsupported_creator_status(attributes)
    if unsupported_status is not None:
        return unsupported_status
    parts = [
        str(item.get("reachability") or attributes.get("reachability") or "").replace("_", " "),
        str(attributes.get("terminal_kind") or "").replace("_", " "),
        "unresolved" if attributes.get("unresolved") else "",
    ]
    return " · ".join(part for part in parts if part)


def _unsupported_creator_status(attributes: Mapping[str, object]) -> str | None:
    metadata = attributes.get("metadata")
    metadata_value = metadata if isinstance(metadata, Mapping) else {}
    if (
        attributes.get("source_kind") == "opaque"
        and metadata_value.get("executed") is False
        and metadata_value.get("reason") == "embedded_python_not_executed"
    ):
        return "Unsupported creator Python · preserved, not executed"
    return None


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
