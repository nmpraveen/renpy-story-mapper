"""Deterministic presentation records for the M15 Narrative Map quotient."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from renpy_story_mapper.canonical_graph_contract import (
    CanonicalGraph,
    CanonicalNode,
    CanonicalNodeKind,
)
from renpy_story_mapper.narrative_map.contracts import (
    CoverageState,
    EvidenceNavigation,
    NarrativeEvent,
    NarrativeMapNode,
    NarrativeNodeKind,
    stable_m15_id,
)


@dataclass(frozen=True)
class PresentationIndex:
    nodes: tuple[NarrativeMapNode, ...]
    event_nodes: dict[str, str]
    choice_nodes: dict[str, str]
    rejoin_nodes: dict[str, str]
    canonical_node_to_map_node: dict[str, str]


def build_narrative_presentation(
    canonical: CanonicalGraph,
    events: tuple[NarrativeEvent, ...],
    *,
    major_start_event_ids: frozenset[str] = frozenset(),
) -> PresentationIndex:
    """Build stable event/choice/arm/rejoin nodes with Detail/Evidence navigation."""

    canonical_nodes = {item.id: item for item in canonical.nodes}
    canonical_regions = {item.id: item for item in canonical.regions}
    nodes: list[NarrativeMapNode] = []
    event_nodes: dict[str, str] = {}
    choice_nodes: dict[str, str] = {}
    rejoin_nodes: dict[str, str] = {}
    canonical_to_map: dict[str, str] = {}
    choice_owner: dict[str, str] = {}
    rejoin_owner: dict[str, str] = {}
    cluster_parent_by_event: dict[str, str | None] = {}

    for event in events:
        for choice_id in event.nested_choice_ids:
            if choice_id in choice_owner:
                raise ValueError("a deterministic choice cannot have multiple presentation owners")
            choice_owner[choice_id] = event.event_id
            choice_nodes[choice_id] = stable_m15_id("map_choice", [event.event_id, choice_id])

    current_cluster_id: str | None = None
    for event in events:
        map_node_id = stable_m15_id("map_node", [event.event_id, "event"])
        event_nodes[event.event_id] = map_node_id
        kind = _event_kind(event, canonical_nodes)
        if event.event_id in major_start_event_ids:
            current_cluster_id = map_node_id
            kind = NarrativeNodeKind.EVENT_CLUSTER
            cluster_parent_by_event[event.event_id] = None
        elif (
            kind is NarrativeNodeKind.EVENT_CLUSTER
            and current_cluster_id is not None
            and event.temporary_arm_id is None
        ):
            kind = NarrativeNodeKind.SUB_EVENT
            cluster_parent_by_event[event.event_id] = current_cluster_id
        else:
            cluster_parent_by_event[event.event_id] = None
        parent_node_id = None
        if event.temporary_arm_id is not None and event.temporary_container_id is not None:
            parent_node_id = choice_nodes.get(event.temporary_container_id)
        elif kind is NarrativeNodeKind.SUB_EVENT:
            parent_node_id = cluster_parent_by_event[event.event_id]
        nodes.append(
            NarrativeMapNode(
                node_id=map_node_id,
                kind=kind,
                title=event.ai_title or event.deterministic_title,
                ordinal=len(nodes),
                navigation=EvidenceNavigation("narrative_event", event.event_id),
                event_id=event.event_id,
                parent_node_id=parent_node_id,
                arm_id=event.temporary_arm_id,
                technical_count=(
                    len(event.ordered_atom_ids)
                    if event.coverage_state is CoverageState.TECHNICAL
                    else 0
                ),
            )
        )
        for node_id in event.provenance.node_ids:
            prior = canonical_to_map.setdefault(node_id, map_node_id)
            if prior != map_node_id:
                raise ValueError("canonical nodes cannot belong to multiple Narrative Events")

    for event in events:
        parent_id = event_nodes[event.event_id]
        for choice_id in event.nested_choice_ids:
            map_node_id = choice_nodes[choice_id]
            nodes.append(
                NarrativeMapNode(
                    node_id=map_node_id,
                    kind=NarrativeNodeKind.CHOICE,
                    title="Choice",
                    ordinal=len(nodes),
                    navigation=EvidenceNavigation("canonical_region", choice_id),
                    event_id=event.event_id,
                    parent_node_id=parent_id,
                    choice_id=choice_id,
                )
            )
            region = canonical_regions.get(choice_id)
            if region is not None:
                canonical_to_map[region.split_node_id] = map_node_id
        for rejoin_id in event.rejoin_node_ids:
            if rejoin_id in rejoin_owner:
                raise ValueError("a deterministic rejoin cannot have multiple presentation owners")
            rejoin_owner[rejoin_id] = event.event_id
            map_node_id = stable_m15_id("map_rejoin", [event.event_id, rejoin_id])
            rejoin_nodes[rejoin_id] = map_node_id
            nodes.append(
                NarrativeMapNode(
                    node_id=map_node_id,
                    kind=NarrativeNodeKind.REJOIN,
                    title="Proven rejoin",
                    ordinal=len(nodes),
                    navigation=EvidenceNavigation("canonical_node", rejoin_id),
                    event_id=event.event_id,
                    parent_node_id=parent_id,
                    rejoin_node_id=rejoin_id,
                )
            )
            canonical_to_map[rejoin_id] = map_node_id
    return PresentationIndex(
        nodes=tuple(nodes),
        event_nodes=event_nodes,
        choice_nodes=choice_nodes,
        rejoin_nodes=rejoin_nodes,
        canonical_node_to_map_node=canonical_to_map,
    )


def _event_kind(
    event: NarrativeEvent,
    canonical_nodes: Mapping[str, CanonicalNode],
) -> NarrativeNodeKind:
    if event.coverage_state is CoverageState.TECHNICAL:
        return NarrativeNodeKind.TECHNICAL_COVERAGE
    if event.temporary_arm_id is not None:
        return NarrativeNodeKind.CHOICE_ARM
    owned = [canonical_nodes[item] for item in event.provenance.node_ids if item in canonical_nodes]
    if any(getattr(item, "kind", None) is CanonicalNodeKind.UNRESOLVED for item in owned):
        return NarrativeNodeKind.UNRESOLVED
    if any(getattr(item, "kind", None) is CanonicalNodeKind.TERMINAL for item in owned):
        return NarrativeNodeKind.TERMINAL
    return NarrativeNodeKind.EVENT_CLUSTER
