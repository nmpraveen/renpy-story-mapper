"""Durable B2 workflow adapter over the provider-neutral Story Map V2 repository."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict
from typing import cast

from renpy_story_mapper import storage
from renpy_story_mapper.story_map_v2 import durable_repository as durable
from renpy_story_mapper.story_map_v2.frozen_plans import FrozenPlanBundle
from renpy_story_mapper.story_map_v2.workflow_contracts import (
    AttemptAccounting,
    AttemptCompletion,
    AttemptReservation,
    AuthorityIdentity,
    CacheIdentity,
    DerivedSemanticNodeRole,
    IndeterminateRetryStatus,
    JobClaim,
    JobResolution,
    JobRetryApproval,
    ProviderCallKind,
    ProviderInputIdentity,
    ProviderMode,
    ProviderSettings,
    RecoveryReport,
    SerializedRequestIdentity,
    TransmissionDisposition,
    ValidatedWorkflowResult,
    WorkflowAccounting,
    WorkflowApproval,
    WorkflowCorridorDescriptor,
    WorkflowDerivedSemanticJobDescriptor,
    WorkflowDerivedSemanticPlanDescriptor,
    WorkflowExecutableJobDescriptor,
    WorkflowFailure,
    WorkflowJobDescriptor,
    WorkflowPlanDescriptor,
    WorkflowPolicy,
    WorkflowPreview,
    WorkflowPrivacyScope,
    WorkflowResourceCeilings,
    WorkflowRouteMembership,
    WorkflowStatus,
    canonical_workflow_bytes,
    workflow_digest,
)
from renpy_story_mapper.story_map_v2.workflow_protocols import WorkflowRepository

_PREVIEW_KIND = "story-map-v2-workflow-preview-v1"
_RESULT_KIND = "story-map-v2-normalized-prose-v1"
_STRUCTURAL_KIND = "story-map-v2-structural-fallback-v1"
_DERIVED_JOB_KIND = "story-map-v2-derived-semantic-job-v2"
_FROZEN_PLANS_KIND = "story-map-v2-frozen-plans-v1"


class DurableWorkflowRepositoryAdapter(WorkflowRepository):
    """Translate frozen B2 records into canonical sanitized B1 operations.

    File-backed SQLite repositories use a short-lived connection per operation. This keeps the
    workflow service safe across its six worker threads and makes the global B1 claim transaction
    authoritative across adapters and processes.
    """

    def __init__(
        self,
        repository: durable.StoryMapV2Repository,
        *,
        fault: durable.FaultInjector | None = None,
    ) -> None:
        self._primary = repository
        self._fault = fault
        self._database_path = (
            repository.database_path
            if isinstance(repository, durable.SqliteStoryMapV2Repository)
            else None
        )

    @classmethod
    def from_project(cls, project: object) -> DurableWorkflowRepositoryAdapter:
        """Use the existing narrow ``Project.story_map_v2_repository`` construction seam."""

        factory = getattr(project, "story_map_v2_repository", None)
        if not callable(factory):
            raise TypeError("project does not expose story_map_v2_repository()")
        return cls(cast(durable.StoryMapV2Repository, factory()))

    @contextmanager
    def _repository(self) -> Iterator[durable.StoryMapV2Repository]:
        if self._database_path is None:
            yield self._primary
            return
        connection = storage.connect(self._database_path)
        try:
            yield durable.SqliteStoryMapV2Repository(connection)
        finally:
            connection.close()

    def store_prepared(
        self,
        preview: WorkflowPreview,
        frozen_plans: FrozenPlanBundle | None = None,
    ) -> None:
        stored = _preview_object(preview)
        preview_id = _preview_id(preview.run_id)
        descriptor = durable.PreparedPreviewDescriptor(
            preview_id=preview_id,
            plan_id=_stable_id("plan", preview.plan.plan_id),
            authority_identity=_authority_digest(preview.plan.authority_identity.value),
            preview=stored,
            preview_identity=_object_identity(stored),
        )
        run = durable.FrozenRunDescriptor(
            _run_id(preview.run_id),
            descriptor.plan_id,
            descriptor.authority_identity,
        )
        jobs = tuple(
            _durable_job(preview.run_id, item, ordinal)
            for ordinal, item in enumerate(preview.plan.jobs)
        )
        with self._repository() as repository:
            if frozen_plans is not None:
                semantic_plan = preview.plan.derived_semantic_plan
                if (
                    semantic_plan is not None
                    and semantic_plan.story_chunk_plan_identity
                    != frozen_plans.story_chunk_plan.identity
                ):
                    raise durable.ImmutableRecordConflictError(
                        "frozen chunk plan does not match the semantic plan"
                    )
                frozen = _frozen_plans_object(frozen_plans)
                repository.store_prepared_preview(
                    durable.PreparedPreviewDescriptor(
                        preview_id=_frozen_plans_id(preview.run_id),
                        plan_id=descriptor.plan_id,
                        authority_identity=descriptor.authority_identity,
                        preview=frozen,
                        preview_identity=_object_identity(frozen),
                    )
                )
            repository.store_prepared_preview(descriptor)
            existing = repository.get_run(run.run_id)
            if existing is None:
                repository.create_run(run, jobs)
            elif existing.descriptor != run or tuple(
                item.descriptor for item in repository.list_jobs(run.run_id)[: len(jobs)]
            ) != jobs:
                raise durable.ImmutableRecordConflictError("workflow run identity is immutable")

    def load_frozen_plans(self, run_id: str) -> FrozenPlanBundle | None:
        with self._repository() as repository:
            record = repository.load_prepared_preview(_frozen_plans_id(run_id))
            run = repository.get_run(_run_id(run_id))
        if record is None:
            return None
        if run is None:
            raise storage.ProjectCorruptError("frozen plans have no workflow run")
        if (
            record.descriptor.plan_id != run.descriptor.plan_id
            or record.descriptor.authority_identity
            != run.descriptor.authority_identity
            or _object_identity(record.descriptor.preview)
            != record.descriptor.preview_identity
        ):
            raise storage.ProjectCorruptError("durable frozen-plan binding changed")
        bundle = _decode_frozen_plans(record.descriptor.preview)
        preview = self.load_preview(run_id)
        semantic_plan = preview.plan.derived_semantic_plan
        if (
            semantic_plan is not None
            and semantic_plan.story_chunk_plan_identity
            != bundle.story_chunk_plan.identity
        ):
            raise storage.ProjectCorruptError("durable frozen chunk plan identity changed")
        return bundle

    def load_preview(self, run_id: str) -> WorkflowPreview:
        with self._repository() as repository:
            record = repository.load_prepared_preview(_preview_id(run_id))
        if record is None:
            raise durable.StoryMapV2RepositoryError("unknown workflow run")
        preview = _decode_preview(record.descriptor.preview)
        if preview.run_id != run_id or _object_identity(_preview_object(preview)) != (
            record.descriptor.preview_identity
        ):
            raise storage.ProjectCorruptError("durable workflow preview identity changed")
        return preview

    def store_approval(self, run_id: str, approval: WorkflowApproval) -> None:
        preview = self.load_preview(run_id)
        if approval != WorkflowApproval(
            preview.identity,
            preview.plan.plan_id,
            preview.plan.authority_identity,
        ):
            raise durable.ImmutableRecordConflictError("workflow approval does not match preview")
        stored = asdict(approval)
        with self._repository() as repository:
            repository.store_run_approval(
                durable.RunApprovalDescriptor(
                    approval_id=_stable_id("approval", run_id),
                    run_id=_run_id(run_id),
                    preview_id=_preview_id(run_id),
                    execution_identity=_execution_id(preview),
                    approval=stored,
                    approval_identity=_object_identity(stored),
                )
            )

    def load_approval(self, run_id: str) -> WorkflowApproval | None:
        with self._repository() as repository:
            record = repository.load_run_approval(_run_id(run_id))
        if record is None:
            return None
        value = _mapping(record.descriptor.approval, "workflow approval")
        return WorkflowApproval(
            preview_identity=_str(value, "preview_identity"),
            plan_id=_str(value, "plan_id"),
            authority_identity=AuthorityIdentity(
                _str(_mapping(value.get("authority_identity"), "authority identity"), "value")
            ),
        )

    def load_cache(self, cache_identity: CacheIdentity) -> ValidatedWorkflowResult | None:
        with self._repository() as repository:
            entry = repository.lookup_cache(cache_identity.value)
        return None if entry is None else _decode_result(entry.normalized_result)

    def load_published_result(
        self, run_id: str, job_id: str
    ) -> ValidatedWorkflowResult | None:
        with self._repository() as repository:
            record = repository.load_published_result(
                _run_id(run_id), _job_id(run_id, job_id)
            )
        if record is None:
            return None
        value = _mapping(record.result, "published workflow result")
        if value.get("kind") != _RESULT_KIND:
            return None
        return _decode_result(value)

    def register_derived_job(
        self,
        run_id: str,
        preview_identity: str,
        job: WorkflowDerivedSemanticJobDescriptor,
    ) -> None:
        preview = self.load_preview(run_id)
        approval = self.load_approval(run_id)
        semantic_plan = preview.plan.derived_semantic_plan
        if (
            preview.identity != preview_identity
            or approval is None
            or approval.preview_identity != preview_identity
            or semantic_plan is None
            or job.plan_id != preview.plan.plan_id
            or job.authority_identity != preview.plan.authority_identity
            or job.semantic_plan_identity != semantic_plan.semantic_plan_identity
            or job.story_chunk_plan_identity != semantic_plan.story_chunk_plan_identity
        ):
            raise durable.StoryMapV2RepositoryError(
                "derived job does not match the approved semantic plan"
            )
        _validate_derived_job_membership(job, semantic_plan)
        stored = _derived_job_object(job)
        with self._repository() as repository:
            run = repository.get_run(_run_id(run_id))
            if run is None or run.cancel_requested:
                raise durable.StoryMapV2RepositoryError(
                    "cancelled or missing workflow cannot register descendants"
                )
            for child_id, prose_hash in zip(
                job.child_ids, job.child_prose_hashes, strict=True
            ):
                child = repository.load_published_result(
                    run.descriptor.run_id, _job_id(run_id, child_id)
                )
                if child is None:
                    raise durable.StoryMapV2RepositoryError(
                        "derived job dependencies are not all published"
                    )
                child_value = _mapping(child.result, "derived child result")
                if child_value.get("kind") != _RESULT_KIND or _str(
                    child_value, "result_identity"
                ) != prose_hash:
                    raise durable.StoryMapV2RepositoryError(
                        "derived job child prose identity changed"
                    )
            repository.store_prepared_preview(
                durable.PreparedPreviewDescriptor(
                    preview_id=_derived_job_preview_id(_job_id(run_id, job.job_id)),
                    plan_id=run.descriptor.plan_id,
                    authority_identity=run.descriptor.authority_identity,
                    preview=stored,
                    preview_identity=_object_identity(stored),
                )
            )
            existing_jobs = repository.list_jobs(run.descriptor.run_id)
            existing = repository.get_job(_job_id(run_id, job.job_id))
            ordinal = existing.descriptor.ordinal if existing is not None else len(existing_jobs)
            repository.register_jobs(
                run.descriptor.run_id,
                (_durable_job(run_id, job, ordinal),),
            )

    def load_job_descriptor(
        self,
        run_id: str,
        job_id: str,
    ) -> WorkflowExecutableJobDescriptor | None:
        preview = self.load_preview(run_id)
        mapping = next((item for item in preview.plan.jobs if item.job_id == job_id), None)
        if mapping is not None:
            return mapping
        with self._repository() as repository:
            record = repository.get_job(_job_id(run_id, job_id))
            if record is None:
                return None
            return _load_derived_job(repository, record.descriptor.job_id)

    def begin_execution(
        self, run_id: str, preview_identity: str, authority_identity: str
    ) -> str:
        preview = self.load_preview(run_id)
        approval = self.load_approval(run_id)
        if (
            preview.identity != preview_identity
            or preview.plan.authority_identity.value != authority_identity
            or approval is None
            or approval.preview_identity != preview_identity
        ):
            raise durable.StoryMapV2RepositoryError("execution identity is not approved")
        with self._repository() as repository:
            repository.activate_resumable_jobs(_run_id(run_id))
        return _execution_id(preview)

    def claim_next_job(
        self,
        run_id: str,
        execution_id: str,
        worker_id: str,
        *,
        submission_slots: int,
    ) -> JobClaim | None:
        preview = self.load_preview(run_id)
        if execution_id != _execution_id(preview):
            raise durable.LeaseConflictError("execution identity changed")
        if submission_slots != durable.GLOBAL_SUBMISSION_LIMIT:
            raise ValueError("workflow requires exactly six global submission slots")
        with self._repository() as repository:
            claim = repository.claim_next_job(
                _stable_id("worker", worker_id),
                run_id=_run_id(run_id),
                materialize_cache_hits=False,
            )
            if claim is None:
                return None
            attempts = repository.list_attempts(claim.descriptor.job_id)
            job = _job_for_record(repository, preview, claim.descriptor)
        resume = _resume_kind(claim, attempts)
        return JobClaim(
            run_id,
            execution_id,
            claim.lease_token,
            worker_id,
            job,
            resume,
        )

    def reserve_attempt(
        self,
        claim: JobClaim,
        call_kind: ProviderCallKind,
        provider_input: ProviderInputIdentity,
        ceilings: WorkflowResourceCeilings,
    ) -> AttemptReservation | None:
        preview = self.load_preview(claim.run_id)
        if isinstance(claim.job, WorkflowDerivedSemanticJobDescriptor):
            input_matches = (
                call_kind is claim.job.call_kind
                and provider_input == claim.job.provider_input_identity
            )
        else:
            input_matches = provider_input == preview.policy.input_identity(
                claim.job.serialized_request_identity,
                mode=provider_input.mode,
            )
        if ceilings != preview.ceilings or not input_matches:
            raise durable.StoryMapV2RepositoryError("attempt input changed after approval")
        with self._repository() as repository:
            durable_claim = _load_claim(repository, claim)
            metadata = durable.AttemptReservationMetadata(
                call_kind.value,
                workflow_digest(asdict(provider_input)),
                workflow_digest(asdict(ceilings)),
            )
            try:
                reserved = repository.reserve_attempt(
                    durable_claim,
                    metadata,
                    limits=durable.AttemptReservationLimits(
                        mapping_calls=ceilings.mapping_calls,
                        review_calls=ceilings.review_calls,
                        fallback_calls=ceilings.fallback_calls,
                        input_tokens=ceilings.input_tokens,
                        output_tokens=ceilings.output_tokens,
                        elapsed_ms=ceilings.elapsed_ms,
                        indeterminate_retry_calls=ceilings.indeterminate_retry_calls,
                        section_synthesis_calls=ceilings.section_synthesis_calls,
                        route_reduction_calls=ceilings.route_reduction_calls,
                        route_summary_calls=ceilings.route_summary_calls,
                        whole_game_reduction_calls=ceilings.whole_game_reduction_calls,
                        final_overview_calls=ceilings.final_overview_calls,
                        rollup_synthesis_calls=ceilings.rollup_synthesis_calls,
                    ),
                    fault=self._fault,
                )
            except durable.StoryMapV2RepositoryError as exc:
                if "ceiling" in str(exc) or "capacity" in str(exc):
                    return None
                raise
        return AttemptReservation(
            reserved.attempt_id,
            reserved.ordinal,
            call_kind,
            provider_input,
            reserved.retry_of_attempt_id,
            reserved.uses_supplemental_retry_capacity,
        )

    def mark_submitting(self, claim: JobClaim, reservation: AttemptReservation) -> bool:
        with self._repository() as repository:
            durable_claim = _load_claim(repository, claim)
            attempt = _load_attempt(repository, durable_claim, reservation)
            try:
                repository.mark_transmitting(durable_claim, attempt)
            except durable.LeaseConflictError:
                run = repository.get_run(_run_id(claim.run_id))
                if run is not None and run.cancel_requested:
                    return False
                raise
        return True

    def complete_attempt(
        self,
        claim: JobClaim,
        reservation: AttemptReservation,
        completion: AttemptCompletion,
    ) -> None:
        disposition = {
            TransmissionDisposition.NOT_TRANSMITTED: (
                durable.TransmissionDisposition.DEFINITELY_NOT_TRANSMITTED
            ),
            TransmissionDisposition.TRANSMITTED: durable.TransmissionDisposition.TRANSMITTED,
            TransmissionDisposition.INDETERMINATE: durable.TransmissionDisposition.INDETERMINATE,
        }[completion.transmission]
        response_identity = completion.response_identity
        if (
            completion.transmission is TransmissionDisposition.TRANSMITTED
            and response_identity is None
        ):
            response_identity = workflow_digest(
                {
                    "attempt_id": reservation.attempt_id,
                    "failure": None if completion.failure is None else completion.failure.value,
                }
            )
        with self._repository() as repository:
            durable_claim = _load_claim(repository, claim)
            attempt = _load_attempt(repository, durable_claim, reservation)
            repository.complete_attempt(
                durable_claim,
                attempt,
                disposition=disposition,
                accounting=_durable_accounting(completion.accounting),
                response_identity=response_identity,
                failure_kind=(
                    None if completion.failure is None else completion.failure.value
                ),
                sanitized_failure=completion.sanitized_reason,
                defer_resumable=(
                    completion.transmission
                    is TransmissionDisposition.NOT_TRANSMITTED
                ),
                fault=self._fault,
            )
            if (
                completion.failure is WorkflowFailure.CONTENT_REFUSAL
                and completion.transmission is TransmissionDisposition.TRANSMITTED
                and reservation.call_kind is ProviderCallKind.MAPPING
            ):
                assert response_identity is not None
                repository.record_continuation(
                    durable_claim.descriptor.job_id,
                    durable.ContinuationKind.REFUSAL_FALLBACK,
                    prior_attempt_id=reservation.attempt_id,
                    prior_result_identity=response_identity,
                )

    def record_validated(
        self,
        claim: JobClaim,
        reservation: AttemptReservation | None,
        result: ValidatedWorkflowResult,
        cache_identity: CacheIdentity,
    ) -> None:
        stored = _result_object(result)
        with self._repository() as repository:
            durable_claim = _load_claim(repository, claim)
            repository.record_validated(
                durable_claim.descriptor.job_id,
                None if reservation is None else reservation.attempt_id,
                stored,
                cache_identity=cache_identity.value,
                fault=self._fault,
            )
            if (
                result.flagged_for_review
                and reservation is not None
                and reservation.call_kind is ProviderCallKind.MAPPING
            ):
                repository.record_continuation(
                    durable_claim.descriptor.job_id,
                    durable.ContinuationKind.REPLACEMENT_REVIEW,
                    prior_attempt_id=reservation.attempt_id,
                    prior_result_identity=_object_identity(stored),
                )
            elif (
                reservation is not None
                and reservation.call_kind
                in {
                    ProviderCallKind.REPLACEMENT_REVIEW,
                    ProviderCallKind.REFUSAL_FALLBACK,
                }
            ):
                repository.record_continuation(
                    durable_claim.descriptor.job_id,
                    durable.ContinuationKind.COMPLETE,
                    prior_attempt_id=reservation.attempt_id,
                    prior_result_identity=_object_identity(stored),
                )

    def store_cache(
        self,
        claim: JobClaim,
        cache_identity: CacheIdentity,
        result: ValidatedWorkflowResult,
    ) -> None:
        stored = _result_object(result)
        job_id = _job_id(claim.run_id, claim.job.job_id)
        with self._repository() as repository:
            job = repository.get_job(job_id)
            expected_descriptor = (
                None
                if job is None
                else _durable_job(claim.run_id, claim.job, job.descriptor.ordinal)
            )
            if (
                job is None
                or job.descriptor != expected_descriptor
                or job.status is not durable.JobStatus.VALIDATED
                or job.normalized_result_identity != _object_identity(stored)
                or job.validated_cache_identity != cache_identity.value
            ):
                raise durable.StoryMapV2RepositoryError(
                    "validated cache write no longer matches its durable job"
                )
            repository.store_cache(
                job_id, cache_identity=cache_identity.value
            )

    def finalize_job(
        self,
        claim: JobClaim,
        resolution: JobResolution,
        result_identity: str | None,
        failure: WorkflowFailure | None,
        sanitized_reason: str | None,
        resume_call_kind: ProviderCallKind | None,
    ) -> None:
        del failure, sanitized_reason, resume_call_kind
        with self._repository() as repository:
            durable_claim = _load_claim_or_job(repository, claim)
            job_id = durable_claim.descriptor.job_id
            if resolution is JobResolution.RESUMABLE:
                job = repository.get_job(job_id)
                if (
                    job is not None
                    and job.status is durable.JobStatus.FINALIZED
                    and job.resolution is durable.JobResolution.RESUMABLE
                ):
                    return
                if job is None or job.status is not durable.JobStatus.PENDING:
                    raise durable.StoryMapV2RepositoryError("job is not durably resumable")
                repository.defer_resumable_job(job_id)
                return
            mapped = {
                JobResolution.ACCEPTED: durable.JobResolution.ACCEPTED,
                JobResolution.STRUCTURAL_FALLBACK: durable.JobResolution.STRUCTURAL,
                JobResolution.INDETERMINATE: durable.JobResolution.INDETERMINATE,
                JobResolution.CANCELLED: durable.JobResolution.CANCELLED,
            }[resolution]
            if resolution is JobResolution.ACCEPTED:
                job = repository.get_job(job_id)
                if job is None or result_identity is None:
                    raise durable.StoryMapV2RepositoryError("accepted result identity is missing")
            repository.finalize_job(job_id, mapped, fault=self._fault)

    def publish_job(self, claim: JobClaim) -> None:
        with self._repository() as repository:
            job = repository.get_job(_job_id(claim.run_id, claim.job.job_id))
            if job is None or job.resolution is None:
                raise durable.StoryMapV2RepositoryError("job is not finalized")
            if job.resolution is durable.JobResolution.ACCEPTED:
                if job.normalized_result_identity is None:
                    raise storage.ProjectCorruptError("accepted job has no durable result")
                if job.validated_cache_identity is None:
                    raise storage.ProjectCorruptError(
                        "accepted job cache identity is missing"
                    )
                entry = repository.lookup_cache(job.validated_cache_identity)
                if entry is None:
                    raise storage.ProjectCorruptError("accepted job cache is missing")
                result: object = entry.normalized_result
            else:
                result = {
                    "kind": _STRUCTURAL_KIND,
                    "job_identity": workflow_digest(
                        {"run_id": claim.run_id, "job_id": claim.job.job_id}
                    ),
                }
            repository.publish_job(job.descriptor.job_id, result, fault=self._fault)

    def release_claim(self, claim: JobClaim) -> None:
        with self._repository() as repository:
            durable_claim = _load_claim_or_job(repository, claim)
            repository.release_claim(durable_claim)

    def persist_cancellation(self, run_id: str) -> None:
        with self._repository() as repository:
            repository.cancel_run(_run_id(run_id))

    def is_cancelled(self, run_id: str) -> bool:
        with self._repository() as repository:
            run = repository.get_run(_run_id(run_id))
        if run is None:
            raise durable.StoryMapV2RepositoryError("unknown workflow run")
        return run.cancel_requested

    def recover(self, run_id: str) -> RecoveryReport:
        # Expire only this run's leases through the B1 recovery transaction, then finish durable
        # validated/finalized checkpoints without constructing or calling a provider.
        with self._repository() as repository:
            repository.recover_run(_run_id(run_id))
            jobs = repository.list_jobs(_run_id(run_id))
            not_transmitted: list[str] = []
            indeterminate: list[str] = []
            finalized: list[str] = []
            published: list[str] = []
            policy_resume: list[str] = []
            preview = self.load_preview(run_id)
            for job in jobs:
                public_id = _job_for_record(repository, preview, job.descriptor).job_id
                attempts = repository.list_attempts(job.descriptor.job_id)
                if job.status is durable.JobStatus.PENDING and attempts:
                    if attempts[-1].reservation.transmission_disposition is (
                        durable.TransmissionDisposition.DEFINITELY_NOT_TRANSMITTED
                    ):
                        not_transmitted.append(public_id)
                        repository.defer_resumable_job(job.descriptor.job_id)
                elif job.status is durable.JobStatus.INDETERMINATE:
                    indeterminate.append(public_id)
                elif job.status in {durable.JobStatus.RETURNED, durable.JobStatus.VALIDATED} and (
                    job.continuation_kind
                    in {
                        durable.ContinuationKind.REPLACEMENT_REVIEW,
                        durable.ContinuationKind.REFUSAL_FALLBACK,
                    }
                ):
                    policy_resume.append(public_id)
                elif job.status is durable.JobStatus.VALIDATED:
                    repository.store_cache(job.descriptor.job_id)
                    repository.finalize_job(job.descriptor.job_id, durable.JobResolution.ACCEPTED)
                    refreshed = repository.get_job(job.descriptor.job_id)
                    assert refreshed is not None
                    assert refreshed.normalized_result_identity is not None
                    assert refreshed.validated_cache_identity is not None
                    entry = repository.lookup_cache(refreshed.validated_cache_identity)
                    assert entry is not None
                    repository.publish_job(job.descriptor.job_id, entry.normalized_result)
                    finalized.append(public_id)
                    published.append(public_id)
                elif job.status is durable.JobStatus.FINALIZED:
                    if job.resolution is durable.JobResolution.ACCEPTED:
                        assert job.normalized_result_identity is not None
                        assert job.validated_cache_identity is not None
                        entry = repository.lookup_cache(job.validated_cache_identity)
                        assert entry is not None
                        result = entry.normalized_result
                    else:
                        result = {
                            "kind": _STRUCTURAL_KIND,
                            "job_identity": workflow_digest(
                                {"run_id": run_id, "job_id": public_id}
                            ),
                        }
                    repository.publish_job(job.descriptor.job_id, result)
                    published.append(public_id)
        return RecoveryReport(
            tuple(not_transmitted),
            tuple(indeterminate),
            tuple(finalized),
            tuple(published),
            tuple(policy_resume),
        )

    def store_retry_approval(self, run_id: str, approval: JobRetryApproval) -> None:
        preview = self.load_preview(run_id)
        if approval.preview_identity != preview.identity:
            raise durable.StoryMapV2RepositoryError("retry approval changed preview identity")
        job_id = _job_id(run_id, approval.job_id)
        with self._repository() as repository:
            attempts = repository.list_attempts(job_id)
            if not attempts or attempts[-1].reservation.attempt_id != (
                approval.indeterminate_attempt_id
            ):
                raise durable.StoryMapV2RepositoryError("retry approval is not latest")
            if any(
                repository.load_retry_approval(job_id, item.reservation.ordinal) is not None
                for item in attempts[:-1]
            ):
                raise durable.StoryMapV2RepositoryError(
                    "an approved indeterminate retry cannot be approved again"
                )
            stored = asdict(approval)
            repository.store_retry_approval(
                durable.RetryApprovalDescriptor(
                    _stable_id("retry", approval.identity),
                    job_id,
                    attempts[-1].reservation.ordinal,
                    stored,
                    _object_identity(stored),
                )
            )

    def status(self, run_id: str) -> WorkflowStatus:
        preview = self.load_preview(run_id)
        with self._repository() as repository:
            run = repository.get_run(_run_id(run_id))
            if run is None:
                raise durable.StoryMapV2RepositoryError("unknown workflow run")
            jobs = repository.list_jobs(run.descriptor.run_id)
            attempts = tuple(
                attempt
                for job in jobs
                for attempt in repository.list_attempts(job.descriptor.job_id)
            )
            approved = repository.load_run_approval(run.descriptor.run_id) is not None
            retry_details: list[IndeterminateRetryStatus] = []
            for job in jobs:
                job_attempts = repository.list_attempts(job.descriptor.job_id)
                if not job_attempts:
                    continue
                latest = job_attempts[-1]
                if latest.reservation.status is not durable.AttemptStatus.INDETERMINATE:
                    continue
                public_job = _job_for_record(repository, preview, job.descriptor)
                retry = repository.load_retry_approval(
                    job.descriptor.job_id, latest.reservation.ordinal
                )
                retry_details.append(
                    IndeterminateRetryStatus(
                        public_job.job_id,
                        latest.reservation.attempt_id,
                        ProviderCallKind(latest.reservation.metadata.call_kind),
                        None if retry is None else retry.descriptor.approval_identity,
                        retry is None,
                    )
                )
        return WorkflowStatus(
            run_id,
            preview.identity,
            approved,
            run.cancel_requested,
            sum(
                item.status
                in {
                    durable.JobStatus.PENDING,
                    durable.JobStatus.CLAIMED,
                    durable.JobStatus.RETURNED,
                    durable.JobStatus.VALIDATED,
                }
                for item in jobs
            ),
            sum(
                item.status
                in {
                    durable.JobStatus.CLAIMED,
                    durable.JobStatus.RESERVED,
                    durable.JobStatus.SUBMITTING,
                }
                for item in jobs
            ),
            sum(item.resolution is durable.JobResolution.ACCEPTED for item in jobs),
            sum(item.resolution is durable.JobResolution.STRUCTURAL for item in jobs),
            sum(
                item.resolution is durable.JobResolution.RESUMABLE
                for item in jobs
            ),
            len(retry_details),
            WorkflowAccounting(
                sum(item.accounting.calls for item in attempts),
                sum(item.accounting.input_tokens for item in attempts),
                sum(item.accounting.output_tokens for item in attempts),
                sum(item.accounting.elapsed_ms for item in attempts),
            ),
            tuple(retry_details),
        )

def _preview_object(preview: WorkflowPreview) -> object:
    return {
        "kind": _PREVIEW_KIND,
        "preview": json.loads(canonical_workflow_bytes(asdict(preview))),
    }


def _frozen_plans_object(bundle: FrozenPlanBundle) -> object:
    story_plan = bundle.story_plan_bytes
    story_chunk_plan = bundle.story_chunk_plan_bytes
    return {
        "kind": _FROZEN_PLANS_KIND,
        "story_plan": {
            "identity": bundle.story_plan.identity,
            "sha256": hashlib.sha256(story_plan).hexdigest(),
            "canonical_b64": base64.b64encode(story_plan).decode("ascii"),
        },
        "story_chunk_plan": {
            "identity": bundle.story_chunk_plan.identity,
            "sha256": hashlib.sha256(story_chunk_plan).hexdigest(),
            "canonical_b64": base64.b64encode(story_chunk_plan).decode("ascii"),
        },
    }


def _decode_frozen_plans(value: object) -> FrozenPlanBundle:
    envelope = _mapping(value, "frozen plans")
    if set(envelope) != {"kind", "story_plan", "story_chunk_plan"}:
        raise storage.ProjectCorruptError("frozen-plan envelope shape changed")
    if envelope.get("kind") != _FROZEN_PLANS_KIND:
        raise storage.ProjectCorruptError("unsupported durable frozen plans")

    decoded: list[tuple[bytes, str]] = []
    for key in ("story_plan", "story_chunk_plan"):
        item = _mapping(envelope.get(key), key.replace("_", " "))
        if set(item) != {"identity", "sha256", "canonical_b64"}:
            raise storage.ProjectCorruptError("frozen-plan payload shape changed")
        identity = _str(item, "identity")
        expected_hash = _str(item, "sha256")
        try:
            payload = base64.b64decode(_str(item, "canonical_b64"), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise storage.ProjectCorruptError(
                "frozen-plan payload is not canonical base64"
            ) from exc
        if hashlib.sha256(payload).hexdigest() != expected_hash:
            raise storage.ProjectCorruptError("frozen-plan payload hash changed")
        decoded.append((payload, identity))

    try:
        bundle = FrozenPlanBundle.from_bytes(decoded[0][0], decoded[1][0])
    except ValueError as exc:
        raise storage.ProjectCorruptError("frozen-plan payload is invalid") from exc
    if (
        bundle.story_plan.identity != decoded[0][1]
        or bundle.story_chunk_plan.identity != decoded[1][1]
    ):
        raise storage.ProjectCorruptError("frozen-plan identity changed")
    return bundle


def _decode_preview(value: object) -> WorkflowPreview:
    envelope = _mapping(value, "workflow preview")
    if envelope.get("kind") != _PREVIEW_KIND:
        raise storage.ProjectCorruptError("unsupported durable workflow preview")
    item = _mapping(envelope.get("preview"), "workflow preview body")
    plan_value = _mapping(item.get("plan"), "workflow plan")
    authority = AuthorityIdentity(
        _str(_mapping(plan_value.get("authority_identity"), "plan authority"), "value")
    )
    jobs = tuple(
        WorkflowJobDescriptor(
            plan_id=_str(job, "plan_id"),
            scope_id=_str(job, "scope_id"),
            job_id=_str(job, "job_id"),
            chunk_id=_str(job, "chunk_id"),
            authority_identity=AuthorityIdentity(
                _str(_mapping(job.get("authority_identity"), "job authority"), "value")
            ),
            serialized_request_identity=_decode_request_identity(
                job.get("serialized_request_identity")
            ),
            cache_identity=CacheIdentity(
                _str(_mapping(job.get("cache_identity"), "cache identity"), "value")
            ),
            critical=bool(job.get("critical", False)),
        )
        for job in (
            _mapping(raw, "workflow job") for raw in _list(plan_value, "jobs")
        )
    )
    policy_value = _mapping(item.get("policy"), "workflow policy")
    loopback_raw = policy_value.get("loopback")
    policy = WorkflowPolicy(
        prompt_version=_str(policy_value, "prompt_version"),
        schema_version=_str(policy_value, "schema_version"),
        cloud=_decode_settings(policy_value.get("cloud")),
        loopback=None if loopback_raw is None else _decode_settings(loopback_raw),
        allow_refusal_fallback=bool(policy_value.get("allow_refusal_fallback")),
        policy_version=_str(policy_value, "policy_version"),
    )
    ceilings_value = _mapping(item.get("ceilings"), "workflow ceilings")
    privacy_value = _mapping(item.get("privacy"), "workflow privacy")
    derived_raw = plan_value.get("derived_semantic_plan")
    return WorkflowPreview(
        run_id=_str(item, "run_id"),
        plan=WorkflowPlanDescriptor(
            _str(plan_value, "plan_id"),
            authority,
            jobs,
            None if derived_raw is None else _decode_derived_plan(derived_raw),
        ),
        policy=policy,
        ceilings=WorkflowResourceCeilings(
            **{key: _int(ceilings_value, key) for key in asdict(_dummy_ceilings())}
        ),
        privacy=WorkflowPrivacyScope(
            **{key: bool(privacy_value[key]) for key in asdict(_dummy_privacy())}
        ),
        cache_hit_job_ids=tuple(str(value) for value in _list(item, "cache_hit_job_ids")),
        loopback_cache_hit_job_ids=tuple(
            str(value) for value in _list(item, "loopback_cache_hit_job_ids")
        ),
        schema=_str(item, "schema"),
    )


def _decode_settings(value: object) -> ProviderSettings:
    item = _mapping(value, "provider settings")
    return ProviderSettings(
        provider=_str(item, "provider"),
        model=_str(item, "model"),
        reasoning=None if item.get("reasoning") is None else _str(item, "reasoning"),
        fast_mode=cast(bool | None, item.get("fast_mode")),
        mode=ProviderMode(_str(item, "mode")),
        adapter_version=_str(item, "adapter_version"),
    )


def _decode_request_identity(value: object) -> SerializedRequestIdentity:
    item = _mapping(value, "serialized request identity")
    return SerializedRequestIdentity(
        _str(item, "value"), _str(item, "sha256"), _int(item, "byte_count")
    )


def _decode_derived_plan(value: object) -> WorkflowDerivedSemanticPlanDescriptor:
    item = _mapping(value, "derived semantic plan")
    return WorkflowDerivedSemanticPlanDescriptor(
        semantic_plan_identity=_str(item, "semantic_plan_identity"),
        story_chunk_plan_identity=_str(item, "story_chunk_plan_identity"),
        authority_identity=AuthorityIdentity(
            _str(_mapping(item.get("authority_identity"), "derived authority"), "value")
        ),
        corridors=tuple(
            WorkflowCorridorDescriptor(
                _str(corridor, "corridor_id"),
                (
                    None
                    if corridor.get("route_owner") is None
                    else _str(corridor, "route_owner")
                ),
                _int(corridor, "event_slot_upper_bound"),
                _int(corridor, "ordinal"),
            )
            for corridor in (
                _mapping(raw, "derived corridor") for raw in _list(item, "corridors")
            )
        ),
        route_memberships=tuple(
            WorkflowRouteMembership(
                _str(membership, "route_id"),
                tuple(str(raw) for raw in _list(membership, "ordered_corridor_ids")),
            )
            for membership in (
                _mapping(raw, "route membership")
                for raw in _list(item, "route_memberships")
            )
        ),
        section_synthesis_calls=_int(item, "section_synthesis_calls"),
        route_reduction_calls=_int(item, "route_reduction_calls"),
        route_summary_calls=_int(item, "route_summary_calls"),
        whole_game_reduction_calls=_int(item, "whole_game_reduction_calls"),
        final_overview_calls=_int(item, "final_overview_calls"),
        rollup_synthesis_calls=_int(item, "rollup_synthesis_calls"),
        fan_in=_int(item, "fan_in"),
        version=_str(item, "version"),
    )


def _result_object(result: ValidatedWorkflowResult) -> object:
    return {
        "kind": _RESULT_KIND,
        "result_identity": result.result_identity,
        "normalized_prose_b64": base64.b64encode(result.normalized_payload).decode("ascii"),
        "flagged_for_review": result.flagged_for_review,
    }


def _decode_result(value: object) -> ValidatedWorkflowResult:
    item = _mapping(value, "normalized workflow result")
    if item.get("kind") != _RESULT_KIND:
        raise storage.ProjectCorruptError("unsupported normalized workflow result")
    try:
        normalized = base64.b64decode(_str(item, "normalized_prose_b64"), validate=True)
    except ValueError as exc:
        raise storage.ProjectCorruptError("invalid normalized workflow prose encoding") from exc
    return ValidatedWorkflowResult(
        _str(item, "result_identity"), normalized, bool(item.get("flagged_for_review"))
    )


def _dummy_ceilings() -> WorkflowResourceCeilings:
    return WorkflowResourceCeilings(1, 0, 0, 1, 0, 1)


def _dummy_privacy() -> WorkflowPrivacyScope:
    return WorkflowPrivacyScope(True, False)


def _durable_job(
    run_id: str, job: WorkflowExecutableJobDescriptor, ordinal: int
) -> durable.FrozenJobDescriptor:
    if isinstance(job, WorkflowDerivedSemanticJobDescriptor):
        scope_id = (
            "section_synthesis" if job.node_role is None else job.node_role.value
        )
        chunk_id = _stable_id("derived-job", job.job_id)
    else:
        scope_id = _stable_id("scope", job.scope_id)
        chunk_id = _stable_id("chunk", job.chunk_id)
    return durable.FrozenJobDescriptor(
        _run_id(run_id),
        _stable_id("plan", job.plan_id),
        scope_id,
        _job_id(run_id, job.job_id),
        chunk_id,
        _authority_digest(job.authority_identity.value),
        workflow_digest(asdict(job.serialized_request_identity)),
        job.cache_identity.value,
        ordinal,
    )


def _preview_job(preview: WorkflowPreview, ordinal: int) -> WorkflowJobDescriptor:
    try:
        return preview.plan.jobs[ordinal]
    except IndexError as exc:
        raise storage.ProjectCorruptError("workflow job ordinal is outside its preview") from exc


def _job_for_record(
    repository: durable.StoryMapV2Repository,
    preview: WorkflowPreview,
    descriptor: durable.FrozenJobDescriptor,
) -> WorkflowExecutableJobDescriptor:
    if descriptor.ordinal < len(preview.plan.jobs):
        return _preview_job(preview, descriptor.ordinal)
    return _load_derived_job(repository, descriptor.job_id)


def _derived_job_object(job: WorkflowDerivedSemanticJobDescriptor) -> object:
    return {
        "kind": _DERIVED_JOB_KIND,
        "job": json.loads(canonical_workflow_bytes(asdict(job))),
    }


def _load_derived_job(
    repository: durable.StoryMapV2Repository,
    durable_job_id: str,
) -> WorkflowDerivedSemanticJobDescriptor:
    record = repository.load_prepared_preview(_derived_job_preview_id(durable_job_id))
    if record is None:
        raise storage.ProjectCorruptError("derived workflow job descriptor is missing")
    envelope = _mapping(record.descriptor.preview, "derived workflow job")
    if envelope.get("kind") != _DERIVED_JOB_KIND:
        raise storage.ProjectCorruptError("unsupported derived workflow job descriptor")
    item = _mapping(envelope.get("job"), "derived workflow job body")
    provider_input = _decode_provider_input(item.get("provider_input_identity"))
    return WorkflowDerivedSemanticJobDescriptor(
        plan_id=_str(item, "plan_id"),
        semantic_plan_identity=_str(item, "semantic_plan_identity"),
        story_chunk_plan_identity=_str(item, "story_chunk_plan_identity"),
        candidate_generation_identity=_str(item, "candidate_generation_identity"),
        authority_identity=AuthorityIdentity(
            _str(_mapping(item.get("authority_identity"), "derived authority"), "value")
        ),
        job_id=_str(item, "job_id"),
        call_kind=ProviderCallKind(_str(item, "call_kind")),
        node_role=(
            None
            if item.get("node_role") is None
            else DerivedSemanticNodeRole(_str(item, "node_role"))
        ),
        corridor_id=(
            None if item.get("corridor_id") is None else _str(item, "corridor_id")
        ),
        route_owner=(
            None if item.get("route_owner") is None else _str(item, "route_owner")
        ),
        child_ids=tuple(str(value) for value in _list(item, "child_ids")),
        child_prose_hashes=tuple(
            str(value) for value in _list(item, "child_prose_hashes")
        ),
        ordinal=_int(item, "ordinal"),
        serialized_request_identity=_decode_request_identity(
            item.get("serialized_request_identity")
        ),
        provider_input_identity=provider_input,
        cache_identity=CacheIdentity(
            _str(_mapping(item.get("cache_identity"), "derived cache identity"), "value")
        ),
    )


def _decode_provider_input(value: object) -> ProviderInputIdentity:
    item = _mapping(value, "provider input identity")
    return ProviderInputIdentity(
        serialized_request_identity=_decode_request_identity(
            item.get("serialized_request_identity")
        ),
        prompt_version=_str(item, "prompt_version"),
        schema_version=_str(item, "schema_version"),
        adapter_version=_str(item, "adapter_version"),
        provider=_str(item, "provider"),
        model=_str(item, "model"),
        reasoning=(
            None if item.get("reasoning") is None else _str(item, "reasoning")
        ),
        fast_mode=cast(bool | None, item.get("fast_mode")),
        mode=ProviderMode(_str(item, "mode")),
    )


def _validate_derived_job_membership(
    job: WorkflowDerivedSemanticJobDescriptor,
    plan: WorkflowDerivedSemanticPlanDescriptor,
) -> None:
    if job.call_kind is ProviderCallKind.SECTION_SYNTHESIS:
        corridor = next(
            (item for item in plan.corridors if item.corridor_id == job.corridor_id), None
        )
        if corridor is None or corridor.route_owner != job.route_owner:
            raise durable.StoryMapV2RepositoryError(
                "section job does not match a frozen semantic corridor"
            )
        return
    assert job.node_role is not None
    component_limit = {
        DerivedSemanticNodeRole.ROUTE_REDUCTION: plan.route_reduction_calls,
        DerivedSemanticNodeRole.ROUTE_SUMMARY: plan.route_summary_calls,
        DerivedSemanticNodeRole.WHOLE_GAME_REDUCTION: plan.whole_game_reduction_calls,
        DerivedSemanticNodeRole.FINAL_OVERVIEW: plan.final_overview_calls,
    }[job.node_role]
    if component_limit < 1:
        raise durable.StoryMapV2RepositoryError(
            "rollup job exceeds its frozen semantic component ceiling"
        )


def _resume_kind(
    claim: durable.JobClaim, attempts: tuple[durable.AttemptRecord, ...]
) -> ProviderCallKind | None:
    if claim.continuation_kind in {
        durable.ContinuationKind.REPLACEMENT_REVIEW,
        durable.ContinuationKind.REFUSAL_FALLBACK,
    }:
        return ProviderCallKind(claim.continuation_kind.value)
    if attempts and attempts[-1].reservation.transmission_disposition in {
        durable.TransmissionDisposition.DEFINITELY_NOT_TRANSMITTED,
        durable.TransmissionDisposition.INDETERMINATE,
    }:
        return ProviderCallKind(attempts[-1].reservation.metadata.call_kind)
    return None


def _load_claim(
    repository: durable.StoryMapV2Repository, claim: JobClaim
) -> durable.JobClaim:
    durable_claim = repository.load_claim(
        _job_id(claim.run_id, claim.job.job_id), claim.claim_id
    )
    if durable_claim is None:
        raise durable.LeaseConflictError("claimed workflow job no longer exists")
    return durable_claim


def _load_claim_or_job(
    repository: durable.StoryMapV2Repository, claim: JobClaim
) -> durable.JobClaim:
    loaded = repository.load_claim(
        _job_id(claim.run_id, claim.job.job_id), claim.claim_id
    )
    if loaded is not None:
        return loaded
    job = repository.get_job(_job_id(claim.run_id, claim.job.job_id))
    if job is None:
        raise durable.LeaseConflictError("workflow job no longer exists")
    return durable.JobClaim(
        job.descriptor,
        _stable_id("worker", claim.worker_id),
        claim.claim_id,
        "1970-01-01T00:00:00.000000Z",
        job.continuation_kind,
        job.continuation_attempt_id,
        job.continuation_result_identity,
    )


def _load_attempt(
    repository: durable.StoryMapV2Repository,
    claim: durable.JobClaim,
    reservation: AttemptReservation,
) -> durable.AttemptReservation:
    match = next(
        (
            item.reservation
            for item in repository.list_attempts(claim.descriptor.job_id)
            if item.reservation.attempt_id == reservation.attempt_id
        ),
        None,
    )
    if match is None:
        raise durable.LeaseConflictError("reserved workflow attempt no longer exists")
    return match


def _durable_accounting(value: AttemptAccounting) -> durable.AttemptAccounting:
    return durable.AttemptAccounting(
        value.calls, value.input_tokens, value.output_tokens, value.elapsed_ms
    )


def repository_attempts_not_transmitted(
    attempts: tuple[durable.AttemptRecord, ...], job_id: str
) -> tuple[durable.AttemptRecord, ...]:
    return tuple(
        item
        for item in attempts
        if item.reservation.job_id == job_id
        and item.reservation.transmission_disposition
        is durable.TransmissionDisposition.DEFINITELY_NOT_TRANSMITTED
    )


def _run_id(run_id: str) -> str:
    return _stable_id("run", run_id)


def _preview_id(run_id: str) -> str:
    return _stable_id("preview", run_id)


def _frozen_plans_id(run_id: str) -> str:
    return _stable_id("frozen-plans", run_id)


def _derived_job_preview_id(durable_job_id: str) -> str:
    return _stable_id("derived-job-preview", durable_job_id)


def _job_id(run_id: str, job_id: str) -> str:
    return workflow_digest({"kind": "job", "run_id": run_id, "job_id": job_id})


def _stable_id(kind: str, value: str) -> str:
    return workflow_digest({"kind": kind, "value": value})


def _authority_digest(value: str) -> str:
    return _stable_id("authority", value)


def _execution_id(preview: WorkflowPreview) -> str:
    return workflow_digest(
        {
            "kind": "execution",
            "run_id": preview.run_id,
            "preview_identity": preview.identity,
            "authority_identity": preview.plan.authority_identity.value,
        }
    )


def _object_identity(value: object) -> str:
    return hashlib.sha256(storage.canonical_json(value)).hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise storage.ProjectCorruptError(f"{label} is not a canonical object")
    return cast(Mapping[str, object], value)


def _list(value: Mapping[str, object], key: str) -> list[object]:
    item = value.get(key)
    if not isinstance(item, list):
        raise storage.ProjectCorruptError(f"{key} is not a canonical list")
    return item


def _str(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise storage.ProjectCorruptError(f"{key} is not canonical text")
    return item


def _int(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if type(item) is not int:
        raise storage.ProjectCorruptError(f"{key} is not a canonical integer")
    return item


__all__ = ["DurableWorkflowRepositoryAdapter"]
