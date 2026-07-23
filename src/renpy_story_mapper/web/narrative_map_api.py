"""Bounded, provider-free web projection for the M15 Narrative Map."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final, cast

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
    AuthorityBinding,
    BoundaryWindow,
    ChoiceComposition,
    EvidenceNavigation,
    FineNarrativeUnit,
    LiveSemanticProvenance,
    MajorCluster,
    NarrativeEvent,
    NarrativeGapCandidate,
    NarrativeMap,
    NarrativeMapEdge,
    NarrativeMapNode,
    NarrativeMapRepository,
    NarrativeMapService,
    NarrativeNodeKind,
    SemanticBeat,
    SemanticOutline,
    assemble_narrative_events,
    build_all_eligible_gap_candidates,
    build_boundary_candidates,
    build_boundary_windows,
    build_choice_compositions,
    build_fine_narrative_units,
    build_narrative_corridors,
    build_narrative_map,
    build_semantic_quotient_topology,
    resolve_leading_technical_coverage_correction,
    stable_m15_id,
)
from renpy_story_mapper.narrative_map.adapters import bind_m15_authority
from renpy_story_mapper.narrative_map.contracts import (
    LeadingTechnicalCoverageCorrection,
    canonical_hash,
)
from renpy_story_mapper.narrative_map.coverage_corrections import (
    M15_LEADING_TECHNICAL_CORRECTION_KEY,
    M15_LEADING_TECHNICAL_CORRECTIONS_COLLECTION,
    LeadingTechnicalCorrectionRepository,
)
from renpy_story_mapper.narrative_map.persistence import NarrativeJobStatus
from renpy_story_mapper.narrative_map.projection import (
    SemanticQuotientTopology,
    SemanticTopologyEdge,
)
from renpy_story_mapper.narrative_map.provider import ProviderJobKind
from renpy_story_mapper.narrative_map.semantic_projection import (
    MAXIMUM_COMPACT_WHOLE_SCOPE_ROWS,
    CompactWholeScopeProjection,
    project_compact_semantic_edges,
    project_compact_semantic_nodes,
    semantic_outline_hash,
)
from renpy_story_mapper.project import Project

NARRATIVE_MAP_PAGE_SCHEMA: Final = "m15-narrative-map-page-v1"
NARRATIVE_MAP_DETAIL_SCHEMA: Final = "m15-narrative-map-detail-v1"
MAX_MAP_NODES: Final = 120
MAX_MAP_EDGES: Final = 360
MAX_DETAIL_EVIDENCE: Final = 60
MAX_DETAIL_MEMBERS: Final = 30
MAX_DETAIL_EDGES: Final = 180
SEMANTIC_PUBLICATION_SCHEMA: Final = "m15-semantic-publication-v2"
SEMANTIC_OUTLINE_SCHEMA: Final = "m15-semantic-outline-v2"
SEMANTIC_CORRECTION_ID: Final = "m15.1-product-path-v1"
SEMANTIC_PRIVACY_SCOPE: Final = "story_evidence_only"


@dataclass(frozen=True)
class NarrativeMapSnapshot:
    canonical: CanonicalGraph
    model: SceneModel
    events: tuple[NarrativeEvent, ...]
    narrative_map: NarrativeMap | None
    correction_status: dict[str, str]
    semantic: SemanticNarrativeSnapshot | None = None


@dataclass(frozen=True)
class SemanticNarrativeSnapshot:
    publication_hash: str
    build_id: str
    units: tuple[FineNarrativeUnit, ...]
    candidates: tuple[NarrativeGapCandidate, ...]
    windows: tuple[BoundaryWindow, ...]
    outline: SemanticOutline
    topology: SemanticQuotientTopology
    summaries: Mapping[str, Mapping[str, object]]
    summary_provenance: Mapping[str, Mapping[str, object]]
    nodes: tuple[dict[str, object], ...]
    edges: tuple[dict[str, object], ...]


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
    page = _semantic_page_payload(loaded) if loaded.semantic is not None else _page_payload(loaded)
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


def whole_scope_projection_page(
    projection: CompactWholeScopeProjection,
    *,
    authority_hash: str,
    publication_hash: str,
    build_id: str,
    outline_label: str = "Story outline",
) -> dict[str, object]:
    """Serialize one already-validated Stage H/E projection for the normal browser flow.

    This adapter is deliberately persistence- and provider-free. Track B owns publication and
    lifecycle validation; the integrated product can call this only after those checks succeed.
    """

    for value, label in (
        (authority_hash, "whole-scope authority hash"),
        (publication_hash, "whole-scope publication hash"),
        (build_id, "whole-scope build ID"),
        (outline_label, "whole-scope outline label"),
    ):
        if not value or value != value.strip():
            raise ValueError(f"{label} must be non-empty and trimmed")
    sections = [
        item for item in projection.nodes if item.get("kind") == "major_cluster"
    ]
    if not sections:
        raise ValueError("whole-scope normal flow requires a visible major section")
    nodes = [dict(item) for item in projection.nodes]
    edges = [_semantic_edge_payload(item) for item in projection.edges]
    return {
        "schema": NARRATIVE_MAP_PAGE_SCHEMA,
        "status": "available",
        "level": "narrative_map",
        "presentation_levels": ["narrative_map", "detail_evidence"],
        "authority_hash": authority_hash,
        "map_hash": publication_hash,
        "publication_hash": publication_hash,
        "build_id": build_id,
        "build_state": (
            "partial"
            if projection.partial_subject_ids or projection.warnings
            else "complete"
        ),
        "outline_label": outline_label,
        "technical_correction_id": None,
        "correction_status": {"state": "whole_scope_applied"},
        "nodes": nodes,
        "edges": edges,
        "lanes": [{"id": "story-spine", "kind": "spine", "label": "Story spine"}],
        "initial_node_ids": [str(sections[0]["id"])],
        "hidden_technical_count": len(projection.omitted_subject_ids),
        "omitted_subject_ids": list(projection.omitted_subject_ids),
        "partial_subject_ids": list(projection.partial_subject_ids),
        "warnings": list(projection.warnings),
        "density": {
            "visible_rows": projection.visible_row_count,
            "maximum_visible_rows": MAXIMUM_COMPACT_WHOLE_SCOPE_ROWS,
            "major_sections": len(sections),
            "choices": sum(item.get("kind") == "choice" for item in projection.nodes),
            "choice_arms": sum(
                item.get("kind") == "choice_arm" for item in projection.nodes
            ),
            "rejoins": sum(item.get("kind") == "rejoin" for item in projection.nodes),
        },
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "provider_calls": 0,
        "m12_requests": 0,
        "fallback": None,
    }


def narrative_map_detail(project: Project, element_id: str) -> dict[str, object]:
    """Resolve any visible map node or connector to exact bounded local evidence."""

    loaded = _load_snapshot(project)
    if isinstance(loaded, str):
        raise KeyError(element_id)
    if loaded.semantic is not None:
        return _semantic_detail(project, loaded, element_id)
    page = _page_payload(loaded)
    narrative_map = loaded.narrative_map
    if narrative_map is None:
        raise KeyError(element_id)
    map_node = next(
        (item for item in narrative_map.nodes if item.node_id == element_id),
        None,
    )
    map_edge = next(
        (item for item in narrative_map.edges if item.edge_id == element_id),
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
    except (KeyError, TypeError, ValueError, storage.ProjectStorageError):
        return "m11_publication_invalid"
    repository = NarrativeMapRepository(project)
    try:
        semantic_current = repository.read_semantic_current()
    except (TypeError, ValueError, storage.ProjectStorageError):
        return "semantic_publication_invalid"
    if semantic_current is not None:
        try:
            semantic = _load_semantic_snapshot(
                canonical,
                model,
                semantic_current,
                repository,
            )
        except (KeyError, TypeError, ValueError, storage.ProjectStorageError):
            return "semantic_publication_invalid"
        if len(semantic.nodes) > MAX_MAP_NODES or len(semantic.edges) > MAX_MAP_EDGES:
            return "narrative_map_exceeds_bounded_surface"
        return NarrativeMapSnapshot(
            canonical,
            model,
            (),
            None,
            {"state": "not_applied", "diagnostic": "semantic_current"},
            semantic,
        )
    try:
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
    except (KeyError, TypeError, ValueError, storage.ProjectStorageError):
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


def _load_semantic_snapshot(
    canonical: CanonicalGraph,
    model: SceneModel,
    publication: Mapping[str, object],
    repository: NarrativeMapRepository,
) -> SemanticNarrativeSnapshot:
    expected_publication_keys = {
        "schema",
        "build_id",
        "authority",
        "source_hash",
        "correction_id",
        "privacy_scope",
        "boundary_manifest_id",
        "summary_manifest_id",
        "membership_hash",
        "outline",
        "summaries",
        "summary_provenance",
        "quotient_topology",
        "publication_hash",
    }
    _exact_keys(publication, expected_publication_keys, "semantic publication")
    if publication.get("schema") != SEMANTIC_PUBLICATION_SCHEMA:
        raise ValueError("semantic publication schema is unsupported")
    publication_hash = _required_text(publication, "publication_hash")
    unhashed = {key: value for key, value in publication.items() if key != "publication_hash"}
    if canonical_hash(unhashed) != publication_hash:
        raise ValueError("semantic publication hash is invalid")
    authority = _authority_binding(publication.get("authority"))
    if authority != bind_m15_authority(canonical, model):
        raise ValueError("semantic publication authority is stale")
    if publication.get("source_hash") != canonical.source_generation:
        raise ValueError("semantic publication source identity is stale")
    if publication.get("correction_id") != SEMANTIC_CORRECTION_ID:
        raise ValueError("semantic publication correction identity is unsupported")
    if publication.get("privacy_scope") != SEMANTIC_PRIVACY_SCOPE:
        raise ValueError("semantic publication privacy scope is unsupported")
    boundary_manifest_id = _required_text(publication, "boundary_manifest_id")
    summary_manifest_id = _required_text(publication, "summary_manifest_id")
    if boundary_manifest_id == summary_manifest_id:
        raise ValueError("semantic publication reused boundary consent for summaries")

    units = build_fine_narrative_units(canonical, model)
    candidates = build_all_eligible_gap_candidates(units)
    windows = build_boundary_windows(units, candidates)
    outline = _semantic_outline_from_payload(
        publication.get("outline"),
        authority=authority,
        units=units,
        candidates=candidates,
        windows=windows,
        repository=repository,
    )
    membership_hash = _required_text(publication, "membership_hash")
    if semantic_outline_hash(outline) != membership_hash:
        raise ValueError("semantic publication membership hash is invalid")
    expected_choices = build_choice_compositions(canonical, units, outline)
    if expected_choices != outline.choices:
        raise ValueError("semantic publication choice composition is not deterministic")
    topology = build_semantic_quotient_topology(canonical, units, outline)
    if publication.get("quotient_topology") != topology.to_dict():
        raise ValueError("semantic publication quotient topology is invalid")
    summaries, provenance = _semantic_summaries(
        publication.get("summaries"),
        publication.get("summary_provenance"),
        outline=outline,
        units=units,
        repository=repository,
        membership_hash=membership_hash,
    )
    nodes = project_compact_semantic_nodes(
        canonical,
        model,
        units,
        outline,
        topology,
        summaries,
        provenance,
    )
    node_ids = {str(item["id"]) for item in nodes}
    edges = tuple(
        _semantic_edge_payload(item)
        for item in project_compact_semantic_edges(topology, tuple(node_ids))
    )
    if any(
        str(edge["source_id"]) not in node_ids or str(edge["target_id"]) not in node_ids
        for edge in edges
    ):
        raise ValueError("semantic topology contains a missing endpoint")
    return SemanticNarrativeSnapshot(
        publication_hash=publication_hash,
        build_id=_required_text(publication, "build_id"),
        units=units,
        candidates=candidates,
        windows=windows,
        outline=outline,
        topology=topology,
        summaries=summaries,
        summary_provenance=provenance,
        nodes=nodes,
        edges=edges,
    )


def _semantic_outline_from_payload(
    value: object,
    *,
    authority: AuthorityBinding,
    units: Sequence[FineNarrativeUnit],
    candidates: Sequence[NarrativeGapCandidate],
    windows: Sequence[BoundaryWindow],
    repository: NarrativeMapRepository,
) -> SemanticOutline:
    raw = _required_mapping(value, "semantic outline")
    _exact_keys(
        raw,
        {
            "schema",
            "authority",
            "ordered_unit_ids",
            "ordered_candidate_ids",
            "beats",
            "clusters",
            "choices",
            "boundary_provenance",
        },
        "semantic outline",
    )
    if raw.get("schema") != SEMANTIC_OUTLINE_SCHEMA:
        raise ValueError("semantic outline schema is unsupported")
    if _authority_binding(raw.get("authority")) != authority:
        raise ValueError("semantic outline authority is stale")
    ordered_unit_ids = _string_sequence(raw.get("ordered_unit_ids"), "outline unit IDs")
    ordered_candidate_ids = _string_sequence(
        raw.get("ordered_candidate_ids"), "outline candidate IDs"
    )
    if ordered_unit_ids != tuple(item.unit_id for item in units):
        raise ValueError("semantic outline unit identity is stale")
    if ordered_candidate_ids != tuple(item.candidate_id for item in candidates):
        raise ValueError("semantic outline candidate identity is stale")
    beats = tuple(_semantic_beat(item) for item in _mapping_sequence(raw.get("beats"), "beats"))
    clusters = tuple(
        _major_cluster(item) for item in _mapping_sequence(raw.get("clusters"), "clusters")
    )
    choices = tuple(
        _choice_composition(item)
        for item in _mapping_sequence(raw.get("choices"), "choices")
    )
    window_by_candidate = {
        candidate_id: window.window_id
        for window in windows
        for candidate_id in window.owned_candidate_ids
    }
    raw_provenance = _mapping_sequence(
        raw.get("boundary_provenance"), "boundary provenance"
    )
    if len(raw_provenance) != len(candidates):
        raise ValueError("semantic outline boundary provenance is incomplete")
    provenance: list[LiveSemanticProvenance] = []
    for candidate, item in zip(candidates, raw_provenance, strict=True):
        required = {
            "candidate_id",
            "window_id",
            "stage",
            "job_id",
            "input_hash",
            "manifest_id",
            "provider_identity_hash",
            "cache_identity",
        }
        if frozenset(item) != frozenset(required):
            raise ValueError("boundary provenance contains unsupported fields")
        candidate_id = _required_text(item, "candidate_id")
        window_id = _required_text(item, "window_id")
        if candidate_id != candidate.candidate_id or window_id != window_by_candidate[candidate_id]:
            raise ValueError("boundary provenance candidate/window identity is invalid")
        live = LiveSemanticProvenance(
            _required_text(item, "stage"),
            _required_text(item, "job_id"),
            _required_text(item, "input_hash"),
            _required_text(item, "manifest_id"),
            _required_text(item, "provider_identity_hash"),
            _required_text(item, "cache_identity"),
            candidate_id=candidate_id,
            window_id=window_id,
        )
        # The publication header names the finalizing manifest; resumed work can retain
        # a different actual producer, which is authoritative only through this exact job.
        record = repository.get(ProviderJobKind.SEMANTIC_BOUNDARY_WINDOW, live.job_id)
        if (
            record is None
            or record.status is not NarrativeJobStatus.VALIDATED
            or record.subject_id != live.window_id
            or record.input_hash != live.input_hash
            or record.consent_manifest_id != live.manifest_id
            or record.provider_identity is None
            or canonical_hash(record.provider_identity) != live.provider_identity_hash
            or record.result is None
            or not _boundary_record_contains(record.result, candidate_id, live.window_id)
        ):
            raise ValueError("boundary provenance does not resolve to one validated job")
        provenance.append(live)
    outline = SemanticOutline(
        authority,
        ordered_unit_ids,
        ordered_candidate_ids,
        beats,
        clusters,
        choices,
        tuple(provenance),
    )
    beat_units = tuple(unit_id for beat in beats for unit_id in beat.ordered_unit_ids)
    if len(beat_units) != len(set(beat_units)) or set(beat_units) != set(ordered_unit_ids):
        raise ValueError("semantic outline beat membership is incomplete or overlapping")
    cluster_beats = tuple(beat_id for cluster in clusters for beat_id in cluster.ordered_beat_ids)
    if len(cluster_beats) != len(set(cluster_beats)) or set(cluster_beats) != {
        item.beat_id for item in beats
    }:
        raise ValueError("semantic outline cluster membership is incomplete or overlapping")
    return outline


def _semantic_summaries(
    summaries_value: object,
    provenance_value: object,
    *,
    outline: SemanticOutline,
    units: Sequence[FineNarrativeUnit],
    repository: NarrativeMapRepository,
    membership_hash: str,
) -> tuple[dict[str, Mapping[str, object]], dict[str, Mapping[str, object]]]:
    summaries = _mapping_sequence(summaries_value, "semantic summaries")
    provenance = _mapping_sequence(provenance_value, "summary provenance")
    subjects = (
        *(("beat", item.beat_id) for item in outline.beats),
        *(("major_cluster", item.cluster_id) for item in outline.clusters),
        *(("choice", item.choice_id) for item in outline.choices),
    )
    if len(summaries) != len(subjects) or len(provenance) != len(subjects):
        raise ValueError("semantic summaries do not cover every visible subject")
    allowed_evidence = _summary_evidence_by_subject(outline, units)
    by_subject: dict[str, Mapping[str, object]] = {}
    provenance_by_subject: dict[str, Mapping[str, object]] = {}
    for (expected_kind, expected_id), summary, live in zip(
        subjects, summaries, provenance, strict=True
    ):
        _exact_keys(
            summary,
            {
                "subject_kind",
                "subject_id",
                "membership_hash",
                "title",
                "summary",
                "characters",
                "claims",
                "warnings",
            },
            "semantic summary",
        )
        if (
            summary.get("subject_kind") != expected_kind
            or summary.get("subject_id") != expected_id
            or summary.get("membership_hash") != membership_hash
        ):
            raise ValueError("semantic summary subject or membership identity is invalid")
        _required_text(summary, "title")
        _required_text(summary, "summary")
        _string_sequence(summary.get("characters"), "summary characters")
        _string_sequence(summary.get("warnings"), "summary warnings")
        claims = _mapping_sequence(summary.get("claims"), "summary claims")
        if not claims:
            raise ValueError("semantic summary has no evidence-linked claims")
        for claim in claims:
            _exact_keys(claim, {"claim_class", "text", "evidence_ids"}, "semantic claim")
            if claim.get("claim_class") not in {"factual", "interpretive"}:
                raise ValueError("semantic claim class is invalid")
            _required_text(claim, "text")
            evidence_ids = _string_sequence(claim.get("evidence_ids"), "claim evidence IDs")
            if not evidence_ids or not set(evidence_ids).issubset(allowed_evidence[expected_id]):
                raise ValueError("semantic claim evidence is foreign to its subject")
        _exact_keys(
            live,
            {
                "subject_kind",
                "subject_id",
                "stage",
                "job_id",
                "input_hash",
                "manifest_id",
                "provider_identity_hash",
                "cache_identity",
            },
            "summary provenance",
        )
        if (
            live.get("subject_kind") != expected_kind
            or live.get("subject_id") != expected_id
            or live.get("stage") != "summaries"
        ):
            raise ValueError("summary provenance uses the wrong stage or consent")
        record = repository.get(
            ProviderJobKind.SEMANTIC_SUMMARY,
            _required_text(live, "job_id"),
        )
        # As above, the durable validated job owns producer consent lineage, not the
        # finalizing summary manifest named by the publication header.
        if (
            record is None
            or record.status is not NarrativeJobStatus.VALIDATED
            or record.subject_id != expected_id
            or record.input_hash != live.get("input_hash")
            or record.consent_manifest_id != live.get("manifest_id")
            or record.result != summary
            or record.provider_identity is None
            or canonical_hash(record.provider_identity) != live.get("provider_identity_hash")
        ):
            raise ValueError("summary provenance does not resolve to one validated job")
        by_subject[expected_id] = dict(summary)
        provenance_by_subject[expected_id] = {
            **dict(live),
            "subject_kind": expected_kind,
            "subject_id": expected_id,
            "provider_identity": dict(record.provider_identity),
        }
    return by_subject, provenance_by_subject


def _semantic_nodes(
    canonical: CanonicalGraph,
    units: Sequence[FineNarrativeUnit],
    outline: SemanticOutline,
    topology: SemanticQuotientTopology,
    summaries: Mapping[str, Mapping[str, object]],
    provenance: Mapping[str, Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    units_by_id = {item.unit_id: item for item in units}
    nodes: list[dict[str, object]] = []
    order = 0
    for cluster in outline.clusters:
        order += 1
        summary = summaries[cluster.cluster_id]
        nodes.append(
            _semantic_node(
                cluster.cluster_id,
                "major_cluster",
                summary,
                provenance[cluster.cluster_id],
                order,
                parent_node_id=None,
            )
        )
    first_arm_beat: set[tuple[str, str]] = set()
    for beat in outline.beats:
        order += 1
        first_unit = units_by_id[beat.ordered_unit_ids[0]]
        arm_key = (
            (beat.parent_choice_id, beat.parent_arm_id)
            if beat.parent_choice_id is not None and beat.parent_arm_id is not None
            else None
        )
        kind = "beat"
        if arm_key is not None and arm_key not in first_arm_beat:
            first_arm_beat.add(arm_key)
            kind = "choice_arm"
        node = _semantic_node(
            beat.beat_id,
            kind,
            summaries[beat.beat_id],
            provenance[beat.beat_id],
            order,
            parent_node_id=beat.parent_choice_id or beat.parent_cluster_id,
        )
        node.update(
            {
                "parent_cluster_id": beat.parent_cluster_id,
                "choice_id": beat.parent_choice_id,
                "arm_id": beat.parent_arm_id,
                "parent_arm_id": beat.parent_arm_id,
                "lane_id": first_unit.lane_id,
            }
        )
        nodes.append(node)
    for choice in outline.choices:
        order += 1
        node = _semantic_node(
            choice.choice_id,
            "choice",
            summaries[choice.choice_id],
            provenance[choice.choice_id],
            order,
            parent_node_id=choice.parent_choice_id or choice.parent_cluster_id,
        )
        node.update(
            {
                "choice_id": choice.choice_id,
                "parent_cluster_id": choice.parent_cluster_id,
                "parent_arm_id": choice.parent_arm_id,
                "ordered_arm_ids": list(choice.ordered_arm_ids),
                "ordered_arm_captions": list(choice.ordered_arm_captions),
                "rejoin_relationship_ids": list(choice.rejoin_relationship_ids),
            }
        )
        nodes.append(node)
    choice_by_rejoin = {
        stable_m15_id(
            "semantic_rejoin",
            {
                "canonical_hash": canonical.authority_hash,
                "canonical_node_id": choice.shared_target_id,
                "call_occurrence_path": list(choice.call_occurrence_path),
            },
        ): choice
        for choice in outline.choices
        if choice.shared_target_id is not None
    }
    existing_ids = {str(item["id"]) for item in nodes}
    canonical_nodes = {item.id: item for item in canonical.nodes}
    for topology_node in topology.nodes:
        if topology_node.subject_id in existing_ids:
            continue
        order += 1
        rejoin_choice = choice_by_rejoin.get(topology_node.subject_id)
        if topology_node.subject_kind == "rejoin":
            kind = "rejoin"
            title = "Paths come back together"
            summary_text = "The choice arms reach the same authoritative continuation."
        elif topology_node.subject_kind == "terminal":
            kind = "ending"
            title = "End of the extracted story"
            summary_text = "The current deterministic story scope ends here."
        elif topology_node.subject_kind == "unresolved":
            kind = "unresolved"
            title = "Unresolved story path"
            summary_text = "Static authority cannot prove what happens beyond this point."
        else:
            kind = "technical_coverage"
            title = "Deterministic continuity"
            summary_text = "Exact technical structure connects nearby story items."
        source_nodes = [
            canonical_nodes[item]
            for item in topology_node.canonical_node_ids
            if item in canonical_nodes
        ]
        lane_id = "story-spine"
        nodes.append(
            {
                "id": topology_node.subject_id,
                "kind": kind,
                "title": title,
                "summary": summary_text,
                "order": order,
                "ordinal": order - 1,
                "lane_id": lane_id,
                "lane_kind": "spine",
                "lane_label": "Story spine",
                "parent_node_id": (
                    rejoin_choice.choice_id if rejoin_choice is not None else None
                ),
                "choice_id": rejoin_choice.choice_id if rejoin_choice is not None else None,
                "arm_id": None,
                "rejoin_node_id": (
                    rejoin_choice.shared_target_id if rejoin_choice is not None else None
                ),
                "technical_count": len(source_nodes) if kind == "technical_coverage" else 0,
                "unresolved": kind == "unresolved",
                "navigation": {
                    "mode": "detail_evidence",
                    "target_kind": topology_node.subject_kind,
                    "target_id": topology_node.subject_id,
                },
            }
        )
    return tuple(nodes)


def _semantic_node(
    subject_id: str,
    kind: str,
    summary: Mapping[str, object],
    provenance: Mapping[str, object],
    order: int,
    *,
    parent_node_id: str | None,
) -> dict[str, object]:
    return {
        "id": subject_id,
        "kind": kind,
        "title": str(summary["title"]),
        "summary": str(summary["summary"]),
        "order": order,
        "ordinal": order - 1,
        "lane_id": "story-spine",
        "lane_kind": "spine",
        "lane_label": "Story spine",
        "parent_node_id": parent_node_id,
        "choice_id": None,
        "arm_id": None,
        "rejoin_node_id": None,
        "technical_count": 0,
        "unresolved": False,
        "characters": list(cast(Sequence[object], summary["characters"])),
        "claims": [dict(item) for item in cast(Sequence[Mapping[str, object]], summary["claims"])],
        "warnings": list(cast(Sequence[object], summary["warnings"])),
        "summary_provenance": dict(provenance),
        "navigation": {
            "mode": "detail_evidence",
            "target_kind": str(summary["subject_kind"]),
            "target_id": subject_id,
        },
    }


def _semantic_edge_payload(topology_edge: SemanticTopologyEdge) -> dict[str, object]:
    return {
        "id": topology_edge.edge_id,
        "source_id": topology_edge.source_subject_id,
        "target_id": topology_edge.target_subject_id,
        "role": topology_edge.kind.value,
        "kind": topology_edge.kind.value,
        "authority_edge_ids": list(topology_edge.authority_edge_ids),
        "gate_ids": list(topology_edge.requirement_ids),
        "requirement_ids": list(topology_edge.requirement_ids),
        "effect_ids": list(topology_edge.effect_ids),
        "evidence_ids": list(topology_edge.evidence_ids),
        "proven_merge": topology_edge.kind.value in {"rejoin", "persistent_merge"},
        "interactive": True,
        "navigation": {
            "mode": "detail_evidence",
            "target_kind": "semantic_topology_edge",
            "target_id": topology_edge.edge_id,
        },
    }


def _semantic_page_payload(snapshot: NarrativeMapSnapshot) -> dict[str, object]:
    semantic = snapshot.semantic
    if semantic is None:
        raise ValueError("semantic Narrative Map projection is unavailable")
    return {
        "schema": NARRATIVE_MAP_PAGE_SCHEMA,
        "status": "available",
        "level": "narrative_map",
        "presentation_levels": ["narrative_map", "detail_evidence"],
        "authority_hash": snapshot.canonical.authority_hash,
        "map_hash": semantic.publication_hash,
        "publication_hash": semantic.publication_hash,
        "build_id": semantic.build_id,
        "build_state": "complete",
        "outline_label": "Story outline",
        "technical_correction_id": None,
        "correction_status": dict(snapshot.correction_status),
        "nodes": [dict(item) for item in semantic.nodes],
        "edges": [dict(item) for item in semantic.edges],
        "lanes": [{"id": "story-spine", "kind": "spine", "label": "Story spine"}],
        "initial_node_ids": [
            str(
                next(
                    item
                    for item in semantic.nodes
                    if item.get("kind") == "major_cluster"
                )["id"]
            )
        ],
        "hidden_technical_count": sum(
            item.get("kind") == "technical_coverage" for item in semantic.nodes
        ),
        "total_nodes": len(semantic.nodes),
        "total_edges": len(semantic.edges),
        "provider_calls": 0,
        "m12_requests": 0,
        "fallback": None,
    }


def _semantic_detail(
    project: Project,
    snapshot: NarrativeMapSnapshot,
    element_id: str,
) -> dict[str, object]:
    semantic = snapshot.semantic
    if semantic is None:
        raise KeyError(element_id)
    node = next((item for item in semantic.nodes if item["id"] == element_id), None)
    edge = next((item for item in semantic.edges if item["id"] == element_id), None)
    if node is None and edge is None:
        raise KeyError(element_id)
    projected_member_unit_ids = (
        _string_sequence(node.get("member_unit_ids"), "projected member unit IDs")
        if node is not None and "member_unit_ids" in node
        else ()
    )
    unit_ids = projected_member_unit_ids or _detail_unit_ids(semantic.outline, element_id)
    unit_by_id = {item.unit_id: item for item in semantic.units}
    selected_units = [unit_by_id[item] for item in unit_ids if item in unit_by_id]
    topology_node = next(
        (item for item in semantic.topology.nodes if item.subject_id == element_id),
        None,
    )
    topology_edge = next(
        (item for item in semantic.topology.edges if item.edge_id == element_id),
        None,
    )
    projected_authority_edge_ids = (
        _string_sequence(edge.get("authority_edge_ids"), "projected authority edge IDs")
        if edge is not None
        else ()
    )
    projected_requirement_ids = (
        _string_sequence(edge.get("requirement_ids"), "projected requirement IDs")
        if edge is not None
        else ()
    )
    projected_effect_ids = (
        _string_sequence(edge.get("effect_ids"), "projected effect IDs")
        if edge is not None
        else ()
    )
    projected_evidence_ids = (
        _string_sequence(edge.get("evidence_ids"), "projected evidence IDs")
        if edge is not None
        else ()
    )
    canonical_node_ids = list(
        _ordered_unique(
            (
                *(item for unit in selected_units for item in unit.provenance.node_ids),
                *(topology_node.canonical_node_ids if topology_node is not None else ()),
            )
        )
    )
    canonical_edge_ids = list(
        _ordered_unique(
            (
                *(item for unit in selected_units for item in unit.provenance.edge_ids),
                *(
                    topology_edge.authority_edge_ids
                    if topology_edge is not None
                    else projected_authority_edge_ids
                ),
            )
        )
    )
    fact_ids = list(
        _ordered_unique(
            (
                *(item for unit in selected_units for item in unit.provenance.fact_ids),
                *(
                    topology_edge.requirement_ids
                    if topology_edge is not None
                    else projected_requirement_ids
                ),
                *(
                    topology_edge.effect_ids
                    if topology_edge is not None
                    else projected_effect_ids
                ),
            )
        )
    )
    evidence_ids = list(
        _ordered_unique(
            (
                *(item for unit in selected_units for item in unit.provenance.evidence_ids),
                *(
                    topology_edge.evidence_ids
                    if topology_edge is not None
                    else projected_evidence_ids
                ),
            )
        )
    )
    canonical_nodes = {item.id: item for item in snapshot.canonical.nodes}
    canonical_edges = {item.id: item for item in snapshot.canonical.edges}
    canonical_facts = {item.id: item for item in snapshot.canonical.facts}
    canonical_evidence = {item.id: item for item in snapshot.canonical.evidence}
    for canonical_node_id in canonical_node_ids:
        authority_node = canonical_nodes.get(canonical_node_id)
        if authority_node is not None:
            evidence_ids.extend(authority_node.evidence_ids)
    for canonical_edge_id in canonical_edge_ids:
        authority_edge = canonical_edges.get(canonical_edge_id)
        if authority_edge is not None:
            evidence_ids.extend(authority_edge.evidence_ids)
    for fact_id in fact_ids:
        fact = canonical_facts.get(fact_id)
        if fact is not None:
            evidence_ids.extend(fact.evidence_ids)
    evidence_ids = list(_ordered_unique(evidence_ids))
    if not evidence_ids:
        raise ValueError("a semantic Narrative Map element has no exact source evidence")
    line_basis_by_path = {
        str(item["source_path"]): str(item["line_basis"])
        for item in project.source_derivations()
        if isinstance(item.get("source_path"), str)
        and isinstance(item.get("line_basis"), str)
    }
    atom_by_id = {item.id: item for item in snapshot.model.atoms}
    atom_ids = _ordered_unique(
        item for unit in selected_units for item in unit.provenance.atom_ids
    )
    atoms = [atom_by_id[item] for item in atom_ids if item in atom_by_id]
    facts = [canonical_facts[item] for item in fact_ids if item in canonical_facts]
    selected = dict(node or edge or {})
    summary = semantic.summaries.get(element_id)
    if summary is None and node is not None and isinstance(node.get("claims"), list):
        summary = node
    summary_provenance = semantic.summary_provenance.get(element_id)
    if (
        summary_provenance is None
        and node is not None
        and isinstance(node.get("summary_provenance"), Mapping)
    ):
        summary_provenance = cast(Mapping[str, object], node["summary_provenance"])
    claims = (
        []
        if summary is None
        else [
            dict(item)
            for item in cast(list[Mapping[str, object]], summary["claims"])
        ]
    )
    predecessors = [
        str(item["source_id"]) for item in semantic.edges if item["target_id"] == element_id
    ]
    successors = [
        str(item["target_id"]) for item in semantic.edges if item["source_id"] == element_id
    ]
    return {
        "schema": NARRATIVE_MAP_DETAIL_SCHEMA,
        "status": "available",
        "level": "detail_evidence",
        "authority_hash": snapshot.canonical.authority_hash,
        "publication_hash": semantic.publication_hash,
        "element": selected,
        "predecessor_ids": predecessors,
        "successor_ids": successors,
        "member_route_nodes": [
            canonical_nodes[item].to_dict()
            for item in canonical_node_ids[:MAX_DETAIL_MEMBERS]
            if item in canonical_nodes
        ],
        "member_route_edges": [
            canonical_edges[item].to_dict()
            for item in canonical_edge_ids[:MAX_DETAIL_EDGES]
            if item in canonical_edges
        ],
        "choices": _semantic_choices(
            snapshot.canonical,
            semantic.outline,
            (
                str(node["choice_id"])
                if node is not None
                and node.get("kind") == "choice_arm"
                and node.get("choice_id") is not None
                else element_id
            ),
        ),
        "requirements": [_fact_payload(item) for item in facts if _is_requirement(item)],
        "effects": [_fact_payload(item) for item in facts if not _is_requirement(item)],
        "dialogue": [_atom_payload(item) for item in atoms if item.kind is AtomKind.DIALOGUE],
        "narration": [_atom_payload(item) for item in atoms if item.kind is AtomKind.NARRATION],
        "facts": [_fact_payload(item) for item in facts],
        "characters": [] if summary is None else list(cast(list[object], summary["characters"])),
        "claims": claims,
        "warnings": [] if summary is None else list(cast(list[object], summary["warnings"])),
        "summary_provenance": None if summary_provenance is None else dict(summary_provenance),
        "quotient_topology": {
            "node": None if topology_node is None else topology_node.to_dict(),
            "edge": None if topology_edge is None else topology_edge.to_dict(),
        },
        "evidence": [
            _evidence_payload(canonical_evidence[item], line_basis_by_path)
            for item in evidence_ids[:MAX_DETAIL_EVIDENCE]
            if item in canonical_evidence
        ],
        "evidence_reference_count": len(evidence_ids),
        "evidence_reference_limit": MAX_DETAIL_EVIDENCE,
        "canonical_focus_id": canonical_node_ids[0] if canonical_node_ids else None,
        "canonical_focus_offset": 0,
        "provider_calls": 0,
        "m12_requests": 0,
    }


def _summary_evidence_by_subject(
    outline: SemanticOutline,
    units: Sequence[FineNarrativeUnit],
) -> dict[str, set[str]]:
    unit_by_id = {item.unit_id: item for item in units}
    result = {
        beat.beat_id: {
            evidence_id
            for unit_id in beat.ordered_unit_ids
            for evidence_id in unit_by_id[unit_id].evidence_ids
        }
        for beat in outline.beats
    }
    for cluster in outline.clusters:
        result[cluster.cluster_id] = {
            evidence_id
            for beat_id in cluster.ordered_beat_ids
            for evidence_id in result[beat_id]
        }
    choice_by_id = {item.choice_id: item for item in outline.choices}

    def owned_choices(choice_id: str, visiting: set[str]) -> set[str]:
        if choice_id in visiting:
            raise ValueError("semantic choice ownership contains a cycle")
        choice = choice_by_id.get(choice_id)
        if choice is None:
            raise ValueError("semantic choice ownership references an unknown choice")
        nested = {choice_id}
        for child_id in choice.child_choice_ids:
            nested.update(owned_choices(child_id, {*visiting, choice_id}))
        return nested

    for choice in outline.choices:
        choice_ids = owned_choices(choice.choice_id, set())
        result[choice.choice_id] = {
            evidence_id
            for beat in outline.beats
            if beat.parent_choice_id in choice_ids
            for unit_id in beat.ordered_unit_ids
            for evidence_id in unit_by_id[unit_id].evidence_ids
        }
        if not result[choice.choice_id]:
            split_beat = next(
                (
                    beat
                    for beat in outline.beats
                    if beat.parent_cluster_id == choice.parent_cluster_id
                ),
                None,
            )
            if split_beat is not None:
                result[choice.choice_id] = set(result[split_beat.beat_id])
    return result


def _detail_unit_ids(outline: SemanticOutline, subject_id: str) -> tuple[str, ...]:
    beat = next((item for item in outline.beats if item.beat_id == subject_id), None)
    if beat is not None:
        return beat.ordered_unit_ids
    cluster = next((item for item in outline.clusters if item.cluster_id == subject_id), None)
    if cluster is not None:
        beat_by_id = {item.beat_id: item for item in outline.beats}
        return tuple(
            unit_id
            for beat_id in cluster.ordered_beat_ids
            for unit_id in beat_by_id[beat_id].ordered_unit_ids
        )
    choice = next((item for item in outline.choices if item.choice_id == subject_id), None)
    if choice is None:
        return ()
    owned = {choice.choice_id}
    changed = True
    while changed:
        changed = False
        for item in outline.choices:
            if item.parent_choice_id in owned and item.choice_id not in owned:
                owned.add(item.choice_id)
                changed = True
    return tuple(
        unit_id
        for beat in outline.beats
        if beat.parent_choice_id in owned
        for unit_id in beat.ordered_unit_ids
    )


def _semantic_choices(
    canonical: CanonicalGraph,
    outline: SemanticOutline,
    element_id: str,
) -> list[dict[str, object]]:
    choices = [item for item in outline.choices if item.choice_id == element_id]
    if not choices:
        choices = [
            item
            for item in outline.choices
            if item.parent_cluster_id == element_id or item.parent_choice_id == element_id
        ]
    result: list[dict[str, object]] = []
    for choice in choices:
        for arm_id, caption, relationship_id in zip(
            choice.ordered_arm_ids,
            choice.ordered_arm_captions,
            choice.rejoin_relationship_ids,
            strict=True,
        ):
            result.append(
                {
                    "id": arm_id,
                    "caption": caption,
                    "label": caption,
                    "expression": "",
                    "choice_id": choice.choice_id,
                    "rejoin_relationship_id": relationship_id,
                    "shared_target_id": choice.shared_target_id,
                    "canonical_region_id": choice.canonical_region_id,
                    "authority_hash": canonical.authority_hash,
                }
            )
    return result


def _semantic_beat(value: Mapping[str, object]) -> SemanticBeat:
    _exact_keys(
        value,
        {
            "beat_id",
            "parent_cluster_id",
            "ordered_unit_ids",
            "parent_choice_id",
            "parent_arm_id",
            "navigation",
        },
        "semantic beat",
    )
    beat_id = _required_text(value, "beat_id")
    return SemanticBeat(
        beat_id,
        _required_text(value, "parent_cluster_id"),
        _string_sequence(value.get("ordered_unit_ids"), "semantic beat unit IDs"),
        _optional_text(value.get("parent_choice_id"), "semantic beat parent choice"),
        _optional_text(value.get("parent_arm_id"), "semantic beat parent arm"),
        _navigation(value.get("navigation"), beat_id),
    )


def _major_cluster(value: Mapping[str, object]) -> MajorCluster:
    _exact_keys(
        value,
        {"cluster_id", "ordinal", "ordered_beat_ids", "ordered_choice_ids", "navigation"},
        "major cluster",
    )
    cluster_id = _required_text(value, "cluster_id")
    ordinal = value.get("ordinal")
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
        raise ValueError("major cluster ordinal is invalid")
    return MajorCluster(
        cluster_id,
        ordinal,
        _string_sequence(value.get("ordered_beat_ids"), "major cluster beat IDs"),
        _string_sequence(value.get("ordered_choice_ids"), "major cluster choice IDs"),
        _navigation(value.get("navigation"), cluster_id),
    )


def _choice_composition(value: Mapping[str, object]) -> ChoiceComposition:
    _exact_keys(
        value,
        {
            "schema",
            "choice_id",
            "parent_cluster_id",
            "parent_choice_id",
            "parent_arm_id",
            "ordered_arm_ids",
            "ordered_arm_captions",
            "child_choice_ids",
            "rejoin_relationship_ids",
            "shared_target_id",
            "post_rejoin_continuation_id",
            "canonical_region_id",
            "call_occurrence_path",
        },
        "choice composition",
    )
    if value.get("schema") != "m15-choice-composition-v2":
        raise ValueError("choice composition schema is unsupported")
    return ChoiceComposition(
        _required_text(value, "choice_id"),
        _required_text(value, "parent_cluster_id"),
        _optional_text(value.get("parent_choice_id"), "choice parent choice"),
        _optional_text(value.get("parent_arm_id"), "choice parent arm"),
        _string_sequence(value.get("ordered_arm_ids"), "choice arm IDs"),
        _string_sequence(value.get("ordered_arm_captions"), "choice arm captions"),
        _string_sequence(value.get("child_choice_ids"), "child choice IDs"),
        _string_sequence(value.get("rejoin_relationship_ids"), "rejoin relationship IDs"),
        _optional_text(value.get("shared_target_id"), "choice shared target"),
        _optional_text(
            value.get("post_rejoin_continuation_id"), "choice post-rejoin continuation"
        ),
        _optional_text(value.get("canonical_region_id"), "choice canonical region"),
        _string_sequence(value.get("call_occurrence_path"), "choice occurrence path"),
    )


def _navigation(value: object, expected_id: str) -> EvidenceNavigation:
    raw = _required_mapping(value, "semantic navigation")
    _exact_keys(raw, {"mode", "target_kind", "target_id"}, "semantic navigation")
    navigation = EvidenceNavigation(
        _required_text(raw, "target_kind"),
        _required_text(raw, "target_id"),
        mode=_required_text(raw, "mode"),
    )
    if navigation.target_id != expected_id:
        raise ValueError("semantic navigation target identity is invalid")
    return navigation


def _authority_binding(value: object) -> AuthorityBinding:
    raw = _required_mapping(value, "semantic authority")
    _exact_keys(
        raw,
        {"source_generation", "canonical_schema", "canonical_hash", "atom_schema", "atom_hash"},
        "semantic authority",
    )
    return AuthorityBinding(
        _required_text(raw, "source_generation"),
        _required_text(raw, "canonical_schema"),
        _required_text(raw, "canonical_hash"),
        _required_text(raw, "atom_schema"),
        _required_text(raw, "atom_hash"),
    )


def _boundary_record_contains(
    result: Mapping[str, object], candidate_id: str, window_id: str
) -> bool:
    decisions = result.get("decisions")
    return (
        result.get("window_id") == window_id
        and isinstance(decisions, list)
        and sum(
            isinstance(item, Mapping) and item.get("candidate_id") == candidate_id
            for item in decisions
        )
        == 1
    )


def _exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} fields are invalid")


def _required_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _mapping_sequence(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{label} must be an object array")
    return tuple(cast(Mapping[str, object], item) for item in value)


def _string_sequence(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item and item == item.strip() for item in value
    ):
        raise ValueError(f"{label} must be a trimmed string array")
    result = tuple(cast(list[str], value))
    if len(result) != len(set(result)):
        raise ValueError(f"{label} must be unique")
    return result


def _required_text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item or item != item.strip():
        raise ValueError(f"{key} must be non-empty trimmed text")
    return item


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be non-empty trimmed text")
    return value


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
    if snapshot.narrative_map is None:
        raise ValueError("legacy Narrative Map projection is unavailable")
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
