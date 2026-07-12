"""Provider-neutral, resumable M07 scope orchestration.

Workers perform only provider calls.  Checkpoint mutation, cache publication, and
final assembly pass through one serialized sink so completion order cannot change
the resulting envelope.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Protocol

from renpy_story_mapper.organization.contracts import (
    M05_CLOUD_MODEL,
    M05_REASONING_PROFILE,
    CodexMode,
    OrganizationChunkResult,
    OrganizationProvider,
    OrganizationRequest,
    ProviderAttemptUsage,
)
from renpy_story_mapper.organization.errors import (
    InvalidProviderOutputError,
    OrganizationCancelledError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)


class CheckpointState(StrEnum):
    PENDING = "pending"
    CACHED_OR_IN_FLIGHT = "cached/in-flight"
    VALIDATED = "validated"
    FALLBACK = "fallback"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class RouteScope:
    """One complete deterministic route scope, ordered before any AI work."""

    ordinal: int
    request: OrganizationRequest
    fallback: OrganizationChunkResult | None = None


@dataclass(frozen=True)
class BudgetPolicy:
    soft_seconds: float | None = None
    hard_seconds: float | None = None
    soft_tokens: int | None = None
    hard_tokens: int | None = None
    hard_calls: int | None = None


@dataclass(frozen=True)
class SchedulerConfig:
    initial_workers: int = 8
    maximum_workers: int = 12
    ramp_after_successes: int = 2
    maximum_repairs: int = 2
    minimum_timeout_seconds: float = 15.0
    maximum_timeout_seconds: float = 300.0
    latency_backoff_seconds: float = 90.0
    budget: BudgetPolicy = field(default_factory=BudgetPolicy)
    provider_mode: CodexMode = CodexMode.CODEX_CHATGPT
    model: str = M05_CLOUD_MODEL
    reasoning_profile: str = M05_REASONING_PROFILE
    fast_mode: bool = False
    prompt_version: str = "m07-v1"
    schema_version: str = "m07-v1"

    def __post_init__(self) -> None:
        if not 1 <= self.initial_workers <= self.maximum_workers <= 12:
            raise ValueError("Scheduler workers must start between 1 and 12 and cap at 12.")
        if self.maximum_repairs != 2:
            raise ValueError("M07 permits exactly two concurrent repairs.")
        if self.provider_mode is not CodexMode.CODEX_CHATGPT:
            raise ValueError("M07 cloud analysis supports only the ChatGPT Codex boundary.")
        if (
            self.model != M05_CLOUD_MODEL
            or self.reasoning_profile != M05_REASONING_PROFILE
            or self.fast_mode
        ):
            raise ValueError("M07 analysis is locked to GPT-5.6 Luna, High, fast disabled.")


@dataclass(frozen=True)
class OutcomeEvent:
    sequence: int
    scope_id: str
    state: CheckpointState
    cache_identity: str
    error_code: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class ScopeEnvelope:
    ordinal: int
    scope_id: str
    state: CheckpointState
    cache_identity: str
    result: OrganizationChunkResult | None


@dataclass(frozen=True)
class ProgressSnapshot:
    total: int
    validated: int
    fallback: int
    failed: int
    cancelled: int
    pending: int
    ai_coverage: float
    technical_coverage: float
    calls: int
    input_tokens: int
    output_tokens: int
    eta_low_seconds: float | None
    eta_high_seconds: float | None
    partial: bool
    peak_workers: int


@dataclass(frozen=True)
class OrchestrationResult:
    envelopes: tuple[ScopeEnvelope, ...]
    progress: ProgressSnapshot


class CheckpointSink(Protocol):
    def checkpoint(self, scope_id: str) -> ScopeEnvelope | None: ...
    def cached(self, identity: str) -> OrganizationChunkResult | None: ...
    def event(
        self,
        scope: RouteScope,
        state: CheckpointState,
        identity: str,
        *,
        error_code: str | None = None,
        message: str | None = None,
    ) -> None: ...
    def attempt(self, scope_id: str, usage: ProviderAttemptUsage) -> None: ...
    def publish(self, envelope: ScopeEnvelope) -> None: ...
    def cache(self, identity: str, result: OrganizationChunkResult) -> None: ...
    def assemble(self, envelopes: Iterable[ScopeEnvelope]) -> tuple[ScopeEnvelope, ...]: ...


class InMemoryCheckpointSink:
    """Thread-safe reference sink used by tests and non-persistent callers."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sequence = 0
        self.checkpoints: dict[str, ScopeEnvelope] = {}
        self.cache_entries: dict[str, OrganizationChunkResult] = {}
        self.events: list[OutcomeEvent] = []
        self.attempts: list[tuple[str, ProviderAttemptUsage]] = []
        self.assembly_threads: list[int] = []

    def checkpoint(self, scope_id: str) -> ScopeEnvelope | None:
        with self._lock:
            return self.checkpoints.get(scope_id)

    def cached(self, identity: str) -> OrganizationChunkResult | None:
        with self._lock:
            return self.cache_entries.get(identity)

    def event(
        self,
        scope: RouteScope,
        state: CheckpointState,
        identity: str,
        *,
        error_code: str | None = None,
        message: str | None = None,
    ) -> None:
        with self._lock:
            self._sequence += 1
            self.events.append(
                OutcomeEvent(
                    self._sequence,
                    scope.request.scope_id,
                    state,
                    identity,
                    error_code,
                    message,
                )
            )

    def attempt(self, scope_id: str, usage: ProviderAttemptUsage) -> None:
        with self._lock:
            self.attempts.append((scope_id, usage))

    def publish(self, envelope: ScopeEnvelope) -> None:
        with self._lock:
            self.checkpoints[envelope.scope_id] = envelope

    def cache(self, identity: str, result: OrganizationChunkResult) -> None:
        with self._lock:
            self.cache_entries[identity] = result

    def assemble(self, envelopes: Iterable[ScopeEnvelope]) -> tuple[ScopeEnvelope, ...]:
        with self._lock:
            self.assembly_threads.append(threading.get_ident())
            return tuple(sorted(envelopes, key=lambda item: (item.ordinal, item.scope_id)))


def normalized_cache_identity(request: OrganizationRequest, config: SchedulerConfig) -> str:
    """Hash semantic input while excluding run/chunk/scope routing identifiers."""
    constraints = request.constraints
    material = {
        "provider_mode": config.provider_mode.value,
        "model": config.model,
        "reasoning_profile": config.reasoning_profile,
        "fast_mode": config.fast_mode,
        "prompt_version": config.prompt_version,
        "schema_version": config.schema_version,
        "stage": request.stage.value,
        "payload": request.payload,
        "ordered_member_ids": constraints.ordered_member_ids,
        "required_member_ids": sorted(constraints.required_member_ids),
        "context_member_ids": sorted(constraints.context_member_ids),
        "fact_ids": sorted(constraints.fact_ids),
        "evidence_ids": sorted(constraints.evidence_ids),
        "character_names": sorted(constraints.character_names),
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class _UsageLedger:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def record(self, usage: ProviderAttemptUsage) -> None:
        with self._lock:
            self.calls += 1
            self.input_tokens += usage.input_tokens or 0
            self.output_tokens += usage.output_tokens or 0

    def values(self) -> tuple[int, int, int]:
        with self._lock:
            return self.calls, self.input_tokens, self.output_tokens


ProviderFactory = Callable[[RouteScope], OrganizationProvider]
ProgressCallback = Callable[[ProgressSnapshot], None]


class ParallelOrganizationScheduler:
    """Run deterministic scopes concurrently and commit outcomes serially."""

    def __init__(
        self,
        provider_factory: ProviderFactory,
        sink: CheckpointSink,
        config: SchedulerConfig | None = None,
    ) -> None:
        self._provider_factory = provider_factory
        self._sink = sink
        self.config = config or SchedulerConfig()
        self._repair_semaphore = threading.Semaphore(self.config.maximum_repairs)

    def run(
        self,
        scopes: Iterable[RouteScope],
        *,
        consent_run_id: str,
        cancelled: Callable[[], bool] = lambda: False,
        progress: ProgressCallback | None = None,
    ) -> OrchestrationResult:
        ordered = tuple(sorted(scopes, key=lambda item: (item.ordinal, item.request.scope_id)))
        self._validate_scopes(ordered)
        started = time.monotonic()
        ledger = _UsageLedger()
        completed: dict[str, ScopeEnvelope] = {}
        pending: deque[tuple[RouteScope, str]] = deque()
        latencies: list[float] = []
        desired = self.config.initial_workers
        peak_workers = 0
        consecutive_successes = 0

        for scope in ordered:
            identity = normalized_cache_identity(scope.request, self.config)
            saved = self._sink.checkpoint(scope.request.scope_id)
            if (
                saved is not None
                and saved.state is CheckpointState.VALIDATED
                and saved.cache_identity == identity
            ):
                completed[scope.request.scope_id] = saved
                continue
            cached = self._sink.cached(identity)
            if cached is not None:
                self._sink.event(scope, CheckpointState.CACHED_OR_IN_FLIGHT, identity)
                envelope = ScopeEnvelope(
                    scope.ordinal,
                    scope.request.scope_id,
                    CheckpointState.VALIDATED,
                    identity,
                    cached,
                )
                self._commit(scope, envelope)
                completed[scope.request.scope_id] = envelope
                continue
            self._sink.event(scope, CheckpointState.PENDING, identity)
            pending.append((scope, identity))

        if pending:
            self._validate_transmission_consent(pending, consent_run_id)

        futures: dict[Future[OrganizationChunkResult], tuple[RouteScope, str, float]] = {}
        with ThreadPoolExecutor(max_workers=self.config.maximum_workers) as executor:
            while pending or futures:
                elapsed = time.monotonic() - started
                stop_reason = self._stop_reason(elapsed, ledger, cancelled)
                while pending and len(futures) < desired and stop_reason is None:
                    if not self._can_start(ledger, len(futures)):
                        stop_reason = "hard_budget"
                        break
                    scope, identity = pending.popleft()
                    timeout = self._adaptive_timeout(scope.request.timeout_seconds, latencies)
                    request = replace(scope.request, timeout_seconds=timeout)
                    scheduled_scope = replace(scope, request=request)
                    self._sink.event(scheduled_scope, CheckpointState.CACHED_OR_IN_FLIGHT, identity)
                    launched_at = time.monotonic()
                    future = executor.submit(
                        self._call_provider,
                        scheduled_scope,
                        ledger,
                        started,
                        cancelled,
                    )
                    futures[future] = (scheduled_scope, identity, launched_at)
                    peak_workers = max(peak_workers, len(futures))
                if not futures:
                    if stop_reason is not None:
                        break
                    continue
                done, _ = wait(tuple(futures), return_when=FIRST_COMPLETED, timeout=0.05)
                if not done:
                    self._emit_progress(
                        ordered,
                        completed,
                        len(pending) + len(futures),
                        ledger,
                        latencies,
                        peak_workers,
                        progress,
                    )
                    continue
                for future in done:
                    scope, identity, launched = futures.pop(future)
                    latency = time.monotonic() - launched
                    latencies.append(latency)
                    try:
                        result = future.result()
                    except Exception as exc:
                        budget_reason = self._stop_reason(
                            time.monotonic() - started, ledger, lambda: False
                        )
                        if (
                            isinstance(exc, OrganizationCancelledError)
                            and not cancelled()
                            and budget_reason is not None
                        ):
                            state = (
                                CheckpointState.FALLBACK
                                if scope.fallback is not None
                                else CheckpointState.FAILED
                            )
                            code = budget_reason
                            message = "The run budget stopped this scope."
                        else:
                            state, code, message = _sanitized_failure(
                                exc, scope.fallback is not None
                            )
                        outcome_result: OrganizationChunkResult | None = scope.fallback
                        envelope = ScopeEnvelope(
                            scope.ordinal,
                            scope.request.scope_id,
                            state,
                            identity,
                            outcome_result,
                        )
                        self._sink.event(scope, state, identity, error_code=code, message=message)
                        self._sink.publish(envelope)
                        completed[scope.request.scope_id] = envelope
                        consecutive_successes = 0
                        desired = max(1, desired // 2)
                    else:
                        envelope = ScopeEnvelope(
                            scope.ordinal,
                            scope.request.scope_id,
                            CheckpointState.VALIDATED,
                            identity,
                            result,
                        )
                        self._sink.cache(identity, result)
                        self._commit(scope, envelope)
                        completed[scope.request.scope_id] = envelope
                        consecutive_successes += 1
                        if latency >= self.config.latency_backoff_seconds:
                            desired = max(1, desired - 1)
                            consecutive_successes = 0
                        elif consecutive_successes >= self.config.ramp_after_successes:
                            desired = min(self.config.maximum_workers, desired + 1)
                            consecutive_successes = 0
                self._emit_progress(
                    ordered,
                    completed,
                    len(pending) + len(futures),
                    ledger,
                    latencies,
                    peak_workers,
                    progress,
                )

        final_reason = self._stop_reason(time.monotonic() - started, ledger, cancelled)
        while pending:
            scope, identity = pending.popleft()
            pending_result: OrganizationChunkResult | None
            if final_reason == "cancelled":
                state = CheckpointState.CANCELLED
                code = "cancelled"
                message = "Organization was cancelled; validated scopes were preserved."
                pending_result = None
            elif scope.fallback is not None:
                state = CheckpointState.FALLBACK
                code = final_reason or "soft_budget"
                message = "The scope used deterministic fallback after the run budget was reached."
                pending_result = scope.fallback
            else:
                state = CheckpointState.FAILED
                code = final_reason or "soft_budget"
                message = "The scope was not started because the run budget was reached."
                pending_result = None
            envelope = ScopeEnvelope(
                scope.ordinal, scope.request.scope_id, state, identity, pending_result
            )
            self._sink.event(scope, state, identity, error_code=code, message=message)
            self._sink.publish(envelope)
            completed[scope.request.scope_id] = envelope

        assembled = self._sink.assemble(completed.values())
        snapshot = self._snapshot(ordered, assembled, 0, ledger, latencies, peak_workers)
        if progress is not None:
            progress(snapshot)
        return OrchestrationResult(assembled, snapshot)

    def _call_provider(
        self,
        scope: RouteScope,
        ledger: _UsageLedger,
        run_started: float,
        cancelled: Callable[[], bool],
    ) -> OrganizationChunkResult:
        provider = self._provider_factory(scope)
        observed = 0

        def observe(usage: ProviderAttemptUsage) -> None:
            nonlocal observed
            observed += 1
            ledger.record(usage)
            self._sink.attempt(scope.request.scope_id, usage)

        observer_setter = getattr(provider, "set_attempt_observer", None)
        if callable(observer_setter):
            observer_setter(observe)
        semaphore_setter = getattr(provider, "set_repair_semaphore", None)
        if callable(semaphore_setter):
            semaphore_setter(self._repair_semaphore)
        launched = time.monotonic()
        try:
            result = provider.organize(
                scope.request,
                lambda _percent, _status: None,
                lambda: cancelled() or self._hard_budget_reached(run_started, ledger),
            )
        except Exception:
            if observed == 0:
                observe(
                    ProviderAttemptUsage(
                        attempt=1,
                        elapsed_ms=round((time.monotonic() - launched) * 1000),
                        outcome="failed",
                    )
                )
            raise
        if observed == 0:
            metadata = result.metadata
            observe(
                ProviderAttemptUsage(
                    attempt=1,
                    elapsed_ms=metadata.elapsed_ms if metadata is not None else 0,
                    outcome="validated",
                    input_tokens=metadata.input_tokens if metadata is not None else None,
                    output_tokens=metadata.output_tokens if metadata is not None else None,
                )
            )
        return result

    def _validate_scopes(self, scopes: tuple[RouteScope, ...]) -> None:
        seen: set[str] = set()
        for scope in scopes:
            request = scope.request
            if request.scope_id in seen:
                raise ValueError("Deterministic route scope IDs must be unique.")
            seen.add(request.scope_id)
            if request.model != self.config.model:
                raise ValueError(
                    "Every analysis scope requires exact GPT-5.6 Luna selection."
                )

    @staticmethod
    def _validate_transmission_consent(
        pending: Iterable[tuple[RouteScope, str]], consent_run_id: str
    ) -> None:
        if not consent_run_id or consent_run_id != consent_run_id.strip():
            raise ValueError("Fresh cloud consent must name the exact organization run.")
        for scope, _identity in pending:
            request = scope.request
            if (
                request.run_id != consent_run_id
                or request.cloud_consent_run_id != consent_run_id
            ):
                raise ValueError(
                    "Every transmitted scope requires fresh run consent before provider use."
                )

    def _adaptive_timeout(self, requested: float, latencies: list[float]) -> float:
        if latencies:
            ordered = sorted(latencies)
            p90 = ordered[math.ceil(len(ordered) * 0.9) - 1]
            requested = max(requested, p90 * 2.0)
        return min(
            self.config.maximum_timeout_seconds,
            max(self.config.minimum_timeout_seconds, requested),
        )

    def _can_start(self, ledger: _UsageLedger, in_flight: int) -> bool:
        calls, input_tokens, output_tokens = ledger.values()
        budget = self.config.budget
        if budget.hard_calls is not None and calls + in_flight >= budget.hard_calls:
            return False
        return not (
            budget.hard_tokens is not None and input_tokens + output_tokens >= budget.hard_tokens
        )

    def _stop_reason(
        self, elapsed: float, ledger: _UsageLedger, cancelled: Callable[[], bool]
    ) -> str | None:
        if cancelled():
            return "cancelled"
        calls, input_tokens, output_tokens = ledger.values()
        total_tokens = input_tokens + output_tokens
        budget = self.config.budget
        if budget.hard_seconds is not None and elapsed >= budget.hard_seconds:
            return "hard_time_budget"
        if budget.hard_tokens is not None and total_tokens >= budget.hard_tokens:
            return "hard_token_budget"
        if budget.hard_calls is not None and calls >= budget.hard_calls:
            return "hard_call_budget"
        if budget.soft_seconds is not None and elapsed >= budget.soft_seconds:
            return "soft_time_budget"
        if budget.soft_tokens is not None and total_tokens >= budget.soft_tokens:
            return "soft_token_budget"
        return None

    def _hard_budget_reached(self, started: float, ledger: _UsageLedger) -> bool:
        calls, input_tokens, output_tokens = ledger.values()
        budget = self.config.budget
        return any(
            (
                budget.hard_seconds is not None
                and time.monotonic() - started >= budget.hard_seconds,
                budget.hard_tokens is not None
                and input_tokens + output_tokens >= budget.hard_tokens,
                budget.hard_calls is not None and calls >= budget.hard_calls,
            )
        )

    def _commit(self, scope: RouteScope, envelope: ScopeEnvelope) -> None:
        self._sink.event(scope, CheckpointState.VALIDATED, envelope.cache_identity)
        self._sink.publish(envelope)

    def _emit_progress(
        self,
        scopes: tuple[RouteScope, ...],
        completed: Mapping[str, ScopeEnvelope],
        pending: int,
        ledger: _UsageLedger,
        latencies: list[float],
        peak_workers: int,
        progress: ProgressCallback | None,
    ) -> None:
        if progress is not None:
            progress(
                self._snapshot(
                    scopes, tuple(completed.values()), pending, ledger, latencies, peak_workers
                )
            )

    @staticmethod
    def _snapshot(
        scopes: tuple[RouteScope, ...],
        envelopes: Iterable[ScopeEnvelope],
        pending: int,
        ledger: _UsageLedger,
        latencies: list[float],
        peak_workers: int,
    ) -> ProgressSnapshot:
        values = tuple(envelopes)
        counts = {state: 0 for state in CheckpointState}
        for envelope in values:
            counts[envelope.state] += 1
        total = len(scopes)
        validated = counts[CheckpointState.VALIDATED]
        fallback = counts[CheckpointState.FALLBACK]
        remaining = max(0, total - len(values)) if pending else 0
        eta_low: float | None
        eta_high: float | None
        if latencies and remaining:
            average = sum(latencies) / len(latencies)
            eta_low = average * remaining / 12
            eta_high = average * remaining / max(1, min(8, remaining)) * 1.5
        else:
            eta_low = eta_high = None
        calls, input_tokens, output_tokens = ledger.values()
        denominator = max(1, total)
        return ProgressSnapshot(
            total=total,
            validated=validated,
            fallback=fallback,
            failed=counts[CheckpointState.FAILED],
            cancelled=counts[CheckpointState.CANCELLED],
            pending=remaining,
            ai_coverage=validated / denominator,
            technical_coverage=(validated + fallback) / denominator,
            calls=calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            eta_low_seconds=eta_low,
            eta_high_seconds=eta_high,
            partial=validated + fallback < total or fallback > 0,
            peak_workers=peak_workers,
        )


def _sanitized_failure(
    error: BaseException, has_fallback: bool
) -> tuple[CheckpointState, str, str]:
    state = CheckpointState.FALLBACK if has_fallback else CheckpointState.FAILED
    if isinstance(error, OrganizationCancelledError):
        return (
            CheckpointState.CANCELLED,
            "cancelled",
            "Organization was cancelled; validated scopes were preserved.",
        )
    if isinstance(error, ProviderRateLimitError):
        return state, "rate_limited", "The provider rate-limited this scope."
    if isinstance(error, ProviderTimeoutError):
        return state, "timeout", "The provider timed out for this scope."
    if isinstance(error, InvalidProviderOutputError):
        return state, "invalid_output", "The provider output failed validation."
    return state, "provider_error", "The provider could not complete this scope."
