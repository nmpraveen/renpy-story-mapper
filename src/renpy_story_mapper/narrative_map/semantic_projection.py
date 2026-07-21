"""Transient M15.1 provider projection over frozen Track A semantic contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise

from renpy_story_mapper.narrative_map.assembly import semantic_membership_hash
from renpy_story_mapper.narrative_map.contracts import JsonValue, SourceLocator, canonical_hash
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
    SemanticSummary,
)

MAXIMUM_OWNED_GAPS_PER_WINDOW = 8
MAXIMUM_CONTEXT_UNITS_PER_WINDOW = 16
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
