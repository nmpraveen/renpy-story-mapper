"""Fail-closed validation for M15.1 boundary-window and frozen-summary responses."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from renpy_story_mapper.narrative_map.contracts import (
    MAX_REASON_LENGTH,
    MAX_SUMMARY_LENGTH,
    MAX_TITLE_LENGTH,
)
from renpy_story_mapper.narrative_map.provider import PreparedNarrativeJob, ProviderJobKind
from renpy_story_mapper.narrative_map.semantic_contracts import (
    BoundaryWindow,
    SemanticBoundaryDecision,
    SemanticBoundaryKind,
    SemanticClaimClass,
    SemanticSummary,
    SemanticSummaryClaim,
)
from renpy_story_mapper.narrative_map.validation import ValidationFinding

_BOUNDARY_FIELDS = frozenset({"candidate_id", "decision", "reason", "confidence", "warnings"})
_SUMMARY_FIELDS = frozenset(
    {
        "subject_kind",
        "subject_id",
        "membership_hash",
        "title",
        "summary",
        "characters",
        "claims",
        "warnings",
    }
)
_CLAIM_FIELDS = frozenset({"claim_class", "text", "evidence_ids"})
_TECHNICAL_TITLE = re.compile(
    r"(?:\b(?:atom|boundary|cache|cluster|evidence|job|label|line|menu|node|source)\b|"
    r"^(?:bg|cg|scene|show|hide|image)[ _:-]|\b\d+\s+(?:atoms?|lines?|items?|nodes?)\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SemanticBoundaryValidation:
    decisions: tuple[SemanticBoundaryDecision, ...]
    findings: tuple[ValidationFinding, ...]

    @property
    def valid(self) -> bool:
        return not self.findings


@dataclass(frozen=True)
class SemanticSummaryValidation:
    summary: SemanticSummary | None
    findings: tuple[ValidationFinding, ...]

    @property
    def valid(self) -> bool:
        return self.summary is not None and not self.findings


def validate_semantic_boundary_response(
    payload: object,
    job: PreparedNarrativeJob,
) -> SemanticBoundaryValidation:
    if job.kind is not ProviderJobKind.SEMANTIC_BOUNDARY_WINDOW or not isinstance(
        job.subject, BoundaryWindow
    ):
        raise ValueError("semantic boundary validation requires a boundary-window job")
    if not isinstance(payload, Mapping) or set(payload) != {"window_id", "decisions"}:
        return SemanticBoundaryValidation((), (ValidationFinding("invalid_envelope", job.job_id),))
    if payload.get("window_id") != job.subject.window_id:
        return SemanticBoundaryValidation((), (ValidationFinding("wrong_window", job.job_id),))
    raw = payload.get("decisions")
    if not isinstance(raw, list):
        return SemanticBoundaryValidation((), (ValidationFinding("invalid_decisions", job.job_id),))
    expected = job.subject.owned_candidate_ids
    supplied_ids = tuple(
        item.get("candidate_id") if isinstance(item, Mapping) else None for item in raw
    )
    if supplied_ids != expected or len(supplied_ids) != len(set(supplied_ids)):
        return SemanticBoundaryValidation(
            (), (ValidationFinding("inexact_candidate_coverage", job.job_id),)
        )
    decisions: list[SemanticBoundaryDecision] = []
    findings: list[ValidationFinding] = []
    for index, item in enumerate(raw):
        candidate_id = expected[index]
        if not isinstance(item, Mapping) or set(item) != _BOUNDARY_FIELDS:
            findings.append(ValidationFinding("invalid_decision_fields", candidate_id, index))
            continue
        decision_value = item.get("decision")
        reason = item.get("reason")
        confidence = item.get("confidence")
        warnings = item.get("warnings")
        try:
            decision = (
                SemanticBoundaryKind(decision_value) if isinstance(decision_value, str) else None
            )
        except ValueError:
            decision = None
        if decision is None:
            findings.append(ValidationFinding("invalid_decision", candidate_id, index))
            continue
        if not _text(reason, MAX_REASON_LENGTH):
            findings.append(ValidationFinding("invalid_reason", candidate_id, index))
            continue
        if (
            not isinstance(confidence, int | float)
            or isinstance(confidence, bool)
            or not math.isfinite(float(confidence))
            or not 0 <= float(confidence) <= 1
        ):
            findings.append(ValidationFinding("invalid_confidence", candidate_id, index))
            continue
        if not _text_list(warnings, MAX_REASON_LENGTH):
            findings.append(ValidationFinding("invalid_warnings", candidate_id, index))
            continue
        decisions.append(
            SemanticBoundaryDecision(
                candidate_id,
                decision,
                cast(str, reason),
                float(confidence),
                tuple(cast(list[str], warnings)),
            )
        )
    return SemanticBoundaryValidation(tuple(decisions), tuple(findings))


def validate_semantic_summary_response(
    payload: object,
    job: PreparedNarrativeJob,
) -> SemanticSummaryValidation:
    if job.kind is not ProviderJobKind.SEMANTIC_SUMMARY or job.membership_hash is None:
        raise ValueError("semantic summary validation requires a frozen-summary job")
    if not isinstance(payload, Mapping) or set(payload) != _SUMMARY_FIELDS:
        return SemanticSummaryValidation(None, (ValidationFinding("invalid_envelope", job.job_id),))
    subject_kind = payload.get("subject_kind")
    subject_id = payload.get("subject_id")
    membership_hash = payload.get("membership_hash")
    expected_kind = _subject_kind(job)
    if (
        subject_kind != expected_kind
        or subject_id != job.subject_id
        or membership_hash != job.membership_hash
    ):
        return SemanticSummaryValidation(None, (ValidationFinding("wrong_subject", job.job_id),))
    title = payload.get("title")
    summary_text = payload.get("summary")
    top_level_findings: list[ValidationFinding] = []
    title_valid = bool(
        _text(title, MAX_TITLE_LENGTH) and not _TECHNICAL_TITLE.search(cast(str, title))
    )
    if not title_valid:
        top_level_findings.append(ValidationFinding("invalid_title", job.job_id))
    summary_valid = bool(
        _text(summary_text, MAX_SUMMARY_LENGTH)
        and (
            not isinstance(title, str)
            or cast(str, summary_text).casefold() != title.casefold()
        )
    )
    if not summary_valid:
        top_level_findings.append(ValidationFinding("invalid_summary", job.job_id))
    characters = payload.get("characters")
    if not _text_list(characters, MAX_REASON_LENGTH) or any(
        item not in job.known_characters for item in cast(list[str], characters)
    ):
        top_level_findings.append(ValidationFinding("invalid_characters", job.job_id))
    warnings = payload.get("warnings")
    if not _text_list(warnings, MAX_REASON_LENGTH):
        top_level_findings.append(ValidationFinding("invalid_warnings", job.job_id))
    if top_level_findings:
        return SemanticSummaryValidation(None, tuple(top_level_findings))
    claims_value = payload.get("claims")
    if not isinstance(claims_value, list) or not claims_value:
        return SemanticSummaryValidation(None, (ValidationFinding("invalid_claims", job.job_id),))
    claims: list[SemanticSummaryClaim] = []
    claim_keys: set[tuple[str, str, tuple[str, ...]]] = set()
    for index, item in enumerate(claims_value):
        if not isinstance(item, Mapping) or set(item) != _CLAIM_FIELDS:
            return SemanticSummaryValidation(
                None, (ValidationFinding("invalid_claim_fields", job.subject_id, index),)
            )
        claim_class_value = item.get("claim_class")
        try:
            claim_class = (
                SemanticClaimClass(claim_class_value)
                if isinstance(claim_class_value, str)
                else None
            )
        except ValueError:
            claim_class = None
        text = item.get("text")
        evidence_ids = item.get("evidence_ids")
        if (
            claim_class is None
            or not _text(text, MAX_SUMMARY_LENGTH)
            or not _text_list(evidence_ids, MAX_REASON_LENGTH, allow_empty=False)
            or any(value not in job.known_evidence_ids for value in cast(list[str], evidence_ids))
        ):
            return SemanticSummaryValidation(
                None, (ValidationFinding("invalid_claim", job.subject_id, index),)
            )
        key = (
            claim_class.value,
            cast(str, text),
            tuple(cast(list[str], evidence_ids)),
        )
        if key in claim_keys:
            return SemanticSummaryValidation(
                None, (ValidationFinding("duplicate_claim", job.subject_id, index),)
            )
        claim_keys.add(key)
        claims.append(
            SemanticSummaryClaim(
                claim_class,
                cast(str, text),
                tuple(cast(list[str], evidence_ids)),
            )
        )
    return SemanticSummaryValidation(
        SemanticSummary(
            subject_kind,
            subject_id,
            membership_hash,
            cast(str, title),
            cast(str, summary_text),
            tuple(cast(list[str], characters)),
            tuple(claims),
            tuple(cast(list[str], warnings)),
        ),
        (),
    )


def _subject_kind(job: PreparedNarrativeJob) -> str:
    from renpy_story_mapper.narrative_map.semantic_contracts import (
        ChoiceComposition,
        MajorCluster,
        SemanticBeat,
    )

    if isinstance(job.subject, SemanticBeat):
        return "beat"
    if isinstance(job.subject, MajorCluster):
        return "major_cluster"
    if isinstance(job.subject, ChoiceComposition):
        return "choice"
    raise ValueError("semantic summary subject contract is invalid")


def _text(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str) and bool(value) and value == value.strip() and len(value) <= maximum
    )


def _text_list(value: object, maximum: int, *, allow_empty: bool = True) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and len(value) == len({item for item in value if isinstance(item, str)})
        and all(_text(item, maximum) for item in value)
    )
