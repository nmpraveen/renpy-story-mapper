"""Bounded, reference-only browser adapter for a published M11 scene model."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from renpy_story_mapper.storage import canonical_json

MAX_SCENE_NODES = 30
MAX_SCENE_RELATIONSHIPS = 180
MAX_SCENE_DETAIL_REFERENCES = 60
MAX_SCENE_MAP_MEMBERSHIP_REFERENCES = 240
MAX_SCENE_SEARCH_RESULTS = 50


class _ReferenceBudget:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    def take(self, values: object) -> tuple[list[str], int]:
        references = list(_strings(values))
        available = max(0, self.limit - self.used)
        selected = references[:available]
        self.used += len(selected)
        return selected, len(references)


def scene_page(
    model: Mapping[str, object] | None,
    presentation: Mapping[str, object] | None,
    *,
    current_source_generation: str,
    current_canonical_hash: str,
    offset: int = 0,
    limit: int = MAX_SCENE_NODES,
    relationship_offset: int = 0,
    relationship_limit: int = MAX_SCENE_RELATIONSHIPS,
    query: str | None = None,
    focus: str | None = None,
) -> dict[str, object]:
    """Return one bounded page of the explicit M11 presentation graph.

    Relationships are never reconstructed from canonical topology.  Only relationships
    recorded by the presentation phase and incident to the selected page are returned.
    """

    _validate_window(offset, limit, relationship_offset, relationship_limit)
    reason = _availability_reason(
        model,
        presentation,
        current_source_generation,
        current_canonical_hash,
    )
    if reason is not None:
        return _unavailable(reason, current_source_generation, current_canonical_hash)
    assert model is not None and presentation is not None

    indexes = _indexes(model)
    nodes = _map_nodes(model, presentation, indexes)
    ordered = sorted(nodes, key=lambda item: (_required_int(item["page_order"]), str(item["id"])))
    search = _search(ordered, indexes, query=query, focus=focus, page_size=limit)
    search_focus = search.get("focus") if search is not None else None
    if isinstance(search_focus, Mapping):
        focus_offset = search_focus.get("offset")
        if isinstance(focus_offset, int) and not isinstance(focus_offset, bool):
            offset = focus_offset

    raw_page_nodes = ordered[offset : offset + limit]
    page_scene_ids = {
        scene_id
        for item in raw_page_nodes
        if isinstance((scene_id := item.get("scene_id")), str)
    }
    page_chapter_ids = {
        chapter_id
        for item in raw_page_nodes
        if isinstance((chapter_id := item.get("chapter_id")), str)
    }
    page_lane_ids = {
        lane_id
        for item in raw_page_nodes
        for lane_id in (
            *_strings(item.get("lane_ancestry")),
            *((item.get("lane_id"),) if isinstance(item.get("lane_id"), str) else ()),
        )
    }
    membership_budget = _ReferenceBudget(MAX_SCENE_MAP_MEMBERSHIP_REFERENCES)
    page_nodes = [
        _bounded_record(item, membership_budget)
        for item in raw_page_nodes
    ]
    page_ids = {str(item["id"]) for item in page_nodes}
    all_ids = {str(item["id"]) for item in ordered}
    relationships = _relationships(presentation, all_ids)
    incident = [
        item
        for item in relationships
        if str(item["source_id"]) in page_ids or str(item["target_id"]) in page_ids
    ]
    page_relationships = incident[
        relationship_offset : relationship_offset + relationship_limit
    ]
    relationship_next = (
        relationship_offset + len(page_relationships)
        if relationship_offset + len(page_relationships) < len(incident)
        else None
    )
    next_offset = offset + len(page_nodes) if offset + len(page_nodes) < len(ordered) else None
    if relationship_next is not None:
        next_offset = None
    chapter_bands = [
        _bounded_record(item, membership_budget)
        for item in _chapter_bands(
            presentation,
            indexes,
            page_scene_ids,
            page_chapter_ids,
            page_lane_ids,
        )
    ]
    lane_summaries = [
        _bounded_record(item, membership_budget)
        for item in _lane_summaries(
            presentation, indexes, page_scene_ids, page_lane_ids
        )
    ]

    result: dict[str, object] = {
        "schema_version": 1,
        "status": "available",
        "level": "scene_map",
        "source_generation": current_source_generation,
        "canonical_hash": current_canonical_hash,
        "scene_model_hash": _model_hash(model),
        "offset": offset,
        "limit": limit,
        "next_offset": next_offset,
        "relationship_offset": relationship_offset,
        "relationship_limit": relationship_limit,
        "relationship_next_offset": relationship_next,
        "page_relationship_total": len(incident),
        "total_nodes": len(ordered),
        "total_relationships": len(relationships),
        "nodes": page_nodes,
        "relationships": page_relationships,
        "chapter_bands": chapter_bands,
        "chapter_total": len(
            _records(presentation.get("chapter_bands"), "presentation.chapter_bands")
        ),
        "lanes": lane_summaries,
        "lane_total": len(_records(presentation.get("lanes"), "presentation.lanes")),
        "membership_reference_limit": MAX_SCENE_MAP_MEMBERSHIP_REFERENCES,
        "membership_reference_count": membership_budget.used,
        "navigation": {
            "next": (
                {"offset": next_offset, "relationship_offset": 0}
                if next_offset is not None
                else None
            )
        },
    }
    if search is not None:
        result["search"] = search
    return result


def scene_detail(
    model: Mapping[str, object] | None,
    presentation: Mapping[str, object] | None,
    canonical: Mapping[str, object] | None,
    *,
    current_source_generation: str,
    current_canonical_hash: str,
    element_id: str,
) -> dict[str, object]:
    """Return deterministic M11 detail and matching current-canonical evidence."""

    reason = _availability_reason(
        model,
        presentation,
        current_source_generation,
        current_canonical_hash,
    )
    if reason is not None:
        return _unavailable(reason, current_source_generation, current_canonical_hash)
    if canonical is None:
        return _unavailable("canonical_missing", current_source_generation, current_canonical_hash)
    if canonical.get("source_generation") != current_source_generation:
        return _unavailable(
            "canonical_generation_mismatch",
            current_source_generation,
            current_canonical_hash,
        )
    if _content_hash(canonical) != current_canonical_hash:
        return _unavailable(
            "canonical_hash_mismatch",
            current_source_generation,
            current_canonical_hash,
        )
    assert model is not None and presentation is not None

    indexes = _indexes(model)
    selected_node = next(
        (
            item
            for item in _records(presentation.get("nodes"), "presentation.nodes")
            if item.get("id") == element_id
        ),
        None,
    )
    scene_id = _node_scene_id(selected_node) if selected_node is not None else None
    branch_id = _node_branch_id(selected_node) if selected_node is not None else None
    occurrence_id: str | None = None
    if element_id in indexes["scenes"]:
        scene_id = element_id
    elif element_id in indexes["branches"]:
        branch_id = element_id
    elif element_id in indexes["occurrences"]:
        occurrence_id = element_id
        scene_value = indexes["occurrences"][element_id].get("scene_id")
        scene_id = scene_value if isinstance(scene_value, str) else None

    scene = indexes["scenes"].get(scene_id or "")
    branch = indexes["branches"].get(branch_id or "")
    occurrence = indexes["occurrences"].get(occurrence_id or "")
    lane = indexes["lanes"].get(element_id)
    chapter = indexes["chapters"].get(element_id)
    boundary = indexes["boundaries"].get(element_id)
    selected_hub = indexes["hubs"].get(element_id)
    if (
        scene is None
        and branch is None
        and selected_hub is None
        and lane is None
        and chapter is None
        and boundary is None
    ):
        raise KeyError(element_id)

    atoms: list[Mapping[str, object]] = []
    branches: list[Mapping[str, object]] = []
    occurrences: list[Mapping[str, object]] = []
    hubs: list[Mapping[str, object]] = []
    related_scenes: list[Mapping[str, object]] = []
    if scene is not None:
        if occurrence is not None:
            atoms = _referenced(indexes["atoms"], occurrence.get("referenced_atom_ids"))
            occurrences = [occurrence]
        else:
            atoms = _referenced(indexes["atoms"], scene.get("atom_ids"))
            branches = _referenced(indexes["branches"], scene.get("temporary_branch_ids"))
            occurrences = _referenced(indexes["occurrences"], scene.get("occurrence_ids"))
        hubs = [
            item
            for item in indexes["hubs"].values()
            if scene.get("id") in _strings(item.get("scene_ids"))
        ]
        if boundary is None:
            boundary = indexes["boundaries"].get(str(scene.get("boundary_id", "")))
    if branch is not None:
        atoms.extend(_referenced(indexes["atoms"], _arm_refs(branch, "atom_ids")))
        branches.extend(_referenced(indexes["branches"], _arm_refs(branch, "nested_branch_ids")))
        occurrences.extend(
            _referenced(indexes["occurrences"], _arm_refs(branch, "occurrence_ids"))
        )
    if selected_hub is not None:
        hubs = [selected_hub]
    if lane is not None:
        related_scenes = _referenced(indexes["scenes"], lane.get("scene_ids"))
    if chapter is not None:
        related_scenes = _referenced(indexes["scenes"], chapter.get("scene_ids"))
    if boundary is not None and scene is None:
        related_scenes = [
            item
            for item in indexes["scenes"].values()
            if item.get("boundary_id") == boundary.get("id")
        ]

    records = [
        item
        for item in (scene, branch, occurrence, selected_hub, lane, chapter, boundary)
        if item is not None
    ]
    records.extend((*atoms, *branches, *occurrences, *hubs))
    records.extend(related_scenes[:MAX_SCENE_DETAIL_REFERENCES])
    provenance = _combined_provenance(records)
    escape_ids = _canonical_escape_ids(provenance, records)
    canonical_records = _matching_canonical_records(canonical, escape_ids)
    evidence_ids = set(provenance["evidence_ids"])
    for record in canonical_records:
        evidence_ids.update(_strings(record.get("evidence_ids")))
    evidence = [
        dict(item)
        for item in _records(canonical.get("evidence"), "canonical.evidence")
        if item.get("id") in evidence_ids
    ][:MAX_SCENE_DETAIL_REFERENCES]

    arm_local_scenes = _arm_local_scenes(branch, indexes) if branch is not None else []
    membership_budget = _ReferenceBudget(MAX_SCENE_DETAIL_REFERENCES)
    bounded_scene = _bounded_optional_record(scene, membership_budget)
    bounded_branch = _bounded_optional_record(branch, membership_budget)
    bounded_occurrence = _bounded_optional_record(occurrence, membership_budget)
    bounded_lane = _bounded_optional_record(lane, membership_budget)
    bounded_chapter = _bounded_optional_record(chapter, membership_budget)
    bounded_boundary = _bounded_optional_record(boundary, membership_budget)
    bounded_atoms = [
        _bounded_record(item, membership_budget)
        for item in atoms[:MAX_SCENE_DETAIL_REFERENCES]
    ]
    bounded_branches = [
        _bounded_record(item, membership_budget)
        for item in branches[:MAX_SCENE_DETAIL_REFERENCES]
    ]
    bounded_arm_scenes = [
        _bounded_record(item, membership_budget)
        for item in arm_local_scenes[:MAX_SCENE_DETAIL_REFERENCES]
    ]
    bounded_occurrences = [
        _bounded_record(item, membership_budget)
        for item in occurrences[:MAX_SCENE_DETAIL_REFERENCES]
    ]
    bounded_hubs = [
        _bounded_record(item, membership_budget)
        for item in hubs[:MAX_SCENE_DETAIL_REFERENCES]
    ]
    bounded_related_scenes = [
        _bounded_record(item, membership_budget)
        for item in related_scenes[:MAX_SCENE_DETAIL_REFERENCES]
    ]
    canonical_record_budget = _ReferenceBudget(MAX_SCENE_DETAIL_REFERENCES)
    bounded_canonical_records = [
        _bounded_record(item, canonical_record_budget)
        for item in canonical_records[:MAX_SCENE_DETAIL_REFERENCES]
    ]
    bounded_evidence = [
        _bounded_record(item, canonical_record_budget)
        for item in evidence[:MAX_SCENE_DETAIL_REFERENCES]
    ]
    result: dict[str, object] = {
        "schema_version": 1,
        "status": "available",
        "level": "scene_detail",
        "source_generation": current_source_generation,
        "canonical_hash": current_canonical_hash,
        "element_id": element_id,
        "scene": bounded_scene,
        "caller_scene": _ownership_context(scene) if occurrence is not None else None,
        "temporary_branch": bounded_branch,
        "selected_occurrence": bounded_occurrence,
        "selected_occurrence_id": occurrence_id,
        "lane": bounded_lane,
        "chapter": bounded_chapter,
        "boundary": bounded_boundary,
        "atoms": bounded_atoms,
        "temporary_branches": bounded_branches,
        "arm_local_scenes": bounded_arm_scenes,
        "call_occurrences": bounded_occurrences,
        "loop_hubs": bounded_hubs,
        "related_scenes": bounded_related_scenes,
        "return_relationships": _hub_records(hubs, "return_relationships"),
        "partial_order": _hub_records(hubs, "partial_order"),
        "provenance": provenance,
        "canonical_escape_ids": escape_ids[:MAX_SCENE_DETAIL_REFERENCES],
        "canonical_records": bounded_canonical_records,
        "canonical_record_total": len(canonical_records),
        "canonical_records_truncated": len(canonical_records) > MAX_SCENE_DETAIL_REFERENCES,
        "evidence": bounded_evidence,
        "evidence_total": len(evidence_ids),
        "evidence_truncated": len(evidence_ids) > MAX_SCENE_DETAIL_REFERENCES,
        "membership_reference_limit": MAX_SCENE_DETAIL_REFERENCES,
        "membership_reference_count": membership_budget.used,
        "canonical_record_reference_limit": MAX_SCENE_DETAIL_REFERENCES,
        "canonical_record_reference_count": canonical_record_budget.used,
    }
    return result


def _availability_reason(
    model: Mapping[str, object] | None,
    presentation: Mapping[str, object] | None,
    current_generation: str,
    current_hash: str,
) -> str | None:
    if model is None:
        return "scene_model_missing"
    if presentation is None:
        return "scene_presentation_missing"
    model_binding = _mapping(model.get("binding"))
    presentation_binding = _mapping(presentation.get("binding"))
    expected = (current_generation, current_hash)
    if _binding_pair(model_binding) != expected:
        return "scene_model_canonical_mismatch"
    if _binding_pair(presentation_binding) != expected:
        return "scene_presentation_canonical_mismatch"
    if presentation_binding != model_binding:
        return "scene_presentation_binding_mismatch"
    scene_model_hash = presentation.get("scene_model_hash")
    if scene_model_hash != _model_hash(model):
        return "scene_presentation_model_mismatch"
    return None


def _unavailable(reason: str, generation: str, canonical_hash: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "unavailable",
        "level": "scene_map",
        "reason": reason,
        "source_generation": generation,
        "canonical_hash": canonical_hash,
    }


def _validate_window(offset: int, limit: int, edge_offset: int, edge_limit: int) -> None:
    if offset < 0 or edge_offset < 0:
        raise ValueError("scene page offsets cannot be negative")
    if limit < 1 or limit > MAX_SCENE_NODES:
        raise ValueError("scene node limit is outside the rendering boundary")
    if edge_limit < 1 or edge_limit > MAX_SCENE_RELATIONSHIPS:
        raise ValueError("scene relationship limit is outside the rendering boundary")


def _model_hash(model: Mapping[str, object]) -> str:
    normalized = dict(model)
    normalized.pop("operational_metadata", None)
    normalized.pop("structural_hash", None)
    return _content_hash(normalized)


def _content_hash(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(dict(value))).hexdigest()


def _indexes(model: Mapping[str, object]) -> dict[str, dict[str, Mapping[str, object]]]:
    indexes = {
        name: {str(item["id"]): item for item in _records(model.get(name), f"model.{name}")}
        for name in (
            "atoms",
            "boundaries",
            "scenes",
            "temporary_branches",
            "occurrences",
            "lanes",
            "chapters",
            "loop_hubs",
        )
    }
    indexes["branches"] = indexes["temporary_branches"]
    indexes["hubs"] = indexes["loop_hubs"]
    return indexes


def _map_nodes(
    model: Mapping[str, object],
    presentation: Mapping[str, object],
    indexes: dict[str, dict[str, Mapping[str, object]]],
) -> list[dict[str, object]]:
    del model
    order_values = _strings(presentation.get("page_order"))
    order = {item: index for index, item in enumerate(order_values)}
    columns: dict[str, int] = {}
    for item in _records(
        presentation.get("layout_columns"), "presentation.layout_columns"
    ):
        lane_id_value = item.get("lane_id")
        column_value = item.get("column")
        if (
            isinstance(lane_id_value, str)
            and isinstance(column_value, int)
            and not isinstance(column_value, bool)
        ):
            columns[lane_id_value] = column_value
    result: list[dict[str, object]] = []
    for fallback_order, item in enumerate(
        _records(presentation.get("nodes"), "presentation.nodes")
    ):
        node_id = _text(item, "id")
        kind = item.get("kind")
        scene_id = _node_scene_id(item)
        branch_id = _node_branch_id(item)
        occurrence_id = item.get("occurrence_id", node_id)
        if kind == "call_occurrence" and occurrence_id in indexes["occurrences"]:
            occurrence = indexes["occurrences"][str(occurrence_id)]
            caller_scene_id = str(occurrence.get("scene_id", scene_id or ""))
            scene = indexes["scenes"].get(caller_scene_id)
            if scene is None:
                continue
            referenced = _referenced(
                indexes["atoms"], occurrence.get("referenced_atom_ids")
            )
            lane_id = str(scene.get("lane_id", ""))
            result.append(
                {
                    "id": node_id,
                    "kind": "scene_occurrence",
                    "scene_id": caller_scene_id,
                    "occurrence_id": occurrence_id,
                    "title": str(
                        item.get(
                            "title",
                            referenced[0].get("label", "Called narrative")
                            if referenced
                            else "Called narrative",
                        )
                    ),
                    "chapter_id": scene.get("chapter_id"),
                    "lane_id": lane_id,
                    "lane_ancestry": _lane_ancestry(lane_id, indexes["lanes"]),
                    "page_order": _page_order(item, node_id, order, fallback_order),
                    "layout_column": _layout_column(item, lane_id, columns),
                    "referenced_atom_ids": list(
                        _strings(occurrence.get("referenced_atom_ids"))
                    ),
                    "guard_fact_ids": list(_strings(occurrence.get("guard_fact_ids"))),
                    "repeatable": bool(occurrence.get("repeatable", False)),
                    "collapsed": bool(occurrence.get("collapsed", False)),
                }
            )
        elif kind in {"scene", "scene_occurrence"} and scene_id in indexes["scenes"]:
            scene = indexes["scenes"][scene_id]
            boundary = indexes["boundaries"].get(str(scene.get("boundary_id", "")), {})
            lane_id = str(scene.get("lane_id", ""))
            result.append(
                {
                    "id": node_id,
                    "kind": "scene_occurrence",
                    "scene_id": scene_id,
                    "title": str(scene.get("title", item.get("title", "Scene"))),
                    "chapter_id": scene.get("chapter_id"),
                    "lane_id": lane_id,
                    "lane_ancestry": _lane_ancestry(lane_id, indexes["lanes"]),
                    "ordinal": scene.get("ordinal"),
                    "page_order": _page_order(item, node_id, order, fallback_order),
                    "layout_column": _layout_column(item, lane_id, columns),
                    "atom_ids": list(_strings(scene.get("atom_ids"))),
                    "temporary_branch_ids": list(
                        _strings(scene.get("temporary_branch_ids"))
                    ),
                    "occurrence_ids": list(_strings(scene.get("occurrence_ids"))),
                    "repeatability": scene.get("repeatability", "once"),
                    "repeatable": scene.get("repeatability") == "repeatable",
                    "loop_hub_id": scene.get("loop_hub_id"),
                    "boundary_id": scene.get("boundary_id"),
                    "boundary_strength": boundary.get("strength"),
                    "boundary_status": boundary.get("status"),
                    "definition_only": bool(scene.get("definition_only", False)),
                }
            )
        elif kind == "temporary_branch" and branch_id in indexes["branches"]:
            branch = indexes["branches"][branch_id]
            parent = indexes["scenes"].get(str(branch.get("parent_scene_id", "")), {})
            boundary = indexes["boundaries"].get(str(parent.get("boundary_id", "")), {})
            lane_id = str(parent.get("lane_id", item.get("lane_id", "")))
            result.append(
                {
                    "id": node_id,
                    "kind": "temporary_branch",
                    "temporary_branch_id": branch_id,
                    "title": str(item.get("title", "Temporary choice")),
                    "chapter_id": parent.get("chapter_id", item.get("chapter_id")),
                    "lane_id": lane_id,
                    "lane_ancestry": _lane_ancestry(lane_id, indexes["lanes"]),
                    "page_order": _page_order(item, node_id, order, fallback_order),
                    "layout_column": _layout_column(item, lane_id, columns),
                    "parent_scene_id": branch.get("parent_scene_id"),
                    "parent_branch_id": branch.get("parent_branch_id"),
                    "split_atom_id": branch.get("split_atom_id"),
                    "merge_node_id": branch.get("merge_node_id"),
                    "continuation_atom_id": branch.get("continuation_atom_id"),
                    "arms": [
                        {
                            "id": arm.get("id"),
                            "ordinal": arm.get("ordinal"),
                            "atom_ids": list(_strings(arm.get("atom_ids"))),
                            "scene_ids": list(_strings(arm.get("scene_ids"))),
                            "nested_branch_ids": list(_strings(arm.get("nested_branch_ids"))),
                            "occurrence_ids": list(_strings(arm.get("occurrence_ids"))),
                        }
                        for arm in _records(branch.get("arms"), "temporary_branch.arms")
                    ],
                    "boundary_id": parent.get("boundary_id"),
                    "boundary_strength": boundary.get("strength"),
                    "boundary_status": boundary.get("status"),
                }
            )
    return result


def _relationships(
    presentation: Mapping[str, object], valid_ids: set[str]
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in _records(presentation.get("relationships"), "presentation.relationships"):
        source = _text(item, "source_id")
        target = _text(item, "target_id")
        if source not in valid_ids or target not in valid_ids:
            continue
        result.append(
            {
                "id": _text(item, "id"),
                "kind": str(item.get("kind", "relationship")),
                "source_id": source,
                "target_id": target,
            }
        )
    return sorted(result, key=lambda item: item["id"])


def _chapter_bands(
    presentation: Mapping[str, object],
    indexes: dict[str, dict[str, Mapping[str, object]]],
    page_scene_ids: set[str],
    page_chapter_ids: set[str],
    page_lane_ids: set[str],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for item in _records(presentation.get("chapter_bands"), "presentation.chapter_bands"):
        chapter_id = str(item.get("chapter_id", item.get("id", "")))
        if chapter_id not in page_chapter_ids:
            continue
        chapter = indexes["chapters"].get(chapter_id, {})
        scene_ids = _strings(chapter.get("scene_ids", item.get("scene_ids")))
        result.append(
            {
                "id": chapter_id,
                "label": str(chapter.get("label", item.get("label", "Story"))),
                "ordinal": chapter.get("ordinal", item.get("ordinal")),
                "lane_ids": [
                    value
                    for value in _strings(chapter.get("lane_ids", item.get("lane_ids")))
                    if value in page_lane_ids
                ],
                "scene_ids": [value for value in scene_ids if value in page_scene_ids],
                "scene_total": len(scene_ids),
            }
        )
    return sorted(result, key=lambda item: (_required_int(item["ordinal"]), str(item["id"])))


def _lane_summaries(
    presentation: Mapping[str, object],
    indexes: dict[str, dict[str, Mapping[str, object]]],
    page_scene_ids: set[str],
    page_lane_ids: set[str],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for item in _records(presentation.get("lanes"), "presentation.lanes"):
        lane_id = _text(item, "id")
        if lane_id not in page_lane_ids:
            continue
        lane = indexes["lanes"].get(lane_id, item)
        scene_ids = _strings(lane.get("scene_ids"))
        result.append(
            {
                "id": lane_id,
                "kind": lane.get("kind"),
                "parent_lane_id": lane.get("parent_lane_id"),
                "ancestry": _lane_ancestry(lane_id, indexes["lanes"]),
                "scene_ids": [value for value in scene_ids if value in page_scene_ids],
                "scene_total": len(scene_ids),
            }
        )
    return result


def _search(
    nodes: Sequence[Mapping[str, object]],
    indexes: dict[str, dict[str, Mapping[str, object]]],
    *,
    query: str | None,
    focus: str | None,
    page_size: int,
) -> dict[str, object] | None:
    requested = (focus or query or "").strip()
    if not requested:
        return None
    needle = requested.casefold()
    matches: list[dict[str, object]] = []
    for index, node in enumerate(nodes):
        values = [
            str(node.get(key, ""))
            for key in ("id", "title", "scene_id", "temporary_branch_id")
        ]
        scene = indexes["scenes"].get(str(node.get("scene_id", "")))
        branch = indexes["branches"].get(str(node.get("temporary_branch_id", "")))
        if scene is not None:
            values.extend(_search_values(scene, indexes))
        if branch is not None:
            values.extend(_search_values(branch, indexes))
        exact = any(value.casefold() == needle for value in values)
        if exact or (focus is None and any(needle in value.casefold() for value in values)):
            matches.append(
                {
                    "id": node["id"],
                    "kind": node["kind"],
                    "title": node["title"],
                    "offset": (index // page_size) * page_size,
                }
            )
    result: dict[str, object] = {
        "query": requested,
        "total": len(matches),
        "matches": matches[:MAX_SCENE_SEARCH_RESULTS],
        "truncated": len(matches) > MAX_SCENE_SEARCH_RESULTS,
    }
    if focus is not None and matches:
        result["focus"] = matches[0]
    return result


def _search_values(
    record: Mapping[str, object],
    indexes: dict[str, dict[str, Mapping[str, object]]],
) -> list[str]:
    result = [str(record.get("id", "")), str(record.get("title", ""))]
    atom_ids = [*_strings(record.get("atom_ids")), *_strings(_arm_refs(record, "atom_ids"))]
    for atom_id in atom_ids:
        atom = indexes["atoms"].get(atom_id)
        if atom is not None:
            result.extend((atom_id, str(atom.get("label", "")), str(atom.get("speaker", ""))))
            result.extend(_provenance_ids(atom.get("provenance")))
    result.extend(_provenance_ids(record.get("provenance")))
    return result


def _lane_ancestry(
    lane_id: str, lanes: Mapping[str, Mapping[str, object]]
) -> list[str]:
    reverse: list[str] = []
    seen: set[str] = set()
    current: str | None = lane_id or None
    while current is not None and current not in seen and current in lanes:
        seen.add(current)
        reverse.append(current)
        parent = lanes[current].get("parent_lane_id")
        current = parent if isinstance(parent, str) else None
    return list(reversed(reverse))


def _combined_provenance(records: Sequence[Mapping[str, object]]) -> dict[str, list[str]]:
    keys = ("node_ids", "edge_ids", "region_ids", "fact_ids", "evidence_ids", "proof_ids")
    budget = _ReferenceBudget(MAX_SCENE_DETAIL_REFERENCES)
    result: dict[str, list[str]] = {}
    for key in keys:
        values = sorted(
            {
                value
                for record in records
                for value in _strings(_mapping(record.get("provenance")).get(key))
            }
        )
        selected, _total = budget.take(values)
        result[key] = selected
    return result


def _canonical_escape_ids(
    provenance: Mapping[str, Sequence[str]], records: Sequence[Mapping[str, object]]
) -> list[str]:
    result = {item for values in provenance.values() for item in values}
    for record in records:
        for key in ("canonical_region_id", "merge_node_id", "callee_entry_node_id"):
            value = record.get(key)
            if isinstance(value, str):
                result.add(value)
        result.update(_strings(record.get("canonical_anchor_ids")))
    return sorted(result)


def _matching_canonical_records(
    canonical: Mapping[str, object], ids: Sequence[str]
) -> list[Mapping[str, object]]:
    selected = set(ids)
    result: list[Mapping[str, object]] = []
    for collection in ("nodes", "edges", "regions", "facts", "proofs"):
        result.extend(
            item
            for item in _records(canonical.get(collection), f"canonical.{collection}")
            if item.get("id") in selected
        )
    return result


def _arm_local_scenes(
    branch: Mapping[str, object],
    indexes: dict[str, dict[str, Mapping[str, object]]],
) -> list[dict[str, object]]:
    return [
        {
            "arm_id": arm.get("id"),
            "ordinal": arm.get("ordinal"),
            "scene_ids": list(_strings(arm.get("scene_ids"))),
            "scenes": [
                dict(indexes["scenes"][scene_id])
                for scene_id in _strings(arm.get("scene_ids"))
                if scene_id in indexes["scenes"]
            ],
            "nested_branch_ids": list(_strings(arm.get("nested_branch_ids"))),
        }
        for arm in _records(branch.get("arms"), "temporary_branch.arms")
    ]


def _hub_records(hubs: Sequence[Mapping[str, object]], key: str) -> list[dict[str, object]]:
    return [
        dict(item)
        for hub in hubs
        for item in _records(hub.get(key), f"loop_hub.{key}")
    ][:MAX_SCENE_DETAIL_REFERENCES]


def _referenced(
    index: Mapping[str, Mapping[str, object]], values: object
) -> list[Mapping[str, object]]:
    return [index[item] for item in _strings(values) if item in index]


def _bounded_optional_record(
    value: Mapping[str, object] | None, budget: _ReferenceBudget
) -> dict[str, object] | None:
    return _bounded_record(value, budget) if value is not None else None


def _ownership_context(value: Mapping[str, object] | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        key: value.get(key)
        for key in ("id", "title", "chapter_id", "lane_id", "boundary_id")
    }


def _bounded_record(
    value: Mapping[str, object], budget: _ReferenceBudget
) -> dict[str, object]:
    """Copy a model record without allowing nested membership references to escape its budget."""

    result: dict[str, object] = {}
    for key, item in value.items():
        if key.endswith("_ids") and not isinstance(item, (str, bytes)):
            selected, total = budget.take(item)
            result[key] = selected
            if total > len(selected):
                result[f"{key}_total"] = total
                result[f"{key}_truncated"] = True
        elif isinstance(item, Mapping):
            result[key] = _bounded_record(item, budget)
        elif (
            isinstance(item, Sequence)
            and not isinstance(item, (str, bytes))
            and all(isinstance(nested, Mapping) for nested in item)
        ):
            records = tuple(nested for nested in item if isinstance(nested, Mapping))
            result[key] = [
                _bounded_record(nested, budget)
                for nested in records[:MAX_SCENE_DETAIL_REFERENCES]
            ]
            if len(records) > MAX_SCENE_DETAIL_REFERENCES:
                result[f"{key}_total"] = len(records)
                result[f"{key}_truncated"] = True
        else:
            result[key] = item
    return result


def _arm_refs(record: Mapping[str, object], key: str) -> tuple[str, ...]:
    return tuple(
        value
        for arm in _records(record.get("arms"), "temporary_branch.arms")
        for value in _strings(arm.get(key))
    )


def _node_scene_id(item: Mapping[str, object]) -> str | None:
    fallback = (
        item.get("id") if item.get("kind") in {"scene", "scene_occurrence"} else None
    )
    value = item.get("scene_id", fallback)
    return value if isinstance(value, str) else None


def _node_branch_id(item: Mapping[str, object]) -> str | None:
    fallback = item.get("id") if item.get("kind") == "temporary_branch" else None
    value = item.get("temporary_branch_id", item.get("branch_id", fallback))
    return value if isinstance(value, str) else None


def _page_order(
    item: Mapping[str, object], node_id: str, order: Mapping[str, int], fallback: int
) -> int:
    value = item.get("page_order")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return order.get(node_id, fallback)


def _layout_column(
    item: Mapping[str, object], lane_id: str, columns: Mapping[str, int]
) -> int:
    value = item.get("layout_column")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return columns.get(lane_id, 0)


def _binding_pair(binding: Mapping[str, object]) -> tuple[object, object]:
    return binding.get("source_generation"), binding.get("canonical_hash")


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _records(value: object, name: str) -> tuple[Mapping[str, object], ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{name} must contain records")
    return tuple(item for item in value if isinstance(item, Mapping))


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _provenance_ids(value: object) -> list[str]:
    provenance = _mapping(value)
    return [
        item
        for key in ("node_ids", "edge_ids", "region_ids", "fact_ids", "evidence_ids", "proof_ids")
        for item in _strings(provenance.get(key))
    ]


def _text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} must be a non-empty string")
    return item


def _required_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("expected an integer")
    return value
