"""Current-authority Story Map V2 path, detail, and source navigation.

The adapter accepts only Python-built visible selection IDs.  Browser input can
never supply route mechanics, M12 destination kinds, authority IDs, or source
locations.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final, Protocol, TypeVar

from renpy_story_mapper.canonical_graph_contract import CanonicalGraph, CanonicalNodeKind
from renpy_story_mapper.m11_scene_model import SceneModel, StoryAtom
from renpy_story_mapper.m12_model import DestinationKind
from renpy_story_mapper.storage import canonical_json
from renpy_story_mapper.story_map_v2.contracts import (
    ArmLineageStep,
    CoreBranchOutcome,
    StoryMapCore,
)
from renpy_story_mapper.story_map_v2.phase03_contracts import (
    NavigationBinding,
    SourceBinding,
    StoryArmReadModel,
    StoryChoiceReadModel,
    StoryEventReadModel,
    StoryMapReadModel,
)

PATH_SCHEMA: Final = "story-map-v2-path-v1"
DETAIL_SCHEMA: Final = "story-map-v2-detail-v1"
BOUNDARY_SELECTION_SCHEMA: Final = "story_map_v2_continuation_v1"
MAX_WITNESS_SCENES: Final = 80
MAX_WITNESS_CHOICES: Final = 80
MAX_WITNESS_REQUIREMENTS: Final = 80
MAX_WITNESS_EFFECTS: Final = 80
MAX_WITNESS_UNCERTAINTY: Final = 40
MAX_WITNESS_INSTRUCTIONS: Final = 120
MAX_WITNESS_TITLE_CHARS: Final = 160
MAX_WITNESS_TEXT_CHARS: Final = 1_000
CONTROL_ONLY_BOUNDARY_KINDS: Final = frozenset(
    {CanonicalNodeKind.MERGE, CanonicalNodeKind.LABEL_REGION}
)

Prepared = TypeVar("Prepared")


class NavigationAuthority(Protocol):
    @property
    def graph(self) -> CanonicalGraph: ...

    @property
    def scene_model(self) -> SceneModel: ...

    @property
    def canonical_hash(self) -> str: ...


class RouteSolveOutcome(Protocol):
    @property
    def cached(self) -> bool: ...

    @property
    def result(self) -> Mapping[str, object] | None: ...


class RouteService(Protocol[Prepared]):
    def prepare(self, destination_kind: str, target_id: str) -> Prepared: ...

    def solve(self, prepared: Prepared) -> RouteSolveOutcome: ...


class UnknownStorySelectionError(KeyError):
    """The browser supplied no current Python-built visible selection ID."""


class StoryNavigationAuthorityUnavailableError(RuntimeError):
    """Current M10/M11 authority cannot support deterministic navigation."""


@dataclass(frozen=True)
class NavigationSelection:
    selection_id: str
    role: str
    exact_node_ids: tuple[str, ...]
    source: SourceBinding
    anchor_line: int
    lineage: tuple[ArmLineageStep, ...] = ()
    effects: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Candidate:
    kind: DestinationKind
    target_id: str
    detail_kind: str
    detail_id: str
    atom_ids: tuple[str, ...]


def continuation_selection_id(path: str, node_id: str, line: int) -> str:
    """Return the frozen server-owned continuation identity."""

    payload = [BOUNDARY_SELECTION_SCHEMA, path, node_id, line]
    digest = hashlib.sha256(canonical_json(payload)).hexdigest()
    return f"story-map-v2-continuation:{digest}"


def _unique(values: Sequence[str | None]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in values if item))


def _core_selections(core: StoryMapCore) -> dict[str, NavigationSelection]:
    outcomes: dict[tuple[str, int], CoreBranchOutcome] = {}
    selections: dict[str, NavigationSelection] = {}
    for chunk in core.chunks:
        for outcome in chunk.branch_outcomes:
            key = (outcome.choice_key, outcome.arm_order)
            if key in outcomes:
                raise ValueError("Story Map V2 branch outcomes are not uniquely keyed")
            outcomes[key] = outcome
        for event in chunk.events:
            anchor = event.anchor
            if anchor.id in selections:
                raise ValueError("Story Map V2 visible selection IDs collide")
            selections[anchor.id] = NavigationSelection(
                anchor.id,
                "event",
                _unique((anchor.destination_id, anchor.canonical_node_id)),
                SourceBinding(event.relative_path, event.start_line, event.end_line),
                anchor.line,
                anchor.arm_lineage,
            )
    for chunk in core.chunks:
        for choice in chunk.choices:
            for arm in choice.arms:
                stored_outcome = outcomes.get((choice.key, arm.order))
                if stored_outcome is None:
                    raise ValueError("every visible choice arm requires one accepted outcome")
                anchor = stored_outcome.anchor
                if anchor.id in selections:
                    raise ValueError("Story Map V2 visible selection IDs collide")
                selections[anchor.id] = NavigationSelection(
                    anchor.id,
                    "arm",
                    _unique(
                        (
                            arm.destination_id,
                            anchor.destination_id,
                            anchor.canonical_node_id,
                        )
                    ),
                    SourceBinding(choice.relative_path, arm.start_line, arm.end_line),
                    anchor.line,
                    anchor.arm_lineage,
                    arm.effects,
                )
                if arm.rejoin_node_id is not None and arm.rejoin_line is not None:
                    boundary_id = continuation_selection_id(
                        choice.relative_path,
                        arm.rejoin_node_id,
                        arm.rejoin_line,
                    )
                    boundary = NavigationSelection(
                        boundary_id,
                        "boundary",
                        (arm.rejoin_node_id,),
                        SourceBinding(
                            choice.relative_path,
                            arm.rejoin_line,
                            arm.rejoin_line,
                        ),
                        arm.rejoin_line,
                    )
                    previous = selections.get(boundary_id)
                    if previous is not None:
                        if previous.role != "boundary" or previous != boundary:
                            raise ValueError(
                                "a deterministic boundary selection collides with visible authority"
                            )
                    else:
                        selections[boundary_id] = boundary
    return selections


def require_current_selection(core: StoryMapCore, selection_id: str) -> None:
    """Reject IDs that were not rebuilt from the current stored core."""

    if selection_id not in _core_selections(core):
        raise UnknownStorySelectionError(selection_id)


def _atom_node_ids(atom: StoryAtom) -> frozenset[str]:
    return frozenset((atom.primary_node_id, *atom.provenance.node_ids))


def _candidate_atoms_match_source(
    candidate: _Candidate,
    atoms: Mapping[str, StoryAtom],
    selection: NavigationSelection,
) -> bool:
    for atom_id in candidate.atom_ids:
        atom = atoms.get(atom_id)
        if atom is None:
            continue
        path, line, _column, _node_id = atom.source_order
        if _same_path(path, selection.source.relative_path) and (
            selection.source.start_line <= line <= selection.source.end_line
        ):
            return True
    return False


def _same_path(left: str, right: str) -> bool:
    normalized_left = left.replace("\\", "/").casefold().strip("/")
    normalized_right = right.replace("\\", "/").casefold().strip("/")
    return normalized_left == normalized_right or normalized_left.endswith(
        f"/{normalized_right}"
    ) or normalized_right.endswith(f"/{normalized_left}")


def _deduplicate(candidates: Sequence[_Candidate]) -> tuple[_Candidate, ...]:
    keyed: dict[tuple[DestinationKind, str], _Candidate] = {}
    for candidate in candidates:
        keyed[(candidate.kind, candidate.target_id)] = candidate
    return tuple(keyed[key] for key in sorted(keyed, key=lambda item: (item[0].value, item[1])))


def _forward_boundary_scenes(
    authority: NavigationAuthority,
    selection: NavigationSelection,
    atoms: Mapping[str, StoryAtom],
) -> tuple[_Candidate, ...]:
    outgoing: dict[str, set[str]] = defaultdict(set)
    for edge in authority.graph.edges:
        if edge.resolved:
            outgoing[edge.source_id].add(edge.target_id)
    scene_by_node: dict[str, set[str]] = defaultdict(set)
    node_kinds = {node.id: node.kind for node in authority.graph.nodes}
    model = authority.scene_model
    for scene in model.scenes:
        for atom_id in scene.atom_ids:
            atom = atoms[atom_id]
            if (
                not atom.story_facing
                or node_kinds.get(atom.primary_node_id) in CONTROL_ONLY_BOUNDARY_KINDS
            ):
                continue
            scene_by_node[atom.primary_node_id].add(scene.id)
    queue = deque((node_id, 0) for node_id in selection.exact_node_ids)
    seen = set(selection.exact_node_ids)
    found_depth: int | None = None
    found: set[str] = set()
    while queue:
        node_id, depth = queue.popleft()
        if found_depth is not None and depth > found_depth:
            break
        if depth > 0:
            scenes_at_depth = scene_by_node.get(node_id, ())
            if scenes_at_depth:
                found.update(scenes_at_depth)
                found_depth = depth
                continue
        if depth >= 32:
            continue
        for target in sorted(outgoing.get(node_id, ())):
            if target not in seen:
                seen.add(target)
                queue.append((target, depth + 1))
    scenes = {item.id: item for item in model.scenes}
    return tuple(
        _Candidate(
            DestinationKind.GENERIC_SCENE,
            scene_id,
            "m11_scene",
            scene_id,
            scenes[scene_id].atom_ids,
        )
        for scene_id in sorted(found)
    )


def _candidate_groups(
    authority: NavigationAuthority,
    selection: NavigationSelection,
) -> dict[DestinationKind, tuple[_Candidate, ...]]:
    model = authority.scene_model
    atoms = {item.id: item for item in model.atoms}
    exact = frozenset(selection.exact_node_ids)
    matching_atom_ids = {
        atom.id for atom in model.atoms if _atom_node_ids(atom).intersection(exact)
    }
    groups: dict[DestinationKind, list[_Candidate]] = defaultdict(list)

    for node in authority.graph.nodes:
        if node.kind is CanonicalNodeKind.TERMINAL and node.id in exact:
            groups[DestinationKind.TERMINAL].append(
                _Candidate(
                    DestinationKind.TERMINAL,
                    node.id,
                    "m10_canonical",
                    node.id,
                    (),
                )
            )
    for scene in model.scenes:
        direct = scene.id in exact
        matched = matching_atom_ids.intersection(scene.atom_ids)
        if direct or matched:
            groups[DestinationKind.GENERIC_SCENE].append(
                _Candidate(
                    DestinationKind.GENERIC_SCENE,
                    scene.id,
                    "m11_scene",
                    scene.id,
                    scene.atom_ids if direct else tuple(sorted(matched)),
                )
            )
            if scene.repeatability.value == "repeatable":
                groups[DestinationKind.REPEATABLE_EVENT].append(
                    _Candidate(
                        DestinationKind.REPEATABLE_EVENT,
                        scene.id,
                        "m11_scene",
                        scene.id,
                        scene.atom_ids if direct else tuple(sorted(matched)),
                    )
                )
    for occurrence in model.occurrences:
        occurrence_atoms = (occurrence.call_atom_id, *occurrence.referenced_atom_ids)
        if occurrence.id in exact or occurrence.call_atom_id in matching_atom_ids:
            groups[DestinationKind.EXACT_OCCURRENCE].append(
                _Candidate(
                    DestinationKind.EXACT_OCCURRENCE,
                    occurrence.id,
                    "m11_scene",
                    occurrence.id,
                    tuple(dict.fromkeys(occurrence_atoms)),
                )
            )
    requested_ordinal = selection.lineage[-1].arm_order - 1 if selection.lineage else None
    for branch in model.temporary_branches:
        for arm in branch.arms:
            matched = matching_atom_ids.intersection(arm.atom_ids)
            if arm.id in exact or matched:
                if requested_ordinal is not None and arm.ordinal != requested_ordinal:
                    continue
                groups[DestinationKind.TEMPORARY_OUTCOME].append(
                    _Candidate(
                        DestinationKind.TEMPORARY_OUTCOME,
                        arm.id,
                        "m11_scene",
                        arm.id,
                        arm.atom_ids if arm.id in exact else tuple(sorted(matched)),
                    )
                )
    scenes_by_atom = {
        atom_id: scene.id for scene in model.scenes for atom_id in scene.atom_ids
    }
    matched_scenes = {scenes_by_atom[item] for item in matching_atom_ids if item in scenes_by_atom}
    for lane in model.lanes:
        if lane.kind.value == "spine" or not lane.scene_ids:
            continue
        if lane.id in exact or matched_scenes.intersection(lane.scene_ids):
            lane_atoms = tuple(
                atom_id
                for scene in model.scenes
                if scene.id in lane.scene_ids
                for atom_id in scene.atom_ids
                if atom_id in matching_atom_ids
            )
            groups[DestinationKind.PERSISTENT_LANE].append(
                _Candidate(
                    DestinationKind.PERSISTENT_LANE,
                    lane.id,
                    "m11_scene",
                    lane.id,
                    lane_atoms,
                )
            )
    if selection.role == "boundary":
        groups[DestinationKind.GENERIC_SCENE] = list(
            _forward_boundary_scenes(authority, selection, atoms)
        )
    return {kind: _deduplicate(values) for kind, values in groups.items()}


def _resolve_binding(
    authority: NavigationAuthority,
    selection: NavigationSelection,
) -> NavigationBinding:
    groups = _candidate_groups(authority, selection)
    if selection.role == "boundary":
        priority: tuple[DestinationKind, ...] = (
            DestinationKind.GENERIC_SCENE,
            DestinationKind.TERMINAL,
        )
    elif selection.role == "arm" or selection.lineage:
        priority = (
            DestinationKind.TEMPORARY_OUTCOME,
            DestinationKind.PERSISTENT_LANE,
            DestinationKind.EXACT_OCCURRENCE,
            DestinationKind.TERMINAL,
            DestinationKind.GENERIC_SCENE,
            DestinationKind.REPEATABLE_EVENT,
        )
    else:
        priority = (
            DestinationKind.EXACT_OCCURRENCE,
            DestinationKind.TERMINAL,
            DestinationKind.PERSISTENT_LANE,
            DestinationKind.GENERIC_SCENE,
            DestinationKind.REPEATABLE_EVENT,
            DestinationKind.TEMPORARY_OUTCOME,
        )
    atoms = {item.id: item for item in authority.scene_model.atoms}
    for kind in priority:
        candidates = groups.get(kind, ())
        if len(candidates) > 1:
            source_matches = tuple(
                candidate
                for candidate in candidates
                if _candidate_atoms_match_source(candidate, atoms, selection)
            )
            if source_matches:
                candidates = source_matches
        if len(candidates) == 1:
            candidate = candidates[0]
            return NavigationBinding(
                selection.selection_id,
                candidate.kind.value,
                candidate.target_id,
                (
                    "story_map_v2_continuation"
                    if selection.role == "boundary"
                    else (
                        "story_map_v2_arm"
                        if selection.role == "arm"
                        else "story_map_v2_event"
                    )
                ),
                selection.selection_id,
                selection.source,
            )
        if len(candidates) > 1:
            return NavigationBinding(
                selection.selection_id,
                "unresolved",
                selection.exact_node_ids[0],
                "story_map_v2_unresolved",
                selection.selection_id,
                selection.source,
            )
    return NavigationBinding(
        selection.selection_id,
        "unresolved",
        selection.exact_node_ids[0],
        "story_map_v2_unresolved",
        selection.selection_id,
        selection.source,
    )


def _bind_choice(
    choice: StoryChoiceReadModel,
    bindings: Mapping[str, NavigationBinding],
    boundary_by_node: Mapping[tuple[str, int], NavigationBinding],
) -> StoryChoiceReadModel:
    arms: list[StoryArmReadModel] = []
    for arm in choice.arms:
        boundary = None
        if arm.rejoin_node_id is not None and arm.rejoin_line is not None:
            boundary = boundary_by_node.get((arm.rejoin_node_id, arm.rejoin_line))
            if boundary is not None and boundary.destination_kind not in {
                item.value for item in DestinationKind
            }:
                boundary = None
        arms.append(
            replace(
                arm,
                binding=bindings[arm.selection_id],
                nested_choices=tuple(
                    _bind_choice(item, bindings, boundary_by_node)
                    for item in arm.nested_choices
                ),
                rejoin_binding=boundary,
            )
        )
    return replace(choice, arms=tuple(arms))


def compact_witness(
    result: Mapping[str, object],
    *,
    selection_effects: Sequence[str] = (),
) -> tuple[dict[str, object], str | None]:
    """Project only M12's recommended known witness and honest completion state."""

    recommended_value = result.get("recommended")
    recommended = recommended_value if isinstance(recommended_value, Mapping) else {}
    claims = recommended.get("satisfying_effect_claims")
    effect_text = [
        str(item["text"])
        for item in claims
        if isinstance(claims, Sequence)
        and isinstance(item, Mapping)
        and isinstance(item.get("text"), str)
    ] if isinstance(claims, Sequence) and not isinstance(claims, (str, bytes)) else []
    for effect in selection_effects:
        if effect not in effect_text:
            effect_text.append(effect)
    witness = {
        "scene_titles": _string_list(
            recommended.get("scene_titles"),
            maximum_items=MAX_WITNESS_SCENES,
            maximum_chars=MAX_WITNESS_TITLE_CHARS,
        ),
        "visible_choices": _string_list(
            recommended.get("visible_choices"),
            maximum_items=MAX_WITNESS_CHOICES,
            maximum_chars=MAX_WITNESS_TEXT_CHARS,
        ),
        "requirements": _requirement_list(recommended.get("requirements")),
        "effects": [
            _bounded_text(item, MAX_WITNESS_TEXT_CHARS)
            for item in effect_text[:MAX_WITNESS_EFFECTS]
        ],
        "uncertainty": _string_list(
            recommended.get("uncertainty_warnings"),
            maximum_items=MAX_WITNESS_UNCERTAINTY,
            maximum_chars=MAX_WITNESS_TEXT_CHARS,
        ),
        "instructions": _instruction_list(recommended.get("instructions")),
    }
    complete = result.get("complete") is True
    if complete:
        return witness, None
    if recommended:
        return (
            witness,
            "The deterministic search did not prove a complete route; "
            "this is the known static prefix.",
        )
    status = result.get("status")
    if status == "dynamic_or_unknown_possibility":
        reason = "Dynamic or unresolved behavior may change whether this selection can be reached."
    elif status in {"no_route_in_resolved_static_graph", "state_infeasible"}:
        reason = "No route was proven by the complete resolved deterministic authority."
    else:
        reason = "No deterministic witness is currently available for this selection."
    return witness, reason


def _bounded_text(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    return f"{value[: maximum - 3]}..."


def _string_list(
    value: object,
    *,
    maximum_items: int,
    maximum_chars: int,
) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [
        _bounded_text(item, maximum_chars)
        for item in value[:maximum_items]
        if isinstance(item, str)
    ]


def _requirement_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    result: list[dict[str, object]] = []
    for item in value[:MAX_WITNESS_REQUIREMENTS]:
        if not isinstance(item, Mapping):
            continue
        expression = item.get("expression")
        source = item.get("source")
        if not isinstance(expression, str) or not isinstance(source, str):
            continue
        evidence_ids = item.get("evidence_ids")
        result.append(
            {
                "expression": _bounded_text(expression, MAX_WITNESS_TEXT_CHARS),
                "source": _bounded_text(source, 80),
                "evidence_ids": _string_list(
                    evidence_ids,
                    maximum_items=80,
                    maximum_chars=160,
                ),
            }
        )
    return result


def _instruction_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    result: list[dict[str, object]] = []
    for item in value[:MAX_WITNESS_INSTRUCTIONS]:
        if not isinstance(item, Mapping):
            continue
        ordinal = item.get("ordinal")
        kind = item.get("kind")
        text = item.get("text")
        if not isinstance(ordinal, int) or not isinstance(kind, str) or not isinstance(text, str):
            continue
        result.append(
            {
                "ordinal": ordinal,
                "kind": _bounded_text(kind, 80),
                "text": _bounded_text(text, MAX_WITNESS_TEXT_CHARS),
            }
        )
    return result


def unresolved_navigation_page(page: StoryMapReadModel) -> StoryMapReadModel:
    """Keep a stored story page visible when current M12 authority is unavailable."""

    def unresolved_binding(binding: NavigationBinding) -> NavigationBinding:
        return replace(binding, destination_kind="unresolved")

    def unresolved_choice(choice: StoryChoiceReadModel) -> StoryChoiceReadModel:
        return replace(
            choice,
            arms=tuple(
                replace(
                    arm,
                    binding=unresolved_binding(arm.binding),
                    nested_choices=tuple(
                        unresolved_choice(nested) for nested in arm.nested_choices
                    ),
                    rejoin_binding=None,
                )
                for arm in choice.arms
            ),
        )

    return replace(
        page,
        sections=tuple(
            replace(
                section,
                events=tuple(
                    replace(
                        event,
                        binding=unresolved_binding(event.binding),
                        choices=tuple(unresolved_choice(choice) for choice in event.choices),
                    )
                    for event in section.events
                ),
            )
            for section in page.sections
        ),
    )


class StoryMapNavigator[Prepared]:
    """Resolve and serve only current stored-core visible selections."""

    def __init__(
        self,
        authority: NavigationAuthority,
        service: RouteService[Prepared],
        core: StoryMapCore,
        page: StoryMapReadModel,
    ) -> None:
        self._page = page
        self._selections = _core_selections(core)
        self._authority = authority
        self._service = service
        self._bindings = {
            selection_id: _resolve_binding(self._authority, selection)
            for selection_id, selection in self._selections.items()
        }
        self._unresolved_reasons = {
            selection_id: self._unresolved_reason(selection_id)
            for selection_id, binding in self._bindings.items()
            if binding.destination_kind == "unresolved"
        }

    def _unresolved_reason(self, selection_id: str) -> str:
        selection = self._selections[selection_id]
        groups = _candidate_groups(self._authority, selection)
        if any(len(group) > 1 for group in groups.values()):
            return "Multiple current deterministic authority targets match this selection."
        return "No current deterministic M12 destination matches this selection."

    def bound_page(self) -> StoryMapReadModel:
        boundary_by_node: dict[tuple[str, int], NavigationBinding] = {}
        for selection_id, selection in self._selections.items():
            if selection.role == "boundary":
                boundary_by_node[(selection.exact_node_ids[0], selection.anchor_line)] = (
                    self._bindings[selection_id]
                )
        sections = tuple(
            replace(
                section,
                events=tuple(self._bind_event(event, boundary_by_node) for event in section.events),
            )
            for section in self._page.sections
        )
        return replace(self._page, sections=sections)

    def _bind_event(
        self,
        event: StoryEventReadModel,
        boundary_by_node: Mapping[tuple[str, int], NavigationBinding],
    ) -> StoryEventReadModel:
        return replace(
            event,
            binding=self._bindings[event.selection_id],
            choices=tuple(
                _bind_choice(choice, self._bindings, boundary_by_node)
                for choice in event.choices
            ),
        )

    def binding(self, selection_id: str) -> NavigationBinding:
        if selection_id not in self._selections:
            raise UnknownStorySelectionError(selection_id)
        return self._bindings[selection_id]

    def detail_service_target(self, selection_id: str) -> tuple[str, str]:
        """Adapt a resolved binding to an existing M10/M11 detail element."""

        binding = self.binding(selection_id)
        if binding.destination_kind == DestinationKind.TERMINAL.value:
            return "m10_canonical", binding.target_id
        if binding.destination_kind == DestinationKind.TEMPORARY_OUTCOME.value:
            owners = [
                branch.id
                for branch in self._authority.scene_model.temporary_branches
                if any(arm.id == binding.target_id for arm in branch.arms)
            ]
            if len(owners) != 1:
                raise ValueError("temporary outcome has no unique current M11 detail owner")
            return "m11_scene", owners[0]
        return "m11_scene", binding.target_id

    def path(self, selection_id: str) -> dict[str, object]:
        binding = self.binding(selection_id)
        selection = self._selections[selection_id]
        if binding.destination_kind == "unresolved":
            witness, _unused = compact_witness(
                {"complete": False, "recommended": {}},
                selection_effects=selection.effects,
            )
            return {
                "schema": PATH_SCHEMA,
                "semantic_level": "route_map",
                "status": "unresolved",
                "selection_id": selection_id,
                "binding": binding,
                "cached": False,
                "route_status": None,
                "complete": False,
                "explanation": self._unresolved_reasons[selection_id],
                "witness": witness,
            }
        prepared = self._service.prepare(binding.destination_kind, binding.target_id)
        outcome = self._service.solve(prepared)
        if outcome.result is None:
            witness, _unused = compact_witness(
                {"complete": False, "recommended": {}},
                selection_effects=selection.effects,
            )
            return {
                "schema": PATH_SCHEMA,
                "semantic_level": "route_map",
                "status": "unresolved",
                "selection_id": selection_id,
                "binding": binding,
                "cached": False,
                "route_status": None,
                "complete": False,
                "explanation": (
                    "The deterministic route attempt ended without a publishable result."
                ),
                "witness": witness,
            }
        result = outcome.result
        witness, explanation = compact_witness(result, selection_effects=selection.effects)
        return {
            "schema": PATH_SCHEMA,
            "semantic_level": "route_map",
            "status": "available",
            "selection_id": selection_id,
            "binding": binding,
            "cached": outcome.cached,
            "route_status": result.get("status"),
            "complete": result.get("complete") is True,
            "explanation": explanation,
            "witness": witness,
        }

    def source_navigation(self, selection_id: str) -> dict[str, object]:
        self.binding(selection_id)
        selection = self._selections[selection_id]
        node_by_id = {item.id: item for item in self._authority.graph.nodes}
        evidence_by_id = {item.id: item for item in self._authority.graph.evidence}
        matches: list[tuple[int, str, str, int, int, str]] = []
        for node_id in selection.exact_node_ids:
            node = node_by_id.get(node_id)
            if node is None:
                continue
            for evidence_id in node.evidence_ids:
                evidence = evidence_by_id.get(evidence_id)
                if evidence is None:
                    continue
                location = _source_location(evidence.source)
                if location is None or not _same_path(location[0], selection.source.relative_path):
                    continue
                path, start_line, end_line = location
                distance = abs(start_line - selection.anchor_line)
                matches.append(
                    (
                        distance,
                        evidence.id,
                        path,
                        start_line,
                        end_line,
                        evidence.line_basis or "physical",
                    )
                )
        if not matches:
            return {
                "status": "unavailable",
                "reason": "Exact current source evidence is unavailable for this selection.",
            }
        _distance, evidence_id, path, start_line, end_line, line_basis = min(matches)
        return {
            "status": "available",
            "path": path,
            "start_line": start_line,
            "end_line": end_line,
            "line_basis": line_basis,
            "evidence_id": evidence_id,
        }


def _source_location(source: Mapping[str, object]) -> tuple[str, int, int] | None:
    path = source.get("path")
    start = source.get("start")
    end = source.get("end")
    if not isinstance(path, str) or not isinstance(start, Mapping):
        return None
    start_line = start.get("line")
    if not isinstance(start_line, int) or start_line < 1:
        return None
    end_line = end.get("line") if isinstance(end, Mapping) else start_line
    if not isinstance(end_line, int) or end_line < start_line:
        end_line = start_line
    return path, start_line, end_line
