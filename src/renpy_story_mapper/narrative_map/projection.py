"""Authoritative M10 quotient projection for M15 Narrative Events."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

from renpy_story_mapper.canonical_graph_contract import (
    CanonicalEdge,
    CanonicalGraph,
    CanonicalNodeKind,
)
from renpy_story_mapper.narrative_map.adapters import ordered_unique
from renpy_story_mapper.narrative_map.contracts import (
    NarrativeCorridor,
    NarrativeEdgeKind,
    NarrativeEvent,
    NarrativeMap,
    NarrativeMapEdge,
    NarrativeMapNode,
    NarrativeNodeKind,
)
from renpy_story_mapper.narrative_map.presentation import build_narrative_presentation


def build_narrative_map(
    canonical: CanonicalGraph,
    events: Sequence[NarrativeEvent],
    *,
    corridors: Sequence[NarrativeCorridor] = (),
) -> NarrativeMap:
    """Build a stable quotient whose every connector is backed by exact M10 edge IDs."""

    canonical.validate()
    materialized = tuple(events)
    if not materialized:
        raise ValueError("Narrative Map projection requires at least one event")
    authority = materialized[0].authority
    if authority.source_generation != canonical.source_generation:
        raise ValueError("Narrative Events are bound to a different source generation")
    if authority.canonical_hash != canonical.authority_hash:
        raise ValueError("Narrative Events are bound to a different M10 graph")
    if any(item.authority != authority for item in materialized):
        raise ValueError("Narrative Events from different authorities cannot share a map")
    correction_ids = {item.technical_correction_id for item in materialized}
    if len(correction_ids) != 1:
        raise ValueError("Narrative Events from different technical corrections cannot share a map")
    technical_correction_id = materialized[0].technical_correction_id
    if corridors and any(
        item.technical_correction_id != technical_correction_id for item in corridors
    ):
        raise ValueError("Narrative corridors and events use different technical corrections")

    presentation = build_narrative_presentation(
        canonical,
        materialized,
        major_start_event_ids=_major_start_events(materialized, corridors),
        collapsed_prefix_event_ids=_leading_technical_events(materialized),
    )
    node_kind = {item.id: item.kind for item in canonical.nodes}
    persistent_split_nodes = {
        item.split_node_id
        for item in canonical.regions
        if item.kind in {"persistent_route", "terminal_split"}
    }
    persistent_merge_nodes = {
        item.merge_node_id
        for item in canonical.regions
        if item.kind in {"persistent_route", "terminal_split"} and item.merge_node_id is not None
    }
    edges = _quotient_edges(
        canonical.edges,
        presentation.canonical_node_to_map_node,
        node_kind,
        presentation.rejoin_nodes,
        persistent_split_nodes,
        persistent_merge_nodes,
    )
    edges = (*edges, *_hidden_technical_continuity(edges, presentation.nodes))
    incoming = {item.target_node_id for item in edges}
    base_nodes = [
        item
        for item in presentation.nodes
        if item.event_id is not None
        and presentation.event_nodes.get(item.event_id) == item.node_id
        and item.kind is not NarrativeNodeKind.TECHNICAL_COVERAGE
    ]
    initial_candidates = tuple(item.node_id for item in base_nodes if item.node_id not in incoming)
    initial = initial_candidates[:1]
    if not initial and base_nodes:
        initial = (base_nodes[0].node_id,)
    hidden = ordered_unique(
        atom_id for corridor in corridors for atom_id in corridor.technical_atom_ids
    )
    return NarrativeMap(
        authority=authority,
        event_ids=tuple(item.event_id for item in materialized),
        nodes=presentation.nodes,
        edges=edges,
        initial_node_ids=initial,
        hidden_technical_atom_ids=hidden,
        technical_correction_id=technical_correction_id,
    )


def _major_start_events(
    events: tuple[NarrativeEvent, ...],
    corridors: Sequence[NarrativeCorridor],
) -> frozenset[str]:
    corridor_by_id = {item.corridor_id: item for item in corridors}
    result: set[str] = set()
    found_story = False
    current_chapter_id: str | None = None
    for event in events:
        technical = event.coverage_state.value == "technical"
        top_level = event.temporary_container_id is None and event.temporary_arm_id is None
        event_corridors = [
            corridor_by_id[item] for item in event.ordered_corridor_ids if item in corridor_by_id
        ]
        soft_start = any(item.soft_boundary_signals for item in event_corridors)
        chapter_start = found_story and event.chapter_id != current_chapter_id
        if top_level and not technical and (not found_story or soft_start or chapter_start):
            result.add(event.event_id)
            found_story = True
        if top_level and not technical:
            current_chapter_id = event.chapter_id
    if not result:
        for event in events:
            if event.coverage_state.value != "technical":
                result.add(event.event_id)
                break
    return frozenset(result)


def _leading_technical_events(events: tuple[NarrativeEvent, ...]) -> frozenset[str]:
    result: set[str] = set()
    for event in events:
        if event.coverage_state.value != "technical":
            break
        result.add(event.event_id)
    return frozenset(result)


def _quotient_edges(
    canonical_edges: Sequence[CanonicalEdge],
    node_to_map: Mapping[str, str],
    node_kind: Mapping[str, CanonicalNodeKind],
    rejoin_nodes: Mapping[str, str],
    persistent_split_nodes: set[str],
    persistent_merge_nodes: set[str],
) -> tuple[NarrativeMapEdge, ...]:
    grouped: dict[
        tuple[str, str, NarrativeEdgeKind, tuple[str, ...], tuple[str, ...]], list[str]
    ] = defaultdict(list)
    order: list[tuple[str, str, NarrativeEdgeKind, tuple[str, ...], tuple[str, ...]]] = []
    for edge in canonical_edges:
        source = node_to_map.get(edge.source_id)
        target = node_to_map.get(edge.target_id)
        if source is None or target is None:
            raise ValueError(f"authoritative edge {edge.id} escapes Narrative Event membership")
        kind = _edge_kind(
            edge,
            node_kind,
            rejoin_nodes,
            persistent_split_nodes,
            persistent_merge_nodes,
        )
        if source == target and kind is not NarrativeEdgeKind.LOOP:
            continue
        requirements = _attribute_ids(edge.attributes, "gate_ids", "requirement_ids")
        effects = _attribute_ids(edge.attributes, "effect_ids")
        key = (source, target, kind, requirements, effects)
        if key not in grouped:
            order.append(key)
        grouped[key].append(edge.id)
    return tuple(
        NarrativeMapEdge(
            source_node_id=key[0],
            target_node_id=key[1],
            kind=key[2],
            authority_edge_ids=ordered_unique(grouped[key]),
            requirement_ids=key[3],
            effect_ids=key[4],
        )
        for key in order
    )


def _hidden_technical_continuity(
    edges: Sequence[NarrativeMapEdge],
    nodes: Sequence[NarrativeMapNode],
) -> tuple[NarrativeMapEdge, ...]:
    """Collapse authoritative paths through hidden technical nodes for normal presentation."""

    technical_ids = {
        item.node_id
        for item in nodes
        if item.kind is NarrativeNodeKind.TECHNICAL_COVERAGE
    }
    if not technical_ids:
        return ()
    outgoing: dict[str, list[NarrativeMapEdge]] = defaultdict(list)
    for edge in edges:
        outgoing[edge.source_node_id].append(edge)
    result: list[NarrativeMapEdge] = []
    seen: set[str] = set()

    def walk(
        source_id: str,
        current_id: str,
        path: tuple[NarrativeMapEdge, ...],
        visited: frozenset[str],
    ) -> None:
        for edge in outgoing.get(current_id, ()):
            target_id = edge.target_node_id
            extended = (*path, edge)
            if target_id in technical_ids:
                if target_id not in visited:
                    walk(source_id, target_id, extended, visited | {target_id})
                continue
            if target_id == source_id or any(
                item.kind is not NarrativeEdgeKind.CONTINUATION for item in extended
            ):
                continue
            authority_ids = ordered_unique(
                authority_id
                for item in extended
                for authority_id in item.authority_edge_ids
            )
            continuity = NarrativeMapEdge(
                source_node_id=source_id,
                target_node_id=target_id,
                kind=NarrativeEdgeKind.CONTINUATION,
                authority_edge_ids=authority_ids,
                requirement_ids=ordered_unique(
                    requirement_id
                    for item in extended
                    for requirement_id in item.requirement_ids
                ),
                effect_ids=ordered_unique(
                    effect_id for item in extended for effect_id in item.effect_ids
                ),
            )
            if continuity.edge_id not in seen:
                seen.add(continuity.edge_id)
                result.append(continuity)

    for edge in edges:
        if edge.source_node_id in technical_ids or edge.target_node_id not in technical_ids:
            continue
        walk(
            edge.source_node_id,
            edge.target_node_id,
            (edge,),
            frozenset((edge.target_node_id,)),
        )
    return tuple(result)


def _edge_kind(
    edge: CanonicalEdge,
    node_kind: Mapping[str, CanonicalNodeKind],
    rejoin_nodes: Mapping[str, str],
    persistent_split_nodes: set[str],
    persistent_merge_nodes: set[str],
) -> NarrativeEdgeKind:
    roles = {str(item).casefold() for item in _iter_values(edge.attributes.get("semantic_roles"))}
    raw = edge.kind.casefold()
    if not edge.resolved or node_kind.get(edge.target_id) is CanonicalNodeKind.UNRESOLVED:
        return NarrativeEdgeKind.UNRESOLVED
    if "loop" in raw or any("loop" in item or "back" in item for item in roles):
        return NarrativeEdgeKind.LOOP
    if "return" in raw or any("return" in item for item in roles):
        return NarrativeEdgeKind.RETURN
    if "call" in raw or any("call" in item and "return" not in item for item in roles):
        return NarrativeEdgeKind.CALL
    if edge.target_id in persistent_merge_nodes or any(
        "persistent" in item and "merge" in item for item in roles
    ):
        return NarrativeEdgeKind.PERSISTENT_MERGE
    if edge.source_id in persistent_split_nodes or any("persistent" in item for item in roles):
        return NarrativeEdgeKind.PERSISTENT_SPLIT
    if edge.target_id in rejoin_nodes or any("rejoin" in item or "merge" in item for item in roles):
        return NarrativeEdgeKind.REJOIN
    if node_kind.get(edge.source_id) is CanonicalNodeKind.CHOICE or any(
        "choice" in item or "arm" in item for item in roles
    ):
        return NarrativeEdgeKind.CHOICE_ARM
    if node_kind.get(edge.target_id) is CanonicalNodeKind.TERMINAL:
        return NarrativeEdgeKind.TERMINAL
    return NarrativeEdgeKind.CONTINUATION


def _attribute_ids(attributes: Mapping[str, object], *names: str) -> tuple[str, ...]:
    return ordered_unique(
        item
        for name in names
        for item in _iter_values(attributes.get(name))
        if isinstance(item, str) and item.strip()
    )


def _iter_values(value: object) -> Iterable[object]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        return value
    return ()
