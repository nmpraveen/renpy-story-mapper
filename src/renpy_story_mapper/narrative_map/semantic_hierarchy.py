"""Deterministic validation and compilation for M15.1 whole-scope Stage H.

Stage H output is an editorial proposal, never authority.  This module proves that a proposal is
an exact, ownership-safe partition of the supplied fine-unit authority before it derives any
stable identity or translates membership into the adjacent-gap vocabulary consumed by the
existing semantic outline assembler.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from renpy_story_mapper.canonical_graph_contract import CanonicalGraph
from renpy_story_mapper.m11_scene_model import SceneModel
from renpy_story_mapper.narrative_map.adapters import ordered_unique
from renpy_story_mapper.narrative_map.assembly import (
    assemble_semantic_outline,
    assemble_semantic_outline_from_authority,
)
from renpy_story_mapper.narrative_map.contracts import AuthorityBinding
from renpy_story_mapper.narrative_map.corridors import (
    build_all_eligible_gap_candidates,
    build_fine_narrative_units,
)
from renpy_story_mapper.narrative_map.semantic_contracts import (
    ChoiceComposition,
    FineNarrativeUnit,
    NarrativeGapCandidate,
    ProposedBeatGroup,
    ProposedMajorCluster,
    SemanticBoundaryDecision,
    SemanticBoundaryKind,
    SemanticOutline,
    WholeScopeHierarchyProposal,
)

_VALIDATION_SEAL = object()


class HierarchyHardLockKind(StrEnum):
    """Supported Python-owned constraints supplied beside the Stage H prompt.

    Structural sequence, lane, call, loop, choice, and arm ownership is always checked from the
    typed authority.  Explicit locks add assertions that are not completely represented by a gap,
    such as an isolated scope marker or a required editorial boundary.
    """

    CHOICE_OWNERSHIP = "choice_ownership"
    SCOPE_MARKER = "scope_marker"
    TERMINAL = "terminal"
    UNRESOLVED = "unresolved"
    CHAPTER_DAY = "chapter_day"
    SEQUENCE = "sequence"
    LANE = "lane"
    CALL_OCCURRENCE = "call_occurrence"
    LOOP = "loop"
    SPLIT = "split"
    ARM = "arm"
    PROVEN_REJOIN = "proven_rejoin"
    BEAT_BOUNDARY = "beat_boundary"
    MAJOR_CLUSTER_BOUNDARY = "major_cluster_boundary"
    SEPARATE_BEAT = "separate_beat"
    SEPARATE_MAJOR_CLUSTER = "separate_major_cluster"


@dataclass(frozen=True)
class HierarchyHardLock:
    lock_id: str
    kind: HierarchyHardLockKind
    unit_ids: tuple[str, ...] = ()
    left_unit_id: str | None = None
    right_unit_id: str | None = None
    choice_id: str | None = None
    arm_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.lock_id, "hierarchy hard-lock ID")
        if not isinstance(self.kind, HierarchyHardLockKind):
            raise ValueError("hierarchy hard-lock kind is unsupported")
        _require_unique(self.unit_ids, "hierarchy hard-lock unit ID")
        _require_unique(self.arm_ids, "hierarchy hard-lock arm ID")
        for value, label in (
            (self.left_unit_id, "hierarchy hard-lock left unit ID"),
            (self.right_unit_id, "hierarchy hard-lock right unit ID"),
            (self.choice_id, "hierarchy hard-lock choice ID"),
        ):
            if value is not None:
                _require_text(value, label)
        if self.kind is HierarchyHardLockKind.CHOICE_OWNERSHIP:
            if self.choice_id is None or not self.arm_ids:
                raise ValueError("choice-ownership hard lock requires a choice and ordered arms")
            if self.unit_ids or self.left_unit_id is not None or self.right_unit_id is not None:
                raise ValueError("choice-ownership hard lock has incompatible fields")
        elif self.kind in {
            HierarchyHardLockKind.SCOPE_MARKER,
            HierarchyHardLockKind.TERMINAL,
            HierarchyHardLockKind.UNRESOLVED,
        }:
            if not self.unit_ids:
                raise ValueError("isolating hard lock requires at least one unit ID")
            if (
                self.left_unit_id is not None
                or self.right_unit_id is not None
                or self.choice_id is not None
                or self.arm_ids
            ):
                raise ValueError("isolating hard lock has incompatible fields")
        else:
            if self.left_unit_id is None or self.right_unit_id is None:
                raise ValueError("boundary hard lock requires left and right unit IDs")
            if self.left_unit_id == self.right_unit_id:
                raise ValueError("boundary hard lock requires two distinct unit IDs")
            if self.unit_ids or self.choice_id is not None or self.arm_ids:
                raise ValueError("boundary hard lock has incompatible fields")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> HierarchyHardLock:
        """Parse the strict generalized-fixture representation without accepting extra facts."""

        allowed = {
            "lock_id",
            "kind",
            "unit_ids",
            "left_unit_id",
            "right_unit_id",
            "choice_id",
            "arm_ids",
        }
        if set(value) - allowed:
            raise ValueError("hierarchy hard lock contains unsupported fields")
        lock_id = value.get("lock_id")
        kind_value = value.get("kind")
        if not isinstance(lock_id, str) or not isinstance(kind_value, str):
            raise ValueError("hierarchy hard lock identity is malformed")
        try:
            kind = HierarchyHardLockKind(kind_value)
        except ValueError as exc:
            raise ValueError("hierarchy hard-lock kind is unsupported") from exc
        return cls(
            lock_id=lock_id,
            kind=kind,
            unit_ids=_mapping_strings(value.get("unit_ids", ()), "hard-lock unit IDs"),
            left_unit_id=_mapping_optional_text(value.get("left_unit_id"), "left unit ID"),
            right_unit_id=_mapping_optional_text(value.get("right_unit_id"), "right unit ID"),
            choice_id=_mapping_optional_text(value.get("choice_id"), "choice ID"),
            arm_ids=_mapping_strings(value.get("arm_ids", ()), "hard-lock arm IDs"),
        )


@dataclass(frozen=True)
class ValidatedWholeScopeHierarchy:
    """A complete proposal that has passed every deterministic Track A constraint."""

    scope_id: str
    authority: AuthorityBinding
    units: tuple[FineNarrativeUnit, ...]
    candidates: tuple[NarrativeGapCandidate, ...]
    choices: tuple[ChoiceComposition, ...]
    hard_locks: tuple[HierarchyHardLock, ...]
    beat_groups: tuple[ProposedBeatGroup, ...]
    major_clusters: tuple[ProposedMajorCluster, ...]
    _validation_seal: object = field(repr=False, compare=False)

    @property
    def ordered_unit_ids(self) -> tuple[str, ...]:
        return tuple(item.unit_id for item in self.units)

    @property
    def ordered_candidate_ids(self) -> tuple[str, ...]:
        return tuple(item.candidate_id for item in self.candidates)


@dataclass(frozen=True)
class DerivedHierarchyIds:
    """Stable Python-owned identities keyed by transport-local proposal keys."""

    beat_ids: tuple[tuple[str, str], ...]
    cluster_ids: tuple[tuple[str, str], ...]

    def beat_id_for(self, proposal_key: str) -> str:
        return _lookup_id(self.beat_ids, proposal_key, "beat")

    def cluster_id_for(self, proposal_key: str) -> str:
        return _lookup_id(self.cluster_ids, proposal_key, "cluster")


def validate_whole_scope_hierarchy(
    proposal: WholeScopeHierarchyProposal,
    units: Sequence[FineNarrativeUnit],
    candidates: Sequence[NarrativeGapCandidate],
    choices: Sequence[ChoiceComposition] = (),
    hard_locks: Sequence[HierarchyHardLock | Mapping[str, object]] = (),
    *,
    scope_id: str | None = None,
    authority: AuthorityBinding | None = None,
    _defer_choice_authority: bool = False,
) -> ValidatedWholeScopeHierarchy:
    """Validate exact Stage H identity, coverage, order, ownership, and hard locks.

    Invalid or uncertain proposals raise ``ValueError`` and produce no partially trusted result.
    ``scope_id`` and ``authority`` let the caller bind validation to the exact prepared manifest;
    when omitted they are inferred from the supplied typed authority for focused deterministic use.
    """

    if not isinstance(proposal, WholeScopeHierarchyProposal):
        raise ValueError("whole-scope hierarchy proposal contract is invalid")
    materialized_units = tuple(units)
    materialized_candidates = tuple(candidates)
    materialized_choices = tuple(choices)
    materialized_locks = tuple(_normalize_lock(item) for item in hard_locks)
    if not materialized_units:
        raise ValueError("whole-scope hierarchy requires fine narrative units")

    expected_scope_id = proposal.scope_id if scope_id is None else scope_id
    _require_text(expected_scope_id, "whole-scope hierarchy expected scope ID")
    if proposal.scope_id != expected_scope_id:
        raise ValueError("whole-scope hierarchy has foreign or stale scope identity")

    exact_authority = materialized_units[0].authority
    if authority is not None and authority != exact_authority:
        raise ValueError("whole-scope hierarchy units have foreign or stale authority")
    unit_ids = tuple(item.unit_id for item in materialized_units)
    if len(unit_ids) != len(set(unit_ids)):
        raise ValueError("whole-scope hierarchy contains duplicate fine-unit identity")
    if any(item.authority != exact_authority for item in materialized_units):
        raise ValueError("whole-scope hierarchy units have mixed authority")

    expected_candidates = build_all_eligible_gap_candidates(materialized_units)
    if materialized_candidates != expected_candidates:
        raise ValueError(
            "whole-scope hierarchy requires the exact exhaustive adjacent-gap authority"
        )
    if any(item.authority != exact_authority for item in materialized_candidates):
        raise ValueError("whole-scope hierarchy candidates have mixed authority")

    if _defer_choice_authority:
        if materialized_choices:
            raise ValueError("deferred choice authority cannot accept supplied choices")
    else:
        _validate_choices(materialized_choices, materialized_units)
    _validate_temporary_keys(
        proposal,
        materialized_units,
        materialized_candidates,
        materialized_choices,
        materialized_locks,
    )

    proposed_unit_ids = tuple(
        unit_id for group in proposal.beat_groups for unit_id in group.ordered_unit_ids
    )
    if len(proposed_unit_ids) != len(set(proposed_unit_ids)):
        raise ValueError("whole-scope hierarchy duplicates fine-unit membership")
    known_unit_ids = set(unit_ids)
    foreign = tuple(item for item in proposed_unit_ids if item not in known_unit_ids)
    if foreign:
        raise ValueError("whole-scope hierarchy references foreign fine-unit identity")

    unit_by_id = {item.unit_id: item for item in materialized_units}
    sequence_positions: dict[str, dict[str, int]] = {}
    for unit in materialized_units:
        positions = sequence_positions.setdefault(unit.sequence_id, {})
        positions[unit.unit_id] = len(positions)
    for group in proposal.beat_groups:
        owned_units = tuple(unit_by_id[item] for item in group.ordered_unit_ids)
        ownership = {_unit_ownership(item) for item in owned_units}
        if len(ownership) != 1:
            raise ValueError("whole-scope beat crosses sequence or deterministic ownership")
        positions = sequence_positions[owned_units[0].sequence_id]
        actual = [positions[item.unit_id] for item in owned_units]
        if actual != list(range(actual[0], actual[0] + len(actual))):
            raise ValueError(
                "whole-scope beat membership is noncontiguous or reordered within its sequence"
            )

    if proposed_unit_ids != unit_ids:
        missing = known_unit_ids - set(proposed_unit_ids)
        if missing:
            raise ValueError("whole-scope hierarchy is missing required fine-unit coverage")
        raise ValueError("whole-scope hierarchy reorders deterministic fine-unit authority")

    if proposal.uncertain_unit_ids:
        if any(item not in known_unit_ids for item in proposal.uncertain_unit_ids):
            raise ValueError(
                "whole-scope hierarchy uncertainty references foreign fine-unit identity"
            )
        raise ValueError("whole-scope hierarchy uncertainty fails closed")

    validated = ValidatedWholeScopeHierarchy(
        scope_id=expected_scope_id,
        authority=exact_authority,
        units=materialized_units,
        candidates=materialized_candidates,
        choices=materialized_choices,
        hard_locks=materialized_locks,
        beat_groups=proposal.beat_groups,
        major_clusters=proposal.major_clusters,
        _validation_seal=_VALIDATION_SEAL,
    )
    _validate_hard_locks(validated, defer_choice_authority=_defer_choice_authority)
    _assemble_exact_outline(validated)
    return validated


def validate_whole_scope_hierarchy_from_authority(
    canonical: CanonicalGraph,
    scene_model: SceneModel,
    proposal: WholeScopeHierarchyProposal,
    hard_locks: Sequence[HierarchyHardLock | Mapping[str, object]] = (),
    *,
    scope_id: str | None = None,
    authority: AuthorityBinding | None = None,
) -> ValidatedWholeScopeHierarchy:
    """Bind one Stage H proposal to the current M10/M11 assembly, including choices."""

    units = build_fine_narrative_units(canonical, scene_model)
    candidates = build_all_eligible_gap_candidates(units)
    normalized_locks = tuple(_normalize_lock(item) for item in hard_locks)
    preliminary = validate_whole_scope_hierarchy(
        proposal,
        units,
        candidates,
        tuple(),
        tuple(
            item
            for item in normalized_locks
            if item.kind is not HierarchyHardLockKind.CHOICE_OWNERSHIP
        ),
        scope_id=scope_id,
        authority=authority,
        _defer_choice_authority=True,
    )
    decisions = compile_hierarchy_to_gap_decisions(preliminary)
    exact_units, exact_candidates, outline = assemble_semantic_outline_from_authority(
        canonical,
        scene_model,
        decisions,
    )
    if exact_units != units or exact_candidates != candidates:
        raise ValueError("current hierarchy authority changed during deterministic assembly")
    return validate_whole_scope_hierarchy(
        proposal,
        exact_units,
        exact_candidates,
        outline.choices,
        normalized_locks,
        scope_id=scope_id,
        authority=authority,
    )


def compile_hierarchy_to_gap_decisions(
    hierarchy: ValidatedWholeScopeHierarchy,
) -> tuple[SemanticBoundaryDecision, ...]:
    """Compile every eligible gap into the existing exhaustive decision vocabulary."""

    _require_validated(hierarchy, "hierarchy compilation")
    beat_by_unit = {
        unit_id: group
        for group in hierarchy.beat_groups
        for unit_id in group.ordered_unit_ids
    }
    cluster_by_beat = {
        beat_key: cluster
        for cluster in hierarchy.major_clusters
        for beat_key in cluster.ordered_beat_keys
    }
    decisions: list[SemanticBoundaryDecision] = []
    for candidate in hierarchy.candidates:
        left_beat = beat_by_unit[candidate.left_unit_id]
        right_beat = beat_by_unit[candidate.right_unit_id]
        left_cluster = cluster_by_beat[left_beat.proposal_key]
        right_cluster = cluster_by_beat[right_beat.proposal_key]
        if left_beat.proposal_key == right_beat.proposal_key:
            kind = SemanticBoundaryKind.SAME_BEAT
            confidence = left_beat.confidence
            sources: tuple[ProposedBeatGroup | ProposedMajorCluster, ...] = (left_beat,)
            reason = "Validated Stage H membership keeps this adjacent gap inside one beat."
        elif left_cluster.proposal_key == right_cluster.proposal_key:
            kind = SemanticBoundaryKind.NEW_BEAT_SAME_CLUSTER
            confidence = min(left_beat.confidence, right_beat.confidence, left_cluster.confidence)
            sources = (left_beat, right_beat, left_cluster)
            reason = "Validated Stage H membership starts a new beat inside the same major cluster."
        else:
            kind = SemanticBoundaryKind.NEW_MAJOR_CLUSTER
            confidence = min(
                left_beat.confidence,
                right_beat.confidence,
                left_cluster.confidence,
                right_cluster.confidence,
            )
            sources = (left_beat, right_beat, left_cluster, right_cluster)
            reason = "Validated Stage H membership starts a new major cluster."
        decisions.append(
            SemanticBoundaryDecision(
                candidate_id=candidate.candidate_id,
                decision=kind,
                reason=reason,
                confidence=confidence,
                warnings=ordered_unique(
                    warning for source in sources for warning in source.warnings
                ),
            )
        )
    return tuple(decisions)


def derive_stable_hierarchy_ids(
    hierarchy: ValidatedWholeScopeHierarchy,
) -> DerivedHierarchyIds:
    """Return the stable identities published by the sole existing assembler.

    Proposal keys are lookup handles only.  Identity derivation is deliberately not duplicated
    here: the validated adjacent decisions are assembled and the resulting exact beat/cluster IDs
    are returned in proposal order.
    """

    _require_validated(hierarchy, "stable hierarchy IDs")
    outline = _assemble_exact_outline(hierarchy)
    beat_ids = tuple(
        (proposal.proposal_key, assembled.beat_id)
        for proposal, assembled in zip(hierarchy.beat_groups, outline.beats, strict=True)
    )
    cluster_ids = tuple(
        (proposal.proposal_key, assembled.cluster_id)
        for proposal, assembled in zip(
            hierarchy.major_clusters, outline.clusters, strict=True
        )
    )
    return DerivedHierarchyIds(beat_ids, cluster_ids)


def _assemble_exact_outline(hierarchy: ValidatedWholeScopeHierarchy) -> SemanticOutline:
    """Prove the compiled proposal round-trips through the sole assembly implementation."""

    try:
        outline = assemble_semantic_outline(
            hierarchy.units,
            hierarchy.candidates,
            compile_hierarchy_to_gap_decisions(hierarchy),
            choices=hierarchy.choices,
        )
    except ValueError as exc:
        raise ValueError(
            "whole-scope hierarchy is not representable by the existing assembler"
        ) from exc
    if not isinstance(outline, SemanticOutline):  # pragma: no cover - typed overload guarantee
        raise AssertionError("typed semantic outline assembly returned a serialized fixture")

    proposed_beats = tuple(item.ordered_unit_ids for item in hierarchy.beat_groups)
    assembled_beats = tuple(item.ordered_unit_ids for item in outline.beats)
    if assembled_beats != proposed_beats:
        raise ValueError(
            "whole-scope hierarchy beat membership is not representable by the existing assembler"
        )

    proposal_beat_by_key = {
        item.proposal_key: item.ordered_unit_ids for item in hierarchy.beat_groups
    }
    proposed_clusters = tuple(
        tuple(proposal_beat_by_key[beat_key] for beat_key in cluster.ordered_beat_keys)
        for cluster in hierarchy.major_clusters
    )
    assembled_beat_by_id = {item.beat_id: item.ordered_unit_ids for item in outline.beats}
    assembled_clusters = tuple(
        tuple(assembled_beat_by_id[beat_id] for beat_id in cluster.ordered_beat_ids)
        for cluster in outline.clusters
    )
    if assembled_clusters != proposed_clusters:
        raise ValueError(
            "whole-scope hierarchy cluster membership is not representable by the existing "
            "assembler"
        )
    return outline


def _validate_temporary_keys(
    proposal: WholeScopeHierarchyProposal,
    units: Sequence[FineNarrativeUnit],
    candidates: Sequence[NarrativeGapCandidate],
    choices: Sequence[ChoiceComposition],
    hard_locks: Sequence[HierarchyHardLock],
) -> None:
    beat_keys = tuple(item.proposal_key for item in proposal.beat_groups)
    cluster_keys = tuple(item.proposal_key for item in proposal.major_clusters)
    if set(beat_keys).intersection(cluster_keys):
        raise ValueError("beat and cluster temporary proposal keys must use separate identity")
    authority_ids = {
        *(item.unit_id for item in units),
        *(item.candidate_id for item in candidates),
        *(item.choice_id for item in choices),
        *(arm_id for item in choices for arm_id in item.ordered_arm_ids),
        *(item.lock_id for item in hard_locks),
    }
    for key in (*beat_keys, *cluster_keys):
        if key in authority_ids:
            raise ValueError("temporary proposal key collides with authoritative identity")


def _validate_choices(
    choices: Sequence[ChoiceComposition],
    units: Sequence[FineNarrativeUnit],
) -> None:
    choice_by_id = {item.choice_id: item for item in choices}
    unit_ids = {item.unit_id for item in units}
    if len(choice_by_id) != len(choices):
        raise ValueError("whole-scope hierarchy contains duplicate choice authority")
    for choice in choices:
        for child_id in choice.child_choice_ids:
            child = choice_by_id.get(child_id)
            if child is None or child.parent_choice_id != choice.choice_id:
                raise ValueError("whole-scope hierarchy has inconsistent child choice authority")
        if choice.parent_choice_id is not None:
            parent = choice_by_id.get(choice.parent_choice_id)
            if (
                parent is None
                or choice.choice_id not in parent.child_choice_ids
                or choice.parent_arm_id not in parent.ordered_arm_ids
            ):
                raise ValueError("whole-scope hierarchy has inconsistent nested choice authority")
        if (
            choice.post_rejoin_continuation_id is not None
            and choice.post_rejoin_continuation_id not in unit_ids
        ):
            raise ValueError("whole-scope hierarchy choice continuation is foreign")
    for choice in choices:
        seen: set[str] = set()
        cursor: ChoiceComposition | None = choice
        while cursor is not None:
            if cursor.choice_id in seen:
                raise ValueError("whole-scope hierarchy choice ownership contains a cycle")
            seen.add(cursor.choice_id)
            cursor = (
                choice_by_id.get(cursor.parent_choice_id)
                if cursor.parent_choice_id is not None
                else None
            )
    for unit in units:
        if unit.parent_choice_id is None:
            continue
        owner = choice_by_id.get(unit.parent_choice_id)
        if owner is None:
            raise ValueError("whole-scope hierarchy unit references missing choice authority")
        if unit.parent_arm_id not in owner.ordered_arm_ids:
            raise ValueError("whole-scope hierarchy unit references foreign choice-arm authority")


def _validate_hard_locks(
    hierarchy: ValidatedWholeScopeHierarchy,
    *,
    defer_choice_authority: bool = False,
) -> None:
    unit_ids = set(hierarchy.ordered_unit_ids)
    choice_by_id = {item.choice_id: item for item in hierarchy.choices}
    beat_by_unit = {
        unit_id: group.proposal_key
        for group in hierarchy.beat_groups
        for unit_id in group.ordered_unit_ids
    }
    cluster_by_beat = {
        beat_key: cluster.proposal_key
        for cluster in hierarchy.major_clusters
        for beat_key in cluster.ordered_beat_keys
    }
    seen_lock_ids: set[str] = set()
    for lock in hierarchy.hard_locks:
        if lock.lock_id in seen_lock_ids:
            raise ValueError("whole-scope hierarchy contains duplicate hard-lock identity")
        seen_lock_ids.add(lock.lock_id)
        referenced_units = {
            *lock.unit_ids,
            *(item for item in (lock.left_unit_id, lock.right_unit_id) if item is not None),
        }
        if not referenced_units <= unit_ids:
            raise ValueError("whole-scope hard lock references foreign fine-unit identity")
        if lock.kind is HierarchyHardLockKind.CHOICE_OWNERSHIP:
            if defer_choice_authority:
                continue
            assert lock.choice_id is not None
            choice = choice_by_id.get(lock.choice_id)
            if choice is None or choice.ordered_arm_ids != lock.arm_ids:
                raise ValueError("whole-scope hierarchy violates choice-ownership hard lock")
        elif lock.kind in {
            HierarchyHardLockKind.SCOPE_MARKER,
            HierarchyHardLockKind.TERMINAL,
            HierarchyHardLockKind.UNRESOLVED,
        }:
            if any(
                len(
                    next(
                        group.ordered_unit_ids
                        for group in hierarchy.beat_groups
                        if unit_id in group.ordered_unit_ids
                    )
                )
                != 1
                for unit_id in lock.unit_ids
            ):
                raise ValueError("whole-scope hierarchy crosses an isolating hard lock")
        else:
            assert lock.left_unit_id is not None and lock.right_unit_id is not None
            left_beat = beat_by_unit[lock.left_unit_id]
            right_beat = beat_by_unit[lock.right_unit_id]
            if left_beat == right_beat:
                raise ValueError("whole-scope hierarchy crosses a required beat hard lock")
            if (
                lock.kind
                in {
                    HierarchyHardLockKind.MAJOR_CLUSTER_BOUNDARY,
                    HierarchyHardLockKind.SEPARATE_MAJOR_CLUSTER,
                }
                and cluster_by_beat[left_beat] == cluster_by_beat[right_beat]
            ):
                raise ValueError("whole-scope hierarchy crosses a required major-cluster hard lock")


def _unit_ownership(unit: FineNarrativeUnit) -> tuple[object, ...]:
    return (
        unit.sequence_id,
        unit.lane_id,
        unit.call_occurrence_id,
        unit.call_occurrence_path,
        unit.call_site_path,
        unit.loop_id,
        unit.parent_choice_id,
        unit.parent_arm_id,
    )


def _normalize_lock(
    value: HierarchyHardLock | Mapping[str, object],
) -> HierarchyHardLock:
    if isinstance(value, HierarchyHardLock):
        return value
    if isinstance(value, Mapping):
        return HierarchyHardLock.from_mapping(value)
    raise ValueError("whole-scope hierarchy hard-lock contract is invalid")


def _lookup_id(values: tuple[tuple[str, str], ...], key: str, label: str) -> str:
    for proposal_key, stable_id in values:
        if proposal_key == key:
            return stable_id
    raise KeyError(f"unknown {label} proposal key: {key}")


def _require_validated(hierarchy: object, operation: str) -> None:
    if (
        not isinstance(hierarchy, ValidatedWholeScopeHierarchy)
        or hierarchy._validation_seal is not _VALIDATION_SEAL
    ):
        raise ValueError(f"{operation} requires a validated whole-scope hierarchy")


def _require_text(value: str, label: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{label} must be a non-empty trimmed string")


def _require_unique(values: tuple[str, ...], label: str) -> None:
    for value in values:
        _require_text(value, label)
    if len(values) != len(set(values)):
        raise ValueError(f"{label} values must be unique")


def _mapping_strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes) or not all(
        isinstance(item, str) for item in value
    ):
        raise ValueError(f"{label} must be an array of strings")
    return tuple(value)


def _mapping_optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string or null")
    return value
