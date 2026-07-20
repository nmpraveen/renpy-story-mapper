"""Deterministic M15 narrative-corridor construction over exact M10/M11 authority."""

from __future__ import annotations

import heapq
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import cast

from renpy_story_mapper.canonical_graph_contract import (
    CanonicalEdge,
    CanonicalGraph,
    CanonicalNode,
    CanonicalRegion,
)
from renpy_story_mapper.m11_scene_model import AtomKind, SceneModel, StoryAtom
from renpy_story_mapper.narrative_map.adapters import (
    atom_locators,
    bind_m15_authority,
    ordered_unique,
)
from renpy_story_mapper.narrative_map.contracts import (
    BoundaryCandidate,
    BoundarySignal,
    NarrativeCorridor,
    Provenance,
    SourceLocator,
)

_PROGRESSION_RE = re.compile(r"^(day|chapter|prologue)$", re.IGNORECASE)
_VISUAL_COMMANDS = {"scene", "show", "hide", "image", "with", "at", "as"}


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
) -> tuple[NarrativeCorridor, ...]:
    """Build ordered, evidence-complete corridors without trusting M11 scene membership.

    Corridors are emitted in reconstructed control order. ``soft_boundary_signals`` belongs to
    the boundary immediately before that corridor. Visual commands are collapsed coverage; only
    a stable visual-family transition may become a soft candidate.
    """

    authority = bind_m15_authority(canonical, scene_model)
    atoms = {item.id: item for item in scene_model.atoms}
    edges = tuple(canonical.edges)
    if set(atoms) != {item.id for item in scene_model.atoms}:
        raise ValueError("M11 atom IDs must be unique")

    canonical_by_node = {item.id: item for item in canonical.nodes}
    occurrence_by_node = _call_occurrences(canonical.edges)
    temporary_by_node, choice_by_node, rejoin_by_node = _temporary_ownership(
        canonical.regions,
        canonical_by_node,
    )
    ordered_atoms = _control_order(tuple(atoms.values()), edges)
    progression_atom_ids = {
        atom.id
        for atom in ordered_atoms
        if _is_standalone_progression_marker(atom, canonical_by_node[atom.primary_node_id])
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

    leading_technical = _leading_technical_ids(
        ordered_atoms,
        canonical.regions,
        edges,
        progression_atom_ids,
    )
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
        structural = atom.id in split_atom_ids or atom.id in rejoin_atom_ids
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
                    )
                )
    return tuple(candidates)


def ordered_unique_locators(values: Iterable[SourceLocator]) -> tuple[SourceLocator, ...]:
    result: list[SourceLocator] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


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


def _leading_technical_ids(
    atoms: Sequence[StoryAtom],
    regions: Sequence[CanonicalRegion],
    edges: Sequence[CanonicalEdge],
    progression_atom_ids: set[str],
) -> set[str]:
    result: set[str] = set()
    for atom in atoms:
        if atom.story_facing:
            break
        result.add(atom.id)
    position = {item.id: index for index, item in enumerate(atoms)}
    atom_by_node = {item.primary_node_id: item for item in atoms}
    first_progression = min(
        (position[item] for item in progression_atom_ids),
        default=len(atoms),
    )
    temporary_kinds = {"local_detour", "optional_detour", "reconvergent_route_segment"}
    temporary_merge_nodes = {
        item.merge_node_id
        for item in regions
        if item.kind in temporary_kinds and item.merge_node_id is not None
    }
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.resolved:
            outgoing[edge.source_id].append(edge.target_id)
    anchor_positions: list[int] = []
    for region in regions:
        split_atom = atom_by_node.get(region.split_node_id)
        if (
            region.kind not in temporary_kinds
            or split_atom is None
            or region.merge_node_id is None
            or position[split_atom.id] >= first_progression
        ):
            continue
        member_atoms = [
            atom_by_node[node_id] for node_id in region.member_node_ids if node_id in atom_by_node
        ]
        if not any(
            item.kind in {AtomKind.CONDITION, AtomKind.STATE_CHANGE, AtomKind.TECHNICAL}
            for item in member_atoms
        ):
            continue
        pending = list(outgoing.get(region.merge_node_id, ()))
        visited: set[str] = set()
        while pending:
            node_id = pending.pop()
            if node_id in visited:
                raise ValueError("leading technical continuation contains a merge cycle")
            visited.add(node_id)
            if node_id in temporary_merge_nodes:
                pending.extend(outgoing.get(node_id, ()))
                continue
            anchor = atom_by_node.get(node_id)
            if (
                anchor is not None
                and anchor.story_facing
                and position[anchor.id] < first_progression
            ):
                anchor_positions.append(position[anchor.id])
    if anchor_positions:
        result.update(item.id for item in atoms[: max(anchor_positions)])
    return result


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


def _is_standalone_progression_marker(atom: StoryAtom, node: CanonicalNode) -> bool:
    source_kind = node.attributes.get("source_kind", atom.source_kind)
    if atom.kind is not AtomKind.VISUAL_CHANGE or source_kind != "scene":
        return False
    words = re.findall(r"[a-z]+", atom.label.casefold())
    meaningful = [item for item in words if item not in _VISUAL_COMMANDS]
    return len(meaningful) == 1 and _PROGRESSION_RE.fullmatch(meaningful[0]) is not None


def _is_collapsed_technical(atom: StoryAtom) -> bool:
    return atom.source_kind == "module_end" or not atom.story_facing or atom.kind in {
        AtomKind.VISUAL_CHANGE,
        AtomKind.CONDITION,
        AtomKind.STATE_CHANGE,
        AtomKind.CALL,
        AtomKind.LOOP,
        AtomKind.TECHNICAL,
    }


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
