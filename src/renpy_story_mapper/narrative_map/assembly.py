"""Fail-closed deterministic assembly of complete M15 Narrative Events."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

from renpy_story_mapper.narrative_map.adapters import ordered_unique
from renpy_story_mapper.narrative_map.contracts import (
    BoundaryDecision,
    BoundaryDecisionKind,
    CoverageState,
    NarrativeCorridor,
    NarrativeEvent,
    Provenance,
    SourceLocator,
)
from renpy_story_mapper.narrative_map.corridors import build_boundary_candidates


def assemble_narrative_events(
    corridors: Sequence[NarrativeCorridor],
    decisions: Sequence[BoundaryDecision] = (),
    *,
    expected_atom_ids: Iterable[str] | None = None,
) -> tuple[NarrativeEvent, ...]:
    """Assemble adjacent corridors; every invalid membership or decision fails closed.

    Adjacency is evaluated within the exact lane/occurrence/temporary/loop stream. A merge may
    occur only through a validated ``merge`` decision for one emitted soft candidate. Missing,
    uncertain, or unavailable decisions retain the conservative boundary.
    """

    materialized = tuple(corridors)
    if not materialized:
        raise ValueError("event assembly requires at least one corridor")
    expected = None if expected_atom_ids is None else tuple(expected_atom_ids)
    _validate_corridors(materialized, expected)
    candidates = build_boundary_candidates(materialized)
    candidate_by_id = {item.candidate_id: item for item in candidates}
    candidate_by_pair = {
        (item.left_corridor_id, item.right_corridor_id): item for item in candidates
    }
    decisions_by_id: dict[str, BoundaryDecision] = {}
    for decision in decisions:
        candidate = candidate_by_id.get(decision.candidate.candidate_id)
        if candidate is None or candidate != decision.candidate:
            raise ValueError("boundary decision does not match an exact adjacent soft candidate")
        if decision.candidate.candidate_id in decisions_by_id:
            raise ValueError("a boundary candidate has duplicate decisions")
        decisions_by_id[decision.candidate.candidate_id] = decision

    streams: dict[tuple[object, ...], list[NarrativeCorridor]] = defaultdict(list)
    first_index: dict[str, int] = {}
    for index, corridor in enumerate(materialized):
        streams[_context(corridor)].append(corridor)
        first_index[corridor.corridor_id] = index

    event_groups: list[tuple[NarrativeCorridor, ...]] = []
    for stream in streams.values():
        group: list[NarrativeCorridor] = []
        for corridor in stream:
            if not group:
                group.append(corridor)
                continue
            left = group[-1]
            candidate = candidate_by_pair.get((left.corridor_id, corridor.corridor_id))
            candidate_decision = (
                None if candidate is None else decisions_by_id.get(candidate.candidate_id)
            )
            may_merge = (
                candidate is not None
                and candidate_decision is not None
                and candidate_decision.decision is BoundaryDecisionKind.MERGE
                and not left.hard_boundary_after
                and not corridor.hard_boundary_before
            )
            if may_merge:
                group.append(corridor)
            else:
                event_groups.append(tuple(group))
                group = [corridor]
        if group:
            event_groups.append(tuple(group))

    event_groups.sort(key=lambda group: min(first_index[item.corridor_id] for item in group))
    events = tuple(_event_from_group(group) for group in event_groups)
    _validate_event_membership(events, materialized, expected)
    return events


def _event_from_group(group: tuple[NarrativeCorridor, ...]) -> NarrativeEvent:
    first = group[0]
    atom_ids = tuple(atom_id for item in group for atom_id in item.ordered_atom_ids)
    technical_ids = {atom_id for item in group for atom_id in item.technical_atom_ids}
    provenance = Provenance(
        atom_ids=atom_ids,
        node_ids=ordered_unique(node_id for item in group for node_id in item.provenance.node_ids),
        edge_ids=ordered_unique(edge_id for item in group for edge_id in item.provenance.edge_ids),
        fact_ids=ordered_unique(fact_id for item in group for fact_id in item.provenance.fact_ids),
        evidence_ids=ordered_unique(
            evidence_id for item in group for evidence_id in item.provenance.evidence_ids
        ),
        locators=_ordered_unique_locators(
            locator for item in group for locator in item.provenance.locators
        ),
    )
    technical_only = set(atom_ids) == technical_ids
    return NarrativeEvent(
        authority=first.authority,
        ordered_corridor_ids=tuple(item.corridor_id for item in group),
        ordered_atom_ids=atom_ids,
        chapter_id=first.chapter_id,
        lane_id=first.lane_id,
        call_occurrence_id=first.call_occurrence_id,
        temporary_container_id=first.temporary_container_id,
        temporary_arm_id=first.temporary_arm_id,
        loop_id=first.loop_id,
        entry_node_id=first.entry_node_id,
        exit_node_id=group[-1].exit_node_id,
        nested_choice_ids=ordered_unique(
            choice_id for item in group for choice_id in item.choice_ids
        ),
        rejoin_node_ids=ordered_unique(
            node_id for item in group for node_id in item.rejoin_node_ids
        ),
        deterministic_title=_fallback_title(provenance.locators, technical_only),
        coverage_state=(
            CoverageState.TECHNICAL if technical_only else CoverageState.DETERMINISTIC_FALLBACK
        ),
        provenance=provenance,
    )


def _validate_corridors(
    corridors: tuple[NarrativeCorridor, ...],
    expected_atom_ids: Iterable[str] | None,
) -> None:
    authority = corridors[0].authority
    corridor_ids = [item.corridor_id for item in corridors]
    if len(corridor_ids) != len(set(corridor_ids)):
        raise ValueError("duplicate corridor membership is forbidden")
    if any(item.authority != authority for item in corridors):
        raise ValueError("corridors from different authority bindings cannot be assembled")
    atoms = [atom_id for item in corridors for atom_id in item.ordered_atom_ids]
    if len(atoms) != len(set(atoms)):
        raise ValueError("corridor atom membership overlaps")
    if expected_atom_ids is not None:
        expected = tuple(expected_atom_ids)
        if len(expected) != len(set(expected)):
            raise ValueError("expected atom coverage contains duplicates")
        if set(atoms) != set(expected):
            raise ValueError("corridor atom membership is missing or out of scope")
    positions: dict[tuple[object, ...], tuple[tuple[str, int], NarrativeCorridor]] = {}
    for corridor in corridors:
        context = _context(corridor)
        locator = _first_locator(corridor.provenance.locators)
        if locator is None:
            continue
        prior = positions.get(context)
        current = (locator.relative_path, locator.start_line)
        if prior is not None and current < prior[0]:
            raise ValueError("corridors are out of source/control order within a context")
        positions[context] = (current, corridor)


def _validate_event_membership(
    events: tuple[NarrativeEvent, ...],
    corridors: tuple[NarrativeCorridor, ...],
    expected_atom_ids: Iterable[str] | None,
) -> None:
    corridor_ids = [item for event in events for item in event.ordered_corridor_ids]
    expected_corridors = [item.corridor_id for item in corridors]
    if len(corridor_ids) != len(set(corridor_ids)) or set(corridor_ids) != set(expected_corridors):
        raise ValueError("event corridor membership is duplicate, missing, or crossing")
    atom_ids = [item for event in events for item in event.ordered_atom_ids]
    expected_atoms = [item for corridor in corridors for item in corridor.ordered_atom_ids]
    if len(atom_ids) != len(set(atom_ids)) or set(atom_ids) != set(expected_atoms):
        raise ValueError("event atom membership is duplicate, missing, or crossing")
    if expected_atom_ids is not None and set(atom_ids) != set(expected_atom_ids):
        raise ValueError("event atom membership is incomplete")


def _fallback_title(locators: tuple[SourceLocator, ...], technical: bool) -> str:
    prefix = "Technical coverage" if technical else "Narrative event"
    locator = _first_locator(locators)
    if locator is None:
        return prefix
    return f"{prefix} at line {locator.start_line}"


def _first_locator(locators: tuple[SourceLocator, ...]) -> SourceLocator | None:
    return min(locators, default=None, key=lambda item: (item.relative_path, item.start_line))


def _ordered_unique_locators(values: Iterable[SourceLocator]) -> tuple[SourceLocator, ...]:
    result: list[SourceLocator] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


def _context(corridor: NarrativeCorridor) -> tuple[object, ...]:
    return (
        corridor.chapter_id,
        corridor.lane_id,
        corridor.call_occurrence_id,
        corridor.loop_id,
        corridor.temporary_container_id,
        corridor.temporary_arm_id,
    )
