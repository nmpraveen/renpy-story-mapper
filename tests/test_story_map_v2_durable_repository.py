from __future__ import annotations

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from renpy_story_mapper import storage
from renpy_story_mapper.project import Project
from renpy_story_mapper.story_map_v2.durable_repository import (
    FAULT_AFTER_ATTEMPT_COMPLETION,
    FAULT_AFTER_ATTEMPT_FINALIZATION,
    FAULT_AFTER_ATTEMPT_RESERVATION,
    FAULT_AFTER_GENERATION_PUBLICATION,
    FAULT_AFTER_JOB_FINALIZATION,
    FAULT_AFTER_JOB_PUBLICATION,
    FAULT_AFTER_VALIDATION_RECORD,
    FAULT_BEFORE_ATTEMPT_FINALIZATION,
    FAULT_BEFORE_ATTEMPT_RESERVATION,
    FAULT_BEFORE_GENERATION_PUBLICATION,
    AttemptAccounting,
    AttemptReservationMetadata,
    AttemptStatus,
    ContinuationKind,
    FrozenJobDescriptor,
    FrozenRunDescriptor,
    GenerationDescriptor,
    GenerationKind,
    ImmutableRecordConflictError,
    JobResolution,
    JobStatus,
    LeaseConflictError,
    PreparedPreviewDescriptor,
    PublicationConflictError,
    RetryApprovalDescriptor,
    RunApprovalDescriptor,
    SectionPageRecord,
    SelectionIndexRecord,
    SqliteStoryMapV2Repository,
    StoryMapV2RepositoryError,
    TransmissionDisposition,
)

NOW = datetime(2026, 7, 26, 20, 0, tzinfo=UTC)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def job(
    ordinal: int,
    *,
    run_id: str = "run-1",
    plan_id: str = "plan-1",
    authority_identity: str | None = None,
    request_identity: str | None = None,
    cache_identity: str | None = None,
) -> FrozenJobDescriptor:
    return FrozenJobDescriptor(
        run_id=run_id,
        plan_id=plan_id,
        scope_id=f"scope-{ordinal}",
        job_id=f"{run_id}-job-{ordinal}",
        chunk_id=f"chunk-{ordinal}",
        authority_identity=digest("authority")
        if authority_identity is None
        else authority_identity,
        serialized_request_identity=digest(f"request-{run_id}-{ordinal}")
        if request_identity is None
        else request_identity,
        cache_identity=digest(f"cache-{run_id}-{ordinal}")
        if cache_identity is None
        else cache_identity,
        ordinal=ordinal,
    )


def create_run(
    repository: SqliteStoryMapV2Repository,
    *,
    run_id: str = "run-1",
    plan_id: str = "plan-1",
    jobs: tuple[FrozenJobDescriptor, ...] | None = None,
) -> tuple[FrozenJobDescriptor, ...]:
    descriptors = (job(0, run_id=run_id, plan_id=plan_id),) if jobs is None else jobs
    preview_payload = {
        "plan_id": plan_id,
        "authority_identity": digest("authority"),
        "pending_job_ids": [descriptor.job_id for descriptor in descriptors],
    }
    preview_id = f"preview-{run_id}"
    repository.store_prepared_preview(
        PreparedPreviewDescriptor(
            preview_id,
            plan_id,
            digest("authority"),
            preview_payload,
            hashlib.sha256(storage.canonical_json(preview_payload)).hexdigest(),
        ),
        now=NOW,
    )
    repository.create_run(
        FrozenRunDescriptor(run_id, plan_id, digest("authority")),
        descriptors,
    )
    approval_payload = {"run_id": run_id, "preview_id": preview_id, "approved": True}
    repository.store_run_approval(
        RunApprovalDescriptor(
            f"approval-{run_id}",
            run_id,
            preview_id,
            digest(f"execution-{run_id}"),
            approval_payload,
            hashlib.sha256(storage.canonical_json(approval_payload)).hexdigest(),
        ),
        now=NOW,
    )
    return descriptors


def reservation_metadata(descriptor: FrozenJobDescriptor) -> AttemptReservationMetadata:
    return AttemptReservationMetadata(
        call_kind="mapping",
        provider_input_identity=descriptor.serialized_request_identity,
        ceilings_identity=digest("finite-ceilings"),
    )


def one_call() -> AttemptAccounting:
    return AttemptAccounting(calls=1, input_tokens=10, output_tokens=5, elapsed_ms=100)


def raise_at(expected: str):  # type: ignore[no-untyped-def]
    def inject(point: str) -> None:
        if point == expected:
            raise RuntimeError(f"injected:{point}")

    return inject


def test_schema_v6_backup_is_verified_and_migrates_to_v7(tmp_path: Path) -> None:
    path = tmp_path / "v6.rsmp"
    connection = storage.connect(path)
    storage.initialize_database(connection, target_version=6)
    connection.close()

    with Project.open(path) as project:
        assert project.schema_version == 7
        tables = {
            str(row[0])
            for row in project._require_open().execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )
        }
        assert "story_map_v2_jobs" in tables
        assert "story_map_v2_generation_pointers" in tables

    backup = path.with_name(f"{path.name}.pre-migrate-v6.bak")
    backup_connection = storage.connect(backup)
    try:
        assert storage.validate_database(backup_connection) == 6
    finally:
        backup_connection.close()


def test_failed_v7_migration_restores_the_verified_v6_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "failed-migration.rsmp"
    connection = storage.connect(path)
    storage.initialize_database(connection, target_version=6)
    connection.execute("INSERT INTO project_metadata VALUES ('marker', X'31', 'then')")
    connection.close()

    def fail_after_a_write(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE migration_fault(value TEXT) STRICT")
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(storage, "_migrate_to_v7", fail_after_a_write)
    with pytest.raises(RuntimeError, match="injected migration failure"):
        Project.open(path)

    restored = storage.connect(path)
    try:
        assert storage.validate_database(restored) == 6
        assert restored.execute(
            "SELECT value_json FROM project_metadata WHERE key='marker'"
        ).fetchone()
        assert (
            restored.execute("SELECT 1 FROM sqlite_schema WHERE name='migration_fault'").fetchone()
            is None
        )
    finally:
        restored.close()


def test_v7_corrupt_index_fails_schema_validation(tmp_path: Path) -> None:
    path = tmp_path / "corrupt-index.rsmp"
    with Project.create(path):
        pass
    connection = sqlite3.connect(path)
    connection.execute("DROP INDEX story_map_v2_jobs_claim_idx")
    connection.close()

    with pytest.raises(storage.ProjectCorruptError, match="missing Story Map V2 index"):
        Project.open(path)


def test_two_connections_share_six_global_claims_without_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "claims.rsmp"
    with Project.create(path) as project:
        repository = project.story_map_v2_repository()
        descriptors = tuple(job(index) for index in range(12))
        create_run(repository, jobs=descriptors)

    def runner(owner: str) -> tuple[str, ...]:
        claimed: list[str] = []
        with Project.open(path) as project:
            repository = project.story_map_v2_repository()
            for _ in range(6):
                claim = repository.claim_next_job(owner, now=NOW)
                if claim is not None:
                    claimed.append(claim.descriptor.job_id)
        return tuple(claimed)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(runner, "runner-a")
        second = executor.submit(runner, "runner-b")
        claimed = first.result() + second.result()

    assert len(claimed) == 6
    assert len(set(claimed)) == 6
    with Project.open(path) as project:
        repository = project.story_map_v2_repository()
        assert repository.global_active_claim_count(now=NOW) == 6
        assert repository.claim_next_job("runner-c", now=NOW) is None


def test_preview_approval_is_required_and_run_filter_keeps_global_accounting(
    tmp_path: Path,
) -> None:
    with Project.create(tmp_path / "approval.rsmp") as project:
        repository = project.story_map_v2_repository()
        descriptor = job(0)
        preview_payload = {"plan_id": "plan-1", "pending": [descriptor.job_id]}
        preview = PreparedPreviewDescriptor(
            "preview-1",
            "plan-1",
            digest("authority"),
            preview_payload,
            hashlib.sha256(storage.canonical_json(preview_payload)).hexdigest(),
        )
        repository.store_prepared_preview(preview, now=NOW)
        repository.create_run(
            FrozenRunDescriptor("run-1", "plan-1", digest("authority")),
            (descriptor,),
        )
        assert repository.claim_next_job("blocked", run_id="run-1", now=NOW) is None

        approval_payload = {"run_id": "run-1", "preview_id": "preview-1"}
        approval = RunApprovalDescriptor(
            "approval-1",
            "run-1",
            "preview-1",
            digest("execution-1"),
            approval_payload,
            hashlib.sha256(storage.canonical_json(approval_payload)).hexdigest(),
        )
        repository.store_run_approval(approval, now=NOW)
        assert repository.load_prepared_preview("preview-1").descriptor == preview  # type: ignore[union-attr]
        assert repository.load_run_approval("run-1").descriptor == approval  # type: ignore[union-attr]

        create_run(repository, run_id="run-2", plan_id="plan-2")
        run_two = repository.claim_next_job("runner-2", run_id="run-2", now=NOW)
        assert run_two is not None and run_two.descriptor.run_id == "run-2"
        run_one = repository.claim_next_job("runner-1", run_id="run-1", now=NOW)
        assert run_one is not None and run_one.descriptor.run_id == "run-1"
        assert repository.global_active_claim_count(now=NOW) == 2


def test_reservation_faults_are_durable_and_attempt_ordinals_never_reuse(tmp_path: Path) -> None:
    path = tmp_path / "attempts.rsmp"
    with Project.create(path) as project:
        repository = project.story_map_v2_repository()
        create_run(repository)
        claim = repository.claim_next_job("runner", lease_seconds=10, now=NOW)
        assert claim is not None

        with pytest.raises(RuntimeError, match=FAULT_BEFORE_ATTEMPT_RESERVATION):
            repository.reserve_attempt(
                claim,
                reservation_metadata(claim.descriptor),
                now=NOW,
                fault=raise_at(FAULT_BEFORE_ATTEMPT_RESERVATION),
            )
        assert repository.list_attempts(claim.descriptor.job_id) == ()

        first = repository.reserve_attempt(claim, reservation_metadata(claim.descriptor), now=NOW)
        assert first.ordinal == 1
        repository.mark_transmitting(claim, first, now=NOW)
        repository.finalize_failure(
            claim,
            first,
            disposition=TransmissionDisposition.INDETERMINATE,
            accounting=AttemptAccounting(0, 0, 0, 1),
            failure_kind="transport_unknown",
            sanitized_failure="provider_outcome_unknown",
            now=NOW,
        )
        first_retry_payload = {"job_id": claim.descriptor.job_id, "attempt_ordinal": 1}
        pending_approval = repository.store_retry_approval(
            RetryApprovalDescriptor(
                "retry-approval-0",
                claim.descriptor.job_id,
                1,
                first_retry_payload,
                hashlib.sha256(storage.canonical_json(first_retry_payload)).hexdigest(),
            ),
            now=NOW,
        )
        assert pending_approval.consumed_utc is None

        second_claim = repository.claim_next_job("runner", lease_seconds=10, now=NOW)
        assert second_claim is not None
        with pytest.raises(RuntimeError, match=FAULT_AFTER_ATTEMPT_RESERVATION):
            repository.reserve_attempt(
                second_claim,
                reservation_metadata(second_claim.descriptor),
                now=NOW,
                fault=raise_at(FAULT_AFTER_ATTEMPT_RESERVATION),
            )
        attempts = repository.list_attempts(second_claim.descriptor.job_id)
        assert [record.reservation.ordinal for record in attempts] == [1, 2]
        assert attempts[-1].reservation.status is AttemptStatus.RESERVED
        first_approval = repository.load_retry_approval(second_claim.descriptor.job_id, 1)
        assert first_approval is not None and first_approval.consumed_utc is not None

        assert repository.recover_expired_leases(now=NOW + timedelta(seconds=11)) == 1
        assert repository.get_job(second_claim.descriptor.job_id).status is JobStatus.PENDING  # type: ignore[union-attr]
        assert repository.list_attempts(second_claim.descriptor.job_id)[-1].reservation.status is (
            AttemptStatus.NOT_TRANSMITTED
        )
        assert repository.load_retry_approval(second_claim.descriptor.job_id, 2) is None
        retry_claim = repository.claim_next_job(
            "runner", run_id="run-1", lease_seconds=10, now=NOW + timedelta(seconds=12)
        )
        assert retry_claim is not None
        third = repository.reserve_attempt(
            retry_claim,
            reservation_metadata(retry_claim.descriptor),
            now=NOW + timedelta(seconds=12),
        )
        assert third.ordinal == 3


def test_expired_unreserved_claim_requeues_and_old_cas_token_fails(tmp_path: Path) -> None:
    with Project.create(tmp_path / "cas.rsmp") as project:
        repository = project.story_map_v2_repository()
        create_run(repository)
        old = repository.claim_next_job("old", lease_seconds=1, now=NOW)
        assert old is not None
        assert repository.recover_expired_leases(now=NOW + timedelta(seconds=2)) == 1
        current = repository.claim_next_job("current", now=NOW + timedelta(seconds=2))
        assert current is not None
        assert current.descriptor.job_id == old.descriptor.job_id
        assert current.lease_token != old.lease_token
        with pytest.raises(LeaseConflictError):
            repository.reserve_attempt(
                old,
                reservation_metadata(old.descriptor),
                now=NOW + timedelta(seconds=2),
            )


def test_expired_reserved_attempt_is_definitely_not_transmitted_and_retries_without_approval(
    tmp_path: Path,
) -> None:
    with Project.create(tmp_path / "reserved-expiry.rsmp") as project:
        repository = project.story_map_v2_repository()
        create_run(repository)
        first_claim = repository.claim_next_job("runner-1", lease_seconds=1, now=NOW)
        assert first_claim is not None
        first = repository.reserve_attempt(
            first_claim, reservation_metadata(first_claim.descriptor), now=NOW
        )

        assert repository.recover_expired_leases(now=NOW + timedelta(seconds=2)) == 1
        recovered = repository.list_attempts(first_claim.descriptor.job_id)[0]
        assert recovered.reservation.status is AttemptStatus.NOT_TRANSMITTED
        assert (
            recovered.reservation.transmission_disposition
            is TransmissionDisposition.DEFINITELY_NOT_TRANSMITTED
        )
        assert recovered.accounting == AttemptAccounting(0, 0, 0, 0)
        assert repository.get_job(first_claim.descriptor.job_id).status is JobStatus.PENDING  # type: ignore[union-attr]
        assert repository.load_retry_approval(first_claim.descriptor.job_id, first.ordinal) is None

        second_claim = repository.claim_next_job(
            "runner-2", lease_seconds=10, now=NOW + timedelta(seconds=2)
        )
        assert second_claim is not None
        second = repository.reserve_attempt(
            second_claim,
            reservation_metadata(second_claim.descriptor),
            now=NOW + timedelta(seconds=2),
        )
        assert second.ordinal == 2
        assert second.metadata.call_kind == first.metadata.call_kind
        assert (
            sum(record.accounting.calls for record in repository.list_attempts(first.job_id)) == 0
        )


def test_expired_transmitting_attempt_is_indeterminate_and_not_automatic(tmp_path: Path) -> None:
    with Project.create(tmp_path / "transmitting-expiry.rsmp") as project:
        repository = project.story_map_v2_repository()
        create_run(repository)
        claim = repository.claim_next_job("runner", lease_seconds=1, now=NOW)
        assert claim is not None
        attempt = repository.reserve_attempt(claim, reservation_metadata(claim.descriptor), now=NOW)
        repository.mark_transmitting(claim, attempt, now=NOW)

        assert repository.recover_expired_leases(now=NOW + timedelta(seconds=2)) == 1
        recovered = repository.list_attempts(claim.descriptor.job_id)[0]
        assert recovered.reservation.status is AttemptStatus.INDETERMINATE
        assert (
            recovered.reservation.transmission_disposition is TransmissionDisposition.INDETERMINATE
        )
        assert repository.get_job(claim.descriptor.job_id).status is JobStatus.INDETERMINATE  # type: ignore[union-attr]
        assert repository.claim_next_job("automatic", now=NOW + timedelta(seconds=2)) is None


def test_cancelled_reserved_attempt_cannot_transition_to_transmitting(tmp_path: Path) -> None:
    with Project.create(tmp_path / "cancel-reserved.rsmp") as project:
        repository = project.story_map_v2_repository()
        create_run(repository)
        claim = repository.claim_next_job("runner", lease_seconds=10, now=NOW)
        assert claim is not None
        attempt = repository.reserve_attempt(claim, reservation_metadata(claim.descriptor), now=NOW)
        repository.cancel_run("run-1", now=NOW)

        with pytest.raises(LeaseConflictError, match="cancel"):
            repository.mark_transmitting(claim, attempt, now=NOW)
        assert repository.get_job(claim.descriptor.job_id).status is JobStatus.RESERVED  # type: ignore[union-attr]
        assert repository.list_attempts(claim.descriptor.job_id)[0].reservation.status is (
            AttemptStatus.RESERVED
        )


def test_staged_indeterminate_completion_requires_explicit_retry_approval(tmp_path: Path) -> None:
    with Project.create(tmp_path / "staged-indeterminate.rsmp") as project:
        repository = project.story_map_v2_repository()
        create_run(repository)
        claim = repository.claim_next_job("runner", now=NOW)
        assert claim is not None
        attempt = repository.reserve_attempt(claim, reservation_metadata(claim.descriptor), now=NOW)
        repository.mark_transmitting(claim, attempt, now=NOW)
        repository.complete_attempt(
            claim,
            attempt,
            disposition=TransmissionDisposition.INDETERMINATE,
            accounting=AttemptAccounting(0, 0, 0, 10),
            response_identity=None,
            failure_kind="transport_unknown",
            sanitized_failure="provider_outcome_unknown",
            now=NOW,
        )

        assert repository.get_job(claim.descriptor.job_id).status is JobStatus.INDETERMINATE  # type: ignore[union-attr]
        finalized = repository.finalize_job(
            claim.descriptor.job_id, JobResolution.INDETERMINATE, now=NOW
        )
        assert finalized.resolution is JobResolution.INDETERMINATE
        assert repository.claim_next_job("automatic", now=NOW) is None
        with pytest.raises(ValueError, match="zero or one"):
            AttemptAccounting(2, 0, 0, 0)


@pytest.mark.parametrize(
    "continuation",
    [ContinuationKind.REPLACEMENT_REVIEW, ContinuationKind.REFUSAL_FALLBACK],
)
def test_indeterminate_continuation_retry_requires_matching_unconsumed_approval(
    tmp_path: Path,
    continuation: ContinuationKind,
) -> None:
    with Project.create(tmp_path / f"indeterminate-{continuation}.rsmp") as project:
        repository = project.story_map_v2_repository()
        create_run(repository)
        primary_claim = repository.claim_next_job("primary", lease_seconds=1, now=NOW)
        assert primary_claim is not None
        primary = repository.reserve_attempt(
            primary_claim, reservation_metadata(primary_claim.descriptor), now=NOW
        )
        repository.mark_transmitting(primary_claim, primary, now=NOW)
        primary_identity = digest(f"primary-{continuation}")
        repository.complete_attempt(
            primary_claim,
            primary,
            disposition=TransmissionDisposition.TRANSMITTED,
            accounting=one_call(),
            response_identity=primary_identity,
            now=NOW,
        )
        repository.record_continuation(
            primary_claim.descriptor.job_id,
            continuation,
            prior_attempt_id=primary.attempt_id,
            prior_result_identity=primary_identity,
            now=NOW,
        )
        continuation_claim = repository.claim_next_job(
            "secondary", lease_seconds=10, now=NOW + timedelta(seconds=2)
        )
        assert continuation_claim is not None
        secondary = repository.reserve_attempt(
            continuation_claim,
            AttemptReservationMetadata(
                continuation,
                digest(f"{continuation}-input"),
                digest(f"{continuation}-ceilings"),
            ),
            now=NOW + timedelta(seconds=2),
        )
        repository.mark_transmitting(continuation_claim, secondary, now=NOW + timedelta(seconds=2))
        repository.finalize_failure(
            continuation_claim,
            secondary,
            disposition=TransmissionDisposition.INDETERMINATE,
            accounting=AttemptAccounting(0, 0, 0, 5),
            failure_kind="transport_unknown",
            sanitized_failure="provider_outcome_unknown",
            now=NOW + timedelta(seconds=2),
        )
        payload = {"job_id": secondary.job_id, "attempt_ordinal": secondary.ordinal}
        approval = RetryApprovalDescriptor(
            f"retry-{continuation}",
            secondary.job_id,
            secondary.ordinal,
            payload,
            hashlib.sha256(storage.canonical_json(payload)).hexdigest(),
        )
        stored = repository.store_retry_approval(approval, now=NOW + timedelta(seconds=3))
        assert stored.consumed_utc is None
        retry_claim = repository.claim_next_job("secondary-retry", now=NOW + timedelta(seconds=3))
        assert retry_claim is not None
        wrong_kind = (
            ContinuationKind.REFUSAL_FALLBACK
            if continuation is ContinuationKind.REPLACEMENT_REVIEW
            else ContinuationKind.REPLACEMENT_REVIEW
        )
        with pytest.raises(StoryMapV2RepositoryError, match="same call kind"):
            repository.reserve_attempt(
                retry_claim,
                AttemptReservationMetadata(
                    wrong_kind,
                    digest("wrong-input"),
                    digest("wrong-ceilings"),
                ),
                now=NOW + timedelta(seconds=3),
            )
        loaded = repository.load_retry_approval(secondary.job_id, secondary.ordinal)
        assert loaded is not None and loaded.consumed_utc is None

        retried = repository.reserve_attempt(
            retry_claim,
            AttemptReservationMetadata(
                continuation,
                digest(f"{continuation}-retry-input"),
                digest(f"{continuation}-retry-ceilings"),
            ),
            now=NOW + timedelta(seconds=3),
        )
        assert retried.ordinal == 3
        consumed = repository.load_retry_approval(secondary.job_id, secondary.ordinal)
        assert consumed is not None and consumed.consumed_utc is not None


def test_finalization_is_atomic_before_and_durable_after_fault(tmp_path: Path) -> None:
    with Project.create(tmp_path / "finalize.rsmp") as project:
        repository = project.story_map_v2_repository()
        create_run(repository)
        claim = repository.claim_next_job("runner", now=NOW)
        assert claim is not None
        attempt = repository.reserve_attempt(claim, reservation_metadata(claim.descriptor), now=NOW)
        repository.mark_transmitting(claim, attempt, now=NOW)
        result = {"title": "Public summary", "events": [{"event_id": "event-1"}]}

        with pytest.raises(RuntimeError, match=FAULT_BEFORE_ATTEMPT_FINALIZATION):
            repository.finalize_success(
                claim,
                attempt,
                result,
                one_call(),
                now=NOW,
                fault=raise_at(FAULT_BEFORE_ATTEMPT_FINALIZATION),
            )
        assert repository.lookup_cache(claim.descriptor.cache_identity) is None
        assert repository.get_job(claim.descriptor.job_id).status is JobStatus.SUBMITTING  # type: ignore[union-attr]

        with pytest.raises(RuntimeError, match=FAULT_AFTER_ATTEMPT_FINALIZATION):
            repository.finalize_success(
                claim,
                attempt,
                result,
                one_call(),
                now=NOW,
                fault=raise_at(FAULT_AFTER_ATTEMPT_FINALIZATION),
            )
        cached = repository.lookup_cache(claim.descriptor.cache_identity)
        assert cached is not None
        assert cached.normalized_result == result
        assert repository.get_job(claim.descriptor.job_id).status is JobStatus.SUCCEEDED  # type: ignore[union-attr]
        final_attempt = repository.list_attempts(claim.descriptor.job_id)[0]
        assert final_attempt.accounting == one_call()
        assert final_attempt.reservation.transmission_disposition.value == "transmitted"


def test_attempt_completion_enforces_call_and_disposition_coherence(tmp_path: Path) -> None:
    with Project.create(tmp_path / "accounting-coherence.rsmp") as project:
        repository = project.story_map_v2_repository()
        create_run(repository)
        claim = repository.claim_next_job("runner", now=NOW)
        assert claim is not None
        attempt = repository.reserve_attempt(claim, reservation_metadata(claim.descriptor), now=NOW)

        with pytest.raises(ValueError, match="transmitted attempt must account for one call"):
            repository.complete_attempt(
                claim,
                attempt,
                disposition=TransmissionDisposition.TRANSMITTED,
                accounting=AttemptAccounting(0, 0, 0, 1),
                response_identity=digest("unexpected-zero-call-response"),
                now=NOW,
            )
        with pytest.raises(ValueError, match="non-transmission must account for zero calls"):
            repository.complete_attempt(
                claim,
                attempt,
                disposition=TransmissionDisposition.DEFINITELY_NOT_TRANSMITTED,
                accounting=AttemptAccounting(1, 0, 0, 1),
                response_identity=None,
                failure_kind="not_sent",
                sanitized_failure="provider_not_contacted",
                now=NOW,
            )
        assert repository.list_attempts(claim.descriptor.job_id)[0].reservation.status is (
            AttemptStatus.RESERVED
        )


def test_indeterminate_failure_persists_disposition_accounting_and_failure_kind(
    tmp_path: Path,
) -> None:
    with Project.create(tmp_path / "indeterminate.rsmp") as project:
        repository = project.story_map_v2_repository()
        create_run(repository)
        claim = repository.claim_next_job("runner", now=NOW)
        assert claim is not None
        metadata = AttemptReservationMetadata(
            "mapping",
            claim.descriptor.serialized_request_identity,
            digest("review-ceilings"),
        )
        attempt = repository.reserve_attempt(claim, metadata, now=NOW)
        repository.mark_transmitting(claim, attempt, now=NOW)
        accounting = AttemptAccounting(1, 123, 0, 456)
        repository.finalize_failure(
            claim,
            attempt,
            disposition=TransmissionDisposition.INDETERMINATE,
            accounting=accounting,
            failure_kind="transport_identity_unknown",
            sanitized_failure="provider_outcome_unknown",
            now=NOW,
        )

        record = repository.list_attempts(claim.descriptor.job_id)[0]
        assert record.reservation.metadata == metadata
        assert record.reservation.status is AttemptStatus.INDETERMINATE
        assert record.reservation.transmission_disposition is TransmissionDisposition.INDETERMINATE
        assert record.accounting == accounting
        assert record.failure_kind == "transport_identity_unknown"
        assert repository.get_job(claim.descriptor.job_id).status is JobStatus.INDETERMINATE  # type: ignore[union-attr]


def test_staged_return_validation_finalization_and_publication_survive_crashes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "staged.rsmp"
    normalized = {"summary": "Validated synthetic result", "event_ids": ["event-1"]}
    with Project.create(path) as project:
        repository = project.story_map_v2_repository()
        create_run(repository)
        claim = repository.claim_next_job("runner", now=NOW)
        assert claim is not None
        attempt = repository.reserve_attempt(claim, reservation_metadata(claim.descriptor), now=NOW)
        repository.mark_transmitting(claim, attempt, now=NOW)
        with pytest.raises(RuntimeError, match=FAULT_AFTER_ATTEMPT_COMPLETION):
            repository.complete_attempt(
                claim,
                attempt,
                disposition=TransmissionDisposition.TRANSMITTED,
                accounting=one_call(),
                response_identity=digest("provider-response"),
                now=NOW,
                fault=raise_at(FAULT_AFTER_ATTEMPT_COMPLETION),
            )

    with Project.open(path) as project:
        repository = project.story_map_v2_repository()
        assert repository.get_job("run-1-job-0").status is JobStatus.RETURNED  # type: ignore[union-attr]
        assert repository.list_attempts("run-1-job-0")[0].reservation.status is (
            AttemptStatus.RETURNED
        )
        with pytest.raises(RuntimeError, match=FAULT_AFTER_VALIDATION_RECORD):
            repository.record_validated(
                "run-1-job-0",
                repository.list_attempts("run-1-job-0")[0].reservation.attempt_id,
                normalized,
                now=NOW,
                fault=raise_at(FAULT_AFTER_VALIDATION_RECORD),
            )

    with Project.open(path) as project:
        repository = project.story_map_v2_repository()
        validated = repository.get_job("run-1-job-0")
        assert validated is not None and validated.status is JobStatus.VALIDATED
        repository.store_cache("run-1-job-0", now=NOW)
        assert repository.lookup_cache(validated.descriptor.cache_identity) is not None
        with pytest.raises(RuntimeError, match=FAULT_AFTER_JOB_FINALIZATION):
            repository.finalize_job(
                "run-1-job-0",
                JobResolution.ACCEPTED,
                now=NOW,
                fault=raise_at(FAULT_AFTER_JOB_FINALIZATION),
            )

    with Project.open(path) as project:
        repository = project.story_map_v2_repository()
        finalized = repository.get_job("run-1-job-0")
        assert finalized is not None and finalized.status is JobStatus.FINALIZED
        assert finalized.resolution is JobResolution.ACCEPTED
        with pytest.raises(PublicationConflictError, match="cached normalized result"):
            repository.publish_job("run-1-job-0", {"summary": "wrong"}, now=NOW)
        with pytest.raises(RuntimeError, match=FAULT_AFTER_JOB_PUBLICATION):
            repository.publish_job(
                "run-1-job-0",
                normalized,
                now=NOW,
                fault=raise_at(FAULT_AFTER_JOB_PUBLICATION),
            )

    with Project.open(path) as project:
        repository = project.story_map_v2_repository()
        published = repository.load_published_result("run-1", "run-1-job-0")
        assert published is not None and published.result == normalized
        assert repository.get_job("run-1-job-0").status is JobStatus.PUBLISHED  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "continuation",
    [ContinuationKind.REPLACEMENT_REVIEW, ContinuationKind.REFUSAL_FALLBACK],
)
def test_reopen_resumes_exactly_one_review_or_refusal_fallback_attempt(
    tmp_path: Path,
    continuation: ContinuationKind,
) -> None:
    path = tmp_path / f"continuation-{continuation}.rsmp"
    primary_result = {"summary": "Flagged primary", "event_ids": ["event-1"]}
    with Project.create(path) as project:
        repository = project.story_map_v2_repository()
        create_run(repository)
        claim = repository.claim_next_job("primary", lease_seconds=1, now=NOW)
        assert claim is not None
        primary = repository.reserve_attempt(claim, reservation_metadata(claim.descriptor), now=NOW)
        repository.mark_transmitting(claim, primary, now=NOW)
        response_identity = digest("primary-response")
        repository.complete_attempt(
            claim,
            primary,
            disposition=TransmissionDisposition.TRANSMITTED,
            accounting=one_call(),
            response_identity=response_identity,
            now=NOW,
        )
        prior_identity = response_identity
        if continuation is ContinuationKind.REPLACEMENT_REVIEW:
            validated = repository.record_validated(
                claim.descriptor.job_id,
                primary.attempt_id,
                primary_result,
                now=NOW,
            )
            assert validated.normalized_result_identity is not None
            prior_identity = validated.normalized_result_identity
        repository.record_continuation(
            claim.descriptor.job_id,
            continuation,
            prior_attempt_id=primary.attempt_id,
            prior_result_identity=prior_identity,
            now=NOW,
        )
        other = (
            ContinuationKind.REFUSAL_FALLBACK
            if continuation is ContinuationKind.REPLACEMENT_REVIEW
            else ContinuationKind.REPLACEMENT_REVIEW
        )
        with pytest.raises(ImmutableRecordConflictError, match="kind is immutable"):
            repository.record_continuation(
                claim.descriptor.job_id,
                other,
                prior_attempt_id=primary.attempt_id,
                prior_result_identity=prior_identity,
                now=NOW,
            )

    with Project.open(path) as project:
        repository = project.story_map_v2_repository()
        assert repository.load_published_result("run-1", "run-1-job-0") is None
        resumed = repository.claim_next_job(
            "continuation", run_id="run-1", lease_seconds=10, now=NOW + timedelta(seconds=2)
        )
        assert resumed is not None
        assert resumed.continuation_kind is continuation
        assert resumed.continuation_attempt_id == primary.attempt_id
        resumed = repository.renew_lease(resumed, lease_seconds=20, now=NOW + timedelta(seconds=2))
        repository.release_claim(resumed, now=NOW + timedelta(seconds=2))
        resumed = repository.claim_next_job(
            "continuation", run_id="run-1", lease_seconds=10, now=NOW + timedelta(seconds=2)
        )
        assert resumed is not None and resumed.continuation_kind is continuation
        second = repository.reserve_attempt(
            resumed,
            AttemptReservationMetadata(
                continuation,
                digest(f"{continuation}-provider-input"),
                digest(f"{continuation}-ceilings"),
            ),
            now=NOW + timedelta(seconds=2),
        )
        assert second.ordinal == 2
        repository.mark_transmitting(resumed, second, now=NOW + timedelta(seconds=2))
        repository.complete_attempt(
            resumed,
            second,
            disposition=TransmissionDisposition.TRANSMITTED,
            accounting=one_call(),
            response_identity=digest(f"{continuation}-response"),
            now=NOW + timedelta(seconds=2),
        )
        with pytest.raises(StoryMapV2RepositoryError, match="latest returned attempt"):
            repository.record_validated(
                resumed.descriptor.job_id,
                primary.attempt_id,
                primary_result,
                now=NOW + timedelta(seconds=2),
            )
        replacement = repository.record_validated(
            resumed.descriptor.job_id,
            second.attempt_id,
            {"summary": f"Accepted {continuation}", "event_ids": ["event-1"]},
            now=NOW + timedelta(seconds=2),
        )
        assert replacement.normalized_result_identity is not None
        repository.record_continuation(
            resumed.descriptor.job_id,
            ContinuationKind.COMPLETE,
            prior_attempt_id=second.attempt_id,
            prior_result_identity=replacement.normalized_result_identity,
            now=NOW + timedelta(seconds=2),
        )
        with pytest.raises(StoryMapV2RepositoryError, match="limited to one"):
            repository.reserve_attempt(
                resumed,
                AttemptReservationMetadata(
                    continuation,
                    digest("third-input"),
                    digest("third-ceilings"),
                ),
                now=NOW + timedelta(seconds=2),
            )
        assert [
            record.reservation.metadata.call_kind
            for record in repository.list_attempts(resumed.descriptor.job_id)
        ] == ["mapping", continuation]


def test_cache_identity_is_immutable_and_run_routing_is_excluded(tmp_path: Path) -> None:
    shared_cache = digest("shared-cache")
    with Project.create(tmp_path / "cache.rsmp") as project:
        repository = project.story_map_v2_repository()
        first_job = job(0, cache_identity=shared_cache)
        create_run(repository, jobs=(first_job,))
        first_claim = repository.claim_next_job("first", now=NOW)
        assert first_claim is not None
        first_attempt = repository.reserve_attempt(
            first_claim, reservation_metadata(first_claim.descriptor), now=NOW
        )
        repository.finalize_success(
            first_claim,
            first_attempt,
            {"summary": "one"},
            one_call(),
            now=NOW,
        )

        replay_job = job(
            0,
            run_id="run-2",
            plan_id="plan-2",
            request_identity=first_job.serialized_request_identity,
            cache_identity=shared_cache,
        )
        create_run(repository, run_id="run-2", plan_id="plan-2", jobs=(replay_job,))
        assert repository.claim_next_job("replay", now=NOW) is None
        assert repository.get_job(replay_job.job_id).status is JobStatus.CACHED  # type: ignore[union-attr]

        collision_job = job(
            0,
            run_id="run-3",
            plan_id="plan-3",
            request_identity=digest("different-request"),
            cache_identity=shared_cache,
        )
        create_run(repository, run_id="run-3", plan_id="plan-3", jobs=(collision_job,))
        collision_claim = repository.claim_next_job("collision", now=NOW)
        assert collision_claim is not None
        collision_attempt = repository.reserve_attempt(
            collision_claim,
            reservation_metadata(collision_claim.descriptor),
            now=NOW,
        )
        with pytest.raises(ImmutableRecordConflictError):
            repository.finalize_success(
                collision_claim,
                collision_attempt,
                {"summary": "two"},
                one_call(),
                now=NOW,
            )
        assert repository.lookup_cache(shared_cache).normalized_result == {"summary": "one"}  # type: ignore[union-attr]


def test_generation_pages_selection_and_atomic_pointer_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "generation.rsmp"
    page_payload = {"events": [{"event_id": "event-1", "summary": "Synthetic"}]}
    page_identity = hashlib.sha256(storage.canonical_json(page_payload)).hexdigest()
    with Project.create(path) as project:
        repository = project.story_map_v2_repository()
        create_run(repository)
        generation = GenerationDescriptor(
            "generation-1",
            "run-1",
            "plan-1",
            digest("authority"),
            GenerationKind.COMPLETE,
            {"section_count": 1, "event_count": 1},
        )
        repository.create_generation(generation, now=NOW)
        repository.store_section_page(
            SectionPageRecord("generation-1", "section-1", 0, 1, page_payload, page_identity)
        )
        repository.store_selection(
            SelectionIndexRecord("generation-1", "event-1", "section-1", 0, 0, "event")
        )
        repository.set_active_generation(
            "generation-1", expected_active_generation_id=None, now=NOW
        )

        with pytest.raises(RuntimeError, match=FAULT_BEFORE_GENERATION_PUBLICATION):
            repository.publish_generation(
                "generation-1",
                expected_active_generation_id="generation-1",
                now=NOW,
                fault=raise_at(FAULT_BEFORE_GENERATION_PUBLICATION),
            )
        assert repository.generation_pointers().map_revision == 0

        with pytest.raises(RuntimeError, match=FAULT_AFTER_GENERATION_PUBLICATION):
            repository.publish_generation(
                "generation-1",
                expected_active_generation_id="generation-1",
                now=NOW,
                fault=raise_at(FAULT_AFTER_GENERATION_PUBLICATION),
            )
        assert repository.generation_pointers().current_complete_generation == "generation-1"
        assert repository.generation_pointers().map_revision == 1
        repository.save_view_state(
            "primary",
            generation_id="generation-1",
            map_revision=1,
            selection_id="event-1",
            section_id="section-1",
            state={"scroll_anchor": "event-1", "expanded": ["choice-1"]},
            now=NOW,
        )

    with Project.open(path) as project:
        repository = project.story_map_v2_repository()
        assert repository.generation_pointers().current_complete_generation == "generation-1"
        assert repository.load_section_page("generation-1", "section-1", 0) == SectionPageRecord(
            "generation-1", "section-1", 0, 1, page_payload, page_identity
        )
        assert repository.locate_selection("generation-1", "event-1") == SelectionIndexRecord(
            "generation-1", "event-1", "section-1", 0, 0, "event"
        )
        view = repository.load_view_state("primary")
        assert view is not None
        assert view.selection_id == "event-1"
        assert view.state == {"scroll_anchor": "event-1", "expanded": ["choice-1"]}


def test_generation_and_page_records_are_immutable(tmp_path: Path) -> None:
    with Project.create(tmp_path / "immutable-generation.rsmp") as project:
        repository = project.story_map_v2_repository()
        create_run(repository)
        generation = GenerationDescriptor(
            "generation-1",
            "run-1",
            "plan-1",
            digest("authority"),
            GenerationKind.COMPLETE,
            {"count": 1},
        )
        repository.create_generation(generation, now=NOW)
        repository.create_generation(generation, now=NOW)
        with pytest.raises(ImmutableRecordConflictError):
            repository.create_generation(
                GenerationDescriptor(
                    "generation-1",
                    "run-1",
                    "plan-1",
                    digest("authority"),
                    GenerationKind.COMPLETE,
                    {"count": 2},
                ),
                now=NOW,
            )

        first = {"events": ["one"]}
        first_hash = hashlib.sha256(storage.canonical_json(first)).hexdigest()
        repository.store_section_page(
            SectionPageRecord("generation-1", "section-1", 0, 1, first, first_hash)
        )
        second = {"events": ["two"]}
        second_hash = hashlib.sha256(storage.canonical_json(second)).hexdigest()
        with pytest.raises(ImmutableRecordConflictError):
            repository.store_section_page(
                SectionPageRecord("generation-1", "section-1", 0, 1, second, second_hash)
            )


def test_publication_requires_the_exact_active_complete_generation(tmp_path: Path) -> None:
    with Project.create(tmp_path / "publication-cas.rsmp") as project:
        repository = project.story_map_v2_repository()
        create_run(repository)
        repository.create_generation(
            GenerationDescriptor(
                "candidate",
                "run-1",
                "plan-1",
                digest("authority"),
                GenerationKind.CANDIDATE,
                {},
            ),
            now=NOW,
        )
        repository.set_active_generation("candidate", expected_active_generation_id=None, now=NOW)
        with pytest.raises(PublicationConflictError, match="complete"):
            repository.publish_generation(
                "candidate", expected_active_generation_id="candidate", now=NOW
            )


def test_generation_authority_must_match_its_run_at_create_activate_and_publish(
    tmp_path: Path,
) -> None:
    with Project.create(tmp_path / "generation-authority.rsmp") as project:
        repository = project.story_map_v2_repository()
        create_run(repository)
        with pytest.raises(StoryMapV2RepositoryError, match="run identity"):
            repository.create_generation(
                GenerationDescriptor(
                    "wrong-plan",
                    "run-1",
                    "foreign-plan",
                    digest("authority"),
                    GenerationKind.COMPLETE,
                    {},
                ),
                now=NOW,
            )
        with pytest.raises(StoryMapV2RepositoryError, match="run identity"):
            repository.create_generation(
                GenerationDescriptor(
                    "wrong-authority",
                    "run-1",
                    "plan-1",
                    digest("foreign-authority"),
                    GenerationKind.COMPLETE,
                    {},
                ),
                now=NOW,
            )

        generation = GenerationDescriptor(
            "complete",
            "run-1",
            "plan-1",
            digest("authority"),
            GenerationKind.COMPLETE,
            {},
        )
        repository.create_generation(generation, now=NOW)
        repository._connection.execute(
            "UPDATE story_map_v2_generations SET plan_id = 'foreign-plan' WHERE generation_id = ?",
            (generation.generation_id,),
        )
        with pytest.raises(PublicationConflictError, match="run identity"):
            repository.set_active_generation(
                generation.generation_id,
                expected_active_generation_id=None,
                now=NOW,
            )
        repository._connection.execute(
            """UPDATE story_map_v2_generations
               SET plan_id = 'plan-1' WHERE generation_id = ?""",
            (generation.generation_id,),
        )
        repository.set_active_generation(
            generation.generation_id,
            expected_active_generation_id=None,
            now=NOW,
        )
        repository._connection.execute(
            """UPDATE story_map_v2_generations
               SET authority_identity = ? WHERE generation_id = ?""",
            (digest("foreign-authority"), generation.generation_id),
        )
        with pytest.raises(PublicationConflictError, match="run identity"):
            repository.publish_generation(
                generation.generation_id,
                expected_active_generation_id=generation.generation_id,
                now=NOW,
            )


def test_privacy_rejection_and_sanitized_database_scan(tmp_path: Path) -> None:
    path = tmp_path / "privacy.rsmp"
    forbidden_marker = "PRIVATE_RAW_PROMPT_MARKER"
    normalized_key_markers = {
        "Raw Response": "PRIVATE_RAW_RESPONSE_MARKER",
        "request-payload": "PRIVATE_REQUEST_PAYLOAD_MARKER",
        "Prompt Text": "PRIVATE_PROMPT_TEXT_MARKER",
        "source_packet": "PRIVATE_SOURCE_PACKET_MARKER",
        "Provider Stderr": "PRIVATE_PROVIDER_STDERR_MARKER",
        "API Credentials": "PRIVATE_CREDENTIALS_MARKER",
    }
    embedded_paths = (
        "Location /opt/private/POSIX_PATH_MARKER.rpy",
        "Location C:\\private\\WINDOWS_PATH_MARKER.rpy",
        "Location \\\\private-server\\share\\UNC_PATH_MARKER.rpy",
    )
    with Project.create(path) as project:
        repository = project.story_map_v2_repository()
        create_run(repository)
        claim = repository.claim_next_job("runner", now=NOW)
        assert claim is not None
        attempt = repository.reserve_attempt(claim, reservation_metadata(claim.descriptor), now=NOW)

        with pytest.raises(ValueError, match="forbidden durable field"):
            repository.finalize_success(
                claim,
                attempt,
                {"raw_prompt": forbidden_marker},
                one_call(),
                now=NOW,
            )
        with pytest.raises(ValueError, match="absolute path"):
            repository.finalize_success(
                claim,
                attempt,
                {"summary": "C:\\Users\\private\\story.rpy"},
                one_call(),
                now=NOW,
            )
        repository.finalize_success(
            claim,
            attempt,
            {"summary": "Synthetic public result", "evidence_ids": ["evidence-1"]},
            one_call(),
            now=NOW,
        )
        with pytest.raises(ValueError, match="absolute path"):
            GenerationDescriptor(
                "private-generation",
                "run-1",
                "plan-1",
                digest("authority"),
                GenerationKind.COMPLETE,
                {"machine_path": "C:\\private\\source.rpy"},
            )
        for index, (key, marker) in enumerate(normalized_key_markers.items()):
            preview = {key: marker}
            with pytest.raises(ValueError, match="forbidden durable field"):
                PreparedPreviewDescriptor(
                    f"private-preview-{index}",
                    "plan-1",
                    digest("authority"),
                    preview,
                    hashlib.sha256(storage.canonical_json(preview)).hexdigest(),
                )
        for index, embedded_path in enumerate(embedded_paths):
            preview = {"summary": embedded_path}
            with pytest.raises(ValueError, match="absolute path"):
                PreparedPreviewDescriptor(
                    f"private-path-preview-{index}",
                    "plan-1",
                    digest("authority"),
                    preview,
                    hashlib.sha256(storage.canonical_json(preview)).hexdigest(),
                )

    database_bytes = path.read_bytes()
    assert forbidden_marker.encode("utf-8") not in database_bytes
    assert b"C:\\Users\\private\\story.rpy" not in database_bytes
    assert b"PRIVATE" not in database_bytes
    for marker in normalized_key_markers.values():
        assert marker.encode("utf-8") not in database_bytes
    for embedded_path in embedded_paths:
        assert embedded_path.encode("utf-8") not in database_bytes
