from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import pytest

from renpy_story_mapper.narrative.batching import BatchLimits
from renpy_story_mapper.narrative.contracts import (
    ArtifactPublication,
    AttemptOutcome,
    AuthorityBinding,
    BudgetLimits,
    CacheIdentity,
    ConsentManifest,
    CostConfidence,
    InputRevision,
    LogicalJob,
    LogicalJobKind,
    LogicalJobSpec,
    LogicalJobState,
    PrivacyMode,
    ProviderIdentity,
    ProviderSettings,
    RunEstimate,
    StructuralContext,
)
from renpy_story_mapper.narrative.provider import (
    NarrativeProviderError,
    ProviderAuthenticationError,
    ProviderOutputError,
    ProviderOutputItem,
    ProviderPolicyViolationError,
    ProviderProcessError,
    ProviderRateLimitError,
    ProviderRefusalError,
    ProviderRequest,
    ProviderResponse,
    ProviderRuntimeConfigurationError,
    ProviderSchemaRejectedError,
    ProviderServerTransientError,
    ProviderStatus,
    ProviderTimeoutError,
    ProviderTransportError,
    ProviderUsage,
)
from renpy_story_mapper.narrative.scheduler import (
    CacheReplay,
    NarrativeScheduler,
    ScheduledSceneJob,
    SchedulerAttemptRecord,
    SchedulerBatchRecord,
    SchedulerConfigurationError,
    SchedulerJobRecord,
    SchedulerPolicy,
    SchedulerRunRecord,
    SchedulerRunState,
    SchedulerSink,
    SchedulerUsage,
    ValidatedLogicalOutput,
)

PROMPT_VERSION = "runtime-prompt-version"
SCHEMA_VERSION = "runtime-response-schema"


def _provider_identity(*, resolved_model: str = "resolved-runtime-model") -> ProviderIdentity:
    return ProviderIdentity(
        provider="test-cloud",
        adapter="test-adapter",
        adapter_version="test-adapter-version",
        requested_model="requested-runtime-model",
        resolved_model=resolved_model,
        settings=ProviderSettings(),
    )


def _authority() -> AuthorityBinding:
    return AuthorityBinding(
        source_generation="source-generation",
        source_archive_hash="a" * 64,
        canonical_schema="m10-schema",
        canonical_hash="b" * 64,
        scene_schema="m11-schema",
        scene_hash="c" * 64,
        correction_hash="d" * 64,
        m12_result_identities=("m12-result",),
    )


def _job(
    index: int,
    provider: ProviderIdentity,
    *,
    input_tokens: int = 10,
    output_tokens: int = 5,
    cost_micros: int | None = None,
) -> ScheduledSceneJob:
    normalized_input_hash = f"normalized-input-{index}"
    logical = LogicalJob(
        spec=LogicalJobSpec(
            kind=LogicalJobKind.SCENE,
            owner_id=f"scene-{index}",
            context=StructuralContext(
                chapter_id="chapter-common",
                lane_id="lane-common",
                temporal_anchor=f"scene-{index:04d}",
            ),
        ),
        input_revision=InputRevision(
            authority=_authority(),
            projection_schema="m13-scene-projection",
            normalized_input_hash=normalized_input_hash,
        ),
    )
    cache = CacheIdentity(
        logical_job_id=logical.spec.job_id,
        input_revision_id=logical.input_revision.identity,
        normalized_input_hash=normalized_input_hash,
        prompt_template_version=PROMPT_VERSION,
        response_schema_version=SCHEMA_VERSION,
        provider=provider,
    )
    return ScheduledSceneJob(
        logical_job=logical,
        cache_identity=cache,
        scope_id="selected-scope",
        provider_input={
            "scene_binding": {
                "logical_job_id": logical.spec.job_id,
                "input_revision_id": logical.input_revision.identity,
            },
            "facts": [{"handle": "E1", "value": f"fact-{index}"}],
        },
        ordinal=index,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
        estimated_cost_micros=cost_micros,
    )


def _consent(
    provider: ProviderIdentity,
    *,
    logical_jobs: int,
    estimated_calls: int = 1,
    call_limit: int = 30,
    input_limit: int = 10_000,
    output_limit: int = 10_000,
    total_limit: int = 20_000,
    timeout_seconds: int = 60,
    concurrency: int = 4,
    max_cost_micros: int | None = None,
    estimated_cost_micros: int | None = None,
    cost_confidence: CostConfidence = CostConfidence.UNAVAILABLE,
    granted: bool = True,
) -> ConsentManifest:
    return ConsentManifest(
        run_id="run-exact-consent",
        provider=provider,
        selected_scope_ids=("selected-scope",),
        privacy_mode=PrivacyMode.FACT_ONLY,
        includes_m12_material=True,
        estimate=RunEstimate(
            logical_job_count=logical_jobs,
            provider_call_count=estimated_calls,
            input_tokens=min(input_limit, max(1, logical_jobs * 10)),
            output_tokens=min(output_limit, max(1, logical_jobs * 5)),
            estimated_cost_micros=estimated_cost_micros,
            cost_confidence=cost_confidence,
        ),
        limits=BudgetLimits(
            max_provider_calls=call_limit,
            max_input_tokens=input_limit,
            max_output_tokens=output_limit,
            max_total_tokens=total_limit,
            timeout_seconds=timeout_seconds,
            max_concurrency=concurrency,
            max_cost_micros=max_cost_micros,
        ),
        consent_granted=granted,
    )


def _success_item(job_id: str, index: int, *, value: str = "summary") -> ProviderOutputItem:
    return ProviderOutputItem(
        logical_job_id=job_id,
        transport_index=index,
        payload={"owner": job_id, "summary": value, "claims": []},
    )


def _response(
    request: ProviderRequest,
    provider: ProviderIdentity,
    items: tuple[ProviderOutputItem, ...],
    *,
    input_tokens: int = 20,
    output_tokens: int = 10,
    elapsed_ms: int = 4,
    cost_micros: int | None = None,
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
) -> ProviderResponse:
    return ProviderResponse(
        request_id=request.request_id,
        provider=provider,
        items=items,
        usage=ProviderUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            elapsed_ms=elapsed_ms,
            cost_micros=cost_micros,
        ),
        prompt_template_version=prompt_version,
        response_schema_version=schema_version,
    )


ProviderScript = Callable[[ProviderRequest, int], ProviderResponse]


@dataclass
class ScriptedProvider:
    identity: ProviderIdentity
    script: ProviderScript
    requests: list[ProviderRequest] = field(default_factory=list)
    status_calls: int = 0
    cancel_calls: int = 0
    active_calls: int = 0
    peak_active_calls: int = 0

    def status(self) -> ProviderStatus:
        self.status_calls += 1
        return ProviderStatus(
            available=True,
            provider=self.identity.provider,
            adapter=self.identity.adapter,
            adapter_version=self.identity.adapter_version,
            cli_version="test-cli",
        )

    def submit(
        self,
        request: ProviderRequest,
        cancelled: Callable[[], bool],
    ) -> ProviderResponse:
        if cancelled():
            raise AssertionError("test provider was called after cancellation")
        self.requests.append(request)
        self.active_calls += 1
        self.peak_active_calls = max(self.peak_active_calls, self.active_calls)
        try:
            return self.script(request, len(self.requests))
        finally:
            self.active_calls -= 1

    def cancel(self) -> None:
        self.cancel_calls += 1


@dataclass
class MemorySink:
    caches: dict[str, CacheReplay] = field(default_factory=dict)
    histories: dict[tuple[str, str], list[AttemptOutcome]] = field(default_factory=dict)
    jobs: list[SchedulerJobRecord] = field(default_factory=list)
    attempts: list[SchedulerAttemptRecord] = field(default_factory=list)
    batches: list[SchedulerBatchRecord] = field(default_factory=list)
    published: list[tuple[ScheduledSceneJob, ValidatedLogicalOutput]] = field(
        default_factory=list
    )
    runs: list[SchedulerRunRecord] = field(default_factory=list)
    after_publish: Callable[[ScheduledSceneJob], None] | None = None
    cumulative_usage: SchedulerUsage = field(default_factory=SchedulerUsage)

    def lookup_exact_cache(self, job: ScheduledSceneJob) -> CacheReplay | None:
        return self.caches.get(job.cache_identity.key)

    def attempt_history(
        self,
        run_id: str,
        consent_manifest_id: str,
        job: ScheduledSceneJob,
    ) -> tuple[AttemptOutcome, ...]:
        del consent_manifest_id
        return tuple(self.histories.get((run_id, job.logical_job_id), ()))

    def resume_usage(
        self,
        consent: ConsentManifest,
        jobs: tuple[ScheduledSceneJob, ...],
        compatibility_id: str,
    ) -> SchedulerUsage:
        del consent, jobs, compatibility_id
        return self.cumulative_usage

    def record_job(self, record: SchedulerJobRecord) -> None:
        self.jobs.append(record)

    def record_attempt(self, record: SchedulerAttemptRecord) -> None:
        self.attempts.append(record)
        self.histories.setdefault((record.run_id, record.logical_job_id), []).append(
            record.outcome
        )

    def record_batch(self, record: SchedulerBatchRecord) -> None:
        self.batches.append(record)

    def publish_validated(
        self,
        job: ScheduledSceneJob,
        output: ValidatedLogicalOutput,
        attempt: SchedulerAttemptRecord,
        job_record: SchedulerJobRecord,
    ) -> None:
        assert output.logical_job_id == job.logical_job_id
        assert job_record.artifact_id == output.artifact_id
        self.published.append((job, output))
        self.record_attempt(attempt)
        self.jobs.append(job_record)
        self.caches[job.cache_identity.key] = CacheReplay(
            output.artifact_id,
            output.publication,
        )
        if self.after_publish is not None:
            self.after_publish(job)

    def record_run(self, record: SchedulerRunRecord) -> None:
        self.runs.append(record)


def _validator(
    job: ScheduledSceneJob,
    payload: Mapping[str, object],
) -> ValidatedLogicalOutput:
    if payload.get("owner") != job.logical_job_id or not isinstance(payload.get("summary"), str):
        raise ValueError("provider output changed ownership or shape")
    return ValidatedLogicalOutput(
        logical_job_id=job.logical_job_id,
        artifact_id=f"artifact-{job.logical_job_id}",
        publication=ArtifactPublication.COMPLETE,
        payload={"summary": payload["summary"], "claims": payload.get("claims", [])},
        validated_claim_count=0,
    )


def _scheduler(
    provider: ScriptedProvider,
    sink: MemorySink,
    *,
    maximum_items: int = 8,
    maximum_attempts: int = 8,
    maximum_transient: int = 3,
    maximum_malformed: int = 8,
) -> NarrativeScheduler:
    typed_sink: SchedulerSink = sink
    return NarrativeScheduler(
        provider,
        typed_sink,
        SchedulerPolicy(
            batch_limits=BatchLimits(maximum_items, 500_000, 100_000),
            maximum_attempts_per_job=maximum_attempts,
            maximum_transient_attempts_per_job=maximum_transient,
            maximum_malformed_attempts_per_job=maximum_malformed,
        ),
    )


def test_exact_cache_replay_makes_zero_provider_calls_and_is_byte_stable() -> None:
    identity = _provider_identity()
    jobs = (_job(0, identity), _job(1, identity))
    sink = MemorySink(
        caches={
            job.cache_identity.key: CacheReplay(
                f"cached-{job.logical_job_id}",
                ArtifactPublication.COMPLETE,
            )
            for job in jobs
        }
    )
    provider = ScriptedProvider(
        identity,
        lambda _request, _number: pytest.fail("provider called during exact replay"),
    )
    scheduler = _scheduler(provider, sink)
    consent = _consent(identity, logical_jobs=2)

    first = scheduler.run(jobs, consent, _validator)
    second = scheduler.run(jobs, consent, _validator)

    assert provider.requests == []
    assert provider.status_calls == 0
    assert first.record.usage.provider_calls == 0
    assert first.jobs == second.jobs
    assert [record.cache_replay for record in first.jobs] == [True, True]
    assert first.record.provider == second.record.provider


def test_valid_batch_items_commit_and_missing_or_malformed_items_retry_individually() -> None:
    identity = _provider_identity()
    jobs = tuple(_job(index, identity) for index in range(3))

    def script(request: ProviderRequest, number: int) -> ProviderResponse:
        ids = tuple(item.logical_job_id for item in request.items)
        if number == 1:
            assert ids == tuple(job.logical_job_id for job in jobs)
            return _response(
                request,
                identity,
                (
                    _success_item(ids[0], 0),
                    _success_item(ids[1], 1, value="wrong owner"),
                ),
            )
        assert len(ids) == 1
        return _response(request, identity, (_success_item(ids[0], 0),))

    provider = ScriptedProvider(identity, script)
    sink = MemorySink()

    def validator(
        job: ScheduledSceneJob,
        payload: Mapping[str, object],
    ) -> ValidatedLogicalOutput:
        if job.logical_job_id == jobs[1].logical_job_id and len(provider.requests) == 1:
            raise ValueError("malformed first item")
        return _validator(job, payload)

    result = _scheduler(provider, sink).run(
        jobs,
        _consent(identity, logical_jobs=3),
        validator,
    )

    assert result.record.state is SchedulerRunState.SUCCEEDED
    transported_ids = [
        tuple(item.logical_job_id for item in request.items)
        for request in provider.requests
    ]
    assert transported_ids == [
        tuple(job.logical_job_id for job in jobs),
        (jobs[1].logical_job_id,),
        (jobs[2].logical_job_id,),
    ]
    assert [job.logical_job_id for job, _output in sink.published] == [
        jobs[0].logical_job_id,
        jobs[1].logical_job_id,
        jobs[2].logical_job_id,
    ]
    assert _attempt_counts(sink.attempts) == {
        jobs[0].logical_job_id: 1,
        jobs[1].logical_job_id: 2,
        jobs[2].logical_job_id: 2,
    }


def test_valid_partial_item_commits_once_and_replays_without_another_provider_call() -> None:
    identity = _provider_identity()
    job = _job(0, identity)
    provider = ScriptedProvider(
        identity,
        lambda request, _number: _response(
            request,
            identity,
            (_success_item(request.items[0].logical_job_id, 0),),
        ),
    )
    sink = MemorySink()

    def partial_validator(
        scheduled: ScheduledSceneJob,
        payload: Mapping[str, object],
    ) -> ValidatedLogicalOutput:
        accepted = _validator(scheduled, payload)
        return ValidatedLogicalOutput(
            logical_job_id=accepted.logical_job_id,
            artifact_id=f"partial-{accepted.artifact_id}",
            publication=ArtifactPublication.PARTIAL,
            payload=accepted.payload,
            validated_claim_count=0,
            invalid_claim_count=1,
        )

    scheduler = _scheduler(provider, sink)
    consent = _consent(identity, logical_jobs=1)
    first = scheduler.run((job,), consent, partial_validator)
    replay = scheduler.run((job,), consent, partial_validator)

    assert first.record.state is SchedulerRunState.PARTIAL
    assert first.jobs[0].state is LogicalJobState.PARTIAL
    assert replay.record.state is SchedulerRunState.PARTIAL
    assert replay.jobs[0].cache_replay is True
    assert len(provider.requests) == 1


def test_wholly_unusable_batches_split_recursively_without_discarding_prior_artifacts() -> None:
    identity = _provider_identity()
    jobs = tuple(_job(index, identity) for index in range(4))

    def script(request: ProviderRequest, _number: int) -> ProviderResponse:
        ids = tuple(item.logical_job_id for item in request.items)
        if len(ids) > 1:
            return _response(
                request,
                identity,
                (_success_item("foreign-logical-job", 0),),
            )
        return _response(request, identity, (_success_item(ids[0], 0),))

    provider = ScriptedProvider(identity, script)
    sink = MemorySink()
    result = _scheduler(provider, sink).run(
        jobs,
        _consent(identity, logical_jobs=4, estimated_calls=1),
        _validator,
    )

    assert result.record.state is SchedulerRunState.SUCCEEDED
    assert result.record.usage.provider_calls == 7
    assert [len(request.items) for request in provider.requests] == [4, 2, 1, 1, 2, 1, 1]
    assert len(sink.published) == 4
    assert any(record.state.value == "split" for record in sink.batches)


def test_provider_and_content_refusals_are_localized_by_splitting() -> None:
    identity = _provider_identity()
    jobs = (_job(0, identity), _job(1, identity))

    def script(request: ProviderRequest, _number: int) -> ProviderResponse:
        ids = tuple(item.logical_job_id for item in request.items)
        if len(ids) > 1:
            raise ProviderRefusalForTest()
        if ids[0] == jobs[1].logical_job_id:
            return _response(
                request,
                identity,
                (
                    ProviderOutputItem(
                        logical_job_id=ids[0],
                        transport_index=0,
                        payload=None,
                        error_code="content_refusal",
                    ),
                ),
            )
        return _response(request, identity, (_success_item(ids[0], 0),))

    provider = ScriptedProvider(identity, script)
    sink = MemorySink()
    result = _scheduler(provider, sink).run(
        jobs,
        _consent(identity, logical_jobs=2),
        _validator,
    )

    assert result.record.state is SchedulerRunState.PARTIAL
    assert result.record.succeeded_jobs == 1
    assert result.record.refused_jobs == 1
    assert [job.logical_job_id for job, _output in sink.published] == [jobs[0].logical_job_id]
    assert provider.requests[-1].items[0].logical_job_id == jobs[1].logical_job_id


def test_provider_level_unusable_output_splits_before_individual_retry() -> None:
    identity = _provider_identity()
    jobs = (_job(0, identity), _job(1, identity))

    def script(request: ProviderRequest, number: int) -> ProviderResponse:
        if number == 1:
            raise ProviderOutputError("invalid_output", "sanitized output error")
        assert len(request.items) == 1
        return _response(
            request,
            identity,
            (_success_item(request.items[0].logical_job_id, 0),),
        )

    provider = ScriptedProvider(identity, script)
    sink = MemorySink()
    result = _scheduler(provider, sink).run(
        jobs,
        _consent(identity, logical_jobs=2),
        _validator,
    )

    assert result.record.state is SchedulerRunState.SUCCEEDED
    assert [len(request.items) for request in provider.requests] == [2, 1, 1]
    assert _attempt_counts(sink.attempts) == {
        jobs[0].logical_job_id: 2,
        jobs[1].logical_job_id: 2,
    }


def test_provider_policy_violation_fails_closed_without_retry_or_fallback() -> None:
    identity = _provider_identity()
    jobs = (_job(0, identity), _job(1, identity))

    def script(_request: ProviderRequest, _number: int) -> ProviderResponse:
        raise ProviderPolicyViolationError(
            "forbidden_policy_event",
            "sanitized policy failure",
        )

    provider = ScriptedProvider(identity, script)
    sink = MemorySink()
    result = _scheduler(provider, sink).run(
        jobs,
        _consent(identity, logical_jobs=2),
        _validator,
    )

    assert result.record.state is SchedulerRunState.FAILED
    assert result.record.error_code == "internal_error"
    assert len(provider.requests) == 1
    assert sink.published == []


@pytest.mark.parametrize(
    ("error_type", "error_code", "expected_provider_calls"),
    [
        (ProviderSchemaRejectedError, "output_schema_rejected", 0),
        (
            ProviderRuntimeConfigurationError,
            "runtime_configuration_rejected",
            0,
        ),
        (ProviderAuthenticationError, "authentication_failed", 0),
        (ProviderProcessError, "provider_process_failed", 1),
    ],
)
def test_run_global_provider_failure_trips_one_call_circuit_breaker(
    error_type: type[NarrativeProviderError],
    error_code: str,
    expected_provider_calls: int,
) -> None:
    identity = _provider_identity()
    jobs = tuple(_job(index, identity) for index in range(3))

    def script(_request: ProviderRequest, _number: int) -> ProviderResponse:
        raise error_type(error_code, "SECRET-STORY raw provider detail")

    provider = ScriptedProvider(identity, script)
    sink = MemorySink()
    result = _scheduler(provider, sink, maximum_items=1).run(
        jobs,
        _consent(identity, logical_jobs=3, estimated_calls=3),
        _validator,
    )

    assert result.record.state is SchedulerRunState.FAILED
    assert result.record.error_code == error_code
    assert len(provider.requests) == 1
    assert result.record.usage.provider_calls == expected_provider_calls
    assert [job.attempt_count for job in result.jobs] == [1, 0, 0]
    assert [attempt.logical_job_id for attempt in sink.attempts] == [
        jobs[0].logical_job_id
    ]
    assert sink.attempts[0].transmitted is bool(expected_provider_calls)
    assert {job.error_code for job in result.jobs} == {error_code}
    assert sink.batches[-1].error_code == error_code
    assert sink.published == []
    assert "SECRET-STORY" not in repr((sink.jobs, sink.attempts, sink.batches, sink.runs))


def test_generic_transient_flag_does_not_authorize_a_retry() -> None:
    identity = _provider_identity()
    job = _job(0, identity)

    def script(_request: ProviderRequest, _number: int) -> ProviderResponse:
        raise NarrativeProviderError(
            "transient_provider_error",
            "sanitized but unclassified error",
            transient=True,
        )

    provider = ScriptedProvider(identity, script)
    sink = MemorySink()
    result = _scheduler(provider, sink, maximum_transient=3).run(
        (job,),
        _consent(identity, logical_jobs=1),
        _validator,
    )

    assert result.record.state is SchedulerRunState.FAILED
    assert len(provider.requests) == 1
    assert len(sink.attempts) == 1


class ProviderRefusalForTest(ProviderRefusalError):
    def __init__(self) -> None:
        super().__init__("provider_refusal", "sanitized refusal")


def test_transient_failures_retry_only_eligible_jobs_with_a_hard_bound() -> None:
    identity = _provider_identity()
    jobs = (_job(0, identity), _job(1, identity))

    def script(request: ProviderRequest, number: int) -> ProviderResponse:
        if number <= 2:
            raise ProviderRateLimitError(
                "rate_limited",
                "sanitized rate limit",
                transient=True,
            )
        return _response(
            request,
            identity,
            tuple(
                _success_item(item.logical_job_id, index)
                for index, item in enumerate(request.items)
            ),
        )

    provider = ScriptedProvider(identity, script)
    sink = MemorySink()
    result = _scheduler(provider, sink, maximum_transient=3).run(
        jobs,
        _consent(identity, logical_jobs=2),
        _validator,
    )

    assert result.record.state is SchedulerRunState.SUCCEEDED
    assert provider.peak_active_calls == 1
    assert result.record.usage.peak_concurrency == 1
    assert _attempt_counts(sink.attempts) == {
        jobs[0].logical_job_id: 3,
        jobs[1].logical_job_id: 3,
    }


def test_provider_timeout_is_a_bounded_transient_attempt() -> None:
    identity = _provider_identity()
    job = _job(0, identity)

    def script(request: ProviderRequest, number: int) -> ProviderResponse:
        if number == 1:
            raise ProviderTimeoutError(
                "provider_timeout",
                "sanitized provider timeout",
                transient=True,
            )
        return _response(
            request,
            identity,
            (_success_item(request.items[0].logical_job_id, 0),),
        )

    provider = ScriptedProvider(identity, script)
    sink = MemorySink()
    result = _scheduler(provider, sink, maximum_transient=2).run(
        (job,),
        _consent(identity, logical_jobs=1),
        _validator,
    )

    assert result.record.state is SchedulerRunState.SUCCEEDED
    assert [attempt.outcome for attempt in sink.attempts] == [
        AttemptOutcome.TIMEOUT,
        AttemptOutcome.ACCEPTED,
    ]


@pytest.mark.parametrize(
    ("error_type", "error_code"),
    [
        (ProviderTransportError, "transport_failure"),
        (ProviderServerTransientError, "server_transient"),
    ],
)
def test_recognized_transport_and_server_failures_retry_within_bound(
    error_type: type[NarrativeProviderError],
    error_code: str,
) -> None:
    identity = _provider_identity()
    job = _job(0, identity)

    def script(request: ProviderRequest, number: int) -> ProviderResponse:
        if number == 1:
            raise error_type(error_code, "sanitized transient failure", transient=True)
        return _response(
            request,
            identity,
            (_success_item(request.items[0].logical_job_id, 0),),
        )

    provider = ScriptedProvider(identity, script)
    sink = MemorySink()
    result = _scheduler(provider, sink, maximum_transient=2).run(
        (job,),
        _consent(identity, logical_jobs=1),
        _validator,
    )

    assert result.record.state is SchedulerRunState.SUCCEEDED
    assert len(provider.requests) == 2
    assert [attempt.outcome for attempt in sink.attempts] == [
        AttemptOutcome.TRANSIENT_FAILURE,
        AttemptOutcome.ACCEPTED,
    ]


def test_cancellation_preserves_already_validated_item_and_cancels_only_unfinished() -> None:
    identity = _provider_identity()
    jobs = (_job(0, identity), _job(1, identity))
    cancelled_state = {"value": False}

    def script(request: ProviderRequest, _number: int) -> ProviderResponse:
        return _response(
            request,
            identity,
            tuple(
                _success_item(item.logical_job_id, index)
                for index, item in enumerate(request.items)
            ),
        )

    provider = ScriptedProvider(identity, script)
    sink = MemorySink(after_publish=lambda _job: cancelled_state.__setitem__("value", True))
    result = _scheduler(provider, sink).run(
        jobs,
        _consent(identity, logical_jobs=2),
        _validator,
        cancelled=lambda: cancelled_state["value"],
    )

    assert result.record.state is SchedulerRunState.CANCELLED
    assert result.jobs[0].state is LogicalJobState.SUCCEEDED
    assert result.jobs[1].state is LogicalJobState.CANCELLED
    assert result.jobs[1].attempt_count == 1
    assert sink.attempts[-1].outcome is AttemptOutcome.CANCELLED
    assert len(sink.published) == 1
    assert sink.caches[jobs[0].cache_identity.key].artifact_id == (
        f"artifact-{jobs[0].logical_job_id}"
    )


def test_call_limit_after_partial_batch_preserves_valid_work_and_blocks_retry() -> None:
    identity = _provider_identity()
    jobs = (_job(0, identity), _job(1, identity))

    def script(request: ProviderRequest, _number: int) -> ProviderResponse:
        return _response(
            request,
            identity,
            (_success_item(request.items[0].logical_job_id, 0),),
        )

    provider = ScriptedProvider(identity, script)
    sink = MemorySink()
    result = _scheduler(provider, sink).run(
        jobs,
        _consent(identity, logical_jobs=2, estimated_calls=1, call_limit=1),
        _validator,
    )

    assert result.record.state is SchedulerRunState.HARD_LIMIT
    assert result.record.usage.provider_calls == 1
    assert result.jobs[0].state is LogicalJobState.SUCCEEDED
    assert result.jobs[1].state is LogicalJobState.FAILED
    assert result.jobs[1].error_code == "hard_limit"
    assert len(sink.published) == 1


def test_initial_elapsed_usage_enforces_one_cumulative_pipeline_timeout() -> None:
    identity = _provider_identity()
    job = _job(0, identity)
    provider = ScriptedProvider(
        identity,
        lambda request, _number: _response(
            request,
            identity,
            (_success_item(request.items[0].logical_job_id, 0),),
        ),
    )
    sink = MemorySink()

    result = _scheduler(provider, sink).run(
        (job,),
        _consent(identity, logical_jobs=1, timeout_seconds=60),
        _validator,
        initial_usage=SchedulerUsage(
            provider_calls=2,
            input_tokens=20,
            output_tokens=10,
            elapsed_ms=60_000,
            cost_micros=0,
            peak_concurrency=1,
        ),
    )

    assert result.record.state is SchedulerRunState.HARD_LIMIT
    assert result.record.error_code == "hard_limit"
    assert result.record.usage.elapsed_ms >= 60_000
    assert provider.requests == []
    assert result.jobs[0].error_code == "hard_limit"


def test_postflight_token_overrun_publishes_nothing_and_stops_at_hard_limit() -> None:
    identity = _provider_identity()
    jobs = (_job(0, identity, input_tokens=2, output_tokens=2),)

    def script(request: ProviderRequest, _number: int) -> ProviderResponse:
        return _response(
            request,
            identity,
            (_success_item(request.items[0].logical_job_id, 0),),
            input_tokens=12,
            output_tokens=12,
        )

    provider = ScriptedProvider(identity, script)
    sink = MemorySink()
    result = _scheduler(provider, sink).run(
        jobs,
        _consent(
            identity,
            logical_jobs=1,
            input_limit=20,
            output_limit=20,
            total_limit=20,
        ),
        _validator,
    )

    assert result.record.state is SchedulerRunState.HARD_LIMIT
    assert result.jobs[0].state is LogicalJobState.FAILED
    assert sink.published == []


def test_hard_cost_control_requires_reliable_accounting_before_transmission() -> None:
    identity = _provider_identity()
    jobs = (_job(0, identity),)
    provider = ScriptedProvider(
        identity,
        lambda request, _number: _response(
            request,
            identity,
            (_success_item(request.items[0].logical_job_id, 0),),
        ),
    )
    sink = MemorySink()

    with pytest.raises(SchedulerConfigurationError, match="reliable cost accounting"):
        _scheduler(provider, sink).run(
            jobs,
            _consent(
                identity,
                logical_jobs=1,
                max_cost_micros=100,
                cost_confidence=CostConfidence.UNAVAILABLE,
            ),
            _validator,
        )

    assert provider.requests == []


def test_actual_cost_overrun_is_not_published() -> None:
    identity = _provider_identity()
    job = _job(0, identity, cost_micros=40)
    provider = ScriptedProvider(
        identity,
        lambda request, _number: _response(
            request,
            identity,
            (_success_item(request.items[0].logical_job_id, 0),),
            cost_micros=60,
        ),
    )
    sink = MemorySink()
    result = _scheduler(provider, sink).run(
        (job,),
        _consent(
            identity,
            logical_jobs=1,
            max_cost_micros=50,
            estimated_cost_micros=40,
            cost_confidence=CostConfidence.RELIABLE,
        ),
        _validator,
    )

    assert result.record.state is SchedulerRunState.HARD_LIMIT
    assert result.jobs[0].error_code == "hard_limit"
    assert sink.published == []


def test_runtime_provider_identity_mismatch_fails_without_fallback_or_publication() -> None:
    identity = _provider_identity()
    changed = _provider_identity(resolved_model="unexpected-runtime-model")
    jobs = (_job(0, identity),)

    provider = ScriptedProvider(
        identity,
        lambda request, _number: _response(
            request,
            changed,
            (_success_item(request.items[0].logical_job_id, 0),),
        ),
    )
    sink = MemorySink()
    result = _scheduler(provider, sink).run(
        jobs,
        _consent(identity, logical_jobs=1),
        _validator,
    )

    assert result.record.state is SchedulerRunState.FAILED
    assert result.record.error_code == "internal_error"
    assert result.jobs[0].state is LogicalJobState.FAILED
    assert result.record.usage.provider_calls == 1
    assert sink.published == []


def test_prior_attempt_history_continues_attempt_identity_and_cache_hit_is_not_retried() -> None:
    identity = _provider_identity()
    jobs = (_job(0, identity), _job(1, identity))
    sink = MemorySink(
        caches={
            jobs[0].cache_identity.key: CacheReplay(
                "prior-artifact",
                ArtifactPublication.COMPLETE,
            )
        },
        histories={
            ("run-exact-consent", jobs[1].logical_job_id): [
                AttemptOutcome.TRANSIENT_FAILURE
            ]
        },
    )
    provider = ScriptedProvider(
        identity,
        lambda request, _number: _response(
            request,
            identity,
            (_success_item(request.items[0].logical_job_id, 0),),
        ),
    )
    result = _scheduler(provider, sink).run(
        jobs,
        _consent(identity, logical_jobs=2),
        _validator,
    )

    assert tuple(item.logical_job_id for item in provider.requests[0].items) == (
        jobs[1].logical_job_id,
    )
    assert sink.attempts[-1].attempt_number == 2
    assert result.jobs[0].cache_replay is True
    assert result.jobs[0].attempt_count == 0


def test_durable_attempt_limit_is_enforced_before_queue_or_submit() -> None:
    identity = _provider_identity()
    job = _job(0, identity)
    sink = MemorySink(
        histories={
            ("run-exact-consent", job.logical_job_id): [
                AttemptOutcome.TIMEOUT,
                AttemptOutcome.TRANSIENT_FAILURE,
            ]
        }
    )
    provider = ScriptedProvider(
        identity,
        lambda _request, _number: pytest.fail("exhausted job must not be submitted"),
    )

    result = _scheduler(
        provider,
        sink,
        maximum_attempts=2,
        maximum_transient=2,
        maximum_malformed=2,
    ).run(
        (job,),
        _consent(identity, logical_jobs=1),
        _validator,
    )

    assert provider.requests == []
    assert result.record.usage.provider_calls == 0
    assert result.jobs[0].state is LogicalJobState.FAILED
    assert result.jobs[0].attempt_count == 2
    assert result.jobs[0].error_code == "hard_limit"


def test_post_submit_timeout_reserves_nonzero_estimated_usage() -> None:
    identity = _provider_identity()
    job = _job(0, identity, input_tokens=17, output_tokens=9)

    def timeout(_request: ProviderRequest, _number: int) -> ProviderResponse:
        raise ProviderTimeoutError(
            "provider_timeout",
            "SECRET-STORY provider detail",
            transient=True,
        )

    provider = ScriptedProvider(identity, timeout)
    sink = MemorySink()
    result = _scheduler(provider, sink, maximum_transient=1).run(
        (job,),
        _consent(identity, logical_jobs=1),
        _validator,
    )

    assert result.record.usage.provider_calls == 1
    assert result.record.usage.input_tokens == 17
    assert result.record.usage.output_tokens == 9
    assert result.record.usage.usage_estimated is True
    assert sink.attempts[0].metrics.input_tokens == 17
    assert sink.attempts[0].metrics.output_tokens == 9
    assert sink.attempts[0].metrics_estimated is True
    assert sink.attempts[0].transmitted is True
    assert "SECRET-STORY" not in repr((sink.attempts, sink.runs))


def test_post_submit_timeout_retains_exact_sanitized_partial_usage() -> None:
    identity = _provider_identity()
    job = _job(0, identity, input_tokens=17, output_tokens=9)

    def timeout(_request: ProviderRequest, _number: int) -> ProviderResponse:
        error = ProviderTimeoutError(
            "provider_timeout",
            "sanitized timeout",
            transient=True,
        )
        error.partial_usage = ProviderUsage(7, 3, 11, cost_micros=5)
        raise error

    provider = ScriptedProvider(identity, timeout)
    sink = MemorySink()
    result = _scheduler(provider, sink, maximum_transient=1).run(
        (job,),
        _consent(identity, logical_jobs=1),
        _validator,
    )

    assert result.record.usage.input_tokens == 7
    assert result.record.usage.output_tokens == 3
    assert result.record.usage.elapsed_ms >= 11
    assert result.record.usage.cost_micros == 5
    assert result.record.usage.usage_estimated is False
    assert sink.attempts[0].metrics.input_tokens == 7
    assert sink.attempts[0].metrics.output_tokens == 3
    assert sink.attempts[0].metrics_estimated is False


def test_unknown_transmitted_cost_under_hard_cap_stops_without_retry() -> None:
    identity = _provider_identity()
    job = _job(0, identity, cost_micros=10)

    def timeout(_request: ProviderRequest, _number: int) -> ProviderResponse:
        raise ProviderTimeoutError(
            "provider_timeout",
            "sanitized timeout",
            transient=True,
        )

    provider = ScriptedProvider(identity, timeout)
    sink = MemorySink()
    result = _scheduler(provider, sink, maximum_transient=3).run(
        (job,),
        _consent(
            identity,
            logical_jobs=1,
            max_cost_micros=100,
            estimated_cost_micros=10,
            cost_confidence=CostConfidence.RELIABLE,
        ),
        _validator,
    )

    assert len(provider.requests) == 1
    assert result.record.state is SchedulerRunState.HARD_LIMIT
    assert result.record.usage.cost_micros is None
    assert sink.attempts[0].metrics.cost_micros is None


def test_post_submit_malformed_output_with_missing_usage_charges_reservation() -> None:
    identity = _provider_identity()
    job = _job(0, identity, input_tokens=13, output_tokens=7)
    provider = ScriptedProvider(
        identity,
        lambda request, _number: _response(
            request,
            identity,
            (),
            input_tokens=0,
            output_tokens=0,
            elapsed_ms=0,
        ),
    )
    sink = MemorySink()

    result = _scheduler(provider, sink, maximum_malformed=1).run(
        (job,),
        _consent(identity, logical_jobs=1),
        _validator,
    )

    assert len(provider.requests) == 1
    assert result.record.usage.input_tokens == 13
    assert result.record.usage.output_tokens == 7
    assert result.record.usage.usage_estimated is True
    assert sink.attempts[0].outcome is AttemptOutcome.MALFORMED
    assert sink.attempts[0].metrics_estimated is True


def test_failed_usage_prevents_the_next_over_budget_submit() -> None:
    identity = _provider_identity()
    jobs = (
        _job(0, identity, input_tokens=10, output_tokens=2),
        _job(1, identity, input_tokens=10, output_tokens=2),
    )

    def timeout(_request: ProviderRequest, _number: int) -> ProviderResponse:
        raise ProviderTimeoutError(
            "provider_timeout",
            "sanitized timeout",
            transient=True,
        )

    provider = ScriptedProvider(identity, timeout)
    sink = MemorySink()
    result = _scheduler(
        provider,
        sink,
        maximum_items=1,
        maximum_transient=1,
    ).run(
        jobs,
        _consent(
            identity,
            logical_jobs=2,
            estimated_calls=2,
            input_limit=15,
        ),
        _validator,
    )

    assert len(provider.requests) == 1
    assert result.record.state is SchedulerRunState.HARD_LIMIT
    assert result.record.usage.input_tokens == 10
    assert result.jobs[1].attempt_count == 0
    assert result.jobs[1].error_code == "hard_limit"


def test_pre_transmission_runtime_rejection_keeps_zero_usage() -> None:
    identity = _provider_identity()
    job = _job(0, identity)

    def rejected(_request: ProviderRequest, _number: int) -> ProviderResponse:
        raise ProviderRuntimeConfigurationError(
            "runtime_configuration_rejected",
            "sanitized local configuration rejection",
        )

    provider = ScriptedProvider(identity, rejected)
    sink = MemorySink()
    result = _scheduler(provider, sink).run(
        (job,),
        _consent(identity, logical_jobs=1),
        _validator,
    )

    assert result.record.usage.provider_calls == 0
    assert result.record.usage.input_tokens == 0
    assert result.record.usage.output_tokens == 0
    assert sink.attempts[0].transmitted is False
    assert sink.attempts[0].metrics.input_tokens == 0


def test_accepted_attempt_without_exact_cache_fails_closed_instead_of_rerunning() -> None:
    identity = _provider_identity()
    job = _job(0, identity)
    sink = MemorySink(
        histories={
            ("run-exact-consent", job.logical_job_id): [AttemptOutcome.ACCEPTED]
        }
    )
    provider = ScriptedProvider(
        identity,
        lambda _request, _number: pytest.fail("accepted job must not be rerun"),
    )

    with pytest.raises(SchedulerConfigurationError, match="missing its exact accepted cache"):
        _scheduler(provider, sink).run(
            (job,),
            _consent(identity, logical_jobs=1),
            _validator,
        )

    assert provider.requests == []


def test_scheduler_records_contain_no_raw_prompt_source_packet_or_provider_response() -> None:
    identity = _provider_identity()
    jobs = tuple(_job(index, identity) for index in range(2))
    provider = ScriptedProvider(
        identity,
        lambda request, _number: _response(
            request,
            identity,
            tuple(
                _success_item(item.logical_job_id, index)
                for index, item in enumerate(request.items)
            ),
            input_tokens=7,
            output_tokens=5,
            cost_micros=3,
        ),
    )
    sink = MemorySink()
    result = _scheduler(provider, sink).run(
        jobs,
        _consent(identity, logical_jobs=2),
        _validator,
    )

    durable = [
        *(record.to_dict() for record in sink.jobs),
        *(record.to_dict() for record in sink.attempts),
        *(record.to_dict() for record in sink.batches),
        result.record.to_dict(),
    ]
    encoded = repr(durable).casefold()
    for forbidden in (
        "raw_prompt",
        "source_packet",
        "provider_response",
        "prompt_text",
        "response_body",
    ):
        assert forbidden not in encoded
    assert sum(attempt.metrics.input_tokens for attempt in sink.attempts) == 7
    assert sum(attempt.metrics.output_tokens for attempt in sink.attempts) == 5
    assert sum(attempt.metrics.cost_micros or 0 for attempt in sink.attempts) == 3


def test_consent_is_single_manifest_bound_and_not_repeated_per_logical_item() -> None:
    identity = _provider_identity()
    jobs = tuple(_job(index, identity) for index in range(5))
    provider = ScriptedProvider(
        identity,
        lambda request, _number: _response(
            request,
            identity,
            tuple(
                _success_item(item.logical_job_id, index)
                for index, item in enumerate(request.items)
            ),
        ),
    )
    sink = MemorySink()
    consent = _consent(identity, logical_jobs=5, estimated_calls=3)
    result = _scheduler(provider, sink, maximum_items=2).run(jobs, consent, _validator)

    assert result.record.state is SchedulerRunState.SUCCEEDED
    assert len(provider.requests) == 3
    assert {request.consent_manifest_id for request in provider.requests} == {
        consent.manifest_id
    }
    assert all(request.requested_model == identity.requested_model for request in provider.requests)


def test_ungranted_consent_and_out_of_scope_jobs_make_no_provider_call() -> None:
    identity = _provider_identity()
    job = _job(0, identity)
    provider = ScriptedProvider(
        identity,
        lambda _request, _number: pytest.fail("provider should not be called"),
    )
    sink = MemorySink()
    scheduler = _scheduler(provider, sink)

    with pytest.raises(SchedulerConfigurationError, match="consent is disabled"):
        scheduler.run(
            (job,),
            _consent(identity, logical_jobs=1, granted=False),
            _validator,
        )

    outside = ScheduledSceneJob(
        logical_job=job.logical_job,
        cache_identity=job.cache_identity,
        scope_id="outside-scope",
        provider_input=job.provider_input,
        ordinal=job.ordinal,
        estimated_input_tokens=job.estimated_input_tokens,
        estimated_output_tokens=job.estimated_output_tokens,
    )
    with pytest.raises(SchedulerConfigurationError, match="outside the consented scope"):
        scheduler.run(
            (outside,),
            _consent(identity, logical_jobs=1),
            _validator,
        )
    assert provider.requests == []


def _attempt_counts(records: list[SchedulerAttemptRecord]) -> dict[str, int]:
    result: dict[str, int] = {}
    for record in records:
        result[record.logical_job_id] = result.get(record.logical_job_id, 0) + 1
    return result
