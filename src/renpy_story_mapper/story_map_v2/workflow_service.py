"""Six-slot durable workflow and provider policy for Story Map V2 Phase 04."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from renpy_story_mapper.story_map_v2.frozen_plans import FrozenPlanBundle
from renpy_story_mapper.story_map_v2.workflow_contracts import (
    AttemptAccounting,
    AttemptCompletion,
    AttemptReservation,
    AttemptStage,
    AuthorityIdentity,
    CacheIdentity,
    JobClaim,
    JobResolution,
    JobRetryApproval,
    ProviderCallKind,
    ProviderCallResult,
    ProviderInputIdentity,
    ProviderMode,
    ProviderSettings,
    RecoveryReport,
    TransmissionDisposition,
    ValidatedWorkflowResult,
    WorkflowApproval,
    WorkflowDerivedSemanticJobDescriptor,
    WorkflowFailure,
    WorkflowPlanDescriptor,
    WorkflowPolicy,
    WorkflowPreview,
    WorkflowPrivacyScope,
    WorkflowResourceCeilings,
    WorkflowStatus,
    validate_transmission_accounting,
)
from renpy_story_mapper.story_map_v2.workflow_protocols import (
    ProviderFactory,
    RequestMaterializer,
    WorkflowCheckpoint,
    WorkflowProvider,
    WorkflowProviderError,
    WorkflowRepository,
    WorkflowResponseValidator,
)

_ABSOLUTE_PATH = re.compile(
    rb"(?:[A-Za-z]:[\\/]|\\\\[^\\\r\n]+\\|(?<![A-Za-z0-9._-])/(?!/)[^\s\"'<>]+(?:/[^\s\"'<>]+)*)",
    re.IGNORECASE,
)
_SOURCE_PACKET_MARKERS = (b"@@SOURCE ", b'"raw_text":', b'"mechanics":')
_AI_TRANSCRIPT_ENV = "RENPY_STORY_MAPPER_AI_TRANSCRIPT"
_AI_TRANSCRIPT_LOCK = threading.Lock()


class WorkflowApprovalError(ValueError):
    """The execution no longer matches its frozen preview and approval."""


class WorkflowValidationError(ValueError):
    """A validator attempted to make unsafe material durable."""


@dataclass(frozen=True)
class _CallSuccess:
    reservation: AttemptReservation
    result: ProviderCallResult
    request: bytes


@dataclass(frozen=True)
class _CallFailure:
    reservation: AttemptReservation | None
    failure: WorkflowFailure
    transmission: TransmissionDisposition


class _NoCheckpoint:
    def __call__(self, name: str, job_id: str) -> None:
        del name, job_id


class StoryMapWorkflowService:
    """Coordinate one approved plan without importing a planner or concrete repository.

    A call to :meth:`prepare`, :meth:`approve`, :meth:`status`, or :meth:`recover` never touches a
    provider factory.  Provider construction occurs only after a durable attempt reservation and
    immediately before the corresponding independent submission.
    """

    def __init__(
        self,
        repository: WorkflowRepository,
        materializer: RequestMaterializer,
        validator: WorkflowResponseValidator,
        *,
        cloud_factory: ProviderFactory,
        loopback_factory: ProviderFactory | None = None,
        checkpoint: WorkflowCheckpoint | None = None,
    ) -> None:
        self._repository = repository
        self._materializer = materializer
        self._validator = validator
        self._cloud_factory = cloud_factory
        self._loopback_factory = loopback_factory
        self._checkpoint = checkpoint or _NoCheckpoint()
        self._active_lock = threading.Lock()
        self._active: dict[str, WorkflowProvider] = {}

    def prepare(
        self,
        run_id: str,
        plan: WorkflowPlanDescriptor,
        policy: WorkflowPolicy,
        ceilings: WorkflowResourceCeilings,
        *,
        frozen_plans: FrozenPlanBundle | None = None,
    ) -> WorkflowPreview:
        """Persist a deterministic preview while constructing and calling zero providers."""

        cache_hits: list[str] = []
        loopback_cache_hits: list[str] = []
        for job in plan.jobs:
            expected = policy.input_identity(job.serialized_request_identity).cache_identity
            if expected != job.cache_identity:
                raise ValueError("job cache identity does not match the frozen provider input")
            if self._repository.load_cache(job.cache_identity) is not None:
                cache_hits.append(job.job_id)
                continue
            if policy.allow_refusal_fallback:
                loopback_identity = policy.input_identity(
                    job.serialized_request_identity, mode=ProviderMode.LOOPBACK
                ).cache_identity
                if self._repository.load_cache(loopback_identity) is not None:
                    loopback_cache_hits.append(job.job_id)
        pending = len(plan.jobs) - len(cache_hits) - len(loopback_cache_hits)
        if ceilings.mapping_calls < pending:
            raise ValueError("mapping-call ceiling cannot cover every frozen pending job")
        if ceilings.review_calls > len(plan.jobs):
            raise ValueError("review-call ceiling cannot exceed one review per job")
        if ceilings.indeterminate_retry_calls > len(plan.jobs):
            derived_max = (
                0
                if plan.derived_semantic_plan is None
                else plan.derived_semantic_plan.section_synthesis_calls
                + plan.derived_semantic_plan.rollup_synthesis_calls
            )
            if ceilings.indeterminate_retry_calls > len(plan.jobs) + derived_max:
                raise ValueError("retry-call ceiling cannot exceed one approved retry per job")
        if policy.allow_refusal_fallback:
            if ceilings.fallback_calls > len(plan.jobs):
                raise ValueError("fallback-call ceiling cannot exceed one fallback per job")
        elif ceilings.fallback_calls != 0:
            raise ValueError("fallback calls require a disclosed loopback provider")
        _validate_derived_ceilings(plan, ceilings)
        preview = WorkflowPreview(
            run_id=run_id,
            plan=plan,
            policy=policy,
            ceilings=ceilings,
            privacy=WorkflowPrivacyScope(
                cloud_story_content=policy.cloud.mode is ProviderMode.CLOUD,
                loopback_story_content=(
                    policy.cloud.mode is ProviderMode.LOOPBACK
                    or policy.allow_refusal_fallback
                ),
            ),
            cache_hit_job_ids=tuple(cache_hits),
            loopback_cache_hit_job_ids=tuple(loopback_cache_hits),
        )
        self._repository.store_prepared(preview, frozen_plans)
        return preview

    def register_derived_job(
        self,
        run_id: str,
        *,
        preview_identity: str,
        job: WorkflowDerivedSemanticJobDescriptor,
    ) -> None:
        """Register one immutable dependency-ready semantic job without a provider."""

        preview = self._repository.load_preview(run_id)
        if not _same_digest(preview.identity, preview_identity):
            raise WorkflowApprovalError(
                "derived job registration does not match the frozen preview"
            )
        self._repository.register_derived_job(run_id, preview_identity, job)

    def approve(self, run_id: str, preview_identity: str) -> WorkflowApproval:
        preview = self._repository.load_preview(run_id)
        if not _same_digest(preview.identity, preview_identity):
            raise WorkflowApprovalError("approval does not match the frozen workflow preview")
        approval = WorkflowApproval(
            preview_identity=preview.identity,
            plan_id=preview.plan.plan_id,
            authority_identity=preview.plan.authority_identity,
        )
        self._repository.store_approval(run_id, approval)
        return approval

    def approve_indeterminate_retry(
        self,
        run_id: str,
        *,
        preview_identity: str,
        job_id: str,
        indeterminate_attempt_id: str,
    ) -> JobRetryApproval:
        preview = self._repository.load_preview(run_id)
        if not _same_digest(preview.identity, preview_identity):
            raise WorkflowApprovalError("retry approval does not match the frozen workflow preview")
        mapping_job = next((job for job in preview.plan.jobs if job.job_id == job_id), None)
        if mapping_job is None and self._repository.load_job_descriptor(run_id, job_id) is None:
            raise ValueError("retry approval identifies a foreign workflow job")
        approval = JobRetryApproval(preview.identity, job_id, indeterminate_attempt_id)
        self._repository.store_retry_approval(run_id, approval)
        return approval

    def execute(
        self,
        run_id: str,
        *,
        preview_identity: str,
        authority_identity: AuthorityIdentity,
    ) -> WorkflowStatus:
        preview = self._validated_execution(run_id, preview_identity, authority_identity)
        execution_id = self._repository.begin_execution(
            run_id, preview.identity, authority_identity.value
        )
        abort = threading.Event()
        with ThreadPoolExecutor(
            max_workers=preview.ceilings.submission_slots,
            thread_name_prefix="story-map-v2-workflow",
        ) as executor:
            futures = tuple(
                executor.submit(
                    self._worker,
                    preview,
                    execution_id,
                    f"worker-{index + 1}",
                    abort,
                )
                for index in range(preview.ceilings.submission_slots)
            )
            for future in futures:
                future.result()
        return self._repository.status(run_id)

    def cancel(self, run_id: str) -> None:
        """Commit cancellation before signalling any active provider."""

        self._repository.persist_cancellation(run_id)
        with self._active_lock:
            active = tuple(self._active.values())
        for provider in active:
            with suppress(Exception):
                provider.cancel()

    def recover(self, run_id: str) -> RecoveryReport:
        """Recover durable state without constructing a provider or resubmitting work."""

        return self._repository.recover(run_id)

    def status(self, run_id: str) -> WorkflowStatus:
        return self._repository.status(run_id)

    def _validated_execution(
        self,
        run_id: str,
        preview_identity: str,
        authority_identity: AuthorityIdentity,
    ) -> WorkflowPreview:
        preview = self._repository.load_preview(run_id)
        approval = self._repository.load_approval(run_id)
        if not _same_digest(preview.identity, preview_identity):
            raise WorkflowApprovalError("execution does not match the frozen workflow preview")
        if approval is None or not _same_digest(approval.preview_identity, preview.identity):
            raise WorkflowApprovalError("the frozen workflow preview has not been approved")
        if (
            approval.plan_id != preview.plan.plan_id
            or approval.authority_identity != authority_identity
        ):
            raise WorkflowApprovalError("plan or authority changed after workflow approval")
        if authority_identity != preview.plan.authority_identity:
            raise WorkflowApprovalError("current authority does not match the frozen workflow plan")
        if self._repository.is_cancelled(run_id):
            raise WorkflowApprovalError("cancelled workflow runs are terminal")
        initial_cloud_hits = set(preview.cache_hit_job_ids)
        initial_loopback_hits = set(preview.loopback_cache_hit_job_ids)
        for job in preview.plan.jobs:
            published = self._repository.load_published_result(run_id, job.job_id)
            self._validate_frozen_cache_state(
                job.job_id,
                job.cache_identity,
                job.job_id in initial_cloud_hits,
                published,
            )
            if preview.policy.allow_refusal_fallback:
                loopback_identity = preview.policy.input_identity(
                    job.serialized_request_identity, mode=ProviderMode.LOOPBACK
                ).cache_identity
                self._validate_frozen_cache_state(
                    job.job_id,
                    loopback_identity,
                    job.job_id in initial_loopback_hits,
                    published,
                )
        return preview

    def _validate_frozen_cache_state(
        self,
        job_id: str,
        cache_identity: CacheIdentity,
        was_hit: bool,
        published: ValidatedWorkflowResult | None,
    ) -> None:
        cached = self._repository.load_cache(cache_identity)
        if cached is None:
            if was_hit:
                raise WorkflowApprovalError("cache-hit work changed after workflow preview")
            return
        if was_hit or published == cached:
            return
        raise WorkflowApprovalError(
            f"cache-hit work changed after workflow preview for {job_id}"
        )

    def _worker(
        self,
        preview: WorkflowPreview,
        execution_id: str,
        worker_id: str,
        abort: threading.Event,
    ) -> None:
        while not abort.is_set() and not self._repository.is_cancelled(preview.run_id):
            claim = self._repository.claim_next_job(
                preview.run_id,
                execution_id,
                worker_id,
                submission_slots=preview.ceilings.submission_slots,
            )
            if claim is None:
                return
            if abort.is_set():
                self._repository.release_claim(claim)
                return
            try:
                self._process_claim(preview, claim)
            except BaseException:
                abort.set()
                raise
            finally:
                self._repository.release_claim(claim)

    def _process_claim(self, preview: WorkflowPreview, claim: JobClaim) -> None:
        if self._repository.is_cancelled(preview.run_id):
            self._finalize_cancelled(claim)
            return
        if isinstance(claim.job, WorkflowDerivedSemanticJobDescriptor):
            self._process_derived_claim(preview, claim)
            return
        if claim.resume_call_kind is ProviderCallKind.REPLACEMENT_REVIEW:
            review = self._call(
                preview,
                claim,
                ProviderCallKind.REPLACEMENT_REVIEW,
                preview.policy.cloud,
                self._cloud_factory,
            )
            if isinstance(review, _CallFailure):
                self._finalize_from_call_failure(claim, review)
                return
            replacement = self._validate_call(claim, review)
            if replacement is None or replacement.flagged_for_review:
                self._finalize_structural(claim, WorkflowFailure.INVALID_RESPONSE)
                return
            self._accept_result(
                claim, review.reservation, claim.job.cache_identity, replacement
            )
            return
        if claim.resume_call_kind is ProviderCallKind.REFUSAL_FALLBACK:
            self._run_refusal_fallback(preview, claim)
            return

        cached_identity = claim.job.cache_identity
        cached = self._load_eligible_cache(
            preview,
            claim,
            cached_identity,
            set(preview.cache_hit_job_ids),
        )
        if cached is None and preview.policy.allow_refusal_fallback:
            loopback_identity = preview.policy.input_identity(
                claim.job.serialized_request_identity, mode=ProviderMode.LOOPBACK
            ).cache_identity
            cached = self._load_eligible_cache(
                preview,
                claim,
                loopback_identity,
                set(preview.loopback_cache_hit_job_ids),
            )
            if cached is not None:
                cached_identity = loopback_identity
        if cached is not None:
            try:
                cached_validated = self._validator.validate(
                    claim.job, cached.normalized_payload, cached=True
                )
                _validate_durable_result(cached_validated)
            except Exception:
                self._finalize_structural(claim, WorkflowFailure.INVALID_RESPONSE)
                return
            if cached_validated.flagged_for_review:
                self._finalize_structural(claim, WorkflowFailure.INVALID_RESPONSE)
                return
            self._accept_result(claim, None, cached_identity, cached_validated)
            return

        primary = self._call(
            preview,
            claim,
            ProviderCallKind.MAPPING,
            preview.policy.cloud,
            self._cloud_factory,
        )
        if isinstance(primary, _CallFailure):
            self._handle_primary_failure(preview, claim, primary)
            return
        validated = self._validate_call(claim, primary)
        if validated is None:
            self._finalize_structural(claim, WorkflowFailure.INVALID_RESPONSE)
            return
        if validated.flagged_for_review:
            review = self._call(
                preview,
                claim,
                ProviderCallKind.REPLACEMENT_REVIEW,
                preview.policy.cloud,
                self._cloud_factory,
            )
            if isinstance(review, _CallFailure):
                self._finalize_from_call_failure(claim, review)
                return
            replacement = self._validate_call(claim, review)
            if replacement is None or replacement.flagged_for_review:
                self._finalize_structural(claim, WorkflowFailure.INVALID_RESPONSE)
                return
            validated = replacement
            reservation = review.reservation
        else:
            reservation = primary.reservation
        self._accept_result(claim, reservation, claim.job.cache_identity, validated)

    def _process_derived_claim(self, preview: WorkflowPreview, claim: JobClaim) -> None:
        job = claim.job
        assert isinstance(job, WorkflowDerivedSemanticJobDescriptor)
        cached = self._repository.load_cache(job.cache_identity)
        if cached is not None:
            try:
                validated = self._validator.validate(job, cached.normalized_payload, cached=True)
                _validate_durable_result(validated)
            except Exception:
                self._finalize_structural(claim, WorkflowFailure.INVALID_RESPONSE)
                return
            if validated.flagged_for_review:
                self._finalize_structural(claim, WorkflowFailure.INVALID_RESPONSE)
                return
            self._accept_result(claim, None, job.cache_identity, validated)
            return
        settings = ProviderSettings(
            provider=job.provider_input_identity.provider,
            model=job.provider_input_identity.model,
            reasoning=job.provider_input_identity.reasoning,
            fast_mode=job.provider_input_identity.fast_mode,
            mode=job.provider_input_identity.mode,
            adapter_version=job.provider_input_identity.adapter_version,
        )
        call = self._call(
            preview,
            claim,
            job.call_kind,
            settings,
            self._cloud_factory,
            provider_input=job.provider_input_identity,
        )
        if isinstance(call, _CallFailure):
            self._finalize_from_call_failure(claim, call)
            return
        call_validated = self._validate_call(claim, call)
        if call_validated is None or call_validated.flagged_for_review:
            self._finalize_structural(claim, WorkflowFailure.INVALID_RESPONSE)
            return
        self._accept_result(claim, call.reservation, job.cache_identity, call_validated)

    def _load_eligible_cache(
        self,
        preview: WorkflowPreview,
        claim: JobClaim,
        cache_identity: CacheIdentity,
        approved_hit_job_ids: set[str],
    ) -> ValidatedWorkflowResult | None:
        cached = self._repository.load_cache(cache_identity)
        if cached is None:
            return None
        if claim.job.job_id in approved_hit_job_ids:
            return cached
        published = self._repository.load_published_result(
            preview.run_id, claim.job.job_id
        )
        if published == cached:
            return cached
        raise WorkflowApprovalError("cache-hit work changed after workflow preview")

    def _handle_primary_failure(
        self,
        preview: WorkflowPreview,
        claim: JobClaim,
        failure: _CallFailure,
    ) -> None:
        if (
            failure.failure is WorkflowFailure.CONTENT_REFUSAL
            and failure.transmission is TransmissionDisposition.TRANSMITTED
            and preview.policy.allow_refusal_fallback
            and preview.policy.loopback is not None
            and self._loopback_factory is not None
        ):
            self._run_refusal_fallback(preview, claim)
            return
        self._finalize_from_call_failure(claim, failure)

    def _run_refusal_fallback(
        self,
        preview: WorkflowPreview,
        claim: JobClaim,
    ) -> None:
        if (
            not preview.policy.allow_refusal_fallback
            or preview.policy.loopback is None
            or self._loopback_factory is None
        ):
            self._finalize_structural(claim, WorkflowFailure.INVALID_RESPONSE)
            return
        fallback = self._call(
            preview,
            claim,
            ProviderCallKind.REFUSAL_FALLBACK,
            preview.policy.loopback,
            self._loopback_factory,
        )
        if isinstance(fallback, _CallFailure):
            self._finalize_from_call_failure(claim, fallback, local_invalid=True)
            return
        validated = self._validate_call(claim, fallback)
        if validated is None or validated.flagged_for_review:
            self._finalize_structural(claim, WorkflowFailure.INVALID_RESPONSE)
            return
        local_cache = preview.policy.input_identity(
            claim.job.serialized_request_identity, mode=ProviderMode.LOOPBACK
        ).cache_identity
        self._accept_result(claim, fallback.reservation, local_cache, validated)

    def _call(
        self,
        preview: WorkflowPreview,
        claim: JobClaim,
        call_kind: ProviderCallKind,
        settings: ProviderSettings,
        factory: ProviderFactory,
        *,
        provider_input: ProviderInputIdentity | None = None,
    ) -> _CallSuccess | _CallFailure:
        provider_input = provider_input or _provider_input(preview.policy, claim, settings)
        self._checkpoint("before_reservation", claim.job.job_id)
        reservation = self._repository.reserve_attempt(
            claim, call_kind, provider_input, preview.ceilings
        )
        if reservation is None:
            return _CallFailure(
                None,
                WorkflowFailure.RESOURCE_LIMIT,
                TransmissionDisposition.NOT_TRANSMITTED,
            )
        self._checkpoint("after_reservation", claim.job.job_id)

        try:
            request = self._materializer.materialize(claim.job.serialized_request_identity)
            claim.job.serialized_request_identity.verify(request)
        except Exception:
            self._complete_not_transmitted(
                claim, reservation, WorkflowFailure.IDENTITY_MISMATCH
            )
            return _CallFailure(
                reservation,
                WorkflowFailure.IDENTITY_MISMATCH,
                TransmissionDisposition.NOT_TRANSMITTED,
            )
        try:
            provider = factory()
        except Exception:
            self._complete_not_transmitted(
                claim, reservation, WorkflowFailure.PROVIDER_UNAVAILABLE
            )
            return _CallFailure(
                reservation,
                WorkflowFailure.PROVIDER_UNAVAILABLE,
                TransmissionDisposition.NOT_TRANSMITTED,
            )
        if self._repository.is_cancelled(preview.run_id):
            with suppress(Exception):
                provider.cancel()
            self._complete_not_transmitted(claim, reservation, WorkflowFailure.CANCELLED)
            return _CallFailure(
                reservation, WorkflowFailure.CANCELLED, TransmissionDisposition.NOT_TRANSMITTED
            )

        with self._active_lock:
            self._active[reservation.attempt_id] = provider
        try:
            submitting = self._repository.mark_submitting(claim, reservation)
        except BaseException:
            with self._active_lock:
                self._active.pop(reservation.attempt_id, None)
            raise
        if not submitting:
            with self._active_lock:
                self._active.pop(reservation.attempt_id, None)
            self._complete_not_transmitted(claim, reservation, WorkflowFailure.CANCELLED)
            return _CallFailure(
                reservation,
                WorkflowFailure.CANCELLED,
                TransmissionDisposition.NOT_TRANSMITTED,
            )
        try:
            self._checkpoint("after_mark_submitting", claim.job.job_id)
        except BaseException:
            with self._active_lock:
                self._active.pop(reservation.attempt_id, None)
            raise
        if self._repository.is_cancelled(preview.run_id):
            with self._active_lock:
                self._active.pop(reservation.attempt_id, None)
            self._complete_not_transmitted(claim, reservation, WorkflowFailure.CANCELLED)
            return _CallFailure(
                reservation,
                WorkflowFailure.CANCELLED,
                TransmissionDisposition.NOT_TRANSMITTED,
            )
        stop_monitor, monitor = self._start_cancellation_monitor(preview.run_id, provider)
        try:
            result = provider.submit(request)
        except WorkflowProviderError as exc:
            _append_ai_transcript(
                job_id=claim.job.job_id,
                attempt_id=reservation.attempt_id,
                call_kind=call_kind,
                prompt=request,
                response=None,
                outcome="provider_error",
                comment=exc.failure.value,
                accounting=exc.accounting,
                provider=settings.provider,
                model=settings.model,
            )
            failure, transmission = self._record_provider_failure(claim, reservation, exc)
            return _CallFailure(reservation, failure, transmission)
        except Exception as exc:
            _append_ai_transcript(
                job_id=claim.job.job_id,
                attempt_id=reservation.attempt_id,
                call_kind=call_kind,
                prompt=request,
                response=None,
                outcome="provider_error",
                comment=f"{type(exc).__name__}: {exc}",
                accounting=AttemptAccounting.zero(),
                provider=settings.provider,
                model=settings.model,
            )
            completion = AttemptCompletion(
                stage=AttemptStage.INDETERMINATE,
                transmission=TransmissionDisposition.INDETERMINATE,
                accounting=AttemptAccounting.zero(),
                response_identity=None,
                failure=WorkflowFailure.INDETERMINATE,
                sanitized_reason=_SANITIZED_REASONS[WorkflowFailure.INDETERMINATE],
            )
            self._repository.complete_attempt(claim, reservation, completion)
            return _CallFailure(
                reservation,
                WorkflowFailure.INDETERMINATE,
                TransmissionDisposition.INDETERMINATE,
            )
        finally:
            stop_monitor.set()
            monitor.join(timeout=0.2)
            with self._active_lock:
                self._active.pop(reservation.attempt_id, None)

        response_identity = hashlib.sha256(result.payload).hexdigest()
        identity_failure = _provider_identity_failure(result, settings)
        completion = AttemptCompletion(
            stage=AttemptStage.RETURNED,
            transmission=TransmissionDisposition.TRANSMITTED,
            accounting=result.accounting,
            response_identity=response_identity,
            failure=identity_failure,
            sanitized_reason=(
                None if identity_failure is None else _SANITIZED_REASONS[identity_failure]
            ),
        )
        self._repository.complete_attempt(claim, reservation, completion)
        self._checkpoint("after_transport_return", claim.job.job_id)
        if identity_failure is not None:
            _append_ai_transcript(
                job_id=claim.job.job_id,
                attempt_id=reservation.attempt_id,
                call_kind=call_kind,
                prompt=request,
                response=result.payload,
                outcome="identity_rejected",
                comment=identity_failure.value,
                accounting=result.accounting,
                provider=result.resolved_provider,
                model=result.resolved_model,
            )
            return _CallFailure(
                reservation, identity_failure, TransmissionDisposition.TRANSMITTED
            )
        return _CallSuccess(reservation, result, request)

    def _validate_call(
        self,
        claim: JobClaim,
        call: _CallSuccess,
    ) -> ValidatedWorkflowResult | None:
        try:
            validated = self._validator.validate(claim.job, call.result.payload, cached=False)
            _validate_durable_result(validated, prohibited_request=call.request)
        except Exception as exc:
            _append_ai_transcript(
                job_id=claim.job.job_id,
                attempt_id=call.reservation.attempt_id,
                call_kind=call.reservation.call_kind,
                prompt=call.request,
                response=call.result.payload,
                outcome="validation_rejected",
                comment=f"{type(exc).__name__}: {exc}",
                accounting=call.result.accounting,
                provider=call.result.resolved_provider,
                model=call.result.resolved_model,
            )
            return None
        transcript_outcome = (
            "review_requested" if validated.flagged_for_review else "accepted"
        )
        transcript_comment = (
            "AI response passed validation but requested review; replacement required."
            if validated.flagged_for_review
            else "AI response passed validation; summary added."
        )
        _append_ai_transcript(
            job_id=claim.job.job_id,
            attempt_id=call.reservation.attempt_id,
            call_kind=call.reservation.call_kind,
            prompt=call.request,
            response=call.result.payload,
            outcome=transcript_outcome,
            comment=transcript_comment,
            accounting=call.result.accounting,
            provider=call.result.resolved_provider,
            model=call.result.resolved_model,
        )
        self._repository.record_validated(
            claim,
            call.reservation,
            validated,
            call.reservation.provider_input.cache_identity,
        )
        self._checkpoint("after_validation", claim.job.job_id)
        return validated

    def _accept_result(
        self,
        claim: JobClaim,
        reservation: AttemptReservation | None,
        cache_identity: CacheIdentity,
        result: ValidatedWorkflowResult,
    ) -> None:
        if reservation is None:
            self._repository.record_validated(claim, None, result, cache_identity)
            self._checkpoint("after_validation", claim.job.job_id)
        self._repository.store_cache(claim, cache_identity, result)
        self._repository.finalize_job(
            claim,
            JobResolution.ACCEPTED,
            result.result_identity,
            None,
            None,
            None,
        )
        self._checkpoint("after_finalization", claim.job.job_id)
        self._repository.publish_job(claim)
        self._checkpoint("after_publication", claim.job.job_id)

    def _finalize_from_call_failure(
        self,
        claim: JobClaim,
        failure: _CallFailure,
        *,
        local_invalid: bool = False,
    ) -> None:
        if failure.failure is WorkflowFailure.RESOURCE_LIMIT:
            resolution = JobResolution.STRUCTURAL_FALLBACK
            code = WorkflowFailure.RESOURCE_LIMIT
        elif failure.transmission is TransmissionDisposition.INDETERMINATE:
            resolution = JobResolution.INDETERMINATE
            code = WorkflowFailure.INDETERMINATE
        elif failure.failure is WorkflowFailure.CANCELLED:
            resolution = JobResolution.CANCELLED
            code = WorkflowFailure.CANCELLED
        elif failure.transmission is TransmissionDisposition.NOT_TRANSMITTED:
            resolution = JobResolution.RESUMABLE
            code = WorkflowFailure.NOT_TRANSMITTED
        else:
            resolution = JobResolution.STRUCTURAL_FALLBACK
            code = WorkflowFailure.INVALID_RESPONSE if local_invalid else failure.failure
        resume_call_kind = (
            failure.reservation.call_kind
            if resolution in {JobResolution.RESUMABLE, JobResolution.INDETERMINATE}
            and failure.reservation is not None
            else None
        )
        self._repository.finalize_job(
            claim,
            resolution,
            None,
            code,
            _SANITIZED_REASONS[code],
            resume_call_kind,
        )
        self._checkpoint("after_finalization", claim.job.job_id)
        if resolution is JobResolution.STRUCTURAL_FALLBACK:
            self._repository.publish_job(claim)
            self._checkpoint("after_publication", claim.job.job_id)

    def _finalize_structural(self, claim: JobClaim, failure: WorkflowFailure) -> None:
        self._repository.finalize_job(
            claim,
            JobResolution.STRUCTURAL_FALLBACK,
            None,
            failure,
            _SANITIZED_REASONS[failure],
            None,
        )
        self._checkpoint("after_finalization", claim.job.job_id)
        self._repository.publish_job(claim)
        self._checkpoint("after_publication", claim.job.job_id)

    def _finalize_cancelled(self, claim: JobClaim) -> None:
        self._repository.finalize_job(
            claim,
            JobResolution.CANCELLED,
            None,
            WorkflowFailure.CANCELLED,
            _SANITIZED_REASONS[WorkflowFailure.CANCELLED],
            None,
        )

    def _complete_not_transmitted(
        self,
        claim: JobClaim,
        reservation: AttemptReservation,
        failure: WorkflowFailure,
    ) -> None:
        self._repository.complete_attempt(
            claim,
            reservation,
            AttemptCompletion(
                stage=AttemptStage.NOT_TRANSMITTED,
                transmission=TransmissionDisposition.NOT_TRANSMITTED,
                accounting=AttemptAccounting.zero(),
                response_identity=None,
                failure=failure,
                sanitized_reason=_SANITIZED_REASONS[failure],
            ),
        )

    def _record_provider_failure(
        self,
        claim: JobClaim,
        reservation: AttemptReservation,
        error: WorkflowProviderError,
    ) -> tuple[WorkflowFailure, TransmissionDisposition]:
        try:
            validate_transmission_accounting(error.transmission, error.accounting)
        except (TypeError, ValueError):
            self._repository.complete_attempt(
                claim,
                reservation,
                AttemptCompletion(
                    stage=AttemptStage.INDETERMINATE,
                    transmission=TransmissionDisposition.INDETERMINATE,
                    accounting=error.accounting,
                    response_identity=None,
                    failure=WorkflowFailure.INDETERMINATE,
                    sanitized_reason=_SANITIZED_REASONS[WorkflowFailure.INDETERMINATE],
                ),
            )
            return WorkflowFailure.INDETERMINATE, TransmissionDisposition.INDETERMINATE
        if error.transmission is TransmissionDisposition.NOT_TRANSMITTED:
            stage = AttemptStage.NOT_TRANSMITTED
        elif error.transmission is TransmissionDisposition.INDETERMINATE:
            stage = AttemptStage.INDETERMINATE
        else:
            stage = AttemptStage.RETURNED
        self._repository.complete_attempt(
            claim,
            reservation,
            AttemptCompletion(
                stage=stage,
                transmission=error.transmission,
                accounting=error.accounting,
                response_identity=None,
                failure=error.failure,
                sanitized_reason=_SANITIZED_REASONS[error.failure],
            ),
        )
        return error.failure, error.transmission

    def _start_cancellation_monitor(
        self,
        run_id: str,
        provider: WorkflowProvider,
    ) -> tuple[threading.Event, threading.Thread]:
        stop = threading.Event()

        def monitor() -> None:
            while not stop.wait(0.01):
                if self._repository.is_cancelled(run_id):
                    with suppress(Exception):
                        provider.cancel()
                    return

        thread = threading.Thread(
            target=monitor, name="story-map-v2-workflow-cancel", daemon=True
        )
        thread.start()
        return stop, thread


def _append_ai_transcript(
    *,
    job_id: str,
    attempt_id: str,
    call_kind: ProviderCallKind,
    prompt: bytes,
    response: bytes | None,
    outcome: str,
    comment: str,
    accounting: AttemptAccounting,
    provider: str,
    model: str,
) -> None:
    """Append an explicitly enabled private local provider transcript outside durable storage."""

    target = os.environ.get(_AI_TRANSCRIPT_ENV)
    if not target:
        return
    record = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "job_id": job_id,
        "attempt_id": attempt_id,
        "call_kind": call_kind.value,
        "provider": provider,
        "model": model,
        "outcome": outcome,
        "comment": comment,
        "accounting": {
            "calls": accounting.calls,
            "input_tokens": accounting.input_tokens,
            "output_tokens": accounting.output_tokens,
            "elapsed_ms": accounting.elapsed_ms,
        },
        "prompt": _transcript_payload(prompt),
        "response": None if response is None else _transcript_payload(response),
    }
    try:
        path = Path(target).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with _AI_TRANSCRIPT_LOCK, path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(f"{line}\n")
    except (OSError, ValueError):
        # Debug retention must never change workflow success or failure behavior.
        return


def _transcript_payload(payload: bytes) -> object:
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return payload.decode("utf-8", errors="replace")


def _provider_input(
    policy: WorkflowPolicy,
    claim: JobClaim,
    settings: ProviderSettings,
) -> ProviderInputIdentity:
    mode = settings.mode
    result = policy.input_identity(claim.job.serialized_request_identity, mode=mode)
    if settings.mode is ProviderMode.CLOUD and result.cache_identity != claim.job.cache_identity:
        raise WorkflowApprovalError("claimed job cache identity changed after approval")
    return result


def _validate_derived_ceilings(
    plan: WorkflowPlanDescriptor,
    ceilings: WorkflowResourceCeilings,
) -> None:
    semantic = plan.derived_semantic_plan
    actual = (
        ceilings.section_synthesis_calls,
        ceilings.route_reduction_calls,
        ceilings.route_summary_calls,
        ceilings.whole_game_reduction_calls,
        ceilings.final_overview_calls,
        ceilings.rollup_synthesis_calls,
    )
    if semantic is None:
        if any(actual):
            raise ValueError("derived semantic ceilings require a frozen semantic plan")
        return
    expected = (
        semantic.section_synthesis_calls,
        semantic.route_reduction_calls,
        semantic.route_summary_calls,
        semantic.whole_game_reduction_calls,
        semantic.final_overview_calls,
        semantic.rollup_synthesis_calls,
    )
    if actual != expected:
        raise ValueError("derived semantic ceilings changed from the frozen semantic plan")


def _provider_identity_failure(
    result: ProviderCallResult,
    expected: ProviderSettings,
) -> WorkflowFailure | None:
    if (
        result.resolved_provider != expected.provider
        or result.resolved_model != expected.model
        or result.resolved_reasoning != expected.reasoning
        or result.resolved_fast_mode != expected.fast_mode
    ):
        return WorkflowFailure.IDENTITY_MISMATCH
    return None


def _validate_durable_result(
    result: ValidatedWorkflowResult,
    *,
    prohibited_request: bytes | None = None,
) -> None:
    payload = result.normalized_payload
    scan_payload = _without_python_owned_mechanics(payload)
    if _ABSOLUTE_PATH.search(scan_payload) is not None or any(
        marker in scan_payload for marker in _SOURCE_PACKET_MARKERS
    ):
        raise WorkflowValidationError("normalized workflow result contains prohibited material")
    if prohibited_request is not None and prohibited_request in payload:
        raise WorkflowValidationError("normalized workflow result retained the request packet")


def _without_python_owned_mechanics(payload: bytes) -> bytes:
    """Exclude exact authority mechanics from the provider-material privacy scan."""

    try:
        value: object = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return payload

    def scrub(item: object) -> object:
        if isinstance(item, dict):
            return {
                key: "" if key == "canonical_mechanics" else scrub(child)
                for key, child in item.items()
            }
        if isinstance(item, list):
            return [scrub(child) for child in item]
        return item

    return json.dumps(
        scrub(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _same_digest(left: str, right: str) -> bool:
    return isinstance(right, str) and hmac.compare_digest(left, right)


_SANITIZED_REASONS = {
    WorkflowFailure.CONTENT_REFUSAL: "The cloud mapper declined this story section.",
    WorkflowFailure.NOT_TRANSMITTED: "The provider call definitely did not transmit.",
    WorkflowFailure.INDETERMINATE: (
        "Transmission could not be determined; retry approval is required."
    ),
    WorkflowFailure.INVALID_RESPONSE: "The mapper result was invalid; structural coverage remains.",
    WorkflowFailure.PROVIDER_UNAVAILABLE: "The configured mapper is unavailable.",
    WorkflowFailure.IDENTITY_MISMATCH: "The mapper identity or request identity did not match.",
    WorkflowFailure.RESOURCE_LIMIT: "The approved finite workflow ceiling was reached.",
    WorkflowFailure.CANCELLED: "Story Map generation was cancelled.",
}
