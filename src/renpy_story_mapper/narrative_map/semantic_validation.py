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
    ProposedBeatGroup,
    ProposedMajorCluster,
    SemanticBoundaryDecision,
    SemanticBoundaryKind,
    SemanticClaimClass,
    SemanticPresentationRole,
    SemanticSummary,
    SemanticSummaryClaim,
    WholeScopeEditorialBatch,
    WholeScopeEditorialRecord,
    WholeScopeHierarchyProposal,
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
_HIERARCHY_FIELDS = frozenset(
    {"scope_id", "beat_groups", "major_clusters", "uncertain_unit_ids", "warnings"}
)
_PROPOSED_BEAT_FIELDS = frozenset(
    {"proposal_key", "ordered_unit_ids", "confidence", "reason", "warnings"}
)
_PROPOSED_CLUSTER_FIELDS = frozenset(
    {"proposal_key", "ordered_beat_keys", "confidence", "reason", "warnings"}
)
_EDITORIAL_BATCH_FIELDS = frozenset({"scope_id", "hierarchy_hash", "records", "warnings"})
_EDITORIAL_RECORD_FIELDS = frozenset(
    {
        "subject_kind",
        "subject_id",
        "membership_hash",
        "presentation_role",
        "title",
        "summary",
        "characters",
        "claims",
        "warnings",
    }
)
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


@dataclass(frozen=True)
class WholeScopeHierarchyValidation:
    proposal: WholeScopeHierarchyProposal | None
    findings: tuple[ValidationFinding, ...]

    @property
    def valid(self) -> bool:
        return self.proposal is not None and not self.findings


@dataclass(frozen=True)
class WholeScopeEditorialValidation:
    batch: WholeScopeEditorialBatch | None
    valid_records: tuple[WholeScopeEditorialRecord, ...]
    findings: tuple[ValidationFinding, ...]

    @property
    def valid(self) -> bool:
        return self.batch is not None and not self.findings


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


def validate_whole_scope_hierarchy_response(
    payload: object,
    job: PreparedNarrativeJob,
) -> WholeScopeHierarchyValidation:
    from renpy_story_mapper.narrative_map.provider import WholeScopeProviderSubject
    from renpy_story_mapper.narrative_map.semantic_contracts import WholeScopeSemanticStage

    subject = job.subject
    if (
        job.kind is not ProviderJobKind.WHOLE_SCOPE_HIERARCHY
        or not isinstance(subject, WholeScopeProviderSubject)
        or subject.stage is not WholeScopeSemanticStage.HIERARCHY
    ):
        raise ValueError("whole-scope hierarchy validation requires a Stage H job")
    if not isinstance(payload, Mapping) or set(payload) != _HIERARCHY_FIELDS:
        return WholeScopeHierarchyValidation(
            None, (ValidationFinding("invalid_envelope", job.job_id),)
        )
    if payload.get("scope_id") != subject.scope_id:
        return WholeScopeHierarchyValidation(
            None, (ValidationFinding("wrong_scope", job.job_id),)
        )
    uncertain = payload.get("uncertain_unit_ids")
    warnings = payload.get("warnings")
    if not _text_list(uncertain, MAX_REASON_LENGTH):
        return WholeScopeHierarchyValidation(
            None, (ValidationFinding("invalid_uncertain_units", job.job_id),)
        )
    if cast(list[str], uncertain):
        return WholeScopeHierarchyValidation(
            None, (ValidationFinding("uncertain_membership", job.job_id),)
        )
    if not _text_list(warnings, MAX_REASON_LENGTH):
        return WholeScopeHierarchyValidation(
            None, (ValidationFinding("invalid_warnings", job.job_id),)
        )
    raw_beats = payload.get("beat_groups")
    raw_clusters = payload.get("major_clusters")
    if not isinstance(raw_beats, list) or not isinstance(raw_clusters, list):
        return WholeScopeHierarchyValidation(
            None, (ValidationFinding("invalid_hierarchy_arrays", job.job_id),)
        )
    beats: list[ProposedBeatGroup] = []
    findings: list[ValidationFinding] = []
    for index, item in enumerate(raw_beats):
        if not isinstance(item, Mapping) or set(item) != _PROPOSED_BEAT_FIELDS:
            findings.append(ValidationFinding("invalid_beat_group", job.job_id, index))
            continue
        try:
            beats.append(
                ProposedBeatGroup(
                    cast(str, item.get("proposal_key")),
                    tuple(cast(list[str], item.get("ordered_unit_ids"))),
                    float(cast(float, item.get("confidence"))),
                    cast(str, item.get("reason")),
                    tuple(cast(list[str], item.get("warnings"))),
                )
            )
        except (TypeError, ValueError):
            findings.append(ValidationFinding("invalid_beat_group", job.job_id, index))
    flattened = tuple(unit_id for beat in beats for unit_id in beat.ordered_unit_ids)
    if len(flattened) != len(set(flattened)):
        findings.append(ValidationFinding("duplicate_unit", job.job_id))
    if any(unit_id not in subject.ordered_unit_ids for unit_id in flattened):
        findings.append(ValidationFinding("foreign_unit", job.job_id))
    if flattened != subject.ordered_unit_ids:
        findings.append(ValidationFinding("inexact_unit_coverage", job.job_id))
    clusters: list[ProposedMajorCluster] = []
    for index, item in enumerate(raw_clusters):
        if not isinstance(item, Mapping) or set(item) != _PROPOSED_CLUSTER_FIELDS:
            findings.append(ValidationFinding("invalid_major_cluster", job.job_id, index))
            continue
        try:
            clusters.append(
                ProposedMajorCluster(
                    cast(str, item.get("proposal_key")),
                    tuple(cast(list[str], item.get("ordered_beat_keys"))),
                    float(cast(float, item.get("confidence"))),
                    cast(str, item.get("reason")),
                    tuple(cast(list[str], item.get("warnings"))),
                )
            )
        except (TypeError, ValueError):
            findings.append(ValidationFinding("invalid_major_cluster", job.job_id, index))
    beat_keys = tuple(item.proposal_key for item in beats)
    cluster_beat_keys = tuple(
        beat_key for cluster in clusters for beat_key in cluster.ordered_beat_keys
    )
    if cluster_beat_keys != beat_keys or len(cluster_beat_keys) != len(set(cluster_beat_keys)):
        findings.append(ValidationFinding("inexact_cluster_coverage", job.job_id))
    if findings:
        return WholeScopeHierarchyValidation(None, tuple(dict.fromkeys(findings)))
    try:
        proposal = WholeScopeHierarchyProposal(
            subject.scope_id,
            tuple(beats),
            tuple(clusters),
            (),
            tuple(cast(list[str], warnings)),
        )
    except ValueError:
        return WholeScopeHierarchyValidation(
            None, (ValidationFinding("invalid_hierarchy", job.job_id),)
        )
    return WholeScopeHierarchyValidation(proposal, ())


def validate_whole_scope_editorial_response(
    payload: object,
    job: PreparedNarrativeJob,
) -> WholeScopeEditorialValidation:
    from renpy_story_mapper.narrative_map.provider import WholeScopeProviderSubject
    from renpy_story_mapper.narrative_map.semantic_contracts import WholeScopeSemanticStage

    subject = job.subject
    if (
        job.kind is not ProviderJobKind.WHOLE_SCOPE_EDITORIAL
        or not isinstance(subject, WholeScopeProviderSubject)
        or subject.stage is not WholeScopeSemanticStage.EDITORIAL
    ):
        raise ValueError("whole-scope editorial validation requires a Stage E job")
    if not isinstance(payload, Mapping) or set(payload) != _EDITORIAL_BATCH_FIELDS:
        return WholeScopeEditorialValidation(
            None, (), (ValidationFinding("invalid_envelope", job.job_id),)
        )
    if payload.get("scope_id") != subject.scope_id:
        return WholeScopeEditorialValidation(
            None, (), (ValidationFinding("wrong_scope", job.job_id),)
        )
    if payload.get("hierarchy_hash") != subject.hierarchy_hash:
        return WholeScopeEditorialValidation(
            None, (), (ValidationFinding("stale_hierarchy", job.job_id),)
        )
    warnings = payload.get("warnings")
    raw_records = payload.get("records")
    if not _text_list(warnings, MAX_REASON_LENGTH) or not isinstance(raw_records, list):
        return WholeScopeEditorialValidation(
            None, (), (ValidationFinding("invalid_editorial_batch", job.job_id),)
        )
    expected = tuple(item.identity for item in subject.editorial_subjects)
    supplied = tuple(
        f"{item.get('subject_kind')}:{item.get('subject_id')}"
        if isinstance(item, Mapping)
        else ""
        for item in raw_records
    )
    findings: list[ValidationFinding] = []
    if len(supplied) != len(set(supplied)):
        findings.append(ValidationFinding("duplicate_subject", job.job_id))
    if any(identity not in expected for identity in supplied):
        findings.append(ValidationFinding("foreign_subject", job.job_id))
    if supplied != expected:
        findings.append(ValidationFinding("inexact_subject_coverage", job.job_id))
    expected_by_identity = {item.identity: item for item in subject.editorial_subjects}
    records: list[WholeScopeEditorialRecord] = []
    for index, item in enumerate(raw_records):
        identity = supplied[index]
        exact = expected_by_identity.get(identity)
        if exact is None:
            continue
        record, record_findings = _whole_scope_editorial_record(item, exact, index)
        findings.extend(record_findings)
        if record is not None:
            records.append(record)
    if findings or len(records) != len(expected):
        return WholeScopeEditorialValidation(
            None, tuple(records), tuple(dict.fromkeys(findings))
        )
    batch = WholeScopeEditorialBatch(
        subject.scope_id,
        cast(str, subject.hierarchy_hash),
        tuple(records),
        tuple(cast(list[str], warnings)),
    )
    return WholeScopeEditorialValidation(batch, tuple(records), ())


def _whole_scope_editorial_record(
    value: object,
    expected: object,
    index: int,
) -> tuple[WholeScopeEditorialRecord | None, tuple[ValidationFinding, ...]]:
    from renpy_story_mapper.narrative_map.provider import WholeScopeEditorialSubject

    if not isinstance(expected, WholeScopeEditorialSubject):
        raise TypeError("whole-scope editorial subject contract is invalid")
    if not isinstance(value, Mapping) or set(value) != _EDITORIAL_RECORD_FIELDS:
        return None, (ValidationFinding("invalid_editorial_record", expected.subject_id, index),)
    if (
        value.get("subject_kind") != expected.subject_kind
        or value.get("subject_id") != expected.subject_id
        or value.get("membership_hash") != expected.membership_hash
    ):
        return None, (ValidationFinding("stale_subject", expected.subject_id, index),)
    title = value.get("title")
    summary = value.get("summary")
    characters = value.get("characters")
    warnings = value.get("warnings")
    role_value = value.get("presentation_role")
    try:
        role = SemanticPresentationRole(cast(str, role_value))
    except (TypeError, ValueError):
        role = None
    findings: list[ValidationFinding] = []
    if not _text(title, MAX_TITLE_LENGTH) or _TECHNICAL_TITLE.search(cast(str, title)):
        findings.append(ValidationFinding("invalid_title", expected.subject_id, index))
    if (
        not _text(summary, MAX_SUMMARY_LENGTH)
        or (isinstance(title, str) and cast(str, summary).casefold() == title.casefold())
    ):
        findings.append(ValidationFinding("invalid_summary", expected.subject_id, index))
    if role is None:
        findings.append(ValidationFinding("invalid_presentation_role", expected.subject_id, index))
    if not _text_list(characters, MAX_REASON_LENGTH) or any(
        character not in expected.known_characters
        for character in cast(list[str], characters)
    ):
        findings.append(ValidationFinding("invalid_characters", expected.subject_id, index))
    if not _text_list(warnings, MAX_REASON_LENGTH):
        findings.append(ValidationFinding("invalid_warnings", expected.subject_id, index))
    claims_value = value.get("claims")
    claims: list[SemanticSummaryClaim] = []
    claim_keys: set[tuple[str, str, tuple[str, ...]]] = set()
    if not isinstance(claims_value, list) or not claims_value:
        findings.append(ValidationFinding("invalid_claims", expected.subject_id, index))
    else:
        for claim_index, claim in enumerate(claims_value):
            if not isinstance(claim, Mapping) or set(claim) != _CLAIM_FIELDS:
                findings.append(
                    ValidationFinding("invalid_claim_fields", expected.subject_id, claim_index)
                )
                continue
            try:
                claim_class = SemanticClaimClass(cast(str, claim.get("claim_class")))
            except (TypeError, ValueError):
                claim_class = None
            text = claim.get("text")
            evidence_ids = claim.get("evidence_ids")
            if (
                claim_class is None
                or not _text(text, MAX_SUMMARY_LENGTH)
                or not _text_list(evidence_ids, MAX_REASON_LENGTH, allow_empty=False)
                or any(
                    evidence_id not in expected.evidence_ids
                    for evidence_id in cast(list[str], evidence_ids)
                )
            ):
                findings.append(
                    ValidationFinding("invalid_claim", expected.subject_id, claim_index)
                )
                continue
            key = (
                claim_class.value,
                cast(str, text),
                tuple(cast(list[str], evidence_ids)),
            )
            if key in claim_keys:
                findings.append(
                    ValidationFinding("duplicate_claim", expected.subject_id, claim_index)
                )
                continue
            claim_keys.add(key)
            claims.append(SemanticSummaryClaim(claim_class, key[1], key[2]))
    if findings:
        return None, tuple(findings)
    return (
        WholeScopeEditorialRecord(
            expected.subject_kind,
            expected.subject_id,
            expected.membership_hash,
            cast(SemanticPresentationRole, role),
            cast(str, title),
            cast(str, summary),
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
