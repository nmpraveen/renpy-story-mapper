"""Deterministic M15 narrative-corridor construction over exact M10/M11 authority."""

from __future__ import annotations

import heapq
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from typing import cast

from renpy_story_mapper.canonical_graph_contract import (
    CanonicalEdge,
    CanonicalGraph,
    CanonicalNode,
    CanonicalRegion,
)
from renpy_story_mapper.m11_scene_model import (
    AtomKind,
    CallSiteOccurrence,
    SceneModel,
    StoryAtom,
)
from renpy_story_mapper.narrative_map.adapters import (
    atom_locators,
    bind_m15_authority,
    ordered_unique,
)
from renpy_story_mapper.narrative_map.contracts import (
    AuthorityBinding,
    BoundaryCandidate,
    BoundarySignal,
    LeadingTechnicalCoverageCorrection,
    NarrativeCorridor,
    Provenance,
    QualifiedSourceLocator,
    SourceLocator,
    stable_m15_id,
)
from renpy_story_mapper.narrative_map.semantic_contracts import (
    BoundaryWindow,
    FineNarrativeUnit,
    NarrativeGapCandidate,
)

_PROGRESSION_RE = re.compile(r"^(day|chapter|prologue)$", re.IGNORECASE)
_VISUAL_COMMANDS = {"scene", "show", "hide", "image", "with", "at", "as"}
_SCENE_MODIFIER_WORDS = {"with", "at", "onlayer", "zorder", "behind"}


@dataclass(frozen=True)
class _Context:
    chapter_id: str | None
    lane_id: str
    occurrence_id: str | None
    loop_id: str | None
    container_id: str | None
    arm_id: str | None


@dataclass
class _Segment:
    atom_ids: list[str]
    context: _Context
    hard_before: bool
    hard_after: bool
    signals: tuple[BoundarySignal, ...]


def build_narrative_corridors(
    canonical: CanonicalGraph,
    scene_model: SceneModel,
    *,
    technical_correction: LeadingTechnicalCoverageCorrection | None = None,
) -> tuple[NarrativeCorridor, ...]:
    """Build ordered, evidence-complete corridors without trusting M11 scene membership.

    Corridors are emitted in reconstructed control order. ``soft_boundary_signals`` belongs to
    the boundary immediately before that corridor. Visual commands are collapsed coverage; only
    a stable visual-family transition may become a soft candidate.
    """

    authority = bind_m15_authority(canonical, scene_model)
    atoms = {item.id: item for item in scene_model.atoms}
    edges = tuple(sorted(canonical.edges, key=lambda item: item.id))
    regions = tuple(sorted(canonical.regions, key=lambda item: item.id))
    if set(atoms) != {item.id for item in scene_model.atoms}:
        raise ValueError("M11 atom IDs must be unique")

    canonical_by_node = {item.id: item for item in canonical.nodes}
    occurrence_by_node = _call_occurrences(edges)
    temporary_by_node, choice_by_node, rejoin_by_node = _temporary_ownership(
        regions,
        canonical_by_node,
    )
    ordered_atoms = _control_order(tuple(atoms.values()), edges)
    progression_atom_ids = {
        atom.id
        for atom in ordered_atoms
        if _is_standalone_progression_marker(canonical_by_node[atom.primary_node_id])
    }
    progression_by_atom = _progression_contexts(ordered_atoms, progression_atom_ids)
    contexts: dict[str, _Context] = {}
    for atom_id, atom in atoms.items():
        node = canonical_by_node[atom.primary_node_id]
        container_id, arm_id = temporary_by_node.get(atom.primary_node_id, (None, None))
        contexts[atom_id] = _Context(
            chapter_id=progression_by_atom[atom_id],
            lane_id=_canonical_lane(node.attributes),
            occurrence_id=occurrence_by_node.get(atom.primary_node_id),
            loop_id=_canonical_loop(node),
            container_id=container_id,
            arm_id=arm_id,
        )

    correction_id: str | None = None
    if technical_correction is None:
        leading_technical = _leading_technical_ids(ordered_atoms)
    else:
        try:
            resolved_prefix = resolve_leading_technical_coverage_correction(
                canonical,
                scene_model,
                technical_correction,
            )
        except ValueError:
            leading_technical = _leading_technical_ids(ordered_atoms)
        else:
            leading_technical = set(resolved_prefix)
            correction_id = technical_correction.correction_id
    soft_before = _soft_boundaries(
        ordered_atoms,
        contexts,
        edges,
        progression_atom_ids,
    )
    choice_by_atom = {
        atom.id: choice_by_node[atom.primary_node_id]
        for atom in ordered_atoms
        if atom.primary_node_id in choice_by_node
    }
    split_atom_ids = set(choice_by_atom)
    rejoin_atom_ids = {atom.id for atom in ordered_atoms if atom.primary_node_id in rejoin_by_node}

    segments: list[_Segment] = []
    previous: StoryAtom | None = None
    for atom in ordered_atoms:
        context = contexts[atom.id]
        node_kind = canonical_by_node[atom.primary_node_id].kind.value
        structural = (
            atom.id in split_atom_ids
            or atom.id in rejoin_atom_ids
            or node_kind in {"choice", "condition", "merge"}
        )
        isolated = structural or atom.kind in {
            AtomKind.CALL,
            AtomKind.LOOP,
            AtomKind.TERMINAL,
            AtomKind.UNRESOLVED,
        }
        context_change = previous is not None and contexts[previous.id] != context
        prior_isolated = previous is not None and (
            previous.id in split_atom_ids
            or previous.id in rejoin_atom_ids
            or canonical_by_node[previous.primary_node_id].kind.value
            in {"choice", "condition", "merge"}
            or previous.kind
            in {AtomKind.CALL, AtomKind.LOOP, AtomKind.TERMINAL, AtomKind.UNRESOLVED}
        )
        prefix_transition = bool(
            previous is not None
            and previous.id in leading_technical
            and atom.id not in leading_technical
        )
        hard_before = context_change or isolated or prior_isolated or prefix_transition
        signals = () if hard_before else soft_before.get(atom.id, ())
        if not segments or hard_before or signals:
            if segments and hard_before:
                segments[-1].hard_after = True
            segments.append(_Segment([atom.id], context, hard_before, isolated, signals))
        else:
            segments[-1].atom_ids.append(atom.id)
            if isolated:
                segments[-1].hard_after = True
        previous = atom

    evidence_by_id = {item.id: item for item in canonical.evidence}
    edge_by_id = {item.id: item for item in canonical.edges}
    node_to_atom = {item.primary_node_id: item.id for item in scene_model.atoms}
    result: list[NarrativeCorridor] = []
    for segment in segments:
        member_atoms = tuple(atoms[item] for item in segment.atom_ids)
        member_nodes = ordered_unique(item.primary_node_id for item in member_atoms)
        member_node_set = set(member_nodes)
        incident = tuple(
            edge.id
            for edge in edges
            if edge.source_id in member_node_set or edge.target_id in member_node_set
        )
        technical = tuple(
            item.id
            for item in member_atoms
            if item.id in leading_technical or _is_collapsed_technical(item)
        )
        choices = ordered_unique(
            choice for item in member_atoms for choice in choice_by_atom.get(item.id, ())
        )
        rejoins = ordered_unique(
            rejoin_by_node[item.primary_node_id]
            for item in member_atoms
            if item.primary_node_id in rejoin_by_node
        )
        provenance = Provenance(
            atom_ids=tuple(segment.atom_ids),
            node_ids=member_nodes,
            edge_ids=incident,
            fact_ids=ordered_unique(
                fact_id for item in member_atoms for fact_id in item.provenance.fact_ids
            ),
            evidence_ids=ordered_unique(
                evidence_id for item in member_atoms for evidence_id in item.provenance.evidence_ids
            ),
            locators=ordered_unique_locators(
                locator for item in member_atoms for locator in atom_locators(item, evidence_by_id)
            ),
        )
        entry_node_id, exit_node_id = _entry_exit_nodes(
            member_nodes,
            incident,
            edge_by_id,
            node_to_atom,
            segment.atom_ids,
        )
        result.append(
            NarrativeCorridor(
                authority=authority,
                lane_id=segment.context.lane_id,
                chapter_id=segment.context.chapter_id,
                call_occurrence_id=segment.context.occurrence_id,
                loop_id=segment.context.loop_id,
                temporary_container_id=segment.context.container_id,
                temporary_arm_id=segment.context.arm_id,
                ordered_atom_ids=tuple(segment.atom_ids),
                entry_node_id=entry_node_id,
                exit_node_id=exit_node_id,
                incident_edge_ids=incident,
                choice_ids=choices,
                rejoin_node_ids=rejoins,
                hard_boundary_before=segment.hard_before,
                hard_boundary_after=segment.hard_after,
                soft_boundary_signals=segment.signals,
                technical_atom_ids=technical,
                technical_correction_id=correction_id,
                provenance=provenance,
            )
        )
    _validate_corridor_coverage(result, atoms)
    return tuple(result)


def build_boundary_candidates(
    corridors: Sequence[NarrativeCorridor],
) -> tuple[BoundaryCandidate, ...]:
    """Create only exact adjacent, non-hard soft-boundary candidates."""

    candidates: list[BoundaryCandidate] = []
    streams: dict[tuple[object, ...], list[NarrativeCorridor]] = defaultdict(list)
    for corridor in corridors:
        streams[_corridor_context(corridor)].append(corridor)
    for stream in streams.values():
        for left, right in pairwise(stream):
            if (
                right.soft_boundary_signals
                and not left.hard_boundary_after
                and not right.hard_boundary_before
            ):
                candidates.append(
                    BoundaryCandidate(
                        authority=right.authority,
                        left_corridor_id=left.corridor_id,
                        right_corridor_id=right.corridor_id,
                        signals=right.soft_boundary_signals,
                        evidence_ids=ordered_unique(
                            (*left.provenance.evidence_ids, *right.provenance.evidence_ids)
                        ),
                        technical_correction_id=right.technical_correction_id,
                    )
                )
    return tuple(candidates)


def build_fine_narrative_units(
    canonical: CanonicalGraph,
    scene_model: SceneModel,
) -> tuple[FineNarrativeUnit, ...]:
    """Project one story-facing M11 atom per unit over exact M10 structural locks.

    M11 contributes only the atom classification and text-facing speaker identity.  Ordering,
    lanes, calls, loops, temporary-arm ownership, split/rejoin locks, nodes, edges, facts, and
    evidence all come from the bound M10 graph.  Non-story atoms may be attached only as context;
    they never become an additional story-facing member of a unit.
    """

    authority = bind_m15_authority(canonical, scene_model)
    corridors = build_narrative_corridors(canonical, scene_model)
    atom_by_id = {item.id: item for item in scene_model.atoms}
    if len(atom_by_id) != len(scene_model.atoms):
        raise ValueError("M11 atom IDs must be unique")
    canonical_edges = tuple(sorted(canonical.edges, key=lambda item: item.id))
    canonical_regions = tuple(sorted(canonical.regions, key=lambda item: item.id))
    ordered_atoms = _control_order(tuple(scene_model.atoms), canonical_edges)
    order_by_atom = {item.id: index for index, item in enumerate(ordered_atoms)}
    corridor_by_atom: dict[str, int] = {}
    for corridor_index, corridor in enumerate(corridors):
        for atom_id in corridor.ordered_atom_ids:
            prior = corridor_by_atom.setdefault(atom_id, corridor_index)
            if prior != corridor_index:
                raise ValueError("one atom cannot belong to multiple fine-unit lock scopes")
    if set(corridor_by_atom) != set(atom_by_id):
        raise ValueError("fine-unit preparation lost authoritative atom coverage")

    sequence_by_corridor = _fine_sequence_ids(corridors)
    story_atoms_by_corridor: dict[int, list[str]] = defaultdict(list)
    for atom in ordered_atoms:
        if atom.story_facing:
            story_atoms_by_corridor[corridor_by_atom[atom.id]].append(atom.id)

    # Technical context is attached exactly once and cannot silently become story membership.
    context_by_story: dict[str, list[str]] = {
        atom_id: [] for values in story_atoms_by_corridor.values() for atom_id in values
    }
    for corridor_index, corridor in enumerate(corridors):
        story_ids = story_atoms_by_corridor.get(corridor_index, [])
        technical_ids = [
            atom_id for atom_id in corridor.ordered_atom_ids if atom_id not in context_by_story
        ]
        if story_ids:
            for atom_id in technical_ids:
                owner = min(
                    story_ids,
                    key=lambda candidate: (
                        abs(order_by_atom[candidate] - order_by_atom[atom_id]),
                        order_by_atom[candidate] < order_by_atom[atom_id],
                        order_by_atom[candidate],
                    ),
                )
                context_by_story[owner].append(atom_id)
            continue
        adjacent_owner = _adjacent_story_owner(
            corridor_index,
            corridors,
            story_atoms_by_corridor,
            canonical_edges,
            atom_by_id,
        )
        if adjacent_owner is not None:
            context_by_story[adjacent_owner].extend(technical_ids)

    evidence_by_id = {item.id: item for item in canonical.evidence}
    edge_by_id = {item.id: item for item in canonical_edges}
    regions_by_node: dict[str, list[str]] = defaultdict(list)
    for region in canonical_regions:
        for node_id in {
            region.split_node_id,
            *region.member_node_ids,
            *((region.merge_node_id,) if region.merge_node_id is not None else ()),
        }:
            regions_by_node[node_id].append(region.id)

    sequence_ordinals: dict[str, int] = defaultdict(int)
    result: list[FineNarrativeUnit] = []
    for story_atom in ordered_atoms:
        if not story_atom.story_facing:
            continue
        corridor_index = corridor_by_atom[story_atom.id]
        corridor = corridors[corridor_index]
        sequence_id = sequence_by_corridor[corridor_index]
        attached_ids = sorted(
            context_by_story[story_atom.id],
            key=lambda atom_id: (order_by_atom[atom_id], atom_id),
        )
        member_ids = tuple(
            sorted(
                (story_atom.id, *attached_ids),
                key=lambda atom_id: (order_by_atom[atom_id], atom_id),
            )
        )
        member_atoms = tuple(atom_by_id[item] for item in member_ids)
        member_nodes = ordered_unique(item.primary_node_id for item in member_atoms)
        member_node_set = set(member_nodes)
        incident_edge_ids = tuple(
            edge.id
            for edge in canonical_edges
            if edge.source_id in member_node_set or edge.target_id in member_node_set
        )
        entry_node_id, exit_node_id = _entry_exit_nodes(
            member_nodes,
            incident_edge_ids,
            edge_by_id,
            {item.primary_node_id: item.id for item in scene_model.atoms},
            list(member_ids),
        )
        locators = ordered_unique_locators(
            locator for atom in member_atoms for locator in atom_locators(atom, evidence_by_id)
        )
        story_locators = atom_locators(story_atom, evidence_by_id)
        if not story_locators:
            raise ValueError("a fine narrative unit requires an exact story locator")
        fact_ids = ordered_unique(
            fact_id for atom in member_atoms for fact_id in atom.provenance.fact_ids
        )
        evidence_ids = ordered_unique(
            evidence_id for atom in member_atoms for evidence_id in atom.provenance.evidence_ids
        )
        context_ids = ordered_unique(
            (
                *((corridor.chapter_id,) if corridor.chapter_id is not None else ()),
                *(
                    (corridor.call_occurrence_id,)
                    if corridor.call_occurrence_id is not None
                    else ()
                ),
                *((corridor.loop_id,) if corridor.loop_id is not None else ()),
                *((corridor.temporary_container_id,) if corridor.temporary_container_id else ()),
                *((corridor.temporary_arm_id,) if corridor.temporary_arm_id else ()),
                *(region_id for node_id in member_nodes for region_id in regions_by_node[node_id]),
            )
        )
        ordinal = sequence_ordinals[sequence_id]
        sequence_ordinals[sequence_id] += 1
        result.append(
            FineNarrativeUnit(
                authority=authority,
                sequence_id=sequence_id,
                ordinal=ordinal,
                story_atom_id=story_atom.id,
                story_locator=story_locators[0],
                technical_context_atom_ids=tuple(attached_ids),
                node_ids=member_nodes,
                evidence_ids=evidence_ids,
                speaker_ids=((story_atom.speaker,) if story_atom.speaker else ()),
                context_ids=context_ids,
                lane_id=corridor.lane_id,
                call_occurrence_id=corridor.call_occurrence_id,
                loop_id=corridor.loop_id,
                parent_choice_id=corridor.temporary_container_id,
                parent_arm_id=corridor.temporary_arm_id,
                entry_node_id=entry_node_id,
                exit_node_id=exit_node_id,
                incident_edge_ids=incident_edge_ids,
                provenance=Provenance(
                    atom_ids=member_ids,
                    node_ids=member_nodes,
                    edge_ids=incident_edge_ids,
                    fact_ids=fact_ids,
                    evidence_ids=evidence_ids,
                    locators=locators,
                ),
            )
        )
    expanded = _expand_call_occurrence_units(
        tuple(result),
        ordered_atoms,
        tuple(scene_model.occurrences),
        order_by_atom,
    )
    _validate_fine_units(
        expanded,
        tuple(item.story_atom_id for item in expanded),
        authority,
    )
    if {item.story_atom_id for item in expanded} != {
        item.id for item in ordered_atoms if item.story_facing
    }:
        raise ValueError("call-occurrence expansion lost story-facing atom coverage")
    return expanded


def build_all_eligible_gap_candidates(
    units: Sequence[FineNarrativeUnit],
) -> tuple[NarrativeGapCandidate, ...]:
    """Emit exactly one stable candidate for every adjacent pair in each unlocked sequence."""

    materialized = tuple(units)
    if not materialized:
        return ()
    authority = materialized[0].authority
    unit_ids = [item.unit_id for item in materialized]
    if len(unit_ids) != len(set(unit_ids)):
        raise ValueError("fine-unit input contains duplicate identities")
    if any(item.authority != authority for item in materialized):
        raise ValueError("fine units from different authority bindings cannot share candidates")
    closed_sequences: set[str] = set()
    active_sequence: str | None = None
    for unit in materialized:
        if unit.sequence_id == active_sequence:
            continue
        if unit.sequence_id in closed_sequences:
            raise ValueError("fine-unit sequence is discontiguous in encounter order")
        if active_sequence is not None:
            closed_sequences.add(active_sequence)
        active_sequence = unit.sequence_id
    streams: dict[str, list[FineNarrativeUnit]] = defaultdict(list)
    for unit in materialized:
        streams[unit.sequence_id].append(unit)
    candidates: list[NarrativeGapCandidate] = []
    for sequence_id, stream in streams.items():
        ordinals = [item.ordinal for item in stream]
        if ordinals != list(range(len(stream))):
            raise ValueError("fine-unit ordinals must be contiguous in encounter order")
        for ordinal, (left, right) in enumerate(pairwise(stream)):
            if _fine_context(left) != _fine_context(right):
                raise ValueError("one fine-unit sequence crosses an authoritative hard lock")
            candidates.append(
                NarrativeGapCandidate(
                    authority=authority,
                    sequence_id=sequence_id,
                    ordinal=ordinal,
                    left_unit_id=left.unit_id,
                    right_unit_id=right.unit_id,
                    lane_id=right.lane_id,
                    call_occurrence_id=right.call_occurrence_id,
                    loop_id=right.loop_id,
                    parent_choice_id=right.parent_choice_id,
                    parent_arm_id=right.parent_arm_id,
                    evidence_ids=ordered_unique((*left.evidence_ids, *right.evidence_ids)),
                )
            )
    return tuple(candidates)


def build_boundary_windows(
    units: Sequence[FineNarrativeUnit],
    candidates: Sequence[NarrativeGapCandidate],
    *,
    maximum_owned_candidates: int = 8,
    context_halo_units: int = 2,
) -> tuple[BoundaryWindow, ...]:
    """Batch exhaustive candidates with deterministic, bounded same-sequence context halos."""

    if maximum_owned_candidates <= 0 or context_halo_units < 0:
        raise ValueError("boundary-window bounds must be positive and non-negative")
    materialized_units = tuple(units)
    expected = build_all_eligible_gap_candidates(materialized_units)
    if tuple(candidates) != expected:
        raise ValueError("boundary windows require the exact exhaustive candidate sequence")
    if not expected:
        return ()
    unit_by_id = {item.unit_id: item for item in materialized_units}
    sequence_units: dict[str, list[str]] = defaultdict(list)
    for unit in materialized_units:
        sequence_units[unit.sequence_id].append(unit.unit_id)
    candidates_by_sequence: dict[str, list[NarrativeGapCandidate]] = defaultdict(list)
    for candidate in expected:
        candidates_by_sequence[candidate.sequence_id].append(candidate)
    windows: list[BoundaryWindow] = []
    maximum_context_units = maximum_owned_candidates + 1 + context_halo_units * 2
    for sequence_id, sequence_candidates in candidates_by_sequence.items():
        sequence = sequence_units[sequence_id]
        for start in range(0, len(sequence_candidates), maximum_owned_candidates):
            owned = sequence_candidates[start : start + maximum_owned_candidates]
            left_index = sequence.index(owned[0].left_unit_id)
            right_index = sequence.index(owned[-1].right_unit_id)
            halo_start = max(0, left_index - context_halo_units)
            halo_end = min(len(sequence), right_index + context_halo_units + 1)
            context_ids = sequence[halo_start:halo_end]
            windows.append(
                BoundaryWindow(
                    authority=unit_by_id[owned[0].left_unit_id].authority,
                    ordinal=len(windows),
                    owned_candidate_ids=tuple(item.candidate_id for item in owned),
                    context_unit_ids=tuple(context_ids),
                    maximum_context_units=maximum_context_units,
                )
            )
    return tuple(windows)


def ordered_unique_locators(values: Iterable[SourceLocator]) -> tuple[SourceLocator, ...]:
    result: list[SourceLocator] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


def _expand_call_occurrence_units(
    units: tuple[FineNarrativeUnit, ...],
    ordered_atoms: tuple[StoryAtom, ...],
    occurrences: tuple[CallSiteOccurrence, ...],
    order_by_atom: dict[str, int],
) -> tuple[FineNarrativeUnit, ...]:
    """Expand shared referenced atoms once per exact M11 call occurrence."""

    if not occurrences:
        return units
    unit_by_story = {item.story_atom_id: item for item in units}
    if len(unit_by_story) != len(units):
        raise ValueError("base fine units must own unique story atoms before occurrence expansion")
    sorted_occurrences = tuple(
        sorted(
            occurrences,
            key=lambda item: (order_by_atom.get(item.call_atom_id, len(order_by_atom)), item.id),
        )
    )
    occurrences_by_call: dict[str, list[CallSiteOccurrence]] = defaultdict(list)
    referenced_atom_ids: set[str] = set()
    for occurrence in sorted_occurrences:
        if len(occurrence.referenced_atom_ids) != len(set(occurrence.referenced_atom_ids)):
            raise ValueError("one call occurrence repeats referenced atom identity")
        occurrences_by_call[occurrence.call_atom_id].append(occurrence)
        referenced_atom_ids.update(occurrence.referenced_atom_ids)

    result: list[FineNarrativeUnit] = []
    emitted: set[tuple[str, str | None]] = set()
    sequence_ordinals: dict[str, int] = defaultdict(int)

    def append_unit(story_atom_id: str, occurrence_id: str | None) -> None:
        unit = unit_by_story.get(story_atom_id)
        if unit is None:
            return
        key = (story_atom_id, occurrence_id)
        if key in emitted:
            raise ValueError("one story atom is duplicated within a call occurrence")
        emitted.add(key)
        if occurrence_id is None:
            sequence_id = unit.sequence_id
            call_occurrence_id = unit.call_occurrence_id
        else:
            sequence_id = stable_m15_id(
                "fine_sequence_occurrence",
                {
                    "authority": unit.authority.to_dict(),
                    "base_sequence_id": unit.sequence_id,
                    "call_occurrence_id": occurrence_id,
                },
            )
            call_occurrence_id = occurrence_id
        ordinal = sequence_ordinals[sequence_id]
        sequence_ordinals[sequence_id] += 1
        result.append(
            replace(
                unit,
                sequence_id=sequence_id,
                ordinal=ordinal,
                call_occurrence_id=call_occurrence_id,
                context_ids=ordered_unique(
                    (
                        *unit.context_ids,
                        *((occurrence_id,) if occurrence_id is not None else ()),
                    )
                ),
            )
        )

    def append_occurrence(occurrence: CallSiteOccurrence, active: set[str]) -> None:
        if occurrence.id in active:
            raise ValueError("call-occurrence expansion contains a cycle")
        active.add(occurrence.id)
        append_unit(occurrence.call_atom_id, occurrence.id)
        for atom_id in occurrence.referenced_atom_ids:
            nested = occurrences_by_call.get(atom_id)
            if nested:
                for nested_occurrence in nested:
                    append_occurrence(nested_occurrence, active)
            else:
                append_unit(atom_id, occurrence.id)
        active.remove(occurrence.id)

    for atom in ordered_atoms:
        atom_occurrences = occurrences_by_call.get(atom.id)
        if atom_occurrences:
            if atom.id not in referenced_atom_ids:
                for occurrence in atom_occurrences:
                    append_occurrence(occurrence, set())
            continue
        if atom.id not in referenced_atom_ids:
            append_unit(atom.id, None)
    return tuple(result)


def _fine_sequence_ids(corridors: Sequence[NarrativeCorridor]) -> dict[int, str]:
    result: dict[int, str] = {}
    first_in_sequence: NarrativeCorridor | None = None
    prior: NarrativeCorridor | None = None
    for index, corridor in enumerate(corridors):
        starts_sequence = (
            prior is None
            or prior.hard_boundary_after
            or corridor.hard_boundary_before
            or _corridor_context(prior) != _corridor_context(corridor)
        )
        if starts_sequence:
            first_in_sequence = corridor
        if first_in_sequence is None:  # pragma: no cover - guarded by the first item
            raise AssertionError("fine-unit sequence lacks its first corridor")
        result[index] = stable_m15_id(
            "fine_sequence",
            {
                "authority": corridor.authority.to_dict(),
                "context": [
                    corridor.chapter_id,
                    corridor.lane_id,
                    corridor.call_occurrence_id,
                    corridor.loop_id,
                    corridor.temporary_container_id,
                    corridor.temporary_arm_id,
                ],
                "first_corridor_id": first_in_sequence.corridor_id,
            },
        )
        prior = corridor
    return result


def _adjacent_story_owner(
    corridor_index: int,
    corridors: Sequence[NarrativeCorridor],
    story_atoms_by_corridor: dict[int, list[str]],
    edges: Sequence[CanonicalEdge],
    atom_by_id: dict[str, StoryAtom],
) -> str | None:
    """Attach a technical-only corridor only through an unlocked, direct M10 adjacency."""

    corridor = corridors[corridor_index]
    member_nodes = {atom_by_id[atom_id].primary_node_id for atom_id in corridor.ordered_atom_ids}
    candidates: list[tuple[int, int, str]] = []
    for neighbor_index in (corridor_index - 1, corridor_index + 1):
        if not 0 <= neighbor_index < len(corridors):
            continue
        neighbor = corridors[neighbor_index]
        if _corridor_context(neighbor) != _corridor_context(corridor):
            continue
        if neighbor_index < corridor_index:
            if neighbor.hard_boundary_after or corridor.hard_boundary_before:
                continue
        elif corridor.hard_boundary_after or neighbor.hard_boundary_before:
            continue
        story_ids = story_atoms_by_corridor.get(neighbor_index, [])
        for story_id in story_ids:
            story_node = atom_by_id[story_id].primary_node_id
            directly_incident = any(
                (edge.source_id in member_nodes and edge.target_id == story_node)
                or (edge.target_id in member_nodes and edge.source_id == story_node)
                for edge in edges
            )
            if directly_incident:
                candidates.append((abs(neighbor_index - corridor_index), neighbor_index, story_id))
    if not candidates:
        return None
    return min(candidates)[2]


def _fine_context(unit: FineNarrativeUnit) -> tuple[object, ...]:
    return (
        unit.lane_id,
        next((item for item in unit.context_ids if item.startswith("progression:")), None),
        unit.call_occurrence_id,
        unit.loop_id,
        unit.parent_choice_id,
        unit.parent_arm_id,
    )


def _validate_fine_units(
    units: tuple[FineNarrativeUnit, ...],
    expected_story_atom_ids: tuple[str, ...],
    authority: AuthorityBinding,
) -> None:
    if not expected_story_atom_ids:
        if units:
            raise ValueError("technical-only authority cannot produce story-facing units")
        return
    story_ids = [item.story_atom_id for item in units]
    if story_ids != list(expected_story_atom_ids):
        raise ValueError("fine narrative units do not match occurrence-qualified story order")
    unit_ids = [item.unit_id for item in units]
    if len(unit_ids) != len(set(unit_ids)):
        raise ValueError("fine narrative units contain duplicate occurrence-qualified identities")
    if any(item.authority != authority for item in units):
        raise ValueError("fine narrative units changed authority binding")
    context_ids = [
        (atom_id, item.call_occurrence_id)
        for item in units
        for atom_id in item.technical_context_atom_ids
    ]
    if len(context_ids) != len(set(context_ids)):
        raise ValueError("technical context cannot belong to multiple fine narrative units")
    for unit in units:
        owned_atom_ids = (unit.story_atom_id, *unit.technical_context_atom_ids)
        if len(unit.provenance.atom_ids) != len(set(unit.provenance.atom_ids)) or set(
            unit.provenance.atom_ids
        ) != set(owned_atom_ids):
            raise ValueError("fine-unit provenance and atom ownership disagree")
        if set(unit.node_ids) != set(unit.provenance.node_ids):
            raise ValueError("fine-unit node provenance is not exact")
        if set(unit.evidence_ids) != set(unit.provenance.evidence_ids):
            raise ValueError("fine-unit evidence provenance is not exact")


def _temporary_ownership(
    regions: Sequence[CanonicalRegion],
    canonical_by_node: dict[str, CanonicalNode],
) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, ...]], dict[str, str]]:
    region_by_id = {item.id: item for item in regions}
    temporary_kinds = {
        "local_detour",
        "optional_detour",
        "reconvergent_route_segment",
    }
    depth: dict[str, int] = {}

    def region_depth(region_id: str) -> int:
        if region_id in depth:
            return depth[region_id]
        region = region_by_id[region_id]
        parent = region.attributes.get("parent_region_id")
        parent_id = parent if isinstance(parent, str) and parent in region_by_id else None
        if parent_id is None:
            containers = [
                item
                for item in regions
                if item.id != region.id
                and item.kind in temporary_kinds
                and region.split_node_id in item.member_node_ids
            ]
            container = min(containers, key=lambda item: len(item.member_node_ids), default=None)
            parent_id = None if container is None else container.id
        depth[region_id] = 0 if parent_id is None else region_depth(parent_id) + 1
        return depth[region_id]

    memberships: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    choices: dict[str, list[str]] = defaultdict(list)
    rejoin_by_node: dict[str, str] = {}
    for region in regions:
        if region.kind not in temporary_kinds:
            continue
        split = canonical_by_node[region.split_node_id]
        split_attributes = split.attributes
        if split.kind.value == "choice" or split_attributes.get("source_kind") == "menu":
            choices[region.split_node_id].append(region.id)
        if region.merge_node_id is not None:
            rejoin_by_node[region.merge_node_id] = region.merge_node_id
        arms = region.attributes.get("arms")
        if not isinstance(arms, Sequence) or isinstance(arms, str | bytes):
            raise ValueError(f"canonical region {region.id} has invalid arm authority")
        for raw_arm in arms:
            if not isinstance(raw_arm, dict):
                raise ValueError(f"canonical region {region.id} has invalid arm authority")
            arm = cast(dict[str, object], raw_arm)
            arm_id = arm.get("id")
            entry_node_id = arm.get("entry_node_id")
            members = arm.get("member_node_ids")
            if (
                not isinstance(arm_id, str)
                or not isinstance(entry_node_id, str)
                or not isinstance(members, Sequence)
                or isinstance(members, str | bytes)
            ):
                raise ValueError(f"canonical region {region.id} has invalid arm authority")
            member_ids = [entry_node_id, *(item for item in members if isinstance(item, str))]
            for node_id in member_ids:
                memberships[node_id].append((region_depth(region.id), region.id, arm_id))
    ownership: dict[str, tuple[str, str]] = {}
    for atom_id, items in memberships.items():
        ordered = sorted(items)
        ownership[atom_id] = (ordered[-1][1], ordered[-1][2])
    return ownership, {key: ordered_unique(value) for key, value in choices.items()}, rejoin_by_node


def _call_occurrences(edges: Sequence[CanonicalEdge]) -> dict[str, str]:
    result: dict[str, str] = {}
    for edge in edges:
        call_site_id = edge.attributes.get("call_site_id")
        if not isinstance(call_site_id, str) or not call_site_id:
            continue
        prior = result.setdefault(edge.source_id, call_site_id)
        if prior != call_site_id:
            raise ValueError("one canonical call source has multiple occurrence identities")
    return result


def _canonical_lane(attributes: object) -> str:
    if isinstance(attributes, dict):
        route = attributes.get("route")
        if isinstance(route, dict):
            lane_id = route.get("lane_id")
            if isinstance(lane_id, str) and lane_id:
                return lane_id
    return "lane_story_spine"


def _canonical_loop(node: CanonicalNode) -> str | None:
    attributes = node.attributes
    if not isinstance(attributes, dict):
        return node.id if node.kind.value == "loop" else None
    loop_ids = attributes.get("loop_ids")
    if not isinstance(loop_ids, Sequence) or isinstance(loop_ids, str | bytes):
        return node.id if node.kind.value == "loop" else None
    values = sorted(item for item in loop_ids if isinstance(item, str) and item)
    if values:
        return "/".join(values)
    return node.id if node.kind.value == "loop" else None


def _control_order(
    atoms: tuple[StoryAtom, ...],
    edges: tuple[CanonicalEdge, ...],
) -> tuple[StoryAtom, ...]:
    atom_by_node = {item.primary_node_id: item for item in atoms}
    by_id = {item.id: item for item in atoms}
    adjacency: dict[str, list[str]] = defaultdict(list)
    indegree = {item.id: 0 for item in atoms}
    for edge in edges:
        source = atom_by_node.get(edge.source_id)
        target = atom_by_node.get(edge.target_id)
        if source is None or target is None or source.id == target.id:
            continue
        if target.id not in adjacency[source.id]:
            adjacency[source.id].append(target.id)
            indegree[target.id] += 1
    keys = {item.id: _source_key(item) for item in atoms}
    heap = [(keys[item_id], item_id) for item_id, degree in indegree.items() if degree == 0]
    heapq.heapify(heap)
    remaining = set(indegree)
    result: list[StoryAtom] = []
    while remaining:
        if not heap:
            item_id = min(remaining, key=lambda value: (keys[value], value))
            heapq.heappush(heap, (keys[item_id], item_id))
        _key, atom_id = heapq.heappop(heap)
        if atom_id not in remaining:
            continue
        remaining.remove(atom_id)
        result.append(by_id[atom_id])
        for target_id in adjacency.get(atom_id, ()):
            indegree[target_id] -= 1
            if indegree[target_id] <= 0 and target_id in remaining:
                heapq.heappush(heap, (keys[target_id], target_id))
    return tuple(result)


def _source_key(atom: StoryAtom) -> tuple[object, ...]:
    path, line, column, node_id = atom.source_order
    kind_rank = 0 if atom.kind in {AtomKind.CHOICE, AtomKind.CONDITION} else 1
    return (path.replace("\\", "/"), line, column, kind_rank, node_id)


def _leading_technical_ids(atoms: Sequence[StoryAtom]) -> set[str]:
    result: set[str] = set()
    for atom in atoms:
        if atom.story_facing:
            break
        result.add(atom.id)
    return result


def resolve_leading_technical_coverage_correction(
    canonical: CanonicalGraph,
    scene_model: SceneModel,
    correction: LeadingTechnicalCoverageCorrection,
) -> tuple[str, ...]:
    """Resolve a correction only when both locators and IDs prove the same strict prefix."""

    authority = bind_m15_authority(canonical, scene_model)
    if correction.authority != authority:
        raise ValueError("technical correction authority is stale")
    ordered_atoms = _control_order(tuple(scene_model.atoms), tuple(canonical.edges))
    ordered_ids = tuple(item.id for item in ordered_atoms)
    prefix_length = len(correction.ordered_atom_ids)
    if prefix_length == 0 or prefix_length >= len(ordered_ids):
        raise ValueError("technical correction must identify a strict prefix")
    unknown = set(correction.ordered_atom_ids) - set(ordered_ids)
    if unknown:
        raise ValueError("technical correction contains an unknown atom ID")
    if correction.ordered_atom_ids != ordered_ids[:prefix_length]:
        raise ValueError("technical correction atom IDs are not the ordered prefix")

    evidence_by_id = {item.id: item for item in canonical.evidence}
    atom_by_id = {item.id: item for item in ordered_atoms}
    for qualified in correction.qualified_locators:
        atom = atom_by_id.get(qualified.atom_id)
        if atom is None:
            raise ValueError("technical correction locator names an unknown atom")
        if atom.primary_node_id != qualified.primary_node_id:
            raise ValueError("technical correction locator primary node is mismatched")
        if atom.provenance.evidence_ids != qualified.evidence_ids:
            raise ValueError("technical correction locator evidence is stale or mismatched")
        if qualified.source not in atom_locators(atom, evidence_by_id):
            raise ValueError("technical correction locator source does not resolve uniquely")
    return correction.ordered_atom_ids


def create_leading_technical_coverage_correction(
    canonical: CanonicalGraph,
    scene_model: SceneModel,
    qualified_locators: Sequence[SourceLocator],
    *,
    reason: str,
) -> LeadingTechnicalCoverageCorrection:
    """Create authority only when qualified locators prove one exact strict prefix."""

    ordered_atoms = _control_order(tuple(scene_model.atoms), tuple(canonical.edges))
    evidence_by_id = {item.id: item for item in canonical.evidence}
    resolved: list[str] = []
    used_locators: set[int] = set()
    for atom in ordered_atoms:
        locators = atom_locators(atom, evidence_by_id)
        hits = tuple(
            index
            for index, locator in enumerate(qualified_locators)
            if any(_locator_contains(locator, atom_locator) for atom_locator in locators)
        )
        if not hits:
            break
        if len(hits) != 1:
            raise ValueError("technical correction locator resolution is ambiguous")
        used_locators.add(hits[0])
        resolved.append(atom.id)
    if used_locators != set(range(len(qualified_locators))):
        raise ValueError("technical correction locator does not resolve the leading prefix")
    qualified: list[QualifiedSourceLocator] = []
    for atom in ordered_atoms[: len(resolved)]:
        exact_locators = atom_locators(atom, evidence_by_id)
        matching = tuple(
            item
            for item in exact_locators
            if any(_locator_contains(source, item) for source in qualified_locators)
        )
        if not matching:
            raise ValueError("technical correction locator does not resolve the leading prefix")
        qualified.append(
            QualifiedSourceLocator(
                atom_id=atom.id,
                primary_node_id=atom.primary_node_id,
                evidence_ids=atom.provenance.evidence_ids,
                source=matching[0],
            )
        )
    correction = LeadingTechnicalCoverageCorrection(
        authority=bind_m15_authority(canonical, scene_model),
        reason=reason,
        qualified_locators=tuple(qualified),
        ordered_atom_ids=tuple(resolved),
    )
    resolve_leading_technical_coverage_correction(canonical, scene_model, correction)
    return correction


def _locator_contains(qualified: SourceLocator, atom: SourceLocator) -> bool:
    return (
        qualified.relative_path.replace("\\", "/") == atom.relative_path.replace("\\", "/")
        and qualified.line_basis == atom.line_basis
        and qualified.start_line <= atom.start_line
        and qualified.end_line >= atom.end_line
    )


def _progression_contexts(
    atoms: Sequence[StoryAtom],
    progression_atom_ids: set[str],
) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    current: str | None = None
    for atom in atoms:
        if atom.id in progression_atom_ids:
            current = f"progression:{atom.primary_node_id}"
        result[atom.id] = current
    return result


def _soft_boundaries(
    atoms: Sequence[StoryAtom],
    contexts: dict[str, _Context],
    edges: Sequence[CanonicalEdge],
    progression_atom_ids: set[str],
) -> dict[str, tuple[BoundarySignal, ...]]:
    result: dict[str, list[BoundarySignal]] = defaultdict(list)
    by_context: dict[_Context, list[StoryAtom]] = defaultdict(list)
    for atom in atoms:
        by_context[contexts[atom.id]].append(atom)

    resolved_pairs = {(item.source_id, item.target_id) for item in edges if item.resolved}
    for stream in by_context.values():
        for left, right in pairwise(stream):
            if (
                left.source_order[0] != right.source_order[0]
                and (left.primary_node_id, right.primary_node_id) in resolved_pairs
            ):
                result[right.id].append(BoundarySignal.RESOLVED_TRANSFER)
        _stable_visual_boundaries(stream, result, progression_atom_ids)
        _stable_cast_boundaries(stream, result)
    return {key: tuple(dict.fromkeys(values)) for key, values in result.items()}


def _stable_visual_boundaries(
    stream: Sequence[StoryAtom],
    result: dict[str, list[BoundarySignal]],
    progression_atom_ids: set[str],
) -> None:
    scenes = [
        (index, item, _visual_family(item.label))
        for index, item in enumerate(stream)
        if item.kind is AtomKind.VISUAL_CHANGE and item.source_kind == "scene"
    ]
    scenes = [item for item in scenes if item[2] is not None]
    for visual_index in range(1, len(scenes)):
        prior_family = scenes[visual_index - 1][2]
        family = scenes[visual_index][2]
        if family == prior_family:
            continue
        prior_run = 0
        for item in reversed(scenes[:visual_index]):
            if item[2] != prior_family:
                break
            prior_run += 1
        next_run = 0
        for item in scenes[visual_index:]:
            if item[2] != family:
                break
            next_run += 1
        if prior_run < 2 or next_run < 2:
            continue
        current_position = scenes[visual_index][0]
        previous_position = scenes[visual_index - 1][0]
        if any(
            item.id in progression_atom_ids
            for item in stream[previous_position + 1 : current_position]
        ):
            continue
        cut_position = current_position
        for index in range(previous_position, current_position):
            left = stream[index]
            right = stream[index + 1]
            if (
                left.source_order[0] == right.source_order[0]
                and right.source_order[1] - left.source_order[1] > 1
            ):
                cut_position = index + 1
                break
        result[stream[cut_position].id].append(BoundarySignal.VISUAL_FAMILY)


def _stable_cast_boundaries(
    stream: Sequence[StoryAtom],
    result: dict[str, list[BoundarySignal]],
) -> None:
    narrative = [item for item in stream if item.speaker]
    for index in range(2, len(narrative) - 1):
        prior = {item.speaker for item in narrative[index - 2 : index]}
        following = {item.speaker for item in narrative[index : index + 2]}
        if len(prior) == 1 and len(following) == 1 and prior.isdisjoint(following):
            result[narrative[index].id].append(BoundarySignal.CAST)


def _visual_family(label: str) -> str | None:
    words = re.findall(r"[a-z]+", label.casefold())
    meaningful = [
        item
        for item in words
        if item not in _VISUAL_COMMANDS and not _PROGRESSION_RE.fullmatch(item)
    ]
    return meaningful[0] if meaningful else None


def _is_standalone_progression_marker(node: CanonicalNode) -> bool:
    source_kind_value = node.attributes.get("source_kind")
    source_text_value = node.attributes.get("source_text")
    if source_kind_value != "scene" or not isinstance(source_text_value, str):
        return False
    words = re.findall(r"[a-z]+", source_text_value.casefold())
    return (
        len(words) >= 2
        and words[0] == "scene"
        and _PROGRESSION_RE.fullmatch(words[1]) is not None
        and (len(words) == 2 or words[2] in _SCENE_MODIFIER_WORDS)
    )


def _is_collapsed_technical(atom: StoryAtom) -> bool:
    return (
        atom.source_kind == "module_end"
        or not atom.story_facing
        or atom.kind
        in {
            AtomKind.VISUAL_CHANGE,
            AtomKind.CONDITION,
            AtomKind.STATE_CHANGE,
            AtomKind.CALL,
            AtomKind.LOOP,
            AtomKind.TECHNICAL,
        }
    )


def _entry_exit_nodes(
    member_nodes: tuple[str, ...],
    incident_edge_ids: tuple[str, ...],
    edge_by_id: dict[str, CanonicalEdge],
    node_to_atom: dict[str, str],
    ordered_atom_ids: list[str],
) -> tuple[str, str]:
    members = set(member_nodes)
    incoming: set[str] = set()
    outgoing: set[str] = set()
    for edge_id in incident_edge_ids:
        edge = edge_by_id[edge_id]
        if edge.target_id in members and edge.source_id not in members:
            incoming.add(edge.target_id)
        if edge.source_id in members and edge.target_id not in members:
            outgoing.add(edge.source_id)
    order = {atom_id: index for index, atom_id in enumerate(ordered_atom_ids)}

    def rank(node_id: str) -> tuple[int, str]:
        return (order.get(node_to_atom.get(node_id, ""), len(order)), node_id)

    entry = min(incoming or members, key=rank)
    exit_node = max(outgoing or members, key=rank)
    return entry, exit_node


def _validate_corridor_coverage(
    corridors: Sequence[NarrativeCorridor],
    atoms: dict[str, StoryAtom],
) -> None:
    owned = [atom_id for corridor in corridors for atom_id in corridor.ordered_atom_ids]
    if len(owned) != len(set(owned)):
        raise ValueError("corridor atom membership overlaps")
    if set(owned) != set(atoms):
        raise ValueError("corridor atom membership is incomplete")


def _corridor_context(corridor: NarrativeCorridor) -> tuple[object, ...]:
    return (
        corridor.chapter_id,
        corridor.lane_id,
        corridor.call_occurrence_id,
        corridor.loop_id,
        corridor.temporary_container_id,
        corridor.temporary_arm_id,
    )
