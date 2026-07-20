"""Item-isolated validation for M15 boundary decisions and frozen-event summaries."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from renpy_story_mapper.narrative_map.contracts import (
    MAX_REASON_LENGTH,
    MAX_SUMMARY_LENGTH,
    MAX_TITLE_LENGTH,
    BoundaryCandidate,
    BoundaryDecision,
    BoundaryDecisionKind,
    BoundaryProviderIdentity,
    NarrativeEvent,
    canonical_hash,
    stable_m15_id,
)

_BOUNDARY_FIELDS = frozenset({"candidate_id", "decision", "reason", "confidence", "warnings"})
_SUMMARY_FIELDS = frozenset({"event_id", "title", "summary", "characters", "claims", "warnings"})
_CLAIM_FIELDS = frozenset({"claim_class", "text", "evidence_ids"})
_BLOCKED_TITLES = frozenset(
    {
        "start",
        "clean",
        "module end",
        "module ending",
        "technical merge",
    }
)
_IMAGE_TITLE = re.compile(r"^(?:bg|cg|scene|show|hide|image)[ _:-]+[a-z0-9_. -]+$", re.I)


@dataclass(frozen=True)
class ValidationFinding:
    code: str
    subject_id: str | None
    index: int | None = None


@dataclass(frozen=True)
class BoundaryValidationResult:
    decisions: tuple[BoundaryDecision, ...]
    findings: tuple[ValidationFinding, ...]
    omitted_candidate_ids: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.findings and not self.omitted_candidate_ids


class ClaimClass(StrEnum):
    FACTUAL = "factual"
    INTERPRETIVE = "interpretive"


@dataclass(frozen=True)
class EventSummaryClaim:
    claim_class: ClaimClass
    text: str
    evidence_ids: tuple[str, ...]

    @property
    def claim_id(self) -> str:
        return stable_m15_id(
            "event_claim",
            {
                "claim_class": self.claim_class.value,
                "text": self.text,
                "evidence_ids": list(self.evidence_ids),
            },
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "claim_class": self.claim_class.value,
            "text": self.text,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True)
class EventSummary:
    event_id: str
    title: str
    summary: str
    characters: tuple[str, ...]
    claims: tuple[EventSummaryClaim, ...]
    warnings: tuple[str, ...]
    provider_identity: BoundaryProviderIdentity | None

    @property
    def normalized_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "title": self.title,
            "summary": self.summary,
            "characters": list(self.characters),
            "claims": [claim.to_dict() for claim in self.claims],
            "warnings": list(self.warnings),
            "provider_identity": (
                self.provider_identity.to_dict() if self.provider_identity is not None else None
            ),
        }


@dataclass(frozen=True)
class EventSummaryValidationResult:
    summary: EventSummary | None
    findings: tuple[ValidationFinding, ...]

    @property
    def valid(self) -> bool:
        return self.summary is not None and not self.findings


def validate_boundary_response(
    payload: object,
    candidates: Sequence[BoundaryCandidate],
    *,
    provider_identity: BoundaryProviderIdentity | None,
) -> BoundaryValidationResult:
    """Validate every returned boundary independently; malformed siblings cannot erase peers."""

    findings: list[ValidationFinding] = []
    known = {candidate.candidate_id: candidate for candidate in candidates}
    if len(known) != len(candidates):
        raise ValueError("known boundary candidates must be unique")
    if not isinstance(payload, Mapping):
        return BoundaryValidationResult(
            (),
            (ValidationFinding("response_not_object", None),),
            tuple(known),
        )
    extra_top = set(payload) - {"decisions"}
    if extra_top:
        findings.append(ValidationFinding("extra_field", None))
    raw_decisions = payload.get("decisions")
    if not isinstance(raw_decisions, list):
        return BoundaryValidationResult(
            (),
            (*findings, ValidationFinding("decisions_not_array", None)),
            tuple(known),
        )
    returned_ids: list[str] = []
    for item in raw_decisions:
        if isinstance(item, Mapping) and isinstance(item.get("candidate_id"), str):
            returned_ids.append(cast(str, item["candidate_id"]))
    duplicate_ids: set[str] = {
        candidate_id for candidate_id, count in Counter(returned_ids).items() if count > 1
    }
    for duplicate_id in sorted(duplicate_ids):
        findings.append(ValidationFinding("duplicate_candidate", duplicate_id))
    accepted: dict[str, BoundaryDecision] = {}
    previous_known_index = -1
    known_order = {candidate.candidate_id: index for index, candidate in enumerate(candidates)}
    for index, raw in enumerate(raw_decisions):
        if not isinstance(raw, Mapping):
            findings.append(ValidationFinding("decision_not_object", None, index))
            continue
        candidate_value = raw.get("candidate_id")
        current_id = candidate_value if isinstance(candidate_value, str) else None
        item_codes: list[str] = []
        if set(raw) != _BOUNDARY_FIELDS:
            item_codes.append("extra_field" if set(raw) - _BOUNDARY_FIELDS else "missing_field")
        candidate = known.get(current_id or "")
        if candidate is None:
            item_codes.append("unknown_candidate")
        elif candidate.candidate_id in duplicate_ids:
            item_codes.append("duplicate_candidate")
        else:
            current_index = known_order[candidate.candidate_id]
            if current_index < previous_known_index:
                item_codes.append("crossing_order")
            previous_known_index = max(previous_known_index, current_index)
        decision_value = raw.get("decision")
        try:
            decision = (
                BoundaryDecisionKind(decision_value) if isinstance(decision_value, str) else None
            )
        except (ValueError, TypeError):
            decision = None
            item_codes.append("invalid_enum")
        if decision is None and "invalid_enum" not in item_codes:
            item_codes.append("invalid_enum")
        reason = raw.get("reason")
        if not _bounded_text(reason, MAX_REASON_LENGTH):
            item_codes.append("invalid_reason")
        confidence = raw.get("confidence")
        if (
            not isinstance(confidence, int | float)
            or isinstance(confidence, bool)
            or not math.isfinite(float(confidence))
            or not 0 <= float(confidence) <= 1
        ):
            item_codes.append("invalid_confidence")
        warnings = _text_array(raw.get("warnings"), MAX_REASON_LENGTH)
        if warnings is None:
            item_codes.append("invalid_warnings")
        if (
            decision is not None
            and decision is not BoundaryDecisionKind.UNCERTAIN
            and provider_identity is None
        ):
            item_codes.append("provider_identity_required")
        if item_codes:
            findings.extend(
                ValidationFinding(code, current_id, index) for code in dict.fromkeys(item_codes)
            )
            continue
        assert candidate is not None
        assert decision is not None
        assert isinstance(reason, str)
        assert isinstance(confidence, int | float)
        assert warnings is not None
        accepted[candidate.candidate_id] = BoundaryDecision(
            candidate=candidate,
            decision=decision,
            reason=reason,
            confidence=float(confidence),
            provider_identity=provider_identity,
            warnings=warnings,
        )
    present_known = {candidate_id for candidate_id in returned_ids if candidate_id in known}
    omitted = tuple(candidate_id for candidate_id in known if candidate_id not in present_known)
    findings.extend(
        ValidationFinding("omitted_candidate", candidate_id) for candidate_id in omitted
    )
    ordered = tuple(
        accepted[candidate.candidate_id]
        for candidate in candidates
        if candidate.candidate_id in accepted
    )
    return BoundaryValidationResult(ordered, tuple(findings), omitted)


def validate_event_summary_response(
    payload: object,
    event: NarrativeEvent,
    *,
    known_characters: Sequence[str],
    provider_identity: BoundaryProviderIdentity | None,
    story_facing: bool = True,
) -> EventSummaryValidationResult:
    """Validate one final-event response without permitting membership or authority changes."""

    findings: list[ValidationFinding] = []
    if not isinstance(payload, Mapping):
        return EventSummaryValidationResult(
            None, (ValidationFinding("response_not_object", event.event_id),)
        )
    if set(payload) != _SUMMARY_FIELDS:
        if set(payload) - _SUMMARY_FIELDS:
            findings.append(ValidationFinding("extra_field", event.event_id))
        if _SUMMARY_FIELDS - set(payload):
            findings.append(ValidationFinding("missing_field", event.event_id))
    if payload.get("event_id") != event.event_id:
        findings.append(
            ValidationFinding("unknown_event", _optional_string(payload.get("event_id")))
        )
    title = payload.get("title")
    if not _bounded_text(title, MAX_TITLE_LENGTH):
        findings.append(ValidationFinding("invalid_title", event.event_id))
    elif story_facing and _blocked_title(cast(str, title)):
        findings.append(ValidationFinding("blocked_title", event.event_id))
    summary_text = payload.get("summary")
    if not _bounded_text(summary_text, MAX_SUMMARY_LENGTH):
        findings.append(ValidationFinding("invalid_summary", event.event_id))
    character_values = _text_array(payload.get("characters"), MAX_REASON_LENGTH)
    if character_values is None:
        findings.append(ValidationFinding("invalid_characters", event.event_id))
        characters: tuple[str, ...] = ()
    else:
        characters = character_values
        allowed_characters = set(known_characters)
        if any(character not in allowed_characters for character in characters):
            findings.append(ValidationFinding("unknown_character", event.event_id))
    warnings = _text_array(payload.get("warnings"), MAX_REASON_LENGTH)
    if warnings is None:
        findings.append(ValidationFinding("invalid_warnings", event.event_id))
        warnings = ()
    raw_claims = payload.get("claims")
    claims: list[EventSummaryClaim] = []
    indexed_claims: list[tuple[int, EventSummaryClaim]] = []
    if not isinstance(raw_claims, list):
        findings.append(ValidationFinding("claims_not_array", event.event_id))
    else:
        allowed_evidence = set(event.provenance.evidence_ids)
        for index, raw_claim in enumerate(raw_claims):
            if not isinstance(raw_claim, Mapping):
                findings.append(ValidationFinding("claim_not_object", event.event_id, index))
                continue
            claim_codes: list[str] = []
            if set(raw_claim) != _CLAIM_FIELDS:
                claim_codes.append(
                    "extra_field" if set(raw_claim) - _CLAIM_FIELDS else "missing_field"
                )
            claim_class_value = raw_claim.get("claim_class")
            try:
                claim_class = (
                    ClaimClass(claim_class_value)
                    if isinstance(claim_class_value, str)
                    else None
                )
            except (ValueError, TypeError):
                claim_class = None
                claim_codes.append("invalid_claim_class")
            if claim_class is None and "invalid_claim_class" not in claim_codes:
                claim_codes.append("invalid_claim_class")
            claim_text = raw_claim.get("text")
            if not _bounded_text(claim_text, MAX_SUMMARY_LENGTH):
                claim_codes.append("invalid_claim_text")
            evidence_ids = _text_array(raw_claim.get("evidence_ids"), MAX_REASON_LENGTH)
            if not evidence_ids:
                claim_codes.append("invalid_evidence")
            elif any(evidence_id not in allowed_evidence for evidence_id in evidence_ids):
                claim_codes.append("unknown_evidence")
            if claim_codes:
                findings.extend(
                    ValidationFinding(code, event.event_id, index)
                    for code in dict.fromkeys(claim_codes)
                )
                continue
            assert claim_class is not None
            assert isinstance(claim_text, str)
            assert evidence_ids is not None
            claim = EventSummaryClaim(claim_class, claim_text, evidence_ids)
            claims.append(claim)
            indexed_claims.append((index, claim))
        duplicate_claim_ids = {
            claim_id
            for claim_id, count in Counter(
                claim.claim_id for _, claim in indexed_claims
            ).items()
            if count > 1
        }
        findings.extend(
            ValidationFinding("duplicate_claim", event.event_id, index)
            for index, claim in indexed_claims
            if claim.claim_id in duplicate_claim_ids
        )
    if findings:
        return EventSummaryValidationResult(None, tuple(findings))
    assert isinstance(title, str)
    assert isinstance(summary_text, str)
    return EventSummaryValidationResult(
        EventSummary(
            event_id=event.event_id,
            title=title,
            summary=summary_text,
            characters=characters,
            claims=tuple(claims),
            warnings=warnings,
            provider_identity=provider_identity,
        ),
        (),
    )


def _bounded_text(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= maximum
    )


def _text_array(value: object, maximum: int) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    if any(not _bounded_text(item, maximum) for item in value):
        return None
    values = cast(tuple[str, ...], tuple(value))
    if len(values) != len(set(values)):
        return None
    return values


def _blocked_title(title: str) -> bool:
    normalized = " ".join(title.casefold().split())
    return (
        normalized in _BLOCKED_TITLES
        or normalized.startswith("this scene defines")
        or _IMAGE_TITLE.fullmatch(title) is not None
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None
