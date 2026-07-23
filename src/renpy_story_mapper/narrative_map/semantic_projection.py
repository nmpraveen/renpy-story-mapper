"""Transient M15.1 provider projection over frozen Track A semantic contracts."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import cast

from renpy_story_mapper.canonical_graph_contract import CanonicalGraph
from renpy_story_mapper.m11_scene_model import AtomKind, SceneModel
from renpy_story_mapper.narrative_map.assembly import semantic_membership_hash
from renpy_story_mapper.narrative_map.contracts import (
    JsonValue,
    SourceLocator,
    canonical_hash,
    stable_m15_id,
)
from renpy_story_mapper.narrative_map.projection import (
    SemanticQuotientTopology,
    SemanticTopologyEdge,
)
from renpy_story_mapper.narrative_map.provider import (
    SEMANTIC_BOUNDARY_PROMPT_VERSION,
    SEMANTIC_BOUNDARY_RESPONSE_SCHEMA,
    SEMANTIC_SUMMARY_PROMPT_VERSION,
    SEMANTIC_SUMMARY_RESPONSE_SCHEMA,
    PreparedNarrativeJob,
    ProviderJobKind,
)
from renpy_story_mapper.narrative_map.semantic_contracts import (
    BoundaryWindow,
    ChoiceComposition,
    FineNarrativeUnit,
    MajorCluster,
    NarrativeGapCandidate,
    SemanticBeat,
    SemanticOutline,
    SemanticPresentationRole,
    SemanticSummary,
    WholeScopeEditorialBatch,
)

MAXIMUM_OWNED_GAPS_PER_WINDOW = 8
MAXIMUM_CONTEXT_UNITS_PER_WINDOW = 16
MAXIMUM_COMPACT_WHOLE_SCOPE_ROWS = 32

_STORY_CONTENT_ATOM_KINDS = frozenset(
    {
        AtomKind.DIALOGUE,
        AtomKind.NARRATION,
        AtomKind.VISUAL_CHANGE,
        AtomKind.CALL,
        AtomKind.LOOP,
        AtomKind.TERMINAL,
        AtomKind.UNRESOLVED,
    }
)
SEMANTIC_SUMMARY_INPUT_SCHEMA = "m15-semantic-summary-input-v3"


@dataclass(frozen=True)
class SemanticEvidenceRecord:
    """One transient story-facing evidence record; text is never durable job metadata."""

    unit_id: str
    atom_id: str
    evidence_id: str
    ordinal: int
    kind: str
    text: str
    speaker: str | None
    locator: SourceLocator

    def __post_init__(self) -> None:
        for value, label in (
            (self.unit_id, "semantic evidence unit ID"),
            (self.atom_id, "semantic evidence atom ID"),
            (self.evidence_id, "semantic evidence ID"),
            (self.kind, "semantic evidence kind"),
            (self.text, "semantic evidence text"),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{label} must be a non-empty trimmed string")
        if self.ordinal < 0:
            raise ValueError("semantic evidence ordinal cannot be negative")
        if self.speaker is not None and (not self.speaker or self.speaker != self.speaker.strip()):
            raise ValueError("semantic evidence speaker must be trimmed")

    def to_prompt_dict(self) -> dict[str, JsonValue]:
        return {
            "unit_id": self.unit_id,
            "atom_id": self.atom_id,
            "evidence_id": self.evidence_id,
            "ordinal": self.ordinal,
            "kind": self.kind,
            "text": self.text,
            "speaker": self.speaker,
            "locator": self.locator.to_dict(),
        }


@dataclass(frozen=True)
class FrozenSummaryInput:
    """Track A membership plus transient evidence for one required visible summary."""

    subject_kind: str
    subject_id: str
    ordered_unit_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    known_characters: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.subject_kind not in {"beat", "major_cluster", "choice"}:
            raise ValueError("summary input subject kind is unsupported")
        if not self.subject_id or self.subject_id != self.subject_id.strip():
            raise ValueError("summary input subject ID must be non-empty and trimmed")
        _unique(self.ordered_unit_ids, "summary input unit ID", allow_empty=False)
        _unique(self.evidence_ids, "summary input evidence ID", allow_empty=False)
        _unique(self.known_characters, "summary input character")


@dataclass(frozen=True)
class CompactWholeScopeProjection:
    """One bounded, role-filtered normal-flow projection of frozen whole-scope work."""

    nodes: tuple[dict[str, object], ...]
    edges: tuple[SemanticTopologyEdge, ...]
    omitted_subject_ids: tuple[str, ...]
    partial_subject_ids: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def visible_row_count(self) -> int:
        return len(self.nodes)


def prepare_semantic_boundary_jobs(
    units: Sequence[FineNarrativeUnit],
    candidates: Sequence[NarrativeGapCandidate],
    windows: Sequence[BoundaryWindow],
    evidence_by_unit: Mapping[str, Sequence[SemanticEvidenceRecord]],
    *,
    source_hash: str,
    correction_id: str,
    privacy_scope: str,
) -> tuple[PreparedNarrativeJob, ...]:
    """Project exhaustive adjacent gaps into bounded multi-candidate windows."""

    _text(source_hash, "semantic source hash")
    _text(correction_id, "semantic correction ID")
    _text(privacy_scope, "semantic privacy scope")
    if not units:
        if candidates or windows:
            raise ValueError("semantic boundary inputs require fine narrative units")
        return ()
    unit_ids = tuple(unit.unit_id for unit in units)
    _unique(unit_ids, "fine-unit ID", allow_empty=False)
    unit_by_id = dict(zip(unit_ids, units, strict=True))
    authority = units[0].authority
    if any(unit.authority != authority for unit in units):
        raise ValueError("semantic boundary units must share exact authority")

    candidate_ids = tuple(candidate.candidate_id for candidate in candidates)
    _unique(candidate_ids, "narrative gap ID")
    candidate_by_id = dict(zip(candidate_ids, candidates, strict=True))
    adjacent_pairs = {(left.unit_id, right.unit_id) for left, right in pairwise(units)}
    for candidate in candidates:
        if candidate.authority != authority:
            raise ValueError("semantic gap authority does not match its units")
        if (candidate.left_unit_id, candidate.right_unit_id) not in adjacent_pairs:
            raise ValueError("every semantic gap must reference exact adjacent units")
        left = unit_by_id[candidate.left_unit_id]
        right = unit_by_id[candidate.right_unit_id]
        context = (
            candidate.sequence_id,
            candidate.lane_id,
            candidate.call_occurrence_id,
            candidate.loop_id,
            candidate.parent_choice_id,
            candidate.parent_arm_id,
        )
        if context != _unit_context(left) or context != _unit_context(right):
            raise ValueError("semantic gaps cannot cross frozen structural ownership")

    owned_ids: list[str] = []
    jobs: list[PreparedNarrativeJob] = []
    positions = {unit_id: index for index, unit_id in enumerate(unit_ids)}
    for window in windows:
        if window.authority != authority:
            raise ValueError("boundary window authority does not match its units")
        if not 1 <= len(window.owned_candidate_ids) <= MAXIMUM_OWNED_GAPS_PER_WINDOW:
            raise ValueError("boundary window owned-candidate count exceeds its bound")
        if len(window.context_unit_ids) > MAXIMUM_CONTEXT_UNITS_PER_WINDOW:
            raise ValueError("boundary window context exceeds the production bound")
        if any(unit_id not in unit_by_id for unit_id in window.context_unit_ids):
            raise ValueError("boundary window references an unknown context unit")
        context_positions = tuple(positions[unit_id] for unit_id in window.context_unit_ids)
        if context_positions and context_positions != tuple(
            range(context_positions[0], context_positions[0] + len(context_positions))
        ):
            raise ValueError("boundary window context must be contiguous and ordered")
        window_candidates: list[NarrativeGapCandidate] = []
        for candidate_id in window.owned_candidate_ids:
            window_candidate = candidate_by_id.get(candidate_id)
            if window_candidate is None:
                raise ValueError("boundary window owns an unknown narrative gap")
            if (
                window_candidate.left_unit_id not in window.context_unit_ids
                or window_candidate.right_unit_id not in window.context_unit_ids
            ):
                raise ValueError("boundary window context must contain each owned gap")
            window_candidates.append(window_candidate)
        owned_ids.extend(window.owned_candidate_ids)
        evidence = _ordered_evidence(window.context_unit_ids, evidence_by_unit)
        evidence_ids = tuple(item.evidence_id for item in evidence)
        if any(
            not set(candidate.evidence_ids).issubset(evidence_ids)
            for candidate in window_candidates
        ):
            raise ValueError("owned gap evidence must exist in its boundary window")
        payload: dict[str, JsonValue] = {
            "window_id": window.window_id,
            "owned_candidates": [candidate.to_dict() for candidate in window_candidates],
            "context_units": [unit_by_id[item].to_dict() for item in window.context_unit_ids],
            "evidence": [item.to_prompt_dict() for item in evidence],
            "allowed_decisions": [
                "same_beat",
                "new_beat_same_cluster",
                "new_major_cluster",
                "uncertain",
            ],
        }
        jobs.append(
            PreparedNarrativeJob(
                kind=ProviderJobKind.SEMANTIC_BOUNDARY_WINDOW,
                authority=authority,
                subject=window,
                subject_id=window.window_id,
                input_hash=canonical_hash(payload),
                prompt_version=SEMANTIC_BOUNDARY_PROMPT_VERSION,
                response_schema=SEMANTIC_BOUNDARY_RESPONSE_SCHEMA,
                payload=payload,
                known_evidence_ids=evidence_ids,
                source_hash=source_hash,
                correction_id=correction_id,
                privacy_scope=privacy_scope,
            )
        )
    if tuple(owned_ids) != candidate_ids or len(owned_ids) != len(set(owned_ids)):
        raise ValueError("boundary windows must own every eligible gap exactly once in order")
    return tuple(jobs)


def prepare_semantic_summary_jobs(
    outline: SemanticOutline,
    inputs: Sequence[FrozenSummaryInput],
    evidence_by_unit: Mapping[str, Sequence[SemanticEvidenceRecord]],
    *,
    source_hash: str,
    correction_id: str,
    privacy_scope: str,
) -> tuple[PreparedNarrativeJob, ...]:
    """Create one independent job for every frozen visible semantic subject."""

    membership_hash = semantic_outline_hash(outline)
    subjects: dict[tuple[str, str], SemanticBeat | MajorCluster | ChoiceComposition] = {
        **{("beat", item.beat_id): item for item in outline.beats},
        **{("major_cluster", item.cluster_id): item for item in outline.clusters},
        **{("choice", item.choice_id): item for item in outline.choices},
    }
    expected = tuple(subjects)
    supplied = tuple((item.subject_kind, item.subject_id) for item in inputs)
    if supplied != expected or len(supplied) != len(set(supplied)):
        raise ValueError("summary inputs must cover every frozen visible subject exactly once")
    beats_by_id = {item.beat_id: item for item in outline.beats}
    clusters_by_id = {item.cluster_id: item for item in outline.clusters}
    choices_by_id = {item.choice_id: item for item in outline.choices}

    def cluster_units(cluster: MajorCluster) -> tuple[str, ...]:
        if any(beat_id not in beats_by_id for beat_id in cluster.ordered_beat_ids):
            raise ValueError("major cluster references an unknown frozen beat")
        ordered = tuple(
            unit_id
            for beat_id in cluster.ordered_beat_ids
            for unit_id in beats_by_id[beat_id].ordered_unit_ids
        )
        if len(ordered) != len(set(ordered)):
            raise ValueError("major cluster frozen beat membership overlaps")
        return ordered

    def choice_units(choice: ChoiceComposition) -> tuple[str, ...]:
        owned_choice_ids: set[str] = set()
        visiting: set[str] = set()

        def collect(choice_id: str) -> None:
            if choice_id in visiting:
                raise ValueError("choice summary membership contains a cycle")
            if choice_id in owned_choice_ids:
                return
            nested = choices_by_id.get(choice_id)
            if nested is None:
                raise ValueError("choice summary subject references an unknown child choice")
            visiting.add(choice_id)
            for child_id in nested.child_choice_ids:
                child = choices_by_id.get(child_id)
                if child is None or child.parent_choice_id != choice_id:
                    raise ValueError("choice summary child ownership is inconsistent")
                collect(child_id)
            visiting.remove(choice_id)
            owned_choice_ids.add(choice_id)

        collect(choice.choice_id)
        selected = {
            unit_id
            for beat in outline.beats
            if beat.parent_choice_id in owned_choice_ids
            for unit_id in beat.ordered_unit_ids
        }
        ordered = tuple(unit_id for unit_id in outline.ordered_unit_ids if unit_id in selected)
        if not ordered or len(ordered) != len(selected):
            raise ValueError("choice summary has invalid frozen beat membership")
        return ordered

    expected_units: dict[tuple[str, str], tuple[str, ...]] = {
        **{("beat", item.beat_id): item.ordered_unit_ids for item in outline.beats},
        **{
            ("major_cluster", item.cluster_id): cluster_units(item)
            for item in outline.clusters
        },
        **{
            ("choice", item.choice_id): choice_units(item)
            for item in outline.choices
            if item.parent_cluster_id in clusters_by_id
        },
    }
    if len(expected_units) != len(subjects):
        raise ValueError("choice summary subject references an unknown parent cluster")
    unit_ids = set(outline.ordered_unit_ids)
    unit_authority = _summary_unit_authority(outline)
    jobs: list[PreparedNarrativeJob] = []
    for item in inputs:
        if any(unit_id not in unit_ids for unit_id in item.ordered_unit_ids):
            raise ValueError("summary input contains a unit outside frozen membership")
        if item.ordered_unit_ids != expected_units[(item.subject_kind, item.subject_id)]:
            raise ValueError("summary input must preserve exact frozen subject membership")
        evidence = _ordered_evidence(item.ordered_unit_ids, evidence_by_unit)
        evidence_ids = tuple(record.evidence_id for record in evidence)
        if not set(item.evidence_ids).issubset(evidence_ids):
            raise ValueError("summary evidence must exist in its frozen subject input")
        subject = subjects[(item.subject_kind, item.subject_id)]
        ordered_unit_authority = [
            unit_authority[unit_id] for unit_id in item.ordered_unit_ids
        ]
        serialized_unit_authority: list[JsonValue] = list(ordered_unit_authority)
        payload: dict[str, JsonValue] = {
            "input_schema": SEMANTIC_SUMMARY_INPUT_SCHEMA,
            "subject_kind": item.subject_kind,
            "subject_id": item.subject_id,
            "membership_hash": membership_hash,
            "subject_authority": _summary_subject_authority(
                item.subject_kind,
                subject,
                clusters_by_id,
            ),
            "frozen_unit_ids": list(item.ordered_unit_ids),
            "ordered_unit_authority": serialized_unit_authority,
            "choice_authority": _summary_choice_authority(
                item.subject_kind,
                subject,
                ordered_unit_authority,
                outline.choices,
            ),
            "ending_authority": {
                "classification": "not_provided",
                "whole_story_ending_authorized": False,
                "authority_ids": [],
            },
            "allowed_evidence_ids": list(item.evidence_ids),
            "known_characters": list(item.known_characters),
            "evidence": [record.to_prompt_dict() for record in evidence],
        }
        jobs.append(
            PreparedNarrativeJob(
                kind=ProviderJobKind.SEMANTIC_SUMMARY,
                authority=outline.authority,
                subject=subjects[(item.subject_kind, item.subject_id)],
                subject_id=item.subject_id,
                input_hash=canonical_hash(payload),
                prompt_version=SEMANTIC_SUMMARY_PROMPT_VERSION,
                response_schema=SEMANTIC_SUMMARY_RESPONSE_SCHEMA,
                payload=payload,
                known_evidence_ids=item.evidence_ids,
                known_characters=item.known_characters,
                story_facing=True,
                source_hash=source_hash,
                correction_id=correction_id,
                membership_hash=membership_hash,
                privacy_scope=privacy_scope,
            )
        )
    return tuple(jobs)


def _summary_unit_authority(
    outline: SemanticOutline,
) -> dict[str, dict[str, JsonValue]]:
    choices_by_id = {item.choice_id: item for item in outline.choices}
    authority: dict[str, dict[str, JsonValue]] = {}
    for beat in outline.beats:
        arm_caption: str | None = None
        if beat.parent_choice_id is not None:
            choice = choices_by_id.get(beat.parent_choice_id)
            if choice is None or choice.parent_cluster_id != beat.parent_cluster_id:
                raise ValueError("arm-local summary beat lacks matching choice authority")
            assert beat.parent_arm_id is not None
            try:
                arm_index = choice.ordered_arm_ids.index(beat.parent_arm_id)
            except ValueError:
                raise ValueError(
                    "arm-local summary beat references an unknown choice arm"
                ) from None
            arm_caption = choice.ordered_arm_captions[arm_index]
        for unit_id in beat.ordered_unit_ids:
            if unit_id in authority:
                raise ValueError("summary unit belongs to more than one frozen beat")
            authority[unit_id] = {
                "unit_id": unit_id,
                "beat_id": beat.beat_id,
                "parent_cluster_id": beat.parent_cluster_id,
                "parent_choice_id": beat.parent_choice_id,
                "parent_arm_id": beat.parent_arm_id,
                "choice_arm_caption": arm_caption,
                "navigation": beat.navigation.to_dict(),
            }
    if set(authority) != set(outline.ordered_unit_ids):
        raise ValueError("summary unit authority must cover frozen outline membership exactly")
    return authority


def _summary_subject_authority(
    subject_kind: str,
    subject: SemanticBeat | MajorCluster | ChoiceComposition,
    clusters_by_id: Mapping[str, MajorCluster],
) -> dict[str, JsonValue]:
    if subject_kind == "beat":
        if not isinstance(subject, SemanticBeat):
            raise ValueError("summary beat subject authority is invalid")
        return {
            "subject_kind": subject_kind,
            "subject_id": subject.beat_id,
            "parent_cluster_id": subject.parent_cluster_id,
            "parent_choice_id": subject.parent_choice_id,
            "parent_arm_id": subject.parent_arm_id,
            "navigation": subject.navigation.to_dict(),
        }
    if subject_kind == "major_cluster":
        if not isinstance(subject, MajorCluster):
            raise ValueError("summary cluster subject authority is invalid")
        return {
            "subject_kind": subject_kind,
            "subject_id": subject.cluster_id,
            "ordinal": subject.ordinal,
            "ordered_beat_ids": list(subject.ordered_beat_ids),
            "ordered_choice_ids": list(subject.ordered_choice_ids),
            "navigation": subject.navigation.to_dict(),
        }
    if not isinstance(subject, ChoiceComposition):
        raise ValueError("summary choice subject authority is invalid")
    parent = clusters_by_id.get(subject.parent_cluster_id)
    if parent is None:
        raise ValueError("summary choice lacks parent-cluster navigation authority")
    return {
        "subject_kind": subject_kind,
        "subject_id": subject.choice_id,
        "parent_navigation": parent.navigation.to_dict(),
        "choice": subject.to_dict(),
    }


def _summary_choice_authority(
    subject_kind: str,
    subject: SemanticBeat | MajorCluster | ChoiceComposition,
    ordered_unit_authority: Sequence[dict[str, JsonValue]],
    choices: Sequence[ChoiceComposition],
) -> list[JsonValue]:
    choices_by_id = {item.choice_id: item for item in choices}
    relevant = {
        choice_id
        for item in ordered_unit_authority
        for choice_id in (item["parent_choice_id"],)
        if isinstance(choice_id, str)
    }
    if subject_kind == "major_cluster":
        if not isinstance(subject, MajorCluster):
            raise ValueError("summary cluster choice authority is invalid")
        relevant.update(subject.ordered_choice_ids)
    elif subject_kind == "choice":
        if not isinstance(subject, ChoiceComposition):
            raise ValueError("summary choice authority is invalid")
        relevant.add(subject.choice_id)

    pending = list(relevant)
    while pending:
        choice_id = pending.pop()
        choice = choices_by_id.get(choice_id)
        if choice is None:
            raise ValueError("summary subject references unknown choice authority")
        linked = (*choice.child_choice_ids, choice.parent_choice_id)
        for linked_id in linked:
            if linked_id is not None and linked_id not in relevant:
                relevant.add(linked_id)
                pending.append(linked_id)
    return [item.to_dict() for item in choices if item.choice_id in relevant]


def semantic_outline_payload(outline: SemanticOutline) -> dict[str, JsonValue]:
    return {
        "schema": "m15-semantic-outline-v2",
        "authority": outline.authority.to_dict(),
        "ordered_unit_ids": list(outline.ordered_unit_ids),
        "ordered_candidate_ids": list(outline.ordered_candidate_ids),
        "beats": [
            {
                "beat_id": item.beat_id,
                "parent_cluster_id": item.parent_cluster_id,
                "ordered_unit_ids": list(item.ordered_unit_ids),
                "parent_choice_id": item.parent_choice_id,
                "parent_arm_id": item.parent_arm_id,
                "navigation": item.navigation.to_dict(),
            }
            for item in outline.beats
        ],
        "clusters": [
            {
                "cluster_id": item.cluster_id,
                "ordinal": item.ordinal,
                "ordered_beat_ids": list(item.ordered_beat_ids),
                "ordered_choice_ids": list(item.ordered_choice_ids),
                "navigation": item.navigation.to_dict(),
            }
            for item in outline.clusters
        ],
        "choices": [item.to_dict() for item in outline.choices],
        "boundary_provenance": [
            {
                "candidate_id": item.candidate_id,
                "window_id": item.window_id,
                "stage": item.stage,
                "job_id": item.job_id,
                "input_hash": item.input_hash,
                "manifest_id": item.manifest_id,
                "provider_identity_hash": item.provider_identity_hash,
                "cache_identity": item.cache_identity,
            }
            for item in outline.boundary_provenance
        ],
    }


def semantic_outline_hash(outline: SemanticOutline) -> str:
    """Hash frozen membership only; live provider provenance is not membership."""

    return semantic_membership_hash(outline)


def semantic_summary_payload(summary: SemanticSummary) -> dict[str, JsonValue]:
    return {
        "schema": "m15-semantic-summary-v2",
        "subject_kind": summary.subject_kind,
        "subject_id": summary.subject_id,
        "membership_hash": summary.membership_hash,
        "title": summary.title,
        "summary": summary.summary,
        "characters": list(summary.characters),
        "claims": [
            {
                "claim_class": claim.claim_class.value,
                "text": claim.text,
                "evidence_ids": list(claim.evidence_ids),
            }
            for claim in summary.claims
        ],
        "warnings": list(summary.warnings),
    }


def project_compact_semantic_nodes(
    canonical: CanonicalGraph,
    model: SceneModel,
    units: Sequence[FineNarrativeUnit],
    outline: SemanticOutline,
    topology: SemanticQuotientTopology,
    summaries: Mapping[str, Mapping[str, object]],
    provenance: Mapping[str, Mapping[str, object]],
    *,
    presentation_roles: Mapping[str, SemanticPresentationRole] | None = None,
) -> tuple[dict[str, object], ...]:
    """Project the frozen hierarchy as compact story-facing rows in source chronology.

    Beat membership remains durable and available in Detail/Evidence, but it is not promoted as
    one equal-weight row per boundary decision. A temporary choice is visible only when every
    authoritative arm owns story content (directly or through a visible nested choice). Each
    visible arm is represented exactly once with its authoritative caption, and shared M10 merge
    targets produce one visual rejoin marker.
    """

    canonical.validate()
    materialized_units = tuple(units)
    if not materialized_units:
        raise ValueError("compact semantic projection requires fine narrative units")
    if (
        outline.authority.source_generation != canonical.source_generation
        or outline.authority.canonical_hash != canonical.authority_hash
        or any(unit.authority != outline.authority for unit in materialized_units)
    ):
        raise ValueError("compact semantic projection inputs do not share exact authority")
    unit_by_id = {item.unit_id: item for item in materialized_units}
    if tuple(unit_by_id) != outline.ordered_unit_ids:
        raise ValueError("compact semantic projection requires exact ordered unit membership")
    atom_by_id = {item.id: item for item in model.atoms}
    if any(unit.story_atom_id not in atom_by_id for unit in materialized_units):
        raise ValueError("compact semantic projection unit lacks its M11 story atom")
    position = {unit_id: index for index, unit_id in enumerate(outline.ordered_unit_ids)}
    beat_by_id = {item.beat_id: item for item in outline.beats}
    beat_by_unit_id = {
        unit_id: beat for beat in outline.beats for unit_id in beat.ordered_unit_ids
    }
    choice_by_id = {item.choice_id: item for item in outline.choices}
    if len(beat_by_id) != len(outline.beats) or len(choice_by_id) != len(outline.choices):
        raise ValueError("compact semantic projection has duplicate frozen subjects")

    def beat_position(beat: SemanticBeat) -> int:
        return min(position[item] for item in beat.ordered_unit_ids)

    def beat_has_story_content(beat: SemanticBeat) -> bool:
        return any(
            atom_by_id[unit_by_id[unit_id].story_atom_id].kind in _STORY_CONTENT_ATOM_KINDS
            for unit_id in beat.ordered_unit_ids
        )

    beats_by_arm: dict[tuple[str, str], list[SemanticBeat]] = {}
    for beat in outline.beats:
        if beat.parent_choice_id is not None and beat.parent_arm_id is not None:
            beats_by_arm.setdefault((beat.parent_choice_id, beat.parent_arm_id), []).append(beat)
    children_by_arm: dict[tuple[str, str], list[ChoiceComposition]] = {}
    for choice in outline.choices:
        if choice.parent_choice_id is not None and choice.parent_arm_id is not None:
            children_by_arm.setdefault(
                (choice.parent_choice_id, choice.parent_arm_id), []
            ).append(choice)

    region_by_id = {item.id: item for item in canonical.regions}

    def is_shallow_setup_detour(choice: ChoiceComposition) -> bool:
        if presentation_roles is not None:
            return False
        if choice.canonical_region_id is None:
            return False
        region = region_by_id.get(choice.canonical_region_id)
        if region is None or region.kind != "local_detour" or choice.child_choice_ids:
            return False
        for arm_id in choice.ordered_arm_ids:
            arm_story_kinds = [
                atom_by_id[atom_id].kind
                for beat in beats_by_arm.get((choice.choice_id, arm_id), ())
                for unit_id in beat.ordered_unit_ids
                for atom_id in unit_by_id[unit_id].provenance.atom_ids
                if atom_id in atom_by_id
                and atom_by_id[atom_id].kind in _STORY_CONTENT_ATOM_KINDS
            ]
            if arm_story_kinds != [AtomKind.NARRATION]:
                return False
        return True

    visible_choice_ids: set[str] = set()
    visiting: set[str] = set()

    def choice_is_story_facing(choice_id: str) -> bool:
        if choice_id in visible_choice_ids:
            return True
        if choice_id in visiting:
            raise ValueError("compact semantic projection choice ownership contains a cycle")
        choice = choice_by_id[choice_id]
        if (
            presentation_roles is not None
            and (
                presentation_roles.get(choice_id) is not SemanticPresentationRole.STORY
                or presentation_roles.get(choice.parent_cluster_id)
                is not SemanticPresentationRole.STORY
            )
        ):
            return False
        if is_shallow_setup_detour(choice):
            return False
        visiting.add(choice_id)
        arm_results = []
        for arm_id in choice.ordered_arm_ids:
            arm_beats = beats_by_arm.get((choice_id, arm_id), ())
            has_direct_story = (
                bool(arm_beats)
                if presentation_roles is not None
                else any(beat_has_story_content(beat) for beat in arm_beats)
            )
            has_nested_story = any(
                choice_is_story_facing(child.choice_id)
                for child in children_by_arm.get((choice_id, arm_id), ())
            )
            arm_results.append(has_direct_story or has_nested_story)
        visiting.remove(choice_id)
        if arm_results and all(arm_results):
            visible_choice_ids.add(choice_id)
            return True
        return False

    for choice in reversed(outline.choices):
        choice_is_story_facing(choice.choice_id)

    topology_by_subject = {item.subject_id: item for item in topology.nodes}

    def choice_position_from_authority(choice: ChoiceComposition) -> int:
        topology_choice = topology_by_subject.get(choice.choice_id)
        split_nodes = set(topology_choice.canonical_node_ids) if topology_choice else set()
        split_positions = [
            position[unit.unit_id]
            for unit in materialized_units
            if split_nodes.intersection(unit.node_ids)
        ]
        return min(split_positions) if split_positions else min(
            beat_position(beat)
            for beat in outline.beats
            if beat.parent_cluster_id == choice.parent_cluster_id
        )

    visible_cluster_ids = (
        {
            cluster.cluster_id
            for cluster in outline.clusters
            if presentation_roles.get(cluster.cluster_id)
            is SemanticPresentationRole.STORY
        }
        if presentation_roles is not None
        else {
            cluster.cluster_id
            for cluster in outline.clusters
            if any(
                beat.parent_choice_id is None and beat_has_story_content(beat)
                for beat_id in cluster.ordered_beat_ids
                if (beat := beat_by_id[beat_id])
            )
            or any(choice_id in visible_choice_ids for choice_id in cluster.ordered_choice_ids)
        }
    )
    visible_top_choices = tuple(
        choice
        for choice in outline.choices
        if choice.parent_choice_id is None and choice.choice_id in visible_choice_ids
    )
    if visible_top_choices and presentation_roles is None:
        first_story_choice_position = min(
            choice_position_from_authority(choice) for choice in visible_top_choices
        )
        leading_filtered_choices = tuple(
            choice
            for choice in outline.choices
            if choice.parent_choice_id is None
            and choice.choice_id not in visible_choice_ids
            and choice_position_from_authority(choice) < first_story_choice_position
        )
        if leading_filtered_choices:
            cluster_ordinal = {item.cluster_id: item.ordinal for item in outline.clusters}
            leading_cutoff = max(
                cluster_ordinal[choice.parent_cluster_id]
                for choice in leading_filtered_choices
            )
            visible_cluster_ids = {
                cluster_id
                for cluster_id in visible_cluster_ids
                if cluster_ordinal[cluster_id] > leading_cutoff
                or any(
                    choice_id in visible_choice_ids
                    for choice_id in next(
                        item
                        for item in outline.clusters
                        if item.cluster_id == cluster_id
                    ).ordered_choice_ids
                )
            }
    if not visible_cluster_ids:
        raise ValueError("compact semantic projection has no story-facing section")

    ranked_nodes: list[tuple[tuple[int, int, int], dict[str, object]]] = []
    for cluster in outline.clusters:
        if cluster.cluster_id not in visible_cluster_ids:
            continue
        cluster_beats = tuple(beat_by_id[item] for item in cluster.ordered_beat_ids)
        first_position = min(beat_position(beat) for beat in cluster_beats)
        ranked_nodes.append(
            (
                (first_position, 0, cluster.ordinal),
                _story_summary_node(
                    cluster.cluster_id,
                    "major_cluster",
                    summaries[cluster.cluster_id],
                    provenance[cluster.cluster_id],
                    parent_node_id=None,
                ),
            )
        )

    def choice_split_beats(choice_id: str) -> tuple[SemanticBeat, ...]:
        topology_choice = topology_by_subject.get(choice_id)
        split_nodes = set(topology_choice.canonical_node_ids) if topology_choice else set()
        return tuple(
            beat_by_unit_id[unit.unit_id]
            for unit in materialized_units
            if split_nodes.intersection(unit.node_ids)
        )

    for choice in outline.choices:
        if choice.choice_id not in visible_choice_ids:
            continue
        choice_position = choice_position_from_authority(choice)
        parent_choice_id = (
            choice.parent_choice_id
            if choice.parent_choice_id in visible_choice_ids
            else None
        )
        choice_node = _story_summary_node(
            choice.choice_id,
            "choice",
            summaries[choice.choice_id],
            provenance[choice.choice_id],
            parent_node_id=parent_choice_id or choice.parent_cluster_id,
        )
        choice_node.update(
            {
                "choice_id": choice.choice_id,
                "parent_cluster_id": choice.parent_cluster_id,
                "parent_arm_id": choice.parent_arm_id if parent_choice_id is not None else None,
                "ordered_arm_ids": list(choice.ordered_arm_ids),
                "ordered_arm_captions": list(choice.ordered_arm_captions),
                "rejoin_relationship_ids": list(choice.rejoin_relationship_ids),
            }
        )
        ranked_nodes.append(((choice_position, 1, 0), choice_node))
        for arm_ordinal, (arm_id, caption) in enumerate(
            zip(choice.ordered_arm_ids, choice.ordered_arm_captions, strict=True)
        ):
            arm_beats = sorted(
                beats_by_arm.get((choice.choice_id, arm_id), ()),
                key=beat_position,
            )
            story_beats = [beat for beat in arm_beats if beat_has_story_content(beat)]
            nested_split_beats = [
                beat
                for child in children_by_arm.get((choice.choice_id, arm_id), ())
                if child.choice_id in visible_choice_ids
                for beat in choice_split_beats(child.choice_id)
            ]
            representative = (story_beats or arm_beats or nested_split_beats)[0]
            arm_node = _story_summary_node(
                representative.beat_id,
                "choice_arm",
                summaries[representative.beat_id],
                provenance[representative.beat_id],
                parent_node_id=choice.choice_id,
            )
            first_unit = unit_by_id[representative.ordered_unit_ids[0]]
            arm_node.update(
                {
                    "title": caption,
                    "parent_cluster_id": choice.parent_cluster_id,
                    "choice_id": choice.choice_id,
                    "arm_id": arm_id,
                    "parent_arm_id": arm_id,
                    "lane_id": first_unit.lane_id,
                    "collapsed_beat_ids": [
                        beat.beat_id for beat in (arm_beats or nested_split_beats)
                    ],
                }
            )
            ranked_nodes.append(
                ((choice_position, 2, arm_ordinal), arm_node)
            )

    choice_by_rejoin: dict[str, ChoiceComposition] = {}
    for choice in outline.choices:
        if choice.choice_id not in visible_choice_ids or choice.shared_target_id is None:
            continue
        if not choice_owns_visual_rejoin(choice, choice_by_id, visible_choice_ids):
            continue
        rejoin_id = stable_m15_id(
            "semantic_rejoin",
            {
                "canonical_hash": canonical.authority_hash,
                "canonical_node_id": choice.shared_target_id,
                "call_occurrence_path": list(choice.call_occurrence_path),
            },
        )
        choice_by_rejoin.setdefault(rejoin_id, choice)

    last_cluster_id = next(
        cluster.cluster_id
        for cluster in reversed(outline.clusters)
        if cluster.cluster_id in visible_cluster_ids
    )
    for topology_node in topology.nodes:
        rejoin_choice = choice_by_rejoin.get(topology_node.subject_id)
        if topology_node.subject_kind == "rejoin" and rejoin_choice is not None:
            continuation_position = (
                position[rejoin_choice.post_rejoin_continuation_id]
                if rejoin_choice.post_rejoin_continuation_id in position
                else len(position)
            )
            ranked_nodes.append(
                (
                    (continuation_position, 0, 0),
                    _structural_story_node(
                        topology_node.subject_id,
                        "rejoin",
                        "Paths come back together",
                        "The choice arms reach the same authoritative continuation.",
                        parent_node_id=rejoin_choice.choice_id,
                        target_kind=topology_node.subject_kind,
                        rejoin_choice=rejoin_choice,
                    ),
                )
            )
        elif topology_node.subject_kind in {"terminal", "unresolved"}:
            kind = "ending" if topology_node.subject_kind == "terminal" else "unresolved"
            title = (
                "End of the extracted story"
                if kind == "ending"
                else "Unresolved story path"
            )
            summary_text = (
                "The current deterministic story scope ends here."
                if kind == "ending"
                else "Static authority cannot prove what happens beyond this point."
            )
            ranked_nodes.append(
                (
                    (len(position), 2, len(ranked_nodes)),
                    _structural_story_node(
                        topology_node.subject_id,
                        kind,
                        title,
                        summary_text,
                        parent_node_id=last_cluster_id,
                        target_kind=topology_node.subject_kind,
                    ),
                )
            )

    ranked_nodes.sort(key=lambda item: item[0])
    result: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for order, (_rank, node) in enumerate(ranked_nodes, start=1):
        node_id = str(node["id"])
        if node_id in seen_ids:
            raise ValueError("compact semantic projection duplicates one visible subject")
        seen_ids.add(node_id)
        node["order"] = order
        node["ordinal"] = order - 1
        result.append(node)
    return tuple(result)


def build_compact_whole_scope_projection(
    canonical: CanonicalGraph,
    model: SceneModel,
    units: Sequence[FineNarrativeUnit],
    outline: SemanticOutline,
    topology: SemanticQuotientTopology,
    editorial: WholeScopeEditorialBatch,
    provenance: Mapping[str, Mapping[str, object]],
) -> CompactWholeScopeProjection:
    """Build the revised Stage H/E projection without inventing presentation authority.

    Stage E roles decide which editorial subjects enter normal story flow. Choice arms remain
    deterministic M10/M11 structures: their presentation IDs derive from authority plus exact
    choice/arm identity, captions remain byte-for-byte contract captions, and their Detail /
    Evidence membership covers every collapsed beat in that arm.
    """

    materialized_units = tuple(units)
    if editorial.hierarchy_hash != semantic_outline_hash(outline):
        raise ValueError("whole-scope editorial hierarchy identity is stale")
    records = editorial.records
    records_by_id = {item.subject_id: item for item in records}
    if len(records_by_id) != len(records):
        raise ValueError("whole-scope editorial subject IDs must be globally unique")
    expected_subjects = {
        *(item.beat_id for item in outline.beats),
        *(item.cluster_id for item in outline.clusters),
        *(item.choice_id for item in outline.choices),
    }
    if set(records_by_id) != expected_subjects:
        raise ValueError("whole-scope editorial records must cover every frozen subject")
    if set(provenance) != expected_subjects:
        raise ValueError("whole-scope editorial provenance must be one-to-one with subjects")

    allowed_evidence = _whole_scope_evidence_by_subject(outline, materialized_units)
    for record in records:
        if record.subject_kind != _whole_scope_subject_kind(outline, record.subject_id):
            raise ValueError("whole-scope editorial subject kind is inconsistent")
        cited = {
            evidence_id
            for claim in record.claims
            for evidence_id in claim.evidence_ids
        }
        if not cited or not cited.issubset(allowed_evidence[record.subject_id]):
            raise ValueError("whole-scope editorial claim cites foreign evidence")

    summaries: dict[str, Mapping[str, object]] = {
        record.subject_id: cast(Mapping[str, object], record.to_dict())
        for record in records
    }
    roles = {record.subject_id: record.presentation_role for record in records}
    base_nodes = project_compact_semantic_nodes(
        canonical,
        model,
        materialized_units,
        outline,
        topology,
        summaries,
        provenance,
        presentation_roles=roles,
    )
    base_node_ids = tuple(str(item["id"]) for item in base_nodes)
    base_edges = project_compact_semantic_edges(topology, base_node_ids)
    beat_by_id = {item.beat_id: item for item in outline.beats}
    cluster_by_id = {item.cluster_id: item for item in outline.clusters}
    unit_by_id = {item.unit_id: item for item in materialized_units}

    arm_id_remap: dict[str, str] = {}
    nodes: list[dict[str, object]] = []
    partial_subject_ids: list[str] = []
    for base in base_nodes:
        node = dict(base)
        if node.get("kind") == "choice_arm":
            choice_id = str(node["choice_id"])
            arm_id = str(node["arm_id"])
            member_beat_ids = tuple(
                str(item)
                for item in cast(Sequence[object], node.get("collapsed_beat_ids", ()))
            )
            member_beats = tuple(
                beat_by_id[item] for item in member_beat_ids if item in beat_by_id
            )
            if not member_beats:
                raise ValueError("a visible whole-scope arm has no frozen beat membership")
            member_records = tuple(records_by_id[item.beat_id] for item in member_beats)
            story_records = tuple(
                item
                for item in member_records
                if item.presentation_role is SemanticPresentationRole.STORY
            )
            presentation_id = stable_m15_id(
                "semantic_choice_arm_presentation",
                {
                    "canonical_hash": canonical.authority_hash,
                    "choice_id": choice_id,
                    "arm_id": arm_id,
                },
            )
            arm_id_remap[str(node["id"])] = presentation_id
            warnings = _ordered_strings(
                warning for item in member_records for warning in item.warnings
            )
            member_unit_ids = tuple(
                unit_id for beat in member_beats for unit_id in beat.ordered_unit_ids
            )
            evidence_ids = _ordered_strings(
                (
                    *(
                        evidence_id
                        for item in member_records
                        for claim in item.claims
                        for evidence_id in claim.evidence_ids
                    ),
                    *(
                        evidence_id
                        for unit_id in member_unit_ids
                        for evidence_id in unit_by_id[unit_id].evidence_ids
                    ),
                )
            )
            node.update(
                {
                    "id": presentation_id,
                    "summary": " ".join(
                        _ordered_strings(item.summary for item in story_records)
                    ),
                    "characters": list(
                        _ordered_strings(
                            character for item in story_records for character in item.characters
                        )
                    ),
                    "claims": [
                        {
                            "claim_class": claim.claim_class.value,
                            "text": claim.text,
                            "evidence_ids": list(claim.evidence_ids),
                        }
                        for item in story_records
                        for claim in item.claims
                    ],
                    "warnings": list(warnings),
                    "presentation_role": SemanticPresentationRole.STORY.value,
                    "editorial_status": (
                        "complete" if story_records and not warnings else "partial"
                    ),
                    "member_subject_ids": list(member_beat_ids),
                    "member_unit_ids": list(member_unit_ids),
                    "evidence_ids": list(evidence_ids),
                    "membership_hash": canonical_hash(
                        [item.membership_hash for item in member_records]
                    ),
                    "summary_provenance": {
                        "subject_kind": "choice_arm",
                        "subject_id": presentation_id,
                        "member_subject_ids": list(member_beat_ids),
                        "member_provenance": [dict(provenance[item]) for item in member_beat_ids],
                    },
                    "navigation": {
                        "mode": "detail_evidence",
                        "target_kind": "choice_arm",
                        "target_id": presentation_id,
                    },
                }
            )
            if node["editorial_status"] == "partial":
                partial_subject_ids.append(presentation_id)
        else:
            node_record = records_by_id.get(str(node["id"]))
            if node_record is not None:
                collapsed_warnings = (
                    _ordered_strings(
                        (
                            *node_record.warnings,
                            *(
                                warning
                                for beat_id in cluster_by_id[
                                    node_record.subject_id
                                ].ordered_beat_ids
                                for warning in records_by_id[beat_id].warnings
                            ),
                        )
                    )
                    if node_record.subject_kind == "major_cluster"
                    else node_record.warnings
                )
                node_cited = _ordered_strings(
                    evidence_id
                    for claim in node_record.claims
                    for evidence_id in claim.evidence_ids
                )
                node.update(
                    {
                        "presentation_role": node_record.presentation_role.value,
                        "editorial_status": (
                            "partial" if collapsed_warnings else "complete"
                        ),
                        "warnings": list(collapsed_warnings),
                        "evidence_ids": list(node_cited),
                        "membership_hash": node_record.membership_hash,
                    }
                )
                if collapsed_warnings:
                    partial_subject_ids.append(node_record.subject_id)
            else:
                node.update(
                    {
                        "presentation_role": "structural",
                        "editorial_status": "partial" if node.get("unresolved") else "complete",
                    }
                )
                if node.get("unresolved"):
                    partial_subject_ids.append(str(node["id"]))
        nodes.append(node)

    projected_edges: list[SemanticTopologyEdge] = []
    for edge in base_edges:
        source_id = arm_id_remap.get(edge.source_subject_id, edge.source_subject_id)
        target_id = arm_id_remap.get(edge.target_subject_id, edge.target_subject_id)
        projected_edges.append(
            SemanticTopologyEdge(
                edge_id=stable_m15_id(
                    "semantic_whole_scope_edge",
                    {
                        "canonical_hash": topology.canonical_hash,
                        "source": source_id,
                        "target": target_id,
                        "kind": edge.kind.value,
                        "authority_edge_ids": list(edge.authority_edge_ids),
                    },
                ),
                source_subject_id=source_id,
                target_subject_id=target_id,
                kind=edge.kind,
                authority_edge_ids=edge.authority_edge_ids,
                requirement_ids=edge.requirement_ids,
                effect_ids=edge.effect_ids,
                evidence_ids=edge.evidence_ids,
            )
        )

    if len(nodes) > MAXIMUM_COMPACT_WHOLE_SCOPE_ROWS:
        raise ValueError("compact whole-scope projection exceeds the 32-row normal-flow limit")
    _validate_whole_scope_choice_order(nodes, outline)
    visible_ids = {str(item["id"]) for item in nodes}
    if any(
        item.source_subject_id not in visible_ids or item.target_subject_id not in visible_ids
        for item in projected_edges
    ):
        raise ValueError("whole-scope projection contains a non-visible edge endpoint")
    omitted = tuple(
        item.subject_id
        for item in records
        if item.presentation_role is not SemanticPresentationRole.STORY
    )
    return CompactWholeScopeProjection(
        tuple(nodes),
        tuple(projected_edges),
        omitted,
        _ordered_strings(partial_subject_ids),
        _ordered_strings(editorial.warnings),
    )


def _whole_scope_subject_kind(outline: SemanticOutline, subject_id: str) -> str:
    if any(item.beat_id == subject_id for item in outline.beats):
        return "beat"
    if any(item.cluster_id == subject_id for item in outline.clusters):
        return "major_cluster"
    if any(item.choice_id == subject_id for item in outline.choices):
        return "choice"
    raise ValueError("whole-scope editorial record references an unknown subject")


def _whole_scope_evidence_by_subject(
    outline: SemanticOutline,
    units: Sequence[FineNarrativeUnit],
) -> dict[str, set[str]]:
    unit_by_id = {item.unit_id: item for item in units}
    evidence = {
        beat.beat_id: {
            evidence_id
            for unit_id in beat.ordered_unit_ids
            for evidence_id in unit_by_id[unit_id].evidence_ids
        }
        for beat in outline.beats
    }
    beat_by_id = {item.beat_id: item for item in outline.beats}
    for cluster in outline.clusters:
        evidence[cluster.cluster_id] = {
            evidence_id
            for beat_id in cluster.ordered_beat_ids
            for evidence_id in evidence[beat_by_id[beat_id].beat_id]
        }
    choices = {item.choice_id: item for item in outline.choices}

    def descendants(choice_id: str, visiting: frozenset[str]) -> frozenset[str]:
        if choice_id in visiting:
            raise ValueError("whole-scope choice ownership contains a cycle")
        choice = choices.get(choice_id)
        if choice is None:
            raise ValueError("whole-scope choice ownership references an unknown choice")
        result = {choice_id}
        for child_id in choice.child_choice_ids:
            result.update(descendants(child_id, visiting | {choice_id}))
        return frozenset(result)

    for choice in outline.choices:
        owned = descendants(choice.choice_id, frozenset())
        evidence[choice.choice_id] = {
            evidence_id
            for beat in outline.beats
            if beat.parent_choice_id in owned
            for evidence_id in evidence[beat.beat_id]
        }
        if not evidence[choice.choice_id]:
            evidence[choice.choice_id] = set(evidence[choice.parent_cluster_id])
    return evidence


def _validate_whole_scope_choice_order(
    nodes: Sequence[Mapping[str, object]],
    outline: SemanticOutline,
) -> None:
    order = {str(item["id"]): int(cast(int, item["order"])) for item in nodes}
    visible_choices = {
        str(item["id"]): item for item in nodes if item.get("kind") == "choice"
    }
    arms_by_choice: dict[str, list[Mapping[str, object]]] = {}
    rejoins_by_choice: dict[str, list[Mapping[str, object]]] = {}
    for item in nodes:
        choice_id = item.get("choice_id")
        if not isinstance(choice_id, str):
            continue
        if item.get("kind") == "choice_arm":
            arms_by_choice.setdefault(choice_id, []).append(item)
        elif item.get("kind") == "rejoin":
            rejoins_by_choice.setdefault(choice_id, []).append(item)
    choice_by_id = {item.choice_id: item for item in outline.choices}
    for choice_id in visible_choices:
        choice = choice_by_id[choice_id]
        arms = arms_by_choice.get(choice_id, [])
        if [str(item["arm_id"]) for item in arms] != list(choice.ordered_arm_ids):
            raise ValueError("whole-scope choice arms are incomplete or out of order")
        if any(order[choice_id] >= order[str(item["id"])] for item in arms):
            raise ValueError("whole-scope choice must precede every consequence arm")
        if any(
            order[str(rejoin["id"])] <= max(order[str(item["id"])] for item in arms)
            for rejoin in rejoins_by_choice.get(choice_id, ())
        ):
            raise ValueError("whole-scope rejoin must follow every alternative outcome")


def choice_owns_visual_rejoin(
    choice: ChoiceComposition,
    choices: Mapping[str, ChoiceComposition],
    visible_choice_ids: Collection[str],
) -> bool:
    """Return whether a choice owns a distinct compact merge marker.

    Exact nested rejoin relationships remain on the choice itself. A nested choice without its
    own continuation feeds the first visible ancestor that owns the continuation, so drawing a
    second marker would duplicate one visual story transition.
    """

    if choice.post_rejoin_continuation_id is not None or choice.parent_choice_id is None:
        return True
    seen = {choice.choice_id}
    parent_id: str | None = choice.parent_choice_id
    while parent_id is not None:
        if parent_id in seen:
            raise ValueError("compact semantic projection choice ownership contains a cycle")
        seen.add(parent_id)
        parent = choices.get(parent_id)
        if parent is None:
            raise ValueError("compact semantic projection nested choice lacks its ancestor")
        if (
            parent.choice_id in visible_choice_ids
            and parent.post_rejoin_continuation_id is not None
        ):
            return False
        parent_id = parent.parent_choice_id
    return True


def project_compact_semantic_edges(
    topology: SemanticQuotientTopology,
    visible_subject_ids: Sequence[str],
) -> tuple[SemanticTopologyEdge, ...]:
    """Contract hidden beat/technical chains while retaining exact M10 edge evidence."""

    visible = frozenset(visible_subject_ids)
    outgoing: dict[str, list[SemanticTopologyEdge]] = {}
    for edge in topology.edges:
        outgoing.setdefault(edge.source_subject_id, []).append(edge)
    projected: list[SemanticTopologyEdge] = []
    projected_keys: set[tuple[str, str, tuple[str, ...]]] = set()
    for source_id in visible:
        stack: list[tuple[str, tuple[SemanticTopologyEdge, ...], frozenset[str]]] = [
            (source_id, (), frozenset({source_id}))
        ]
        while stack:
            current_id, path, visited = stack.pop()
            for edge in outgoing.get(current_id, ()):
                target_id = edge.target_subject_id
                next_path = (*path, edge)
                if target_id in visible:
                    authority_edge_ids = _ordered_strings(
                        item for path_edge in next_path for item in path_edge.authority_edge_ids
                    )
                    key = (source_id, target_id, authority_edge_ids)
                    if key in projected_keys:
                        continue
                    projected_keys.add(key)
                    if len(next_path) == 1:
                        projected.append(edge)
                        continue
                    kind = next(
                        (
                            path_edge.kind
                            for path_edge in reversed(next_path)
                            if path_edge.kind.value != "continuation"
                        ),
                        next_path[0].kind,
                    )
                    projected.append(
                        SemanticTopologyEdge(
                            edge_id=stable_m15_id(
                                "semantic_compact_edge",
                                {
                                    "canonical_hash": topology.canonical_hash,
                                    "source": source_id,
                                    "target": target_id,
                                    "kind": kind.value,
                                    "authority_edge_ids": list(authority_edge_ids),
                                },
                            ),
                            source_subject_id=source_id,
                            target_subject_id=target_id,
                            kind=kind,
                            authority_edge_ids=authority_edge_ids,
                            requirement_ids=_ordered_strings(
                                item
                                for path_edge in next_path
                                for item in path_edge.requirement_ids
                            ),
                            effect_ids=_ordered_strings(
                                item
                                for path_edge in next_path
                                for item in path_edge.effect_ids
                            ),
                            evidence_ids=_ordered_strings(
                                item
                                for path_edge in next_path
                                for item in path_edge.evidence_ids
                            ),
                        )
                    )
                    continue
                if target_id not in visited:
                    stack.append((target_id, next_path, visited | {target_id}))
    projected.sort(
        key=lambda item: (
            item.source_subject_id,
            item.target_subject_id,
            item.kind.value,
            item.edge_id,
        )
    )
    return tuple(projected)


def _story_summary_node(
    subject_id: str,
    kind: str,
    summary: Mapping[str, object],
    provenance: Mapping[str, object],
    *,
    parent_node_id: str | None,
) -> dict[str, object]:
    return {
        "id": subject_id,
        "kind": kind,
        "title": str(summary["title"]),
        "summary": str(summary["summary"]),
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
        "claims": [
            dict(item) for item in cast(Sequence[Mapping[str, object]], summary["claims"])
        ],
        "warnings": list(cast(Sequence[object], summary["warnings"])),
        "summary_provenance": dict(provenance),
        "navigation": {
            "mode": "detail_evidence",
            "target_kind": str(summary["subject_kind"]),
            "target_id": subject_id,
        },
    }


def _structural_story_node(
    subject_id: str,
    kind: str,
    title: str,
    summary: str,
    *,
    parent_node_id: str | None,
    target_kind: str,
    rejoin_choice: ChoiceComposition | None = None,
) -> dict[str, object]:
    return {
        "id": subject_id,
        "kind": kind,
        "title": title,
        "summary": summary,
        "lane_id": "story-spine",
        "lane_kind": "spine",
        "lane_label": "Story spine",
        "parent_node_id": parent_node_id,
        "choice_id": rejoin_choice.choice_id if rejoin_choice is not None else None,
        "arm_id": None,
        "rejoin_node_id": (
            rejoin_choice.shared_target_id if rejoin_choice is not None else None
        ),
        "technical_count": 0,
        "unresolved": kind == "unresolved",
        "navigation": {
            "mode": "detail_evidence",
            "target_kind": target_kind,
            "target_id": subject_id,
        },
    }


def _ordered_strings(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


def _ordered_evidence(
    ordered_unit_ids: Sequence[str],
    evidence_by_unit: Mapping[str, Sequence[SemanticEvidenceRecord]],
) -> tuple[SemanticEvidenceRecord, ...]:
    missing = tuple(unit_id for unit_id in ordered_unit_ids if unit_id not in evidence_by_unit)
    if missing:
        raise ValueError(f"semantic evidence is missing units: {', '.join(missing)}")
    records = tuple(record for unit_id in ordered_unit_ids for record in evidence_by_unit[unit_id])
    if not records:
        raise ValueError("provider semantic input requires story evidence")
    if any(
        record.unit_id != unit_id
        for unit_id in ordered_unit_ids
        for record in evidence_by_unit[unit_id]
    ):
        raise ValueError("semantic evidence record is filed under the wrong unit")
    ordinals = tuple(record.ordinal for record in records)
    if any(left >= right for left, right in pairwise(ordinals)):
        raise ValueError("semantic evidence ordinals must be strictly increasing")
    _unique(
        tuple(record.evidence_id for record in records),
        "semantic evidence ID",
        allow_empty=False,
    )
    return records


def _unit_context(unit: FineNarrativeUnit) -> tuple[str | None, ...]:
    return (
        unit.sequence_id,
        unit.lane_id,
        unit.call_occurrence_id,
        unit.loop_id,
        unit.parent_choice_id,
        unit.parent_arm_id,
    )


def _text(value: str, label: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{label} must be a non-empty trimmed string")


def _unique(values: Sequence[str], label: str, *, allow_empty: bool = True) -> None:
    if not allow_empty and not values:
        raise ValueError(f"{label} cannot be empty")
    if any(not value or value != value.strip() for value in values):
        raise ValueError(f"{label} must be non-empty and trimmed")
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
