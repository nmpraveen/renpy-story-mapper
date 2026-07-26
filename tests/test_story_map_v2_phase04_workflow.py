from __future__ import annotations

import hashlib
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from renpy_story_mapper.story_map_v2.workflow_contracts import (
    GLOBAL_SUBMISSION_SLOTS,
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
    SerializedRequestIdentity,
    TransmissionDisposition,
    ValidatedWorkflowResult,
    WorkflowAccounting,
    WorkflowApproval,
    WorkflowFailure,
    WorkflowJobDescriptor,
    WorkflowPlanDescriptor,
    WorkflowPolicy,
    WorkflowPreview,
    WorkflowPrivacyScope,
    WorkflowResourceCeilings,
    WorkflowStatus,
)
from renpy_story_mapper.story_map_v2.workflow_protocols import (
    ProviderFactory,
    WorkflowCheckpoint,
    WorkflowProviderError,
)
from renpy_story_mapper.story_map_v2.workflow_service import (
    StoryMapWorkflowService,
    WorkflowApprovalError,
)


@dataclass
class _Attempt:
    reservation: AttemptReservation
    stage: AttemptStage = AttemptStage.RESERVED
    completion: AttemptCompletion | None = None


def _attempt_consumes_call_budget(attempt: _Attempt) -> bool:
    if attempt.completion is None:
        return True
    return attempt.completion.accounting.calls == 1


@dataclass
class _Job:
    descriptor: WorkflowJobDescriptor
    state: str = "pending"
    resolution: JobResolution | None = None
    result: ValidatedWorkflowResult | None = None
    attempts: list[_Attempt] = field(default_factory=list)
    defer_epoch: int = -1
    retry_attempt_id: str | None = None
    resume_call_kind: ProviderCallKind | None = None
    claimed_by: str | None = None
    previous_state: str | None = None


@dataclass
class _Run:
    preview: WorkflowPreview
    approval: WorkflowApproval | None = None
    cancelled: bool = False
    epoch: int = 0
    jobs: dict[str, _Job] = field(default_factory=dict)
    execution_ids: set[str] = field(default_factory=set)


class MemoryWorkflowRepository:
    """Public synthetic fake for the transactional B1 repository contract."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.runs: dict[str, _Run] = {}
        self.cache: dict[CacheIdentity, ValidatedWorkflowResult] = {}
        self.active_claims = 0
        self.active_submitting = 0
        self.max_submitting = 0
        self.durable: list[object] = []
        self.cancellation_persisted = False

    def store_prepared(self, preview: WorkflowPreview) -> None:
        with self._lock:
            self.runs[preview.run_id] = _Run(
                preview=preview,
                jobs={job.job_id: _Job(job) for job in preview.plan.jobs},
            )
            self.durable.append(preview)

    def load_preview(self, run_id: str) -> WorkflowPreview:
        with self._lock:
            return self.runs[run_id].preview

    def store_approval(self, run_id: str, approval: WorkflowApproval) -> None:
        with self._lock:
            self.runs[run_id].approval = approval
            self.durable.append(approval)

    def load_approval(self, run_id: str) -> WorkflowApproval | None:
        with self._lock:
            return self.runs[run_id].approval

    def load_cache(self, cache_identity: CacheIdentity) -> ValidatedWorkflowResult | None:
        with self._lock:
            return self.cache.get(cache_identity)

    def load_published_result(
        self, run_id: str, job_id: str
    ) -> ValidatedWorkflowResult | None:
        with self._lock:
            job = self.runs[run_id].jobs[job_id]
            if job.state == "published" and job.resolution is JobResolution.ACCEPTED:
                return job.result
            return None

    def begin_execution(
        self, run_id: str, preview_identity: str, authority_identity: str
    ) -> str:
        with self._lock:
            run = self.runs[run_id]
            assert run.preview.identity == preview_identity
            assert run.preview.plan.authority_identity.value == authority_identity
            run.epoch += 1
            execution_id = f"execution-{run.epoch}"
            run.execution_ids.add(execution_id)
            return execution_id

    def claim_next_job(
        self,
        run_id: str,
        execution_id: str,
        worker_id: str,
        *,
        submission_slots: int,
    ) -> JobClaim | None:
        with self._lock:
            run = self.runs[run_id]
            assert execution_id in run.execution_ids
            assert submission_slots == GLOBAL_SUBMISSION_SLOTS
            if run.cancelled or self.active_claims >= submission_slots:
                return None
            if self._over_finite_accounting(run):
                return None
            for job in run.jobs.values():
                eligible = job.state == "pending" or (
                    job.state == "resumable" and job.defer_epoch < run.epoch
                )
                if job.state == "review_pending":
                    eligible = True
                if job.state == "fallback_pending":
                    eligible = True
                if job.state == "indeterminate" and job.retry_attempt_id is not None:
                    eligible = True
                if not eligible or job.claimed_by is not None:
                    continue
                job.previous_state = job.state
                job.state = "claimed"
                job.claimed_by = worker_id
                self.active_claims += 1
                claim_id = f"claim-{run.epoch}-{job.descriptor.job_id}"
                resume_call_kind = job.resume_call_kind
                return JobClaim(
                    run_id,
                    execution_id,
                    claim_id,
                    worker_id,
                    job.descriptor,
                    resume_call_kind,
                )
            return None

    def reserve_attempt(
        self,
        claim: JobClaim,
        call_kind: ProviderCallKind,
        provider_input: ProviderInputIdentity,
        ceilings: WorkflowResourceCeilings,
    ) -> AttemptReservation | None:
        with self._lock:
            run = self.runs[claim.run_id]
            job = run.jobs[claim.job.job_id]
            assert job.claimed_by == claim.worker_id
            assert ceilings == run.preview.ceilings
            is_indeterminate_retry = job.previous_state == "indeterminate"
            retry_of_attempt_id: str | None = None
            if is_indeterminate_retry:
                if (
                    job.retry_attempt_id is None
                    or claim.resume_call_kind is not call_kind
                ):
                    return None
                latest = job.attempts[-1]
                if (
                    latest.reservation.attempt_id != job.retry_attempt_id
                    or latest.stage is not AttemptStage.INDETERMINATE
                ):
                    return None
                retry_of_attempt_id = job.retry_attempt_id
            role_count = sum(
                _attempt_consumes_call_budget(attempt)
                and attempt.reservation.call_kind is call_kind
                for item in run.jobs.values()
                for attempt in item.attempts
            )
            role_limit = {
                ProviderCallKind.MAPPING: ceilings.mapping_calls,
                ProviderCallKind.REPLACEMENT_REVIEW: ceilings.review_calls,
                ProviderCallKind.REFUSAL_FALLBACK: ceilings.fallback_calls,
            }[call_kind]
            uses_supplemental = role_count >= role_limit
            if uses_supplemental:
                supplemental_used = sum(
                    attempt.reservation.uses_supplemental_retry_capacity
                    for item in run.jobs.values()
                    for attempt in item.attempts
                )
                job_supplemental_used = any(
                    attempt.reservation.uses_supplemental_retry_capacity
                    for attempt in job.attempts
                )
                if (
                    retry_of_attempt_id is None
                    or supplemental_used >= ceilings.indeterminate_retry_calls
                    or job_supplemental_used
                ):
                    return None
            ordinal = len(job.attempts) + 1
            reservation = AttemptReservation(
                attempt_id=f"{job.descriptor.job_id}-attempt-{ordinal}",
                ordinal=ordinal,
                call_kind=call_kind,
                provider_input=provider_input,
                retry_of_attempt_id=retry_of_attempt_id,
                uses_supplemental_retry_capacity=uses_supplemental,
            )
            job.attempts.append(_Attempt(reservation))
            job.retry_attempt_id = None
            job.resume_call_kind = None
            self.durable.append(reservation)
            return reservation

    def mark_submitting(self, claim: JobClaim, reservation: AttemptReservation) -> bool:
        with self._lock:
            if self.runs[claim.run_id].cancelled:
                return False
            attempt = self._attempt(claim, reservation)
            attempt.stage = AttemptStage.SUBMITTING
            self.active_submitting += 1
            self.max_submitting = max(self.max_submitting, self.active_submitting)
            return True

    def complete_attempt(
        self,
        claim: JobClaim,
        reservation: AttemptReservation,
        completion: AttemptCompletion,
    ) -> None:
        with self._lock:
            attempt = self._attempt(claim, reservation)
            if attempt.stage is AttemptStage.SUBMITTING:
                self.active_submitting -= 1
            attempt.stage = completion.stage
            attempt.completion = completion
            self.durable.append(completion)

    def record_validated(
        self,
        claim: JobClaim,
        reservation: AttemptReservation | None,
        result: ValidatedWorkflowResult,
    ) -> None:
        with self._lock:
            job = self.runs[claim.run_id].jobs[claim.job.job_id]
            if reservation is not None:
                self._attempt(claim, reservation).stage = AttemptStage.VALIDATED
            job.result = result
            job.state = "validated"
            self.durable.append(result)

    def store_cache(
        self, cache_identity: CacheIdentity, result: ValidatedWorkflowResult
    ) -> None:
        with self._lock:
            self.cache[cache_identity] = result
            self.durable.extend((cache_identity, result))

    def finalize_job(
        self,
        claim: JobClaim,
        resolution: JobResolution,
        result_identity: str | None,
        failure: WorkflowFailure | None,
        sanitized_reason: str | None,
        resume_call_kind: ProviderCallKind | None,
    ) -> None:
        with self._lock:
            run = self.runs[claim.run_id]
            job = run.jobs[claim.job.job_id]
            job.resolution = resolution
            if resolution is JobResolution.ACCEPTED:
                assert result_identity is not None
                job.state = "accepted"
            elif resolution is JobResolution.STRUCTURAL_FALLBACK:
                job.state = "structural"
            elif resolution is JobResolution.RESUMABLE:
                job.state = "resumable"
                job.defer_epoch = run.epoch
            elif resolution is JobResolution.INDETERMINATE:
                job.state = "indeterminate"
            else:
                job.state = "cancelled"
            job.resume_call_kind = resume_call_kind
            if job.attempts and job.attempts[-1].stage is AttemptStage.VALIDATED:
                job.attempts[-1].stage = AttemptStage.FINALIZED
            self.durable.extend((resolution, result_identity, failure, sanitized_reason))

    def publish_job(self, claim: JobClaim) -> None:
        with self._lock:
            job = self.runs[claim.run_id].jobs[claim.job.job_id]
            assert job.state in {"accepted", "structural"}
            job.state = "published"
            if job.attempts and job.attempts[-1].stage is AttemptStage.FINALIZED:
                job.attempts[-1].stage = AttemptStage.PUBLISHED

    def release_claim(self, claim: JobClaim) -> None:
        with self._lock:
            job = self.runs[claim.run_id].jobs[claim.job.job_id]
            if job.claimed_by is None:
                return
            if job.state == "claimed":
                assert job.previous_state is not None
                job.state = job.previous_state
            job.claimed_by = None
            job.previous_state = None
            self.active_claims -= 1

    def persist_cancellation(self, run_id: str) -> None:
        with self._lock:
            self.runs[run_id].cancelled = True
            self.cancellation_persisted = True
            self.durable.append("cancelled")

    def is_cancelled(self, run_id: str) -> bool:
        with self._lock:
            return self.runs[run_id].cancelled

    def recover(self, run_id: str) -> RecoveryReport:
        with self._lock:
            run = self.runs[run_id]
            not_transmitted: list[str] = []
            indeterminate: list[str] = []
            finalized: list[str] = []
            published: list[str] = []
            policy_resume: list[str] = []
            for job in run.jobs.values():
                if job.state == "published":
                    continue
                reserved = [
                    attempt
                    for attempt in job.attempts
                    if attempt.stage is AttemptStage.RESERVED
                ]
                uncertain = [
                    attempt
                    for attempt in job.attempts
                    if attempt.stage
                    in {AttemptStage.SUBMITTING, AttemptStage.INDETERMINATE}
                    or (
                        attempt.stage is AttemptStage.RETURNED
                        and (
                            attempt.completion is None
                            or attempt.completion.failure
                            is not WorkflowFailure.CONTENT_REFUSAL
                            or attempt.completion.transmission
                            is not TransmissionDisposition.TRANSMITTED
                        )
                    )
                ]
                refusal = [
                    attempt
                    for attempt in job.attempts
                    if attempt.stage is AttemptStage.RETURNED
                    and attempt.completion is not None
                    and attempt.completion.failure is WorkflowFailure.CONTENT_REFUSAL
                    and attempt.completion.transmission
                    is TransmissionDisposition.TRANSMITTED
                ]
                if reserved:
                    job.state = "resumable"
                    job.defer_epoch = run.epoch
                    job.resume_call_kind = reserved[-1].reservation.call_kind
                    not_transmitted.append(job.descriptor.job_id)
                    for attempt in reserved:
                        attempt.stage = AttemptStage.NOT_TRANSMITTED
                elif uncertain:
                    job.state = "indeterminate"
                    job.resume_call_kind = uncertain[-1].reservation.call_kind
                    indeterminate.append(job.descriptor.job_id)
                    for attempt in uncertain:
                        attempt.stage = AttemptStage.INDETERMINATE
                elif refusal and run.preview.policy.allow_refusal_fallback:
                    job.state = "fallback_pending"
                    job.resume_call_kind = ProviderCallKind.REFUSAL_FALLBACK
                    policy_resume.append(job.descriptor.job_id)
                elif job.state == "validated":
                    assert job.result is not None
                    latest_kind = job.attempts[-1].reservation.call_kind
                    if (
                        job.result.flagged_for_review
                        and latest_kind is ProviderCallKind.MAPPING
                    ):
                        job.state = "review_pending"
                        job.resume_call_kind = ProviderCallKind.REPLACEMENT_REVIEW
                        policy_resume.append(job.descriptor.job_id)
                    else:
                        job.resolution = JobResolution.ACCEPTED
                        job.state = "published"
                        finalized.append(job.descriptor.job_id)
                        published.append(job.descriptor.job_id)
                elif job.state in {"accepted", "structural"}:
                    job.state = "published"
                    published.append(job.descriptor.job_id)
            self.active_submitting = 0
            return RecoveryReport(
                tuple(not_transmitted),
                tuple(indeterminate),
                tuple(finalized),
                tuple(published),
                tuple(policy_resume),
            )

    def store_retry_approval(self, run_id: str, approval: JobRetryApproval) -> None:
        with self._lock:
            job = self.runs[run_id].jobs[approval.job_id]
            assert job.state == "indeterminate"
            latest = job.attempts[-1]
            assert latest.reservation.attempt_id == approval.indeterminate_attempt_id
            assert latest.stage is AttemptStage.INDETERMINATE
            assert job.retry_attempt_id is None
            job.retry_attempt_id = approval.indeterminate_attempt_id
            self.durable.append(approval)

    def status(self, run_id: str) -> WorkflowStatus:
        with self._lock:
            run = self.runs[run_id]
            states = [job.state for job in run.jobs.values()]
            accounting = self._accounting(run)
            return WorkflowStatus(
                run_id=run_id,
                preview_identity=run.preview.identity,
                approved=run.approval is not None,
                cancelled=run.cancelled,
                pending_jobs=sum(
                    state in {"pending", "claimed", "review_pending"} for state in states
                ),
                active_jobs=sum(job.claimed_by is not None for job in run.jobs.values()),
                accepted_jobs=sum(
                    job.resolution is JobResolution.ACCEPTED for job in run.jobs.values()
                ),
                structural_fallback_jobs=sum(
                    job.resolution is JobResolution.STRUCTURAL_FALLBACK
                    for job in run.jobs.values()
                ),
                resumable_jobs=states.count("resumable"),
                indeterminate_jobs=states.count("indeterminate"),
                accounting=accounting,
            )

    def attempt_ordinals(self, run_id: str, job_id: str) -> list[int]:
        with self._lock:
            return [
                attempt.reservation.ordinal
                for attempt in self.runs[run_id].jobs[job_id].attempts
            ]

    def last_attempt_id(self, run_id: str, job_id: str) -> str:
        with self._lock:
            return self.runs[run_id].jobs[job_id].attempts[-1].reservation.attempt_id

    def _attempt(self, claim: JobClaim, reservation: AttemptReservation) -> _Attempt:
        job = self.runs[claim.run_id].jobs[claim.job.job_id]
        return next(
            item
            for item in job.attempts
            if item.reservation.attempt_id == reservation.attempt_id
        )

    def _accounting(self, run: _Run) -> WorkflowAccounting:
        completions = [
            attempt.completion
            for job in run.jobs.values()
            for attempt in job.attempts
            if attempt.completion is not None
        ]
        return WorkflowAccounting(
            calls=sum(item.accounting.calls for item in completions),
            input_tokens=sum(item.accounting.input_tokens for item in completions),
            output_tokens=sum(item.accounting.output_tokens for item in completions),
            elapsed_ms=sum(item.accounting.elapsed_ms for item in completions),
        )

    def _over_finite_accounting(self, run: _Run) -> bool:
        used = self._accounting(run)
        ceiling = run.preview.ceilings
        return (
            used.input_tokens >= ceiling.input_tokens
            or used.output_tokens >= ceiling.output_tokens
            or used.elapsed_ms >= ceiling.elapsed_ms
        )


class CancelOnMarkRepository(MemoryWorkflowRepository):
    def __init__(self) -> None:
        super().__init__()
        self.on_mark: Callable[[], None] | None = None

    def mark_submitting(
        self, claim: JobClaim, reservation: AttemptReservation
    ) -> bool:
        if self.on_mark is not None:
            self.on_mark()
        if self.is_cancelled(claim.run_id):
            return False
        return super().mark_submitting(claim, reservation)


class DictMaterializer:
    def __init__(self, requests: dict[str, bytes]) -> None:
        self.requests = requests

    def materialize(self, identity: SerializedRequestIdentity) -> bytes:
        return self.requests[identity.value]


class SyntheticValidator:
    def __init__(self, rejected_authority: str | None = None) -> None:
        self.rejected_authority = rejected_authority
        self.cached_validations = 0

    def validate(
        self,
        job: WorkflowJobDescriptor,
        payload: bytes,
        *,
        cached: bool,
    ) -> ValidatedWorkflowResult:
        if cached:
            self.cached_validations += 1
        if job.authority_identity.value == self.rejected_authority or payload == b"invalid":
            raise ValueError("SECRET raw source validation detail")
        if payload == b"absolute-path":
            normalized = b'{"summary":"C:\\Users\\private\\story.rpy"}'
        elif payload == b"nested-posix-path":
            normalized = b'{"outer":{"items":[{"path":"/opt/private/story.rpy"}]}}'
        elif payload.startswith(b"normalized:"):
            normalized = payload
        else:
            normalized = b"normalized:" + payload
        return ValidatedWorkflowResult(
            hashlib.sha256(normalized).hexdigest(),
            normalized,
            flagged_for_review=payload == b"flagged",
        )


class RecordingFactory:
    def __init__(
        self,
        settings: ProviderSettings,
        outcomes: list[ProviderCallResult | BaseException],
    ) -> None:
        self.settings = settings
        self._outcomes = deque(outcomes)
        self._lock = threading.Lock()
        self.constructions = 0
        self.calls = 0
        self.cancel_calls = 0

    def __call__(self) -> RecordingProvider:
        with self._lock:
            self.constructions += 1
        return RecordingProvider(self)

    def next_outcome(self) -> ProviderCallResult | BaseException:
        with self._lock:
            self.calls += 1
            if not self._outcomes:
                raise AssertionError("unexpected provider call")
            return self._outcomes.popleft()


class RecordingProvider:
    def __init__(self, factory: RecordingFactory) -> None:
        self.factory = factory

    def submit(self, request: bytes) -> ProviderCallResult:
        assert request
        outcome = self.factory.next_outcome()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def cancel(self) -> None:
        with self.factory._lock:
            self.factory.cancel_calls += 1


class ConstructionFailureOnce(RecordingFactory):
    def __call__(self) -> RecordingProvider:
        with self._lock:
            self.constructions += 1
            current = self.constructions
        if current == 1:
            raise RuntimeError("SECRET provider construction detail")
        return RecordingProvider(self)


class ConstructionTrap:
    def __init__(self) -> None:
        self.constructions = 0

    def __call__(self) -> RecordingProvider:
        self.constructions += 1
        raise AssertionError("provider must not be constructed")


class BarrierFactory(RecordingFactory):
    def __init__(self, settings: ProviderSettings, jobs: int) -> None:
        super().__init__(settings, [])
        self.jobs = jobs
        self.barrier = threading.Barrier(GLOBAL_SUBMISSION_SLOTS)
        self.active = 0
        self.max_active = 0

    def __call__(self) -> BarrierProvider:
        with self._lock:
            self.constructions += 1
        return BarrierProvider(self)


class BarrierProvider(RecordingProvider):
    factory: BarrierFactory

    def __init__(self, factory: BarrierFactory) -> None:
        super().__init__(factory)
        self.factory = factory

    def submit(self, request: bytes) -> ProviderCallResult:
        del request
        with self.factory._lock:
            self.factory.calls += 1
            call_number = self.factory.calls
            self.factory.active += 1
            self.factory.max_active = max(self.factory.max_active, self.factory.active)
        try:
            if call_number <= GLOBAL_SUBMISSION_SLOTS:
                self.factory.barrier.wait(timeout=5)
            return _reply(self.factory.settings, f"ok-{call_number}".encode())
        finally:
            with self.factory._lock:
                self.factory.active -= 1


class BlockingCancellationFactory(RecordingFactory):
    def __init__(self, settings: ProviderSettings, repository: MemoryWorkflowRepository) -> None:
        super().__init__(settings, [])
        self.repository = repository
        self.started = threading.Event()
        self.cancelled = threading.Event()

    def __call__(self) -> BlockingCancellationProvider:
        with self._lock:
            self.constructions += 1
        return BlockingCancellationProvider(self)


class BlockingCancellationProvider(RecordingProvider):
    factory: BlockingCancellationFactory

    def __init__(self, factory: BlockingCancellationFactory) -> None:
        super().__init__(factory)
        self.factory = factory

    def submit(self, request: bytes) -> ProviderCallResult:
        del request
        with self.factory._lock:
            self.factory.calls += 1
        self.factory.started.set()
        assert self.factory.cancelled.wait(timeout=5)
        raise WorkflowProviderError(
            WorkflowFailure.CANCELLED,
            TransmissionDisposition.TRANSMITTED,
            AttemptAccounting(1, 1, 0, 1),
        )

    def cancel(self) -> None:
        assert self.factory.repository.cancellation_persisted
        with self.factory._lock:
            self.factory.cancel_calls += 1
        self.factory.cancelled.set()


class EchoFactory(RecordingFactory):
    def __init__(self, settings: ProviderSettings) -> None:
        super().__init__(settings, [])

    def __call__(self) -> EchoProvider:
        with self._lock:
            self.constructions += 1
        return EchoProvider(self)


class EchoProvider(RecordingProvider):
    factory: EchoFactory

    def __init__(self, factory: EchoFactory) -> None:
        super().__init__(factory)
        self.factory = factory

    def submit(self, request: bytes) -> ProviderCallResult:
        with self.factory._lock:
            self.factory.calls += 1
        return _reply(self.factory.settings, request)


class SimulatedProcessCrash(BaseException):
    pass


class FaultOnce:
    def __init__(self, checkpoint: str) -> None:
        self.checkpoint = checkpoint
        self.triggered = False

    def __call__(self, name: str, job_id: str) -> None:
        del job_id
        if name == self.checkpoint and not self.triggered:
            self.triggered = True
            raise SimulatedProcessCrash(name)


class FaultOnOccurrence:
    def __init__(self, checkpoint: str, occurrence: int) -> None:
        self.checkpoint = checkpoint
        self.occurrence = occurrence
        self.seen = 0

    def __call__(self, name: str, job_id: str) -> None:
        del job_id
        if name != self.checkpoint:
            return
        self.seen += 1
        if self.seen == self.occurrence:
            raise SimulatedProcessCrash(name)


def _cloud_settings() -> ProviderSettings:
    return ProviderSettings(
        provider="codex-cli",
        model="gpt-5.6-terra",
        reasoning="high",
        fast_mode=False,
        mode=ProviderMode.CLOUD,
        adapter_version="sterile-cloud-v1",
    )


def _local_settings() -> ProviderSettings:
    return ProviderSettings(
        provider="lm-studio-loopback",
        model="qwen-public-synthetic",
        reasoning=None,
        fast_mode=None,
        mode=ProviderMode.LOOPBACK,
        adapter_version="sterile-loopback-v1",
    )


def _policy(*, fallback: bool = False) -> WorkflowPolicy:
    return WorkflowPolicy(
        prompt_version="mapper-prompt-v4",
        schema_version="mapper-schema-v4",
        cloud=_cloud_settings(),
        loopback=_local_settings() if fallback else None,
        allow_refusal_fallback=fallback,
    )


def _plan(
    jobs: int,
    policy: WorkflowPolicy,
    *,
    authority: str = "authority-public-v1",
    request_prefix: bytes = b'{"story":"public-',
) -> tuple[WorkflowPlanDescriptor, dict[str, bytes]]:
    authority_identity = AuthorityIdentity(authority)
    descriptors: list[WorkflowJobDescriptor] = []
    requests: dict[str, bytes] = {}
    for index in range(jobs):
        request = request_prefix + str(index).encode() + b'"}'
        serialized = SerializedRequestIdentity(
            value=f"request-{index}",
            sha256=hashlib.sha256(request).hexdigest(),
            byte_count=len(request),
        )
        requests[serialized.value] = request
        descriptors.append(
            WorkflowJobDescriptor(
                plan_id="plan-public-v1",
                scope_id=f"scope-{index // 4}",
                job_id=f"job-{index}",
                chunk_id=f"chunk-{index}",
                authority_identity=authority_identity,
                serialized_request_identity=serialized,
                cache_identity=policy.input_identity(serialized).cache_identity,
                critical=index % 5 == 0,
            )
        )
    return (
        WorkflowPlanDescriptor("plan-public-v1", authority_identity, tuple(descriptors)),
        requests,
    )


def _ceilings(
    jobs: int,
    *,
    reviews: int = 0,
    fallbacks: int = 0,
    retries: int = 0,
) -> WorkflowResourceCeilings:
    return WorkflowResourceCeilings(
        mapping_calls=jobs,
        review_calls=reviews,
        fallback_calls=fallbacks,
        input_tokens=max(1, jobs * 100),
        output_tokens=max(1, jobs * 100),
        elapsed_ms=max(1, jobs * 1_000),
        indeterminate_retry_calls=retries,
    )


def _reply(
    settings: ProviderSettings,
    payload: bytes = b"ok",
    *,
    input_tokens: int = 3,
    output_tokens: int = 2,
    elapsed_ms: int = 5,
) -> ProviderCallResult:
    return ProviderCallResult(
        payload=payload,
        accounting=AttemptAccounting(1, input_tokens, output_tokens, elapsed_ms),
        resolved_provider=settings.provider,
        resolved_model=settings.model,
        resolved_reasoning=settings.reasoning,
        resolved_fast_mode=settings.fast_mode,
    )


def _provider_failure(
    failure: WorkflowFailure,
    transmission: TransmissionDisposition,
    *,
    calls: int,
) -> WorkflowProviderError:
    return WorkflowProviderError(
        failure,
        transmission,
        AttemptAccounting(calls, 4 if calls else 0, 1 if calls else 0, 7 if calls else 0),
    )


def _service(
    repository: MemoryWorkflowRepository,
    requests: dict[str, bytes],
    cloud: ProviderFactory,
    *,
    validator: SyntheticValidator | None = None,
    local: ProviderFactory | None = None,
    checkpoint: WorkflowCheckpoint | None = None,
) -> StoryMapWorkflowService:
    return StoryMapWorkflowService(
        repository,
        DictMaterializer(requests),
        validator or SyntheticValidator(),
        cloud_factory=cloud,
        loopback_factory=local,
        checkpoint=checkpoint,
    )


def _prepare_approve(
    service: StoryMapWorkflowService,
    plan: WorkflowPlanDescriptor,
    policy: WorkflowPolicy,
    ceilings: WorkflowResourceCeilings,
    *,
    run_id: str = "run-public",
) -> WorkflowPreview:
    preview = service.prepare(run_id, plan, policy, ceilings)
    service.approve(run_id, preview.identity)
    return preview


def test_prepare_approve_status_recover_and_cached_reopen_construct_no_provider() -> None:
    policy = _policy()
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    cached = ValidatedWorkflowResult(
        hashlib.sha256(b"normalized:cached").hexdigest(), b"normalized:cached"
    )
    repository.cache[plan.jobs[0].cache_identity] = cached
    trap = ConstructionTrap()
    validator = SyntheticValidator()
    service = _service(repository, requests, trap, validator=validator)

    preview = _prepare_approve(service, plan, policy, _ceilings(1))
    assert preview.cache_hit_job_ids == ("job-0",)
    assert service.status("run-public").approved is True
    assert service.recover("run-public") == RecoveryReport((), (), (), ())
    status = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )

    assert status.accepted_jobs == 1
    assert status.accounting == WorkflowAccounting.zero()
    assert validator.cached_validations == 1
    assert trap.constructions == 0


def test_cache_identity_changes_for_every_provider_input_field_and_excludes_run_routing() -> None:
    request = b"public request"
    serialized = SerializedRequestIdentity(
        "request-a", hashlib.sha256(request).hexdigest(), len(request)
    )
    base = ProviderInputIdentity(
        serialized,
        "prompt-v1",
        "schema-v1",
        "adapter-v1",
        "provider-a",
        "model-a",
        "high",
        False,
        ProviderMode.CLOUD,
    )
    mutations = (
        replace(
            base,
            serialized_request_identity=replace(serialized, value="request-b"),
        ),
        replace(
            base,
            serialized_request_identity=replace(serialized, sha256="1" * 64),
        ),
        replace(
            base,
            serialized_request_identity=replace(serialized, byte_count=len(request) + 1),
        ),
        replace(base, prompt_version="prompt-v2"),
        replace(base, schema_version="schema-v2"),
        replace(base, adapter_version="adapter-v2"),
        replace(base, provider="provider-b"),
        replace(base, model="model-b"),
        replace(base, reasoning="medium"),
        replace(base, fast_mode=True),
        replace(base, mode=ProviderMode.LOOPBACK),
    )
    assert len({item.cache_identity for item in (base, *mutations)}) == len(mutations) + 1
    assert base.cache_identity == replace(base).cache_identity


def test_stale_authority_and_preview_mutations_fail_before_construction() -> None:
    policy = _policy()
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    trap = ConstructionTrap()
    service = _service(repository, requests, trap)
    preview = _prepare_approve(service, plan, policy, _ceilings(1))

    with pytest.raises(WorkflowApprovalError):
        service.execute(
            "run-public",
            preview_identity=preview.identity,
            authority_identity=AuthorityIdentity("authority-mutated"),
        )
    with pytest.raises(WorkflowApprovalError):
        service.execute(
            "run-public",
            preview_identity="f" * 64,
            authority_identity=plan.authority_identity,
        )

    changed_policy = replace(policy, prompt_version="mapper-prompt-v5")
    changed_serialized = plan.jobs[0].serialized_request_identity
    changed_job = replace(
        plan.jobs[0],
        cache_identity=changed_policy.input_identity(changed_serialized).cache_identity,
    )
    changed_plan = WorkflowPlanDescriptor(
        plan.plan_id, plan.authority_identity, (changed_job,)
    )
    changed_preview = service.prepare(
        "run-public", changed_plan, changed_policy, replace(_ceilings(1), elapsed_ms=2_000)
    )
    with pytest.raises(WorkflowApprovalError):
        service.execute(
            "run-public",
            preview_identity=changed_preview.identity,
            authority_identity=plan.authority_identity,
        )
    assert trap.constructions == 0


def test_preview_identity_binds_every_plan_provider_and_finite_ceiling_field() -> None:
    policy = _policy()
    plan, _requests = _plan(1, policy)
    base = WorkflowPreview(
        "run-a",
        plan,
        policy,
        _ceilings(1),
        WorkflowPrivacyScope(True, False),
        (),
    )
    job = plan.jobs[0]
    other_authority = AuthorityIdentity("authority-public-v2")
    other_request = replace(job.serialized_request_identity, value="request-other")
    adapter_policy = replace(
        policy,
        cloud=replace(policy.cloud, adapter_version="sterile-cloud-v2"),
    )
    fallback_policy = _policy(fallback=True)
    mutations = (
        replace(
            base,
            plan=WorkflowPlanDescriptor(
                "plan-public-v2",
                plan.authority_identity,
                (replace(job, plan_id="plan-public-v2"),),
            ),
        ),
        replace(
            base,
            plan=WorkflowPlanDescriptor(
                plan.plan_id,
                other_authority,
                (replace(job, authority_identity=other_authority),),
            ),
        ),
        replace(
            base,
            plan=WorkflowPlanDescriptor(
                plan.plan_id, plan.authority_identity, (replace(job, scope_id="scope-other"),)
            ),
        ),
        replace(
            base,
            plan=WorkflowPlanDescriptor(
                plan.plan_id, plan.authority_identity, (replace(job, job_id="job-other"),)
            ),
        ),
        replace(
            base,
            plan=WorkflowPlanDescriptor(
                plan.plan_id, plan.authority_identity, (replace(job, chunk_id="chunk-other"),)
            ),
        ),
        replace(
            base,
            plan=WorkflowPlanDescriptor(
                plan.plan_id,
                plan.authority_identity,
                (
                    replace(
                        job,
                        serialized_request_identity=other_request,
                        cache_identity=policy.input_identity(other_request).cache_identity,
                    ),
                ),
            ),
        ),
        replace(base, policy=replace(policy, prompt_version="mapper-prompt-v5")),
        replace(base, policy=replace(policy, schema_version="mapper-schema-v5")),
        replace(
            base,
            policy=adapter_policy,
            plan=WorkflowPlanDescriptor(
                plan.plan_id,
                plan.authority_identity,
                (
                    replace(
                        job,
                        cache_identity=adapter_policy.input_identity(
                            job.serialized_request_identity
                        ).cache_identity,
                    ),
                ),
            ),
        ),
        replace(base, ceilings=replace(base.ceilings, mapping_calls=2)),
        replace(base, ceilings=replace(base.ceilings, review_calls=1)),
        replace(base, ceilings=replace(base.ceilings, fallback_calls=1)),
        replace(base, ceilings=replace(base.ceilings, input_tokens=101)),
        replace(base, ceilings=replace(base.ceilings, output_tokens=101)),
        replace(base, ceilings=replace(base.ceilings, elapsed_ms=1_001)),
        replace(base, ceilings=replace(base.ceilings, indeterminate_retry_calls=1)),
        replace(
            base,
            policy=fallback_policy,
            plan=WorkflowPlanDescriptor(
                plan.plan_id,
                plan.authority_identity,
                (
                    replace(
                        job,
                        cache_identity=fallback_policy.input_identity(
                            job.serialized_request_identity
                        ).cache_identity,
                    ),
                ),
            ),
            privacy=WorkflowPrivacyScope(True, True),
            ceilings=replace(base.ceilings, fallback_calls=1),
        ),
    )
    assert len({item.identity for item in (base, *mutations)}) == len(mutations) + 1
    assert replace(base, run_id="run-routing-only").identity == base.identity
    for change in (
        {"provider": "other"},
        {"model": "other"},
        {"reasoning": "medium"},
        {"fast_mode": True},
        {"mode": ProviderMode.LOOPBACK},
    ):
        with pytest.raises(ValueError, match="exact Terra"):
            replace(policy, cloud=replace(policy.cloud, **change))


def test_changed_cache_hit_set_invalidates_approval_before_provider_construction() -> None:
    policy = _policy()
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    trap = ConstructionTrap()
    service = _service(repository, requests, trap)
    preview = _prepare_approve(service, plan, policy, _ceilings(1))
    repository.cache[plan.jobs[0].cache_identity] = ValidatedWorkflowResult(
        hashlib.sha256(b"normalized:new").hexdigest(), b"normalized:new"
    )

    with pytest.raises(WorkflowApprovalError):
        service.execute(
            "run-public",
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
    assert trap.constructions == 0


def test_sixty_four_job_barrier_proves_hard_max_and_actual_six_slot_use() -> None:
    policy = _policy()
    plan, requests = _plan(64, policy)
    repository = MemoryWorkflowRepository()
    factory = BarrierFactory(policy.cloud, 64)
    service = _service(repository, requests, factory)
    preview = _prepare_approve(service, plan, policy, _ceilings(64))

    status = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )

    assert status.accepted_jobs == 64
    assert status.accounting.calls == 64
    assert factory.calls == factory.constructions == 64
    assert factory.max_active == GLOBAL_SUBMISSION_SLOTS
    assert repository.max_submitting == GLOBAL_SUBMISSION_SLOTS
    assert all(repository.attempt_ordinals("run-public", job.job_id) == [1] for job in plan.jobs)


def test_two_services_share_one_global_six_slot_claim_without_duplicates() -> None:
    policy = _policy()
    plan, requests = _plan(64, policy)
    repository = MemoryWorkflowRepository()
    factory = BarrierFactory(policy.cloud, 64)
    first = _service(repository, requests, factory)
    second = _service(repository, requests, factory)
    preview = _prepare_approve(first, plan, policy, _ceilings(64))
    statuses: list[WorkflowStatus] = []
    errors: list[BaseException] = []
    start = threading.Barrier(2)

    def execute(service: StoryMapWorkflowService) -> None:
        try:
            start.wait(timeout=5)
            statuses.append(
                service.execute(
                    "run-public",
                    preview_identity=preview.identity,
                    authority_identity=plan.authority_identity,
                )
            )
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    threads = (
        threading.Thread(target=execute, args=(first,)),
        threading.Thread(target=execute, args=(second,)),
    )
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert all(not thread.is_alive() for thread in threads)
    assert len(statuses) == 2
    assert repository.status("run-public").accepted_jobs == 64
    assert factory.calls == 64
    assert factory.max_active == repository.max_submitting == GLOBAL_SUBMISSION_SLOTS
    assert all(repository.attempt_ordinals("run-public", job.job_id) == [1] for job in plan.jobs)


def test_cancellation_is_persisted_before_signal_and_starts_no_later_work() -> None:
    policy = _policy()
    plan, requests = _plan(20, policy)
    repository = MemoryWorkflowRepository()
    factory = BlockingCancellationFactory(policy.cloud, repository)
    service = _service(repository, requests, factory)
    preview = _prepare_approve(service, plan, policy, _ceilings(20))
    errors: list[BaseException] = []

    def execute() -> None:
        try:
            service.execute(
                "run-public",
                preview_identity=preview.identity,
                authority_identity=plan.authority_identity,
            )
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    thread = threading.Thread(target=execute)
    thread.start()
    assert factory.started.wait(timeout=5)
    service.cancel("run-public")
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert errors == []
    assert repository.cancellation_persisted
    assert service.status("run-public").cancelled is True
    assert 1 <= factory.calls <= GLOBAL_SUBMISSION_SLOTS
    assert factory.cancel_calls >= 1


def test_atomic_cancel_wins_mark_submitting_race_with_zero_submit_or_publication() -> None:
    policy = _policy()
    plan, requests = _plan(1, policy)
    repository = CancelOnMarkRepository()
    factory = RecordingFactory(policy.cloud, [_reply(policy.cloud)])
    service = _service(repository, requests, factory)
    repository.on_mark = lambda: service.cancel("run-public")
    preview = _prepare_approve(service, plan, policy, _ceilings(1))

    status = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert status.cancelled is True
    assert factory.calls == 0
    assert factory.cancel_calls == 1
    job = repository.runs["run-public"].jobs["job-0"]
    assert job.state == "cancelled"
    assert job.result is None


def test_definite_nontransmission_resumes_once_with_new_attempt_ordinal() -> None:
    policy = _policy()
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    factory = ConstructionFailureOnce(policy.cloud, [_reply(policy.cloud)])
    service = _service(repository, requests, factory)
    preview = _prepare_approve(service, plan, policy, _ceilings(2))

    first = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert first.resumable_jobs == 1
    assert first.accounting.calls == 0
    second = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )

    assert second.accepted_jobs == 1
    assert second.accounting.calls == 1
    assert factory.calls == 1
    assert repository.attempt_ordinals("run-public", "job-0") == [1, 2]


def test_crash_before_local_reservation_resumes_fallback_without_second_cloud_mapping() -> None:
    policy = _policy(fallback=True)
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    refusal = _provider_failure(
        WorkflowFailure.CONTENT_REFUSAL,
        TransmissionDisposition.TRANSMITTED,
        calls=1,
    )
    cloud = RecordingFactory(policy.cloud, [refusal, refusal])
    assert policy.loopback is not None
    local = RecordingFactory(policy.loopback, [_reply(policy.loopback, b"local-ok")])
    service = _service(
        repository,
        requests,
        cloud,
        local=local,
        checkpoint=FaultOnOccurrence("before_reservation", 2),
    )
    preview = _prepare_approve(service, plan, policy, _ceilings(2, fallbacks=1))

    with pytest.raises(SimulatedProcessCrash):
        service.execute(
            "run-public",
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
    recovery = service.recover("run-public")
    assert recovery.policy_resume_jobs == ("job-0",)

    status = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert status.accepted_jobs == 1
    assert cloud.calls == 1
    assert local.calls == 1
    attempts = repository.runs["run-public"].jobs["job-0"].attempts
    assert [attempt.reservation.call_kind for attempt in attempts] == [
        ProviderCallKind.MAPPING,
        ProviderCallKind.REFUSAL_FALLBACK,
    ]


def test_definite_nontransmitted_local_construction_resumes_local_only() -> None:
    policy = _policy(fallback=True)
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    cloud = RecordingFactory(
        policy.cloud,
        [
            _provider_failure(
                WorkflowFailure.CONTENT_REFUSAL,
                TransmissionDisposition.TRANSMITTED,
                calls=1,
            )
        ],
    )
    assert policy.loopback is not None
    local = ConstructionFailureOnce(policy.loopback, [_reply(policy.loopback, b"local-ok")])
    service = _service(repository, requests, cloud, local=local)
    preview = _prepare_approve(service, plan, policy, _ceilings(2, fallbacks=1))

    first = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert first.resumable_jobs == 1
    final = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert final.accepted_jobs == 1
    assert cloud.calls == 1
    assert local.calls == 1
    attempts = repository.runs["run-public"].jobs["job-0"].attempts
    assert [attempt.reservation.call_kind for attempt in attempts] == [
        ProviderCallKind.MAPPING,
        ProviderCallKind.REFUSAL_FALLBACK,
        ProviderCallKind.REFUSAL_FALLBACK,
    ]
    assert [attempt.reservation.ordinal for attempt in attempts] == [1, 2, 3]
    assert service.recover("run-public").policy_resume_jobs == ()
    reopened = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert reopened.accepted_jobs == 1
    assert cloud.calls == local.calls == 1


def test_same_run_completed_cache_is_allowed_during_definite_nontransmission_resume() -> None:
    policy = _policy()
    plan, requests = _plan(2, policy)
    repository = MemoryWorkflowRepository()
    factory = RecordingFactory(
        policy.cloud,
        [
            _reply(policy.cloud, b"completed"),
            _provider_failure(
                WorkflowFailure.PROVIDER_UNAVAILABLE,
                TransmissionDisposition.NOT_TRANSMITTED,
                calls=0,
            ),
            _reply(policy.cloud, b"resumed"),
        ],
    )
    service = _service(repository, requests, factory)
    preview = _prepare_approve(service, plan, policy, _ceilings(3))

    first = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert first.accepted_jobs == first.resumable_jobs == 1
    second = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert second.accepted_jobs == 2
    assert factory.calls == 3
    assert sorted(
        repository.attempt_ordinals("run-public", job.job_id) for job in plan.jobs
    ) == [[1], [1, 2]]


def test_uncertain_transport_never_auto_resubmits_without_job_approval() -> None:
    policy = _policy()
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    factory = RecordingFactory(
        policy.cloud, [RuntimeError("SECRET uncertain"), _reply(policy.cloud)]
    )
    service = _service(repository, requests, factory)
    preview = _prepare_approve(service, plan, policy, _ceilings(2))

    first = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert first.indeterminate_jobs == 1
    assert factory.calls == 1
    unchanged = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert unchanged.indeterminate_jobs == 1
    assert factory.calls == 1

    attempt_id = repository.last_attempt_id("run-public", "job-0")
    service.approve_indeterminate_retry(
        "run-public",
        preview_identity=preview.identity,
        job_id="job-0",
        indeterminate_attempt_id=attempt_id,
    )
    final = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert final.accepted_jobs == 1
    assert factory.calls == 2
    assert repository.attempt_ordinals("run-public", "job-0") == [1, 2]


@pytest.mark.parametrize("indeterminate_calls", [0, 1])
def test_approved_indeterminate_refusal_fallback_retries_loopback_only(
    indeterminate_calls: int,
) -> None:
    policy = _policy(fallback=True)
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    cloud = RecordingFactory(
        policy.cloud,
        [
            _provider_failure(
                WorkflowFailure.CONTENT_REFUSAL,
                TransmissionDisposition.TRANSMITTED,
                calls=1,
            ),
            _reply(policy.cloud, b"wrong-cloud-retry"),
        ],
    )
    assert policy.loopback is not None
    uncertain: BaseException = (
        RuntimeError("uncertain local transport")
        if indeterminate_calls == 0
        else _provider_failure(
            WorkflowFailure.INDETERMINATE,
            TransmissionDisposition.INDETERMINATE,
            calls=1,
        )
    )
    local = RecordingFactory(
        policy.loopback,
        [uncertain, _reply(policy.loopback, b"local-ok")],
    )
    service = _service(repository, requests, cloud, local=local)
    preview = _prepare_approve(
        service,
        plan,
        policy,
        _ceilings(2, fallbacks=1, retries=indeterminate_calls),
    )

    first = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert first.indeterminate_jobs == 1
    assert cloud.calls == local.calls == 1
    service.recover("run-public")
    job = repository.runs["run-public"].jobs["job-0"]
    assert job.resume_call_kind is ProviderCallKind.REFUSAL_FALLBACK
    attempt_id = repository.last_attempt_id("run-public", "job-0")
    if indeterminate_calls == 1:
        with pytest.raises(AssertionError):
            service.approve_indeterminate_retry(
                "run-public",
                preview_identity=preview.identity,
                job_id="job-0",
                indeterminate_attempt_id=job.attempts[0].reservation.attempt_id,
            )
    service.approve_indeterminate_retry(
        "run-public",
        preview_identity=preview.identity,
        job_id="job-0",
        indeterminate_attempt_id=attempt_id,
    )
    if indeterminate_calls == 1:
        execution_id = repository.begin_execution(
            "run-public", preview.identity, plan.authority_identity.value
        )
        claim = repository.claim_next_job(
            "run-public",
            execution_id,
            "wrong-kind-worker",
            submission_slots=GLOBAL_SUBMISSION_SLOTS,
        )
        assert claim is not None
        assert (
            repository.reserve_attempt(
                claim,
                ProviderCallKind.MAPPING,
                policy.input_identity(claim.job.serialized_request_identity),
                preview.ceilings,
            )
            is None
        )
        repository.release_claim(claim)

    final = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert final.accepted_jobs == 1
    assert final.accounting.calls == 2 + indeterminate_calls
    assert cloud.calls == 1
    assert local.calls == 2
    attempts = repository.runs["run-public"].jobs["job-0"].attempts
    assert [attempt.reservation.call_kind for attempt in attempts] == [
        ProviderCallKind.MAPPING,
        ProviderCallKind.REFUSAL_FALLBACK,
        ProviderCallKind.REFUSAL_FALLBACK,
    ]
    assert [attempt.reservation.ordinal for attempt in attempts] == [1, 2, 3]
    retry_reservation = attempts[-1].reservation
    assert retry_reservation.retry_of_attempt_id == attempt_id
    assert retry_reservation.uses_supplemental_retry_capacity is bool(
        indeterminate_calls
    )
    reopened = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert reopened.accepted_jobs == 1
    assert cloud.calls == 1
    assert local.calls == 2


@pytest.mark.parametrize("indeterminate_calls", [0, 1])
def test_approved_indeterminate_replacement_review_retries_review_only(
    indeterminate_calls: int,
) -> None:
    policy = _policy()
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    uncertain: BaseException = (
        RuntimeError("uncertain review transport")
        if indeterminate_calls == 0
        else _provider_failure(
            WorkflowFailure.INDETERMINATE,
            TransmissionDisposition.INDETERMINATE,
            calls=1,
        )
    )
    cloud = RecordingFactory(
        policy.cloud,
        [
            _reply(policy.cloud, b"flagged"),
            uncertain,
            _reply(policy.cloud, b"review-ok"),
        ],
    )
    service = _service(repository, requests, cloud)
    preview = _prepare_approve(
        service,
        plan,
        policy,
        _ceilings(2, reviews=1, retries=indeterminate_calls),
    )

    first = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert first.indeterminate_jobs == 1
    assert cloud.calls == 2
    service.recover("run-public")
    job = repository.runs["run-public"].jobs["job-0"]
    assert job.resume_call_kind is ProviderCallKind.REPLACEMENT_REVIEW
    attempt_id = repository.last_attempt_id("run-public", "job-0")
    service.approve_indeterminate_retry(
        "run-public",
        preview_identity=preview.identity,
        job_id="job-0",
        indeterminate_attempt_id=attempt_id,
    )

    final = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert final.accepted_jobs == 1
    assert final.accounting.calls == 2 + indeterminate_calls
    assert cloud.calls == 3
    attempts = repository.runs["run-public"].jobs["job-0"].attempts
    assert [attempt.reservation.call_kind for attempt in attempts] == [
        ProviderCallKind.MAPPING,
        ProviderCallKind.REPLACEMENT_REVIEW,
        ProviderCallKind.REPLACEMENT_REVIEW,
    ]
    assert [attempt.reservation.ordinal for attempt in attempts] == [1, 2, 3]
    retry_reservation = attempts[-1].reservation
    assert retry_reservation.retry_of_attempt_id == attempt_id
    assert retry_reservation.uses_supplemental_retry_capacity is bool(
        indeterminate_calls
    )
    reopened = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert reopened.accepted_jobs == 1
    assert cloud.calls == 3


@pytest.mark.parametrize(
    ("transmission", "accounting"),
    [
        (TransmissionDisposition.NOT_TRANSMITTED, AttemptAccounting(1, 1, 0, 1)),
        (TransmissionDisposition.TRANSMITTED, AttemptAccounting.zero()),
    ],
)
def test_provider_failure_rejects_contradictory_disposition_accounting(
    transmission: TransmissionDisposition,
    accounting: AttemptAccounting,
) -> None:
    with pytest.raises(ValueError, match=r"transmission.*accounting"):
        WorkflowProviderError(
            WorkflowFailure.PROVIDER_UNAVAILABLE,
            transmission,
            accounting,
        )


def test_durable_completion_rejects_not_transmitted_with_one_call() -> None:
    with pytest.raises(ValueError, match=r"transmission.*accounting"):
        AttemptCompletion(
            stage=AttemptStage.NOT_TRANSMITTED,
            transmission=TransmissionDisposition.NOT_TRANSMITTED,
            accounting=AttemptAccounting(1, 1, 0, 1),
            response_identity=None,
            failure=WorkflowFailure.NOT_TRANSMITTED,
            sanitized_reason="Provider did not transmit.",
        )


def test_mutated_not_transmitted_call_accounting_fails_indeterminate_without_retry() -> None:
    policy = _policy()
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    malformed = WorkflowProviderError(
        WorkflowFailure.PROVIDER_UNAVAILABLE,
        TransmissionDisposition.NOT_TRANSMITTED,
        AttemptAccounting.zero(),
    )
    malformed.accounting = AttemptAccounting(1, 1, 0, 1)
    factory = RecordingFactory(policy.cloud, [malformed, _reply(policy.cloud)])
    service = _service(repository, requests, factory)
    preview = _prepare_approve(service, plan, policy, _ceilings(2))

    first = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert first.indeterminate_jobs == 1
    assert first.resumable_jobs == 0
    unchanged = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert unchanged.indeterminate_jobs == 1
    assert factory.calls == 1


def test_flagged_cloud_result_receives_exactly_one_replacement_review() -> None:
    policy = _policy()
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    factory = RecordingFactory(
        policy.cloud,
        [_reply(policy.cloud, b"flagged"), _reply(policy.cloud, b"review-ok")],
    )
    service = _service(repository, requests, factory)
    preview = _prepare_approve(service, plan, policy, _ceilings(2, reviews=1))

    status = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )

    assert status.accepted_jobs == 1
    assert factory.calls == 2
    attempts = repository.runs["run-public"].jobs["job-0"].attempts
    assert [item.reservation.call_kind for item in attempts] == [
        ProviderCallKind.MAPPING,
        ProviderCallKind.REPLACEMENT_REVIEW,
    ]


def test_unflagged_cloud_result_never_constructs_a_review_call() -> None:
    policy = _policy()
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    factory = RecordingFactory(policy.cloud, [_reply(policy.cloud, b"ordinary")])
    service = _service(repository, requests, factory)
    preview = _prepare_approve(service, plan, policy, _ceilings(2, reviews=1))

    status = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert status.accepted_jobs == 1
    assert factory.calls == factory.constructions == 1


def test_still_flagged_replacement_falls_back_structurally_without_recursive_review() -> None:
    policy = _policy()
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    factory = RecordingFactory(
        policy.cloud,
        [_reply(policy.cloud, b"flagged"), _reply(policy.cloud, b"flagged")],
    )
    service = _service(repository, requests, factory)
    preview = _prepare_approve(service, plan, policy, _ceilings(3, reviews=1))

    status = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert status.structural_fallback_jobs == 1
    assert factory.calls == 2


def test_flagged_result_without_approved_review_ceiling_falls_back_structurally() -> None:
    policy = _policy()
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    factory = RecordingFactory(policy.cloud, [_reply(policy.cloud, b"flagged")])
    service = _service(repository, requests, factory)
    preview = _prepare_approve(service, plan, policy, _ceilings(1))

    status = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert status.structural_fallback_jobs == 1
    assert status.resumable_jobs == 0
    assert factory.calls == 1


def test_crash_after_flagged_validation_resumes_review_without_repeating_mapping() -> None:
    policy = _policy()
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    factory = RecordingFactory(
        policy.cloud,
        [_reply(policy.cloud, b"flagged"), _reply(policy.cloud, b"review-ok")],
    )
    service = _service(
        repository,
        requests,
        factory,
        checkpoint=FaultOnce("after_validation"),
    )
    preview = _prepare_approve(service, plan, policy, _ceilings(2, reviews=1))

    with pytest.raises(SimulatedProcessCrash):
        service.execute(
            "run-public",
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
    assert factory.calls == 1
    recovery = service.recover("run-public")
    assert recovery.policy_resume_jobs == ("job-0",)

    final = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert final.accepted_jobs == 1
    assert factory.calls == 2
    attempts = repository.runs["run-public"].jobs["job-0"].attempts
    assert [attempt.reservation.call_kind for attempt in attempts] == [
        ProviderCallKind.MAPPING,
        ProviderCallKind.REPLACEMENT_REVIEW,
    ]


def test_preview_approved_refusal_fallback_calls_exactly_one_loopback_provider() -> None:
    policy = _policy(fallback=True)
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    cloud = RecordingFactory(
        policy.cloud,
        [
            _provider_failure(
                WorkflowFailure.CONTENT_REFUSAL,
                TransmissionDisposition.TRANSMITTED,
                calls=1,
            )
        ],
    )
    assert policy.loopback is not None
    local = RecordingFactory(policy.loopback, [_reply(policy.loopback, b"local-ok")])
    service = _service(repository, requests, cloud, local=local)
    preview = _prepare_approve(service, plan, policy, _ceilings(1, fallbacks=1))

    status = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )

    assert status.accepted_jobs == 1
    assert cloud.calls == 1
    assert local.calls == 1
    assert status.accounting.calls == 2


def test_invalid_local_fallback_uses_structural_result_and_never_returns_to_cloud() -> None:
    policy = _policy(fallback=True)
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    cloud = RecordingFactory(
        policy.cloud,
        [
            _provider_failure(
                WorkflowFailure.CONTENT_REFUSAL,
                TransmissionDisposition.TRANSMITTED,
                calls=1,
            ),
            AssertionError("cloud must not be called again"),
        ],
    )
    assert policy.loopback is not None
    local = RecordingFactory(policy.loopback, [_reply(policy.loopback, b"invalid")])
    service = _service(repository, requests, cloud, local=local)
    preview = _prepare_approve(service, plan, policy, _ceilings(1, fallbacks=1))

    status = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )

    assert status.structural_fallback_jobs == 1
    assert cloud.calls == 1
    assert local.calls == 1


def test_unpreviewed_refusal_has_structural_fallback_and_constructs_no_local_provider() -> None:
    policy = _policy()
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    cloud = RecordingFactory(
        policy.cloud,
        [
            _provider_failure(
                WorkflowFailure.CONTENT_REFUSAL,
                TransmissionDisposition.TRANSMITTED,
                calls=1,
            )
        ],
    )
    local = ConstructionTrap()
    service = _service(repository, requests, cloud, local=local)
    preview = _prepare_approve(service, plan, policy, _ceilings(1))

    status = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert status.structural_fallback_jobs == 1
    assert local.constructions == 0


def test_nonrefusal_cloud_failure_never_constructs_disclosed_loopback_provider() -> None:
    policy = _policy(fallback=True)
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    cloud = RecordingFactory(
        policy.cloud,
        [
            _provider_failure(
                WorkflowFailure.PROVIDER_UNAVAILABLE,
                TransmissionDisposition.TRANSMITTED,
                calls=1,
            )
        ],
    )
    local = ConstructionTrap()
    service = _service(repository, requests, cloud, local=local)
    preview = _prepare_approve(service, plan, policy, _ceilings(1, fallbacks=1))

    status = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert status.structural_fallback_jobs == 1
    assert local.constructions == 0


def test_provider_identity_mismatch_is_structural_and_has_no_retry() -> None:
    policy = _policy()
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    mismatch = replace(_reply(policy.cloud), resolved_model="substitute-model")
    factory = RecordingFactory(policy.cloud, [mismatch])
    service = _service(repository, requests, factory)
    preview = _prepare_approve(service, plan, policy, _ceilings(1))

    status = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert status.structural_fallback_jobs == 1
    assert factory.calls == 1
    unchanged = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert unchanged.structural_fallback_jobs == 1
    assert factory.calls == 1


def test_cached_prose_is_revalidated_against_current_job_authority_without_provider() -> None:
    policy = _policy()
    plan, requests = _plan(1, policy, authority="authority-rejected")
    repository = MemoryWorkflowRepository()
    repository.cache[plan.jobs[0].cache_identity] = ValidatedWorkflowResult(
        hashlib.sha256(b"normalized:cached").hexdigest(), b"normalized:cached"
    )
    trap = ConstructionTrap()
    service = _service(
        repository,
        requests,
        trap,
        validator=SyntheticValidator(rejected_authority="authority-rejected"),
    )
    preview = _prepare_approve(service, plan, policy, _ceilings(1))

    status = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )

    assert status.structural_fallback_jobs == 1
    assert trap.constructions == 0


def test_second_approved_run_reuses_mode_specific_loopback_cache_with_zero_calls() -> None:
    policy = _policy(fallback=True)
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    cloud = RecordingFactory(
        policy.cloud,
        [
            _provider_failure(
                WorkflowFailure.CONTENT_REFUSAL,
                TransmissionDisposition.TRANSMITTED,
                calls=1,
            )
        ],
    )
    assert policy.loopback is not None
    local = RecordingFactory(policy.loopback, [_reply(policy.loopback, b"local-ok")])
    first_service = _service(repository, requests, cloud, local=local)
    first_preview = _prepare_approve(
        first_service,
        plan,
        policy,
        _ceilings(1, fallbacks=1),
        run_id="run-first",
    )
    first = first_service.execute(
        "run-first",
        preview_identity=first_preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert first.accepted_jobs == 1
    assert cloud.calls == local.calls == 1

    cloud_trap = ConstructionTrap()
    local_trap = ConstructionTrap()
    second_service = _service(
        repository,
        requests,
        cloud_trap,
        local=local_trap,
    )
    second_preview = _prepare_approve(
        second_service,
        plan,
        policy,
        _ceilings(1, fallbacks=1),
        run_id="run-second",
    )
    assert second_preview.cache_hit_job_ids == ()
    assert second_preview.loopback_cache_hit_job_ids == ("job-0",)
    second = second_service.execute(
        "run-second",
        preview_identity=second_preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert second.accepted_jobs == 1
    assert second.accounting == WorkflowAccounting.zero()
    assert cloud_trap.constructions == local_trap.constructions == 0


def test_external_loopback_cache_mutation_invalidates_preview_before_construction() -> None:
    policy = _policy(fallback=True)
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    cloud_trap = ConstructionTrap()
    local_trap = ConstructionTrap()
    service = _service(repository, requests, cloud_trap, local=local_trap)
    preview = _prepare_approve(service, plan, policy, _ceilings(1, fallbacks=1))
    local_identity = policy.input_identity(
        plan.jobs[0].serialized_request_identity,
        mode=ProviderMode.LOOPBACK,
    ).cache_identity
    repository.cache[local_identity] = ValidatedWorkflowResult(
        hashlib.sha256(b"normalized:external-local").hexdigest(),
        b"normalized:external-local",
    )

    with pytest.raises(WorkflowApprovalError, match="cache-hit work changed"):
        service.execute(
            "run-public",
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
    assert cloud_trap.constructions == local_trap.constructions == 0


@pytest.mark.parametrize(
    ("checkpoint", "expected_recovery", "calls_before", "requires_retry"),
    [
        ("before_reservation", "pending", 0, False),
        ("after_reservation", "not_transmitted", 0, False),
        ("after_mark_submitting", "indeterminate", 0, True),
        ("after_transport_return", "indeterminate", 1, True),
        ("after_validation", "published", 1, False),
        ("after_finalization", "published", 1, False),
        ("after_publication", "already_published", 1, False),
    ],
)
def test_crash_fault_matrix_preserves_exact_resume_semantics(
    checkpoint: str,
    expected_recovery: str,
    calls_before: int,
    requires_retry: bool,
) -> None:
    policy = _policy()
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    factory = RecordingFactory(policy.cloud, [_reply(policy.cloud), _reply(policy.cloud)])
    fault = FaultOnce(checkpoint)
    service = _service(repository, requests, factory, checkpoint=fault)
    preview = _prepare_approve(service, plan, policy, _ceilings(2))

    with pytest.raises(SimulatedProcessCrash):
        service.execute(
            "run-public",
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
    assert factory.calls == calls_before
    recovery = service.recover("run-public")

    if expected_recovery == "pending":
        assert recovery == RecoveryReport((), (), (), ())
    elif expected_recovery == "not_transmitted":
        assert recovery.not_transmitted_jobs == ("job-0",)
    elif expected_recovery == "indeterminate":
        assert recovery.indeterminate_jobs == ("job-0",)
    elif expected_recovery == "published":
        assert recovery.published_jobs == ("job-0",)
    else:
        assert service.status("run-public").accepted_jobs == 1

    if requires_retry:
        unchanged = service.execute(
            "run-public",
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
        assert unchanged.indeterminate_jobs == 1
        assert factory.calls == calls_before
        service.approve_indeterminate_retry(
            "run-public",
            preview_identity=preview.identity,
            job_id="job-0",
            indeterminate_attempt_id=repository.last_attempt_id("run-public", "job-0"),
        )
    if expected_recovery not in {"published", "already_published"}:
        final = service.execute(
            "run-public",
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
        assert final.accepted_jobs == 1

    expected_calls = (
        calls_before
        if expected_recovery in {"published", "already_published"}
        else calls_before + 1
    )
    assert factory.calls == expected_calls
    ordinals = repository.attempt_ordinals("run-public", "job-0")
    assert ordinals == list(range(1, len(ordinals) + 1))


def test_mapping_call_ceiling_is_finite_and_denies_unapproved_work_without_calls() -> None:
    policy = _policy()
    plan, requests = _plan(4, policy)
    repository = MemoryWorkflowRepository()
    factory = RecordingFactory(
        policy.cloud,
        [_reply(policy.cloud, b"one"), _reply(policy.cloud, b"two")],
    )
    service = _service(repository, requests, factory)
    ceilings = replace(_ceilings(4), mapping_calls=2)
    # The preview itself rejects a ceiling that cannot cover declared pending work.
    with pytest.raises(ValueError, match="cannot cover"):
        service.prepare("run-public", plan, policy, ceilings)
    assert factory.constructions == factory.calls == 0


def test_accounting_records_calls_tokens_and_time_exactly() -> None:
    policy = _policy()
    plan, requests = _plan(2, policy)
    repository = MemoryWorkflowRepository()
    factory = RecordingFactory(
        policy.cloud,
        [
            _reply(policy.cloud, b"one", input_tokens=11, output_tokens=3, elapsed_ms=17),
            _reply(policy.cloud, b"two", input_tokens=13, output_tokens=5, elapsed_ms=19),
        ],
    )
    service = _service(repository, requests, factory)
    preview = _prepare_approve(service, plan, policy, _ceilings(2))

    status = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert status.accounting == WorkflowAccounting(2, 24, 8, 36)


def test_raw_prompt_source_absolute_path_and_provider_details_never_reach_durable_records() -> None:
    policy = _policy()
    raw = b'{"raw_text":"SECRET STORY C:\\\\Users\\\\private\\\\story.rpy"}'
    plan, requests = _plan(1, policy, request_prefix=raw)
    repository = MemoryWorkflowRepository()
    factory = RecordingFactory(policy.cloud, [_reply(policy.cloud, b"absolute-path")])
    service = _service(repository, requests, factory)
    preview = _prepare_approve(service, plan, policy, _ceilings(1))

    status = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )

    assert status.structural_fallback_jobs == 1
    durable = repr(repository.durable)
    for forbidden in ("SECRET STORY", "SECRET provider", "SECRET raw source", "C:\\\\Users"):
        assert forbidden not in durable
    assert "The mapper result was invalid; structural coverage remains." in durable


def test_echoed_request_packet_is_rejected_before_sanitized_persistence() -> None:
    policy = _policy()
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    factory = EchoFactory(policy.cloud)
    service = _service(repository, requests, factory)
    preview = _prepare_approve(service, plan, policy, _ceilings(1))

    status = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert status.structural_fallback_jobs == 1
    assert requests["request-0"] not in repr(repository.durable).encode()


def test_nested_platform_neutral_absolute_path_is_rejected_recursively() -> None:
    policy = _policy()
    plan, requests = _plan(1, policy)
    repository = MemoryWorkflowRepository()
    factory = RecordingFactory(policy.cloud, [_reply(policy.cloud, b"nested-posix-path")])
    service = _service(repository, requests, factory)
    preview = _prepare_approve(service, plan, policy, _ceilings(1))

    status = service.execute(
        "run-public",
        preview_identity=preview.identity,
        authority_identity=plan.authority_identity,
    )
    assert status.structural_fallback_jobs == 1
    assert "/opt/private/story.rpy" not in repr(repository.durable)


def test_workflow_modules_do_not_import_track_a_storage_project_or_historical_schedulers() -> None:
    root = Path(__file__).parents[1]
    files = (
        root / "src/renpy_story_mapper/story_map_v2/workflow_contracts.py",
        root / "src/renpy_story_mapper/story_map_v2/workflow_protocols.py",
        root / "src/renpy_story_mapper/story_map_v2/workflow_service.py",
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in files)
    for forbidden in (
        "story_map_v2.planner",
        "story_map_v2.source_adapter",
        "renpy_story_mapper.storage",
        "renpy_story_mapper.project",
        "renpy_story_mapper.organization",
        "renpy_story_mapper.narrative",
        "m13_",
    ):
        assert forbidden not in source
