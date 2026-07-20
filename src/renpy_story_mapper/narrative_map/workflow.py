"""Resumable M15 boundary and frozen-event summary workflow."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from renpy_story_mapper.narrative.provider import ProviderUsage
from renpy_story_mapper.narrative_map.contracts import (
    BoundaryCandidate,
    BoundaryProviderIdentity,
    NarrativeEvent,
    canonical_hash,
    stable_m15_id,
)
from renpy_story_mapper.narrative_map.persistence import (
    NarrativeJobStatus,
    NarrativeMapRepository,
)
from renpy_story_mapper.narrative_map.provider import (
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
        consent_manifest_id: str,
        cancelled: CancelledCallback | None = None,
    ) -> NarrativeWorkflowReport:
        if any(job.kind is not ProviderJobKind.BOUNDARY for job in jobs):
            raise ValueError("boundary workflow received a different M15 job kind")
        return self._run(jobs, consent_manifest_id, cancelled or _not_cancelled)

    def run_event_summary_jobs(
        self,
        jobs: Sequence[PreparedNarrativeJob],
        *,
        consent_manifest_id: str,
        cancelled: CancelledCallback | None = None,
    ) -> NarrativeWorkflowReport:
        if any(job.kind is not ProviderJobKind.EVENT_SUMMARY for job in jobs):
            raise ValueError("summary workflow received a different M15 job kind")
        return self._run(jobs, consent_manifest_id, cancelled or _not_cancelled)

    def _run(
        self,
        jobs: Sequence[PreparedNarrativeJob],
        consent_manifest_id: str,
        cancelled: CancelledCallback,
    ) -> NarrativeWorkflowReport:
        if not consent_manifest_id or consent_manifest_id != consent_manifest_id.strip():
            raise ValueError("M15 provider work requires an exact consent manifest ID")
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
                    validated.append(job.job_id)
                    cache_hits += 1
                    continue
            outcome = self._submit_with_repair(
                job,
                consent_manifest_id=consent_manifest_id,
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
        consent_manifest_id: str,
        cancelled: CancelledCallback,
    ) -> _JobOutcome:
        findings: tuple[ValidationFinding, ...] = ()
        usages: list[ProviderUsage] = []
        last_identity: BoundaryProviderIdentity | None = None
        for attempt in (1, 2):
            if cancelled():
                return _JobOutcome(None, None, tuple(usages), attempt - 1, "cancelled", True)
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
                    "consent_manifest_id": consent_manifest_id,
                    "profile": self._profile.to_dict(),
                },
            )
            request = NarrativeMapProviderRequest(
                request_id=request_id,
                consent_manifest_id=consent_manifest_id,
                profile=self._profile,
                job=job,
                repair_codes=repair_codes,
                timeout_seconds=self._timeout_seconds,
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
            result, findings = self._validate_response(job, response.payload, identity)
            if result is not None:
                return _JobOutcome(result, identity, tuple(usages), attempt, None, False)
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


def _not_cancelled() -> bool:
    return False
