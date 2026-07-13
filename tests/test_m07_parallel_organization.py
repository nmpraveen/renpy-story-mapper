"""Focused mocked-process contracts for resumable M07 orchestration."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest

from renpy_story_mapper.organization.contracts import (
    M05_CLOUD_MODEL,
    CodexMode,
    InterpretationClaim,
    OrganizationChunkResult,
    OrganizationConstraints,
    OrganizationGroup,
    OrganizationRequest,
    OrganizationStage,
    ProviderAttemptUsage,
    ProviderExecutionMetadata,
    ProviderState,
    ProviderStatus,
)
from renpy_story_mapper.organization.errors import (
    OrganizationCancelledError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from renpy_story_mapper.organization.parallel import (
    BudgetPolicy,
    CheckpointState,
    InMemoryCheckpointSink,
    ParallelOrganizationScheduler,
    RouteScope,
    SchedulerConfig,
    normalized_cache_identity,
)
from renpy_story_mapper.organization.provider import CodexCliProvider


def _request(
    index: int, *, run_id: str = "run-1", scope_id: str | None = None
) -> OrganizationRequest:
    member = f"beat-{index}"
    return OrganizationRequest(
        run_id=run_id,
        chunk_id=f"chunk-{index}",
        scope_id=scope_id or f"scope-{index:02d}",
        stage=OrganizationStage.EVENTS,
        payload={"beats": [{"id": member, "text": f"Story {index}"}]},
        constraints=OrganizationConstraints(
            ordered_member_ids=(member,),
            required_member_ids=frozenset({member}),
            evidence_ids=frozenset({f"evidence-{index}"}),
            member_evidence_ids=((member, (f"evidence-{index}",)),),
        ),
        cloud_consent_run_id=run_id,
        model=M05_CLOUD_MODEL,
    )


def _result(index: int, *, tokens: int = 10) -> OrganizationChunkResult:
    group = OrganizationGroup(
        id=f"group-{index}",
        title=f"Title {index}",
        summary=f"Summary {index}",
        member_ids=(f"beat-{index}",),
        characters=(),
        importance="supporting",
        outcomes=(),
        promoted_fact_ids=(),
        claims=(
            InterpretationClaim(f"Grounded claim {index}", (f"evidence-{index}",)),
        ),
        warnings=(),
    )
    return OrganizationChunkResult(
        OrganizationStage.EVENTS,
        (group,),
        (),
        {"stage": "events", "groups": [], "ungrouped_ids": []},
        metadata=ProviderExecutionMetadata(
            CodexMode.CODEX_CHATGPT,
            M05_CLOUD_MODEL,
            "mock",
            1,
            "in",
            "out",
            tokens,
            tokens,
        ),
    )


class MockProvider:
    def __init__(
        self,
        scope: RouteScope,
        call: Callable[[RouteScope], OrganizationChunkResult],
        tracker: ConcurrencyTracker | None = None,
    ) -> None:
        self.scope = scope
        self.call = call
        self.tracker = tracker
        self.observer: Callable[[ProviderAttemptUsage], None] | None = None
        self.repair_semaphore: threading.Semaphore | None = None

    def status(self) -> ProviderStatus:
        return ProviderStatus(ProviderState.READY, "mock", model_identifier=M05_CLOUD_MODEL)

    def set_attempt_observer(self, observer: Callable[[ProviderAttemptUsage], None] | None) -> None:
        self.observer = observer

    def set_repair_semaphore(self, semaphore: threading.Semaphore | None) -> None:
        self.repair_semaphore = semaphore

    def organize(self, request: Any, progress: Any, cancelled: Any) -> OrganizationChunkResult:
        del request, progress
        if cancelled():
            raise OrganizationCancelledError("secret story text")
        if self.tracker is not None:
            self.tracker.enter()
        try:
            result = self.call(self.scope)
            if self.observer is not None:
                metadata = result.metadata
                assert metadata is not None
                self.observer(
                    ProviderAttemptUsage(
                        1,
                        metadata.elapsed_ms,
                        "validated",
                        metadata.input_tokens,
                        metadata.output_tokens,
                    )
                )
            return result
        finally:
            if self.tracker is not None:
                self.tracker.leave()

    def cancel(self) -> None:
        return


class ConcurrencyTracker:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0
        self.started = 0
        self.first_wave = threading.Event()

    def enter(self) -> None:
        with self.lock:
            self.active += 1
            self.started += 1
            self.peak = max(self.peak, self.active)
            if self.started >= 8:
                self.first_wave.set()

    def leave(self) -> None:
        with self.lock:
            self.active -= 1


def _scopes(count: int, *, fallback: bool = False) -> tuple[RouteScope, ...]:
    return tuple(
        RouteScope(index, _request(index), _result(index) if fallback else None)
        for index in range(count)
    )


def test_starts_eight_workers_and_ramps_to_twelve() -> None:
    tracker = ConcurrencyTracker()
    release = threading.Event()

    def call(scope: RouteScope) -> OrganizationChunkResult:
        if scope.ordinal < 8:
            assert tracker.first_wave.wait(1)
        else:
            release.wait(0.03)
        time.sleep(0.01)
        return _result(scope.ordinal)

    sink = InMemoryCheckpointSink()
    scheduler = ParallelOrganizationScheduler(
        lambda scope: MockProvider(scope, call, tracker),
        sink,
        SchedulerConfig(ramp_after_successes=1),
    )
    result = scheduler.run(_scopes(30), consent_run_id="run-1")
    release.set()
    assert tracker.peak >= 8
    assert result.progress.peak_workers == 12
    assert result.progress.validated == 30


def test_rate_limit_backs_off_without_global_fallback() -> None:
    tracker = ConcurrencyTracker()

    def call(scope: RouteScope) -> OrganizationChunkResult:
        if scope.ordinal == 0:
            raise ProviderRateLimitError("raw provider detail")
        time.sleep(0.003)
        return _result(scope.ordinal)

    sink = InMemoryCheckpointSink()
    result = ParallelOrganizationScheduler(
        lambda scope: MockProvider(scope, call, tracker), sink
    ).run(_scopes(16, fallback=True), consent_run_id="run-1")
    assert result.progress.validated == 15
    assert result.progress.fallback == 1
    assert any(event.error_code == "rate_limited" for event in sink.events)
    assert all("raw provider detail" not in (event.message or "") for event in sink.events)


def test_latency_backoff_prevents_ramp_and_adapts_later_timeouts() -> None:
    tracker = ConcurrencyTracker()
    observed_timeouts: list[float] = []

    def call(scope: RouteScope) -> OrganizationChunkResult:
        observed_timeouts.append(scope.request.timeout_seconds)
        time.sleep(0.01)
        return _result(scope.ordinal)

    requests = tuple(
        RouteScope(index, replace(_request(index), timeout_seconds=0.001))
        for index in range(4)
    )
    result = ParallelOrganizationScheduler(
        lambda scope: MockProvider(scope, call, tracker),
        InMemoryCheckpointSink(),
        SchedulerConfig(
            initial_workers=1,
            ramp_after_successes=1,
            minimum_timeout_seconds=0.001,
            latency_backoff_seconds=0.005,
        ),
    ).run(requests, consent_run_id="run-1")
    assert result.progress.peak_workers <= 2
    assert max(observed_timeouts[1:]) >= 0.015


def test_shared_repair_semaphore_is_bounded_at_two() -> None:
    active = 0
    peak = 0
    lock = threading.Lock()

    def call(scope: RouteScope) -> OrganizationChunkResult:
        nonlocal active, peak
        provider = providers[scope.ordinal]
        assert provider.repair_semaphore is not None
        with provider.repair_semaphore:
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with lock:
                active -= 1
        return _result(scope.ordinal)

    providers: dict[int, MockProvider] = {}

    def factory(scope: RouteScope) -> MockProvider:
        provider = MockProvider(scope, call)
        providers[scope.ordinal] = provider
        return provider

    ParallelOrganizationScheduler(factory, InMemoryCheckpointSink()).run(
        _scopes(12), consent_run_id="run-1"
    )
    assert peak == 2


def test_cancel_and_resume_preserve_validated_scopes() -> None:
    sink = InMemoryCheckpointSink()
    cancel = threading.Event()
    calls: list[int] = []

    def first(scope: RouteScope) -> OrganizationChunkResult:
        calls.append(scope.ordinal)
        if scope.ordinal == 0:
            cancel.set()
        time.sleep(0.005)
        return _result(scope.ordinal)

    first_result = ParallelOrganizationScheduler(
        lambda scope: MockProvider(scope, first), sink, SchedulerConfig(initial_workers=1)
    ).run(_scopes(5), consent_run_id="run-1", cancelled=cancel.is_set)
    assert first_result.progress.validated == 1
    assert first_result.progress.cancelled == 4

    cancel.clear()
    resumed_calls: list[int] = []

    def resumed(scope: RouteScope) -> OrganizationChunkResult:
        resumed_calls.append(scope.ordinal)
        return _result(scope.ordinal)

    resumed_result = ParallelOrganizationScheduler(
        lambda scope: MockProvider(scope, resumed), sink, SchedulerConfig(initial_workers=1)
    ).run(_scopes(5), consent_run_id="run-1")
    assert resumed_result.progress.validated == 5
    assert 0 not in resumed_calls


def test_zero_call_cache_replay_and_normalized_global_scoped_identity() -> None:
    sink = InMemoryCheckpointSink()
    config = SchedulerConfig()
    original = _request(0, scope_id="global")
    scoped = replace(original, chunk_id="other", scope_id="route-day-1")
    assert normalized_cache_identity(original, config) == normalized_cache_identity(scoped, config)
    calls = 0

    def call(scope: RouteScope) -> OrganizationChunkResult:
        nonlocal calls
        calls += 1
        return _result(scope.ordinal)

    scheduler = ParallelOrganizationScheduler(lambda scope: MockProvider(scope, call), sink, config)
    scheduler.run((RouteScope(0, original),), consent_run_id="run-1")
    scoped = replace(scoped, cloud_consent_run_id=None)
    second = scheduler.run((RouteScope(0, scoped),), consent_run_id="")
    assert calls == 1
    assert second.progress.calls == 0
    assert second.progress.validated == 1
    changed = replace(original, payload={"beats": [{"id": "beat-0", "text": "Changed"}]})
    scheduler.run((RouteScope(0, changed),), consent_run_id="run-1")
    assert calls == 2


def test_timeouts_budgets_accounting_and_partial_preservation() -> None:
    sink = InMemoryCheckpointSink()
    seen_timeouts: list[float] = []

    def call(scope: RouteScope) -> OrganizationChunkResult:
        seen_timeouts.append(scope.request.timeout_seconds)
        if scope.ordinal == 1:
            raise ProviderTimeoutError("secret")
        return _result(scope.ordinal, tokens=7)

    config = SchedulerConfig(
        initial_workers=1,
        budget=BudgetPolicy(soft_tokens=20, hard_calls=3),
        minimum_timeout_seconds=17,
    )
    result = ParallelOrganizationScheduler(
        lambda scope: MockProvider(scope, call), sink, config
    ).run(_scopes(6, fallback=True), consent_run_id="run-1")
    assert seen_timeouts[0] >= 17
    assert result.progress.calls == 3
    assert result.progress.input_tokens == 14
    assert result.progress.output_tokens == 14
    assert result.progress.validated == 2
    assert result.progress.fallback == 4
    assert result.progress.partial


def test_attempt_usage_is_persisted_for_failure_and_cancellation() -> None:
    sink = InMemoryCheckpointSink()
    invocations = 0

    def call(_scope: RouteScope) -> OrganizationChunkResult:
        nonlocal invocations
        invocations += 1
        if invocations == 1:
            raise RuntimeError("private story")
        raise OrganizationCancelledError("private story")

    result = ParallelOrganizationScheduler(
        lambda scope: MockProvider(scope, call), sink, SchedulerConfig(initial_workers=1)
    ).run(_scopes(2), consent_run_id="run-1")
    assert len(sink.attempts) == 2
    assert result.progress.calls == 2
    assert {envelope.state for envelope in result.envelopes} == {
        CheckpointState.FAILED,
        CheckpointState.CANCELLED,
    }
    assert all("private story" not in (event.message or "") for event in sink.events)


def test_hard_time_budget_cancels_in_flight_scope_as_fallback() -> None:
    class PollingProvider(MockProvider):
        def organize(self, request: Any, progress: Any, cancelled: Any) -> OrganizationChunkResult:
            del request, progress
            while not cancelled():
                time.sleep(0.001)
            raise OrganizationCancelledError("private story")

    sink = InMemoryCheckpointSink()
    result = ParallelOrganizationScheduler(
        lambda scope: PollingProvider(scope, lambda item: _result(item.ordinal)),
        sink,
        SchedulerConfig(
            initial_workers=1,
            budget=BudgetPolicy(hard_seconds=0.01),
        ),
    ).run(_scopes(1, fallback=True), consent_run_id="run-1")
    assert result.envelopes[0].state is CheckpointState.FALLBACK
    assert any(event.error_code == "hard_time_budget" for event in sink.events)


def test_completion_order_does_not_change_envelopes_or_assembly_thread() -> None:
    def execute(seed: int) -> tuple[tuple[int, str, str], ...]:
        randomizer = random.Random(seed)
        delays = [randomizer.random() / 100 for _ in range(15)]
        sink = InMemoryCheckpointSink()

        def call(scope: RouteScope) -> OrganizationChunkResult:
            time.sleep(delays[scope.ordinal])
            return _result(scope.ordinal)

        result = ParallelOrganizationScheduler(lambda scope: MockProvider(scope, call), sink).run(
            _scopes(15), consent_run_id="run-1"
        )
        assert sink.assembly_threads == [threading.get_ident()]
        return tuple((item.ordinal, item.scope_id, item.state.value) for item in result.envelopes)

    assert execute(1) == execute(2)


def test_consent_and_model_are_enforced_before_provider_construction() -> None:
    constructed = False

    def factory(scope: RouteScope) -> MockProvider:
        nonlocal constructed
        constructed = True
        return MockProvider(scope, lambda item: _result(item.ordinal))

    scheduler = ParallelOrganizationScheduler(factory, InMemoryCheckpointSink())
    bad = replace(_request(0), cloud_consent_run_id="old-run")
    with pytest.raises(ValueError, match="fresh run consent"):
        scheduler.run((RouteScope(0, bad),), consent_run_id="run-1")
    assert not constructed
    with pytest.raises(ValueError, match=r"GPT-5\.6 Luna"):
        SchedulerConfig(model="other")
    with pytest.raises(ValueError, match="fast disabled"):
        SchedulerConfig(fast_mode=True)


def test_open_or_empty_replay_never_constructs_provider() -> None:
    scheduler = ParallelOrganizationScheduler(
        lambda _scope: (_ for _ in ()).throw(AssertionError("provider constructed")),
        InMemoryCheckpointSink(),
    )
    result = scheduler.run((), consent_run_id="run-1")
    assert result.progress.total == 0


def test_codex_adapter_locks_luna_high_fast_disabled() -> None:
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT)
    _program, arguments = provider.command(__import__("pathlib").Path("schema.json"))
    assert arguments[arguments.index("--model") + 1] == M05_CLOUD_MODEL
    assert 'model_reasoning_effort="high"' in arguments
    disabled = {
        arguments[index + 1] for index, value in enumerate(arguments[:-1]) if value == "--disable"
    }
    assert "fast_mode" in disabled
