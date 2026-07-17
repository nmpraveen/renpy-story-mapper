"""Claim-local validation, one-shot repair, partial salvage, and contradiction review."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from renpy_story_mapper.narrative.contracts import (
    ArtifactPublication,
    ClaimClass,
    ClaimContextScope,
    ClaimPolarity,
    ClaimSemantics,
    ClaimSupport,
    Coverage,
    JsonValue,
    LogicalJobKind,
    LogicalJobSpec,
    NarrativeArtifact,
    NarrativeClaim,
    StructuralContext,
    SupportKind,
    canonical_hash,
)
from renpy_story_mapper.narrative.evidence import HandleBindingError, PromptHandleTable

MAX_PROVIDER_CLAIMS = 256
MAX_PUBLISHED_CLAIMS = 256
_ARTIFACT_FIELDS = frozenset({"logical_job_id", "title", "summary", "claims"})
_CLAIM_FIELDS = frozenset(
    {
        "claim_class",
        "context_scope",
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
    claim_contexts: tuple[tuple[str, StructuralContext], ...] = ()
    claim_context_scopes: tuple[tuple[str, ClaimContextScope], ...] = ()

    def __post_init__(self) -> None:
        embedded_authority = getattr(self.handles, "authority_claims", ())
        if not self.authority_claims and embedded_authority:
            object.__setattr__(self, "authority_claims", tuple(embedded_authority))
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
        available_evidence = {
            item.reference for item in self.handles.evidence_handles
        }
        for claim in self.authority_claims:
            if claim.claim_id in available_handles:
                continue
            if (
                claim.support.kind is SupportKind.DIRECT_EVIDENCE
                and claim.support.direct_evidence
                and set(claim.support.direct_evidence) <= available_evidence
            ):
                continue
            raise ValueError(
                "validation authority claims must be prompt-local children or evidence"
            )
        if any(
            claim.claim_class is not ClaimClass.FACTUAL
            or claim.semantics is None
            for claim in self.authority_claims
        ):
            raise ValueError("validation authority claims must be normalized exact factual claims")
        contextual_ids = tuple(claim_id for claim_id, _context in self.claim_contexts)
        if len(contextual_ids) != len(set(contextual_ids)):
            raise ValueError("validation claim contexts must have unique claim IDs")
        if not set(contextual_ids) <= available_handles:
            raise ValueError("validation claim contexts must be prompt-local children")
        scoped_ids = tuple(claim_id for claim_id, _scope in self.claim_context_scopes)
        if len(scoped_ids) != len(set(scoped_ids)):
            raise ValueError("validation claim context scopes must have unique claim IDs")
        if not set(scoped_ids) <= available_handles:
            raise ValueError("validation claim context scopes must be prompt-local children")

    def context_for_claim(self, claim: NarrativeClaim) -> StructuralContext | None:
        """Resolve one claim's immediate child context without flattening its provenance."""

        contexts = self.contexts_for_claim(claim)
        if not contexts:
            return None
        unique = {
            canonical_hash(context.to_dict()): context
            for context in contexts
        }
        ordered = tuple(unique[key] for key in sorted(unique))
        if len(ordered) == 1:
            return ordered[0]
        support_hash = canonical_hash([context.to_dict() for context in ordered])

        def shared(name: str) -> str | None:
            values = {getattr(context, name) for context in ordered}
            return next(iter(values)) if len(values) == 1 else None

        temporal_anchor = shared("temporal_anchor")
        if temporal_anchor is None:
            temporal_anchor = f"support-set:{support_hash[:24]}"
        return StructuralContext(
            chapter_id=shared("chapter_id"),
            lane_id=shared("lane_id"),
            route_id=shared("route_id"),
            temporary_container_id=shared("temporary_container_id"),
            temporary_arm_id=shared("temporary_arm_id"),
            occurrence_id=shared("occurrence_id"),
            call_site_id=shared("call_site_id"),
            loop_id=shared("loop_id"),
            temporal_anchor=temporal_anchor,
            structural_fingerprint=f"support-set:{support_hash}",
        )

    def contexts_for_claim(self, claim: NarrativeClaim) -> tuple[StructuralContext, ...]:
        """Return unique immediate child contexts in stable order."""

        by_id = dict(self.claim_contexts)
        unique = {
            canonical_hash(by_id[claim_id].to_dict()): by_id[claim_id]
            for claim_id in claim.support.child_claim_ids
            if claim_id in by_id
        }
        return tuple(unique[key] for key in sorted(unique))

    def inherited_scopes_for_claim(
        self, claim: NarrativeClaim
    ) -> tuple[ClaimContextScope, ...]:
        """Return immediate child scopes so comparisons cannot be re-atomized."""

        by_id = dict(self.claim_context_scopes)
        return tuple(
            dict.fromkeys(
                by_id[claim_id]
                for claim_id in claim.support.child_claim_ids
                if claim_id in by_id
            )
        )


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
    claims, limit_issues = _ensure_exact_authority_claims(claims, context)
    issues.extend(limit_issues)

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


def _ensure_exact_authority_claims(
    claims: list[NarrativeClaim],
    context: ValidationContext,
) -> tuple[list[NarrativeClaim], tuple[ValidationIssue, ...]]:
    """Publish every exact M12 leaf as a deterministic parent claim when omitted by AI."""

    if not context.authority_claims:
        return claims, ()
    represented: set[str] = set()
    authority_by_id = {claim.claim_id: claim for claim in context.authority_claims}
    for claim in claims:
        if claim.claim_class is not ClaimClass.FACTUAL:
            continue
        for exact in context.authority_claims:
            if _claim_represents_exact_authority(claim, exact):
                represented.add(exact.claim_id)
    next_ordinal = max((claim.ordinal for claim in claims), default=-1) + 1
    result = list(claims)
    for exact in context.authority_claims:
        if exact.claim_id in represented:
            continue
        support = (
            exact.support
            if exact.support.kind is SupportKind.DIRECT_EVIDENCE
            and exact.claim_id not in {
                item.claim_id for item in context.handles.child_claim_handles
            }
            else ClaimSupport(
                kind=SupportKind.CHILD_CLAIMS,
                child_claim_ids=(exact.claim_id,),
            )
        )
        result.append(
            NarrativeClaim(
                logical_job_id=context.job.job_id,
                job_kind=context.job.kind,
                ordinal=next_ordinal,
                claim_class=ClaimClass.FACTUAL,
                context_scope=exact.context_scope,
                text=exact.text,
                support=support,
                semantics=exact.semantics,
            )
        )
        next_ordinal += 1

    authority_ids = set(authority_by_id)
    mandatory_by_authority: dict[str, NarrativeClaim] = {}
    optional: list[NarrativeClaim] = []
    represented_ids: set[str] = set()
    issues: list[ValidationIssue] = []
    for claim in result:
        cited = tuple(
            exact.claim_id
            for exact in context.authority_claims
            if _claim_represents_exact_authority(claim, exact)
        )
        if cited and claim.claim_class is ClaimClass.FACTUAL:
            authority_id = cited[0]
            if authority_id in mandatory_by_authority:
                issues.append(
                    ValidationIssue(
                        "duplicate_authority_representation",
                        ValidationSeverity.CLAIM,
                        claim.ordinal,
                    )
                )
            else:
                mandatory_by_authority[authority_id] = claim
                represented_ids.add(authority_id)
        else:
            optional.append(claim)
    if represented_ids != authority_ids:
        raise ValueError("exact authority claims were not represented after deterministic salvage")
    mandatory = list(mandatory_by_authority.values())
    if len(mandatory) > MAX_PUBLISHED_CLAIMS:
        raise ValueError("exact authority claims exceed the published artifact bound")
    remaining = MAX_PUBLISHED_CLAIMS - len(mandatory)
    kept_optional = optional[:remaining]
    omitted = optional[remaining:]
    kept_ids = {claim.claim_id for claim in (*kept_optional, *mandatory)}
    bounded = [claim for claim in result if claim.claim_id in kept_ids]
    issues.extend(
        ValidationIssue("claim_limit_exceeded", ValidationSeverity.CLAIM, claim.ordinal)
        for claim in omitted
    )
    return bounded, tuple(issues)


def _claim_represents_exact_authority(
    claim: NarrativeClaim,
    exact: NarrativeClaim,
) -> bool:
    if claim.claim_class is not ClaimClass.FACTUAL:
        return False
    if claim.text != exact.text or claim.semantics != exact.semantics:
        return False
    if exact.claim_id in claim.support.child_claim_ids:
        return (
            claim.support.kind is SupportKind.CHILD_CLAIMS
            and claim.support.child_claim_ids == (exact.claim_id,)
        )
    if exact.support.kind is not SupportKind.DIRECT_EVIDENCE:
        return False
    return (
        claim.support.kind is SupportKind.DIRECT_EVIDENCE
        and claim.support.direct_evidence == exact.support.direct_evidence
    )


def _validate_claim(
    raw: object, ordinal: int, context: ValidationContext
) -> NarrativeClaim:
    if not isinstance(raw, Mapping) or set(raw) != _CLAIM_FIELDS:
        raise ValueError("claim shape is invalid")
    claim_class = ClaimClass(_required_text(raw, "claim_class", 40))
    context_scope = ClaimContextScope(_required_text(raw, "context_scope", 40))
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
        context_scope=context_scope,
        text=_required_text(raw, "text", 1_000),
        support=support,
        semantics=semantics,
    )
    _validate_exact_authority_claim(claim, context.authority_claims)
    _validate_claim_context_scope(claim, context)
    return claim


def _validate_claim_context_scope(
    claim: NarrativeClaim,
    context: ValidationContext,
) -> None:
    """Reject cross-route chronology unless the claim is an explicit comparison."""

    contexts = context.contexts_for_claim(claim)
    inherited_scopes = context.inherited_scopes_for_claim(claim)
    if ClaimContextScope.COMPARISON in inherited_scopes:
        if claim.context_scope is not ClaimContextScope.COMPARISON:
            raise ValueError("comparison support cannot be re-atomized")
    elif (
        ClaimContextScope.ORDERED_SUMMARY in inherited_scopes
        and claim.context_scope is ClaimContextScope.ATOMIC
    ):
        raise ValueError("ordered summary support cannot be re-atomized")
    if not contexts:
        if claim.context_scope is not ClaimContextScope.ATOMIC:
            raise ValueError("direct claims must use atomic context scope")
        return

    routes = {item.route_id for item in contexts if item.route_id is not None}
    lanes = {item.lane_id for item in contexts if item.lane_id is not None}
    anchors = {
        item.temporal_anchor for item in contexts if item.temporal_anchor is not None
    }
    arms_by_container: dict[str, set[str]] = {}
    for item in contexts:
        if item.temporary_container_id is not None and item.temporary_arm_id is not None:
            arms_by_container.setdefault(item.temporary_container_id, set()).add(
                item.temporary_arm_id
            )
    exclusive_arms = any(len(arms) > 1 for arms in arms_by_container.values())
    route_conflict = len(routes) > 1 or len(lanes) > 1
    if route_conflict or exclusive_arms:
        if claim.context_scope is not ClaimContextScope.COMPARISON:
            raise ValueError("mutually exclusive contexts require comparison scope")
        return
    if claim.context_scope is ClaimContextScope.ATOMIC and (
        len(contexts) > 1 or len(anchors) > 1
    ):
        raise ValueError("multi-context factual synthesis requires an explicit scope")


def _validate_exact_authority_claim(
    claim: NarrativeClaim,
    authority_claims: tuple[NarrativeClaim, ...],
) -> None:
    """Prevent factual paraphrase from changing exact M12 status or prerequisite authority."""

    if not authority_claims or claim.claim_class is not ClaimClass.FACTUAL:
        return
    authority_by_id = {item.claim_id: item for item in authority_claims}
    cited_children = tuple(
        authority_by_id[item]
        for item in claim.support.child_claim_ids
        if item in authority_by_id
    )
    exact_evidence = {
        reference
        for exact in authority_claims
        if exact.support.kind is SupportKind.DIRECT_EVIDENCE
        for reference in exact.support.direct_evidence
    }
    cites_exact_evidence = bool(
        exact_evidence.intersection(claim.support.direct_evidence)
    )
    if cited_children:
        if len(cited_children) != 1 or len(claim.support.child_claim_ids) != 1:
            raise ValueError("one factual M12 claim must cite only one exact authority claim")
        exact = cited_children[0]
        if claim.text != exact.text or claim.semantics != exact.semantics:
            raise ValueError("factual M12 claims must preserve exact authority language")
    elif cites_exact_evidence:
        represented = tuple(
            exact
            for exact in authority_claims
            if _claim_represents_exact_authority(claim, exact)
        )
        if len(represented) != 1:
            raise ValueError("factual M12 evidence must preserve one exact authority fact")
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
        tuple(
            ContextualClaim(claim, context.job, context.context_for_claim(claim))
            for claim in claims
        )
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
    context_override: StructuralContext | None = None

    def identity(self) -> ContradictionIdentity:
        semantics = self.claim.semantics
        if semantics is None:
            raise ValueError("contextual contradiction checks require normalized claim semantics")
        context = self.context_override or self.job.context
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
