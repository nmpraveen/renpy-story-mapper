"""Claim-local validation, one-shot repair, partial salvage, and contradiction review."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from renpy_story_mapper.narrative.contracts import (
    ArtifactPublication,
    ClaimClass,
    ClaimPolarity,
    ClaimSemantics,
    Coverage,
    JsonValue,
    LogicalJobKind,
    LogicalJobSpec,
    NarrativeArtifact,
    NarrativeClaim,
)
from renpy_story_mapper.narrative.evidence import HandleBindingError, PromptHandleTable

MAX_PROVIDER_CLAIMS = 256
_ARTIFACT_FIELDS = frozenset({"logical_job_id", "title", "summary", "claims"})
_CLAIM_FIELDS = frozenset(
    {
        "claim_class",
        "text",
        "evidence_handles",
        "child_claim_handles",
        "subject",
        "predicate",
        "polarity",
        "normalized_value",
    }
)
_REPAIR_FIELDS = frozenset({"logical_job_id", "title", "summary", "claims"})


class ValidationSeverity(StrEnum):
    CLAIM = "claim"
    FIELD = "field"
    REVIEW = "review"
    UNSAFE = "unsafe"


class ContradictionSeverity(StrEnum):
    AUTHORITY_VIOLATION = "authority_violation"
    REVIEW_WARNING = "review_warning"


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: ValidationSeverity
    ordinal: int | None = None


@dataclass(frozen=True)
class RepairRequest:
    """Bounded description of only the invalid portions; never a raw prompt or response."""

    logical_job_id: str
    whole_artifact: bool
    invalid_claim_ordinals: tuple[int, ...]
    invalid_fields: tuple[str, ...]
    issue_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "logical_job_id": self.logical_job_id,
            "whole_artifact": self.whole_artifact,
            "invalid_claim_ordinals": list(self.invalid_claim_ordinals),
            "invalid_fields": list(self.invalid_fields),
            "issue_codes": list(self.issue_codes),
        }


@dataclass(frozen=True)
class ValidationContext:
    job: LogicalJobSpec
    input_revision_id: str
    handles: PromptHandleTable
    deterministic_title: str
    deterministic_summary: str = "Narrative summary unavailable."
    expected_child_ids: tuple[str, ...] = ()
    available_child_ids: tuple[str, ...] = ()
    authority_claims: tuple[NarrativeClaim, ...] = ()

    def __post_init__(self) -> None:
        if not self.input_revision_id.strip():
            raise ValueError("validation requires an input revision ID")
        if not self.deterministic_title.strip():
            raise ValueError("validation requires a deterministic title fallback")
        if not self.deterministic_summary.strip():
            raise ValueError("validation requires a deterministic summary fallback")
        if len(self.expected_child_ids) != len(set(self.expected_child_ids)):
            raise ValueError("expected child IDs must be unique")
        if len(self.available_child_ids) != len(set(self.available_child_ids)):
            raise ValueError("available child IDs must be unique")
        if not set(self.available_child_ids) <= set(self.expected_child_ids):
            raise ValueError("available children must be expected by the logical job")
        if self.job.ordered_child_artifact_ids != self.expected_child_ids:
            raise ValueError("validation child order must match the logical job")
        if self.handles.scope_id != self.job.job_id:
            raise ValueError("prompt handles must be bound to the logical job")
        authority_ids = tuple(claim.claim_id for claim in self.authority_claims)
        if len(authority_ids) != len(set(authority_ids)):
            raise ValueError("validation authority claims must be unique")
        available_handles = {
            item.claim_id for item in self.handles.child_claim_handles
        }
        if not set(authority_ids) <= available_handles:
            raise ValueError("validation authority claims must be prompt-local children")
        if any(
            claim.job_kind is not LogicalJobKind.AUTHORITY_FACT
            or claim.claim_class is not ClaimClass.FACTUAL
            or claim.semantics is None
            for claim in self.authority_claims
        ):
            raise ValueError("validation authority claims must be normalized factual leaves")


@dataclass(frozen=True)
class SalvageResult:
    artifact: NarrativeArtifact | None
    issues: tuple[ValidationIssue, ...]
    repair_attempts: int
    rejected_reason: str | None = None

    @property
    def published(self) -> bool:
        return self.artifact is not None


RepairCallback = Callable[[RepairRequest], object]


@dataclass(frozen=True)
class _PassResult:
    artifact: NarrativeArtifact | None
    issues: tuple[ValidationIssue, ...]
    whole_artifact_invalid: bool
    invalid_fields: tuple[str, ...]
    rejected_reason: str | None = None


def validate_and_salvage(
    raw: object,
    context: ValidationContext,
    *,
    repair: RepairCallback | None = None,
) -> SalvageResult:
    """Validate every claim independently and invoke at most one targeted repair."""

    first = _validate_once(raw, context)
    repair_attempts = 0
    current = first
    repairable = tuple(
        issue for issue in first.issues if issue.severity is not ValidationSeverity.REVIEW
    )
    if (
        repair is not None
        and repairable
        and first.rejected_reason != "authority_binding_invalid"
    ):
        request = _repair_request(first, context)
        repair_attempts = 1
        try:
            repaired = repair(request)
        except Exception:
            current = _with_issue(
                first,
                ValidationIssue("repair_request_failed", ValidationSeverity.FIELD),
            )
        else:
            merged = _merge_repair(raw, repaired, request)
            current = _validate_once(merged, context)
            if any(
                issue.severity is not ValidationSeverity.REVIEW
                for issue in current.issues
            ):
                current = _with_issue(
                    current,
                    ValidationIssue("repair_exhausted", ValidationSeverity.FIELD),
                )
    return SalvageResult(
        current.artifact,
        current.issues,
        repair_attempts,
        current.rejected_reason,
    )


def _validate_once(raw: object, context: ValidationContext) -> _PassResult:
    if not isinstance(raw, Mapping) or set(raw) != _ARTIFACT_FIELDS:
        issue = ValidationIssue("unparseable_core_output", ValidationSeverity.UNSAFE)
        return _PassResult(None, (issue,), True, (), "unparseable_core_output")
    logical_job_id = raw.get("logical_job_id")
    if logical_job_id != context.job.job_id:
        issue = ValidationIssue("authority_binding_invalid", ValidationSeverity.UNSAFE)
        return _PassResult(None, (issue,), True, (), "authority_binding_invalid")
    raw_claims = raw.get("claims")
    if not isinstance(raw_claims, list) or len(raw_claims) > MAX_PROVIDER_CLAIMS:
        issue = ValidationIssue("unparseable_claim_array", ValidationSeverity.UNSAFE)
        return _PassResult(None, (issue,), True, (), "unparseable_core_output")

    issues: list[ValidationIssue] = []
    invalid_fields: list[str] = []
    title, title_fallback = _bounded_text(raw.get("title"), 200)
    if title is None:
        title = context.deterministic_title
        title_fallback = True
        invalid_fields.append("title")
        issues.append(ValidationIssue("invalid_ai_title", ValidationSeverity.FIELD))
    summary, summary_fallback = _bounded_text(raw.get("summary"), 4_000)
    if summary is None:
        summary = context.deterministic_summary
        summary_fallback = True
        invalid_fields.append("summary")
        issues.append(ValidationIssue("invalid_ai_summary", ValidationSeverity.FIELD))

    claims: list[NarrativeClaim] = []
    seen_assertions: set[tuple[object, ...]] = set()
    for ordinal, raw_claim in enumerate(raw_claims):
        try:
            claim = _validate_claim(raw_claim, ordinal, context)
            assertion = (
                claim.claim_class,
                claim.text,
                claim.support,
                claim.semantics,
            )
            if assertion in seen_assertions:
                raise ValueError("duplicate normalized claim")
            seen_assertions.add(assertion)
        except (HandleBindingError, TypeError, ValueError):
            issues.append(
                ValidationIssue("invalid_or_unsupported_claim", ValidationSeverity.CLAIM, ordinal)
            )
        else:
            claims.append(claim)

    claims, contradiction_issues = _salvage_contextual_contradictions(claims, context)
    issues.extend(contradiction_issues)

    if not claims:
        issue = ValidationIssue("no_safe_claims", ValidationSeverity.UNSAFE)
        return _PassResult(
            None,
            (*issues, issue),
            False,
            tuple(invalid_fields),
            "no_safe_claims",
        )

    missing = tuple(
        child_id
        for child_id in context.expected_child_ids
        if child_id not in set(context.available_child_ids)
    )
    invalid_count = sum(issue.severity is ValidationSeverity.CLAIM for issue in issues)
    coverage = Coverage(
        expected_child_ids=context.expected_child_ids,
        available_child_ids=context.available_child_ids,
        missing_child_ids=missing,
        valid_claim_count=len(claims),
        invalid_claim_count=invalid_count,
    )
    partial = bool(
        missing
        or any(issue.severity is not ValidationSeverity.REVIEW for issue in issues)
    )
    warnings: list[str] = []
    if invalid_count:
        warnings.append(f"{invalid_count} invalid claim(s) omitted")
    if title_fallback:
        warnings.append("AI title invalid; deterministic M11 title retained")
    if summary_fallback:
        warnings.append("AI summary invalid; deterministic fallback retained")
    if missing:
        percentage = coverage.child_coverage_basis_points / 100
        warnings.append(f"Child coverage is {percentage:g}%")
    if any(issue.severity is ValidationSeverity.REVIEW for issue in issues):
        warnings.append("Interpretive disagreement requires review")
    artifact = NarrativeArtifact(
        logical_job_id=context.job.job_id,
        input_revision_id=context.input_revision_id,
        job_kind=context.job.kind,
        publication=(ArtifactPublication.PARTIAL if partial else ArtifactPublication.COMPLETE),
        title=title,
        summary=summary,
        claims=tuple(claims),
        coverage=coverage,
        warnings=tuple(warnings),
        used_deterministic_title=title_fallback,
    )
    return _PassResult(
        artifact,
        tuple(issues),
        False,
        tuple(invalid_fields),
    )


def _validate_claim(
    raw: object, ordinal: int, context: ValidationContext
) -> NarrativeClaim:
    if not isinstance(raw, Mapping) or set(raw) != _CLAIM_FIELDS:
        raise ValueError("claim shape is invalid")
    claim_class = ClaimClass(_required_text(raw, "claim_class", 40))
    polarity = ClaimPolarity(_required_text(raw, "polarity", 40))
    evidence_handles = _handle_tuple(raw.get("evidence_handles"), "evidence_handles")
    child_handles = _handle_tuple(raw.get("child_claim_handles"), "child_claim_handles")
    support = context.handles.resolve_support(
        evidence_handles=evidence_handles,
        child_claim_handles=child_handles,
    )
    semantics = ClaimSemantics(
        subject=_required_text(raw, "subject", 320),
        predicate=_required_text(raw, "predicate", 320),
        polarity=polarity,
        normalized_value=_required_text(raw, "normalized_value", 320),
    )
    claim = NarrativeClaim(
        logical_job_id=context.job.job_id,
        job_kind=context.job.kind,
        ordinal=ordinal,
        claim_class=claim_class,
        text=_required_text(raw, "text", 1_000),
        support=support,
        semantics=semantics,
    )
    _validate_exact_authority_claim(claim, context.authority_claims)
    return claim


def _validate_exact_authority_claim(
    claim: NarrativeClaim,
    authority_claims: tuple[NarrativeClaim, ...],
) -> None:
    """Prevent factual paraphrase from changing exact M12 status or prerequisite authority."""

    if not authority_claims or claim.claim_class is not ClaimClass.FACTUAL:
        return
    authority_by_id = {item.claim_id: item for item in authority_claims}
    cited = tuple(
        authority_by_id[item]
        for item in claim.support.child_claim_ids
        if item in authority_by_id
    )
    if cited:
        if len(cited) != 1:
            raise ValueError("one factual claim cannot combine exact M12 authority claims")
        exact = cited[0]
        if claim.text != exact.text or claim.semantics != exact.semantics:
            raise ValueError("factual M12 claims must preserve exact authority language")
    semantics = claim.semantics
    assert semantics is not None
    for exact in authority_claims:
        exact_semantics = exact.semantics
        assert exact_semantics is not None
        if (
            semantics.subject.casefold() == exact_semantics.subject.casefold()
            and semantics.predicate.casefold() == exact_semantics.predicate.casefold()
            and (
                semantics.polarity is not exact_semantics.polarity
                or semantics.normalized_value.casefold()
                != exact_semantics.normalized_value.casefold()
            )
        ):
            raise ValueError("factual M12 semantics contradict exact authority")


def _salvage_contextual_contradictions(
    claims: list[NarrativeClaim],
    context: ValidationContext,
) -> tuple[list[NarrativeClaim], tuple[ValidationIssue, ...]]:
    """Omit only later same-context factual conflicts and retain interpretive warnings."""

    findings = contradiction_findings(
        tuple(ContextualClaim(claim, context.job) for claim in claims)
    )
    by_id = {claim.claim_id: claim for claim in claims}
    omitted: set[str] = set()
    issues: list[ValidationIssue] = []
    review_pairs: set[tuple[str, str]] = set()
    for finding in findings:
        if finding.severity is ContradictionSeverity.REVIEW_WARNING:
            pair = (
                min(finding.left_claim_id, finding.right_claim_id),
                max(finding.left_claim_id, finding.right_claim_id),
            )
            if pair not in review_pairs:
                review_pairs.add(pair)
                issues.append(
                    ValidationIssue(
                        "interpretive_disagreement",
                        ValidationSeverity.REVIEW,
                    )
                )
            continue
        right = by_id[finding.right_claim_id]
        if right.claim_id in omitted:
            continue
        omitted.add(right.claim_id)
        issues.append(
            ValidationIssue(
                "factual_contradiction_omitted",
                ValidationSeverity.CLAIM,
                right.ordinal,
            )
        )
    return [claim for claim in claims if claim.claim_id not in omitted], tuple(issues)


def _repair_request(result: _PassResult, context: ValidationContext) -> RepairRequest:
    invalid_ordinals = tuple(
        issue.ordinal
        for issue in result.issues
        if issue.ordinal is not None and issue.severity is ValidationSeverity.CLAIM
    )
    return RepairRequest(
        logical_job_id=context.job.job_id,
        whole_artifact=result.whole_artifact_invalid,
        invalid_claim_ordinals=invalid_ordinals,
        invalid_fields=result.invalid_fields,
        issue_codes=tuple(dict.fromkeys(issue.code for issue in result.issues)),
    )


def _merge_repair(original: object, repaired: object, request: RepairRequest) -> object:
    if request.whole_artifact:
        return repaired
    if not isinstance(original, Mapping) or not isinstance(repaired, Mapping):
        return original
    if (
        not set(repaired) <= _REPAIR_FIELDS
        or repaired.get("logical_job_id") != request.logical_job_id
    ):
        return original
    merged = dict(original)
    for field in request.invalid_fields:
        if field in repaired:
            merged[field] = repaired[field]
    replacements = repaired.get("claims", ())
    if not isinstance(replacements, list):
        return merged
    claims = merged.get("claims")
    if not isinstance(claims, list):
        return original
    mutable_claims = list(claims)
    allowed = set(request.invalid_claim_ordinals)
    seen: set[int] = set()
    for replacement in replacements:
        if not isinstance(replacement, Mapping):
            continue
        ordinal = replacement.get("ordinal")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool):
            continue
        if ordinal not in allowed or ordinal in seen or not 0 <= ordinal < len(mutable_claims):
            continue
        value = {key: item for key, item in replacement.items() if key != "ordinal"}
        mutable_claims[ordinal] = value
        seen.add(ordinal)
    merged["claims"] = mutable_claims
    return merged


def _with_issue(result: _PassResult, issue: ValidationIssue) -> _PassResult:
    artifact = result.artifact
    if artifact is not None:
        warnings = (*artifact.warnings, issue.code.replace("_", " "))
        artifact = NarrativeArtifact(
            logical_job_id=artifact.logical_job_id,
            input_revision_id=artifact.input_revision_id,
            job_kind=artifact.job_kind,
            publication=ArtifactPublication.PARTIAL,
            title=artifact.title,
            summary=artifact.summary,
            claims=artifact.claims,
            coverage=Coverage(
                expected_child_ids=artifact.coverage.expected_child_ids,
                available_child_ids=artifact.coverage.available_child_ids,
                missing_child_ids=artifact.coverage.missing_child_ids,
                valid_claim_count=artifact.coverage.valid_claim_count,
                invalid_claim_count=max(1, artifact.coverage.invalid_claim_count),
            ),
            warnings=tuple(dict.fromkeys(warnings)),
            used_deterministic_title=artifact.used_deterministic_title,
        )
    return _PassResult(
        artifact,
        (*result.issues, issue),
        result.whole_artifact_invalid,
        result.invalid_fields,
        result.rejected_reason,
    )


@dataclass(frozen=True)
class ContradictionIdentity:
    """Full contextual identity required for a single normalized assertion."""

    lane_id: str | None
    route_id: str | None
    scene_id: str | None
    chapter_id: str | None
    temporal_anchor: str | None
    occurrence_id: str | None
    call_site_id: str | None
    claim_class: ClaimClass
    subject: str
    predicate: str
    polarity: ClaimPolarity
    normalized_value: str

    @property
    def comparison_scope(self) -> tuple[object, ...]:
        return (
            self.lane_id,
            self.route_id,
            self.scene_id,
            self.chapter_id,
            self.temporal_anchor,
            self.occurrence_id,
            self.call_site_id,
            self.claim_class,
            self.subject,
            self.predicate,
        )


@dataclass(frozen=True)
class ContextualClaim:
    claim: NarrativeClaim
    job: LogicalJobSpec

    def identity(self) -> ContradictionIdentity:
        semantics = self.claim.semantics
        if semantics is None:
            raise ValueError("contextual contradiction checks require normalized claim semantics")
        context = self.job.context
        return ContradictionIdentity(
            lane_id=context.lane_id,
            route_id=context.route_id,
            scene_id=(self.job.owner_id if self.job.kind is LogicalJobKind.SCENE else None),
            chapter_id=context.chapter_id,
            temporal_anchor=context.temporal_anchor,
            occurrence_id=context.occurrence_id,
            call_site_id=context.call_site_id,
            claim_class=self.claim.claim_class,
            subject=semantics.subject.casefold(),
            predicate=semantics.predicate.casefold(),
            polarity=semantics.polarity,
            normalized_value=semantics.normalized_value.casefold(),
        )


@dataclass(frozen=True)
class ContradictionFinding:
    severity: ContradictionSeverity
    left_claim_id: str
    right_claim_id: str
    left_identity: ContradictionIdentity
    right_identity: ContradictionIdentity


def contradiction_findings(
    claims: tuple[ContextualClaim, ...],
) -> tuple[ContradictionFinding, ...]:
    """Find disagreements only inside identical route and temporal context."""

    identities = tuple((item.claim.claim_id, item.identity()) for item in claims)
    findings: list[ContradictionFinding] = []
    for index, (left_claim_id, left) in enumerate(identities):
        for right_claim_id, right in identities[index + 1 :]:
            if left.comparison_scope != right.comparison_scope:
                continue
            if (
                left.polarity is right.polarity
                and left.normalized_value == right.normalized_value
            ):
                continue
            severity = (
                ContradictionSeverity.AUTHORITY_VIOLATION
                if left.claim_class is ClaimClass.FACTUAL
                else ContradictionSeverity.REVIEW_WARNING
            )
            findings.append(
                ContradictionFinding(
                    severity,
                    left_claim_id,
                    right_claim_id,
                    left,
                    right,
                )
            )
    return tuple(findings)


def _required_text(owner: Mapping[object, object], key: str, maximum: int) -> str:
    value = owner.get(key)
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{key} must be a non-empty trimmed string")
    if len(value) > maximum:
        raise ValueError(f"{key} exceeds its deterministic bound")
    return value


def _bounded_text(value: object, maximum: int) -> tuple[str | None, bool]:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        return None, True
    if len(value) > maximum:
        return None, True
    return value, False


def _handle_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        raise TypeError(f"{label} must be an array")
    if any(not isinstance(item, str) for item in value):
        raise TypeError(f"{label} must contain strings")
    return tuple(value)
