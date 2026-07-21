"""Bounded, provider-free web projection for the M15 Narrative Map."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Final

from renpy_story_mapper import storage
from renpy_story_mapper.canonical_graph_contract import (
    CANONICAL_GRAPH_SCHEMA,
    CanonicalFact,
    CanonicalGraph,
    CanonicalNode,
    SourceEvidence,
)
from renpy_story_mapper.m11_scene_model import AtomKind, SceneModel, StoryAtom
from renpy_story_mapper.m11_scene_projection import scene_model_from_stored_results
from renpy_story_mapper.m12_service import canonical_graph_from_mapping
from renpy_story_mapper.narrative_map import (
    NarrativeEvent,
    NarrativeMap,
    NarrativeMapEdge,
    NarrativeMapNode,
    NarrativeMapRepository,
    NarrativeMapService,
    NarrativeNodeKind,
    assemble_narrative_events,
    build_boundary_candidates,
    build_narrative_corridors,
    build_narrative_map,
    resolve_leading_technical_coverage_correction,
)
from renpy_story_mapper.narrative_map.adapters import bind_m15_authority
from renpy_story_mapper.narrative_map.contracts import LeadingTechnicalCoverageCorrection
from renpy_story_mapper.narrative_map.coverage_corrections import (
    M15_LEADING_TECHNICAL_CORRECTION_KEY,
    M15_LEADING_TECHNICAL_CORRECTIONS_COLLECTION,
    LeadingTechnicalCorrectionRepository,
)
from renpy_story_mapper.project import Project

NARRATIVE_MAP_PAGE_SCHEMA: Final = "m15-narrative-map-page-v1"
NARRATIVE_MAP_DETAIL_SCHEMA: Final = "m15-narrative-map-detail-v1"
MAX_MAP_NODES: Final = 120
MAX_MAP_EDGES: Final = 360
MAX_DETAIL_EVIDENCE: Final = 60
MAX_DETAIL_MEMBERS: Final = 30
MAX_DETAIL_EDGES: Final = 180


@dataclass(frozen=True)
class NarrativeMapSnapshot:
    canonical: CanonicalGraph
    model: SceneModel
    events: tuple[NarrativeEvent, ...]
    narrative_map: NarrativeMap
    correction_status: dict[str, str]


def narrative_map_page(
    project: Project,
    *,
    query: str | None = None,
    focus: str | None = None,
) -> dict[str, object]:
    """Return one coherent server-owned map without invoking a provider or M12 solver."""

    loaded = _load_snapshot(project)
    if isinstance(loaded, str):
        return _unavailable(loaded)
    page = _page_payload(loaded)
    nodes = page["nodes"]
    edges = page["edges"]
    assert isinstance(nodes, list) and isinstance(edges, list)
    node_ids = {str(item["id"]) for item in nodes if isinstance(item, dict)}
    edge_ids = {
        str(item["id"])
        for item in edges
        if isinstance(item, dict)
    }
    if focus is not None and focus not in node_ids | edge_ids:
        raise KeyError(focus)
    normalized_query = query.strip() if query is not None else ""
    matches = [
        {"id": str(item["id"]), "title": str(item.get("title", ""))}
        for item in nodes
        if isinstance(item, dict)
        and normalized_query.casefold()
        in " ".join(
            (
                str(item.get("id", "")),
                str(item.get("title", "")),
                str(item.get("summary", "")),
            )
        ).casefold()
    ]
    page["search"] = {
        "query": normalized_query,
        "matches": matches,
        "total": len(matches),
        "focus": focus,
    }
    return page


def narrative_map_detail(project: Project, element_id: str) -> dict[str, object]:
    """Resolve any visible map node or connector to exact bounded local evidence."""

    loaded = _load_snapshot(project)
    if isinstance(loaded, str):
        raise KeyError(element_id)
    page = _page_payload(loaded)
    map_node = next(
        (item for item in loaded.narrative_map.nodes if item.node_id == element_id),
        None,
    )
    map_edge = next(
        (item for item in loaded.narrative_map.edges if item.edge_id == element_id),
        None,
    )
    if map_node is None and map_edge is None:
        raise KeyError(element_id)
    event_by_id = {item.event_id: item for item in loaded.events}
    event = (
        event_by_id.get(map_node.event_id)
        if map_node is not None and map_node.event_id is not None
        else None
    )
    node_by_id = {item.id: item for item in loaded.canonical.nodes}
    edge_by_id = {item.id: item for item in loaded.canonical.edges}
    fact_by_id = {item.id: item for item in loaded.canonical.facts}
    evidence_by_id = {item.id: item for item in loaded.canonical.evidence}
    line_basis_by_path = {
        str(item["source_path"]): str(item["line_basis"])
        for item in project.source_derivations()
        if isinstance(item.get("source_path"), str)
        and isinstance(item.get("line_basis"), str)
    }
    atom_by_id = {item.id: item for item in loaded.model.atoms}

    canonical_node_ids = list(event.provenance.node_ids if event is not None else ())
    canonical_edge_ids = list(event.provenance.edge_ids if event is not None else ())
    fact_ids = list(event.provenance.fact_ids if event is not None else ())
    evidence_ids = list(event.provenance.evidence_ids if event is not None else ())
    atom_ids = list(event.ordered_atom_ids if event is not None else ())
    if map_edge is not None:
        canonical_edge_ids = list(map_edge.authority_edge_ids)
        fact_ids = [*map_edge.requirement_ids, *map_edge.effect_ids]
        for authority_edge_id in canonical_edge_ids:
            authority_edge = edge_by_id.get(authority_edge_id)
            if authority_edge is None:
                continue
            canonical_node_ids.extend((authority_edge.source_id, authority_edge.target_id))
            evidence_ids.extend(authority_edge.evidence_ids)
        for fact_id in fact_ids:
            fact = fact_by_id.get(fact_id)
            if fact is not None:
                evidence_ids.extend(fact.evidence_ids)
    if map_node is not None:
        _extend_navigation_authority(
            map_node,
            loaded.canonical,
            canonical_node_ids,
            evidence_ids,
        )

    canonical_node_ids = list(_ordered_unique(canonical_node_ids))
    canonical_edge_ids = list(_ordered_unique(canonical_edge_ids))
    fact_ids = list(_ordered_unique(fact_ids))
    evidence_ids = list(_ordered_unique(evidence_ids))
    if not evidence_ids:
        for canonical_node_id in canonical_node_ids:
            authority_node = node_by_id.get(canonical_node_id)
            if authority_node is not None:
                evidence_ids.extend(authority_node.evidence_ids)
        evidence_ids = list(_ordered_unique(evidence_ids))

    atoms = [atom_by_id[item] for item in atom_ids if item in atom_by_id]
    facts = [fact_by_id[item] for item in fact_ids if item in fact_by_id]
    requirements = [item for item in facts if _is_requirement(item)]
    effects = [item for item in facts if not _is_requirement(item)]
    choices = _choices_for_node(map_node, event, loaded.canonical)
    member_nodes = [
        node_by_id[item].to_dict()
        for item in canonical_node_ids[:MAX_DETAIL_MEMBERS]
        if item in node_by_id
    ]
    member_edges = [
        edge_by_id[item].to_dict()
        for item in canonical_edge_ids[:MAX_DETAIL_EDGES]
        if item in edge_by_id
    ]
    evidence = [
        _evidence_payload(evidence_by_id[item], line_basis_by_path)
        for item in evidence_ids[:MAX_DETAIL_EVIDENCE]
        if item in evidence_by_id
    ]
    if not evidence:
        raise ValueError("a Narrative Map element has no exact source evidence")

    nodes = page["nodes"]
    edges = page["edges"]
    assert isinstance(nodes, list) and isinstance(edges, list)
    node_payload = next(
        (item for item in nodes if isinstance(item, dict) and item.get("id") == element_id),
        None,
    )
    edge_payload = next(
        (item for item in edges if isinstance(item, dict) and item.get("id") == element_id),
        None,
    )
    selected = node_payload or edge_payload
    assert selected is not None
    predecessor_ids = [
        str(item["source_id"])
        for item in edges
        if isinstance(item, dict) and item.get("target_id") == element_id
    ]
    successor_ids = [
        str(item["target_id"])
        for item in edges
        if isinstance(item, dict) and item.get("source_id") == element_id
    ]
    canonical_focus_id = canonical_node_ids[0] if canonical_node_ids else None
    return {
        "schema": NARRATIVE_MAP_DETAIL_SCHEMA,
        "status": "available",
        "level": "detail_evidence",
        "authority_hash": loaded.canonical.authority_hash,
        "element": {
            **selected,
            "summary": selected.get("summary")
            or "Deterministic Narrative Map structure with exact qualified evidence.",
        },
        "predecessor_ids": predecessor_ids,
        "successor_ids": successor_ids,
        "member_route_nodes": member_nodes,
        "member_route_edges": member_edges,
        "choices": choices,
        "requirements": [_fact_payload(item) for item in requirements],
        "effects": [_fact_payload(item) for item in effects],
        "dialogue": [_atom_payload(item) for item in atoms if item.kind is AtomKind.DIALOGUE],
        "narration": [_atom_payload(item) for item in atoms if item.kind is AtomKind.NARRATION],
        "facts": [_fact_payload(item) for item in facts],
        "evidence": evidence,
        "evidence_reference_count": len(evidence_ids),
        "evidence_reference_limit": MAX_DETAIL_EVIDENCE,
        "canonical_focus_id": canonical_focus_id,
        "canonical_focus_offset": 0,
        "provider_calls": 0,
        "m12_requests": 0,
    }


def _load_snapshot(project: Project) -> NarrativeMapSnapshot | str:
    raw_state = project.payload("m10_analysis_state", "authoritative")
    raw_canonical = project.payload("m10_canonical_graph", "authoritative")
    if not isinstance(raw_state, dict) or not isinstance(raw_canonical, dict):
        return "m10_canonical_not_current"
    try:
        canonical = canonical_graph_from_mapping(raw_canonical)
    except (TypeError, ValueError):
        return "m10_canonical_invalid"
    source_generation = raw_state.get("source_generation")
    canonical_generation = raw_state.get("canonical_generation")
    canonical_hash = raw_state.get("canonical_hash")
    if (
        raw_state.get("canonical_availability") != "current_complete"
        or source_generation != canonical.source_generation
        or canonical_generation != canonical.source_generation
        or canonical_hash != canonical.authority_hash
    ):
        return "m10_canonical_not_current"
    selection = project.m11_persistence().select_current(
        source_generation=canonical.source_generation,
        canonical_schema=CANONICAL_GRAPH_SCHEMA,
        canonical_hash=canonical.authority_hash,
    )
    if selection.phase_results is None:
        return selection.reason or "m11_not_published"
    try:
        model = scene_model_from_stored_results(selection.phase_results)
        correction, correction_status = _select_technical_correction(
            project,
            canonical,
            model,
        )
        corridors = build_narrative_corridors(
            canonical,
            model,
            technical_correction=correction,
        )
        service = NarrativeMapService(NarrativeMapRepository(project))
        decisions = service.read_boundary_decisions(build_boundary_candidates(corridors))
        events = assemble_narrative_events(
            corridors,
            decisions,
            expected_atom_ids=(item.id for item in model.atoms),
        )
        summaries = {item.event_id: item for item in service.read_event_summaries(events)}
        enriched_events = tuple(
            replace(
                event,
                ai_title=(
                    summaries[event.event_id].title
                    if summaries[event.event_id].enriched
                    else None
                ),
                ai_summary=summaries[event.event_id].summary,
            )
            for event in events
        )
        projected = build_narrative_map(canonical, enriched_events, corridors=corridors)
    except (KeyError, TypeError, ValueError):
        return "narrative_map_projection_invalid"
    if len(projected.nodes) > MAX_MAP_NODES or len(projected.edges) > MAX_MAP_EDGES:
        return "narrative_map_exceeds_bounded_surface"
    return NarrativeMapSnapshot(
        canonical,
        model,
        enriched_events,
        projected,
        correction_status,
    )


def _select_technical_correction(
    project: Project,
    canonical: CanonicalGraph,
    model: SceneModel,
) -> tuple[LeadingTechnicalCoverageCorrection | None, dict[str, str]]:
    """Select only an exact current correction and report a bounded safe outcome."""

    authority = bind_m15_authority(canonical, model)
    present = M15_LEADING_TECHNICAL_CORRECTION_KEY in project.payload_keys(
        M15_LEADING_TECHNICAL_CORRECTIONS_COLLECTION
    )
    if not present:
        return None, {"state": "not_applied", "diagnostic": "absent"}
    try:
        correction = LeadingTechnicalCorrectionRepository(project).load(authority)
    except storage.ProjectCorruptError:
        return None, {"state": "not_applied", "diagnostic": "stored_invalid"}
    if correction is None:
        return None, {"state": "not_applied", "diagnostic": "stale_authority"}
    try:
        resolve_leading_technical_coverage_correction(canonical, model, correction)
    except (TypeError, ValueError):
        return None, {"state": "not_applied", "diagnostic": "resolution_invalid"}
    return correction, {"state": "applied", "diagnostic": "valid"}


def _page_payload(snapshot: NarrativeMapSnapshot) -> dict[str, object]:
    event_by_id = {item.event_id: item for item in snapshot.events}
    node_payloads = [
        _node_payload(item, event_by_id, snapshot.canonical)
        for item in snapshot.narrative_map.nodes
    ]
    visible_node_ids = {str(item["id"]) for item in node_payloads}
    edge_payloads = [
        _edge_payload(item)
        for item in snapshot.narrative_map.edges
    ]
    lane_ids = _ordered_unique(str(item["lane_id"]) for item in node_payloads)
    lanes = [
        {
            "id": lane_id,
            "kind": "detour" if lane_id == "local-choice" else "spine",
            "label": "Local choice" if lane_id == "local-choice" else "Story spine",
        }
        for lane_id in lane_ids
    ]
    return {
        "schema": NARRATIVE_MAP_PAGE_SCHEMA,
        "status": "available",
        "level": "narrative_map",
        "presentation_levels": ["narrative_map", "detail_evidence"],
        "authority_hash": snapshot.canonical.authority_hash,
        "map_hash": snapshot.narrative_map.normalized_hash,
        "technical_correction_id": snapshot.narrative_map.technical_correction_id,
        "correction_status": dict(snapshot.correction_status),
        "nodes": node_payloads,
        "edges": edge_payloads,
        "lanes": lanes,
        "initial_node_ids": [
            item
            for item in snapshot.narrative_map.initial_node_ids
            if item in visible_node_ids
        ],
        "hidden_technical_count": len(snapshot.narrative_map.hidden_technical_atom_ids),
        "total_nodes": len(node_payloads),
        "total_edges": len(edge_payloads),
        "provider_calls": 0,
        "m12_requests": 0,
        "fallback": None,
    }


def _node_payload(
    node: NarrativeMapNode,
    event_by_id: Mapping[str, NarrativeEvent],
    canonical: CanonicalGraph,
) -> dict[str, object]:
    event = event_by_id.get(node.event_id or "")
    source_line = _node_source_line(node, event, canonical)
    lane_id = (
        "local-choice"
        if node.kind is NarrativeNodeKind.CHOICE_ARM
        else "story-spine"
    )
    summary = event.ai_summary if event is not None else None
    if not summary and event is not None:
        summary = f"{len(event.ordered_atom_ids)} evidence-linked story atoms"
    return {
        "id": node.node_id,
        "kind": node.kind.value,
        "title": node.title,
        "summary": summary or "Exact deterministic story structure",
        "order": source_line * 10_000 + _kind_order(node.kind) * 1_000 + node.ordinal,
        "ordinal": node.ordinal,
        "lane_id": lane_id,
        "lane_kind": "detour" if node.kind is NarrativeNodeKind.CHOICE_ARM else "spine",
        "lane_label": (
            "Local choice"
            if node.kind is NarrativeNodeKind.CHOICE_ARM
            else "Story spine"
        ),
        "event_id": node.event_id,
        "parent_node_id": node.parent_node_id,
        "choice_id": node.choice_id,
        "arm_id": node.arm_id,
        "rejoin_node_id": node.rejoin_node_id,
        "technical_count": node.technical_count,
        "unresolved": node.kind is NarrativeNodeKind.UNRESOLVED,
        "navigation": node.navigation.to_dict(),
    }


def _edge_payload(edge: NarrativeMapEdge) -> dict[str, object]:
    return {
        "id": edge.edge_id,
        "source_id": edge.source_node_id,
        "target_id": edge.target_node_id,
        "role": edge.kind.value,
        "kind": edge.kind.value,
        "authority_edge_ids": list(edge.authority_edge_ids),
        "gate_ids": list(edge.requirement_ids),
        "requirement_ids": list(edge.requirement_ids),
        "effect_ids": list(edge.effect_ids),
        "proven_merge": edge.kind.value in {"rejoin", "persistent_merge"},
        "interactive": True,
        "navigation": {
            "mode": "detail_evidence",
            "target_kind": "narrative_edge",
            "target_id": edge.edge_id,
        },
    }


def _node_source_line(
    node: NarrativeMapNode,
    event: NarrativeEvent | None,
    canonical: CanonicalGraph,
) -> int:
    if event is not None and event.provenance.locators:
        return min(item.start_line for item in event.provenance.locators)
    node_by_id = {item.id: item for item in canonical.nodes}
    target = node.rejoin_node_id
    if node.choice_id is not None:
        region = next((item for item in canonical.regions if item.id == node.choice_id), None)
        target = region.split_node_id if region is not None else target
    authority_node = node_by_id.get(target or "")
    evidence_by_id = {item.id: item for item in canonical.evidence}
    evidence_ids = authority_node.evidence_ids if authority_node is not None else ()
    lines = [
        line
        for evidence_id in evidence_ids
        for line in (_evidence_start_line(evidence_by_id.get(evidence_id)),)
        if line is not None
    ]
    return min(lines) if lines else node.ordinal + 1


def _kind_order(kind: NarrativeNodeKind) -> int:
    return {
        NarrativeNodeKind.EVENT_CLUSTER: 0,
        NarrativeNodeKind.SUB_EVENT: 1,
        NarrativeNodeKind.CHOICE: 2,
        NarrativeNodeKind.CHOICE_ARM: 3,
        NarrativeNodeKind.REJOIN: 8,
        NarrativeNodeKind.CONTINUATION: 9,
    }.get(kind, 5)


def _extend_navigation_authority(
    node: NarrativeMapNode,
    canonical: CanonicalGraph,
    node_ids: list[str],
    evidence_ids: list[str],
) -> None:
    canonical_nodes = {item.id: item for item in canonical.nodes}
    target_ids: list[str] = []
    if node.rejoin_node_id is not None:
        target_ids.append(node.rejoin_node_id)
    if node.choice_id is not None:
        region = next((item for item in canonical.regions if item.id == node.choice_id), None)
        if region is not None:
            target_ids.extend((region.split_node_id, *region.member_node_ids))
            if region.merge_node_id is not None:
                target_ids.append(region.merge_node_id)
    for target_id in target_ids:
        authority_node = canonical_nodes.get(target_id)
        if authority_node is not None:
            node_ids.append(target_id)
            evidence_ids.extend(authority_node.evidence_ids)


def _choices_for_node(
    node: NarrativeMapNode | None,
    event: NarrativeEvent | None,
    canonical: CanonicalGraph,
) -> list[dict[str, object]]:
    choice_ids = list(event.nested_choice_ids if event is not None else ())
    if node is not None and node.choice_id is not None:
        choice_ids.append(node.choice_id)
    node_by_id = {item.id: item for item in canonical.nodes}
    result: list[dict[str, object]] = []
    for choice_id in _ordered_unique(choice_ids):
        region = next((item for item in canonical.regions if item.id == choice_id), None)
        if region is None:
            continue
        arms = region.attributes.get("arms")
        if not isinstance(arms, list):
            continue
        for arm in arms:
            if not isinstance(arm, Mapping):
                continue
            entry_id = arm.get("entry_node_id")
            entry = node_by_id.get(str(entry_id))
            result.append(
                {
                    "id": str(arm.get("id", entry_id)),
                    "caption": _canonical_caption(entry),
                    "label": _canonical_caption(entry),
                    "expression": str(arm.get("predicate", "")),
                }
            )
    return result


def _canonical_caption(node: CanonicalNode | None) -> str:
    if node is None:
        return "Choice outcome"
    metadata = node.attributes.get("metadata")
    if isinstance(metadata, Mapping):
        caption = metadata.get("caption")
        if isinstance(caption, str) and caption.strip():
            return caption.strip()
    source_text = node.attributes.get("source_text")
    if isinstance(source_text, str) and source_text.strip():
        return source_text.strip()
    return node.label or "Choice outcome"


def _atom_payload(atom: StoryAtom) -> dict[str, object]:
    return {
        "id": atom.id,
        "label": atom.label,
        "text": atom.label,
        "speaker_display_name": atom.speaker,
        "kind": atom.kind.value,
    }


def _fact_payload(fact: CanonicalFact) -> dict[str, object]:
    attributes = dict(fact.attributes)
    label = attributes.get("label") or attributes.get("expression") or fact.kind.replace("_", " ")
    expression = attributes.get("expression") or attributes.get("source_expression") or ""
    return {
        "id": fact.id,
        "kind": fact.kind,
        "status": fact.status,
        "label": str(label),
        "expression": str(expression),
        "evidence_ids": list(fact.evidence_ids),
    }


def _is_requirement(fact: CanonicalFact) -> bool:
    value = f"{fact.kind} {fact.attributes.get('kind', '')}".casefold()
    return any(token in value for token in ("gate", "condition", "require", "predicate"))


def _evidence_payload(
    evidence: SourceEvidence,
    line_basis_by_path: Mapping[str, str],
) -> dict[str, object]:
    source_path = evidence.source.get("path")
    stored_basis = (
        line_basis_by_path.get(source_path)
        if isinstance(source_path, str)
        else None
    )
    return {
        **evidence.to_dict(),
        "kind": "source",
        "line_basis": evidence.line_basis or stored_basis or "physical_source",
    }


def _evidence_start_line(evidence: SourceEvidence | None) -> int | None:
    if evidence is None:
        return None
    start = evidence.source.get("start")
    if not isinstance(start, Mapping):
        return None
    line = start.get("line")
    return line if isinstance(line, int) and not isinstance(line, bool) else None


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _unavailable(reason: str) -> dict[str, object]:
    return {
        "schema": NARRATIVE_MAP_PAGE_SCHEMA,
        "status": "unavailable",
        "level": "narrative_map",
        "presentation_levels": ["narrative_map", "detail_evidence"],
        "reason": reason,
        "nodes": [],
        "edges": [],
        "lanes": [],
        "initial_node_ids": [],
        "hidden_technical_count": 0,
        "technical_correction_id": None,
        "correction_status": {
            "state": "not_applied",
            "diagnostic": "map_unavailable",
        },
        "total_nodes": 0,
        "total_edges": 0,
        "provider_calls": 0,
        "m12_requests": 0,
        "fallback": {
            "label": "Deterministic inspection fallback",
            "route": "/api/v1/m10/inspection-map",
            "view": "simplified",
        },
    }
