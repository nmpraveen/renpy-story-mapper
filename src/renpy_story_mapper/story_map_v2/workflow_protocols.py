"""Narrow persistence, provider, materialization, and validation seams for Phase 04."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from renpy_story_mapper.story_map_v2.workflow_contracts import (
    AttemptAccounting,
    AttemptCompletion,
    AttemptReservation,
    CacheIdentity,
    JobClaim,
    JobResolution,
    JobRetryApproval,
    ProviderCallKind,
    ProviderCallResult,
    ProviderInputIdentity,
    RecoveryReport,
    SerializedRequestIdentity,
    TransmissionDisposition,
    ValidatedWorkflowResult,
    WorkflowApproval,
    WorkflowFailure,
    WorkflowJobDescriptor,
    WorkflowPreview,
    WorkflowResourceCeilings,
    WorkflowStatus,
    validate_transmission_accounting,
)


class WorkflowProviderError(RuntimeError):
    """A provider-neutral failure with explicit transmission certainty and finite accounting."""

    def __init__(
        self,
        failure: WorkflowFailure,
        transmission: TransmissionDisposition,
        accounting: AttemptAccounting,
    ) -> None:
        if type(transmission) is not TransmissionDisposition:
            raise TypeError("provider failure requires an explicit transmission disposition")
        if type(accounting) is not AttemptAccounting:
            raise TypeError("provider failure requires finite attempt accounting")
        validate_transmission_accounting(transmission, accounting)
        super().__init__(failure.value)
        self.failure = failure
        self.transmission = transmission
        self.accounting = accounting


class WorkflowProvider(Protocol):
    def submit(self, request: bytes) -> ProviderCallResult: ...

    def cancel(self) -> None: ...


ProviderFactory = Callable[[], WorkflowProvider]


class RequestMaterializer(Protocol):
    def materialize(self, identity: SerializedRequestIdentity) -> bytes: ...


class WorkflowResponseValidator(Protocol):
    """Validate authority and return prose-only normalized bytes safe for persistence.

    Implementations must reject or remove source packets, raw prompts/responses, absolute paths,
    provider diagnostics, credentials, and every provider-supplied mechanics/topology field.
    """

    def validate(
        self,
        job: WorkflowJobDescriptor,
        payload: bytes,
        *,
        cached: bool,
    ) -> ValidatedWorkflowResult: ...


class WorkflowRepository(Protocol):
    """Transactional seam implemented by Track B1 after coordinator contract binding.

    The concrete implementation owns CAS/lease atomicity.  No Track A planner object, storage
    connection, project object, provider object, or source packet may cross this boundary.
    """

    def store_prepared(self, preview: WorkflowPreview) -> None: ...

    def load_preview(self, run_id: str) -> WorkflowPreview: ...

    def store_approval(self, run_id: str, approval: WorkflowApproval) -> None: ...

    def load_approval(self, run_id: str) -> WorkflowApproval | None: ...

    def load_cache(self, cache_identity: CacheIdentity) -> ValidatedWorkflowResult | None: ...

    def load_published_result(
        self,
        run_id: str,
        job_id: str,
    ) -> ValidatedWorkflowResult | None: ...

    def begin_execution(
        self,
        run_id: str,
        preview_identity: str,
        authority_identity: str,
    ) -> str: ...

    def claim_next_job(
        self,
        run_id: str,
        execution_id: str,
        worker_id: str,
        *,
        submission_slots: int,
    ) -> JobClaim | None: ...

    def reserve_attempt(
        self,
        claim: JobClaim,
        call_kind: ProviderCallKind,
        provider_input: ProviderInputIdentity,
        ceilings: WorkflowResourceCeilings,
    ) -> AttemptReservation | None:
        """Atomically enforce ordinary ceilings and consume any exact approved retry."""

        ...

    def mark_submitting(self, claim: JobClaim, reservation: AttemptReservation) -> bool:
        """Atomically mark submitting, or return false when cancellation already won."""

        ...

    def complete_attempt(
        self,
        claim: JobClaim,
        reservation: AttemptReservation,
        completion: AttemptCompletion,
    ) -> None: ...

    def record_validated(
        self,
        claim: JobClaim,
        reservation: AttemptReservation | None,
        result: ValidatedWorkflowResult,
    ) -> None: ...

    def store_cache(
        self,
        cache_identity: CacheIdentity,
        result: ValidatedWorkflowResult,
    ) -> None: ...

    def finalize_job(
        self,
        claim: JobClaim,
        resolution: JobResolution,
        result_identity: str | None,
        failure: WorkflowFailure | None,
        sanitized_reason: str | None,
        resume_call_kind: ProviderCallKind | None,
    ) -> None: ...

    def publish_job(self, claim: JobClaim) -> None: ...

    def release_claim(self, claim: JobClaim) -> None: ...

    def persist_cancellation(self, run_id: str) -> None: ...

    def is_cancelled(self, run_id: str) -> bool: ...

    def recover(self, run_id: str) -> RecoveryReport: ...

    def store_retry_approval(self, run_id: str, approval: JobRetryApproval) -> None:
        """Approve only the latest indeterminate attempt for one matching call-kind resume."""

        ...

    def status(self, run_id: str) -> WorkflowStatus: ...


class WorkflowCheckpoint(Protocol):
    def __call__(self, name: str, job_id: str) -> None: ...
