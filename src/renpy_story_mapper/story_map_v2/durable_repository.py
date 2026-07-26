"""Indexed schema-v7 durability for Story Map V2.

The repository deliberately consumes only frozen scalar identities.  It does not
import, adapt, or recompute planning structures and never stores rendered
requests, source packets, provider logs, credentials, or absolute paths.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol, cast, runtime_checkable

from renpy_story_mapper import storage

GLOBAL_SUBMISSION_LIMIT: Final = 6
FaultInjector = Callable[[str], None]

FAULT_BEFORE_ATTEMPT_RESERVATION: Final = "attempt_reservation.before"
FAULT_AFTER_ATTEMPT_RESERVATION: Final = "attempt_reservation.after"
FAULT_BEFORE_ATTEMPT_FINALIZATION: Final = "attempt_finalization.before"
FAULT_AFTER_ATTEMPT_FINALIZATION: Final = "attempt_finalization.after"
FAULT_BEFORE_ATTEMPT_COMPLETION: Final = "attempt_completion.before"
FAULT_AFTER_ATTEMPT_COMPLETION: Final = "attempt_completion.after"
FAULT_BEFORE_VALIDATION_RECORD: Final = "validation_record.before"
FAULT_AFTER_VALIDATION_RECORD: Final = "validation_record.after"
FAULT_BEFORE_JOB_FINALIZATION: Final = "job_finalization.before"
FAULT_AFTER_JOB_FINALIZATION: Final = "job_finalization.after"
FAULT_BEFORE_JOB_PUBLICATION: Final = "job_publication.before"
FAULT_AFTER_JOB_PUBLICATION: Final = "job_publication.after"
FAULT_BEFORE_GENERATION_PUBLICATION: Final = "generation_publication.before"
FAULT_AFTER_GENERATION_PUBLICATION: Final = "generation_publication.after"

_DIGEST_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_ABSOLUTE_RE: Final = re.compile(r"(?<![A-Za-z0-9/\\])[a-zA-Z]:[\\/]")
_UNC_RE: Final = re.compile(r"(?<![A-Za-z0-9/\\])\\\\[^\\\s]+\\")
_POSIX_ABSOLUTE_RE: Final = re.compile(r"(?<![A-Za-z0-9/\\])/(?!/)[^\s)\]}>;,]+")
_FILE_URI_RE: Final = re.compile(r"(?i)(?<![A-Za-z0-9+.-])file:(?:/+|\\\\+)")
_FORBIDDEN_KEYS: Final = frozenset(
    {
        "prompt",
        "promptbytes",
        "prompttext",
        "promptpayload",
        "rawprompt",
        "rawresponse",
        "responsebytes",
        "responsepayload",
        "rawrequest",
        "requestbytes",
        "requestpayload",
        "requestbody",
        "rawsource",
        "sourcebytes",
        "sourcepacket",
        "sourcepayload",
        "sourcecontent",
        "providerstderr",
        "stderr",
        "credential",
        "credentials",
        "apicredential",
        "apicredentials",
        "password",
        "secret",
        "accesstoken",
        "refreshtoken",
        "authorization",
    }
)


class StoryMapV2RepositoryError(storage.ProjectStorageError):
    """Base error for a rejected durable Story Map V2 operation."""


class LeaseConflictError(StoryMapV2RepositoryError):
    """A lease or attempt compare-and-swap precondition no longer holds."""


class ImmutableRecordConflictError(StoryMapV2RepositoryError):
    """An immutable identity was reused for different normalized bytes."""


class PublicationConflictError(StoryMapV2RepositoryError):
    """The generation pointer changed before publication."""


class RunStatus(StrEnum):
    PREPARED = "prepared"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    INDETERMINATE = "indeterminate"
    FAILED = "failed"


class JobStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    RESERVED = "reserved"
    SUBMITTING = "submitting"
    RETURNED = "returned"
    VALIDATED = "validated"
    CACHE_STORED = "cache_stored"
    FINALIZED = "finalized"
    PUBLISHED = "published"
    CACHED = "cached"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INDETERMINATE = "indeterminate"


class AttemptStatus(StrEnum):
    RESERVED = "reserved"
    TRANSMITTING = "transmitting"
    RETURNED = "returned"
    SUCCEEDED = "succeeded"
    NOT_TRANSMITTED = "not_transmitted"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INDETERMINATE = "indeterminate"


class TransmissionDisposition(StrEnum):
    NOT_STARTED = "not_started"
    DEFINITELY_NOT_TRANSMITTED = "definitely_not_transmitted"
    TRANSMITTED = "transmitted"
    INDETERMINATE = "indeterminate"


class GenerationKind(StrEnum):
    STRUCTURAL = "structural"
    CANDIDATE = "candidate"
    COMPLETE = "complete"


class JobResolution(StrEnum):
    ACCEPTED = "accepted"
    STRUCTURAL = "structural"
    RESUMABLE = "resumable"
    INDETERMINATE = "indeterminate"
    CANCELLED = "cancelled"


class ContinuationKind(StrEnum):
    MAPPING = "mapping"
    REPLACEMENT_REVIEW = "replacement_review"
    REFUSAL_FALLBACK = "refusal_fallback"
    COMPLETE = "complete"


@dataclass(frozen=True)
class PreparedPreviewDescriptor:
    preview_id: str
    plan_id: str
    authority_identity: str
    preview: object
    preview_identity: str

    def __post_init__(self) -> None:
        _identifier(self.preview_id, "preview_id")
        _identifier(self.plan_id, "plan_id")
        _digest(self.authority_identity, "authority_identity")
        preview_bytes = _durable_json(self.preview, "prepared preview")
        _matching_identity(preview_bytes, self.preview_identity, "preview_identity")


@dataclass(frozen=True)
class PreparedPreviewRecord:
    descriptor: PreparedPreviewDescriptor
    created_utc: str


@dataclass(frozen=True)
class RunApprovalDescriptor:
    approval_id: str
    run_id: str
    preview_id: str
    execution_identity: str
    approval: object
    approval_identity: str

    def __post_init__(self) -> None:
        _identifier(self.approval_id, "approval_id")
        _identifier(self.run_id, "run_id")
        _identifier(self.preview_id, "preview_id")
        _digest(self.execution_identity, "execution_identity")
        approval_bytes = _durable_json(self.approval, "run approval")
        _matching_identity(approval_bytes, self.approval_identity, "approval_identity")


@dataclass(frozen=True)
class RunApprovalRecord:
    descriptor: RunApprovalDescriptor
    created_utc: str


@dataclass(frozen=True)
class RetryApprovalDescriptor:
    retry_approval_id: str
    job_id: str
    attempt_ordinal: int
    approval: object
    approval_identity: str

    def __post_init__(self) -> None:
        _identifier(self.retry_approval_id, "retry_approval_id")
        _identifier(self.job_id, "job_id")
        if self.attempt_ordinal < 1:
            raise ValueError("attempt_ordinal must be positive")
        approval_bytes = _durable_json(self.approval, "retry approval")
        _matching_identity(approval_bytes, self.approval_identity, "approval_identity")


@dataclass(frozen=True)
class RetryApprovalRecord:
    descriptor: RetryApprovalDescriptor
    created_utc: str
    consumed_utc: str | None


@dataclass(frozen=True)
class AttemptReservationMetadata:
    call_kind: str
    provider_input_identity: str
    ceilings_identity: str

    def __post_init__(self) -> None:
        _identifier(self.call_kind, "call_kind")
        _digest(self.provider_input_identity, "provider_input_identity")
        _digest(self.ceilings_identity, "ceilings_identity")


@dataclass(frozen=True)
class AttemptReservationLimits:
    """Finite workflow limits enforced in the reservation transaction."""

    mapping_calls: int
    review_calls: int
    fallback_calls: int
    input_tokens: int
    output_tokens: int
    elapsed_ms: int
    indeterminate_retry_calls: int = 0

    def __post_init__(self) -> None:
        values = (
            self.mapping_calls,
            self.review_calls,
            self.fallback_calls,
            self.input_tokens,
            self.output_tokens,
            self.elapsed_ms,
            self.indeterminate_retry_calls,
        )
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("attempt reservation limits must be non-negative integers")


@dataclass(frozen=True)
class AttemptAccounting:
    calls: int
    input_tokens: int
    output_tokens: int
    elapsed_ms: int

    def __post_init__(self) -> None:
        values = (self.calls, self.input_tokens, self.output_tokens, self.elapsed_ms)
        if any(type(value) is not int for value in values):
            raise TypeError("attempt accounting fields must be integers")
        if min(self.calls, self.input_tokens, self.output_tokens, self.elapsed_ms) < 0:
            raise ValueError("attempt accounting cannot be negative")
        if self.calls not in {0, 1}:
            raise ValueError("attempt calls must be zero or one")


@dataclass(frozen=True)
class FrozenRunDescriptor:
    run_id: str
    plan_id: str
    authority_identity: str

    def __post_init__(self) -> None:
        _identifier(self.run_id, "run_id")
        _identifier(self.plan_id, "plan_id")
        _digest(self.authority_identity, "authority_identity")


@dataclass(frozen=True)
class FrozenJobDescriptor:
    run_id: str
    plan_id: str
    scope_id: str
    job_id: str
    chunk_id: str
    authority_identity: str
    serialized_request_identity: str
    cache_identity: str
    ordinal: int

    def __post_init__(self) -> None:
        for value, label in (
            (self.run_id, "run_id"),
            (self.plan_id, "plan_id"),
            (self.scope_id, "scope_id"),
            (self.job_id, "job_id"),
            (self.chunk_id, "chunk_id"),
        ):
            _identifier(value, label)
        for value, label in (
            (self.authority_identity, "authority_identity"),
            (self.serialized_request_identity, "serialized_request_identity"),
            (self.cache_identity, "cache_identity"),
        ):
            _digest(value, label)
        if self.ordinal < 0:
            raise ValueError("ordinal cannot be negative")


@dataclass(frozen=True)
class RunRecord:
    descriptor: FrozenRunDescriptor
    status: RunStatus
    cancel_requested: bool


@dataclass(frozen=True)
class JobRecord:
    descriptor: FrozenJobDescriptor
    status: JobStatus
    next_attempt_ordinal: int
    normalized_result_identity: str | None
    resolution: JobResolution | None
    continuation_kind: ContinuationKind
    continuation_attempt_id: str | None
    continuation_result_identity: str | None
    validated_cache_identity: str | None = None


@dataclass(frozen=True)
class JobClaim:
    descriptor: FrozenJobDescriptor
    lease_owner: str
    lease_token: str
    lease_expires_utc: str
    continuation_kind: ContinuationKind = ContinuationKind.MAPPING
    continuation_attempt_id: str | None = None
    continuation_result_identity: str | None = None


@dataclass(frozen=True)
class AttemptReservation:
    attempt_id: str
    job_id: str
    ordinal: int
    metadata: AttemptReservationMetadata
    status: AttemptStatus
    transmission_disposition: TransmissionDisposition
    reserved_utc: str
    retry_of_attempt_id: str | None = None
    uses_supplemental_retry_capacity: bool = False


@dataclass(frozen=True)
class AttemptRecord:
    reservation: AttemptReservation
    transmission_utc: str | None
    finalized_utc: str | None
    normalized_result_identity: str | None
    accounting: AttemptAccounting
    failure_kind: str | None
    sanitized_failure: str | None


@dataclass(frozen=True)
class NormalizedCacheEntry:
    cache_identity: str
    authority_identity: str
    serialized_request_identity: str
    normalized_result: object
    normalized_result_identity: str
    created_utc: str


@dataclass(frozen=True)
class GenerationDescriptor:
    generation_id: str
    run_id: str
    plan_id: str
    authority_identity: str
    kind: GenerationKind
    descriptor: object

    def __post_init__(self) -> None:
        for value, label in (
            (self.generation_id, "generation_id"),
            (self.run_id, "run_id"),
            (self.plan_id, "plan_id"),
        ):
            _identifier(value, label)
        _digest(self.authority_identity, "authority_identity")
        _durable_json(self.descriptor, "generation descriptor")


@dataclass(frozen=True)
class GenerationPointers:
    current_complete_generation: str | None
    active_build_generation: str | None
    map_revision: int


@dataclass(frozen=True)
class SectionPageRecord:
    generation_id: str
    section_id: str
    page_ordinal: int
    item_count: int
    page: object
    page_identity: str


@dataclass(frozen=True)
class SelectionIndexRecord:
    generation_id: str
    selection_id: str
    section_id: str
    page_ordinal: int
    item_ordinal: int
    selection_kind: str


@dataclass(frozen=True)
class ViewStateRecord:
    view_key: str
    generation_id: str | None
    map_revision: int
    selection_id: str | None
    section_id: str | None
    state: object
    state_identity: str


@dataclass(frozen=True)
class PublishedJobResult:
    run_id: str
    job_id: str
    result: object
    result_identity: str
    published_utc: str


@runtime_checkable
class StoryMapV2Repository(Protocol):
    """Durable repository over frozen scalar/dataclass identities."""

    def store_prepared_preview(
        self,
        preview: PreparedPreviewDescriptor,
        *,
        now: datetime | None = None,
    ) -> PreparedPreviewRecord: ...

    def load_prepared_preview(self, preview_id: str) -> PreparedPreviewRecord | None: ...

    def create_run(
        self,
        run: FrozenRunDescriptor,
        jobs: Sequence[FrozenJobDescriptor],
    ) -> None: ...

    def store_run_approval(
        self,
        approval: RunApprovalDescriptor,
        *,
        now: datetime | None = None,
    ) -> RunApprovalRecord: ...

    def load_run_approval(self, run_id: str) -> RunApprovalRecord | None: ...

    def store_retry_approval(
        self,
        approval: RetryApprovalDescriptor,
        *,
        now: datetime | None = None,
    ) -> RetryApprovalRecord: ...

    def load_retry_approval(
        self,
        job_id: str,
        attempt_ordinal: int,
    ) -> RetryApprovalRecord | None: ...

    def get_run(self, run_id: str) -> RunRecord | None: ...

    def get_job(self, job_id: str) -> JobRecord | None: ...

    def load_claim(self, job_id: str, lease_token: str) -> JobClaim | None: ...

    def list_jobs(self, run_id: str) -> tuple[JobRecord, ...]: ...

    def list_attempts(self, job_id: str) -> tuple[AttemptRecord, ...]: ...

    def global_active_claim_count(self, *, now: datetime | None = None) -> int: ...

    def claim_next_job(
        self,
        lease_owner: str,
        *,
        run_id: str | None = None,
        materialize_cache_hits: bool = True,
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> JobClaim | None: ...

    def reserve_attempt(
        self,
        claim: JobClaim,
        metadata: AttemptReservationMetadata,
        *,
        limits: AttemptReservationLimits | None = None,
        now: datetime | None = None,
        fault: FaultInjector | None = None,
    ) -> AttemptReservation: ...

    def renew_lease(
        self,
        claim: JobClaim,
        *,
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> JobClaim: ...

    def reclaim_job(
        self,
        job_id: str,
        lease_owner: str,
        *,
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> JobClaim: ...

    def mark_transmitting(
        self,
        claim: JobClaim,
        attempt: AttemptReservation,
        *,
        now: datetime | None = None,
    ) -> None: ...

    def complete_attempt(
        self,
        claim: JobClaim,
        attempt: AttemptReservation,
        *,
        disposition: TransmissionDisposition,
        accounting: AttemptAccounting,
        response_identity: str | None,
        failure_kind: str | None = None,
        sanitized_failure: str | None = None,
        defer_resumable: bool = False,
        now: datetime | None = None,
        fault: FaultInjector | None = None,
    ) -> AttemptRecord: ...

    def record_validated(
        self,
        job_id: str,
        attempt_id: str | None,
        normalized_result: object,
        *,
        cache_identity: str | None = None,
        now: datetime | None = None,
        fault: FaultInjector | None = None,
    ) -> JobRecord: ...

    def record_continuation(
        self,
        job_id: str,
        continuation: ContinuationKind,
        *,
        prior_attempt_id: str,
        prior_result_identity: str,
        now: datetime | None = None,
    ) -> JobRecord: ...

    def store_cache(
        self,
        job_id: str,
        *,
        cache_identity: str | None = None,
        now: datetime | None = None,
    ) -> NormalizedCacheEntry: ...

    def finalize_job(
        self,
        job_id: str,
        resolution: JobResolution,
        *,
        now: datetime | None = None,
        fault: FaultInjector | None = None,
    ) -> JobRecord: ...

    def defer_resumable_job(self, job_id: str, *, now: datetime | None = None) -> JobRecord: ...

    def activate_resumable_jobs(self, run_id: str, *, now: datetime | None = None) -> int: ...

    def publish_job(
        self,
        job_id: str,
        result: object,
        *,
        now: datetime | None = None,
        fault: FaultInjector | None = None,
    ) -> PublishedJobResult: ...

    def load_published_result(
        self,
        run_id: str,
        job_id: str,
    ) -> PublishedJobResult | None: ...

    def finalize_success(
        self,
        claim: JobClaim,
        attempt: AttemptReservation,
        normalized_result: object,
        accounting: AttemptAccounting,
        *,
        now: datetime | None = None,
        fault: FaultInjector | None = None,
    ) -> NormalizedCacheEntry: ...

    def finalize_not_transmitted(
        self,
        claim: JobClaim,
        attempt: AttemptReservation,
        sanitized_failure: str,
        *,
        now: datetime | None = None,
    ) -> None: ...

    def finalize_failure(
        self,
        claim: JobClaim,
        attempt: AttemptReservation,
        *,
        disposition: TransmissionDisposition,
        accounting: AttemptAccounting,
        failure_kind: str,
        sanitized_failure: str,
        now: datetime | None = None,
    ) -> None: ...

    def release_claim(
        self,
        claim: JobClaim,
        *,
        now: datetime | None = None,
    ) -> None: ...

    def cancel_run(self, run_id: str, *, now: datetime | None = None) -> None: ...

    def recover_expired_leases(self, *, now: datetime | None = None) -> int: ...

    def recover_run(self, run_id: str, *, now: datetime | None = None) -> int: ...

    def lookup_cache(self, cache_identity: str) -> NormalizedCacheEntry | None: ...

    def create_generation(
        self,
        generation: GenerationDescriptor,
        *,
        now: datetime | None = None,
    ) -> None: ...

    def set_active_generation(
        self,
        generation_id: str,
        *,
        expected_active_generation_id: str | None,
        now: datetime | None = None,
    ) -> GenerationPointers: ...

    def store_section_page(self, page: SectionPageRecord) -> None: ...

    def load_section_page(
        self,
        generation_id: str,
        section_id: str,
        page_ordinal: int,
    ) -> SectionPageRecord | None: ...

    def store_selection(self, selection: SelectionIndexRecord) -> None: ...

    def locate_selection(
        self,
        generation_id: str,
        selection_id: str,
    ) -> SelectionIndexRecord | None: ...

    def generation_pointers(self) -> GenerationPointers: ...

    def publish_generation(
        self,
        generation_id: str,
        *,
        expected_active_generation_id: str,
        now: datetime | None = None,
        fault: FaultInjector | None = None,
    ) -> GenerationPointers: ...

    def save_view_state(
        self,
        view_key: str,
        *,
        generation_id: str | None,
        map_revision: int,
        selection_id: str | None,
        section_id: str | None,
        state: object,
        now: datetime | None = None,
    ) -> ViewStateRecord: ...

    def load_view_state(self, view_key: str) -> ViewStateRecord | None: ...


class SqliteStoryMapV2Repository:
    """Transactional schema-v7 Story Map V2 repository."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        row = connection.execute("PRAGMA user_version").fetchone()
        if row is None or int(row[0]) != storage.SCHEMA_VERSION:
            raise StoryMapV2RepositoryError("Story Map V2 repository requires schema v7")

    @property
    def database_path(self) -> Path | None:
        """Return the backing file used to create independent worker connections."""

        row = self._connection.execute("PRAGMA database_list").fetchone()
        if row is None or not str(row[2]):
            return None
        return Path(str(row[2]))

    def store_prepared_preview(
        self,
        preview: PreparedPreviewDescriptor,
        *,
        now: datetime | None = None,
    ) -> PreparedPreviewRecord:
        preview_bytes = _durable_json(preview.preview, "prepared preview")
        timestamp = _timestamp(now)
        with storage.transaction(self._connection):
            existing = self._connection.execute(
                "SELECT * FROM story_map_v2_previews WHERE preview_id = ?",
                (preview.preview_id,),
            ).fetchone()
            expected = (
                preview.plan_id,
                preview.authority_identity,
                preview_bytes,
                preview.preview_identity,
            )
            if existing is not None:
                actual = (
                    str(existing["plan_id"]),
                    str(existing["authority_identity"]),
                    bytes(existing["preview_json"]),
                    str(existing["preview_identity"]),
                )
                if actual != expected:
                    raise ImmutableRecordConflictError("prepared preview identity is immutable")
                return PreparedPreviewRecord(preview, str(existing["created_utc"]))
            self._connection.execute(
                """INSERT INTO story_map_v2_previews(
                    preview_id, plan_id, authority_identity, preview_json,
                    preview_identity, created_utc
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    preview.preview_id,
                    preview.plan_id,
                    preview.authority_identity,
                    preview_bytes,
                    preview.preview_identity,
                    timestamp,
                ),
            )
        return PreparedPreviewRecord(preview, timestamp)

    def load_prepared_preview(self, preview_id: str) -> PreparedPreviewRecord | None:
        _identifier(preview_id, "preview_id")
        row = self._connection.execute(
            "SELECT * FROM story_map_v2_previews WHERE preview_id = ?", (preview_id,)
        ).fetchone()
        if row is None:
            return None
        descriptor = PreparedPreviewDescriptor(
            preview_id=str(row["preview_id"]),
            plan_id=str(row["plan_id"]),
            authority_identity=str(row["authority_identity"]),
            preview=storage.decode_json(row["preview_json"]),
            preview_identity=str(row["preview_identity"]),
        )
        return PreparedPreviewRecord(descriptor, str(row["created_utc"]))

    def create_run(
        self,
        run: FrozenRunDescriptor,
        jobs: Sequence[FrozenJobDescriptor],
    ) -> None:
        ordered = tuple(jobs)
        if len({job.job_id for job in ordered}) != len(ordered):
            raise ValueError("job_id values must be unique")
        if len({job.ordinal for job in ordered}) != len(ordered):
            raise ValueError("job ordinals must be unique")
        for job in ordered:
            if (
                job.run_id != run.run_id
                or job.plan_id != run.plan_id
                or job.authority_identity != run.authority_identity
            ):
                raise ValueError("every job must match its frozen run identity")
        timestamp = _timestamp(None)
        with storage.transaction(self._connection):
            self._connection.execute(
                """INSERT INTO story_map_v2_runs(
                    run_id, plan_id, authority_identity, status, cancel_requested,
                    created_utc, updated_utc
                ) VALUES (?, ?, ?, 'prepared', 0, ?, ?)""",
                (run.run_id, run.plan_id, run.authority_identity, timestamp, timestamp),
            )
            self._connection.executemany(
                """INSERT INTO story_map_v2_jobs(
                    job_id, run_id, plan_id, scope_id, chunk_id, authority_identity,
                    serialized_request_identity, cache_identity, ordinal, status,
                    lease_owner, lease_token, lease_expires_utc, next_attempt_ordinal,
                    validated_result_json, normalized_result_identity, continuation_kind,
                    continuation_attempt_id, continuation_result_identity, resolution, updated_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, NULL, NULL, 1,
                    NULL, NULL, 'mapping', NULL, NULL, NULL, ?)""",
                [
                    (
                        job.job_id,
                        job.run_id,
                        job.plan_id,
                        job.scope_id,
                        job.chunk_id,
                        job.authority_identity,
                        job.serialized_request_identity,
                        job.cache_identity,
                        job.ordinal,
                        timestamp,
                    )
                    for job in ordered
                ],
            )

    def store_run_approval(
        self,
        approval: RunApprovalDescriptor,
        *,
        now: datetime | None = None,
    ) -> RunApprovalRecord:
        approval_bytes = _durable_json(approval.approval, "run approval")
        timestamp = _timestamp(now)
        with storage.transaction(self._connection):
            run = self._connection.execute(
                "SELECT plan_id, authority_identity FROM story_map_v2_runs WHERE run_id = ?",
                (approval.run_id,),
            ).fetchone()
            preview = self._connection.execute(
                """SELECT plan_id, authority_identity FROM story_map_v2_previews
                   WHERE preview_id = ?""",
                (approval.preview_id,),
            ).fetchone()
            if run is None or preview is None:
                raise StoryMapV2RepositoryError("approval requires an existing run and preview")
            if (str(run["plan_id"]), str(run["authority_identity"])) != (
                str(preview["plan_id"]),
                str(preview["authority_identity"]),
            ):
                raise StoryMapV2RepositoryError("approval run and preview identities do not match")
            existing = self._connection.execute(
                """SELECT * FROM story_map_v2_run_approvals
                   WHERE approval_id = ? OR run_id = ?""",
                (approval.approval_id, approval.run_id),
            ).fetchone()
            expected = (
                approval.approval_id,
                approval.run_id,
                approval.preview_id,
                approval.execution_identity,
                approval_bytes,
                approval.approval_identity,
            )
            if existing is not None:
                actual = (
                    str(existing["approval_id"]),
                    str(existing["run_id"]),
                    str(existing["preview_id"]),
                    str(existing["execution_identity"]),
                    bytes(existing["approval_json"]),
                    str(existing["approval_identity"]),
                )
                if actual != expected:
                    raise ImmutableRecordConflictError("run approval identity is immutable")
                return RunApprovalRecord(approval, str(existing["created_utc"]))
            self._connection.execute(
                """INSERT INTO story_map_v2_run_approvals(
                    approval_id, run_id, preview_id, execution_identity,
                    approval_json, approval_identity, created_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (*expected[:4], approval_bytes, approval.approval_identity, timestamp),
            )
        return RunApprovalRecord(approval, timestamp)

    def load_run_approval(self, run_id: str) -> RunApprovalRecord | None:
        _identifier(run_id, "run_id")
        row = self._connection.execute(
            "SELECT * FROM story_map_v2_run_approvals WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        descriptor = RunApprovalDescriptor(
            approval_id=str(row["approval_id"]),
            run_id=str(row["run_id"]),
            preview_id=str(row["preview_id"]),
            execution_identity=str(row["execution_identity"]),
            approval=storage.decode_json(row["approval_json"]),
            approval_identity=str(row["approval_identity"]),
        )
        return RunApprovalRecord(descriptor, str(row["created_utc"]))

    def store_retry_approval(
        self,
        approval: RetryApprovalDescriptor,
        *,
        now: datetime | None = None,
    ) -> RetryApprovalRecord:
        approval_bytes = _durable_json(approval.approval, "retry approval")
        timestamp = _timestamp(now)
        with storage.transaction(self._connection):
            existing = self._connection.execute(
                """SELECT * FROM story_map_v2_retry_approvals
                   WHERE retry_approval_id = ? OR (job_id = ? AND attempt_ordinal = ?)""",
                (approval.retry_approval_id, approval.job_id, approval.attempt_ordinal),
            ).fetchone()
            if existing is not None:
                actual = (
                    str(existing["retry_approval_id"]),
                    str(existing["job_id"]),
                    int(existing["attempt_ordinal"]),
                    bytes(existing["approval_json"]),
                    str(existing["approval_identity"]),
                )
                expected = (
                    approval.retry_approval_id,
                    approval.job_id,
                    approval.attempt_ordinal,
                    approval_bytes,
                    approval.approval_identity,
                )
                if actual != expected:
                    raise ImmutableRecordConflictError("retry approval identity is immutable")
                return RetryApprovalRecord(
                    approval,
                    str(existing["created_utc"]),
                    _optional_text(existing["consumed_utc"]),
                )
            job_row = self._connection.execute(
                """SELECT jobs.run_id, jobs.status, runs.cancel_requested
                   FROM story_map_v2_jobs AS jobs
                   JOIN story_map_v2_runs AS runs ON runs.run_id = jobs.run_id
                   WHERE jobs.job_id = ?""",
                (approval.job_id,),
            ).fetchone()
            attempt = self._connection.execute(
                """SELECT ordinal, status FROM story_map_v2_attempts
                   WHERE job_id = ? ORDER BY ordinal DESC LIMIT 1""",
                (approval.job_id,),
            ).fetchone()
            if job_row is None or attempt is None:
                raise StoryMapV2RepositoryError("retry approval requires an indeterminate attempt")
            if (
                JobStatus(str(job_row["status"])) is not JobStatus.INDETERMINATE
                or bool(job_row["cancel_requested"])
                or int(attempt["ordinal"]) != approval.attempt_ordinal
                or AttemptStatus(str(attempt["status"])) is not AttemptStatus.INDETERMINATE
            ):
                raise StoryMapV2RepositoryError(
                    "retry approval does not match the current indeterminate attempt"
                )
            self._connection.execute(
                """INSERT INTO story_map_v2_retry_approvals(
                    retry_approval_id, job_id, attempt_ordinal, approval_json,
                    approval_identity, created_utc, consumed_utc
                ) VALUES (?, ?, ?, ?, ?, ?, NULL)""",
                (
                    approval.retry_approval_id,
                    approval.job_id,
                    approval.attempt_ordinal,
                    approval_bytes,
                    approval.approval_identity,
                    timestamp,
                ),
            )
            self._connection.execute(
                """UPDATE story_map_v2_jobs
                   SET status = 'pending', resolution = NULL, updated_utc = ? WHERE job_id = ?""",
                (timestamp, approval.job_id),
            )
            self._connection.execute(
                """UPDATE story_map_v2_runs
                   SET status = 'running', updated_utc = ? WHERE run_id = ?""",
                (timestamp, str(job_row["run_id"])),
            )
        return RetryApprovalRecord(approval, timestamp, None)

    def load_retry_approval(
        self,
        job_id: str,
        attempt_ordinal: int,
    ) -> RetryApprovalRecord | None:
        _identifier(job_id, "job_id")
        if attempt_ordinal < 1:
            raise ValueError("attempt_ordinal must be positive")
        row = self._connection.execute(
            """SELECT * FROM story_map_v2_retry_approvals
               WHERE job_id = ? AND attempt_ordinal = ?""",
            (job_id, attempt_ordinal),
        ).fetchone()
        if row is None:
            return None
        descriptor = RetryApprovalDescriptor(
            retry_approval_id=str(row["retry_approval_id"]),
            job_id=str(row["job_id"]),
            attempt_ordinal=int(row["attempt_ordinal"]),
            approval=storage.decode_json(row["approval_json"]),
            approval_identity=str(row["approval_identity"]),
        )
        return RetryApprovalRecord(
            descriptor,
            str(row["created_utc"]),
            _optional_text(row["consumed_utc"]),
        )

    def get_run(self, run_id: str) -> RunRecord | None:
        _identifier(run_id, "run_id")
        row = self._connection.execute(
            "SELECT * FROM story_map_v2_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        return RunRecord(
            descriptor=FrozenRunDescriptor(
                str(row["run_id"]),
                str(row["plan_id"]),
                str(row["authority_identity"]),
            ),
            status=RunStatus(str(row["status"])),
            cancel_requested=bool(row["cancel_requested"]),
        )

    def get_job(self, job_id: str) -> JobRecord | None:
        _identifier(job_id, "job_id")
        row = self._connection.execute(
            "SELECT * FROM story_map_v2_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return None if row is None else _job_record(row)

    def load_claim(self, job_id: str, lease_token: str) -> JobClaim | None:
        _identifier(job_id, "job_id")
        _identifier(lease_token, "lease_token")
        row = self._connection.execute(
            """SELECT * FROM story_map_v2_jobs
               WHERE job_id = ? AND lease_token = ? AND lease_owner IS NOT NULL
                 AND lease_expires_utc IS NOT NULL""",
            (job_id, lease_token),
        ).fetchone()
        if row is None:
            return None
        return _job_claim(
            row,
            str(row["lease_owner"]),
            lease_token,
            str(row["lease_expires_utc"]),
        )

    def list_jobs(self, run_id: str) -> tuple[JobRecord, ...]:
        _identifier(run_id, "run_id")
        rows = self._connection.execute(
            "SELECT * FROM story_map_v2_jobs WHERE run_id = ? ORDER BY ordinal, job_id",
            (run_id,),
        ).fetchall()
        return tuple(_job_record(row) for row in rows)

    def list_attempts(self, job_id: str) -> tuple[AttemptRecord, ...]:
        _identifier(job_id, "job_id")
        rows = self._connection.execute(
            "SELECT * FROM story_map_v2_attempts WHERE job_id = ? ORDER BY ordinal",
            (job_id,),
        ).fetchall()
        return tuple(_attempt_record(row) for row in rows)

    def global_active_claim_count(self, *, now: datetime | None = None) -> int:
        timestamp = _timestamp(now)
        row = self._connection.execute(
            """SELECT COUNT(*) FROM story_map_v2_jobs
               WHERE status IN ('claimed','reserved','submitting')
                 AND lease_expires_utc > ?""",
            (timestamp,),
        ).fetchone()
        assert row is not None
        return int(row[0])

    def claim_next_job(
        self,
        lease_owner: str,
        *,
        run_id: str | None = None,
        materialize_cache_hits: bool = True,
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> JobClaim | None:
        _identifier(lease_owner, "lease_owner")
        if run_id is not None:
            _identifier(run_id, "run_id")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        instant = _instant(now)
        timestamp = _timestamp(instant)
        expires = _timestamp(instant + timedelta(seconds=lease_seconds))
        with storage.transaction(self._connection):
            self._recover_expired_leases_locked(timestamp)
            if materialize_cache_hits:
                self._materialize_cache_hits_locked(timestamp)
            row = self._connection.execute(
                """SELECT COUNT(*) FROM story_map_v2_jobs
                   WHERE status IN ('claimed','reserved','submitting')
                     AND lease_expires_utc > ?""",
                (timestamp,),
            ).fetchone()
            assert row is not None
            if int(row[0]) >= GLOBAL_SUBMISSION_LIMIT:
                return None
            continuation = self._connection.execute(
                """SELECT jobs.* FROM story_map_v2_jobs AS jobs
                   JOIN story_map_v2_runs AS runs ON runs.run_id = jobs.run_id
                   JOIN story_map_v2_run_approvals AS approvals
                     ON approvals.run_id = jobs.run_id
                   WHERE jobs.status IN ('returned','validated')
                     AND jobs.continuation_kind IN ('replacement_review','refusal_fallback')
                     AND (jobs.lease_expires_utc IS NULL OR jobs.lease_expires_utc <= ?)
                     AND runs.cancel_requested = 0 AND runs.status IN ('running','indeterminate')
                     AND (? IS NULL OR jobs.run_id = ?)
                   ORDER BY runs.created_utc, jobs.ordinal, jobs.job_id
                   LIMIT 1""",
                (timestamp, run_id, run_id),
            ).fetchone()
            if continuation is not None:
                lease_token = uuid.uuid4().hex
                cursor = self._connection.execute(
                    """UPDATE story_map_v2_jobs
                       SET lease_owner = ?, lease_token = ?, lease_expires_utc = ?, updated_utc = ?
                       WHERE job_id = ? AND status IN ('returned','validated')
                         AND continuation_kind IN ('replacement_review','refusal_fallback')
                         AND (lease_expires_utc IS NULL OR lease_expires_utc <= ?)""",
                    (
                        lease_owner,
                        lease_token,
                        expires,
                        timestamp,
                        str(continuation["job_id"]),
                        timestamp,
                    ),
                )
                if cursor.rowcount != 1:
                    raise LeaseConflictError("continuation claim compare-and-swap failed")
                return _job_claim(continuation, lease_owner, lease_token, expires)
            candidate = self._connection.execute(
                """SELECT jobs.* FROM story_map_v2_jobs AS jobs
                   JOIN story_map_v2_runs AS runs ON runs.run_id = jobs.run_id
                   JOIN story_map_v2_run_approvals AS approvals
                     ON approvals.run_id = jobs.run_id
                   WHERE jobs.status = 'pending' AND runs.cancel_requested = 0
                     AND runs.status IN ('prepared','running')
                     AND (? IS NULL OR jobs.run_id = ?)
                   ORDER BY runs.created_utc, jobs.ordinal, jobs.job_id
                   LIMIT 1""",
                (run_id, run_id),
            ).fetchone()
            if candidate is None:
                return None
            lease_token = uuid.uuid4().hex
            cursor = self._connection.execute(
                """UPDATE story_map_v2_jobs
                   SET status = 'claimed', lease_owner = ?, lease_token = ?,
                       lease_expires_utc = ?, updated_utc = ?
                   WHERE job_id = ? AND status = 'pending' AND lease_token IS NULL""",
                (lease_owner, lease_token, expires, timestamp, str(candidate["job_id"])),
            )
            if cursor.rowcount != 1:
                raise LeaseConflictError("job claim compare-and-swap failed")
            self._connection.execute(
                """UPDATE story_map_v2_runs SET status = 'running', updated_utc = ?
                   WHERE run_id = ? AND status = 'prepared'""",
                (timestamp, str(candidate["run_id"])),
            )
            return _job_claim(candidate, lease_owner, lease_token, expires)

    def renew_lease(
        self,
        claim: JobClaim,
        *,
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> JobClaim:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        instant = _instant(now)
        expires = _timestamp(instant + timedelta(seconds=lease_seconds))
        timestamp = _timestamp(instant)
        with storage.transaction(self._connection):
            cursor = self._connection.execute(
                """UPDATE story_map_v2_jobs SET lease_expires_utc = ?, updated_utc = ?
                   WHERE job_id = ? AND lease_token = ? AND lease_owner = ?
                     AND status IN ('claimed','reserved','submitting','returned','validated')
                     AND lease_expires_utc > ?""",
                (
                    expires,
                    timestamp,
                    claim.descriptor.job_id,
                    claim.lease_token,
                    claim.lease_owner,
                    timestamp,
                ),
            )
            if cursor.rowcount != 1:
                raise LeaseConflictError("lease renewal compare-and-swap failed")
        return JobClaim(
            claim.descriptor,
            claim.lease_owner,
            claim.lease_token,
            expires,
            claim.continuation_kind,
            claim.continuation_attempt_id,
            claim.continuation_result_identity,
        )

    def reclaim_job(
        self,
        job_id: str,
        lease_owner: str,
        *,
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> JobClaim:
        _identifier(job_id, "job_id")
        _identifier(lease_owner, "lease_owner")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        instant = _instant(now)
        timestamp = _timestamp(instant)
        expires = _timestamp(instant + timedelta(seconds=lease_seconds))
        lease_token = uuid.uuid4().hex
        with storage.transaction(self._connection):
            row = self._connection.execute(
                """SELECT * FROM story_map_v2_jobs
                   WHERE job_id = ? AND status IN ('returned','validated')
                     AND (lease_expires_utc IS NULL OR lease_expires_utc <= ?)""",
                (job_id, timestamp),
            ).fetchone()
            if row is None:
                raise LeaseConflictError("returned job is not reclaimable")
            cursor = self._connection.execute(
                """UPDATE story_map_v2_jobs
                   SET lease_owner = ?, lease_token = ?, lease_expires_utc = ?, updated_utc = ?
                   WHERE job_id = ? AND status IN ('returned','validated')
                     AND (lease_expires_utc IS NULL OR lease_expires_utc <= ?)""",
                (lease_owner, lease_token, expires, timestamp, job_id, timestamp),
            )
            if cursor.rowcount != 1:
                raise LeaseConflictError("returned-job reclaim compare-and-swap failed")
        return _job_claim(row, lease_owner, lease_token, expires)

    def reserve_attempt(
        self,
        claim: JobClaim,
        metadata: AttemptReservationMetadata,
        *,
        limits: AttemptReservationLimits | None = None,
        now: datetime | None = None,
        fault: FaultInjector | None = None,
    ) -> AttemptReservation:
        _inject(fault, FAULT_BEFORE_ATTEMPT_RESERVATION)
        timestamp = _timestamp(now)
        attempt_id = uuid.uuid4().hex
        with storage.transaction(self._connection):
            row = self._assert_claim_locked(
                claim,
                timestamp,
                (JobStatus.CLAIMED, JobStatus.RETURNED, JobStatus.VALIDATED),
            )
            if bool(row["cancel_requested"]):
                raise LeaseConflictError("run was cancelled before attempt reservation")
            ordinal = int(row["next_attempt_ordinal"])
            retry_of_attempt_id = self._validate_attempt_policy_locked(
                claim.descriptor.job_id,
                ordinal,
                metadata,
                timestamp,
            )
            uses_supplemental = False
            if limits is not None:
                uses_supplemental = self._validate_attempt_limits_locked(
                    claim.descriptor.run_id,
                    claim.descriptor.job_id,
                    metadata.call_kind,
                    retry_of_attempt_id,
                    limits,
                )
            if JobStatus(str(row["status"])) is not JobStatus.CLAIMED:
                active_row = self._connection.execute(
                    """SELECT COUNT(*) FROM story_map_v2_jobs
                       WHERE status IN ('claimed','reserved','submitting')
                         AND lease_expires_utc > ?""",
                    (timestamp,),
                ).fetchone()
                assert active_row is not None
                if int(active_row[0]) >= GLOBAL_SUBMISSION_LIMIT:
                    raise LeaseConflictError("global submission slots are full")
            self._connection.execute(
                """INSERT INTO story_map_v2_attempts(
                    attempt_id, job_id, ordinal, call_kind, provider_input_identity,
                    ceilings_identity, retry_of_attempt_id,
                    uses_supplemental_retry_capacity, status,
                    transmission_disposition, reserved_utc,
                    transmission_utc, finalized_utc, normalized_result_identity,
                    calls, input_tokens, output_tokens, elapsed_ms, failure_kind,
                    sanitized_failure
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reserved', 'not_started', ?, NULL, NULL, NULL,
                    0, 0, 0, 0, NULL, NULL)""",
                (
                    attempt_id,
                    claim.descriptor.job_id,
                    ordinal,
                    metadata.call_kind,
                    metadata.provider_input_identity,
                    metadata.ceilings_identity,
                    retry_of_attempt_id,
                    int(uses_supplemental),
                    timestamp,
                ),
            )
            cursor = self._connection.execute(
                """UPDATE story_map_v2_jobs
                   SET status = 'reserved', next_attempt_ordinal = ?, updated_utc = ?
                   WHERE job_id = ? AND lease_token = ?
                     AND status IN ('claimed','returned','validated')""",
                (ordinal + 1, timestamp, claim.descriptor.job_id, claim.lease_token),
            )
            if cursor.rowcount != 1:
                raise LeaseConflictError("attempt reservation compare-and-swap failed")
        reservation = AttemptReservation(
            attempt_id,
            claim.descriptor.job_id,
            ordinal,
            metadata,
            AttemptStatus.RESERVED,
            TransmissionDisposition.NOT_STARTED,
            timestamp,
            retry_of_attempt_id,
            uses_supplemental,
        )
        _inject(fault, FAULT_AFTER_ATTEMPT_RESERVATION)
        return reservation

    def mark_transmitting(
        self,
        claim: JobClaim,
        attempt: AttemptReservation,
        *,
        now: datetime | None = None,
    ) -> None:
        timestamp = _timestamp(now)
        with storage.transaction(self._connection):
            row = self._assert_claim_locked(claim, timestamp, (JobStatus.RESERVED,))
            if bool(row["cancel_requested"]):
                raise LeaseConflictError("run was cancelled before transmission")
            cursor = self._connection.execute(
                """UPDATE story_map_v2_attempts
                   SET status = 'transmitting', transmission_disposition = 'indeterminate',
                       transmission_utc = ?
                   WHERE attempt_id = ? AND job_id = ? AND status = 'reserved'""",
                (timestamp, attempt.attempt_id, claim.descriptor.job_id),
            )
            if cursor.rowcount != 1:
                raise LeaseConflictError("attempt transmission compare-and-swap failed")
            self._connection.execute(
                """UPDATE story_map_v2_jobs SET status = 'submitting', updated_utc = ?
                   WHERE job_id = ? AND lease_token = ?""",
                (timestamp, claim.descriptor.job_id, claim.lease_token),
            )

    def complete_attempt(
        self,
        claim: JobClaim,
        attempt: AttemptReservation,
        *,
        disposition: TransmissionDisposition,
        accounting: AttemptAccounting,
        response_identity: str | None,
        failure_kind: str | None = None,
        sanitized_failure: str | None = None,
        defer_resumable: bool = False,
        now: datetime | None = None,
        fault: FaultInjector | None = None,
    ) -> AttemptRecord:
        if disposition is TransmissionDisposition.NOT_STARTED:
            raise ValueError("completed attempt needs a transmission disposition")
        if disposition is TransmissionDisposition.TRANSMITTED and accounting.calls != 1:
            raise ValueError("transmitted attempt must account for one call")
        if (
            disposition is TransmissionDisposition.DEFINITELY_NOT_TRANSMITTED
            and accounting.calls != 0
        ):
            raise ValueError("definite non-transmission must account for zero calls")
        if response_identity is not None:
            _digest(response_identity, "response_identity")
        if (
            disposition is TransmissionDisposition.TRANSMITTED
            and response_identity is None
            and failure_kind is None
        ):
            raise ValueError("transmitted failure requires a failure_kind")
        if (
            disposition is TransmissionDisposition.DEFINITELY_NOT_TRANSMITTED
            and response_identity is not None
        ):
            raise ValueError("definite non-transmission cannot include a response")
        failure = None if sanitized_failure is None else _sanitized_failure(sanitized_failure)
        if failure_kind is not None:
            _identifier(failure_kind, "failure_kind")
        if (failure_kind is None) != (failure is None):
            raise ValueError("failure_kind and sanitized_failure must be recorded together")
        timestamp = _timestamp(now)
        _inject(fault, FAULT_BEFORE_ATTEMPT_COMPLETION)
        with storage.transaction(self._connection):
            job_row = self._assert_claim_locked(
                claim,
                timestamp,
                (JobStatus.RESERVED, JobStatus.SUBMITTING),
            )
            attempt_row = self._connection.execute(
                """SELECT status FROM story_map_v2_attempts
                   WHERE attempt_id = ? AND job_id = ?""",
                (attempt.attempt_id, claim.descriptor.job_id),
            ).fetchone()
            if attempt_row is None:
                raise LeaseConflictError("attempt is no longer completable")
            current_pair = (
                JobStatus(str(job_row["status"])),
                AttemptStatus(str(attempt_row["status"])),
            )
            allowed_pairs = {(JobStatus.SUBMITTING, AttemptStatus.TRANSMITTING)}
            if disposition is TransmissionDisposition.DEFINITELY_NOT_TRANSMITTED:
                allowed_pairs.add((JobStatus.RESERVED, AttemptStatus.RESERVED))
            if current_pair not in allowed_pairs:
                raise LeaseConflictError(
                    "attempt must be transmitting before possible transmission completion"
                )
            required_attempt_status = current_pair[1]
            if disposition is TransmissionDisposition.TRANSMITTED and response_identity is not None:
                attempt_status = AttemptStatus.RETURNED
            elif disposition is TransmissionDisposition.DEFINITELY_NOT_TRANSMITTED:
                attempt_status = AttemptStatus.NOT_TRANSMITTED
            elif disposition is TransmissionDisposition.INDETERMINATE:
                attempt_status = AttemptStatus.INDETERMINATE
            else:
                attempt_status = AttemptStatus.FAILED
            cursor = self._connection.execute(
                """UPDATE story_map_v2_attempts
                   SET status = ?, transmission_disposition = ?, finalized_utc = ?,
                       response_identity = ?, calls = ?, input_tokens = ?, output_tokens = ?,
                       elapsed_ms = ?, failure_kind = ?, sanitized_failure = ?
                   WHERE attempt_id = ? AND job_id = ?
                     AND status = ?""",
                (
                    attempt_status,
                    disposition,
                    timestamp,
                    response_identity,
                    accounting.calls,
                    accounting.input_tokens,
                    accounting.output_tokens,
                    accounting.elapsed_ms,
                    failure_kind,
                    failure,
                    attempt.attempt_id,
                    claim.descriptor.job_id,
                    required_attempt_status,
                ),
            )
            if cursor.rowcount != 1:
                raise LeaseConflictError("attempt is no longer completable")
            if bool(job_row["cancel_requested"]):
                job_status = JobStatus.CANCELLED
            elif disposition is TransmissionDisposition.DEFINITELY_NOT_TRANSMITTED:
                job_status = (
                    JobStatus.FINALIZED if defer_resumable else JobStatus.PENDING
                )
            elif disposition is TransmissionDisposition.INDETERMINATE:
                job_status = JobStatus.INDETERMINATE
            else:
                job_status = JobStatus.RETURNED
            if job_status in {
                JobStatus.PENDING,
                JobStatus.FINALIZED,
                JobStatus.INDETERMINATE,
                JobStatus.CANCELLED,
            }:
                self._connection.execute(
                    """UPDATE story_map_v2_jobs
                       SET status = ?, lease_owner = NULL, lease_token = NULL,
                           lease_expires_utc = NULL, resolution = ?, updated_utc = ?
                       WHERE job_id = ? AND lease_token = ?""",
                    (
                        job_status,
                        (
                            JobResolution.RESUMABLE
                            if defer_resumable and job_status is JobStatus.FINALIZED
                            else None
                        ),
                        timestamp,
                        claim.descriptor.job_id,
                        claim.lease_token,
                    ),
                )
                self._refresh_run_state_locked(claim.descriptor.run_id, timestamp)
            else:
                self._connection.execute(
                    """UPDATE story_map_v2_jobs SET status = 'returned', updated_utc = ?
                       WHERE job_id = ? AND lease_token = ?""",
                    (timestamp, claim.descriptor.job_id, claim.lease_token),
                )
            row = self._connection.execute(
                "SELECT * FROM story_map_v2_attempts WHERE attempt_id = ?",
                (attempt.attempt_id,),
            ).fetchone()
            assert row is not None
            record = _attempt_record(row)
        _inject(fault, FAULT_AFTER_ATTEMPT_COMPLETION)
        return record

    def record_validated(
        self,
        job_id: str,
        attempt_id: str | None,
        normalized_result: object,
        *,
        cache_identity: str | None = None,
        now: datetime | None = None,
        fault: FaultInjector | None = None,
    ) -> JobRecord:
        _identifier(job_id, "job_id")
        if attempt_id is not None:
            _identifier(attempt_id, "attempt_id")
        if cache_identity is not None:
            _digest(cache_identity, "cache_identity")
        result_bytes = _durable_json(normalized_result, "normalized result")
        result_identity = hashlib.sha256(result_bytes).hexdigest()
        timestamp = _timestamp(now)
        _inject(fault, FAULT_BEFORE_VALIDATION_RECORD)
        with storage.transaction(self._connection):
            job = self._connection.execute(
                """SELECT jobs.*, runs.cancel_requested
                   FROM story_map_v2_jobs AS jobs
                   JOIN story_map_v2_runs AS runs ON runs.run_id = jobs.run_id
                   WHERE jobs.job_id = ?""",
                (job_id,),
            ).fetchone()
            if job is None:
                raise StoryMapV2RepositoryError("unknown job_id")
            stored_cache_identity = _optional_text(job["validated_cache_identity"])
            if (
                stored_cache_identity is not None
                and cache_identity is not None
                and stored_cache_identity != cache_identity
            ):
                raise ImmutableRecordConflictError(
                    "validated job cache identity is immutable"
                )
            if (
                bool(job["cancel_requested"])
                or JobStatus(str(job["status"])) is JobStatus.CANCELLED
            ):
                raise StoryMapV2RepositoryError("cancelled job cannot record a validated result")
            if attempt_id is None:
                if JobStatus(str(job["status"])) not in {
                    JobStatus.CLAIMED,
                    JobStatus.VALIDATED,
                }:
                    raise StoryMapV2RepositoryError(
                        "cached validation requires a currently claimed job"
                    )
            else:
                attempt = self._connection.execute(
                    """SELECT status, ordinal FROM story_map_v2_attempts
                       WHERE attempt_id = ? AND job_id = ?""",
                    (attempt_id, job_id),
                ).fetchone()
                latest = self._connection.execute(
                    """SELECT attempt_id FROM story_map_v2_attempts
                       WHERE job_id = ? ORDER BY ordinal DESC LIMIT 1""",
                    (job_id,),
                ).fetchone()
                if (
                    attempt is None
                    or AttemptStatus(str(attempt["status"])) is not AttemptStatus.RETURNED
                    or latest is None
                    or str(latest["attempt_id"]) != attempt_id
                ):
                    raise StoryMapV2RepositoryError(
                        "only the latest returned attempt can be validated"
                    )
                existing = self._connection.execute(
                    "SELECT * FROM story_map_v2_validated_results WHERE attempt_id = ?",
                    (attempt_id,),
                ).fetchone()
                if existing is not None:
                    actual = (
                        bytes(existing["result_json"]),
                        str(existing["result_identity"]),
                    )
                    if actual != (result_bytes, result_identity):
                        raise ImmutableRecordConflictError(
                            "validated attempt result is immutable"
                        )
                else:
                    self._connection.execute(
                        """INSERT INTO story_map_v2_validated_results(
                            attempt_id, job_id, result_json, result_identity, validated_utc
                        ) VALUES (?, ?, ?, ?, ?)""",
                        (attempt_id, job_id, result_bytes, result_identity, timestamp),
                    )
            self._connection.execute(
                """UPDATE story_map_v2_jobs
                   SET status = 'validated', validated_result_json = ?,
                       normalized_result_identity = ?, validated_cache_identity = ?,
                       updated_utc = ?
                   WHERE job_id = ? AND status IN ('claimed','returned','validated')""",
                (
                    result_bytes,
                    result_identity,
                    cache_identity or stored_cache_identity,
                    timestamp,
                    job_id,
                ),
            )
            row = self._connection.execute(
                "SELECT * FROM story_map_v2_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            assert row is not None
            record = _job_record(row)
        _inject(fault, FAULT_AFTER_VALIDATION_RECORD)
        return record

    def record_continuation(
        self,
        job_id: str,
        continuation: ContinuationKind,
        *,
        prior_attempt_id: str,
        prior_result_identity: str,
        now: datetime | None = None,
    ) -> JobRecord:
        _identifier(job_id, "job_id")
        _identifier(prior_attempt_id, "prior_attempt_id")
        _digest(prior_result_identity, "prior_result_identity")
        if continuation is ContinuationKind.MAPPING:
            raise ValueError("mapping is the initial continuation and cannot be re-recorded")
        timestamp = _timestamp(now)
        with storage.transaction(self._connection):
            row = self._connection.execute(
                """SELECT jobs.*, runs.cancel_requested
                   FROM story_map_v2_jobs AS jobs
                   JOIN story_map_v2_runs AS runs ON runs.run_id = jobs.run_id
                   WHERE jobs.job_id = ?""",
                (job_id,),
            ).fetchone()
            attempt = self._connection.execute(
                """SELECT * FROM story_map_v2_attempts
                   WHERE attempt_id = ? AND job_id = ?""",
                (prior_attempt_id, job_id),
            ).fetchone()
            if row is None or attempt is None:
                raise StoryMapV2RepositoryError("continuation requires an existing job attempt")
            if bool(row["cancel_requested"]):
                raise StoryMapV2RepositoryError("cancelled job cannot record a continuation")
            if JobStatus(str(row["status"])) not in {JobStatus.RETURNED, JobStatus.VALIDATED}:
                raise StoryMapV2RepositoryError("job is not at a continuation checkpoint")
            latest = self._connection.execute(
                """SELECT attempt_id FROM story_map_v2_attempts
                   WHERE job_id = ? ORDER BY ordinal DESC LIMIT 1""",
                (job_id,),
            ).fetchone()
            if latest is None or str(latest["attempt_id"]) != prior_attempt_id:
                raise StoryMapV2RepositoryError("continuation must bind the latest attempt")
            validated = self._connection.execute(
                """SELECT result_identity FROM story_map_v2_validated_results
                   WHERE attempt_id = ?""",
                (prior_attempt_id,),
            ).fetchone()
            known_identities = {
                value
                for value in (
                    _optional_text(attempt["response_identity"]),
                    None if validated is None else str(validated["result_identity"]),
                )
                if value is not None
            }
            if prior_result_identity not in known_identities:
                raise StoryMapV2RepositoryError("continuation prior result identity does not match")
            current = ContinuationKind(str(row["continuation_kind"]))
            current_attempt_id = _optional_text(row["continuation_attempt_id"])
            current_result_identity = _optional_text(row["continuation_result_identity"])
            if current is ContinuationKind.COMPLETE:
                if (
                    continuation is current
                    and current_attempt_id == prior_attempt_id
                    and current_result_identity == prior_result_identity
                ):
                    return _job_record(row)
                raise ImmutableRecordConflictError("completed continuation is immutable")
            if current in {
                ContinuationKind.REPLACEMENT_REVIEW,
                ContinuationKind.REFUSAL_FALLBACK,
            }:
                if continuation is current:
                    if (
                        current_attempt_id == prior_attempt_id
                        and current_result_identity == prior_result_identity
                    ):
                        return _job_record(row)
                    raise ImmutableRecordConflictError("continuation identity is immutable")
                if continuation is not ContinuationKind.COMPLETE:
                    raise ImmutableRecordConflictError("continuation kind is immutable")
            if continuation in {
                ContinuationKind.REPLACEMENT_REVIEW,
                ContinuationKind.REFUSAL_FALLBACK,
            }:
                if int(attempt["ordinal"]) != 1 or str(attempt["call_kind"]) != "mapping":
                    raise StoryMapV2RepositoryError(
                        "review or fallback continuation requires the primary mapping attempt"
                    )
                if int(row["next_attempt_ordinal"]) != 2:
                    raise StoryMapV2RepositoryError("continuation attempt was already reserved")
            self._connection.execute(
                """UPDATE story_map_v2_jobs
                   SET continuation_kind = ?, continuation_attempt_id = ?,
                       continuation_result_identity = ?, updated_utc = ?
                   WHERE job_id = ?""",
                (
                    continuation,
                    prior_attempt_id,
                    prior_result_identity,
                    timestamp,
                    job_id,
                ),
            )
            updated = self._connection.execute(
                "SELECT * FROM story_map_v2_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            assert updated is not None
            return _job_record(updated)

    def store_cache(
        self,
        job_id: str,
        *,
        cache_identity: str | None = None,
        now: datetime | None = None,
    ) -> NormalizedCacheEntry:
        _identifier(job_id, "job_id")
        timestamp = _timestamp(now)
        with storage.transaction(self._connection):
            row = self._connection.execute(
                """SELECT jobs.*, runs.cancel_requested
                   FROM story_map_v2_jobs AS jobs
                   JOIN story_map_v2_runs AS runs ON runs.run_id = jobs.run_id
                   WHERE jobs.job_id = ?""",
                (job_id,),
            ).fetchone()
            if row is not None and bool(row["cancel_requested"]):
                raise StoryMapV2RepositoryError("cancelled job cannot store a cache result")
            if row is None or str(row["status"]) not in {
                JobStatus.VALIDATED,
                JobStatus.CACHE_STORED,
            }:
                raise StoryMapV2RepositoryError("job has no validated result to cache")
            result_blob = row["validated_result_json"]
            result_identity = _optional_text(row["normalized_result_identity"])
            if result_blob is None or result_identity is None:
                raise storage.ProjectCorruptError("validated job is missing normalized result")
            descriptor = _job_descriptor(row)
            stored_cache_identity = _optional_text(row["validated_cache_identity"])
            if (
                cache_identity is not None
                and stored_cache_identity is not None
                and cache_identity != stored_cache_identity
            ):
                raise ImmutableRecordConflictError(
                    "cache write does not match the validated job identity"
                )
            cache_identity = cache_identity or stored_cache_identity
            if cache_identity is not None:
                _digest(cache_identity, "cache_identity")
                descriptor = FrozenJobDescriptor(
                    descriptor.run_id,
                    descriptor.plan_id,
                    descriptor.scope_id,
                    descriptor.job_id,
                    descriptor.chunk_id,
                    descriptor.authority_identity,
                    descriptor.serialized_request_identity,
                    cache_identity,
                    descriptor.ordinal,
                )
            self._insert_immutable_cache_locked(
                descriptor,
                bytes(result_blob),
                result_identity,
                timestamp,
            )
            self._connection.execute(
                """UPDATE story_map_v2_jobs SET status = 'cache_stored', updated_utc = ?
                   WHERE job_id = ?""",
                (timestamp, job_id),
            )
        return NormalizedCacheEntry(
            descriptor.cache_identity,
            descriptor.authority_identity,
            descriptor.serialized_request_identity,
            storage.decode_json(result_blob),
            result_identity,
            timestamp,
        )

    def finalize_job(
        self,
        job_id: str,
        resolution: JobResolution,
        *,
        now: datetime | None = None,
        fault: FaultInjector | None = None,
    ) -> JobRecord:
        _identifier(job_id, "job_id")
        timestamp = _timestamp(now)
        _inject(fault, FAULT_BEFORE_JOB_FINALIZATION)
        with storage.transaction(self._connection):
            row = self._connection.execute(
                """SELECT jobs.*, runs.cancel_requested
                   FROM story_map_v2_jobs AS jobs
                   JOIN story_map_v2_runs AS runs ON runs.run_id = jobs.run_id
                   WHERE jobs.job_id = ?""",
                (job_id,),
            ).fetchone()
            if row is None:
                raise StoryMapV2RepositoryError("unknown job_id")
            if bool(row["cancel_requested"]) and resolution is not JobResolution.CANCELLED:
                raise StoryMapV2RepositoryError(
                    "cancelled run cannot finalize a non-cancelled job result"
                )
            status = JobStatus(str(row["status"]))
            allowed = {
                JobStatus.CLAIMED,
                JobStatus.RETURNED,
                JobStatus.VALIDATED,
                JobStatus.CACHE_STORED,
                JobStatus.INDETERMINATE,
            }
            if (
                status
                in {
                    JobStatus.FINALIZED,
                    JobStatus.INDETERMINATE,
                    JobStatus.CANCELLED,
                }
                and str(row["resolution"]) == resolution
            ):
                return _job_record(row)
            if status is JobStatus.CANCELLED and resolution is JobResolution.CANCELLED:
                self._connection.execute(
                    """UPDATE story_map_v2_jobs SET resolution = ?, updated_utc = ?
                       WHERE job_id = ?""",
                    (resolution, timestamp, job_id),
                )
                self._refresh_run_state_locked(str(row["run_id"]), timestamp)
                updated = self._connection.execute(
                    "SELECT * FROM story_map_v2_jobs WHERE job_id = ?", (job_id,)
                ).fetchone()
                assert updated is not None
                return _job_record(updated)
            if status not in allowed:
                raise StoryMapV2RepositoryError("job is not ready for finalization")
            if status is JobStatus.INDETERMINATE and resolution is not JobResolution.INDETERMINATE:
                raise StoryMapV2RepositoryError(
                    "indeterminate job requires indeterminate finalization"
                )
            if status is JobStatus.CLAIMED and resolution not in {
                JobResolution.STRUCTURAL,
                JobResolution.CANCELLED,
            }:
                raise StoryMapV2RepositoryError(
                    "an unattempted claimed job permits only structural or cancelled finalization"
                )
            if resolution is JobResolution.ACCEPTED and status is not JobStatus.CACHE_STORED:
                raise StoryMapV2RepositoryError("accepted job must store its validated cache first")
            if resolution is JobResolution.INDETERMINATE:
                attempt_row = self._connection.execute(
                    """SELECT transmission_disposition FROM story_map_v2_attempts
                       WHERE job_id = ? ORDER BY ordinal DESC LIMIT 1""",
                    (job_id,),
                ).fetchone()
                if (
                    attempt_row is None
                    or TransmissionDisposition(str(attempt_row[0]))
                    is not TransmissionDisposition.INDETERMINATE
                ):
                    raise StoryMapV2RepositoryError(
                        "indeterminate resolution requires an indeterminate attempt"
                    )
            finalized_status = (
                JobStatus.INDETERMINATE
                if resolution is JobResolution.INDETERMINATE
                else (
                    JobStatus.CANCELLED
                    if resolution is JobResolution.CANCELLED
                    else JobStatus.FINALIZED
                )
            )
            self._connection.execute(
                """UPDATE story_map_v2_jobs
                   SET status = ?, resolution = ?, lease_owner = NULL,
                       lease_token = NULL, lease_expires_utc = NULL, updated_utc = ?
                   WHERE job_id = ?""",
                (finalized_status, resolution, timestamp, job_id),
            )
            self._refresh_run_state_locked(str(row["run_id"]), timestamp)
            finalized = self._connection.execute(
                "SELECT * FROM story_map_v2_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            assert finalized is not None
            record = _job_record(finalized)
        _inject(fault, FAULT_AFTER_JOB_FINALIZATION)
        return record

    def defer_resumable_job(
        self, job_id: str, *, now: datetime | None = None
    ) -> JobRecord:
        _identifier(job_id, "job_id")
        timestamp = _timestamp(now)
        with storage.transaction(self._connection):
            row = self._connection.execute(
                "SELECT * FROM story_map_v2_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            latest = self._connection.execute(
                """SELECT transmission_disposition FROM story_map_v2_attempts
                   WHERE job_id = ? ORDER BY ordinal DESC LIMIT 1""",
                (job_id,),
            ).fetchone()
            if row is None or latest is None:
                raise StoryMapV2RepositoryError("resumable job requires an attempt")
            if (
                JobStatus(str(row["status"])) is not JobStatus.PENDING
                or TransmissionDisposition(str(latest[0]))
                is not TransmissionDisposition.DEFINITELY_NOT_TRANSMITTED
            ):
                raise StoryMapV2RepositoryError("job is not definitely resumable")
            self._connection.execute(
                """UPDATE story_map_v2_jobs
                   SET status = 'finalized', resolution = 'resumable', updated_utc = ?
                   WHERE job_id = ?""",
                (timestamp, job_id),
            )
            self._refresh_run_state_locked(str(row["run_id"]), timestamp)
            updated = self._connection.execute(
                "SELECT * FROM story_map_v2_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            assert updated is not None
            return _job_record(updated)

    def activate_resumable_jobs(
        self, run_id: str, *, now: datetime | None = None
    ) -> int:
        _identifier(run_id, "run_id")
        timestamp = _timestamp(now)
        with storage.transaction(self._connection):
            cursor = self._connection.execute(
                """UPDATE story_map_v2_jobs
                   SET status = 'pending', resolution = NULL, updated_utc = ?
                   WHERE run_id = ? AND status = 'finalized' AND resolution = 'resumable'""",
                (timestamp, run_id),
            )
            self._refresh_run_state_locked(run_id, timestamp)
            return cursor.rowcount

    def publish_job(
        self,
        job_id: str,
        result: object,
        *,
        now: datetime | None = None,
        fault: FaultInjector | None = None,
    ) -> PublishedJobResult:
        _identifier(job_id, "job_id")
        result_bytes = _durable_json(result, "published result")
        result_identity = hashlib.sha256(result_bytes).hexdigest()
        timestamp = _timestamp(now)
        _inject(fault, FAULT_BEFORE_JOB_PUBLICATION)
        with storage.transaction(self._connection):
            job_row = self._connection.execute(
                """SELECT jobs.run_id, jobs.status, jobs.resolution,
                          jobs.normalized_result_identity, runs.cancel_requested
                   FROM story_map_v2_jobs AS jobs
                   JOIN story_map_v2_runs AS runs ON runs.run_id = jobs.run_id
                   WHERE jobs.job_id = ?""",
                (job_id,),
            ).fetchone()
            if job_row is None:
                raise StoryMapV2RepositoryError("unknown job_id")
            if bool(job_row["cancel_requested"]):
                raise StoryMapV2RepositoryError("cancelled run cannot publish a job result")
            if str(job_row["status"]) not in {JobStatus.FINALIZED, JobStatus.PUBLISHED} or str(
                job_row["resolution"]
            ) not in {JobResolution.ACCEPTED, JobResolution.STRUCTURAL}:
                raise StoryMapV2RepositoryError("job is not publishable")
            if (
                str(job_row["resolution"]) == JobResolution.ACCEPTED
                and str(job_row["normalized_result_identity"]) != result_identity
            ):
                raise PublicationConflictError(
                    "accepted publication must match the cached normalized result"
                )
            run_id = str(job_row["run_id"])
            existing = self._connection.execute(
                "SELECT * FROM story_map_v2_published_results WHERE job_id = ?", (job_id,)
            ).fetchone()
            if existing is not None:
                actual = (bytes(existing["result_json"]), str(existing["result_identity"]))
                if actual != (result_bytes, result_identity):
                    raise ImmutableRecordConflictError("published job result is immutable")
                published_utc = str(existing["published_utc"])
            else:
                self._connection.execute(
                    """INSERT INTO story_map_v2_published_results(
                        job_id, run_id, result_json, result_identity, published_utc
                    ) VALUES (?, ?, ?, ?, ?)""",
                    (job_id, run_id, result_bytes, result_identity, timestamp),
                )
                published_utc = timestamp
            self._connection.execute(
                """UPDATE story_map_v2_jobs SET status = 'published', updated_utc = ?
                   WHERE job_id = ?""",
                (timestamp, job_id),
            )
            self._refresh_run_state_locked(run_id, timestamp)
        record = PublishedJobResult(run_id, job_id, result, result_identity, published_utc)
        _inject(fault, FAULT_AFTER_JOB_PUBLICATION)
        return record

    def load_published_result(
        self,
        run_id: str,
        job_id: str,
    ) -> PublishedJobResult | None:
        _identifier(run_id, "run_id")
        _identifier(job_id, "job_id")
        row = self._connection.execute(
            """SELECT * FROM story_map_v2_published_results
               WHERE run_id = ? AND job_id = ?""",
            (run_id, job_id),
        ).fetchone()
        if row is None:
            return None
        return PublishedJobResult(
            run_id=str(row["run_id"]),
            job_id=str(row["job_id"]),
            result=storage.decode_json(row["result_json"]),
            result_identity=str(row["result_identity"]),
            published_utc=str(row["published_utc"]),
        )

    def finalize_success(
        self,
        claim: JobClaim,
        attempt: AttemptReservation,
        normalized_result: object,
        accounting: AttemptAccounting,
        *,
        now: datetime | None = None,
        fault: FaultInjector | None = None,
    ) -> NormalizedCacheEntry:
        if accounting.calls != 1:
            raise ValueError("a successful independent job must account for exactly one call")
        result_bytes = _durable_json(normalized_result, "normalized result")
        result_identity = hashlib.sha256(result_bytes).hexdigest()
        timestamp = _timestamp(now)
        _inject(fault, FAULT_BEFORE_ATTEMPT_FINALIZATION)
        with storage.transaction(self._connection):
            job_row = self._assert_claim_locked(
                claim,
                timestamp,
                (JobStatus.RESERVED, JobStatus.SUBMITTING),
            )
            if JobStatus(str(job_row["status"])) is not JobStatus.SUBMITTING:
                raise LeaseConflictError("attempt must be transmitting before success")
            if bool(job_row["cancel_requested"]):
                raise LeaseConflictError("cancelled run cannot finalize a successful attempt")
            attempt_row = self._connection.execute(
                "SELECT status FROM story_map_v2_attempts WHERE attempt_id = ? AND job_id = ?",
                (attempt.attempt_id, claim.descriptor.job_id),
            ).fetchone()
            if (
                attempt_row is None
                or AttemptStatus(str(attempt_row["status"])) is not AttemptStatus.TRANSMITTING
            ):
                raise LeaseConflictError("attempt must be transmitting before success")
            self._insert_immutable_cache_locked(
                claim.descriptor,
                result_bytes,
                result_identity,
                timestamp,
            )
            attempt_cursor = self._connection.execute(
                """UPDATE story_map_v2_attempts
                   SET status = 'succeeded', transmission_disposition = 'transmitted',
                       finalized_utc = ?, normalized_result_identity = ?, calls = ?,
                       input_tokens = ?, output_tokens = ?, elapsed_ms = ?
                   WHERE attempt_id = ? AND status = 'transmitting'""",
                (
                    timestamp,
                    result_identity,
                    accounting.calls,
                    accounting.input_tokens,
                    accounting.output_tokens,
                    accounting.elapsed_ms,
                    attempt.attempt_id,
                ),
            )
            if attempt_cursor.rowcount != 1:
                raise LeaseConflictError("attempt success compare-and-swap failed")
            job_cursor = self._connection.execute(
                """UPDATE story_map_v2_jobs
                   SET status = 'succeeded', lease_owner = NULL, lease_token = NULL,
                       lease_expires_utc = NULL, normalized_result_identity = ?, updated_utc = ?
                   WHERE job_id = ? AND lease_token = ?""",
                (
                    result_identity,
                    timestamp,
                    claim.descriptor.job_id,
                    claim.lease_token,
                ),
            )
            if job_cursor.rowcount != 1:
                raise LeaseConflictError("job success compare-and-swap failed")
            self._refresh_run_state_locked(claim.descriptor.run_id, timestamp)
        entry = NormalizedCacheEntry(
            claim.descriptor.cache_identity,
            claim.descriptor.authority_identity,
            claim.descriptor.serialized_request_identity,
            normalized_result,
            result_identity,
            timestamp,
        )
        _inject(fault, FAULT_AFTER_ATTEMPT_FINALIZATION)
        return entry

    def finalize_not_transmitted(
        self,
        claim: JobClaim,
        attempt: AttemptReservation,
        sanitized_failure: str,
        *,
        now: datetime | None = None,
    ) -> None:
        self.finalize_failure(
            claim,
            attempt,
            disposition=TransmissionDisposition.DEFINITELY_NOT_TRANSMITTED,
            accounting=AttemptAccounting(0, 0, 0, 0),
            failure_kind="definite_non_transmission",
            sanitized_failure=sanitized_failure,
            now=now,
        )

    def finalize_failure(
        self,
        claim: JobClaim,
        attempt: AttemptReservation,
        *,
        disposition: TransmissionDisposition,
        accounting: AttemptAccounting,
        failure_kind: str,
        sanitized_failure: str,
        now: datetime | None = None,
    ) -> None:
        if disposition is TransmissionDisposition.NOT_STARTED:
            raise ValueError("a finalized failure needs an explicit transmission disposition")
        if disposition is TransmissionDisposition.TRANSMITTED and accounting.calls != 1:
            raise ValueError("transmitted attempt must account for one call")
        if (
            disposition is TransmissionDisposition.DEFINITELY_NOT_TRANSMITTED
            and accounting.calls != 0
        ):
            raise ValueError("definite non-transmission cannot account for provider calls")
        _identifier(failure_kind, "failure_kind")
        failure = _sanitized_failure(sanitized_failure)
        timestamp = _timestamp(now)
        with storage.transaction(self._connection):
            job_row = self._assert_claim_locked(
                claim,
                timestamp,
                (JobStatus.RESERVED, JobStatus.SUBMITTING),
            )
            requires_transmitting = (
                disposition is not TransmissionDisposition.DEFINITELY_NOT_TRANSMITTED
            )
            required_job_status = (
                JobStatus.SUBMITTING if requires_transmitting else JobStatus.RESERVED
            )
            required_attempt_status = (
                AttemptStatus.TRANSMITTING if requires_transmitting else AttemptStatus.RESERVED
            )
            if JobStatus(str(job_row["status"])) is not required_job_status:
                raise LeaseConflictError(
                    "attempt must be transmitting before possible transmission failure"
                )
            cursor = self._connection.execute(
                """UPDATE story_map_v2_attempts
                   SET status = ?, transmission_disposition = ?, finalized_utc = ?,
                       calls = ?, input_tokens = ?, output_tokens = ?, elapsed_ms = ?,
                       failure_kind = ?, sanitized_failure = ?
                   WHERE attempt_id = ? AND job_id = ?
                      AND status = ?""",
                (
                    AttemptStatus.NOT_TRANSMITTED
                    if disposition is TransmissionDisposition.DEFINITELY_NOT_TRANSMITTED
                    else (
                        AttemptStatus.INDETERMINATE
                        if disposition is TransmissionDisposition.INDETERMINATE
                        else AttemptStatus.FAILED
                    ),
                    disposition,
                    timestamp,
                    accounting.calls,
                    accounting.input_tokens,
                    accounting.output_tokens,
                    accounting.elapsed_ms,
                    failure_kind,
                    failure,
                    attempt.attempt_id,
                    claim.descriptor.job_id,
                    required_attempt_status,
                ),
            )
            if cursor.rowcount != 1:
                raise LeaseConflictError("attempt is no longer finalizable")
            if bool(job_row["cancel_requested"]):
                next_status = JobStatus.CANCELLED
            elif disposition is TransmissionDisposition.DEFINITELY_NOT_TRANSMITTED:
                next_status = JobStatus.PENDING
            elif disposition is TransmissionDisposition.INDETERMINATE:
                next_status = JobStatus.INDETERMINATE
            else:
                next_status = JobStatus.FAILED
            self._connection.execute(
                """UPDATE story_map_v2_jobs
                   SET status = ?, lease_owner = NULL, lease_token = NULL,
                       lease_expires_utc = NULL, updated_utc = ?
                   WHERE job_id = ? AND lease_token = ?""",
                (next_status, timestamp, claim.descriptor.job_id, claim.lease_token),
            )
            self._refresh_run_state_locked(claim.descriptor.run_id, timestamp)

    def release_claim(
        self,
        claim: JobClaim,
        *,
        now: datetime | None = None,
    ) -> None:
        timestamp = _timestamp(now)
        with storage.transaction(self._connection):
            current = self._connection.execute(
                "SELECT status, lease_token FROM story_map_v2_jobs WHERE job_id = ?",
                (claim.descriptor.job_id,),
            ).fetchone()
            if (
                current is not None
                and str(current["lease_token"]) == claim.lease_token
                and JobStatus(str(current["status"]))
                in {JobStatus.RESERVED, JobStatus.SUBMITTING}
            ):
                return
            if current is not None and current["lease_token"] is None and JobStatus(
                str(current["status"])
            ) in {
                JobStatus.PENDING,
                JobStatus.FINALIZED,
                JobStatus.PUBLISHED,
                JobStatus.CANCELLED,
                JobStatus.INDETERMINATE,
            }:
                return
            row = self._assert_claim_locked(
                claim,
                timestamp,
                (JobStatus.CLAIMED, JobStatus.RETURNED, JobStatus.VALIDATED),
            )
            run = self._connection.execute(
                "SELECT cancel_requested FROM story_map_v2_runs WHERE run_id = ?",
                (claim.descriptor.run_id,),
            ).fetchone()
            current_status = JobStatus(str(row["status"]))
            next_status = current_status
            if current_status is JobStatus.CLAIMED:
                next_status = (
                    JobStatus.CANCELLED if run is not None and bool(run[0]) else JobStatus.PENDING
                )
            self._connection.execute(
                """UPDATE story_map_v2_jobs
                   SET status = ?, lease_owner = NULL, lease_token = NULL,
                       lease_expires_utc = NULL, updated_utc = ?
                   WHERE job_id = ? AND lease_token = ?""",
                (next_status, timestamp, claim.descriptor.job_id, claim.lease_token),
            )
            self._refresh_run_state_locked(claim.descriptor.run_id, timestamp)

    def cancel_run(self, run_id: str, *, now: datetime | None = None) -> None:
        _identifier(run_id, "run_id")
        timestamp = _timestamp(now)
        with storage.transaction(self._connection):
            cursor = self._connection.execute(
                """UPDATE story_map_v2_runs
                   SET cancel_requested = 1, status = 'cancelling', updated_utc = ?
                   WHERE run_id = ? AND status IN ('prepared','running')""",
                (timestamp, run_id),
            )
            if cursor.rowcount == 0:
                row = self._connection.execute(
                    "SELECT 1 FROM story_map_v2_runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                if row is None:
                    raise StoryMapV2RepositoryError("unknown run_id")
            self._connection.execute(
                """UPDATE story_map_v2_jobs
                   SET status = 'cancelled', lease_owner = NULL, lease_token = NULL,
                       lease_expires_utc = NULL, updated_utc = ?
                   WHERE run_id = ? AND status IN ('pending','claimed')""",
                (timestamp, run_id),
            )
            self._refresh_run_state_locked(run_id, timestamp)

    def recover_expired_leases(self, *, now: datetime | None = None) -> int:
        timestamp = _timestamp(now)
        with storage.transaction(self._connection):
            return self._recover_expired_leases_locked(timestamp)

    def recover_run(self, run_id: str, *, now: datetime | None = None) -> int:
        """Recover every active crash boundary for one exact run immediately."""

        _identifier(run_id, "run_id")
        timestamp = _timestamp(now)
        with storage.transaction(self._connection):
            self._connection.execute(
                """UPDATE story_map_v2_jobs SET lease_expires_utc = ?
                   WHERE run_id = ? AND status IN ('claimed','reserved','submitting')""",
                (timestamp, run_id),
            )
            recovered = self._recover_expired_leases_locked(timestamp)
            rows = self._connection.execute(
                """SELECT job_id, status FROM story_map_v2_jobs
                   WHERE run_id = ? AND status = 'returned'""",
                (run_id,),
            ).fetchall()
            for row in rows:
                continuation = self._connection.execute(
                    """SELECT continuation_kind FROM story_map_v2_jobs WHERE job_id = ?""",
                    (str(row["job_id"]),),
                ).fetchone()
                if continuation is not None and str(continuation[0]) in {
                    ContinuationKind.REPLACEMENT_REVIEW,
                    ContinuationKind.REFUSAL_FALLBACK,
                }:
                    continue
                attempt = self._connection.execute(
                    """SELECT attempt_id FROM story_map_v2_attempts
                       WHERE job_id = ? ORDER BY ordinal DESC LIMIT 1""",
                    (str(row["job_id"]),),
                ).fetchone()
                if attempt is not None:
                    self._connection.execute(
                        """UPDATE story_map_v2_attempts
                           SET status = 'indeterminate',
                               transmission_disposition = 'indeterminate',
                               failure_kind = 'result_lost_after_transport',
                               sanitized_failure = 'result_lost_after_transport'
                           WHERE attempt_id = ?""",
                        (str(attempt["attempt_id"]),),
                    )
                self._connection.execute(
                    """UPDATE story_map_v2_jobs
                       SET status = 'indeterminate', lease_owner = NULL, lease_token = NULL,
                           lease_expires_utc = NULL, updated_utc = ? WHERE job_id = ?""",
                    (timestamp, str(row["job_id"])),
                )
                recovered += 1
            self._refresh_run_state_locked(run_id, timestamp)
            return recovered

    def lookup_cache(self, cache_identity: str) -> NormalizedCacheEntry | None:
        _digest(cache_identity, "cache_identity")
        row = self._connection.execute(
            "SELECT * FROM story_map_v2_cache WHERE cache_identity = ?", (cache_identity,)
        ).fetchone()
        if row is None:
            return None
        return NormalizedCacheEntry(
            cache_identity=str(row["cache_identity"]),
            authority_identity=str(row["authority_identity"]),
            serialized_request_identity=str(row["serialized_request_identity"]),
            normalized_result=storage.decode_json(row["normalized_result_json"]),
            normalized_result_identity=str(row["normalized_result_identity"]),
            created_utc=str(row["created_utc"]),
        )

    def create_generation(
        self,
        generation: GenerationDescriptor,
        *,
        now: datetime | None = None,
    ) -> None:
        descriptor_bytes = _durable_json(generation.descriptor, "generation descriptor")
        descriptor_identity = hashlib.sha256(descriptor_bytes).hexdigest()
        timestamp = _timestamp(now)
        with storage.transaction(self._connection):
            run = self._connection.execute(
                """SELECT plan_id, authority_identity FROM story_map_v2_runs
                   WHERE run_id = ?""",
                (generation.run_id,),
            ).fetchone()
            if run is None or (
                str(run["plan_id"]),
                str(run["authority_identity"]),
            ) != (generation.plan_id, generation.authority_identity):
                raise StoryMapV2RepositoryError(
                    "generation run identity does not match its plan and authority"
                )
            existing = self._connection.execute(
                "SELECT * FROM story_map_v2_generations WHERE generation_id = ?",
                (generation.generation_id,),
            ).fetchone()
            expected = (
                generation.run_id,
                generation.plan_id,
                generation.authority_identity,
                generation.kind,
                descriptor_bytes,
                descriptor_identity,
            )
            if existing is not None:
                actual = (
                    str(existing["run_id"]),
                    str(existing["plan_id"]),
                    str(existing["authority_identity"]),
                    str(existing["generation_kind"]),
                    bytes(existing["descriptor_json"]),
                    str(existing["descriptor_identity"]),
                )
                if actual != expected:
                    raise ImmutableRecordConflictError("generation identity is immutable")
                return
            self._connection.execute(
                """INSERT INTO story_map_v2_generations(
                    generation_id, run_id, plan_id, authority_identity, generation_kind,
                    descriptor_json, descriptor_identity, created_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    generation.generation_id,
                    generation.run_id,
                    generation.plan_id,
                    generation.authority_identity,
                    generation.kind,
                    descriptor_bytes,
                    descriptor_identity,
                    timestamp,
                ),
            )

    def set_active_generation(
        self,
        generation_id: str,
        *,
        expected_active_generation_id: str | None,
        now: datetime | None = None,
    ) -> GenerationPointers:
        _identifier(generation_id, "generation_id")
        timestamp = _timestamp(now)
        with storage.transaction(self._connection):
            self._require_generation_locked(generation_id)
            pointers = self._pointers_locked()
            if pointers.active_build_generation != expected_active_generation_id:
                raise PublicationConflictError("active generation pointer changed")
            self._connection.execute(
                """UPDATE story_map_v2_generation_pointers
                   SET active_build_generation = ?, updated_utc = ? WHERE singleton = 1""",
                (generation_id, timestamp),
            )
        return GenerationPointers(
            pointers.current_complete_generation,
            generation_id,
            pointers.map_revision,
        )

    def store_section_page(self, page: SectionPageRecord) -> None:
        _identifier(page.generation_id, "generation_id")
        _identifier(page.section_id, "section_id")
        if page.page_ordinal < 0 or page.item_count < 0:
            raise ValueError("page ordinal and item count cannot be negative")
        page_bytes = _durable_json(page.page, "section page")
        identity = hashlib.sha256(page_bytes).hexdigest()
        if page.page_identity != identity:
            raise ValueError("page_identity does not match canonical page bytes")
        with storage.transaction(self._connection):
            existing = self._connection.execute(
                """SELECT item_count, page_json, page_identity
                   FROM story_map_v2_section_pages
                   WHERE generation_id = ? AND section_id = ? AND page_ordinal = ?""",
                (page.generation_id, page.section_id, page.page_ordinal),
            ).fetchone()
            if existing is not None:
                actual = (int(existing[0]), bytes(existing[1]), str(existing[2]))
                if actual != (page.item_count, page_bytes, identity):
                    raise ImmutableRecordConflictError("section page identity is immutable")
                return
            self._connection.execute(
                """INSERT INTO story_map_v2_section_pages(
                    generation_id, section_id, page_ordinal, item_count, page_json, page_identity
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    page.generation_id,
                    page.section_id,
                    page.page_ordinal,
                    page.item_count,
                    page_bytes,
                    identity,
                ),
            )

    def store_selection(self, selection: SelectionIndexRecord) -> None:
        for value, label in (
            (selection.generation_id, "generation_id"),
            (selection.selection_id, "selection_id"),
            (selection.section_id, "section_id"),
            (selection.selection_kind, "selection_kind"),
        ):
            _identifier(value, label)
        if selection.page_ordinal < 0 or selection.item_ordinal < 0:
            raise ValueError("selection ordinals cannot be negative")
        values = (
            selection.generation_id,
            selection.selection_id,
            selection.section_id,
            selection.page_ordinal,
            selection.item_ordinal,
            selection.selection_kind,
        )
        with storage.transaction(self._connection):
            existing = self._connection.execute(
                """SELECT generation_id, selection_id, section_id, page_ordinal,
                          item_ordinal, selection_kind
                   FROM story_map_v2_selection_index
                   WHERE generation_id = ? AND selection_id = ?""",
                (selection.generation_id, selection.selection_id),
            ).fetchone()
            if existing is not None:
                if tuple(existing) != values:
                    raise ImmutableRecordConflictError("selection identity is immutable")
                return
            self._connection.execute(
                """INSERT INTO story_map_v2_selection_index(
                    generation_id, selection_id, section_id, page_ordinal,
                    item_ordinal, selection_kind
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                values,
            )

    def load_section_page(
        self,
        generation_id: str,
        section_id: str,
        page_ordinal: int,
    ) -> SectionPageRecord | None:
        _identifier(generation_id, "generation_id")
        _identifier(section_id, "section_id")
        if page_ordinal < 0:
            raise ValueError("page_ordinal cannot be negative")
        row = self._connection.execute(
            """SELECT * FROM story_map_v2_section_pages
               WHERE generation_id = ? AND section_id = ? AND page_ordinal = ?""",
            (generation_id, section_id, page_ordinal),
        ).fetchone()
        if row is None:
            return None
        return SectionPageRecord(
            generation_id=str(row["generation_id"]),
            section_id=str(row["section_id"]),
            page_ordinal=int(row["page_ordinal"]),
            item_count=int(row["item_count"]),
            page=storage.decode_json(row["page_json"]),
            page_identity=str(row["page_identity"]),
        )

    def locate_selection(
        self,
        generation_id: str,
        selection_id: str,
    ) -> SelectionIndexRecord | None:
        _identifier(generation_id, "generation_id")
        _identifier(selection_id, "selection_id")
        row = self._connection.execute(
            """SELECT * FROM story_map_v2_selection_index
               WHERE generation_id = ? AND selection_id = ?""",
            (generation_id, selection_id),
        ).fetchone()
        if row is None:
            return None
        return SelectionIndexRecord(
            generation_id=str(row["generation_id"]),
            selection_id=str(row["selection_id"]),
            section_id=str(row["section_id"]),
            page_ordinal=int(row["page_ordinal"]),
            item_ordinal=int(row["item_ordinal"]),
            selection_kind=str(row["selection_kind"]),
        )

    def generation_pointers(self) -> GenerationPointers:
        return self._pointers_locked()

    def publish_generation(
        self,
        generation_id: str,
        *,
        expected_active_generation_id: str,
        now: datetime | None = None,
        fault: FaultInjector | None = None,
    ) -> GenerationPointers:
        _identifier(generation_id, "generation_id")
        _identifier(expected_active_generation_id, "expected_active_generation_id")
        timestamp = _timestamp(now)
        _inject(fault, FAULT_BEFORE_GENERATION_PUBLICATION)
        with storage.transaction(self._connection):
            generation = self._require_generation_locked(generation_id)
            if str(generation["generation_kind"]) != GenerationKind.COMPLETE:
                raise PublicationConflictError("only a complete generation can be published")
            pointers = self._pointers_locked()
            if pointers.active_build_generation != expected_active_generation_id:
                raise PublicationConflictError("active generation pointer changed")
            if generation_id != expected_active_generation_id:
                raise PublicationConflictError("published generation must be the active generation")
            revision = pointers.map_revision + 1
            self._connection.execute(
                """UPDATE story_map_v2_generation_pointers
                   SET current_complete_generation = ?, active_build_generation = NULL,
                       map_revision = ?, updated_utc = ? WHERE singleton = 1""",
                (generation_id, revision, timestamp),
            )
        published = GenerationPointers(generation_id, None, revision)
        _inject(fault, FAULT_AFTER_GENERATION_PUBLICATION)
        return published

    def save_view_state(
        self,
        view_key: str,
        *,
        generation_id: str | None,
        map_revision: int,
        selection_id: str | None,
        section_id: str | None,
        state: object,
        now: datetime | None = None,
    ) -> ViewStateRecord:
        _identifier(view_key, "view_key")
        if generation_id is not None:
            _identifier(generation_id, "generation_id")
        if selection_id is not None:
            _identifier(selection_id, "selection_id")
        if section_id is not None:
            _identifier(section_id, "section_id")
        if map_revision < 0:
            raise ValueError("map_revision cannot be negative")
        state_bytes = _durable_json(state, "view state")
        state_identity = hashlib.sha256(state_bytes).hexdigest()
        timestamp = _timestamp(now)
        with storage.transaction(self._connection):
            self._connection.execute(
                """INSERT INTO story_map_v2_view_state(
                    view_key, generation_id, map_revision, selection_id, section_id,
                    state_json, state_identity, updated_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(view_key) DO UPDATE SET
                    generation_id = excluded.generation_id,
                    map_revision = excluded.map_revision,
                    selection_id = excluded.selection_id,
                    section_id = excluded.section_id,
                    state_json = excluded.state_json,
                    state_identity = excluded.state_identity,
                    updated_utc = excluded.updated_utc""",
                (
                    view_key,
                    generation_id,
                    map_revision,
                    selection_id,
                    section_id,
                    state_bytes,
                    state_identity,
                    timestamp,
                ),
            )
        return ViewStateRecord(
            view_key,
            generation_id,
            map_revision,
            selection_id,
            section_id,
            state,
            state_identity,
        )

    def load_view_state(self, view_key: str) -> ViewStateRecord | None:
        _identifier(view_key, "view_key")
        row = self._connection.execute(
            "SELECT * FROM story_map_v2_view_state WHERE view_key = ?", (view_key,)
        ).fetchone()
        if row is None:
            return None
        return ViewStateRecord(
            view_key=str(row["view_key"]),
            generation_id=_optional_text(row["generation_id"]),
            map_revision=int(row["map_revision"]),
            selection_id=_optional_text(row["selection_id"]),
            section_id=_optional_text(row["section_id"]),
            state=storage.decode_json(row["state_json"]),
            state_identity=str(row["state_identity"]),
        )

    def _recover_expired_leases_locked(self, timestamp: str) -> int:
        rows = self._connection.execute(
            """SELECT jobs.job_id, jobs.run_id, jobs.status, runs.cancel_requested
               FROM story_map_v2_jobs AS jobs
               JOIN story_map_v2_runs AS runs ON runs.run_id = jobs.run_id
               WHERE jobs.status IN ('claimed','reserved','submitting')
                 AND jobs.lease_expires_utc <= ? ORDER BY jobs.job_id""",
            (timestamp,),
        ).fetchall()
        for row in rows:
            job_id = str(row["job_id"])
            status = JobStatus(str(row["status"]))
            attempt = self._connection.execute(
                """SELECT attempt_id, status FROM story_map_v2_attempts
                   WHERE job_id = ? ORDER BY ordinal DESC LIMIT 1""",
                (job_id,),
            ).fetchone()
            transmitting = status is JobStatus.SUBMITTING or (
                attempt is not None
                and AttemptStatus(str(attempt["status"])) is AttemptStatus.TRANSMITTING
            )
            reserved_not_sent = (
                status is JobStatus.RESERVED
                and attempt is not None
                and AttemptStatus(str(attempt["status"])) is AttemptStatus.RESERVED
            )
            if transmitting and attempt is not None:
                self._connection.execute(
                    """UPDATE story_map_v2_attempts
                       SET status = 'indeterminate',
                           transmission_disposition = 'indeterminate', finalized_utc = ?,
                           failure_kind = 'lease_expired',
                           sanitized_failure = 'lease_expired_after_reservation'
                       WHERE attempt_id = ?""",
                    (timestamp, str(attempt["attempt_id"])),
                )
            elif reserved_not_sent:
                self._connection.execute(
                    """UPDATE story_map_v2_attempts
                       SET status = 'not_transmitted',
                           transmission_disposition = 'definitely_not_transmitted',
                           finalized_utc = ?, calls = 0, input_tokens = 0,
                           output_tokens = 0, elapsed_ms = 0,
                           failure_kind = 'lease_expired_before_transmission',
                           sanitized_failure = 'lease_expired_before_transmission'
                       WHERE attempt_id = ?""",
                    (timestamp, str(attempt["attempt_id"])),
                )
            if transmitting:
                next_status = JobStatus.INDETERMINATE
            elif bool(row["cancel_requested"]):
                next_status = JobStatus.CANCELLED
            else:
                next_status = JobStatus.PENDING
            self._connection.execute(
                """UPDATE story_map_v2_jobs
                   SET status = ?, lease_owner = NULL, lease_token = NULL,
                       lease_expires_utc = NULL, updated_utc = ? WHERE job_id = ?""",
                (next_status, timestamp, job_id),
            )
            self._refresh_run_state_locked(str(row["run_id"]), timestamp)
        return len(rows)

    def _materialize_cache_hits_locked(self, timestamp: str) -> None:
        run_ids = {
            str(row[0])
            for row in self._connection.execute(
                """SELECT DISTINCT jobs.run_id FROM story_map_v2_jobs AS jobs
                   JOIN story_map_v2_run_approvals AS approvals
                     ON approvals.run_id = jobs.run_id
                   WHERE jobs.status = 'pending' AND EXISTS (
                       SELECT 1 FROM story_map_v2_cache AS cache
                       WHERE cache.cache_identity = jobs.cache_identity
                         AND cache.authority_identity = jobs.authority_identity
                         AND cache.serialized_request_identity = jobs.serialized_request_identity
                   )"""
            )
        }
        self._connection.execute(
            """UPDATE story_map_v2_jobs
               SET status = 'cached', normalized_result_identity = (
                       SELECT cache.normalized_result_identity
                       FROM story_map_v2_cache AS cache
                       WHERE cache.cache_identity = story_map_v2_jobs.cache_identity
                         AND cache.authority_identity = story_map_v2_jobs.authority_identity
                         AND cache.serialized_request_identity =
                             story_map_v2_jobs.serialized_request_identity
                   ), updated_utc = ?
               WHERE status = 'pending' AND EXISTS (
                   SELECT 1 FROM story_map_v2_cache AS cache
                   WHERE cache.cache_identity = story_map_v2_jobs.cache_identity
                     AND cache.authority_identity = story_map_v2_jobs.authority_identity
                     AND cache.serialized_request_identity =
                         story_map_v2_jobs.serialized_request_identity
               ) AND EXISTS (
                   SELECT 1 FROM story_map_v2_run_approvals AS approvals
                   WHERE approvals.run_id = story_map_v2_jobs.run_id
               )""",
            (timestamp,),
        )
        for run_id in run_ids:
            self._refresh_run_state_locked(run_id, timestamp)

    def _assert_claim_locked(
        self,
        claim: JobClaim,
        timestamp: str,
        allowed_statuses: tuple[JobStatus, ...],
    ) -> sqlite3.Row:
        row = self._connection.execute(
            """SELECT jobs.*, runs.cancel_requested FROM story_map_v2_jobs AS jobs
               JOIN story_map_v2_runs AS runs ON runs.run_id = jobs.run_id
               WHERE jobs.job_id = ?""",
            (claim.descriptor.job_id,),
        ).fetchone()
        if row is None:
            raise LeaseConflictError("claimed job no longer exists")
        if _job_descriptor(row) != claim.descriptor:
            raise LeaseConflictError("claimed job identity changed")
        if (
            str(row["lease_owner"]) != claim.lease_owner
            or str(row["lease_token"]) != claim.lease_token
            or str(row["lease_expires_utc"]) <= timestamp
            or JobStatus(str(row["status"])) not in allowed_statuses
        ):
            raise LeaseConflictError("job lease compare-and-swap failed")
        if bool(row["cancel_requested"]) and JobStatus(str(row["status"])) is JobStatus.CLAIMED:
            raise LeaseConflictError("run was cancelled before attempt reservation")
        return cast(sqlite3.Row, row)

    def _validate_attempt_policy_locked(
        self,
        job_id: str,
        ordinal: int,
        metadata: AttemptReservationMetadata,
        timestamp: str,
    ) -> str | None:
        rows = self._connection.execute(
            """SELECT attempt_id, ordinal, call_kind, status, transmission_disposition,
                      retry_of_attempt_id
               FROM story_map_v2_attempts
               WHERE job_id = ? ORDER BY ordinal""",
            (job_id,),
        ).fetchall()
        if ordinal == 1:
            if rows or metadata.call_kind != ContinuationKind.MAPPING:
                raise StoryMapV2RepositoryError("first attempt must be the mapping call")
            return None
        if not rows or int(rows[-1]["ordinal"]) != ordinal - 1:
            raise StoryMapV2RepositoryError("attempt ordinal does not follow the latest attempt")
        previous = rows[-1]
        previous_kind = str(previous["call_kind"])
        previous_status = AttemptStatus(str(previous["status"]))
        previous_disposition = TransmissionDisposition(str(previous["transmission_disposition"]))
        if previous_disposition is TransmissionDisposition.DEFINITELY_NOT_TRANSMITTED:
            if metadata.call_kind != previous_kind:
                raise StoryMapV2RepositoryError(
                    "definite non-transmission retry requires the same call kind"
                )
            return _optional_text(previous["retry_of_attempt_id"])
        if (
            previous_status is AttemptStatus.INDETERMINATE
            or previous_disposition is TransmissionDisposition.INDETERMINATE
        ):
            if metadata.call_kind != previous_kind:
                raise StoryMapV2RepositoryError(
                    "indeterminate retry approval permits only the same call kind"
                )
            approval = self._connection.execute(
                """SELECT retry_approval_id FROM story_map_v2_retry_approvals
                   WHERE job_id = ? AND attempt_ordinal = ? AND consumed_utc IS NULL""",
                (job_id, ordinal - 1),
            ).fetchone()
            if approval is None:
                raise StoryMapV2RepositoryError(
                    "retry requires the exact unconsumed prior indeterminate approval"
                )
            consumed = self._connection.execute(
                """UPDATE story_map_v2_retry_approvals SET consumed_utc = ?
                   WHERE retry_approval_id = ? AND consumed_utc IS NULL""",
                (timestamp, str(approval["retry_approval_id"])),
            )
            if consumed.rowcount != 1:
                raise StoryMapV2RepositoryError("retry approval was already consumed")
            return str(previous["attempt_id"])
        if metadata.call_kind == ContinuationKind.MAPPING:
            raise StoryMapV2RepositoryError(
                "mapping retry requires non-transmission or indeterminate approval"
            )
        if metadata.call_kind in {
            ContinuationKind.REPLACEMENT_REVIEW,
            ContinuationKind.REFUSAL_FALLBACK,
        }:
            if any(
                str(row["call_kind"])
                in {ContinuationKind.REPLACEMENT_REVIEW, ContinuationKind.REFUSAL_FALLBACK}
                and (
                    str(row["transmission_disposition"]) == TransmissionDisposition.TRANSMITTED
                    or str(row["status"]) == AttemptStatus.RETURNED
                )
                for row in rows
            ):
                raise StoryMapV2RepositoryError(
                    "review or fallback is limited to one transmitted attempt"
                )
            job = self._connection.execute(
                """SELECT continuation_kind, continuation_attempt_id
                   FROM story_map_v2_jobs WHERE job_id = ?""",
                (job_id,),
            ).fetchone()
            if job is None or str(job["continuation_kind"]) not in {
                ContinuationKind.REPLACEMENT_REVIEW,
                ContinuationKind.REFUSAL_FALLBACK,
            }:
                raise StoryMapV2RepositoryError("job has no approved continuation marker")
            if metadata.call_kind != str(job["continuation_kind"]):
                raise StoryMapV2RepositoryError("attempt call kind does not match continuation")
            if str(job["continuation_attempt_id"]) != str(previous["attempt_id"]):
                raise StoryMapV2RepositoryError("continuation does not bind the latest attempt")
            return None
        raise StoryMapV2RepositoryError("attempt call kind is not authorized")

    def _validate_attempt_limits_locked(
        self,
        run_id: str,
        job_id: str,
        call_kind: str,
        retry_of_attempt_id: str | None,
        limits: AttemptReservationLimits,
    ) -> bool:
        totals = self._connection.execute(
            """SELECT COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0),
                      COALESCE(SUM(elapsed_ms), 0)
               FROM story_map_v2_attempts AS attempts
               JOIN story_map_v2_jobs AS jobs ON jobs.job_id = attempts.job_id
               WHERE jobs.run_id = ?""",
            (run_id,),
        ).fetchone()
        assert totals is not None
        if (
            int(totals[0]) >= limits.input_tokens
            or int(totals[1]) >= limits.output_tokens
            or int(totals[2]) >= limits.elapsed_ms
        ):
            raise StoryMapV2RepositoryError("workflow accounting ceiling is exhausted")
        role_limit = {
            ContinuationKind.MAPPING.value: limits.mapping_calls,
            ContinuationKind.REPLACEMENT_REVIEW.value: limits.review_calls,
            ContinuationKind.REFUSAL_FALLBACK.value: limits.fallback_calls,
        }.get(call_kind)
        if role_limit is None:
            raise StoryMapV2RepositoryError("attempt call kind has no finite role limit")
        role_row = self._connection.execute(
            """SELECT COUNT(*) FROM story_map_v2_attempts AS attempts
               JOIN story_map_v2_jobs AS jobs ON jobs.job_id = attempts.job_id
               WHERE jobs.run_id = ? AND attempts.call_kind = ?
                 AND attempts.transmission_disposition != 'definitely_not_transmitted'
                 AND (attempts.status IN ('reserved','transmitting') OR attempts.calls = 1)""",
            (run_id, call_kind),
        ).fetchone()
        assert role_row is not None
        if int(role_row[0]) < role_limit:
            return False
        if retry_of_attempt_id is None:
            raise StoryMapV2RepositoryError("ordinary provider-call ceiling is exhausted")
        occupied = self._connection.execute(
            """SELECT COUNT(*) FROM story_map_v2_attempts AS attempts
               JOIN story_map_v2_jobs AS jobs ON jobs.job_id = attempts.job_id
               WHERE jobs.run_id = ?
                 AND attempts.uses_supplemental_retry_capacity = 1
                 AND attempts.transmission_disposition != 'definitely_not_transmitted'""",
            (run_id,),
        ).fetchone()
        assert occupied is not None
        if int(occupied[0]) >= limits.indeterminate_retry_calls:
            raise StoryMapV2RepositoryError("supplemental retry-call ceiling is exhausted")
        same_job = self._connection.execute(
            """SELECT 1 FROM story_map_v2_attempts
               WHERE job_id = ? AND uses_supplemental_retry_capacity = 1
                 AND transmission_disposition != 'definitely_not_transmitted'
               LIMIT 1""",
            (job_id,),
        ).fetchone()
        if same_job is not None:
            raise StoryMapV2RepositoryError("job supplemental retry capacity is exhausted")
        return True

    def _insert_immutable_cache_locked(
        self,
        descriptor: FrozenJobDescriptor,
        result_bytes: bytes,
        result_identity: str,
        timestamp: str,
    ) -> None:
        existing = self._connection.execute(
            "SELECT * FROM story_map_v2_cache WHERE cache_identity = ?",
            (descriptor.cache_identity,),
        ).fetchone()
        expected = (
            descriptor.authority_identity,
            descriptor.serialized_request_identity,
            result_bytes,
            result_identity,
        )
        if existing is not None:
            actual = (
                str(existing["authority_identity"]),
                str(existing["serialized_request_identity"]),
                bytes(existing["normalized_result_json"]),
                str(existing["normalized_result_identity"]),
            )
            if actual != expected:
                raise ImmutableRecordConflictError("cache identity is immutable")
            return
        self._connection.execute(
            """INSERT INTO story_map_v2_cache(
                cache_identity, authority_identity, serialized_request_identity,
                normalized_result_json, normalized_result_identity, created_utc
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                descriptor.cache_identity,
                descriptor.authority_identity,
                descriptor.serialized_request_identity,
                result_bytes,
                result_identity,
                timestamp,
            ),
        )

    def _refresh_run_state_locked(self, run_id: str, timestamp: str) -> None:
        run = self._connection.execute(
            "SELECT cancel_requested FROM story_map_v2_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if run is None:
            return
        statuses = {
            JobStatus(str(row[0]))
            for row in self._connection.execute(
                "SELECT DISTINCT status FROM story_map_v2_jobs WHERE run_id = ?", (run_id,)
            )
        }
        active = {
            JobStatus.PENDING,
            JobStatus.CLAIMED,
            JobStatus.RESERVED,
            JobStatus.SUBMITTING,
            JobStatus.RETURNED,
            JobStatus.VALIDATED,
            JobStatus.CACHE_STORED,
        }
        finalized_resolutions = {
            JobResolution(str(row[0]))
            for row in self._connection.execute(
                """SELECT DISTINCT resolution FROM story_map_v2_jobs
                   WHERE run_id = ? AND status = 'finalized' AND resolution IS NOT NULL""",
                (run_id,),
            )
        }
        if finalized_resolutions & {JobResolution.ACCEPTED, JobResolution.STRUCTURAL}:
            active.add(JobStatus.FINALIZED)
        if statuses & active:
            next_status = RunStatus.CANCELLING if bool(run[0]) else RunStatus.RUNNING
        elif JobResolution.INDETERMINATE in finalized_resolutions:
            next_status = RunStatus.INDETERMINATE
        elif JobResolution.RESUMABLE in finalized_resolutions:
            next_status = RunStatus.FAILED
        elif JobResolution.CANCELLED in finalized_resolutions:
            next_status = RunStatus.CANCELLED
        elif JobStatus.INDETERMINATE in statuses:
            next_status = RunStatus.INDETERMINATE
        elif JobStatus.FAILED in statuses:
            next_status = RunStatus.FAILED
        elif bool(run[0]) or JobStatus.CANCELLED in statuses:
            next_status = RunStatus.CANCELLED
        else:
            next_status = RunStatus.COMPLETED
        self._connection.execute(
            "UPDATE story_map_v2_runs SET status = ?, updated_utc = ? WHERE run_id = ?",
            (next_status, timestamp, run_id),
        )

    def _require_generation_locked(self, generation_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            """SELECT generations.*, runs.plan_id AS run_plan_id,
                      runs.authority_identity AS run_authority_identity
               FROM story_map_v2_generations AS generations
               JOIN story_map_v2_runs AS runs ON runs.run_id = generations.run_id
               WHERE generations.generation_id = ?""",
            (generation_id,),
        ).fetchone()
        if row is None:
            raise StoryMapV2RepositoryError("unknown generation_id")
        if (
            str(row["plan_id"]),
            str(row["authority_identity"]),
        ) != (
            str(row["run_plan_id"]),
            str(row["run_authority_identity"]),
        ):
            raise PublicationConflictError(
                "generation run identity does not match its plan and authority"
            )
        return cast(sqlite3.Row, row)

    def _pointers_locked(self) -> GenerationPointers:
        row = self._connection.execute(
            "SELECT * FROM story_map_v2_generation_pointers WHERE singleton = 1"
        ).fetchone()
        if row is None:
            raise storage.ProjectCorruptError("project has no Story Map V2 generation pointer")
        return GenerationPointers(
            _optional_text(row["current_complete_generation"]),
            _optional_text(row["active_build_generation"]),
            int(row["map_revision"]),
        )


def _job_descriptor(row: sqlite3.Row) -> FrozenJobDescriptor:
    return FrozenJobDescriptor(
        run_id=str(row["run_id"]),
        plan_id=str(row["plan_id"]),
        scope_id=str(row["scope_id"]),
        job_id=str(row["job_id"]),
        chunk_id=str(row["chunk_id"]),
        authority_identity=str(row["authority_identity"]),
        serialized_request_identity=str(row["serialized_request_identity"]),
        cache_identity=str(row["cache_identity"]),
        ordinal=int(row["ordinal"]),
    )


def _job_record(row: sqlite3.Row) -> JobRecord:
    result = _optional_text(row["normalized_result_identity"])
    resolution_text = _optional_text(row["resolution"])
    return JobRecord(
        descriptor=_job_descriptor(row),
        status=JobStatus(str(row["status"])),
        next_attempt_ordinal=int(row["next_attempt_ordinal"]),
        normalized_result_identity=result,
        resolution=None if resolution_text is None else JobResolution(resolution_text),
        continuation_kind=ContinuationKind(str(row["continuation_kind"])),
        continuation_attempt_id=_optional_text(row["continuation_attempt_id"]),
        continuation_result_identity=_optional_text(row["continuation_result_identity"]),
        validated_cache_identity=_optional_text(row["validated_cache_identity"]),
    )


def _job_claim(
    row: sqlite3.Row,
    lease_owner: str,
    lease_token: str,
    lease_expires_utc: str,
) -> JobClaim:
    return JobClaim(
        descriptor=_job_descriptor(row),
        lease_owner=lease_owner,
        lease_token=lease_token,
        lease_expires_utc=lease_expires_utc,
        continuation_kind=ContinuationKind(str(row["continuation_kind"])),
        continuation_attempt_id=_optional_text(row["continuation_attempt_id"]),
        continuation_result_identity=_optional_text(row["continuation_result_identity"]),
    )


def _attempt_record(row: sqlite3.Row) -> AttemptRecord:
    return AttemptRecord(
        reservation=AttemptReservation(
            attempt_id=str(row["attempt_id"]),
            job_id=str(row["job_id"]),
            ordinal=int(row["ordinal"]),
            metadata=AttemptReservationMetadata(
                call_kind=str(row["call_kind"]),
                provider_input_identity=str(row["provider_input_identity"]),
                ceilings_identity=str(row["ceilings_identity"]),
            ),
            status=AttemptStatus(str(row["status"])),
            transmission_disposition=TransmissionDisposition(str(row["transmission_disposition"])),
            reserved_utc=str(row["reserved_utc"]),
            retry_of_attempt_id=_optional_text(row["retry_of_attempt_id"]),
            uses_supplemental_retry_capacity=bool(
                row["uses_supplemental_retry_capacity"]
            ),
        ),
        transmission_utc=_optional_text(row["transmission_utc"]),
        finalized_utc=_optional_text(row["finalized_utc"]),
        normalized_result_identity=_optional_text(row["normalized_result_identity"]),
        accounting=AttemptAccounting(
            calls=int(row["calls"]),
            input_tokens=int(row["input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            elapsed_ms=int(row["elapsed_ms"]),
        ),
        failure_kind=_optional_text(row["failure_kind"]),
        sanitized_failure=_optional_text(row["sanitized_failure"]),
    )


def _identifier(value: str, label: str) -> None:
    if not value or value != value.strip() or "\x00" in value:
        raise ValueError(f"{label} must be a non-empty normalized identifier")
    if len(value) > 512:
        raise ValueError(f"{label} is too long")
    _reject_absolute_path(value, label)


def _digest(value: str, label: str) -> None:
    if not _DIGEST_RE.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _matching_identity(payload: bytes, identity: str, label: str) -> None:
    _digest(identity, label)
    if hashlib.sha256(payload).hexdigest() != identity:
        raise ValueError(f"{label} does not match canonical payload bytes")


def _instant(value: datetime | None) -> datetime:
    instant = datetime.now(UTC) if value is None else value
    if instant.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return instant.astimezone(UTC)


def _timestamp(value: datetime | None) -> str:
    return _instant(value).isoformat(timespec="microseconds")


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _inject(fault: FaultInjector | None, point: str) -> None:
    if fault is not None:
        fault(point)


def _sanitized_failure(value: str) -> str:
    if not value or len(value) > 512 or "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError("sanitized failure must be one bounded line")
    _reject_absolute_path(value, "sanitized failure")
    return value


def _durable_json(value: object, label: str) -> bytes:
    _validate_private_content(value, label)
    return storage.canonical_json(value)


def _validate_private_content(value: object, label: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{label} object keys must be strings")
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if (
                normalized in _FORBIDDEN_KEYS
                or normalized.startswith(
                    ("rawresponse", "rawrequest", "rawprompt", "sourcepacket", "providerstderr")
                )
                or normalized.endswith(("credential", "credentials"))
            ):
                raise ValueError(f"{label} contains forbidden durable field {key!r}")
            _reject_absolute_path(key, f"{label} object key")
            _validate_private_content(item, label)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_private_content(item, label)
        return
    if isinstance(value, str):
        _reject_absolute_path(value, label)


def _reject_absolute_path(value: str, label: str) -> None:
    stripped = value.strip()
    if (
        _WINDOWS_ABSOLUTE_RE.search(value) is not None
        or _UNC_RE.search(value) is not None
        or _POSIX_ABSOLUTE_RE.search(value) is not None
        or _FILE_URI_RE.search(value) is not None
        or stripped.startswith("/")
    ):
        raise ValueError(f"{label} cannot contain an absolute path")
