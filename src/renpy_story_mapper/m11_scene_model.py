"""Immutable contracts for deterministic M11 human scenes.

M11 records reference M10 canonical authority by stable ID.  They never copy source text,
evidence text, or control-flow ownership into a competing mutable graph.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from enum import StrEnum

from renpy_story_mapper.storage import canonical_json

M11_SCENE_MODEL_SCHEMA_VERSION = 1
M11_SCENE_MODEL_SCHEMA = f"m11-scene-model-v{M11_SCENE_MODEL_SCHEMA_VERSION}"
M11_ATOM_RULE_VERSION = "m11-atom-rules-v2"
M11_BOUNDARY_RULE_VERSION = "m11-boundary-rules-v2"
MAX_BOUNDARY_REASON_LENGTH = 500
MAX_PROVENANCE_REFERENCES = 100_000

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]

class AtomKind(StrEnum):
    DIALOGUE = "dialogue"
    NARRATION = "narration"
    VISUAL_CHANGE = "visual_change"
    CHOICE = "choice"
    CONDITION = "condition"
    STATE_CHANGE = "state_change"
    CALL = "call"
    LOOP = "loop"
    TERMINAL = "terminal"
    UNRESOLVED = "unresolved"
    TECHNICAL = "technical"


class BoundaryStrength(StrEnum):
    HARD = "hard"
    STRONG = "strong"
    WEAK = "weak"
    CONFLICT = "conflict"


class DecisionStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class OccurrenceKind(StrEnum):
    NARRATIVE = "narrative"
    TECHNICAL = "technical"


class LaneKind(StrEnum):
    SPINE = "spine"
    PERSISTENT_ROUTE = "persistent_route"
    TERMINAL_SPLIT = "terminal_split"


class SceneRepeatability(StrEnum):
    ONCE = "once"
    REPEATABLE = "repeatable"


class CorrectionOperation(StrEnum):
    SPLIT_BEFORE_ATOM = "split_before_atom"
    MERGE_ADJACENT_SCENES = "merge_adjacent_scenes"


class CorrectionStatus(StrEnum):
    APPLIED = "applied"
    ORPHANED = "orphaned"
    REJECTED = "rejected"


class CoverageCollection(StrEnum):
    NODE = "node"
    EDGE = "edge"
    REGION = "region"
    FACT = "fact"


class CoverageDisposition(StrEnum):
    ATOM_OWNED = "atom_owned"
    STRUCTURAL_REFERENCE = "structural_reference"
    COLLAPSED_SUPPORT = "collapsed_support"
    UNREACHABLE_TECHNICAL = "unreachable_technical"
    SYNTHETIC_ANCHOR = "synthetic_anchor"


@dataclass(frozen=True)
class CanonicalBinding:
    source_generation: str
    canonical_schema: str
    canonical_hash: str

    def to_dict(self) -> dict[str, JsonValue]:
        return _json_mapping(asdict(self))


@dataclass(frozen=True)
class Provenance:
    node_ids: tuple[str, ...] = ()
    edge_ids: tuple[str, ...] = ()
    region_ids: tuple[str, ...] = ()
    fact_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    proof_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "node_ids": _json_value(sorted(self.node_ids)),
            "edge_ids": _json_value(sorted(self.edge_ids)),
            "region_ids": _json_value(sorted(self.region_ids)),
            "fact_ids": _json_value(sorted(self.fact_ids)),
            "evidence_ids": _json_value(sorted(self.evidence_ids)),
            "proof_ids": _json_value(sorted(self.proof_ids)),
        }


@dataclass(frozen=True)
class StoryAtom:
    id: str
    kind: AtomKind
    primary_node_id: str
    label: str
    story_facing: bool
    rule_id: str
    provenance: Provenance
    source_kind: str = ""
    speaker: str | None = None
    source_order: tuple[str, int, int, str] = ("", 0, 0, "")

    def to_dict(self) -> dict[str, JsonValue]:
        return _record_dict(self)


@dataclass(frozen=True)
class BoundaryDecision:
    id: str
    before_atom_id: str | None
    after_atom_id: str
    strength: BoundaryStrength
    status: DecisionStatus
    rule_version: str
    canonical_anchor_ids: tuple[str, ...]
    provenance: Provenance
    reason: str
    rule_id: str

    def to_dict(self) -> dict[str, JsonValue]:
        return _record_dict(self)


@dataclass(frozen=True)
class TemporaryBranchArm:
    id: str
    ordinal: int
    atom_ids: tuple[str, ...]
    scene_ids: tuple[str, ...]
    nested_branch_ids: tuple[str, ...]
    occurrence_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        return _record_dict(self)


@dataclass(frozen=True)
class TemporaryBranchContainer:
    id: str
    canonical_region_id: str
    split_atom_id: str
    arms: tuple[TemporaryBranchArm, ...]
    merge_node_id: str
    continuation_atom_id: str | None
    parent_scene_id: str
    parent_branch_id: str | None
    provenance: Provenance

    def to_dict(self) -> dict[str, JsonValue]:
        return _record_dict(self)


@dataclass(frozen=True)
class CallSiteOccurrence:
    id: str
    call_atom_id: str
    callee_entry_node_id: str
    kind: OccurrenceKind
    scene_id: str
    lane_id: str
    referenced_atom_ids: tuple[str, ...]
    guard_fact_ids: tuple[str, ...]
    collapsed: bool
    repeatable: bool
    provenance: Provenance

    def to_dict(self) -> dict[str, JsonValue]:
        return _record_dict(self)


@dataclass(frozen=True)
class Scene:
    id: str
    chapter_id: str
    lane_id: str
    title: str
    ordinal: int
    atom_ids: tuple[str, ...]
    temporary_branch_ids: tuple[str, ...]
    occurrence_ids: tuple[str, ...]
    repeatability: SceneRepeatability
    loop_hub_id: str | None
    boundary_id: str
    definition_only: bool
    provenance: Provenance

    def to_dict(self) -> dict[str, JsonValue]:
        return _record_dict(self)


@dataclass(frozen=True)
class PersistentLane:
    id: str
    kind: LaneKind
    parent_lane_id: str | None
    canonical_region_id: str | None
    arm_ordinal: int | None
    scene_ids: tuple[str, ...]
    split_atom_id: str | None
    merge_node_id: str | None
    provenance: Provenance

    def to_dict(self) -> dict[str, JsonValue]:
        return _record_dict(self)


@dataclass(frozen=True)
class Chapter:
    id: str
    label: str
    ordinal: int
    lane_ids: tuple[str, ...]
    scene_ids: tuple[str, ...]
    boundary_id: str | None
    provenance: Provenance

    def to_dict(self) -> dict[str, JsonValue]:
        return _record_dict(self)


@dataclass(frozen=True)
class PartialOrderRelation:
    id: str
    before_scene_id: str
    after_scene_id: str
    provenance: Provenance

    def to_dict(self) -> dict[str, JsonValue]:
        return _record_dict(self)


@dataclass(frozen=True)
class ReturnToHub:
    id: str
    scene_id: str
    hub_atom_id: str
    provenance: Provenance

    def to_dict(self) -> dict[str, JsonValue]:
        return _record_dict(self)


@dataclass(frozen=True)
class LoopHub:
    id: str
    canonical_region_id: str
    hub_atom_id: str
    scene_ids: tuple[str, ...]
    occurrence_ids: tuple[str, ...]
    return_relationships: tuple[ReturnToHub, ...]
    partial_order: tuple[PartialOrderRelation, ...]
    provenance: Provenance

    def to_dict(self) -> dict[str, JsonValue]:
        return _record_dict(self)


@dataclass(frozen=True)
class Correction:
    id: str
    operation: CorrectionOperation
    status: CorrectionStatus
    atom_id: str | None
    boundary_id: str | None
    scene_ids: tuple[str, ...]
    binding: CanonicalBinding
    reason: str

    def to_dict(self) -> dict[str, JsonValue]:
        return _record_dict(self)


@dataclass(frozen=True)
class CorrectionOverlay:
    binding: CanonicalBinding
    corrections: tuple[Correction, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        return _record_dict(self)


@dataclass(frozen=True)
class CoverageEntry:
    collection: CoverageCollection
    canonical_id: str
    disposition: CoverageDisposition
    owner_atom_id: str | None
    reference_ids: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, JsonValue]:
        return _record_dict(self)


@dataclass(frozen=True)
class CanonicalCoverage:
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    region_ids: tuple[str, ...]
    fact_ids: tuple[str, ...]
    entries: tuple[CoverageEntry, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "node_ids": _json_value(sorted(self.node_ids)),
            "edge_ids": _json_value(sorted(self.edge_ids)),
            "region_ids": _json_value(sorted(self.region_ids)),
            "fact_ids": _json_value(sorted(self.fact_ids)),
            "entries": [
                item.to_dict()
                for item in sorted(
                    self.entries, key=lambda item: (item.collection.value, item.canonical_id)
                )
            ],
        }


@dataclass(frozen=True)
class SceneModel:
    binding: CanonicalBinding
    atoms: tuple[StoryAtom, ...]
    boundaries: tuple[BoundaryDecision, ...]
    scenes: tuple[Scene, ...]
    temporary_branches: tuple[TemporaryBranchContainer, ...]
    occurrences: tuple[CallSiteOccurrence, ...]
    lanes: tuple[PersistentLane, ...]
    chapters: tuple[Chapter, ...]
    loop_hubs: tuple[LoopHub, ...]
    coverage: CanonicalCoverage
    correction_overlay: CorrectionOverlay | None = None
    atom_rule_version: str = M11_ATOM_RULE_VERSION
    boundary_rule_version: str = M11_BOUNDARY_RULE_VERSION
    operational_metadata: Mapping[str, object] | None = None

    def to_dict(self) -> dict[str, JsonValue]:
        value = self.normalized_dict()
        if self.operational_metadata is not None:
            value["operational_metadata"] = _json_value(dict(self.operational_metadata))
        return value

    def normalized_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": M11_SCENE_MODEL_SCHEMA_VERSION,
            "schema": M11_SCENE_MODEL_SCHEMA,
            "binding": self.binding.to_dict(),
            "atom_rule_version": self.atom_rule_version,
            "boundary_rule_version": self.boundary_rule_version,
            "atoms": _sorted_records(self.atoms),
            "boundaries": _sorted_records(self.boundaries),
            "scenes": _sorted_records(self.scenes),
            "temporary_branches": _sorted_records(self.temporary_branches),
            "occurrences": _sorted_records(self.occurrences),
            "lanes": _sorted_records(self.lanes),
            "chapters": _sorted_records(self.chapters),
            "loop_hubs": _sorted_records(self.loop_hubs),
            "coverage": self.coverage.to_dict(),
            "correction_overlay": (
                self.correction_overlay.to_dict()
                if self.correction_overlay is not None
                else None
            ),
        }

    def normalized_bytes(self) -> bytes:
        return canonical_json(self.normalized_dict())

    @property
    def structural_hash(self) -> str:
        return hashlib.sha256(self.normalized_bytes()).hexdigest()

    def validate(self) -> None:
        _validate_binding(self.binding)
        atoms = _unique_by_id(self.atoms, "atom")
        boundaries = _unique_by_id(self.boundaries, "boundary")
        scenes = _unique_by_id(self.scenes, "scene")
        branches = _unique_by_id(self.temporary_branches, "temporary branch")
        occurrences = _unique_by_id(self.occurrences, "call occurrence")
        lanes = _unique_by_id(self.lanes, "lane")
        chapters = _unique_by_id(self.chapters, "chapter")
        loop_hubs = _unique_by_id(self.loop_hubs, "loop hub")
        _validate_coverage(self.coverage, atoms)
        inventories = _coverage_inventories(self.coverage)

        atom_scene_owner: dict[str, str] = {}
        for scene in scenes.values():
            _require_refs(scene.atom_ids, atoms, f"scene {scene.id} atom")
            _require_refs(scene.temporary_branch_ids, branches, f"scene {scene.id} branch")
            _require_refs(scene.occurrence_ids, occurrences, f"scene {scene.id} occurrence")
            if scene.boundary_id not in boundaries:
                raise ValueError(f"scene {scene.id} has an unknown boundary")
            if scene.lane_id not in lanes or scene.chapter_id not in chapters:
                raise ValueError(f"scene {scene.id} has unknown hierarchy ownership")
            for atom_id in scene.atom_ids:
                if atom_id in atom_scene_owner:
                    raise ValueError(f"atom {atom_id} belongs to more than one scene")
                atom_scene_owner[atom_id] = scene.id
            _validate_provenance(scene.provenance, inventories, f"scene {scene.id}")
        if set(atom_scene_owner) != set(atoms):
            raise ValueError("every atom must belong to exactly one scene")

        for boundary in boundaries.values():
            if boundary.after_atom_id not in atoms:
                raise ValueError(f"boundary {boundary.id} has an unknown after atom")
            if boundary.before_atom_id is not None and boundary.before_atom_id not in atoms:
                raise ValueError(f"boundary {boundary.id} has an unknown before atom")
            if not boundary.canonical_anchor_ids or not boundary.reason.strip():
                raise ValueError(f"boundary {boundary.id} lacks anchors or a reason")
            if len(boundary.reason) > MAX_BOUNDARY_REASON_LENGTH:
                raise ValueError(f"boundary {boundary.id} reason is too long")
            if boundary.rule_id in {"persistent_lane_entry", "persistent_lane_merge"} and not (
                set(boundary.provenance.region_ids)
                & inventories[CoverageCollection.REGION]
            ):
                raise ValueError(
                    f"structural boundary {boundary.id} lacks canonical region provenance"
                )
            _validate_provenance(boundary.provenance, inventories, f"boundary {boundary.id}")

        nested_branch_owners: dict[str, str] = {}
        atom_id_by_node = {atom.primary_node_id: atom.id for atom in atoms.values()}
        for branch in branches.values():
            if branch.split_atom_id not in atoms or branch.parent_scene_id not in scenes:
                raise ValueError(f"temporary branch {branch.id} has unknown ownership")
            if branch.canonical_region_id not in inventories[CoverageCollection.REGION]:
                raise ValueError(f"temporary branch {branch.id} has an unknown canonical region")
            if branch.merge_node_id not in inventories[CoverageCollection.NODE]:
                raise ValueError(f"temporary branch {branch.id} has an unknown merge")
            if branch.parent_branch_id is not None and branch.parent_branch_id not in branches:
                raise ValueError(f"temporary branch {branch.id} has an unknown parent")
            if branch.split_atom_id not in scenes[branch.parent_scene_id].atom_ids:
                raise ValueError(f"temporary branch {branch.id} is detached from its parent scene")
            if branch.continuation_atom_id is not None and branch.continuation_atom_id not in atoms:
                raise ValueError(f"temporary branch {branch.id} has an unknown continuation")
            ordinals = [item.ordinal for item in branch.arms]
            if ordinals != list(range(len(ordinals))) or len(ordinals) != len(set(ordinals)):
                raise ValueError(f"temporary branch {branch.id} arm ordinals must be contiguous")
            arm_scene_owner: dict[str, str] = {}
            structural_arm_atoms = {
                boundary.after_atom_id
                for boundary in boundaries.values()
                if boundary.status is DecisionStatus.ACCEPTED
                and boundary.strength in {BoundaryStrength.HARD, BoundaryStrength.STRONG}
            }
            expanded = any(
                structural_arm_atoms.intersection(arm.atom_ids) for arm in branch.arms
            )
            merge_atom_id = atom_id_by_node.get(branch.merge_node_id)
            for arm in branch.arms:
                _require_refs(arm.atom_ids, atoms, f"temporary arm {arm.id} atom")
                _require_refs(arm.scene_ids, scenes, f"temporary arm {arm.id} scene")
                _require_refs(arm.occurrence_ids, occurrences, f"temporary arm {arm.id} occurrence")
                _require_refs(
                    arm.nested_branch_ids, branches, f"temporary arm {arm.id} nested branch"
                )
                if not expanded and arm.scene_ids:
                    raise ValueError(
                        f"short temporary branch {branch.id} exposes arm-local scenes"
                    )
                arm_atom_ids = set(arm.atom_ids)
                if merge_atom_id in arm_atom_ids or branch.continuation_atom_id in arm_atom_ids:
                    raise ValueError(
                        f"temporary arm {arm.id} includes merge or continuation ownership"
                    )
                for scene_id in arm.scene_ids:
                    prior_owner = arm_scene_owner.setdefault(scene_id, arm.id)
                    if prior_owner != arm.id:
                        raise ValueError(
                            f"temporary scene {scene_id} belongs to multiple sibling arms"
                        )
                    scene_atom_ids = set(scenes[scene_id].atom_ids)
                    if not scene_atom_ids <= arm_atom_ids:
                        raise ValueError(
                            f"temporary scene {scene_id} escapes arm {arm.id} ownership"
                        )
                    if branch.continuation_atom_id in scene_atom_ids:
                        raise ValueError(
                            f"temporary scene {scene_id} contains its post-merge continuation"
                        )
                for nested_id in arm.nested_branch_ids:
                    if nested_id in nested_branch_owners:
                        raise ValueError(f"temporary branch {nested_id} has multiple owners")
                    nested_branch_owners[nested_id] = branch.id
            _validate_provenance(branch.provenance, inventories, f"branch {branch.id}")

        for occurrence in occurrences.values():
            if occurrence.call_atom_id not in atoms or occurrence.scene_id not in scenes:
                raise ValueError(f"call occurrence {occurrence.id} has unknown ownership")
            if occurrence.lane_id != scenes[occurrence.scene_id].lane_id:
                raise ValueError(f"call occurrence {occurrence.id} lane disagrees with its scene")
            _require_refs(
                occurrence.referenced_atom_ids, atoms, f"occurrence {occurrence.id} atom"
            )
            if occurrence.kind is OccurrenceKind.NARRATIVE and not occurrence.referenced_atom_ids:
                raise ValueError(f"narrative occurrence {occurrence.id} has no content references")
            _validate_provenance(
                occurrence.provenance, inventories, f"occurrence {occurrence.id}"
            )

        lane_scene_members: dict[str, str] = {}
        for lane in lanes.values():
            _require_refs(lane.scene_ids, scenes, f"lane {lane.id} scene")
            if lane.kind is LaneKind.SPINE:
                if lane.parent_lane_id is not None or lane.canonical_region_id is not None:
                    raise ValueError(f"spine lane {lane.id} cannot claim persistent ownership")
            else:
                if lane.canonical_region_id is None or lane.arm_ordinal is None:
                    raise ValueError(f"persistent lane {lane.id} lacks region-arm ownership")
                if lane.canonical_region_id not in inventories[CoverageCollection.REGION]:
                    raise ValueError(f"persistent lane {lane.id} has an unknown region")
                if lane.split_atom_id not in atoms:
                    raise ValueError(f"persistent lane {lane.id} lacks its canonical split atom")
                if (
                    lane.merge_node_id is not None
                    and lane.merge_node_id not in inventories[CoverageCollection.NODE]
                ):
                    raise ValueError(f"persistent lane {lane.id} has an unknown merge node")
                if lane.canonical_region_id not in lane.provenance.region_ids:
                    raise ValueError(f"persistent lane {lane.id} lacks region provenance")
            if lane.parent_lane_id is not None and lane.parent_lane_id not in lanes:
                raise ValueError(f"lane {lane.id} has an unknown parent")
            for scene_id in lane.scene_ids:
                if scene_id in lane_scene_members:
                    raise ValueError(f"scene {scene_id} belongs to multiple lanes")
                lane_scene_members[scene_id] = lane.id
                if scenes[scene_id].lane_id != lane.id:
                    raise ValueError(f"scene {scene_id} lane membership is inconsistent")
            _validate_provenance(lane.provenance, inventories, f"lane {lane.id}")
        if set(lane_scene_members) != set(scenes):
            raise ValueError("every scene must belong to exactly one lane")

        chapter_scene_members: dict[str, str] = {}
        for chapter in chapters.values():
            _require_refs(chapter.lane_ids, lanes, f"chapter {chapter.id} lane")
            _require_refs(chapter.scene_ids, scenes, f"chapter {chapter.id} scene")
            if chapter.boundary_id is not None and chapter.boundary_id not in boundaries:
                raise ValueError(f"chapter {chapter.id} has an unknown boundary")
            for scene_id in chapter.scene_ids:
                if scene_id in chapter_scene_members:
                    raise ValueError(f"scene {scene_id} belongs to multiple chapters")
                chapter_scene_members[scene_id] = chapter.id
                if scenes[scene_id].chapter_id != chapter.id:
                    raise ValueError(f"scene {scene_id} chapter membership is inconsistent")
            _validate_provenance(chapter.provenance, inventories, f"chapter {chapter.id}")
        if set(chapter_scene_members) != set(scenes):
            raise ValueError("every scene must belong to exactly one chapter")

        hub_scene_owners: dict[str, set[str]] = {}
        for hub in loop_hubs.values():
            if hub.canonical_region_id not in inventories[CoverageCollection.REGION]:
                raise ValueError(f"loop hub {hub.id} has an unknown region")
            if hub.hub_atom_id not in atoms:
                raise ValueError(f"loop hub {hub.id} has an unknown atom")
            _require_refs(hub.scene_ids, scenes, f"loop hub {hub.id} scene")
            _require_refs(hub.occurrence_ids, occurrences, f"loop hub {hub.id} occurrence")
            for scene_id in hub.scene_ids:
                hub_scene_owners.setdefault(scene_id, set()).add(hub.id)
                scene = scenes[scene_id]
                if scene.repeatability is not SceneRepeatability.REPEATABLE:
                    raise ValueError(f"repeatable scene {scene_id} disagrees with its loop hub")
            for return_relation in hub.return_relationships:
                if return_relation.scene_id not in set(hub.scene_ids):
                    raise ValueError(f"loop hub {hub.id} has an external return relation")
                if return_relation.hub_atom_id != hub.hub_atom_id:
                    raise ValueError(f"loop hub {hub.id} return target is inconsistent")
                _validate_provenance(
                    return_relation.provenance,
                    inventories,
                    f"return relation {return_relation.id}",
                )
            for partial_relation in hub.partial_order:
                if not {
                    partial_relation.before_scene_id,
                    partial_relation.after_scene_id,
                } <= set(hub.scene_ids):
                    raise ValueError(f"loop hub {hub.id} has an external partial order")
                _validate_provenance(
                    partial_relation.provenance,
                    inventories,
                    f"partial order {partial_relation.id}",
                )
            _validate_provenance(hub.provenance, inventories, f"loop hub {hub.id}")

        for scene_id, hub_ids in hub_scene_owners.items():
            if scenes[scene_id].loop_hub_id not in hub_ids:
                raise ValueError(f"repeatable scene {scene_id} lacks a primary loop hub")

        if self.correction_overlay is not None:
            if self.correction_overlay.binding != self.binding:
                raise ValueError("correction overlay binding does not match the scene model")
            _validate_corrections(self.correction_overlay, atoms, boundaries, scenes)


def stable_m11_id(prefix: str, *parts: object) -> str:
    identity: list[object] = [M11_SCENE_MODEL_SCHEMA, prefix, *parts]
    return f"{prefix}_{hashlib.sha256(canonical_json(identity)).hexdigest()[:20]}"


def _validate_binding(binding: CanonicalBinding) -> None:
    if not binding.source_generation or not binding.canonical_schema:
        raise ValueError("M11 canonical binding fields must be non-empty")
    if len(binding.canonical_hash) != 64 or any(
        item not in "0123456789abcdef" for item in binding.canonical_hash
    ):
        raise ValueError("M11 canonical hash must be lowercase SHA-256")


def _validate_coverage(
    coverage: CanonicalCoverage, atoms: Mapping[str, StoryAtom]
) -> None:
    inventories = _coverage_inventories(coverage)
    entries: dict[tuple[CoverageCollection, str], CoverageEntry] = {}
    for entry in coverage.entries:
        key = (entry.collection, entry.canonical_id)
        if key in entries:
            raise ValueError(f"canonical {entry.collection.value} {entry.canonical_id} repeats")
        entries[key] = entry
        if entry.canonical_id not in inventories[entry.collection]:
            raise ValueError(f"coverage entry {entry.canonical_id} is not declared")
    expected = {
        (collection, canonical_id)
        for collection, values in inventories.items()
        for canonical_id in values
    }
    if set(entries) != expected:
        raise ValueError("every canonical node, edge, region, and fact needs one coverage entry")
    atom_by_node: dict[str, str] = {}
    for atom in atoms.values():
        if atom.primary_node_id in atom_by_node:
            raise ValueError(f"canonical node {atom.primary_node_id} has multiple atom owners")
        atom_by_node[atom.primary_node_id] = atom.id
        _validate_provenance(atom.provenance, inventories, f"atom {atom.id}")
    if set(atom_by_node) != inventories[CoverageCollection.NODE]:
        raise ValueError("every canonical node must have exactly one atom owner")
    for node_id, atom_id in atom_by_node.items():
        entry = entries[(CoverageCollection.NODE, node_id)]
        if (
            entry.disposition is not CoverageDisposition.ATOM_OWNED
            or entry.owner_atom_id != atom_id
        ):
            raise ValueError(f"canonical node {node_id} coverage disagrees with atom ownership")


def _coverage_inventories(
    coverage: CanonicalCoverage,
) -> dict[CoverageCollection, set[str]]:
    values = {
        CoverageCollection.NODE: set(coverage.node_ids),
        CoverageCollection.EDGE: set(coverage.edge_ids),
        CoverageCollection.REGION: set(coverage.region_ids),
        CoverageCollection.FACT: set(coverage.fact_ids),
    }
    if any(len(item) != len(raw) for item, raw in zip(values.values(), (
        coverage.node_ids,
        coverage.edge_ids,
        coverage.region_ids,
        coverage.fact_ids,
    ), strict=True)):
        raise ValueError("canonical coverage inventories must be unique")
    return values


def _validate_provenance(
    provenance: Provenance,
    inventories: Mapping[CoverageCollection, set[str]],
    owner: str,
) -> None:
    groups = (
        (provenance.node_ids, inventories[CoverageCollection.NODE], "node"),
        (provenance.edge_ids, inventories[CoverageCollection.EDGE], "edge"),
        (provenance.region_ids, inventories[CoverageCollection.REGION], "region"),
        (provenance.fact_ids, inventories[CoverageCollection.FACT], "fact"),
    )
    total = sum(len(values) for values, _, _ in groups) + len(provenance.evidence_ids) + len(
        provenance.proof_ids
    )
    if total > MAX_PROVENANCE_REFERENCES:
        raise ValueError(f"{owner} provenance exceeds the bounded reference limit")
    for values, inventory, name in groups:
        if len(values) != len(set(values)) or not set(values) <= inventory:
            raise ValueError(f"{owner} has invalid canonical {name} provenance")
    for name, values in (
        ("evidence", provenance.evidence_ids),
        ("proof", provenance.proof_ids),
    ):
        if len(values) != len(set(values)):
            raise ValueError(f"{owner} has duplicate {name} provenance")


def _validate_corrections(
    overlay: CorrectionOverlay,
    atoms: Mapping[str, StoryAtom],
    boundaries: Mapping[str, BoundaryDecision],
    scenes: Mapping[str, Scene],
) -> None:
    corrections = _unique_by_id(overlay.corrections, "correction")
    for correction in corrections.values():
        if correction.binding != overlay.binding or not correction.reason.strip():
            raise ValueError(f"correction {correction.id} has an invalid binding or reason")
        if correction.operation is CorrectionOperation.SPLIT_BEFORE_ATOM:
            if correction.atom_id not in atoms or correction.scene_ids:
                raise ValueError(f"split correction {correction.id} has invalid anchors")
        elif (
            len(correction.scene_ids) != 2
            or correction.scene_ids[0] == correction.scene_ids[1]
        ):
            raise ValueError(f"merge correction {correction.id} has invalid scene anchors")
        if correction.boundary_id is not None and correction.boundary_id not in boundaries:
            raise ValueError(f"correction {correction.id} has an unknown boundary")


def _unique_by_id[RecordT](
    items: Iterable[RecordT], name: str
) -> dict[str, RecordT]:
    result: dict[str, RecordT] = {}
    for item in items:
        item_id = getattr(item, "id", None)
        if not isinstance(item_id, str) or not item_id:
            raise ValueError(f"{name} IDs must be non-empty strings")
        if item_id in result:
            raise ValueError(f"duplicate {name} ID {item_id}")
        result[item_id] = item
    return result


def _require_refs(values: Iterable[str], records: Mapping[str, object], name: str) -> None:
    materialized = tuple(values)
    if len(materialized) != len(set(materialized)) or any(
        item not in records for item in materialized
    ):
        raise ValueError(f"{name} references are invalid")


def _sorted_records(values: Iterable[object]) -> list[JsonValue]:
    return [
        _record_dict(item)
        for item in sorted(values, key=lambda item: str(getattr(item, "id", "")))
    ]


def _record_dict(value: object) -> dict[str, JsonValue]:
    if not is_dataclass(value) or isinstance(value, type):
        raise TypeError("M11 records must be dataclass instances")
    return _json_mapping(asdict(value))


def _json_mapping(value: Mapping[str, object]) -> dict[str, JsonValue]:
    return {str(key): _json_value(item) for key, item in value.items()}


def _json_value(value: object) -> JsonValue:
    if isinstance(value, StrEnum):
        return value.value
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return _json_mapping(value)
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return _json_mapping(asdict(value))
    raise TypeError(f"unsupported M11 JSON value: {type(value).__name__}")
