"""Ordered, transient evidence projection for M15 boundary and summary jobs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise

from renpy_story_mapper.narrative_map.contracts import (
    BoundaryCandidate,
    JsonValue,
    NarrativeCorridor,
    NarrativeEvent,
    SourceLocator,
    canonical_hash,
)
from renpy_story_mapper.narrative_map.provider import (
    BOUNDARY_PROMPT_VERSION,
    BOUNDARY_RESPONSE_SCHEMA,
    SUMMARY_PROMPT_VERSION,
    SUMMARY_RESPONSE_SCHEMA,
    PreparedNarrativeJob,
    ProviderJobKind,
)


@dataclass(frozen=True)
class EvidenceRecord:
    """One source-ordered evidence item used only to construct an in-memory provider request."""

    atom_id: str
    evidence_id: str
    ordinal: int
    kind: str
    text: str
    speaker: str | None
    locator: SourceLocator

    def __post_init__(self) -> None:
        for value, label in (
            (self.atom_id, "evidence atom ID"),
            (self.evidence_id, "evidence ID"),
            (self.kind, "evidence kind"),
            (self.text, "evidence text"),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{label} must be a non-empty trimmed string")
        if self.speaker is not None and (
            not self.speaker or self.speaker != self.speaker.strip()
        ):
            raise ValueError("evidence speaker must be a trimmed string when supplied")
        if self.ordinal < 0:
            raise ValueError("evidence ordinal cannot be negative")

    def to_prompt_dict(self) -> dict[str, JsonValue]:
        return {
            "atom_id": self.atom_id,
            "evidence_id": self.evidence_id,
            "ordinal": self.ordinal,
            "kind": self.kind,
            "speaker": self.speaker,
            "text": self.text,
            "locator": self.locator.to_dict(),
        }


def prepare_boundary_jobs(
    corridors: Sequence[NarrativeCorridor],
    candidates: Sequence[BoundaryCandidate],
    evidence_by_atom: Mapping[str, EvidenceRecord],
) -> tuple[PreparedNarrativeJob, ...]:
    """Create exactly one job for each known adjacent soft candidate.

    A candidate that crosses topology/context or either corridor's deterministic cut is rejected
    rather than silently omitted or transmitted.
    """

    if not corridors:
        if candidates:
            raise ValueError("boundary candidates require known adjacent corridors")
        return ()
    ids = tuple(corridor.corridor_id for corridor in corridors)
    if len(ids) != len(set(ids)):
        raise ValueError("corridor order cannot contain duplicate identities")
    candidate_ids = tuple(candidate.candidate_id for candidate in candidates)
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("each boundary candidate must belong to exactly one job")
    by_pair = {
        (corridors[index].corridor_id, corridors[index + 1].corridor_id): (
            corridors[index],
            corridors[index + 1],
        )
        for index in range(len(corridors) - 1)
    }
    jobs: list[PreparedNarrativeJob] = []
    for candidate in candidates:
        pair = by_pair.get((candidate.left_corridor_id, candidate.right_corridor_id))
        if pair is None:
            raise ValueError("boundary candidates must reference adjacent corridors in scope order")
        left, right = pair
        if candidate.authority != left.authority or candidate.authority != right.authority:
            raise ValueError("boundary candidate authority does not match its corridors")
        if left.hard_boundary_after or right.hard_boundary_before:
            raise ValueError("a hard boundary can never enter a provider job")
        if _context(left) != _context(right):
            raise ValueError(
                "cross-lane or cross-occurrence boundaries cannot enter a provider job"
            )
        if not candidate.signals:
            raise ValueError("provider boundary jobs require a soft signal")
        ordered_evidence = _ordered_evidence(
            (*left.ordered_atom_ids, *right.ordered_atom_ids), evidence_by_atom
        )
        known_evidence = tuple(item.evidence_id for item in ordered_evidence)
        if not set(candidate.evidence_ids).issubset(known_evidence):
            raise ValueError("boundary candidate evidence must exist in its ordered window")
        payload: dict[str, JsonValue] = {
            "candidate_id": candidate.candidate_id,
            "left_corridor_id": left.corridor_id,
            "right_corridor_id": right.corridor_id,
            "signals": [item.value for item in candidate.signals],
            "structural_context": {
                "lane_id": left.lane_id,
                "chapter_id": left.chapter_id,
                "call_occurrence_id": left.call_occurrence_id,
                "loop_id": left.loop_id,
                "temporary_container_id": left.temporary_container_id,
                "temporary_arm_id": left.temporary_arm_id,
            },
            "evidence": [item.to_prompt_dict() for item in ordered_evidence],
            "allowed_evidence_ids": list(candidate.evidence_ids),
        }
        jobs.append(
            PreparedNarrativeJob(
                kind=ProviderJobKind.BOUNDARY,
                authority=candidate.authority,
                subject=candidate,
                subject_id=candidate.candidate_id,
                input_hash=canonical_hash(payload),
                prompt_version=BOUNDARY_PROMPT_VERSION,
                response_schema=BOUNDARY_RESPONSE_SCHEMA,
                payload=payload,
                known_evidence_ids=known_evidence,
                story_facing=True,
            )
        )
    return tuple(jobs)


def prepare_event_summary_jobs(
    events: Sequence[NarrativeEvent],
    evidence_by_atom: Mapping[str, EvidenceRecord],
    *,
    known_characters: Mapping[str, Sequence[str]] | None = None,
    story_facing: Mapping[str, bool] | None = None,
) -> tuple[PreparedNarrativeJob, ...]:
    """Create one independent summary job for each already-frozen event."""

    ids = tuple(event.event_id for event in events)
    if len(ids) != len(set(ids)):
        raise ValueError("summary jobs require unique frozen event identities")
    character_map = known_characters or {}
    story_map = story_facing or {}
    jobs: list[PreparedNarrativeJob] = []
    for event in events:
        ordered_evidence = _ordered_evidence(event.ordered_atom_ids, evidence_by_atom)
        known_evidence = tuple(item.evidence_id for item in ordered_evidence)
        if not set(event.provenance.evidence_ids).issubset(known_evidence):
            raise ValueError("event provenance evidence must exist in its ordered prompt")
        characters = tuple(character_map.get(event.event_id, ()))
        if len(characters) != len(set(characters)):
            raise ValueError("known event characters must be unique")
        payload: dict[str, JsonValue] = {
            "event_id": event.event_id,
            "frozen_membership": {
                "corridor_ids": list(event.ordered_corridor_ids),
                "atom_ids": list(event.ordered_atom_ids),
            },
            "deterministic_title": event.deterministic_title,
            "known_character_names": list(characters),
            "allowed_evidence_ids": list(event.provenance.evidence_ids),
            "evidence": [item.to_prompt_dict() for item in ordered_evidence],
        }
        jobs.append(
            PreparedNarrativeJob(
                kind=ProviderJobKind.EVENT_SUMMARY,
                authority=event.authority,
                subject=event,
                subject_id=event.event_id,
                input_hash=canonical_hash(payload),
                prompt_version=SUMMARY_PROMPT_VERSION,
                response_schema=SUMMARY_RESPONSE_SCHEMA,
                payload=payload,
                known_evidence_ids=known_evidence,
                known_characters=characters,
                story_facing=story_map.get(event.event_id, True),
            )
        )
    return tuple(jobs)


def _context(corridor: NarrativeCorridor) -> tuple[str | None, ...]:
    return (
        corridor.lane_id,
        corridor.chapter_id,
        corridor.call_occurrence_id,
        corridor.loop_id,
        corridor.temporary_container_id,
        corridor.temporary_arm_id,
    )


def _ordered_evidence(
    atom_ids: Sequence[str], evidence_by_atom: Mapping[str, EvidenceRecord]
) -> tuple[EvidenceRecord, ...]:
    if len(atom_ids) != len(set(atom_ids)):
        raise ValueError("one provider job cannot duplicate atom ownership")
    missing = tuple(atom_id for atom_id in atom_ids if atom_id not in evidence_by_atom)
    if missing:
        raise ValueError(f"provider evidence is missing known atom IDs: {', '.join(missing)}")
    records = tuple(evidence_by_atom[atom_id] for atom_id in atom_ids)
    if tuple(item.atom_id for item in records) != tuple(atom_ids):
        raise ValueError("provider evidence must preserve exact atom order")
    if any(left.ordinal >= right.ordinal for left, right in pairwise(records)):
        raise ValueError("provider evidence ordinals must be strictly increasing")
    if len({item.evidence_id for item in records}) != len(records):
        raise ValueError("one provider job cannot duplicate evidence handles")
    return records
