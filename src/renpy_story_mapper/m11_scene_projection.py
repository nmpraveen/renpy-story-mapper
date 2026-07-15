"""Deterministic human-scene projection over M10 canonical authority only."""

from __future__ import annotations

import hashlib
import heapq
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import cast

from renpy_story_mapper.canonical_graph_contract import (
    CANONICAL_GRAPH_SCHEMA,
    CANONICAL_GRAPH_SCHEMA_VERSION,
    CanonicalGraph,
)
from renpy_story_mapper.m11_scene_model import (
    M11_ATOM_RULE_VERSION,
    M11_BOUNDARY_RULE_VERSION,
    M11_SCENE_MODEL_SCHEMA,
    AtomKind,
    BoundaryDecision,
    BoundaryStrength,
    CallSiteOccurrence,
    CanonicalBinding,
    CanonicalCoverage,
    Chapter,
    Correction,
    CorrectionOperation,
    CorrectionOverlay,
    CorrectionStatus,
    CoverageCollection,
    CoverageDisposition,
    CoverageEntry,
    DecisionStatus,
    LaneKind,
    LoopHub,
    OccurrenceKind,
    PartialOrderRelation,
    PersistentLane,
    Provenance,
    ReturnToHub,
    Scene,
    SceneModel,
    SceneRepeatability,
    StoryAtom,
    TemporaryBranchArm,
    TemporaryBranchContainer,
    stable_m11_id,
)
from renpy_story_mapper.state import StateCategory, infer_state_category
from renpy_story_mapper.storage import canonical_json

STORY_ATOMS_SCHEMA = "m11-story-atoms-v1"
SCENE_BOUNDARIES_SCHEMA = "m11-scene-boundaries-v1"
SCENE_ASSEMBLY_SCHEMA = "m11-scene-assembly-v1"
SCENE_PRESENTATION_SCHEMA = "m11-scene-presentation-v1"

_TEMPORARY_REGION_KINDS = frozenset(
    {"local_detour", "optional_detour", "reconvergent_route_segment"}
)
_PERSISTENT_REGION_KINDS = frozenset({"persistent_route", "terminal_split"})
_DAY_OR_CHAPTER = re.compile(
    r"(?:^|[_\s.-])(?:day|chapter|episode|act)[_\s.-]*(?:\d+|[a-z]+)(?:$|[_\s.-])",
    re.IGNORECASE,
)
_PROGRESSION_EFFECT = re.compile(
    r"\b(?:day|chapter|episode|act)\b\s*(?:\+=|=)", re.IGNORECASE
)
_MINIMUM_NARRATIVE_RUN = 3
_ORDERING_IGNORED_EDGE_KINDS = frozenset({"call_enter"})
_ORDERING_CYCLE_EDGE_KINDS = frozenset({"loop_back"})
_MAX_RELATIONSHIP_CANONICAL_EDGE_IDS = 60


@dataclass(frozen=True)
class _LaneSpec:
    kind: LaneKind
    region_id: str | None
    arm_ordinal: int | None
    parent_lane_id: str | None
    split_atom_id: str | None
    merge_node_id: str | None
    provenance: Provenance


@dataclass(frozen=True)
class _ArmContextCandidate:
    region_id: str
    arm_ordinal: int
    depth: int
    member_count: int


def build_story_atoms(
    canonical: CanonicalGraph | Mapping[str, object],
    *,
    canonical_binding: CanonicalBinding | None = None,
) -> dict[str, object]:
    """Project one stable atom per canonical node and account for every M10 record."""

    root = _canonical_value(canonical)
    binding = _binding(root, canonical_binding)
    nodes = _records(root, "nodes")
    edges = _records(root, "edges")
    regions = _records(root, "regions")
    facts = _records(root, "facts")
    evidence = {_text(item, "id"): item for item in _records(root, "evidence")}

    projected_atoms = tuple(_atom_for_node(node, evidence) for node in nodes)
    atoms = _canonical_story_atoms(
        nodes,
        edges,
        regions,
        projected_atoms,
    )
    atom_by_node = {item.primary_node_id: item.id for item in atoms}
    coverage = _canonical_coverage(
        nodes,
        edges,
        regions,
        facts,
        atom_by_node,
    )
    return {
        "schema": STORY_ATOMS_SCHEMA,
        "phase": "story_atoms",
        "binding": binding.to_dict(),
        "atom_rule_version": M11_ATOM_RULE_VERSION,
        "atoms": [item.to_dict() for item in atoms],
        "coverage": coverage.to_dict(),
    }


def build_scene_boundaries(
    canonical: CanonicalGraph | Mapping[str, object],
    story_atoms: Mapping[str, object],
    *,
    canonical_binding: CanonicalBinding | None = None,
) -> dict[str, object]:
    """Emit deterministic accepted and rejected boundary decisions with strength."""

    root = _canonical_value(canonical)
    binding = _binding(root, canonical_binding)
    _require_phase_binding(story_atoms, STORY_ATOMS_SCHEMA, binding)
    atoms = tuple(_atom_from_value(item) for item in _records(story_atoms, "atoms"))
    node_by_id = {_text(item, "id"): item for item in _records(root, "nodes")}
    fact_by_id = {_text(item, "id"): item for item in _records(root, "facts")}
    regions = _records(root, "regions")
    persistent_entries, persistent_merges = _persistent_boundary_nodes(root)
    resolved_label_entries = _resolved_label_entry_support(root)
    unresolved_targets = _unresolved_boundary_support(root)
    atom_by_node = {item.primary_node_id: item for item in atoms}
    scope_by_atom = _atom_scope_keys(regions, atom_by_node)

    decisions: list[BoundaryDecision] = []
    chapter_starts: list[str] = []
    prior_atom_id: str | None = None
    pending_chapter_support: dict[tuple[str, str, int], Provenance] = {}
    pending_location_support: dict[tuple[str, str, int], Provenance] = {}
    pending_resolved_entry: dict[tuple[str, str, int], Provenance] = {}
    pending_terminal: dict[tuple[str, str, int], Provenance] = {}
    narrative_run: dict[tuple[str, str, int], int] = defaultdict(int)
    prior_atom_by_scope: dict[tuple[str, str, int], StoryAtom] = {}
    prior_label_by_scope: dict[tuple[str, str, int], str] = {}
    for index, atom in enumerate(atoms):
        node = node_by_id[atom.primary_node_id]
        attributes = _mapping(node.get("attributes"), "canonical node attributes")
        source_text = str(attributes.get("source_text", ""))
        source_kind = str(attributes.get("source_kind", ""))
        label = str(node.get("label", ""))
        scope = scope_by_atom.get(atom.id, ("lane_story_spine", "", -1))
        prior_scope_atom = prior_atom_by_scope.get(scope)
        prior_label = prior_label_by_scope.get(scope)
        fact_support = _fact_category_provenance(attributes, fact_by_id)
        accepted = False
        strength = BoundaryStrength.WEAK
        rule_id = "continuation_candidate"
        reason = "No hard or strong deterministic scene transition is present."
        structural_provenance: Provenance | None = None

        if index == 0:
            accepted = True
            strength = BoundaryStrength.HARD
            rule_id = "corpus_start"
            reason = "The first canonical atom starts the deterministic scene draft."
        elif atom.primary_node_id in persistent_entries:
            accepted = True
            strength = BoundaryStrength.HARD
            rule_id = "persistent_lane_entry"
            reason = "M10 classifies this atom as a persistent or terminal route-arm entry."
            structural_provenance = persistent_entries[atom.primary_node_id]
        elif atom.primary_node_id in persistent_merges:
            accepted = True
            strength = BoundaryStrength.HARD
            rule_id = "persistent_lane_merge"
            reason = "This exact M10 merge returns presentation ownership to the parent lane."
            structural_provenance = persistent_merges[atom.primary_node_id]
        elif scope in pending_chapter_support and _is_chapter_anchor(atom, source_kind):
            accepted = True
            strength = BoundaryStrength.HARD
            rule_id = "explicit_chapter_progression"
            reason = "Proven progression begins a chapter at the next narrative scene anchor."
            chapter_starts.append(atom.id)
            structural_provenance = pending_chapter_support.pop(scope)
        elif source_kind in {"module_start", "module_end"}:
            accepted = True
            strength = BoundaryStrength.HARD
            rule_id = "canonical_module_boundary"
            reason = "M10 module ownership prevents disconnected source files from sharing a scene."
        elif (
            atom.kind is AtomKind.UNRESOLVED
            or str(node.get("reachability")) == "unresolved_dynamic_behavior"
            or atom.primary_node_id in unresolved_targets
        ):
            accepted = True
            strength = BoundaryStrength.HARD
            rule_id = "unresolved_safety"
            reason = (
                "M10 marks this story transition unresolved, so presentation "
                "cannot merge across it."
            )
            structural_provenance = unresolved_targets.get(atom.primary_node_id)
        elif scope in pending_terminal:
            accepted = True
            strength = BoundaryStrength.HARD
            rule_id = "terminal_transition"
            reason = "The atom after an M10 terminal begins separate presentation ownership."
            structural_provenance = pending_terminal[scope]
        elif source_kind == "scene" and scope in pending_location_support:
            accepted = True
            strength = BoundaryStrength.STRONG
            rule_id = "reinforced_location_transition"
            reason = "A proven location effect reinforces this source-authored scene reset."
            structural_provenance = pending_location_support[scope]
        elif source_kind == "scene" and scope in pending_resolved_entry:
            accepted = True
            strength = BoundaryStrength.STRONG
            rule_id = "reinforced_resolved_transfer"
            reason = (
                "An exact resolved M10 story transfer reinforces this "
                "source-authored scene reset."
            )
            structural_provenance = pending_resolved_entry[scope]
        elif source_kind == "scene":
            strength = BoundaryStrength.STRONG
            if narrative_run[scope] >= _MINIMUM_NARRATIVE_RUN:
                accepted = True
                rule_id = "minimum_narrative_run"
                reason = (
                    "A source-authored scene reset follows the versioned minimum "
                    f"narrative run of {_MINIMUM_NARRATIVE_RUN} atoms."
                )
            else:
                rule_id = "scene_reset_candidate"
                reason = (
                    "A source-authored scene reset remains a strong candidate without "
                    "enough deterministic reinforcement to cut the human scene."
                )
        elif source_kind in {"show", "hide"}:
            strength = BoundaryStrength.WEAK
            rule_id = "routine_visual_change"
            reason = "Routine show and hide operations remain weak retained visual candidates."
        elif source_kind == "label":
            continuation = (
                None
                if prior_scope_atom is None
                else resolved_label_entries.get(atom.primary_node_id, {}).get(
                    prior_scope_atom.primary_node_id
                )
            )
            if continuation is None:
                accepted = True
                strength = BoundaryStrength.HARD
                rule_id = "canonical_procedure_entry"
                reason = (
                    "M10 has no normal resolved story predecessor for this procedure entry."
                )
            else:
                strength = BoundaryStrength.WEAK
                rule_id = "resolved_label_continuation"
                reason = (
                    "An exact resolved M10 story edge continues through this label without "
                    "forcing a human-scene cut."
                )
                structural_provenance = continuation
        elif (
            label != prior_label
            and source_kind in {"call_return_site", "procedure_return_boundary"}
        ):
            accepted = True
            strength = BoundaryStrength.HARD
            rule_id = "canonical_procedure_entry"
            reason = (
                "M10 procedure ownership prevents unrelated source definitions "
                "from sharing a scene."
            )

        provenance = (
            atom.provenance
            if structural_provenance is None
            else _merge_provenance((atom.provenance, structural_provenance))
        )
        anchors = tuple(
            dict.fromkeys((atom.primary_node_id, *provenance.region_ids))
        )
        decisions.append(
            BoundaryDecision(
                stable_m11_id("boundary", atom.id, rule_id),
                prior_atom_id,
                atom.id,
                strength,
                DecisionStatus.ACCEPTED if accepted else DecisionStatus.REJECTED,
                M11_BOUNDARY_RULE_VERSION,
                anchors,
                provenance,
                reason,
                rule_id,
            )
        )

        if accepted:
            narrative_run[scope] = 0
        if atom.kind in {AtomKind.DIALOGUE, AtomKind.NARRATION}:
            narrative_run[scope] += 1

        if source_kind == "label":
            if rule_id == "resolved_label_continuation" and structural_provenance is not None:
                pending_resolved_entry[scope] = structural_provenance
            else:
                pending_resolved_entry.pop(scope, None)
        elif source_kind == "scene" or (
            atom.story_facing and source_kind not in {"show", "hide", "with"}
        ):
            pending_resolved_entry.pop(scope, None)
            pending_location_support.pop(scope, None)

        if source_kind == "label" and _DAY_OR_CHAPTER.search(label):
            pending_chapter_support[scope] = atom.provenance
        progression = fact_support.get(StateCategory.PROGRESSION)
        if progression is not None or _PROGRESSION_EFFECT.search(source_text):
            pending_chapter_support[scope] = progression or atom.provenance
        location = fact_support.get(StateCategory.LOCATION)
        if location is not None:
            pending_location_support[scope] = location

        if atom.kind is AtomKind.TERMINAL or source_kind in {
            "return",
            "procedure_return_boundary",
        }:
            pending_terminal[scope] = atom.provenance
        else:
            pending_terminal.pop(scope, None)
        prior_atom_id = atom.id
        prior_atom_by_scope[scope] = atom
        prior_label_by_scope[scope] = label

    return {
        "schema": SCENE_BOUNDARIES_SCHEMA,
        "phase": "scene_boundaries",
        "binding": binding.to_dict(),
        "boundary_rule_version": M11_BOUNDARY_RULE_VERSION,
        "boundaries": [item.to_dict() for item in decisions],
        "chapter_start_atom_ids": chapter_starts,
    }


def build_scene_model(
    canonical: CanonicalGraph | Mapping[str, object],
    correction_overlay: CorrectionOverlay | None = None,
) -> SceneModel:
    root = _canonical_value(canonical)
    binding = _binding(root)
    atoms = build_story_atoms(root, canonical_binding=binding)
    boundaries = build_scene_boundaries(root, atoms, canonical_binding=binding)
    assembly = build_scene_assembly(
        root,
        atoms,
        boundaries,
        correction_overlay=correction_overlay,
        canonical_binding=binding,
    )
    return scene_model_from_phase_results(
        root,
        atoms,
        boundaries,
        assembly,
        canonical_binding=binding,
    )


def correction_overlay_from_mapping(value: Mapping[str, object]) -> CorrectionOverlay:
    """Parse a durable, exact-binding minimal correction overlay."""

    return _correction_overlay_from_value(value)


def build_scene_assembly(
    canonical: CanonicalGraph | Mapping[str, object],
    story_atoms: Mapping[str, object],
    scene_boundaries: Mapping[str, object],
    correction_overlay: CorrectionOverlay | None = None,
    *,
    canonical_binding: CanonicalBinding | None = None,
) -> dict[str, object]:
    """Assemble scenes and hierarchy without changing M10 topology authority."""

    root = _canonical_value(canonical)
    binding = _binding(root, canonical_binding)
    _require_phase_binding(story_atoms, STORY_ATOMS_SCHEMA, binding)
    _require_phase_binding(scene_boundaries, SCENE_BOUNDARIES_SCHEMA, binding)
    atoms = tuple(_atom_from_value(item) for item in _records(story_atoms, "atoms"))
    boundaries = tuple(
        _boundary_from_value(item) for item in _records(scene_boundaries, "boundaries")
    )
    coverage = _coverage_from_value(
        _mapping(story_atoms.get("coverage"), "story atom coverage")
    )
    if correction_overlay is not None:
        if correction_overlay.binding != binding:
            raise ValueError("M11 correction overlay is bound to another canonical graph")
        boundaries = _apply_corrections(boundaries, correction_overlay)

    model = _assemble_model(
        root,
        binding,
        atoms,
        boundaries,
        coverage,
        tuple(_strings(scene_boundaries.get("chapter_start_atom_ids"))),
        correction_overlay,
    )
    model.validate()
    normalized = model.normalized_dict()
    model_hash = hashlib.sha256(canonical_json(normalized)).hexdigest()
    return {
        "schema": SCENE_ASSEMBLY_SCHEMA,
        "phase": "scene_assembly",
        "binding": binding.to_dict(),
        "scene_model_schema": M11_SCENE_MODEL_SCHEMA,
        "scene_model_hash": model_hash,
        "scenes": normalized["scenes"],
        "temporary_branches": normalized["temporary_branches"],
        "occurrences": normalized["occurrences"],
        "lanes": normalized["lanes"],
        "chapters": normalized["chapters"],
        "loop_hubs": normalized["loop_hubs"],
        "correction_overlay": normalized["correction_overlay"],
    }


def _assemble_model(
    canonical: Mapping[str, object],
    binding: CanonicalBinding,
    atoms: tuple[StoryAtom, ...],
    boundaries: tuple[BoundaryDecision, ...],
    coverage: CanonicalCoverage,
    chapter_start_atom_ids: tuple[str, ...],
    correction_overlay: CorrectionOverlay | None,
) -> SceneModel:
    nodes = _records(canonical, "nodes")
    edges = _records(canonical, "edges")
    regions = _records(canonical, "regions")
    node_by_id = {_text(item, "id"): item for item in nodes}
    atom_by_node = {item.primary_node_id: item for item in atoms}
    atom_by_id = {item.id: item for item in atoms}
    atom_rank = {item.id: index for index, item in enumerate(atoms)}
    boundary_by_atom = {item.after_atom_id: item for item in boundaries}
    called_labels = {
        str(node_by_id[_text(edge, "target_id")].get("label", ""))
        for edge in edges
        if str(edge.get("kind")) == "call_enter"
        and _text(edge, "target_id") in node_by_id
    }

    lane_specs, atom_lane = _lane_specs(regions, atom_by_node)
    atom_arm_context = _temporary_arm_contexts(regions, atom_by_node, boundaries)
    scene_chunks: list[
        tuple[str, tuple[str, int] | None, BoundaryDecision, list[StoryAtom]]
    ] = []
    for atom in atoms:
        boundary = boundary_by_atom[atom.id]
        lane_id = atom_lane.get(atom.id, "lane_story_spine")
        arm_context = atom_arm_context.get(atom.id)
        starts_scene = (
            not scene_chunks
            or (lane_id, arm_context) != scene_chunks[-1][:2]
            or (
                boundary.status is DecisionStatus.ACCEPTED
                and boundary.strength in {BoundaryStrength.HARD, BoundaryStrength.STRONG}
            )
        )
        if starts_scene:
            scene_chunks.append((lane_id, arm_context, boundary, [atom]))
        else:
            scene_chunks[-1][3].append(atom)

    scenes: list[Scene] = []
    scene_context_by_id: dict[str, tuple[str, int] | None] = {}
    for ordinal, (lane_id, arm_context, boundary, members) in enumerate(scene_chunks):
        member_labels = {
            str(node_by_id[item.primary_node_id].get("label", "")) for item in members
        }
        definition_only = bool(member_labels) and member_labels <= called_labels
        scene_id = stable_m11_id(
            "scene",
            lane_id,
            *(arm_context or ()),
            boundary.id,
            *(item.id for item in members),
        )
        provenance = _merge_provenance(item.provenance for item in members)
        scenes.append(
            Scene(
                scene_id,
                "chapter_story",
                lane_id,
                _scene_title(members, node_by_id, ordinal),
                ordinal,
                tuple(item.id for item in members),
                (),
                (),
                SceneRepeatability.ONCE,
                None,
                boundary.id,
                definition_only,
                provenance,
            )
        )
        scene_context_by_id[scene_id] = arm_context
    scene_by_atom = {
        atom_id: scene.id for scene in scenes for atom_id in scene.atom_ids
    }

    occurrences = _call_occurrences(
        edges,
        node_by_id,
        atom_by_node,
        atom_by_id,
        atom_rank,
        scene_by_atom,
        {item.id: item for item in scenes},
    )
    branches = _temporary_branches(
        regions,
        edges,
        atom_by_node,
        atom_rank,
        scene_by_atom,
        scene_context_by_id,
        occurrences,
    )
    loop_hubs = _loop_hubs(
        regions,
        edges,
        atom_by_node,
        scene_by_atom,
        occurrences,
        {item.id: item for item in scenes},
    )
    scene_loop = {
        scene_id: hub.id for hub in loop_hubs for scene_id in hub.scene_ids
    }
    branch_by_scene: dict[str, list[str]] = defaultdict(list)
    for branch in branches:
        branch_by_scene[branch.parent_scene_id].append(branch.id)
    occurrence_by_scene: dict[str, list[str]] = defaultdict(list)
    for occurrence in occurrences:
        occurrence_by_scene[occurrence.scene_id].append(occurrence.id)
    scenes = [
        replace(
            scene,
            temporary_branch_ids=tuple(sorted(branch_by_scene.get(scene.id, ()))),
            occurrence_ids=tuple(sorted(occurrence_by_scene.get(scene.id, ()))),
            repeatability=(
                SceneRepeatability.REPEATABLE
                if scene.id in scene_loop
                else SceneRepeatability.ONCE
            ),
            loop_hub_id=scene_loop.get(scene.id),
        )
        for scene in scenes
    ]

    scenes, chapters = _chapters(
        scenes,
        chapter_start_atom_ids,
        atom_by_id,
        node_by_id,
    )
    lanes = _lanes(lane_specs, scenes)
    model = SceneModel(
        binding,
        atoms,
        boundaries,
        tuple(scenes),
        tuple(branches),
        tuple(occurrences),
        tuple(lanes),
        tuple(chapters),
        tuple(loop_hubs),
        coverage,
        correction_overlay,
    )
    return model


def _lane_specs(
    regions: Sequence[Mapping[str, object]],
    atom_by_node: Mapping[str, StoryAtom],
) -> tuple[dict[str, _LaneSpec], dict[str, str]]:
    specs: dict[str, _LaneSpec] = {
        "lane_story_spine": _LaneSpec(
            LaneKind.SPINE,
            None,
            None,
            None,
            None,
            None,
            Provenance(),
        )
    }
    candidates: dict[str, list[tuple[int, str]]] = defaultdict(list)
    persistent = [
        item for item in regions if str(item.get("kind", "")) in _PERSISTENT_REGION_KINDS
    ]
    region_by_id = {_text(item, "id"): item for item in persistent}
    canonical_by_origin = {
        str(origin.get("record_id")): _text(region, "id")
        for region in persistent
        for origin in _records_or_empty(region.get("origins"))
        if origin.get("collection") == "m06_control_flow"
    }
    parent_region: dict[str, str | None] = {}
    for region in persistent:
        region_id = _text(region, "id")
        parent_value = _mapping(region.get("attributes"), "region attributes").get(
            "parent_region_id"
        )
        parent_region[region_id] = (
            canonical_by_origin.get(parent_value, parent_value)
            if isinstance(parent_value, str)
            and canonical_by_origin.get(parent_value, parent_value) in region_by_id
            else None
        )

    for region in sorted(persistent, key=lambda item: _text(item, "id")):
        kind = str(region.get("kind", ""))
        region_id = _text(region, "id")
        provenance = _region_provenance(region)
        lane_kind = (
            LaneKind.PERSISTENT_ROUTE
            if kind == "persistent_route"
            else LaneKind.TERMINAL_SPLIT
        )
        split_node_id = _text(region, "split_node_id")
        split_atom = atom_by_node.get(split_node_id)
        merge_value = region.get("merge_node_id")
        parent_lane_id = "lane_story_spine"
        parent_id = parent_region[region_id]
        if parent_id is not None:
            parent = region_by_id[parent_id]
            containing_arms = [
                arm
                for arm in _records(
                    _mapping(parent.get("attributes"), "region attributes"), "arms"
                )
                if split_node_id
                in {
                    _text(arm, "entry_node_id"),
                    *_strings(arm.get("member_node_ids")),
                }
            ]
            if len(containing_arms) == 1:
                parent_lane_id = stable_m11_id(
                    "lane", parent_id, _integer(containing_arms[0], "ordinal")
                )
        for arm in sorted(
            _records(_mapping(region.get("attributes"), "region attributes"), "arms"),
            key=lambda item: _integer(item, "ordinal"),
        ):
            ordinal = _integer(arm, "ordinal")
            lane_id = stable_m11_id("lane", region_id, ordinal)
            specs[lane_id] = _LaneSpec(
                lane_kind,
                region_id,
                ordinal,
                parent_lane_id,
                None if split_atom is None else split_atom.id,
                merge_value if isinstance(merge_value, str) else None,
                provenance,
            )
            members = set(_strings(arm.get("member_node_ids")))
            members.add(_text(arm, "entry_node_id"))
            for node_id in members:
                atom = atom_by_node.get(node_id)
                if atom is not None:
                    candidates[atom.id].append((len(members), lane_id))
    return specs, {
        atom_id: sorted(values, key=lambda item: (item[0], item[1]))[0][1]
        for atom_id, values in candidates.items()
    }


def _atom_scope_keys(
    regions: Sequence[Mapping[str, object]],
    atom_by_node: Mapping[str, StoryAtom],
) -> dict[str, tuple[str, str, int]]:
    """Return deterministic lane/temporary-arm scopes for local run counters."""

    _specs, atom_lane = _lane_specs(regions, atom_by_node)
    temporary, _parents = _temporary_region_index(regions)
    arm_candidates: dict[str, list[tuple[int, str, int]]] = defaultdict(list)
    for region in temporary:
        region_id = _text(region, "id")
        split_node_id = _text(region, "split_node_id")
        merge_node_id = _text(region, "merge_node_id")
        for arm in _records(
            _mapping(region.get("attributes"), "region attributes"), "arms"
        ):
            ordinal = _integer(arm, "ordinal")
            node_ids = {
                _text(arm, "entry_node_id"),
                *_strings(arm.get("member_node_ids")),
            } - {split_node_id, merge_node_id}
            atom_ids = {
                atom_by_node[node_id].id
                for node_id in node_ids
                if node_id in atom_by_node
            }
            for atom_id in atom_ids:
                arm_candidates[atom_id].append((len(atom_ids), region_id, ordinal))

    result: dict[str, tuple[str, str, int]] = {}
    for atom in atom_by_node.values():
        selected_arm = min(arm_candidates.get(atom.id, ((0, "", -1),)))
        result[atom.id] = (
            atom_lane.get(atom.id, "lane_story_spine"),
            selected_arm[1],
            selected_arm[2],
        )
    return result


def _lanes(
    specs: Mapping[str, _LaneSpec],
    scenes: Sequence[Scene],
) -> list[PersistentLane]:
    scenes_by_lane: dict[str, list[str]] = defaultdict(list)
    for scene in scenes:
        scenes_by_lane[scene.lane_id].append(scene.id)
    result: list[PersistentLane] = []
    for lane_id, spec in sorted(specs.items()):
        result.append(
            PersistentLane(
                lane_id,
                spec.kind,
                spec.parent_lane_id,
                spec.region_id,
                spec.arm_ordinal,
                tuple(scenes_by_lane.get(lane_id, ())),
                spec.split_atom_id,
                spec.merge_node_id,
                spec.provenance,
            )
        )
    return result


def _call_occurrences(
    edges: Sequence[Mapping[str, object]],
    node_by_id: Mapping[str, Mapping[str, object]],
    atom_by_node: Mapping[str, StoryAtom],
    atom_by_id: Mapping[str, StoryAtom],
    atom_rank: Mapping[str, int],
    scene_by_atom: Mapping[str, str],
    scene_by_id: Mapping[str, Scene],
) -> list[CallSiteOccurrence]:
    atoms_by_label: dict[str, list[StoryAtom]] = defaultdict(list)
    for atom in atom_by_id.values():
        label = str(node_by_id[atom.primary_node_id].get("label", ""))
        if atom.kind in {
            AtomKind.DIALOGUE,
            AtomKind.NARRATION,
            AtomKind.VISUAL_CHANGE,
            AtomKind.CHOICE,
        }:
            atoms_by_label[label].append(atom)
    for values in atoms_by_label.values():
        values.sort(key=lambda item: (atom_rank[item.id], item.id))

    result: list[CallSiteOccurrence] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in sorted(edges, key=lambda item: _text(item, "id")):
        if str(edge.get("kind")) != "call_enter":
            continue
        source_node_id = _text(edge, "source_id")
        target_node_id = _text(edge, "target_id")
        call_atom = atom_by_node.get(source_node_id)
        target = node_by_id.get(target_node_id)
        if call_atom is None or target is None or call_atom.id not in scene_by_atom:
            continue
        attributes = _mapping(edge.get("attributes"), "canonical edge attributes")
        call_site_id = str(attributes.get("call_site_id") or edge.get("id"))
        identity = (call_site_id, source_node_id, target_node_id)
        if identity in seen:
            continue
        seen.add(identity)
        referenced = tuple(
            item.id for item in atoms_by_label.get(str(target.get("label", "")), ())
        )
        kind = OccurrenceKind.NARRATIVE if referenced else OccurrenceKind.TECHNICAL
        scene_id = scene_by_atom[call_atom.id]
        scene = scene_by_id[scene_id]
        fact_ids = tuple(
            sorted(
                {
                    *_strings(attributes.get("gate_ids")),
                    *(
                        item
                        for dependency in _records_or_empty(
                            attributes.get("guard_dependencies")
                        )
                        for item in _strings(dependency.get("requirement_fact_ids"))
                    ),
                }
            )
        )
        provenance = Provenance(
            node_ids=(source_node_id, target_node_id),
            edge_ids=(_text(edge, "id"),),
            fact_ids=fact_ids,
            evidence_ids=tuple(sorted(_strings(edge.get("evidence_ids")))),
            proof_ids=tuple(sorted(_strings(edge.get("proof_ids")))),
        )
        result.append(
            CallSiteOccurrence(
                stable_m11_id("occurrence", *identity),
                call_atom.id,
                target_node_id,
                kind,
                scene_id,
                scene.lane_id,
                referenced,
                fact_ids,
                kind is OccurrenceKind.TECHNICAL,
                bool(
                    _strings(
                        _mapping(
                            node_by_id[source_node_id].get("attributes"),
                            "canonical node attributes",
                        ).get("loop_ids")
                    )
                ),
                provenance,
            )
        )
    return result


def _temporary_region_index(
    regions: Sequence[Mapping[str, object]],
) -> tuple[list[Mapping[str, object]], dict[str, str | None]]:
    temporary = [
        item
        for item in regions
        if str(item.get("kind")) in _TEMPORARY_REGION_KINDS
        and isinstance(item.get("merge_node_id"), str)
    ]
    canonical_by_origin: dict[str, str] = {}
    for region in temporary:
        for origin in _records_or_empty(region.get("origins")):
            if origin.get("collection") == "m06_control_flow":
                canonical_by_origin[str(origin.get("record_id"))] = _text(region, "id")
    parent_by_region: dict[str, str | None] = {}
    temporary_ids = {_text(item, "id") for item in temporary}
    for region in temporary:
        parent_origin = _mapping(region.get("attributes"), "region attributes").get(
            "parent_region_id"
        )
        parent_id = (
            canonical_by_origin.get(parent_origin, parent_origin)
            if isinstance(parent_origin, str)
            else None
        )
        parent_by_region[_text(region, "id")] = (
            parent_id if parent_id in temporary_ids else None
        )
    return temporary, parent_by_region


def _temporary_arm_contexts(
    regions: Sequence[Mapping[str, object]],
    atom_by_node: Mapping[str, StoryAtom],
    boundaries: Sequence[BoundaryDecision],
) -> dict[str, tuple[str, int]]:
    temporary, parent_by_region = _temporary_region_index(regions)
    structural_atoms = {
        boundary.after_atom_id
        for boundary in boundaries
        if boundary.status is DecisionStatus.ACCEPTED
        and boundary.strength in {BoundaryStrength.HARD, BoundaryStrength.STRONG}
    }
    depth_cache: dict[str, int] = {}

    def region_depth(region_id: str, active: frozenset[str] = frozenset()) -> int:
        if region_id in depth_cache:
            return depth_cache[region_id]
        if region_id in active:
            raise ValueError("M10 temporary-region hierarchy contains a cycle")
        parent_id = parent_by_region.get(region_id)
        depth = (
            0
            if parent_id is None
            else 1 + region_depth(parent_id, active | {region_id})
        )
        depth_cache[region_id] = depth
        return depth

    candidates: dict[str, list[_ArmContextCandidate]] = defaultdict(list)
    for region in temporary:
        region_id = _text(region, "id")
        split_node_id = _text(region, "split_node_id")
        merge_node_id = _text(region, "merge_node_id")
        arm_atoms: list[tuple[int, set[str]]] = []
        for arm in _records(
            _mapping(region.get("attributes"), "region attributes"), "arms"
        ):
            node_ids = {
                _text(arm, "entry_node_id"),
                *_strings(arm.get("member_node_ids")),
            } - {split_node_id, merge_node_id}
            atom_ids = {
                atom_by_node[node_id].id
                for node_id in node_ids
                if node_id in atom_by_node
            }
            arm_atoms.append((_integer(arm, "ordinal"), atom_ids))
        if not any(atom_ids & structural_atoms for _ordinal, atom_ids in arm_atoms):
            continue
        depth = region_depth(region_id)
        for ordinal, atom_ids in arm_atoms:
            candidate = _ArmContextCandidate(region_id, ordinal, depth, len(atom_ids))
            for atom_id in atom_ids:
                candidates[atom_id].append(candidate)
    return {
        atom_id: (selected.region_id, selected.arm_ordinal)
        for atom_id, values in candidates.items()
        for selected in (
            sorted(
                values,
                key=lambda item: (
                    -item.depth,
                    item.member_count,
                    item.region_id,
                    item.arm_ordinal,
                ),
            )[0],
        )
    }


def _temporary_branches(
    regions: Sequence[Mapping[str, object]],
    edges: Sequence[Mapping[str, object]],
    atom_by_node: Mapping[str, StoryAtom],
    atom_rank: Mapping[str, int],
    scene_by_atom: Mapping[str, str],
    scene_context_by_id: Mapping[str, tuple[str, int] | None],
    occurrences: Sequence[CallSiteOccurrence],
) -> list[TemporaryBranchContainer]:
    temporary, parent_by_region = _temporary_region_index(regions)
    temporary_by_id = {_text(item, "id"): item for item in temporary}
    occurrence_by_atom: dict[str, list[str]] = defaultdict(list)
    for occurrence in occurrences:
        occurrence_by_atom[occurrence.call_atom_id].append(occurrence.id)

    result: list[TemporaryBranchContainer] = []
    for region in sorted(temporary, key=lambda item: _text(item, "id")):
        region_id = _text(region, "id")
        split_atom = atom_by_node.get(_text(region, "split_node_id"))
        merge_node_id = _text(region, "merge_node_id")
        if split_atom is None or split_atom.id not in scene_by_atom:
            continue
        branch_id = stable_m11_id("branch", region_id)
        nested_ids = {
            child_id: stable_m11_id("branch", child_id)
            for child_id, parent_id in parent_by_region.items()
            if parent_id == region_id
        }
        continuation = _merge_continuation(merge_node_id, edges, atom_by_node)
        arms: list[TemporaryBranchArm] = []
        for arm in sorted(
            _records(_mapping(region.get("attributes"), "region attributes"), "arms"),
            key=lambda item: _integer(item, "ordinal"),
        ):
            node_ids = tuple(
                sorted(
                    {
                        *_strings(arm.get("member_node_ids")),
                        _text(arm, "entry_node_id"),
                    }
                    - {
                        _text(region, "split_node_id"),
                        merge_node_id,
                    }
                )
            )
            arm_atoms = sorted(
                (atom_by_node[item] for item in node_ids if item in atom_by_node),
                key=lambda item: (atom_rank[item.id], item.id),
            )
            atom_ids = tuple(
                item.id for item in arm_atoms if item.id != continuation
            )
            local_scene_ids = tuple(
                scene_id
                for scene_id, context in scene_context_by_id.items()
                if context == (region_id, _integer(arm, "ordinal"))
            )
            arm_occurrences = tuple(
                sorted(
                    occurrence_id
                    for atom_id in atom_ids
                    for occurrence_id in occurrence_by_atom.get(atom_id, ())
                )
            )
            arm_nested = tuple(
                sorted(
                    nested_id
                    for child_region_id, nested_id in nested_ids.items()
                    if _text(
                        temporary_by_id[child_region_id],
                        "split_node_id",
                    )
                    in node_ids
                )
            )
            arms.append(
                TemporaryBranchArm(
                    stable_m11_id("branch_arm", region_id, _integer(arm, "ordinal")),
                    _integer(arm, "ordinal"),
                    atom_ids,
                    local_scene_ids,
                    arm_nested,
                    arm_occurrences,
                )
            )
        parent_region_id = parent_by_region[region_id]
        result.append(
            TemporaryBranchContainer(
                branch_id,
                region_id,
                split_atom.id,
                tuple(arms),
                merge_node_id,
                continuation,
                scene_by_atom[split_atom.id],
                (
                    stable_m11_id("branch", parent_region_id)
                    if parent_region_id is not None
                    else None
                ),
                _region_provenance(region),
            )
        )
    return result


def _loop_hubs(
    regions: Sequence[Mapping[str, object]],
    edges: Sequence[Mapping[str, object]],
    atom_by_node: Mapping[str, StoryAtom],
    scene_by_atom: Mapping[str, str],
    occurrences: Sequence[CallSiteOccurrence],
    scenes: Mapping[str, Scene],
) -> list[LoopHub]:
    occurrence_by_atom: dict[str, list[str]] = defaultdict(list)
    for occurrence in occurrences:
        occurrence_by_atom[occurrence.call_atom_id].append(occurrence.id)
    result: list[LoopHub] = []
    for region in sorted(regions, key=lambda item: _text(item, "id")):
        if str(region.get("kind")) != "loop_choice":
            continue
        split_node_id = _text(region, "split_node_id")
        hub_atom = atom_by_node.get(split_node_id)
        if hub_atom is None:
            continue
        member_nodes = {
            split_node_id,
            *_strings(region.get("member_node_ids")),
        }
        member_atoms = {
            atom_by_node[item].id for item in member_nodes if item in atom_by_node
        }
        scene_ids = tuple(
            sorted(
                {scene_by_atom[item] for item in member_atoms if item in scene_by_atom},
                key=lambda item: (scenes[item].ordinal, item),
            )
        )
        hub_id = stable_m11_id("loop_hub", _text(region, "id"))
        returns: list[ReturnToHub] = []
        partial: list[PartialOrderRelation] = []
        for edge in sorted(edges, key=lambda item: _text(item, "id")):
            source_node = _text(edge, "source_id")
            target_node = _text(edge, "target_id")
            if source_node not in member_nodes or target_node not in member_nodes:
                continue
            source_atom = atom_by_node.get(source_node)
            target_atom = atom_by_node.get(target_node)
            if source_atom is None or target_atom is None:
                continue
            source_scene = scene_by_atom.get(source_atom.id)
            target_scene = scene_by_atom.get(target_atom.id)
            if source_scene is None or target_scene is None:
                continue
            provenance = _edge_provenance(edge)
            if target_node == split_node_id:
                returns.append(
                    ReturnToHub(
                        stable_m11_id("return_to_hub", _text(edge, "id")),
                        source_scene,
                        hub_atom.id,
                        provenance,
                    )
                )
            elif source_scene != target_scene:
                partial.append(
                    PartialOrderRelation(
                        stable_m11_id("partial_order", _text(edge, "id")),
                        source_scene,
                        target_scene,
                        provenance,
                    )
                )
        result.append(
            LoopHub(
                hub_id,
                _text(region, "id"),
                hub_atom.id,
                scene_ids,
                tuple(
                    sorted(
                        occurrence_id
                        for atom_id in member_atoms
                        for occurrence_id in occurrence_by_atom.get(atom_id, ())
                    )
                ),
                tuple(returns),
                tuple(partial),
                _region_provenance(region),
            )
        )
    return result


def _chapters(
    scenes: Sequence[Scene],
    chapter_start_atom_ids: Sequence[str],
    atom_by_id: Mapping[str, StoryAtom],
    node_by_id: Mapping[str, Mapping[str, object]],
) -> tuple[list[Scene], list[Chapter]]:
    starts = set(chapter_start_atom_ids)
    assignments: list[tuple[str, str, int, str | None]] = []
    current_id = "chapter_story"
    current_label = "Story"
    current_boundary: str | None = None
    chapter_ordinal = 0
    metadata: dict[str, tuple[int, str, str | None]] = {
        "chapter_story": (0, "Story", None)
    }
    for scene in sorted(scenes, key=lambda item: (item.ordinal, item.id)):
        first_atom = scene.atom_ids[0]
        if first_atom in starts:
            chapter_ordinal += 1
            atom = atom_by_id[first_atom]
            source_label = str(node_by_id[atom.primary_node_id].get("label", ""))
            current_id = stable_m11_id("chapter", first_atom)
            current_label = _humanize_identifier(source_label) or f"Chapter {chapter_ordinal + 1}"
            current_boundary = scene.boundary_id
            metadata[current_id] = (
                chapter_ordinal,
                current_label,
                current_boundary,
            )
        assignments.append((scene.id, current_id, chapter_ordinal, current_boundary))
    scene_chapter = {scene_id: chapter_id for scene_id, chapter_id, _order, _b in assignments}
    updated = [replace(scene, chapter_id=scene_chapter[scene.id]) for scene in scenes]
    updated_by_id = {scene.id: scene for scene in updated}
    grouped: dict[str, list[Scene]] = defaultdict(list)
    for scene_id, chapter_id, _order, _boundary_id in assignments:
        grouped[chapter_id].append(updated_by_id[scene_id])
    chapters: list[Chapter] = []
    for chapter_id, chapter_scenes in sorted(
        grouped.items(), key=lambda item: (metadata[item[0]][0], item[0])
    ):
        order, label, boundary_id = metadata[chapter_id]
        chapters.append(
            Chapter(
                chapter_id,
                label,
                order,
                tuple(dict.fromkeys(scene.lane_id for scene in chapter_scenes)),
                tuple(scene.id for scene in chapter_scenes),
                boundary_id,
                _merge_provenance(scene.provenance for scene in chapter_scenes),
            )
        )
    if not chapters:
        chapters.append(Chapter("chapter_story", "Story", 0, (), (), None, Provenance()))
    return updated, chapters


def build_scene_presentation(
    canonical: CanonicalGraph | Mapping[str, object],
    scene_assembly: Mapping[str, object],
    *,
    canonical_binding: CanonicalBinding | None = None,
) -> dict[str, object]:
    """Build a bounded-client read model from assembled M11 records only."""

    root = _canonical_value(canonical)
    binding = _binding(root, canonical_binding)
    _require_phase_binding(scene_assembly, SCENE_ASSEMBLY_SCHEMA, binding)
    scenes = _records(scene_assembly, "scenes")
    branches = _records(scene_assembly, "temporary_branches")
    occurrences = _records(scene_assembly, "occurrences")
    lanes = _records(scene_assembly, "lanes")
    chapters = _records(scene_assembly, "chapters")
    hubs = _records(scene_assembly, "loop_hubs")

    nodes: list[dict[str, object]] = []
    page_order: list[str] = []
    scene_by_id = {_text(item, "id"): item for item in scenes}
    branch_by_scene: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for branch in branches:
        branch_by_scene[_text(branch, "parent_scene_id")].append(branch)
    occurrence_by_scene: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for occurrence in occurrences:
        if occurrence.get("kind") == OccurrenceKind.NARRATIVE.value:
            occurrence_by_scene[_text(occurrence, "scene_id")].append(occurrence)

    for chapter in sorted(
        chapters,
        key=lambda item: (_integer(item, "ordinal"), _text(item, "id")),
    ):
        for scene_id in _strings(chapter.get("scene_ids")):
            scene = scene_by_id.get(scene_id)
            if scene is None or bool(scene.get("definition_only", False)):
                continue
            nodes.append(
                {
                    "id": scene_id,
                    "kind": "scene",
                    "scene_id": scene_id,
                    "title": str(scene.get("title", "Scene")),
                }
            )
            page_order.append(scene_id)
            for branch in sorted(
                branch_by_scene.get(scene_id, ()), key=lambda item: _text(item, "id")
            ):
                branch_id = _text(branch, "id")
                nodes.append(
                    {
                        "id": branch_id,
                        "kind": "temporary_branch",
                        "temporary_branch_id": branch_id,
                        "title": "Temporary choice",
                    }
                )
                page_order.append(branch_id)
            for occurrence in sorted(
                occurrence_by_scene.get(scene_id, ()), key=lambda item: _text(item, "id")
            ):
                occurrence_id = _text(occurrence, "id")
                nodes.append(
                    {
                        "id": occurrence_id,
                        "kind": "call_occurrence",
                        "occurrence_id": occurrence_id,
                        "scene_id": scene_id,
                        "title": "Called narrative",
                    }
                )
                page_order.append(occurrence_id)

    visible_ids = set(page_order)
    scene_by_atom_id = {
        atom_id: _text(scene, "id")
        for scene in scenes
        for atom_id in _strings(scene.get("atom_ids"))
    }
    relationships: list[dict[str, object]] = []
    flow_edge_ids: dict[tuple[str, str], list[str]] = defaultdict(list)
    for edge in _records(root, "edges"):
        if (
            not bool(edge.get("resolved", True))
            or str(edge.get("kind", "")) in _ORDERING_IGNORED_EDGE_KINDS
        ):
            continue
        source_scene = scene_by_atom_id.get(
            stable_m11_id("atom", _text(edge, "source_id"))
        )
        target_scene = scene_by_atom_id.get(
            stable_m11_id("atom", _text(edge, "target_id"))
        )
        if (
            source_scene is None
            or target_scene is None
            or source_scene == target_scene
            or source_scene not in visible_ids
            or target_scene not in visible_ids
        ):
            continue
        flow_edge_ids[(source_scene, target_scene)].append(_text(edge, "id"))
    for (source_scene, target_scene), edge_ids in sorted(flow_edge_ids.items()):
        relationships.append(
            _presentation_relationship(
                "scene_flow",
                source_scene,
                target_scene,
                canonical_edge_ids=tuple(sorted(set(edge_ids))),
            )
        )
    for branch in branches:
        branch_id = _text(branch, "id")
        parent_scene_id = _text(branch, "parent_scene_id")
        if branch_id in visible_ids and parent_scene_id in visible_ids:
            relationships.append(
                _presentation_relationship("contains_choice", parent_scene_id, branch_id)
            )
        for arm in _records(branch, "arms"):
            for scene_id in _strings(arm.get("scene_ids")):
                if branch_id in visible_ids and scene_id in visible_ids:
                    relationships.append(
                        _presentation_relationship("choice_arm_scene", branch_id, scene_id)
                    )
    for occurrence in occurrences:
        occurrence_id = _text(occurrence, "id")
        scene_id = _text(occurrence, "scene_id")
        if occurrence_id in visible_ids and scene_id in visible_ids:
            relationships.append(
                _presentation_relationship("call_occurrence", scene_id, occurrence_id)
            )
    for hub in hubs:
        for relation in _records(hub, "partial_order"):
            before = _text(relation, "before_scene_id")
            after = _text(relation, "after_scene_id")
            if before in visible_ids and after in visible_ids:
                relationships.append(_presentation_relationship("partial_order", before, after))
        for relation in _records(hub, "return_relationships"):
            scene_id = _text(relation, "scene_id")
            hub_atom_id = _text(relation, "hub_atom_id")
            target_scene = scene_by_atom_id.get(hub_atom_id)
            if scene_id in visible_ids and target_scene in visible_ids:
                relationships.append(
                    _presentation_relationship("return_to_hub", scene_id, target_scene)
                )

    layout_columns = [
        {"lane_id": _text(lane, "id"), "column": index}
        for index, lane in enumerate(
            sorted(
                lanes,
                key=lambda item: (
                    0 if item.get("kind") == LaneKind.SPINE.value else 1,
                    _text(item, "id"),
                ),
            )
        )
    ]
    return {
        "schema": SCENE_PRESENTATION_SCHEMA,
        "phase": "scene_presentation",
        "binding": binding.to_dict(),
        "scene_model_hash": _text(scene_assembly, "scene_model_hash"),
        "nodes": nodes,
        "relationships": sorted(relationships, key=lambda item: str(item["id"])),
        "chapter_bands": [dict(item) for item in chapters],
        "lanes": [dict(item) for item in lanes],
        "page_order": page_order,
        "layout_columns": layout_columns,
    }


def scene_model_from_phase_results(
    canonical: CanonicalGraph | Mapping[str, object],
    story_atoms: Mapping[str, object],
    scene_boundaries: Mapping[str, object],
    scene_assembly: Mapping[str, object],
    *,
    canonical_binding: CanonicalBinding | None = None,
) -> SceneModel:
    """Rehydrate and validate one model from the three structural phase results."""

    root = _canonical_value(canonical)
    binding = _binding(root, canonical_binding)
    _require_phase_binding(story_atoms, STORY_ATOMS_SCHEMA, binding)
    _require_phase_binding(scene_boundaries, SCENE_BOUNDARIES_SCHEMA, binding)
    _require_phase_binding(scene_assembly, SCENE_ASSEMBLY_SCHEMA, binding)
    correction = scene_assembly.get("correction_overlay")
    correction_overlay = (
        None
        if correction is None
        else _correction_overlay_from_value(_mapping(correction, "correction overlay"))
    )
    effective_boundaries = tuple(
        _boundary_from_value(item) for item in _records(scene_boundaries, "boundaries")
    )
    if correction_overlay is not None:
        effective_boundaries = _apply_corrections(effective_boundaries, correction_overlay)
    model = SceneModel(
        binding,
        tuple(_atom_from_value(item) for item in _records(story_atoms, "atoms")),
        effective_boundaries,
        tuple(_scene_from_value(item) for item in _records(scene_assembly, "scenes")),
        tuple(
            _branch_from_value(item)
            for item in _records(scene_assembly, "temporary_branches")
        ),
        tuple(
            _occurrence_from_value(item)
            for item in _records(scene_assembly, "occurrences")
        ),
        tuple(_lane_from_value(item) for item in _records(scene_assembly, "lanes")),
        tuple(_chapter_from_value(item) for item in _records(scene_assembly, "chapters")),
        tuple(_loop_from_value(item) for item in _records(scene_assembly, "loop_hubs")),
        _coverage_from_value(_mapping(story_atoms.get("coverage"), "story atom coverage")),
        correction_overlay,
    )
    model.validate()
    if scene_assembly.get("scene_model_hash") != model.structural_hash:
        raise ValueError("M11 scene assembly structural hash is invalid")
    return model


def scene_model_mapping_from_phase_results(
    canonical: CanonicalGraph | Mapping[str, object],
    phase_results: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Return the normalized scene model consumed by the browser adapter."""

    return cast(
        dict[str, object],
        scene_model_from_phase_results(
            canonical,
            phase_results["story_atoms"],
            phase_results["scene_boundaries"],
            phase_results["scene_assembly"],
        ).normalized_dict(),
    )


def stored_scene_model_mapping(
    phase_results: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Compose the published model without decoding the large canonical payload."""

    atoms = phase_results["story_atoms"]
    boundaries = phase_results["scene_boundaries"]
    assembly = phase_results["scene_assembly"]
    if atoms.get("schema") != STORY_ATOMS_SCHEMA:
        raise ValueError("published M11 story atoms are incompatible")
    if boundaries.get("schema") != SCENE_BOUNDARIES_SCHEMA:
        raise ValueError("published M11 boundaries are incompatible")
    if assembly.get("schema") != SCENE_ASSEMBLY_SCHEMA:
        raise ValueError("published M11 assembly is incompatible")
    bindings = [
        _mapping(item.get("binding"), "published M11 binding")
        for item in (atoms, boundaries, assembly)
    ]
    if bindings[1:] != bindings[:-1]:
        raise ValueError("published M11 phase bindings disagree")
    model: dict[str, object] = {
        "schema_version": 1,
        "schema": M11_SCENE_MODEL_SCHEMA,
        "binding": dict(bindings[0]),
        "atom_rule_version": atoms.get("atom_rule_version"),
        "boundary_rule_version": boundaries.get("boundary_rule_version"),
        "atoms": sorted(
            (dict(item) for item in _records(atoms, "atoms")),
            key=lambda item: _text(item, "id"),
        ),
        "boundaries": sorted(
            (dict(item) for item in _records(boundaries, "boundaries")),
            key=lambda item: _text(item, "id"),
        ),
        "scenes": list(_records(assembly, "scenes")),
        "temporary_branches": list(_records(assembly, "temporary_branches")),
        "occurrences": list(_records(assembly, "occurrences")),
        "lanes": list(_records(assembly, "lanes")),
        "chapters": list(_records(assembly, "chapters")),
        "loop_hubs": list(_records(assembly, "loop_hubs")),
        "coverage": dict(_mapping(atoms.get("coverage"), "published M11 coverage")),
        "correction_overlay": assembly.get("correction_overlay"),
    }
    structural_hash = hashlib.sha256(canonical_json(model)).hexdigest()
    if assembly.get("scene_model_hash") != structural_hash:
        raise ValueError("published M11 model hash is invalid")
    return model


def _atom_from_value(value: Mapping[str, object]) -> StoryAtom:
    source_order = value.get("source_order")
    if not isinstance(source_order, Sequence) or isinstance(source_order, (str, bytes)):
        raise ValueError("story atom source_order must be an array")
    if len(source_order) != 4:
        raise ValueError("story atom source_order must have four fields")
    return StoryAtom(
        _text(value, "id"),
        AtomKind(_text(value, "kind")),
        _text(value, "primary_node_id"),
        _text(value, "label"),
        bool(value.get("story_facing", False)),
        _text(value, "rule_id"),
        _provenance_from_value(_mapping(value.get("provenance"), "atom provenance")),
        str(value.get("source_kind", "")),
        _optional_text(value, "speaker"),
        (
            str(source_order[0]),
            _plain_int(source_order[1], "story atom source line"),
            _plain_int(source_order[2], "story atom source column"),
            str(source_order[3]),
        ),
    )


def _boundary_from_value(value: Mapping[str, object]) -> BoundaryDecision:
    return BoundaryDecision(
        _text(value, "id"),
        _optional_text(value, "before_atom_id"),
        _text(value, "after_atom_id"),
        BoundaryStrength(_text(value, "strength")),
        DecisionStatus(_text(value, "status")),
        _text(value, "rule_version"),
        _strings(value.get("canonical_anchor_ids")),
        _provenance_from_value(
            _mapping(value.get("provenance"), "boundary provenance")
        ),
        _text(value, "reason"),
        _text(value, "rule_id"),
    )


def _scene_from_value(value: Mapping[str, object]) -> Scene:
    return Scene(
        _text(value, "id"),
        _text(value, "chapter_id"),
        _text(value, "lane_id"),
        _text(value, "title"),
        _integer(value, "ordinal"),
        _strings(value.get("atom_ids")),
        _strings(value.get("temporary_branch_ids")),
        _strings(value.get("occurrence_ids")),
        SceneRepeatability(_text(value, "repeatability")),
        _optional_text(value, "loop_hub_id"),
        _text(value, "boundary_id"),
        bool(value.get("definition_only", False)),
        _provenance_from_value(_mapping(value.get("provenance"), "scene provenance")),
    )


def _branch_from_value(value: Mapping[str, object]) -> TemporaryBranchContainer:
    arms = tuple(
        TemporaryBranchArm(
            _text(item, "id"),
            _integer(item, "ordinal"),
            _strings(item.get("atom_ids")),
            _strings(item.get("scene_ids")),
            _strings(item.get("nested_branch_ids")),
            _strings(item.get("occurrence_ids")),
        )
        for item in _records(value, "arms")
    )
    return TemporaryBranchContainer(
        _text(value, "id"),
        _text(value, "canonical_region_id"),
        _text(value, "split_atom_id"),
        arms,
        _text(value, "merge_node_id"),
        _optional_text(value, "continuation_atom_id"),
        _text(value, "parent_scene_id"),
        _optional_text(value, "parent_branch_id"),
        _provenance_from_value(_mapping(value.get("provenance"), "branch provenance")),
    )


def _occurrence_from_value(value: Mapping[str, object]) -> CallSiteOccurrence:
    return CallSiteOccurrence(
        _text(value, "id"),
        _text(value, "call_atom_id"),
        _text(value, "callee_entry_node_id"),
        OccurrenceKind(_text(value, "kind")),
        _text(value, "scene_id"),
        _text(value, "lane_id"),
        _strings(value.get("referenced_atom_ids")),
        _strings(value.get("guard_fact_ids")),
        bool(value.get("collapsed", False)),
        bool(value.get("repeatable", False)),
        _provenance_from_value(
            _mapping(value.get("provenance"), "occurrence provenance")
        ),
    )


def _lane_from_value(value: Mapping[str, object]) -> PersistentLane:
    return PersistentLane(
        _text(value, "id"),
        LaneKind(_text(value, "kind")),
        _optional_text(value, "parent_lane_id"),
        _optional_text(value, "canonical_region_id"),
        _optional_int(value, "arm_ordinal"),
        _strings(value.get("scene_ids")),
        _optional_text(value, "split_atom_id"),
        _optional_text(value, "merge_node_id"),
        _provenance_from_value(_mapping(value.get("provenance"), "lane provenance")),
    )


def _chapter_from_value(value: Mapping[str, object]) -> Chapter:
    return Chapter(
        _text(value, "id"),
        _text(value, "label"),
        _integer(value, "ordinal"),
        _strings(value.get("lane_ids")),
        _strings(value.get("scene_ids")),
        _optional_text(value, "boundary_id"),
        _provenance_from_value(_mapping(value.get("provenance"), "chapter provenance")),
    )


def _loop_from_value(value: Mapping[str, object]) -> LoopHub:
    return LoopHub(
        _text(value, "id"),
        _text(value, "canonical_region_id"),
        _text(value, "hub_atom_id"),
        _strings(value.get("scene_ids")),
        _strings(value.get("occurrence_ids")),
        tuple(
            ReturnToHub(
                _text(item, "id"),
                _text(item, "scene_id"),
                _text(item, "hub_atom_id"),
                _provenance_from_value(
                    _mapping(item.get("provenance"), "return provenance")
                ),
            )
            for item in _records(value, "return_relationships")
        ),
        tuple(
            PartialOrderRelation(
                _text(item, "id"),
                _text(item, "before_scene_id"),
                _text(item, "after_scene_id"),
                _provenance_from_value(
                    _mapping(item.get("provenance"), "partial-order provenance")
                ),
            )
            for item in _records(value, "partial_order")
        ),
        _provenance_from_value(_mapping(value.get("provenance"), "loop provenance")),
    )


def _coverage_from_value(value: Mapping[str, object]) -> CanonicalCoverage:
    return CanonicalCoverage(
        _strings(value.get("node_ids")),
        _strings(value.get("edge_ids")),
        _strings(value.get("region_ids")),
        _strings(value.get("fact_ids")),
        tuple(
            CoverageEntry(
                CoverageCollection(_text(item, "collection")),
                _text(item, "canonical_id"),
                CoverageDisposition(_text(item, "disposition")),
                _optional_text(item, "owner_atom_id"),
                _strings(item.get("reference_ids")),
                _text(item, "reason"),
            )
            for item in _records(value, "entries")
        ),
    )


def _correction_overlay_from_value(value: Mapping[str, object]) -> CorrectionOverlay:
    binding = _binding_from_value(_mapping(value.get("binding"), "correction binding"))
    return CorrectionOverlay(
        binding,
        tuple(
            Correction(
                _text(item, "id"),
                CorrectionOperation(_text(item, "operation")),
                CorrectionStatus(_text(item, "status")),
                _optional_text(item, "atom_id"),
                _optional_text(item, "boundary_id"),
                _strings(item.get("scene_ids")),
                _binding_from_value(_mapping(item.get("binding"), "correction binding")),
                _text(item, "reason"),
            )
            for item in _records(value, "corrections")
        ),
    )


def _provenance_from_value(value: Mapping[str, object]) -> Provenance:
    return Provenance(
        _strings(value.get("node_ids")),
        _strings(value.get("edge_ids")),
        _strings(value.get("region_ids")),
        _strings(value.get("fact_ids")),
        _strings(value.get("evidence_ids")),
        _strings(value.get("proof_ids")),
    )


def _atom_for_node(
    node: Mapping[str, object],
    evidence_by_id: Mapping[str, Mapping[str, object]],
) -> StoryAtom:
    node_id = _text(node, "id")
    node_kind = str(node.get("kind", ""))
    attributes = _mapping(node.get("attributes"), "canonical node attributes")
    source_kind = str(attributes.get("source_kind", ""))
    atom_kind, story_facing, rule_id = _atom_classification(
        node_kind,
        source_kind,
        attributes,
    )
    evidence_ids = tuple(sorted(_strings(node.get("evidence_ids"))))
    proof_ids = tuple(sorted(_strings(node.get("proof_ids"))))
    fact_ids = tuple(sorted(_strings(attributes.get("fact_ids"))))
    source_order = _source_order(node, evidence_ids, evidence_by_id)
    speaker = _metadata_value(attributes, ("speaker", "character", "who"))
    return StoryAtom(
        stable_m11_id("atom", node_id),
        atom_kind,
        node_id,
        _atom_label(node, source_kind, attributes, speaker),
        story_facing,
        rule_id,
        Provenance(
            node_ids=(node_id,),
            fact_ids=fact_ids,
            evidence_ids=evidence_ids,
            proof_ids=proof_ids,
        ),
        source_kind,
        speaker,
        source_order,
    )


def _canonical_story_atoms(
    nodes: Sequence[Mapping[str, object]],
    edges: Sequence[Mapping[str, object]],
    regions: Sequence[Mapping[str, object]],
    atoms: Sequence[StoryAtom],
) -> tuple[StoryAtom, ...]:
    """Linearize exact M10 precedence; use route/source order only for ties."""

    atom_by_node = {atom.primary_node_id: atom for atom in atoms}
    node_by_id = {_text(node, "id"): node for node in nodes}

    loop_return_edges = {
        _text(edge, "id")
        for region in regions
        if str(region.get("kind", "")) == "loop_choice"
        for edge in edges
        if _text(edge, "target_id") == _text(region, "split_node_id")
        and _text(edge, "source_id")
        in {
            _text(region, "split_node_id"),
            *_strings(region.get("member_node_ids")),
        }
    }

    route_order_by_label: dict[str, int] = {}
    for node in nodes:
        attributes = _mapping(node.get("attributes"), "canonical node attributes")
        route = attributes.get("route")
        if not isinstance(route, Mapping):
            continue
        order = route.get("order")
        if not isinstance(order, int) or isinstance(order, bool):
            continue
        label = str(node.get("label", ""))
        route_order_by_label[label] = min(route_order_by_label.get(label, order), order)

    def priority(node_id: str) -> tuple[int, tuple[str, int, int, str], str]:
        node = node_by_id[node_id]
        attributes = _mapping(node.get("attributes"), "canonical node attributes")
        route = attributes.get("route")
        route_order: int | None = None
        if isinstance(route, Mapping):
            candidate = route.get("order")
            if isinstance(candidate, int) and not isinstance(candidate, bool):
                route_order = candidate
        if route_order is None:
            route_order = route_order_by_label.get(str(node.get("label", "")), 2**31 - 1)
        atom = atom_by_node[node_id]
        return (route_order, atom.source_order, atom.id)

    successors: dict[str, set[str]] = defaultdict(set)
    indegree = {node_id: 0 for node_id in atom_by_node}
    for edge in edges:
        edge_id = _text(edge, "id")
        source_id = _text(edge, "source_id")
        target_id = _text(edge, "target_id")
        if (
            edge_id in loop_return_edges
            or str(edge.get("kind", "")) in _ORDERING_IGNORED_EDGE_KINDS
            or str(edge.get("kind", "")) in _ORDERING_CYCLE_EDGE_KINDS
            or not bool(edge.get("resolved", True))
            or source_id == target_id
            or source_id not in atom_by_node
            or target_id not in atom_by_node
            or target_id in successors[source_id]
        ):
            continue
        successors[source_id].add(target_id)
        indegree[target_id] += 1

    ready: list[tuple[tuple[int, tuple[str, int, int, str], str], str]] = []
    remaining = set(atom_by_node)
    for node_id, count in indegree.items():
        if count == 0:
            heapq.heappush(ready, (priority(node_id), node_id))

    ordered: list[StoryAtom] = []
    while remaining:
        if not ready:
            # Exact graphs can retain non-loop cycles around procedures. Breaking the
            # smallest remaining tie only linearizes presentation; it adds no edge.
            node_id = min(remaining, key=priority)
        else:
            _key, node_id = heapq.heappop(ready)
            if node_id not in remaining:
                continue
        remaining.remove(node_id)
        ordered.append(atom_by_node[node_id])
        for target_id in sorted(successors.get(node_id, ()), key=priority):
            indegree[target_id] -= 1
            if indegree[target_id] == 0 and target_id in remaining:
                heapq.heappush(ready, (priority(target_id), target_id))
    return tuple(ordered)


def _atom_classification(
    node_kind: str,
    source_kind: str,
    attributes: Mapping[str, object],
) -> tuple[AtomKind, bool, str]:
    if node_kind == "choice" or source_kind in {"menu", "menu_choice"}:
        return AtomKind.CHOICE, True, "canonical_choice"
    if node_kind == "condition" or source_kind in {"if", "if_branch"}:
        return AtomKind.CONDITION, False, "canonical_condition"
    if node_kind == "loop":
        return AtomKind.LOOP, True, "canonical_loop"
    if node_kind == "terminal":
        return AtomKind.TERMINAL, True, "canonical_terminal"
    if node_kind == "unresolved":
        return AtomKind.UNRESOLVED, True, "canonical_unresolved"
    if source_kind in {"say", "dialogue"}:
        return AtomKind.DIALOGUE, True, "source_dialogue"
    if source_kind in {"narration", "narrator"}:
        return AtomKind.NARRATION, True, "source_narration"
    if source_kind in {"scene", "show", "hide", "with"}:
        return AtomKind.VISUAL_CHANGE, True, "source_visual_change"
    if source_kind == "call":
        return AtomKind.CALL, True, "canonical_call_site"
    if source_kind in {"python", "default", "define", "set", "assignment"} or _strings(
        attributes.get("fact_ids")
    ):
        return AtomKind.STATE_CHANGE, False, "canonical_state_change"
    if source_kind in {
        "label",
        "merge",
        "return",
        "jump",
        "procedure_return_boundary",
        "call_return_site",
    }:
        return AtomKind.TECHNICAL, False, "canonical_structural_support"
    if bool(attributes.get("hidden")) or bool(attributes.get("synthetic")):
        return AtomKind.TECHNICAL, False, "canonical_hidden_support"
    if node_kind == "script_unit":
        return AtomKind.NARRATION, True, "source_narrative_unit"
    return AtomKind.TECHNICAL, False, "canonical_technical_support"


def _atom_label(
    node: Mapping[str, object],
    source_kind: str,
    attributes: Mapping[str, object],
    speaker: str | None,
) -> str:
    metadata_label = _metadata_value(attributes, ("caption", "title", "display_name"))
    if metadata_label:
        return metadata_label[:160]
    source_text = str(attributes.get("source_text", "")).strip()
    if source_kind in {"scene", "show", "hide"}:
        match = re.match(r"^(?:scene|show|hide)\s+([^\s:]+)", source_text, re.IGNORECASE)
        if match:
            return _humanize_identifier(match.group(1))[:160]
        return "Visual change"
    if source_kind == "menu_choice":
        choice = _quoted_caption(source_text)
        return choice[:160] if choice else "Choice"
    if source_kind in {"say", "dialogue"}:
        return f"{speaker} dialogue" if speaker else "Dialogue"
    if source_kind in {"narration", "narrator"}:
        return "Narration"
    if source_kind == "call":
        return "Called narrative"
    label = str(node.get("label", "Story"))
    return _humanize_identifier(label)[:160] or "Story element"


def _canonical_coverage(
    nodes: Sequence[Mapping[str, object]],
    edges: Sequence[Mapping[str, object]],
    regions: Sequence[Mapping[str, object]],
    facts: Sequence[Mapping[str, object]],
    atom_by_node: Mapping[str, str],
) -> CanonicalCoverage:
    entries: list[CoverageEntry] = []
    for node in nodes:
        node_id = _text(node, "id")
        entries.append(
            CoverageEntry(
                CoverageCollection.NODE,
                node_id,
                CoverageDisposition.ATOM_OWNED,
                atom_by_node[node_id],
                (),
                "The canonical node has exactly one deterministic atom owner.",
            )
        )
    for edge in edges:
        edge_id = _text(edge, "id")
        references = tuple(
            atom_by_node[item]
            for item in (_text(edge, "source_id"), _text(edge, "target_id"))
            if item in atom_by_node
        )
        entries.append(
            CoverageEntry(
                CoverageCollection.EDGE,
                edge_id,
                CoverageDisposition.STRUCTURAL_REFERENCE,
                None,
                references,
                "The M10 edge remains a referenced structural relationship.",
            )
        )
    for region in regions:
        region_id = _text(region, "id")
        node_ids = {
            _text(region, "split_node_id"),
            *_strings(region.get("member_node_ids")),
        }
        if isinstance(region.get("merge_node_id"), str):
            node_ids.add(_text(region, "merge_node_id"))
        entries.append(
            CoverageEntry(
                CoverageCollection.REGION,
                region_id,
                CoverageDisposition.STRUCTURAL_REFERENCE,
                None,
                tuple(sorted(atom_by_node[item] for item in node_ids if item in atom_by_node)),
                "The canonical region supplies lane, branch, or loop ownership by reference.",
            )
        )
    atom_facts: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        attributes = _mapping(node.get("attributes"), "canonical node attributes")
        atom_id = atom_by_node[_text(node, "id")]
        for fact_id in _strings(attributes.get("fact_ids")):
            atom_facts[fact_id].append(atom_id)
    for fact in facts:
        fact_id = _text(fact, "id")
        entries.append(
            CoverageEntry(
                CoverageCollection.FACT,
                fact_id,
                CoverageDisposition.COLLAPSED_SUPPORT,
                None,
                tuple(sorted(atom_facts.get(fact_id, ()))),
                "The canonical fact remains provenance and boundary support, not copied text.",
            )
        )
    return CanonicalCoverage(
        tuple(sorted(atom_by_node)),
        tuple(sorted(_text(item, "id") for item in edges)),
        tuple(sorted(_text(item, "id") for item in regions)),
        tuple(sorted(_text(item, "id") for item in facts)),
        tuple(entries),
    )


def _apply_corrections(
    boundaries: tuple[BoundaryDecision, ...],
    overlay: CorrectionOverlay,
) -> tuple[BoundaryDecision, ...]:
    by_id = {item.id: item for item in boundaries}
    by_atom = {item.after_atom_id: item.id for item in boundaries}
    for correction in overlay.corrections:
        if correction.status is not CorrectionStatus.APPLIED:
            continue
        if correction.operation is CorrectionOperation.SPLIT_BEFORE_ATOM:
            boundary_id = by_atom.get(correction.atom_id or "")
            if boundary_id is None:
                continue
            boundary = by_id[boundary_id]
            by_id[boundary_id] = replace(
                boundary,
                strength=BoundaryStrength.HARD,
                status=DecisionStatus.ACCEPTED,
                reason=f"Minimal split correction: {correction.reason}"[:500],
                rule_id="correction_split",
            )
        elif correction.operation is CorrectionOperation.MERGE_ADJACENT_SCENES:
            boundary_id = correction.boundary_id or ""
            if boundary_id not in by_id:
                continue
            boundary = by_id[boundary_id]
            by_id[boundary_id] = replace(
                boundary,
                strength=BoundaryStrength.WEAK,
                status=DecisionStatus.REJECTED,
                reason=f"Minimal adjacent-scene merge correction: {correction.reason}"[:500],
                rule_id="correction_merge",
            )
    return tuple(by_id[item.id] for item in boundaries)


def _persistent_boundary_nodes(
    canonical: Mapping[str, object],
) -> tuple[dict[str, Provenance], dict[str, Provenance]]:
    entry_support: dict[str, list[Provenance]] = defaultdict(list)
    merge_support: dict[str, list[Provenance]] = defaultdict(list)
    for region in _records(canonical, "regions"):
        if str(region.get("kind")) not in _PERSISTENT_REGION_KINDS:
            continue
        provenance = _region_provenance(region)
        attributes = _mapping(region.get("attributes"), "region attributes")
        for arm in _records(attributes, "arms"):
            entry_support[_text(arm, "entry_node_id")].append(provenance)
        merge = region.get("merge_node_id")
        if isinstance(merge, str):
            merge_support[merge].append(provenance)
    return (
        {
            node_id: _merge_provenance(values)
            for node_id, values in entry_support.items()
        },
        {
            node_id: _merge_provenance(values)
            for node_id, values in merge_support.items()
        },
    )


def _resolved_label_entry_support(
    canonical: Mapping[str, object],
) -> dict[str, dict[str, Provenance]]:
    """Index exact M10 story transfers that continue into a label entry."""

    nodes = _records(canonical, "nodes")
    label_nodes = {
        _text(node, "id")
        for node in nodes
        if str(
            _mapping(node.get("attributes"), "canonical node attributes").get(
                "source_kind", ""
            )
        )
        == "label"
    }
    support: dict[str, dict[str, list[Provenance]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for edge in _records(canonical, "edges"):
        source_id = _text(edge, "source_id")
        target_id = _text(edge, "target_id")
        if (
            target_id not in label_nodes
            or not bool(edge.get("resolved", True))
            or str(edge.get("kind", "")) not in {"flow", "jump"}
        ):
            continue
        support[target_id][source_id].append(_edge_provenance(edge))
    return {
        target_id: {
            source_id: _merge_provenance(values)
            for source_id, values in by_source.items()
        }
        for target_id, by_source in support.items()
    }


def _unresolved_boundary_support(
    canonical: Mapping[str, object],
) -> dict[str, Provenance]:
    """Index exact unresolved M10 edges by their presentation-safe target."""

    support: dict[str, list[Provenance]] = defaultdict(list)
    for edge in _records(canonical, "edges"):
        if (
            bool(edge.get("resolved", True))
            and str(edge.get("kind", "")) != "unresolved"
            and str(edge.get("reachability", "")) != "unresolved_dynamic_behavior"
        ):
            continue
        support[_text(edge, "target_id")].append(_edge_provenance(edge))
    return {
        node_id: _merge_provenance(values) for node_id, values in support.items()
    }


def _fact_category_provenance(
    attributes: Mapping[str, object],
    fact_by_id: Mapping[str, Mapping[str, object]],
) -> dict[StateCategory, Provenance]:
    """Return proven semantic state categories using the existing M10 fact taxonomy."""

    support: dict[StateCategory, list[Provenance]] = defaultdict(list)
    for fact_id in _strings(attributes.get("fact_ids")):
        fact = fact_by_id.get(fact_id)
        if fact is None or str(fact.get("status", "")) != "proven":
            continue
        fact_attributes = _mapping(fact.get("attributes"), "canonical fact attributes")
        variable = fact_attributes.get("variable")
        if not isinstance(variable, str) or not variable:
            continue
        category = infer_state_category(variable)
        if category not in {StateCategory.LOCATION, StateCategory.PROGRESSION}:
            continue
        support[category].append(
            Provenance(
                fact_ids=(fact_id,),
                evidence_ids=tuple(sorted(_strings(fact.get("evidence_ids")))),
            )
        )
    return {
        category: _merge_provenance(values) for category, values in support.items()
    }


def _is_chapter_anchor(atom: StoryAtom, source_kind: str) -> bool:
    if source_kind in {"show", "hide", "with", "label"}:
        return False
    return atom.story_facing or atom.kind in {
        AtomKind.CHOICE,
        AtomKind.CALL,
        AtomKind.LOOP,
        AtomKind.TERMINAL,
        AtomKind.UNRESOLVED,
    }


def _merge_continuation(
    merge_node_id: str,
    edges: Sequence[Mapping[str, object]],
    atom_by_node: Mapping[str, StoryAtom],
) -> str | None:
    targets = sorted(
        {
            _text(edge, "target_id")
            for edge in edges
            if _text(edge, "source_id") == merge_node_id and bool(edge.get("resolved", True))
        }
    )
    if len(targets) != 1:
        return None
    target = atom_by_node.get(targets[0])
    return None if target is None else target.id


def _region_provenance(region: Mapping[str, object]) -> Provenance:
    return Provenance(
        region_ids=(_text(region, "id"),),
        proof_ids=tuple(sorted(_strings(region.get("proof_ids")))),
    )


def _edge_provenance(edge: Mapping[str, object]) -> Provenance:
    attributes = _mapping(edge.get("attributes"), "canonical edge attributes")
    return Provenance(
        node_ids=(_text(edge, "source_id"), _text(edge, "target_id")),
        edge_ids=(_text(edge, "id"),),
        fact_ids=tuple(
            sorted(
                {
                    *_strings(attributes.get("gate_ids")),
                    *_strings(attributes.get("effect_ids")),
                }
            )
        ),
        evidence_ids=tuple(sorted(_strings(edge.get("evidence_ids")))),
        proof_ids=tuple(sorted(_strings(edge.get("proof_ids")))),
    )


def _merge_provenance(values: Iterable[Provenance]) -> Provenance:
    materialized = tuple(values)
    return Provenance(
        tuple(sorted({item for value in materialized for item in value.node_ids})),
        tuple(sorted({item for value in materialized for item in value.edge_ids})),
        tuple(sorted({item for value in materialized for item in value.region_ids})),
        tuple(sorted({item for value in materialized for item in value.fact_ids})),
        tuple(sorted({item for value in materialized for item in value.evidence_ids})),
        tuple(sorted({item for value in materialized for item in value.proof_ids})),
    )


def _scene_title(
    atoms: Sequence[StoryAtom],
    node_by_id: Mapping[str, Mapping[str, object]],
    ordinal: int,
) -> str:
    for atom in atoms:
        if atom.kind is AtomKind.VISUAL_CHANGE and atom.label != "Visual change":
            return atom.label
    for atom in atoms:
        if atom.story_facing and atom.label not in {"Dialogue", "Narration"}:
            return atom.label
    for atom in atoms:
        label = str(node_by_id[atom.primary_node_id].get("label", ""))
        if label:
            return _humanize_identifier(label)[:160]
    return f"Scene {ordinal + 1}"


def _presentation_relationship(
    kind: str,
    source_id: str,
    target_id: str,
    *,
    canonical_edge_ids: Sequence[str] = (),
) -> dict[str, object]:
    value: dict[str, object] = {
        "id": stable_m11_id("relationship", kind, source_id, target_id),
        "kind": kind,
        "source_id": source_id,
        "target_id": target_id,
    }
    if canonical_edge_ids:
        edge_ids = tuple(sorted(set(canonical_edge_ids)))
        value["canonical_edge_ids"] = list(
            edge_ids[:_MAX_RELATIONSHIP_CANONICAL_EDGE_IDS]
        )
        value["canonical_edge_count"] = len(edge_ids)
    return value


def _source_order(
    node: Mapping[str, object],
    evidence_ids: Sequence[str],
    evidence_by_id: Mapping[str, Mapping[str, object]],
) -> tuple[str, int, int, str]:
    candidates: list[tuple[str, int, int, str]] = []
    for evidence_id in evidence_ids:
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            continue
        source = evidence.get("source")
        if not isinstance(source, Mapping):
            continue
        start = source.get("start")
        if not isinstance(start, Mapping):
            continue
        path = source.get("path")
        line = start.get("line")
        column = start.get("column")
        if (
            isinstance(path, str)
            and isinstance(line, int)
            and not isinstance(line, bool)
            and isinstance(column, int)
            and not isinstance(column, bool)
        ):
            candidates.append((path, line, column, _text(node, "id")))
    if candidates:
        return min(candidates)
    attributes = _mapping(node.get("attributes"), "canonical node attributes")
    route = attributes.get("route")
    route_order = 0
    if isinstance(route, Mapping):
        raw_order = route.get("order")
        if isinstance(raw_order, int) and not isinstance(raw_order, bool):
            route_order = raw_order
    return (f"~technical/{node.get('label', '')}", route_order, 0, _text(node, "id"))


def _metadata_value(
    attributes: Mapping[str, object], keys: Sequence[str]
) -> str | None:
    metadata = attributes.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _quoted_caption(source_text: str) -> str | None:
    match = re.search(r"(?:^|\s)([\"'])(.*?)\1", source_text)
    return match.group(2).strip() if match and match.group(2).strip() else None


def _humanize_identifier(value: str) -> str:
    return " ".join(value.replace(".", "_").replace("-", "_").split("_")).strip().title()


def _canonical_value(canonical: CanonicalGraph | Mapping[str, object]) -> dict[str, object]:
    value = canonical.to_dict() if isinstance(canonical, CanonicalGraph) else dict(canonical)
    if (
        value.get("schema") != CANONICAL_GRAPH_SCHEMA
        or value.get("schema_version") != CANONICAL_GRAPH_SCHEMA_VERSION
    ):
        raise ValueError("M11 consumes only the supported M10 canonical graph")
    return value


def _binding(
    canonical: Mapping[str, object],
    provided: CanonicalBinding | None = None,
) -> CanonicalBinding:
    generation = canonical.get("source_generation")
    schema = canonical.get("schema")
    if not isinstance(generation, str) or not isinstance(schema, str):
        raise ValueError("canonical graph binding is incomplete")
    if provided is not None:
        if provided.source_generation != generation or provided.canonical_schema != schema:
            raise ValueError("provided canonical binding does not match the M10 payload")
        return provided
    canonical_hash = hashlib.sha256(canonical_json(dict(canonical))).hexdigest()
    return CanonicalBinding(generation, schema, canonical_hash)


def _binding_from_value(value: Mapping[str, object]) -> CanonicalBinding:
    return CanonicalBinding(
        _text(value, "source_generation"),
        _text(value, "canonical_schema"),
        _text(value, "canonical_hash"),
    )


def _require_phase_binding(
    phase: Mapping[str, object], schema: str, binding: CanonicalBinding
) -> None:
    if phase.get("schema") != schema:
        raise ValueError(f"M11 phase must use {schema}")
    phase_binding = _binding_from_value(_mapping(phase.get("binding"), "phase binding"))
    if phase_binding != binding:
        raise ValueError("M11 phase binding does not match current canonical authority")


def _mapping(value: object, name: str = "record") -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _records(value: Mapping[str, object], key: str) -> tuple[Mapping[str, object], ...]:
    raw = value.get(key)
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ValueError(f"{key} must be an array")
    if not all(isinstance(item, Mapping) for item in raw):
        raise ValueError(f"{key} must contain objects")
    return cast(tuple[Mapping[str, object], ...], tuple(raw))


def _records_or_empty(value: object) -> tuple[Mapping[str, object], ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} must be non-empty text")
    return item


def _integer(value: Mapping[str, object], key: str) -> int:
    return _plain_int(value.get(key), key)


def _optional_text(value: Mapping[str, object], key: str) -> str | None:
    item = value.get(key)
    return item if isinstance(item, str) else None


def _optional_int(value: Mapping[str, object], key: str) -> int | None:
    item = value.get(key)
    return item if isinstance(item, int) and not isinstance(item, bool) else None


def _plain_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value
