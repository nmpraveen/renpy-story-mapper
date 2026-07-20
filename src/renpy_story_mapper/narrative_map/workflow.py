"""Resumable M15 boundary and frozen-event summary workflow."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from renpy_story_mapper.narrative.provider import ProviderUsage
from renpy_story_mapper.narrative_map.contracts import (
    MAX_REASON_LENGTH,
    MAX_SUMMARY_LENGTH,
    MAX_TITLE_LENGTH,
    BoundaryCandidate,
    BoundaryDecisionKind,
    BoundaryProviderIdentity,
    JsonValue,
    NarrativeEvent,
    canonical_hash,
    stable_m15_id,
)
from renpy_story_mapper.narrative_map.persistence import (
    NarrativeJobStatus,
    NarrativeMapRepository,
)
from renpy_story_mapper.narrative_map.provider import (
    NarrativeConsentManifest,
    NarrativeMapProvider,
    NarrativeMapProviderError,
    NarrativeMapProviderRequest,
    PreparedNarrativeJob,
    ProviderJobKind,
    ProviderProfile,
)
from renpy_story_mapper.narrative_map.validation import (
    BoundaryValidationResult,
    EventSummary,
    EventSummaryValidationResult,
    ValidationFinding,
    validate_boundary_response,
    validate_event_summary_response,
)

CancelledCallback = Callable[[], bool]


@dataclass(frozen=True)
class NarrativeWorkflowReport:
    validated_job_ids: tuple[str, ...]
    failed_job_ids: tuple[str, ...]
    cache_hits: int
    provider_calls: int
    input_tokens: int
    output_tokens: int
    elapsed_ms: int
    cancelled: bool


class NarrativeBoundaryWorkflow:
    """Execute explicit provider work while retaining each validated item independently."""

    def __init__(
        self,
        repository: NarrativeMapRepository,
        provider: NarrativeMapProvider,
        profile: ProviderProfile,
        *,
        timeout_seconds: float = 300.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("M15 provider timeout must be positive")
        self._repository = repository
        self._provider = provider
        self._profile = profile
        self._timeout_seconds = timeout_seconds

    def cancel(self) -> None:
        self._provider.cancel()

    def run_boundary_jobs(
        self,
        jobs: Sequence[PreparedNarrativeJob],
        *,
        consent: NarrativeConsentManifest,
        cancelled: CancelledCallback | None = None,
    ) -> NarrativeWorkflowReport:
        if any(job.kind is not ProviderJobKind.BOUNDARY for job in jobs):
            raise ValueError("boundary workflow received a different M15 job kind")
        return self._run(jobs, consent, cancelled or _not_cancelled)

    def run_event_summary_jobs(
        self,
        jobs: Sequence[PreparedNarrativeJob],
        *,
        consent: NarrativeConsentManifest,
        cancelled: CancelledCallback | None = None,
    ) -> NarrativeWorkflowReport:
        if any(job.kind is not ProviderJobKind.EVENT_SUMMARY for job in jobs):
            raise ValueError("summary workflow received a different M15 job kind")
        return self._run(jobs, consent, cancelled or _not_cancelled)

    def _run(
        self,
        jobs: Sequence[PreparedNarrativeJob],
        consent: NarrativeConsentManifest,
        cancelled: CancelledCallback,
    ) -> NarrativeWorkflowReport:
        consent.validate_for(jobs, self._profile)
        job_ids = tuple(job.job_id for job in jobs)
        if len(job_ids) != len(set(job_ids)):
            raise ValueError("each M15 semantic job may be scheduled only once")
        validated: list[str] = []
        failed: list[str] = []
        cache_hits = 0
        provider_calls = 0
        usages: list[ProviderUsage] = []
        was_cancelled = False
        for job in jobs:
            if cancelled():
                was_cancelled = True
                break
            record = self._repository.stage(job, self._profile)
            if (
                record.status is NarrativeJobStatus.VALIDATED
                and record.result is not None
                and self._validate_stored(job, record.result, record.provider_identity)
            ):
                validated.append(job.job_id)
                cache_hits += 1
                continue
            cache = self._repository.load_cache(job, self._profile)
            if cache is not None:
                cached_result, cached_identity = cache
                if self._validate_stored(job, cached_result, cached_identity):
                    self._repository.record_validated(
                        job,
                        self._profile,
                        attempt_count=0,
                        result=cached_result,
                        provider_identity=cached_identity,
                        usage=ProviderUsage(0, 0, 0, cost_micros=0),
                    )
                    validated.append(job.job_id)
                    cache_hits += 1
                    continue
            outcome = self._submit_with_repair(
                job,
                consent=consent,
                maximum_attempts=consent.maximum_provider_calls - provider_calls,
                cancelled=cancelled,
            )
            provider_calls += outcome.attempt_count
            usages.extend(outcome.usages)
            if outcome.cancelled:
                self._repository.record_failure(
                    job,
                    self._profile,
                    attempt_count=outcome.attempt_count,
                    error_code="cancelled",
                    provider_identity=(
                        None
                        if outcome.provider_identity is None
                        else outcome.provider_identity.to_dict()
                    ),
                    usage=_optional_combined_usage(outcome.usages),
                )
                failed.append(job.job_id)
                was_cancelled = True
                break
            if outcome.result is None or outcome.provider_identity is None:
                self._repository.record_failure(
                    job,
                    self._profile,
                    attempt_count=max(1, outcome.attempt_count),
                    error_code=outcome.error_code or "invalid_output",
                    provider_identity=(
                        None
                        if outcome.provider_identity is None
                        else outcome.provider_identity.to_dict()
                    ),
                    usage=_optional_combined_usage(outcome.usages),
                )
                failed.append(job.job_id)
                continue
            self._repository.record_validated(
                job,
                self._profile,
                attempt_count=outcome.attempt_count,
                result=outcome.result,
                provider_identity=outcome.provider_identity.to_dict(),
                usage=_combined_usage(outcome.usages),
            )
            validated.append(job.job_id)
        return NarrativeWorkflowReport(
            validated_job_ids=tuple(validated),
            failed_job_ids=tuple(failed),
            cache_hits=cache_hits,
            provider_calls=provider_calls,
            input_tokens=sum(item.input_tokens for item in usages),
            output_tokens=sum(item.output_tokens for item in usages),
            elapsed_ms=sum(item.elapsed_ms for item in usages),
            cancelled=was_cancelled,
        )

    def _submit_with_repair(
        self,
        job: PreparedNarrativeJob,
        *,
        consent: NarrativeConsentManifest,
        maximum_attempts: int,
        cancelled: CancelledCallback,
    ) -> _JobOutcome:
        findings: tuple[ValidationFinding, ...] = ()
        usages: list[ProviderUsage] = []
        last_identity: BoundaryProviderIdentity | None = None
        locked_semantics: dict[str, JsonValue] = {}
        for attempt in (1, 2):
            if attempt > maximum_attempts:
                return _JobOutcome(
                    None,
                    last_identity,
                    tuple(usages),
                    attempt - 1,
                    "budget_exceeded",
                    False,
                )
            if cancelled():
                return _JobOutcome(
                    None,
                    last_identity,
                    tuple(usages),
                    attempt - 1,
                    "cancelled",
                    True,
                )
            consent.validate_fresh()
            repair_codes = (
                ()
                if attempt == 1
                else tuple(dict.fromkeys(finding.code for finding in findings))
            )
            request_id = stable_m15_id(
                "provider_request",
                {
                    "job_id": job.job_id,
                    "attempt": attempt,
                    "consent_manifest_id": consent.manifest_id,
                    "profile": self._profile.to_dict(),
                },
            )
            request = NarrativeMapProviderRequest(
                request_id=request_id,
                consent=consent,
                profile=self._profile,
                job=job,
                repair_codes=repair_codes,
                repair_semantics=locked_semantics if repair_codes else None,
                timeout_seconds=min(self._timeout_seconds, consent.timeout_seconds),
                maximum_input_bytes=consent.maximum_input_bytes,
                maximum_output_bytes=consent.maximum_output_bytes,
            )
            try:
                response = self._provider.submit(request, cancelled)
            except NarrativeMapProviderError as exc:
                return _JobOutcome(
                    None,
                    last_identity,
                    tuple(usages),
                    attempt,
                    exc.error_code,
                    exc.error_code == "cancelled",
                )
            except Exception:
                return _JobOutcome(
                    None,
                    last_identity,
                    tuple(usages),
                    attempt,
                    "internal_error",
                    False,
                )
            usages.append(response.usage)
            try:
                identity = self._validated_identity(job, request.request_id, response)
            except ValueError:
                return _JobOutcome(
                    None, None, tuple(usages), attempt, "provider_identity_mismatch", False
                )
            last_identity = identity
            if attempt == 2 and not _matches_semantic_lock(
                job, response.payload, locked_semantics
            ):
                return _JobOutcome(
                    None,
                    last_identity,
                    tuple(usages),
                    attempt,
                    "semantic_reinterpretation",
                    False,
                )
            result, findings = self._validate_response(job, response.payload, identity)
            if result is not None:
                return _JobOutcome(result, identity, tuple(usages), attempt, None, False)
            if attempt == 1:
                locked_semantics = _semantic_lock(job, response.payload, findings)
        return _JobOutcome(None, last_identity, tuple(usages), 2, "invalid_output", False)

    def _validated_identity(
        self,
        job: PreparedNarrativeJob,
        request_id: str,
        response: object,
    ) -> BoundaryProviderIdentity:
        from renpy_story_mapper.narrative_map.provider import NarrativeMapProviderResponse

        if (
            not isinstance(response, NarrativeMapProviderResponse)
            or response.request_id != request_id
        ):
            raise ValueError("provider response does not match its request")
        identity = response.provider
        expected = self._profile
        if (
            identity.provider != expected.provider
            or identity.adapter != expected.adapter
            or identity.adapter_version != expected.adapter_version
            or identity.requested_model != expected.requested_model
            or identity.resolved_model != expected.requested_model
            or identity.settings.to_dict() != expected.settings.to_dict()
        ):
            raise ValueError("provider identity does not match the exact requested profile")
        return BoundaryProviderIdentity(
            provider=identity.provider,
            adapter_version=f"{identity.adapter}:{identity.adapter_version}",
            requested_model=identity.requested_model,
            resolved_model=identity.resolved_model,
            settings_hash=canonical_hash(identity.settings.to_dict()),
            prompt_version=job.prompt_version,
            response_schema=job.response_schema,
            input_hash=job.input_hash,
        )

    @staticmethod
    def _validate_response(
        job: PreparedNarrativeJob,
        payload: object,
        identity: BoundaryProviderIdentity,
    ) -> tuple[Mapping[str, object] | None, tuple[ValidationFinding, ...]]:
        if job.kind is ProviderJobKind.BOUNDARY:
            if not isinstance(job.subject, BoundaryCandidate):
                raise ValueError("boundary job subject contract is invalid")
            validation: BoundaryValidationResult = validate_boundary_response(
                payload, (job.subject,), provider_identity=identity
            )
            if not validation.valid:
                return None, validation.findings
            decision = validation.decisions[0]
            return (
                {
                    "decisions": [
                        {
                            "candidate_id": decision.candidate.candidate_id,
                            "decision": decision.decision.value,
                            "reason": decision.reason,
                            "confidence": decision.confidence,
                            "warnings": list(decision.warnings),
                        }
                    ]
                },
                (),
            )
        if not isinstance(job.subject, NarrativeEvent):
            raise ValueError("summary job subject contract is invalid")
        summary_validation: EventSummaryValidationResult = validate_event_summary_response(
            payload,
            job.subject,
            known_characters=job.known_characters,
            provider_identity=identity,
            story_facing=job.story_facing,
        )
        if not summary_validation.valid or summary_validation.summary is None:
            return None, summary_validation.findings
        return _summary_provider_payload(summary_validation.summary), ()

    def _validate_stored(
        self,
        job: PreparedNarrativeJob,
        result: Mapping[str, object],
        identity_payload: Mapping[str, object] | None,
    ) -> bool:
        if identity_payload is None:
            return False
        try:
            identity = _decode_boundary_identity(identity_payload)
        except ValueError:
            return False
        expected = BoundaryProviderIdentity(
            provider=self._profile.provider,
            adapter_version=f"{self._profile.adapter}:{self._profile.adapter_version}",
            requested_model=self._profile.requested_model,
            resolved_model=self._profile.requested_model,
            settings_hash=self._profile.settings_hash,
            prompt_version=job.prompt_version,
            response_schema=job.response_schema,
            input_hash=job.input_hash,
        )
        if identity != expected:
            return False
        normalized, findings = self._validate_response(job, result, identity)
        return normalized is not None and not findings


@dataclass(frozen=True)
class _JobOutcome:
    result: Mapping[str, object] | None
    provider_identity: BoundaryProviderIdentity | None
    usages: tuple[ProviderUsage, ...]
    attempt_count: int
    error_code: str | None
    cancelled: bool


def _summary_provider_payload(summary: EventSummary) -> dict[str, object]:
    return {
        "event_id": summary.event_id,
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


def _decode_boundary_identity(payload: Mapping[str, object]) -> BoundaryProviderIdentity:
    fields = {
        "provider",
        "adapter_version",
        "requested_model",
        "resolved_model",
        "settings_hash",
        "prompt_version",
        "response_schema",
        "input_hash",
    }
    if set(payload) != fields or any(not isinstance(payload.get(field), str) for field in fields):
        raise ValueError("persisted provider identity is invalid")
    return BoundaryProviderIdentity(**cast(dict[str, str], dict(payload)))


def _combined_usage(usages: Sequence[ProviderUsage]) -> ProviderUsage:
    if not usages:
        return ProviderUsage(0, 0, 0)
    costs = tuple(item.cost_micros for item in usages)
    cost = None if any(item is None for item in costs) else sum(cast(int, item) for item in costs)
    return ProviderUsage(
        input_tokens=sum(item.input_tokens for item in usages),
        output_tokens=sum(item.output_tokens for item in usages),
        elapsed_ms=sum(item.elapsed_ms for item in usages),
        cost_micros=cost,
    )


def _optional_combined_usage(usages: Sequence[ProviderUsage]) -> ProviderUsage | None:
    return _combined_usage(usages) if usages else None


def _semantic_lock(
    job: PreparedNarrativeJob,
    payload: object,
    findings: Sequence[ValidationFinding],
) -> dict[str, JsonValue]:
    if not isinstance(payload, Mapping):
        return {}
    finding_codes = {finding.code for finding in findings}
    if job.kind is ProviderJobKind.BOUNDARY:
        raw_decisions = payload.get("decisions")
        if not isinstance(raw_decisions, list):
            return {}
        matching = [
            item
            for item in raw_decisions
            if isinstance(item, Mapping) and item.get("candidate_id") == job.subject_id
        ]
        if len(matching) != 1:
            return {}
        item = matching[0]
        locked: dict[str, JsonValue] = {"candidate_id": job.subject_id}
        decision = item.get("decision")
        if isinstance(decision, str):
            try:
                BoundaryDecisionKind(decision)
            except ValueError:
                pass
            else:
                locked["decision"] = decision
        reason = item.get("reason")
        if _repair_text(reason, MAX_REASON_LENGTH):
            locked["reason"] = reason
        confidence = item.get("confidence")
        if (
            isinstance(confidence, int | float)
            and not isinstance(confidence, bool)
            and 0 <= float(confidence) <= 1
        ):
            locked["confidence"] = float(confidence)
        warnings = item.get("warnings")
        if _repair_text_list(warnings, MAX_REASON_LENGTH):
            locked["warnings"] = cast(list[JsonValue], warnings)
        return locked
    locked = {}
    if payload.get("event_id") == job.subject_id:
        locked["event_id"] = job.subject_id
    title = payload.get("title")
    if (
        "invalid_title" not in finding_codes
        and "blocked_title" not in finding_codes
        and _repair_text(title, MAX_TITLE_LENGTH)
    ):
        locked["title"] = title
    summary = payload.get("summary")
    if "invalid_summary" not in finding_codes and _repair_text(summary, MAX_SUMMARY_LENGTH):
        locked["summary"] = summary
    characters = payload.get("characters")
    if (
        "invalid_characters" not in finding_codes
        and "unknown_character" not in finding_codes
        and _repair_text_list(characters, MAX_REASON_LENGTH)
    ):
        locked["characters"] = cast(list[JsonValue], characters)
    warnings = payload.get("warnings")
    if "invalid_warnings" not in finding_codes and _repair_text_list(
        warnings, MAX_REASON_LENGTH
    ):
        locked["warnings"] = cast(list[JsonValue], warnings)
    claims = payload.get("claims")
    invalid_claim_indexes = {
        finding.index for finding in findings if finding.index is not None
    }
    locked_claims: list[JsonValue] = []
    if isinstance(claims, list):
        for index, claim in enumerate(claims):
            if index in invalid_claim_indexes or not isinstance(claim, Mapping):
                continue
            claim_class = claim.get("claim_class")
            text = claim.get("text")
            evidence_ids = claim.get("evidence_ids")
            if (
                set(claim) == {"claim_class", "text", "evidence_ids"}
                and isinstance(claim_class, str)
                and isinstance(text, str)
                and isinstance(evidence_ids, list)
                and all(isinstance(item, str) for item in evidence_ids)
            ):
                locked_claims.append(
                    {
                        "index": index,
                        "claim": {
                            "claim_class": claim_class,
                            "text": text,
                            "evidence_ids": list(cast(list[str], evidence_ids)),
                        },
                    }
                )
    locked["__claim_slots__"] = {
        "length": len(claims) if isinstance(claims, list) else 0,
        "locked": locked_claims,
    }
    return locked


def _matches_semantic_lock(
    job: PreparedNarrativeJob,
    payload: object,
    locked: Mapping[str, JsonValue],
) -> bool:
    if not locked:
        return True
    current = _semantic_lock(job, payload, ())
    scalar_match = all(
        key in current and canonical_hash(current[key]) == canonical_hash(value)
        for key, value in locked.items()
        if key != "__claim_slots__"
    )
    if not scalar_match:
        return False
    claim_slots = locked.get("__claim_slots__")
    return claim_slots is None or _matches_claim_slots(payload, claim_slots)


def _matches_claim_slots(payload: object, constraint: JsonValue) -> bool:
    if not isinstance(payload, Mapping) or not isinstance(constraint, Mapping):
        return False
    claims = payload.get("claims")
    length = constraint.get("length")
    locked = constraint.get("locked")
    if (
        not isinstance(claims, list)
        or not isinstance(length, int)
        or isinstance(length, bool)
        or len(claims) != length
        or not isinstance(locked, list)
    ):
        return False
    for entry in locked:
        if not isinstance(entry, Mapping) or set(entry) != {"index", "claim"}:
            return False
        index = entry.get("index")
        claim = entry.get("claim")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or not 0 <= index < len(claims)
            or not isinstance(claim, Mapping)
            or canonical_hash(claims[index]) != canonical_hash(claim)
        ):
            return False
    return True


def _repair_text(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= maximum
    )


def _repair_text_list(value: object, maximum: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == len({item for item in value if isinstance(item, str)})
        and all(_repair_text(item, maximum) for item in value)
    )


def _not_cancelled() -> bool:
    return False
