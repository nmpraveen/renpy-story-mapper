"""Durable, provider-neutral scheduling for independent M13 logical jobs.

The scheduler is intentionally synchronous in v1.  One active call is a hard,
deterministic subset of every consented positive concurrency ceiling, while
avoiding speculative calls that could exceed a shared token or cost budget.
Logical jobs, attempts, cache entries, and publications remain independent even
when a provider request transports several scene jobs together.

Only structured job input is held in memory.  Durable records contain hashes,
identities, state, sanitized error codes, and usage metrics; they never contain
prompt text, source packets, or raw provider responses.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
from typing import Protocol, cast

from renpy_story_mapper import storage
from renpy_story_mapper.narrative.batching import (
    BatchableSceneJob,
    BatchEvaluation,
    BatchItemOutcome,
    BatchItemStatus,
    BatchLimits,
    TransportBatch,
    evaluate_batch_output,
    pack_scene_jobs,
    recursive_singleton_batches,
    split_transport_batch,
)
from renpy_story_mapper.narrative.contracts import (
    ArtifactPublication,
    AttemptMetrics,
    AttemptOutcome,
    CacheIdentity,
    ConsentManifest,
    CostConfidence,
    JsonValue,
    LogicalJob,
    LogicalJobState,
    ProviderIdentity,
    canonical_hash,
)
from renpy_story_mapper.narrative.persistence import SANITIZED_ERROR_MESSAGES
from renpy_story_mapper.narrative.provider import (
    HARD_MAXIMUM_BATCH_ITEMS,
    HARD_MAXIMUM_INPUT_BYTES,
    HARD_MAXIMUM_OUTPUT_BYTES,
    NarrativeProvider,
    NarrativeProviderError,
    ProviderBatchItem,
    ProviderCancelledError,
    ProviderIdentityMismatchError,
    ProviderLimitError,
    ProviderOutputError,
    ProviderOutputItem,
    ProviderPolicyViolationError,
    ProviderRefusalError,
    ProviderRequest,
    ProviderResponse,
    ProviderTimeoutError,
    ProviderUsage,
)

_REFUSAL_CODES = frozenset(
    {"content_refusal", "content_refused", "provider_refusal", "provider_refused"}
)
_TERMINAL_JOB_STATES = frozenset(
    {
        LogicalJobState.SUCCEEDED,
        LogicalJobState.PARTIAL,
        LogicalJobState.FAILED,
        LogicalJobState.REFUSED,
        LogicalJobState.CANCELLED,
    }
)


class SchedulerRunState(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    HARD_LIMIT = "hard_limit"


class SchedulerBatchState(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    RETRYING = "retrying"
    SPLIT = "split"
    FAILED = "failed"
    CANCELLED = "cancelled"
    HARD_LIMIT = "hard_limit"


class SchedulerConfigurationError(ValueError):
    """The exact run cannot safely start under its consent or job bindings."""


@dataclass(frozen=True)
class SchedulerPolicy:
    """Deterministic transport and bounded retry policy for one scheduler."""

    batch_limits: BatchLimits
    maximum_attempts_per_job: int = 8
    maximum_transient_attempts_per_job: int = 3
    maximum_malformed_attempts_per_job: int = 8
    maximum_output_bytes_per_call: int = 256_000
    maximum_input_bytes_per_call: int = 512_000

    def __post_init__(self) -> None:
        for name in (
            "maximum_attempts_per_job",
            "maximum_transient_attempts_per_job",
            "maximum_malformed_attempts_per_job",
            "maximum_output_bytes_per_call",
            "maximum_input_bytes_per_call",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.maximum_transient_attempts_per_job > self.maximum_attempts_per_job:
            raise ValueError("transient retry limit cannot exceed the total attempt limit")
        if self.maximum_malformed_attempts_per_job > self.maximum_attempts_per_job:
            raise ValueError("malformed retry limit cannot exceed the total attempt limit")
        if self.batch_limits.maximum_items > HARD_MAXIMUM_BATCH_ITEMS:
            raise ValueError("batch item limit exceeds the provider transport hard bound")
        if self.maximum_input_bytes_per_call > HARD_MAXIMUM_INPUT_BYTES:
            raise ValueError("input byte limit exceeds the provider transport hard bound")
        if self.maximum_output_bytes_per_call > HARD_MAXIMUM_OUTPUT_BYTES:
            raise ValueError("output byte limit exceeds the provider transport hard bound")


@dataclass(frozen=True)
class ScheduledSceneJob:
    """One independently cached logical job plus its in-memory structured input.

    The historical class name remains source-compatible with the scene-first scheduler slice;
    hierarchy jobs use the same transport-neutral record without changing logical ownership.
    """

    logical_job: LogicalJob
    cache_identity: CacheIdentity
    scope_id: str
    provider_input: dict[str, JsonValue]
    ordinal: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_micros: int | None = None

    def __post_init__(self) -> None:
        if not self.scope_id or self.scope_id != self.scope_id.strip():
            raise ValueError("scope_id must be a non-empty trimmed string")
        if self.ordinal < 0:
            raise ValueError("ordinal must be non-negative")
        for name in ("estimated_input_tokens", "estimated_output_tokens"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.estimated_cost_micros is not None and (
            not isinstance(self.estimated_cost_micros, int)
            or isinstance(self.estimated_cost_micros, bool)
            or self.estimated_cost_micros < 0
        ):
            raise ValueError("estimated_cost_micros must be non-negative when supplied")
        normalized = storage.decode_json(storage.canonical_json(self.provider_input))
        if not isinstance(normalized, dict) or not normalized:
            raise ValueError("provider_input must be a non-empty JSON object")
        object.__setattr__(self, "provider_input", cast(dict[str, JsonValue], normalized))
        job_id = self.logical_job.spec.job_id
        revision = self.logical_job.input_revision
        if self.cache_identity.logical_job_id != job_id:
            raise ValueError("cache identity belongs to a different logical job")
        if self.cache_identity.input_revision_id != revision.identity:
            raise ValueError("cache identity belongs to a different input revision")
        if self.cache_identity.normalized_input_hash != revision.normalized_input_hash:
            raise ValueError("cache identity normalized input hash does not match the job")

    @property
    def logical_job_id(self) -> str:
        return self.logical_job.spec.job_id

    @property
    def input_revision_id(self) -> str:
        return self.logical_job.input_revision.identity

    @property
    def input_bytes(self) -> int:
        return len(storage.canonical_json(self.provider_input))

    def batchable(self) -> BatchableSceneJob:
        return BatchableSceneJob(
            logical_job_id=self.logical_job_id,
            input_revision=self.input_revision_id,
            ordinal=self.ordinal,
            input_chars=self.input_bytes,
            estimated_input_tokens=self.estimated_input_tokens,
        )


@dataclass(frozen=True)
class CacheReplay:
    """A previously validated exact cache hit; no provider action is needed."""

    artifact_id: str
    publication: ArtifactPublication

    def __post_init__(self) -> None:
        if not self.artifact_id or self.artifact_id != self.artifact_id.strip():
            raise ValueError("cached artifact ID must be a non-empty trimmed string")
        if self.publication is ArtifactPublication.REJECTED:
            raise ValueError("a rejected artifact cannot be an accepted cache hit")


@dataclass(frozen=True)
class ValidatedLogicalOutput:
    """Opaque validated publication handed to a durable item-local commit seam."""

    logical_job_id: str
    artifact_id: str
    publication: ArtifactPublication
    payload: Mapping[str, object]
    validated_claim_count: int
    invalid_claim_count: int = 0

    def __post_init__(self) -> None:
        for value, label in (
            (self.logical_job_id, "validated logical job ID"),
            (self.artifact_id, "validated artifact ID"),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{label} must be a non-empty trimmed string")
        if self.publication is ArtifactPublication.REJECTED:
            raise ValueError("rejected output cannot cross the publication seam")
        if self.validated_claim_count < 0 or self.invalid_claim_count < 0:
            raise ValueError("validated output claim counts cannot be negative")
        normalized = storage.decode_json(storage.canonical_json(dict(self.payload)))
        if not isinstance(normalized, dict):
            raise ValueError("validated output payload must be a JSON object")
        object.__setattr__(self, "payload", normalized)


@dataclass(frozen=True)
class SchedulerJobRecord:
    run_id: str
    logical_job_id: str
    input_revision_id: str
    cache_key: str
    state: LogicalJobState
    attempt_count: int
    artifact_id: str | None = None
    error_code: str | None = None
    cache_replay: bool = False

    def __post_init__(self) -> None:
        if self.attempt_count < 0:
            raise ValueError("scheduler job attempt count cannot be negative")
        _validate_durable_error(self.error_code)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "run_id": self.run_id,
            "logical_job_id": self.logical_job_id,
            "input_revision_id": self.input_revision_id,
            "cache_key": self.cache_key,
            "state": self.state.value,
            "attempt_count": self.attempt_count,
            "artifact_id": self.artifact_id,
            "error_code": self.error_code,
            "cache_replay": self.cache_replay,
        }


@dataclass(frozen=True)
class SchedulerAttemptRecord:
    attempt_id: str
    run_id: str
    logical_job_id: str
    attempt_number: int
    batch_id: str
    outcome: AttemptOutcome
    provider: ProviderIdentity
    metrics: AttemptMetrics
    error_code: str | None = None
    validated_claim_count: int = 0
    invalid_claim_count: int = 0

    def __post_init__(self) -> None:
        if self.attempt_number < 1:
            raise ValueError("scheduler attempt number must be positive")
        if self.validated_claim_count < 0 or self.invalid_claim_count < 0:
            raise ValueError("scheduler attempt claim counts cannot be negative")
        _validate_durable_error(self.error_code)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "attempt_id": self.attempt_id,
            "run_id": self.run_id,
            "logical_job_id": self.logical_job_id,
            "attempt_number": self.attempt_number,
            "batch_id": self.batch_id,
            "outcome": self.outcome.value,
            "provider": self.provider.to_dict(),
            "metrics": self.metrics.to_dict(),
            "error_code": self.error_code,
            "validated_claim_count": self.validated_claim_count,
            "invalid_claim_count": self.invalid_claim_count,
        }


@dataclass(frozen=True)
class SchedulerBatchRecord:
    run_id: str
    batch_id: str
    logical_job_ids: tuple[str, ...]
    split_path: tuple[int, ...]
    state: SchedulerBatchState
    provider_call_number: int
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.provider_call_number < 1:
            raise ValueError("provider call number must be positive")
        _validate_durable_error(self.error_code)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "run_id": self.run_id,
            "batch_id": self.batch_id,
            "logical_job_ids": list(self.logical_job_ids),
            "split_path": list(self.split_path),
            "state": self.state.value,
            "provider_call_number": self.provider_call_number,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class SchedulerUsage:
    provider_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_ms: int = 0
    cost_micros: int | None = 0
    peak_concurrency: int = 0

    def __post_init__(self) -> None:
        for name in (
            "provider_calls",
            "input_tokens",
            "output_tokens",
            "elapsed_ms",
            "peak_concurrency",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.cost_micros is not None and (
            not isinstance(self.cost_micros, int)
            or isinstance(self.cost_micros, bool)
            or self.cost_micros < 0
        ):
            raise ValueError("cost_micros must be non-negative when supplied")

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "provider_calls": self.provider_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "elapsed_ms": self.elapsed_ms,
            "cost_micros": self.cost_micros,
            "peak_concurrency": self.peak_concurrency,
        }


@dataclass(frozen=True)
class SchedulerRunRecord:
    run_id: str
    consent_manifest_id: str
    state: SchedulerRunState
    provider: ProviderIdentity
    usage: SchedulerUsage
    succeeded_jobs: int
    partial_jobs: int
    failed_jobs: int
    refused_jobs: int
    cancelled_jobs: int
    error_code: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "succeeded_jobs",
            "partial_jobs",
            "failed_jobs",
            "refused_jobs",
            "cancelled_jobs",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        _validate_durable_error(self.error_code)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "run_id": self.run_id,
            "consent_manifest_id": self.consent_manifest_id,
            "state": self.state.value,
            "provider": self.provider.to_dict(),
            "usage": self.usage.to_dict(),
            "succeeded_jobs": self.succeeded_jobs,
            "partial_jobs": self.partial_jobs,
            "failed_jobs": self.failed_jobs,
            "refused_jobs": self.refused_jobs,
            "cancelled_jobs": self.cancelled_jobs,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class SchedulerRunResult:
    record: SchedulerRunRecord
    jobs: tuple[SchedulerJobRecord, ...]


class SchedulerSink(Protocol):
    """Persistence seam; implementations serialize mutations and may use M13Persistence."""

    def lookup_exact_cache(self, job: ScheduledSceneJob) -> CacheReplay | None: ...

    def attempt_history(
        self,
        run_id: str,
        logical_job_id: str,
    ) -> tuple[AttemptOutcome, ...]: ...

    def record_job(self, record: SchedulerJobRecord) -> None: ...

    def record_attempt(self, record: SchedulerAttemptRecord) -> None: ...

    def record_batch(self, record: SchedulerBatchRecord) -> None: ...

    def publish_validated(
        self,
        job: ScheduledSceneJob,
        output: ValidatedLogicalOutput,
        attempt: SchedulerAttemptRecord,
        job_record: SchedulerJobRecord,
    ) -> None: ...

    def record_run(self, record: SchedulerRunRecord) -> None: ...


OutputValidator = Callable[[ScheduledSceneJob, Mapping[str, JsonValue]], ValidatedLogicalOutput]
CancelledCallback = Callable[[], bool]
Clock = Callable[[], float]


class NarrativeScheduler:
    """Cache-first bounded state machine for independent M13 logical jobs."""

    def __init__(
        self,
        provider: NarrativeProvider,
        sink: SchedulerSink,
        policy: SchedulerPolicy,
        *,
        clock: Clock = monotonic,
    ) -> None:
        self._provider = provider
        self._sink = sink
        self._policy = policy
        self._clock = clock

    def run(
        self,
        jobs: Sequence[ScheduledSceneJob],
        consent: ConsentManifest,
        validate_output: OutputValidator,
        *,
        cancelled: CancelledCallback = lambda: False,
        initial_usage: SchedulerUsage | None = None,
    ) -> SchedulerRunResult:
        ordered = tuple(sorted(jobs, key=lambda item: (item.ordinal, item.logical_job_id)))
        self._validate_start(ordered, consent)
        started_at = self._clock()
        histories = {
            job.logical_job_id: list(
                self._sink.attempt_history(consent.run_id, job.logical_job_id)
            )
            for job in ordered
        }
        records: dict[str, SchedulerJobRecord] = {}
        job_by_id = {job.logical_job_id: job for job in ordered}
        usage = SchedulerUsage(cost_micros=0) if initial_usage is None else initial_usage

        if cancelled():
            self._mark_unfinished(
                ordered,
                records,
                histories,
                consent.run_id,
                LogicalJobState.CANCELLED,
                "cancelled",
            )
            return self._finish(
                ordered,
                records,
                consent,
                usage,
                started_at,
                SchedulerRunState.CANCELLED,
                "cancelled",
            )

        misses: list[ScheduledSceneJob] = []
        for job in ordered:
            replay = self._sink.lookup_exact_cache(job)
            if replay is None:
                history = histories[job.logical_job_id]
                if any(
                    outcome in {AttemptOutcome.ACCEPTED, AttemptOutcome.PARTIAL}
                    for outcome in history
                ):
                    raise SchedulerConfigurationError(
                        "validated attempt history is missing its exact accepted cache entry"
                    )
                misses.append(job)
                record = self._job_record(
                    consent.run_id,
                    job,
                    LogicalJobState.QUEUED,
                    len(histories[job.logical_job_id]),
                )
            else:
                state = (
                    LogicalJobState.PARTIAL
                    if replay.publication is ArtifactPublication.PARTIAL
                    else LogicalJobState.SUCCEEDED
                )
                record = self._job_record(
                    consent.run_id,
                    job,
                    state,
                    len(histories[job.logical_job_id]),
                    artifact_id=replay.artifact_id,
                    cache_replay=True,
                )
            records[job.logical_job_id] = record
            self._sink.record_job(record)

        if not misses:
            cache_state = self._derive_state(records.values())
            return self._finish(
                ordered,
                records,
                consent,
                usage,
                started_at,
                cache_state,
                None,
            )

        initial_batches = list(
            pack_scene_jobs(tuple(job.batchable() for job in misses), self._policy.batch_limits)
        )
        if consent.estimate.provider_call_count < len(initial_batches):
            raise SchedulerConfigurationError(
                "consent underestimates deterministic provider calls after batching"
            )
        status = self._provider.status()
        if not status.available:
            self._mark_unfinished(
                misses,
                records,
                histories,
                consent.run_id,
                LogicalJobState.REFUSED,
                "provider_refusal",
            )
            return self._finish(
                ordered,
                records,
                consent,
                usage,
                started_at,
                SchedulerRunState.FAILED,
                "provider_refusal",
            )
        expected_provider = consent.provider
        if (
            status.provider != expected_provider.provider
            or status.adapter != expected_provider.adapter
            or status.adapter_version != expected_provider.adapter_version
        ):
            self._mark_unfinished(
                misses,
                records,
                histories,
                consent.run_id,
                LogicalJobState.FAILED,
                "internal_error",
            )
            return self._finish(
                ordered,
                records,
                consent,
                usage,
                started_at,
                SchedulerRunState.FAILED,
                "internal_error",
            )

        queue = initial_batches
        forced_state: SchedulerRunState | None = None
        forced_error: str | None = None
        while queue:
            if cancelled():
                self._provider.cancel()
                forced_state = SchedulerRunState.CANCELLED
                forced_error = "cancelled"
                break
            batch = queue.pop(0)
            active_ids = tuple(
                job_id
                for job_id in batch.logical_job_ids
                if records[job_id].state not in _TERMINAL_JOB_STATES
            )
            if not active_ids:
                continue
            if active_ids != batch.logical_job_ids:
                retry_batches = self._singleton_batches(batch, active_ids)
                queue[0:0] = list(retry_batches)
                continue

            limit_error = self._preflight_limit(
                batch,
                job_by_id,
                consent,
                usage,
                started_at,
            )
            if limit_error is not None:
                forced_state = SchedulerRunState.HARD_LIMIT
                forced_error = "hard_limit"
                break

            call_number = usage.provider_calls + 1
            attempt_numbers: dict[str, int] = {}
            for job_id in batch.logical_job_ids:
                history = histories[job_id]
                attempt_numbers[job_id] = len(history) + 1
                running = self._job_record(
                    consent.run_id,
                    job_by_id[job_id],
                    LogicalJobState.RUNNING,
                    len(history),
                )
                records[job_id] = running
                self._sink.record_job(running)
            self._sink.record_batch(
                self._batch_record(
                    consent.run_id,
                    batch,
                    SchedulerBatchState.RUNNING,
                    call_number,
                )
            )
            request = self._request(batch, job_by_id, consent, started_at)
            usage = SchedulerUsage(
                provider_calls=call_number,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                elapsed_ms=usage.elapsed_ms,
                cost_micros=usage.cost_micros,
                peak_concurrency=max(usage.peak_concurrency, 1),
            )
            try:
                response = self._provider.submit(request, cancelled)
            except NarrativeProviderError as exc:
                if isinstance(exc, ProviderCancelledError):
                    self._provider.cancel()
                action = self._handle_provider_error(
                    exc,
                    batch,
                    job_by_id,
                    records,
                    histories,
                    attempt_numbers,
                    consent,
                    call_number,
                )
                queue[0:0] = list(action.retry_batches)
                if action.stop_state is not None:
                    forced_state = action.stop_state
                    forced_error = action.stop_error
                    break
                continue

            usage = self._add_usage(usage, response.usage, started_at)
            response_error = self._response_binding_error(
                response,
                request,
                consent,
                batch,
                job_by_id,
            )
            if response_error is not None:
                for job_id in batch.logical_job_ids:
                    attempt = self._attempt_record(
                        consent.run_id,
                        job_by_id[job_id],
                        attempt_numbers[job_id],
                        batch.batch_id,
                        AttemptOutcome.MALFORMED,
                        consent.provider,
                        error_code="internal_error",
                    )
                    histories[job_id].append(attempt.outcome)
                    self._sink.record_attempt(attempt)
                    failed = self._job_record(
                        consent.run_id,
                        job_by_id[job_id],
                        LogicalJobState.FAILED,
                        len(histories[job_id]),
                        error_code="internal_error",
                    )
                    records[job_id] = failed
                    self._sink.record_job(failed)
                self._sink.record_batch(
                    self._batch_record(
                        consent.run_id,
                        batch,
                        SchedulerBatchState.FAILED,
                        call_number,
                        "internal_error",
                    )
                )
                forced_state = SchedulerRunState.FAILED
                forced_error = "internal_error"
                break

            postflight_error = self._postflight_limit(consent, usage, response.usage)
            if postflight_error is not None:
                for job_id in batch.logical_job_ids:
                    attempt = self._attempt_record(
                        consent.run_id,
                        job_by_id[job_id],
                        attempt_numbers[job_id],
                        batch.batch_id,
                        AttemptOutcome.HARD_LIMIT,
                        consent.provider,
                        error_code="hard_limit",
                    )
                    histories[job_id].append(attempt.outcome)
                    self._sink.record_attempt(attempt)
                self._sink.record_batch(
                    self._batch_record(
                        consent.run_id,
                        batch,
                        SchedulerBatchState.HARD_LIMIT,
                        call_number,
                        "hard_limit",
                    )
                )
                forced_state = SchedulerRunState.HARD_LIMIT
                forced_error = "hard_limit"
                break

            if cancelled():
                self._provider.cancel()
                for job_id in batch.logical_job_ids:
                    attempt = self._attempt_record(
                        consent.run_id,
                        job_by_id[job_id],
                        attempt_numbers[job_id],
                        batch.batch_id,
                        AttemptOutcome.CANCELLED,
                        consent.provider,
                        error_code="cancelled",
                    )
                    histories[job_id].append(attempt.outcome)
                    self._sink.record_attempt(attempt)
                self._sink.record_batch(
                    self._batch_record(
                        consent.run_id,
                        batch,
                        SchedulerBatchState.CANCELLED,
                        call_number,
                        "cancelled",
                    )
                )
                forced_state = SchedulerRunState.CANCELLED
                forced_error = "cancelled"
                break

            evaluation, validated = self._evaluate_response(
                batch,
                response.items,
                job_by_id,
                validate_output,
            )
            metric_shares = self._metric_shares(batch, job_by_id, response.usage)
            if evaluation.whole_batch_unusable:
                retryable: list[str] = []
                for job_id in batch.logical_job_ids:
                    attempt = self._attempt_record(
                        consent.run_id,
                        job_by_id[job_id],
                        attempt_numbers[job_id],
                        batch.batch_id,
                        AttemptOutcome.MALFORMED,
                        consent.provider,
                        metrics=metric_shares[job_id],
                        error_code="invalid_output",
                    )
                    histories[job_id].append(attempt.outcome)
                    self._sink.record_attempt(attempt)
                    if self._eligible_malformed(histories[job_id]):
                        retryable.append(job_id)
                        queued = self._job_record(
                            consent.run_id,
                            job_by_id[job_id],
                            LogicalJobState.QUEUED,
                            len(histories[job_id]),
                            error_code="invalid_output",
                        )
                        records[job_id] = queued
                        self._sink.record_job(queued)
                    else:
                        failed = self._job_record(
                            consent.run_id,
                            job_by_id[job_id],
                            LogicalJobState.FAILED,
                            len(histories[job_id]),
                            error_code="invalid_output",
                        )
                        records[job_id] = failed
                        self._sink.record_job(failed)
                retry_batches = self._split_or_singletons(batch, tuple(retryable))
                queue[0:0] = list(retry_batches)
                unusable_state = (
                    SchedulerBatchState.SPLIT
                    if retry_batches
                    else SchedulerBatchState.FAILED
                )
                self._sink.record_batch(
                    self._batch_record(
                        consent.run_id,
                        batch,
                        unusable_state,
                        call_number,
                        "batch_unusable",
                    )
                )
                continue

            retry_ids: list[str] = []
            valid_count = 0
            processed_ids: set[str] = set()
            for outcome in evaluation.known_outcomes:
                job_id = cast(str, outcome.logical_job_id)
                job = job_by_id[job_id]
                metrics = metric_shares[job_id]
                if cancelled():
                    self._provider.cancel()
                    for pending_id in batch.logical_job_ids:
                        if pending_id in processed_ids:
                            continue
                        attempt = self._attempt_record(
                            consent.run_id,
                            job_by_id[pending_id],
                            attempt_numbers[pending_id],
                            batch.batch_id,
                            AttemptOutcome.CANCELLED,
                            consent.provider,
                            metrics=metric_shares[pending_id],
                            error_code="cancelled",
                        )
                        histories[pending_id].append(attempt.outcome)
                        self._sink.record_attempt(attempt)
                    forced_state = SchedulerRunState.CANCELLED
                    forced_error = "cancelled"
                    break
                if outcome.status is BatchItemStatus.VALID:
                    output = validated[job_id]
                    attempt_outcome = (
                        AttemptOutcome.PARTIAL
                        if output.publication is ArtifactPublication.PARTIAL
                        else AttemptOutcome.ACCEPTED
                    )
                    attempt = self._attempt_record(
                        consent.run_id,
                        job,
                        attempt_numbers[job_id],
                        batch.batch_id,
                        attempt_outcome,
                        consent.provider,
                        metrics=metrics,
                        validated_claim_count=output.validated_claim_count,
                        invalid_claim_count=output.invalid_claim_count,
                    )
                    state = (
                        LogicalJobState.PARTIAL
                        if output.publication is ArtifactPublication.PARTIAL
                        else LogicalJobState.SUCCEEDED
                    )
                    job_record = self._job_record(
                        consent.run_id,
                        job,
                        state,
                        len(histories[job_id]) + 1,
                        artifact_id=output.artifact_id,
                    )
                    self._sink.publish_validated(job, output, attempt, job_record)
                    histories[job_id].append(attempt.outcome)
                    records[job_id] = job_record
                    processed_ids.add(job_id)
                    valid_count += 1
                    continue

                refusal_code = self._item_refusal_code(outcome, response.items)
                if refusal_code is not None:
                    provider_refusal = refusal_code.startswith("provider_")
                    attempt = self._attempt_record(
                        consent.run_id,
                        job,
                        attempt_numbers[job_id],
                        batch.batch_id,
                        (
                            AttemptOutcome.PROVIDER_REFUSAL
                            if provider_refusal
                            else AttemptOutcome.CONTENT_REFUSAL
                        ),
                        consent.provider,
                        metrics=metrics,
                        error_code=(
                            "provider_refusal" if provider_refusal else "content_refusal"
                        ),
                    )
                    histories[job_id].append(attempt.outcome)
                    self._sink.record_attempt(attempt)
                    refused = self._job_record(
                        consent.run_id,
                        job,
                        LogicalJobState.REFUSED,
                        len(histories[job_id]),
                        error_code=(
                            "provider_refusal" if provider_refusal else "content_refusal"
                        ),
                    )
                    records[job_id] = refused
                    self._sink.record_job(refused)
                    processed_ids.add(job_id)
                    continue

                attempt = self._attempt_record(
                    consent.run_id,
                    job,
                    attempt_numbers[job_id],
                    batch.batch_id,
                    AttemptOutcome.MALFORMED,
                    consent.provider,
                    metrics=metrics,
                    error_code="invalid_output",
                )
                histories[job_id].append(attempt.outcome)
                self._sink.record_attempt(attempt)
                if self._eligible_malformed(histories[job_id]):
                    retry_ids.append(job_id)
                    queued = self._job_record(
                        consent.run_id,
                        job,
                        LogicalJobState.QUEUED,
                        len(histories[job_id]),
                        error_code="invalid_output",
                    )
                    records[job_id] = queued
                    self._sink.record_job(queued)
                else:
                    failed = self._job_record(
                        consent.run_id,
                        job,
                        LogicalJobState.FAILED,
                        len(histories[job_id]),
                        error_code="invalid_output",
                    )
                    records[job_id] = failed
                    self._sink.record_job(failed)
                processed_ids.add(job_id)

            if forced_state is not None:
                self._sink.record_batch(
                    self._batch_record(
                        consent.run_id,
                        batch,
                        SchedulerBatchState.CANCELLED,
                        call_number,
                        "cancelled",
                    )
                )
                break
            retry_batches = self._singleton_batches(batch, tuple(retry_ids))
            queue[0:0] = list(retry_batches)
            if valid_count == len(batch.items):
                batch_state = SchedulerBatchState.SUCCEEDED
            elif valid_count:
                batch_state = SchedulerBatchState.PARTIAL
            elif retry_batches:
                batch_state = SchedulerBatchState.RETRYING
            else:
                batch_state = SchedulerBatchState.FAILED
            self._sink.record_batch(
                self._batch_record(
                    consent.run_id,
                    batch,
                    batch_state,
                    call_number,
                )
            )

        if forced_state is SchedulerRunState.CANCELLED:
            self._mark_unfinished(
                ordered,
                records,
                histories,
                consent.run_id,
                LogicalJobState.CANCELLED,
                "cancelled",
            )
        elif forced_state is SchedulerRunState.HARD_LIMIT:
            self._mark_unfinished(
                ordered,
                records,
                histories,
                consent.run_id,
                LogicalJobState.FAILED,
                "hard_limit",
            )
        elif forced_state is SchedulerRunState.FAILED:
            self._mark_unfinished(
                ordered,
                records,
                histories,
                consent.run_id,
                LogicalJobState.FAILED,
                "internal_error",
            )

        run_state = forced_state or self._derive_state(records.values())
        return self._finish(
            ordered,
            records,
            consent,
            usage,
            started_at,
            run_state,
            forced_error,
        )

    def _validate_start(
        self,
        jobs: tuple[ScheduledSceneJob, ...],
        consent: ConsentManifest,
    ) -> None:
        if not consent.consent_granted:
            raise SchedulerConfigurationError("cloud consent is disabled")
        if not jobs:
            raise SchedulerConfigurationError("a scheduler run requires at least one logical job")
        ids = tuple(job.logical_job_id for job in jobs)
        if len(ids) != len(set(ids)):
            raise SchedulerConfigurationError("logical job IDs must be unique")
        ordinals = tuple(job.ordinal for job in jobs)
        if len(ordinals) != len(set(ordinals)):
            raise SchedulerConfigurationError("logical transport ordinals must be unique")
        if consent.estimate.logical_job_count < len(jobs):
            raise SchedulerConfigurationError("run exceeds the consented logical-job count")
        scopes = set(consent.selected_scope_ids)
        if any(job.scope_id not in scopes for job in jobs):
            raise SchedulerConfigurationError("a logical job is outside the consented scope")
        if any(job.cache_identity.provider != consent.provider for job in jobs):
            raise SchedulerConfigurationError("a cache identity differs from consented provider")
        prompt_versions = {job.cache_identity.prompt_template_version for job in jobs}
        schema_versions = {job.cache_identity.response_schema_version for job in jobs}
        if len(prompt_versions) != 1 or len(schema_versions) != 1:
            raise SchedulerConfigurationError(
                "one transport run requires one prompt and response schema version"
            )
        limits = consent.limits
        estimate = consent.estimate
        if estimate.provider_call_count > limits.max_provider_calls:
            raise SchedulerConfigurationError("estimated calls exceed the consented call limit")
        if estimate.input_tokens > limits.max_input_tokens:
            raise SchedulerConfigurationError("estimated input tokens exceed consent")
        if estimate.output_tokens > limits.max_output_tokens:
            raise SchedulerConfigurationError("estimated output tokens exceed consent")
        if estimate.input_tokens + estimate.output_tokens > limits.max_total_tokens:
            raise SchedulerConfigurationError("estimated total tokens exceed consent")
        if limits.max_cost_micros is not None:
            if estimate.cost_confidence is not CostConfidence.RELIABLE:
                raise SchedulerConfigurationError(
                    "a hard cost limit requires reliable cost accounting"
                )
            if (
                estimate.estimated_cost_micros is None
                or estimate.estimated_cost_micros > limits.max_cost_micros
                or any(job.estimated_cost_micros is None for job in jobs)
            ):
                raise SchedulerConfigurationError("estimated cost is not safely bounded")

    def _preflight_limit(
        self,
        batch: TransportBatch,
        jobs: Mapping[str, ScheduledSceneJob],
        consent: ConsentManifest,
        usage: SchedulerUsage,
        started_at: float,
    ) -> str | None:
        limits = consent.limits
        estimated_input = sum(
            jobs[job_id].estimated_input_tokens for job_id in batch.logical_job_ids
        )
        estimated_output = sum(
            jobs[job_id].estimated_output_tokens for job_id in batch.logical_job_ids
        )
        if usage.provider_calls + 1 > limits.max_provider_calls:
            return "call_limit"
        if usage.input_tokens + estimated_input > limits.max_input_tokens:
            return "input_token_limit"
        if usage.output_tokens + estimated_output > limits.max_output_tokens:
            return "output_token_limit"
        if usage.total_tokens + estimated_input + estimated_output > limits.max_total_tokens:
            return "total_token_limit"
        if self._clock() - started_at >= limits.timeout_seconds:
            return "time_limit"
        if limits.max_concurrency < 1:
            return "concurrency_limit"
        if limits.max_cost_micros is not None:
            current = usage.cost_micros
            estimated_costs = [
                jobs[job_id].estimated_cost_micros for job_id in batch.logical_job_ids
            ]
            if current is None or any(cost is None for cost in estimated_costs):
                return "cost_unavailable"
            if current + sum(cast(int, cost) for cost in estimated_costs) > limits.max_cost_micros:
                return "cost_limit"
        return None

    def _postflight_limit(
        self,
        consent: ConsentManifest,
        usage: SchedulerUsage,
        latest: ProviderUsage,
    ) -> str | None:
        limits = consent.limits
        if usage.input_tokens > limits.max_input_tokens:
            return "input_token_limit"
        if usage.output_tokens > limits.max_output_tokens:
            return "output_token_limit"
        if usage.total_tokens > limits.max_total_tokens:
            return "total_token_limit"
        if usage.elapsed_ms > limits.timeout_seconds * 1_000:
            return "time_limit"
        if limits.max_cost_micros is not None:
            if latest.cost_micros is None or usage.cost_micros is None:
                return "cost_unavailable"
            if usage.cost_micros > limits.max_cost_micros:
                return "cost_limit"
        return None

    def _request(
        self,
        batch: TransportBatch,
        jobs: Mapping[str, ScheduledSceneJob],
        consent: ConsentManifest,
        started_at: float,
    ) -> ProviderRequest:
        remaining = consent.limits.timeout_seconds - (self._clock() - started_at)
        return ProviderRequest(
            request_id=batch.batch_id,
            consent_manifest_id=consent.manifest_id,
            requested_model=consent.provider.requested_model,
            settings=consent.provider.settings,
            items=tuple(
                ProviderBatchItem(
                    logical_job_id=job_id,
                    input_revision_id=jobs[job_id].input_revision_id,
                    payload=jobs[job_id].provider_input,
                )
                for job_id in batch.logical_job_ids
            ),
            timeout_seconds=max(0.001, remaining),
            maximum_output_bytes=self._policy.maximum_output_bytes_per_call,
            maximum_input_bytes=self._policy.maximum_input_bytes_per_call,
        )

    def _response_binding_error(
        self,
        response: ProviderResponse,
        request: ProviderRequest,
        consent: ConsentManifest,
        batch: TransportBatch,
        jobs: Mapping[str, ScheduledSceneJob],
    ) -> str | None:
        if response.request_id != request.request_id:
            return "provider_request_identity_mismatch"
        if response.provider != consent.provider:
            return "provider_identity_mismatch"
        expected_jobs = {job.logical_job_id: job for job in request.items}
        if tuple(expected_jobs) != batch.logical_job_ids:
            return "provider_request_ownership_mismatch"
        for item in request.items:
            scheduled = jobs[item.logical_job_id]
            if item.input_revision_id != scheduled.input_revision_id:
                return "provider_input_revision_mismatch"
            if response.prompt_template_version != scheduled.cache_identity.prompt_template_version:
                return "provider_prompt_template_mismatch"
            if response.response_schema_version != scheduled.cache_identity.response_schema_version:
                return "provider_response_schema_mismatch"
        return None

    def _evaluate_response(
        self,
        batch: TransportBatch,
        items: tuple[ProviderOutputItem, ...],
        jobs: Mapping[str, ScheduledSceneJob],
        validate_output: OutputValidator,
    ) -> tuple[BatchEvaluation, dict[str, ValidatedLogicalOutput]]:
        validated: dict[str, ValidatedLogicalOutput] = {}
        raw_items: list[dict[str, object]] = []
        for index, item in enumerate(items):
            logical_job_id = item.logical_job_id
            output: object
            if item.transport_index != index:
                logical_job_id = None
                output = None
            elif item.error_code is not None:
                output = {"scheduler_error_code": item.error_code}
            else:
                output = item.payload
            raw_items.append({"logical_job_id": logical_job_id, "output": output})

        def validate(logical_job_id: str, value: object) -> object:
            if not isinstance(value, Mapping) or "scheduler_error_code" in value:
                raise ValueError("provider item is not independently publishable")
            normalized = storage.decode_json(storage.canonical_json(dict(value)))
            if not isinstance(normalized, dict):
                raise ValueError("provider item is not a JSON object")
            result = validate_output(
                jobs[logical_job_id],
                cast(Mapping[str, JsonValue], normalized),
            )
            if result.logical_job_id != logical_job_id:
                raise ValueError("validated output changed logical ownership")
            validated[logical_job_id] = result
            return result

        evaluation = evaluate_batch_output(batch, {"items": raw_items}, validate)
        return evaluation, validated

    def _handle_provider_error(
        self,
        error: NarrativeProviderError,
        batch: TransportBatch,
        jobs: Mapping[str, ScheduledSceneJob],
        records: dict[str, SchedulerJobRecord],
        histories: dict[str, list[AttemptOutcome]],
        attempt_numbers: Mapping[str, int],
        consent: ConsentManifest,
        call_number: int,
    ) -> _ErrorAction:
        if isinstance(error, ProviderCancelledError):
            outcome = AttemptOutcome.CANCELLED
            safe_code = "cancelled"
            terminal_state = LogicalJobState.CANCELLED
        elif isinstance(error, ProviderTimeoutError):
            outcome = AttemptOutcome.TIMEOUT
            safe_code = "timeout"
            terminal_state = LogicalJobState.FAILED
        elif isinstance(error, ProviderIdentityMismatchError | ProviderPolicyViolationError):
            outcome = AttemptOutcome.MALFORMED
            safe_code = "internal_error"
            terminal_state = LogicalJobState.FAILED
        elif isinstance(error, ProviderLimitError):
            outcome = AttemptOutcome.HARD_LIMIT
            safe_code = "hard_limit"
            terminal_state = LogicalJobState.FAILED
        elif isinstance(error, ProviderRefusalError):
            outcome = AttemptOutcome.PROVIDER_REFUSAL
            safe_code = "provider_refusal"
            terminal_state = LogicalJobState.REFUSED
        elif isinstance(error, ProviderOutputError):
            outcome = AttemptOutcome.MALFORMED
            safe_code = "invalid_output"
            terminal_state = LogicalJobState.FAILED
        elif error.transient:
            outcome = AttemptOutcome.TRANSIENT_FAILURE
            safe_code = "transient_failure"
            terminal_state = LogicalJobState.FAILED
        else:
            outcome = AttemptOutcome.MALFORMED
            safe_code = "internal_error"
            terminal_state = LogicalJobState.FAILED

        eligible: list[str] = []
        for job_id in batch.logical_job_ids:
            attempt = self._attempt_record(
                consent.run_id,
                jobs[job_id],
                attempt_numbers[job_id],
                batch.batch_id,
                outcome,
                consent.provider,
                error_code=safe_code,
            )
            histories[job_id].append(outcome)
            self._sink.record_attempt(attempt)
            if self._eligible_error(error, histories[job_id], len(batch.items)):
                eligible.append(job_id)
                queued = self._job_record(
                    consent.run_id,
                    jobs[job_id],
                    LogicalJobState.QUEUED,
                    len(histories[job_id]),
                    error_code=safe_code,
                )
                records[job_id] = queued
                self._sink.record_job(queued)
            else:
                terminal = self._job_record(
                    consent.run_id,
                    jobs[job_id],
                    terminal_state,
                    len(histories[job_id]),
                    error_code=safe_code,
                )
                records[job_id] = terminal
                self._sink.record_job(terminal)

        if isinstance(error, ProviderCancelledError):
            batch_state = SchedulerBatchState.CANCELLED
            stop_state = SchedulerRunState.CANCELLED
            stop_error = "cancelled"
            retries: tuple[TransportBatch, ...] = ()
        elif isinstance(error, ProviderIdentityMismatchError | ProviderPolicyViolationError):
            batch_state = SchedulerBatchState.FAILED
            stop_state = SchedulerRunState.FAILED
            stop_error = "internal_error"
            retries = ()
        elif eligible:
            should_split = isinstance(
                error,
                ProviderRefusalError | ProviderLimitError | ProviderOutputError,
            ) and len(batch.items) > 1
            if should_split:
                retries = self._split_or_singletons(batch, tuple(eligible))
            elif error.transient and len(eligible) == len(batch.items):
                retries = (batch,)
            else:
                retries = self._singleton_batches(batch, tuple(eligible))
            batch_state = (
                SchedulerBatchState.SPLIT
                if should_split
                else SchedulerBatchState.RETRYING
            )
            stop_state = None
            stop_error = None
        else:
            batch_state = (
                SchedulerBatchState.HARD_LIMIT
                if isinstance(error, ProviderLimitError)
                else SchedulerBatchState.FAILED
            )
            stop_state = (
                SchedulerRunState.HARD_LIMIT
                if isinstance(error, ProviderLimitError)
                else None
            )
            stop_error = "hard_limit" if stop_state is not None else None
            retries = ()
        self._sink.record_batch(
            self._batch_record(
                consent.run_id,
                batch,
                batch_state,
                call_number,
                safe_code,
            )
        )
        return _ErrorAction(retries, stop_state, stop_error)

    def _eligible_error(
        self,
        error: NarrativeProviderError,
        history: Sequence[AttemptOutcome],
        batch_size: int,
    ) -> bool:
        if len(history) >= self._policy.maximum_attempts_per_job:
            return False
        if isinstance(
            error,
            ProviderCancelledError
            | ProviderIdentityMismatchError
            | ProviderPolicyViolationError,
        ):
            return False
        if isinstance(
            error,
            ProviderRefusalError | ProviderLimitError,
        ):
            return batch_size > 1
        if isinstance(error, ProviderOutputError):
            return batch_size > 1 or self._eligible_malformed(history)
        if error.transient:
            transient = sum(
                outcome in {AttemptOutcome.TRANSIENT_FAILURE, AttemptOutcome.TIMEOUT}
                for outcome in history
            )
            return transient < self._policy.maximum_transient_attempts_per_job
        return False

    def _eligible_malformed(self, history: Sequence[AttemptOutcome]) -> bool:
        return (
            len(history) < self._policy.maximum_attempts_per_job
            and history.count(AttemptOutcome.MALFORMED)
            < self._policy.maximum_malformed_attempts_per_job
        )

    def _add_usage(
        self,
        current: SchedulerUsage,
        latest: ProviderUsage,
        started_at: float,
    ) -> SchedulerUsage:
        if current.cost_micros is None or latest.cost_micros is None:
            cost: int | None = None
        else:
            cost = current.cost_micros + latest.cost_micros
        return SchedulerUsage(
            provider_calls=current.provider_calls,
            input_tokens=current.input_tokens + latest.input_tokens,
            output_tokens=current.output_tokens + latest.output_tokens,
            elapsed_ms=max(latest.elapsed_ms, int((self._clock() - started_at) * 1_000)),
            cost_micros=cost,
            peak_concurrency=current.peak_concurrency,
        )

    def _metric_shares(
        self,
        batch: TransportBatch,
        jobs: Mapping[str, ScheduledSceneJob],
        usage: ProviderUsage,
    ) -> dict[str, AttemptMetrics]:
        ids = batch.logical_job_ids
        input_shares = _partition_integer(
            usage.input_tokens,
            tuple(jobs[job_id].estimated_input_tokens for job_id in ids),
        )
        output_shares = _partition_integer(
            usage.output_tokens,
            tuple(jobs[job_id].estimated_output_tokens for job_id in ids),
        )
        elapsed_shares = _partition_integer(usage.elapsed_ms, tuple(1 for _ in ids))
        cost_shares = (
            None
            if usage.cost_micros is None
            else _partition_integer(
                usage.cost_micros,
                tuple((jobs[job_id].estimated_cost_micros or 1) for job_id in ids),
            )
        )
        return {
            job_id: AttemptMetrics(
                input_tokens=input_shares[index],
                output_tokens=output_shares[index],
                elapsed_ms=elapsed_shares[index],
                cost_micros=None if cost_shares is None else cost_shares[index],
            )
            for index, job_id in enumerate(ids)
        }

    def _item_refusal_code(
        self,
        outcome: BatchItemOutcome,
        items: tuple[ProviderOutputItem, ...],
    ) -> str | None:
        if len(outcome.source_indexes) != 1:
            return None
        index = outcome.source_indexes[0]
        if not 0 <= index < len(items):
            return None
        code = items[index].error_code
        return code if code in _REFUSAL_CODES else None

    def _attempt_record(
        self,
        run_id: str,
        job: ScheduledSceneJob,
        attempt_number: int,
        batch_id: str,
        outcome: AttemptOutcome,
        provider: ProviderIdentity,
        *,
        metrics: AttemptMetrics | None = None,
        error_code: str | None = None,
        validated_claim_count: int = 0,
        invalid_claim_count: int = 0,
    ) -> SchedulerAttemptRecord:
        identity = {
            "run_id": run_id,
            "logical_job_id": job.logical_job_id,
            "attempt_number": attempt_number,
        }
        return SchedulerAttemptRecord(
            attempt_id=f"m13_attempt_{canonical_hash(identity)[:24]}",
            run_id=run_id,
            logical_job_id=job.logical_job_id,
            attempt_number=attempt_number,
            batch_id=batch_id,
            outcome=outcome,
            provider=provider,
            metrics=AttemptMetrics() if metrics is None else metrics,
            error_code=error_code,
            validated_claim_count=validated_claim_count,
            invalid_claim_count=invalid_claim_count,
        )

    def _job_record(
        self,
        run_id: str,
        job: ScheduledSceneJob,
        state: LogicalJobState,
        attempt_count: int,
        *,
        artifact_id: str | None = None,
        error_code: str | None = None,
        cache_replay: bool = False,
    ) -> SchedulerJobRecord:
        return SchedulerJobRecord(
            run_id=run_id,
            logical_job_id=job.logical_job_id,
            input_revision_id=job.input_revision_id,
            cache_key=job.cache_identity.key,
            state=state,
            attempt_count=attempt_count,
            artifact_id=artifact_id,
            error_code=error_code,
            cache_replay=cache_replay,
        )

    def _batch_record(
        self,
        run_id: str,
        batch: TransportBatch,
        state: SchedulerBatchState,
        call_number: int,
        error_code: str | None = None,
    ) -> SchedulerBatchRecord:
        return SchedulerBatchRecord(
            run_id=run_id,
            batch_id=batch.batch_id,
            logical_job_ids=batch.logical_job_ids,
            split_path=batch.split_path,
            state=state,
            provider_call_number=call_number,
            error_code=error_code,
        )

    def _split_or_singletons(
        self,
        batch: TransportBatch,
        job_ids: tuple[str, ...],
    ) -> tuple[TransportBatch, ...]:
        if not job_ids:
            return ()
        if set(job_ids) == set(batch.logical_job_ids):
            split = split_transport_batch(batch)
            if split:
                return split
        return self._singleton_batches(batch, job_ids)

    def _singleton_batches(
        self,
        batch: TransportBatch,
        job_ids: tuple[str, ...],
    ) -> tuple[TransportBatch, ...]:
        wanted = set(job_ids)
        return tuple(
            leaf
            for leaf in recursive_singleton_batches(batch)
            if leaf.logical_job_ids[0] in wanted
        )

    def _mark_unfinished(
        self,
        jobs: Sequence[ScheduledSceneJob],
        records: dict[str, SchedulerJobRecord],
        histories: Mapping[str, Sequence[AttemptOutcome]],
        run_id: str,
        state: LogicalJobState,
        error_code: str,
    ) -> None:
        for job in jobs:
            current = records.get(job.logical_job_id)
            if current is not None and current.state in _TERMINAL_JOB_STATES:
                continue
            record = self._job_record(
                run_id,
                job,
                state,
                len(histories[job.logical_job_id]),
                error_code=error_code,
            )
            records[job.logical_job_id] = record
            self._sink.record_job(record)

    def _derive_state(self, records: Iterable[SchedulerJobRecord]) -> SchedulerRunState:
        states = Counter(record.state for record in records)
        accepted = states[LogicalJobState.SUCCEEDED] + states[LogicalJobState.PARTIAL]
        if accepted == sum(states.values()) and not states[LogicalJobState.PARTIAL]:
            return SchedulerRunState.SUCCEEDED
        if accepted:
            return SchedulerRunState.PARTIAL
        return SchedulerRunState.FAILED

    def _finish(
        self,
        jobs: Sequence[ScheduledSceneJob],
        records: Mapping[str, SchedulerJobRecord],
        consent: ConsentManifest,
        usage: SchedulerUsage,
        started_at: float,
        state: SchedulerRunState,
        error_code: str | None,
    ) -> SchedulerRunResult:
        final_usage = SchedulerUsage(
            provider_calls=usage.provider_calls,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            elapsed_ms=max(usage.elapsed_ms, int((self._clock() - started_at) * 1_000)),
            cost_micros=usage.cost_micros,
            peak_concurrency=usage.peak_concurrency,
        )
        states = Counter(record.state for record in records.values())
        run = SchedulerRunRecord(
            run_id=consent.run_id,
            consent_manifest_id=consent.manifest_id,
            state=state,
            provider=consent.provider,
            usage=final_usage,
            succeeded_jobs=states[LogicalJobState.SUCCEEDED],
            partial_jobs=states[LogicalJobState.PARTIAL],
            failed_jobs=states[LogicalJobState.FAILED],
            refused_jobs=states[LogicalJobState.REFUSED],
            cancelled_jobs=states[LogicalJobState.CANCELLED],
            error_code=error_code,
        )
        self._sink.record_run(run)
        return SchedulerRunResult(
            record=run,
            jobs=tuple(records[job.logical_job_id] for job in jobs),
        )


@dataclass(frozen=True)
class _ErrorAction:
    retry_batches: tuple[TransportBatch, ...]
    stop_state: SchedulerRunState | None
    stop_error: str | None


def _partition_integer(total: int, weights: tuple[int, ...]) -> tuple[int, ...]:
    """Partition an integer deterministically without duplicating batch metrics."""

    if not weights:
        return ()
    denominator = sum(weights)
    if denominator <= 0:
        weights = tuple(1 for _ in weights)
        denominator = len(weights)
    shares = [total * weight // denominator for weight in weights]
    remainder = total - sum(shares)
    for index in range(remainder):
        shares[index % len(shares)] += 1
    return tuple(shares)


def _validate_durable_error(error_code: str | None) -> None:
    if error_code is not None and error_code not in SANITIZED_ERROR_MESSAGES:
        raise ValueError("scheduler records require an allowlisted sanitized error code")
