from __future__ import annotations

import json
import threading
from dataclasses import replace

import pytest

from renpy_story_mapper.story_map_v2.cloud_transport import serialize_chunk_packet
from renpy_story_mapper.story_map_v2.contracts import (
    ChunkStatus,
    DensityMetrics,
    ExecutionMode,
    FailureKind,
    MapperResponse,
    ProviderOrigin,
    StoryChunk,
    StoryScope,
    canonical_hash,
    canonical_json,
)
from renpy_story_mapper.story_map_v2.provider_policy import (
    CLOUD_MAPPER_MODEL,
    LOCAL_MAPPER_ENDPOINT,
    LOCAL_MAPPER_MODEL,
    ProviderFailure,
    execute_chunks,
    prepare_preview,
)
from story_map_v2_fixtures import scope, span

RESPONSE = MapperResponse("Scope", "Overview", (), ())


class RecordingMapper:
    def __init__(
        self,
        model: str,
        outcomes: list[MapperResponse | BaseException],
        endpoint: str = LOCAL_MAPPER_ENDPOINT,
    ) -> None:
        self.model = model
        self.endpoint = endpoint
        self.outcomes = outcomes
        self.chunks: list[StoryChunk] = []
        self.packets: list[bytes] = []
        self.cancelled = False
        self.input_tokens = 12
        self.output_tokens = 3

    @property
    def resolved_model(self) -> str:
        return self.model

    def map_chunk(self, chunk: StoryChunk) -> MapperResponse:
        self.chunks.append(chunk)
        self.packets.append(serialize_chunk_packet(chunk))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def cancel(self) -> None:
        self.cancelled = True


class BlockingMapper(RecordingMapper):
    def __init__(self) -> None:
        super().__init__(CLOUD_MAPPER_MODEL, [])
        self.started = False
        self.release = threading.Event()

    def map_chunk(self, chunk: StoryChunk) -> MapperResponse:
        self.chunks.append(chunk)
        self.started = True
        if not self.release.wait(timeout=1):
            raise AssertionError("Cancellation monitor did not cancel the active mapper.")
        raise ProviderFailure(FailureKind.CANCELLED, "cancelled")

    def cancel(self) -> None:
        super().cancel()
        self.release.set()


class UnresolvedIdentityMapper(RecordingMapper):
    @property
    def observed_model(self) -> None:
        return None


def _fixture(count: int = 1) -> tuple[StoryScope, tuple[StoryChunk, ...]]:
    spans = tuple(
        span(f"span-{index}", 10 * index + 1, 10 * index + 8, 100, boundary=True)
        for index in range(count)
    )
    chunks = tuple(
        StoryChunk(
            index=index,
            span_keys=(item.key,),
            choice_keys=(),
            raw_text=item.raw_text,
            mechanics='{"choices":[]}',
            raw_tokens=item.estimated_tokens,
            density=DensityMetrics(),
            packet_hash=canonical_hash({"span": item.key, "raw_text": item.raw_text}),
        )
        for index, item in enumerate(spans, start=1)
    )
    return scope(spans), chunks


def _preview(
    count: int = 1,
    *,
    fallback: bool = True,
    mode: ExecutionMode = ExecutionMode.CLOUD_PRIMARY,
):
    value, chunks = _fixture(count)
    return (
        prepare_preview(
            value,
            chunks,
            mode=mode,
            allow_local_fallback=fallback if mode is ExecutionMode.CLOUD_PRIMARY else False,
            local_model=(
                LOCAL_MAPPER_MODEL if fallback or mode is ExecutionMode.LOCAL_ONLY else None
            ),
        ),
        chunks,
    )


def test_all_cloud_success_records_exact_requested_and_observed_identity() -> None:
    preview, chunks = _preview(fallback=False)
    cloud = RecordingMapper(CLOUD_MAPPER_MODEL, [RESPONSE])

    result = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=lambda: cloud,
        local_factory=None,
        cancelled=lambda: False,
    )[0]

    assert result.origin is ProviderOrigin.CLOUD
    assert result.requested_model == result.resolved_model == CLOUD_MAPPER_MODEL
    assert result.reasoning == "high" and result.fast_mode is False


def test_cloud_failure_before_construction_keeps_resolved_identity_unknown() -> None:
    preview, chunks = _preview(fallback=False)

    result = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=None,
        local_factory=None,
        cancelled=lambda: False,
    )[0]

    assert result.failure_kind is FailureKind.TRANSPORT
    assert result.requested_model == CLOUD_MAPPER_MODEL
    assert result.resolved_model is None
    assert result.reasoning == "high" and result.fast_mode is False


def test_cloud_success_without_observed_runtime_identity_keeps_resolved_none() -> None:
    preview, chunks = _preview(fallback=False)
    cloud = UnresolvedIdentityMapper(CLOUD_MAPPER_MODEL, [RESPONSE])

    result = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=lambda: cloud,
        local_factory=None,
        cancelled=lambda: False,
    )[0]

    assert result.requested_model == CLOUD_MAPPER_MODEL
    assert result.resolved_model is None


def test_cloud_factory_identity_mismatch_records_observed_substitute() -> None:
    preview, chunks = _preview(fallback=False)

    result = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=lambda: RecordingMapper("substitute", [RESPONSE]),
        local_factory=None,
        cancelled=lambda: False,
    )[0]

    assert result.failure_kind is FailureKind.IDENTITY
    assert result.requested_model == CLOUD_MAPPER_MODEL
    assert result.resolved_model == "substitute"


def test_refusal_fallback_reuses_byte_identical_confirmed_packet() -> None:
    preview, chunks = _preview()
    cloud = RecordingMapper(
        CLOUD_MAPPER_MODEL,
        [ProviderFailure(FailureKind.CONTENT_REFUSAL, "raw cloud detail")],
    )
    local = RecordingMapper(LOCAL_MAPPER_MODEL, [RESPONSE])

    results = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=lambda: cloud,
        local_factory=lambda: local,
        cancelled=lambda: False,
    )
    result = results[0]

    assert cloud.chunks[0] is local.chunks[0] is chunks[0]
    assert cloud.packets == local.packets == [serialize_chunk_packet(chunks[0])]
    packet = json.loads(cloud.packets[0])
    assert canonical_json(packet["mechanics"]) == chunks[0].mechanics.encode()
    assert packet["packet_hash"] == preview.packet_hashes[0] == chunks[0].packet_hash
    assert result.chunk_identity == chunks[0].identity
    assert result.origin is ProviderOrigin.LOCAL_FALLBACK
    assert result.status is ChunkStatus.COMPLETE
    assert result.input_tokens == 12 and result.output_tokens == 3
    assert result.sanitized_reason is None
    assert result.requested_model == result.resolved_model == LOCAL_MAPPER_MODEL
    assert result.reasoning is None and result.fast_mode is None
    assert len(results.attempts) == 2
    cloud_attempt, local_attempt = results.attempts
    assert cloud_attempt.failure_kind is FailureKind.CONTENT_REFUSAL
    assert cloud_attempt.requested_model == cloud_attempt.resolved_model == CLOUD_MAPPER_MODEL
    assert cloud_attempt.input_tokens == 12 and cloud_attempt.output_tokens == 3
    assert local_attempt is result


def test_content_refusal_without_confirmed_fallback_remains_missing() -> None:
    preview, chunks = _preview(fallback=False)
    local_constructed: list[bool] = []
    result = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=lambda: RecordingMapper(
            CLOUD_MAPPER_MODEL,
            [ProviderFailure(FailureKind.CONTENT_REFUSAL, "private refusal text")],
        ),
        local_factory=lambda: local_constructed.append(True),  # type: ignore[arg-type,func-returns-value]
        cancelled=lambda: False,
    )[0]
    assert local_constructed == []
    assert result.origin is ProviderOrigin.MISSING
    assert result.failure_kind is FailureKind.CONTENT_REFUSAL
    assert result.requested_model == result.resolved_model == CLOUD_MAPPER_MODEL
    assert result.reasoning == "high" and result.fast_mode is False
    assert "private refusal text" not in (result.sanitized_reason or "")


def test_cancellation_after_cloud_refusal_prevents_local_fallback_submission() -> None:
    preview, chunks = _preview()
    cloud = RecordingMapper(
        CLOUD_MAPPER_MODEL,
        [ProviderFailure(FailureKind.CONTENT_REFUSAL, "refused")],
    )
    local_constructed: list[bool] = []
    results = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=lambda: cloud,
        local_factory=lambda: local_constructed.append(True),  # type: ignore[arg-type,func-returns-value]
        cancelled=lambda: bool(cloud.chunks),
    )
    assert local_constructed == []
    assert results[0].status is ChunkStatus.CANCELLED
    assert len(results.attempts) == 1
    assert results.attempts[0].failure_kind is FailureKind.CONTENT_REFUSAL


def test_cancellation_at_local_submission_boundary_makes_zero_local_calls() -> None:
    preview, chunks = _preview(2)
    cloud = RecordingMapper(
        CLOUD_MAPPER_MODEL,
        [ProviderFailure(FailureKind.CONTENT_REFUSAL, "refused"), RESPONSE],
    )
    local = RecordingMapper(LOCAL_MAPPER_MODEL, [RESPONSE])
    boundary_cancelled = False

    def local_factory() -> RecordingMapper:
        nonlocal boundary_cancelled
        boundary_cancelled = True
        return local

    results = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=lambda: cloud,
        local_factory=local_factory,
        cancelled=lambda: boundary_cancelled,
    )
    assert local.chunks == []
    assert local.cancelled is True
    assert [result.status for result in results] == [ChunkStatus.CANCELLED] * 2
    assert len(results.attempts) == 1
    assert results.attempts[0].failure_kind is FailureKind.CONTENT_REFUSAL


@pytest.mark.parametrize(
    "kind",
    [
        FailureKind.TIMEOUT,
        FailureKind.RATE_LIMIT,
        FailureKind.AUTHENTICATION,
        FailureKind.TRANSPORT,
        FailureKind.INVALID_RESPONSE,
        FailureKind.IDENTITY,
    ],
)
def test_every_non_refusal_cloud_failure_never_constructs_local(kind: FailureKind) -> None:
    preview, chunks = _preview(2)
    local_constructed: list[bool] = []
    cloud = RecordingMapper(CLOUD_MAPPER_MODEL, [ProviderFailure(kind, "sensitive"), RESPONSE])
    results = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=lambda: cloud,
        local_factory=lambda: local_constructed.append(True),  # type: ignore[arg-type,func-returns-value]
        cancelled=lambda: False,
    )
    assert local_constructed == []
    assert results[0].origin is ProviderOrigin.MISSING
    assert results[0].failure_kind is kind
    assert "sensitive" not in (results[0].sanitized_reason or "")


@pytest.mark.parametrize(
    ("factory", "expected", "expected_resolved"),
    [
        (
            lambda: (_ for _ in ()).throw(OSError("private endpoint")),
            FailureKind.LOCAL_UNAVAILABLE,
            None,
        ),
        (
            lambda: RecordingMapper("wrong-model", [RESPONSE]),
            FailureKind.IDENTITY,
            "wrong-model",
        ),
    ],
)
def test_local_unavailable_or_mismatched_model_is_honestly_missing(
    factory, expected, expected_resolved
) -> None:
    preview, chunks = _preview()
    result = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=lambda: RecordingMapper(
            CLOUD_MAPPER_MODEL,
            [ProviderFailure(FailureKind.CONTENT_REFUSAL, "refused")],
        ),
        local_factory=factory,
        cancelled=lambda: False,
    )[0]
    assert result.status is ChunkStatus.MISSING
    assert result.origin is ProviderOrigin.MISSING
    assert result.failure_kind is expected
    assert result.requested_model == LOCAL_MAPPER_MODEL
    assert result.resolved_model == expected_resolved
    assert result.reasoning is None and result.fast_mode is None


def test_local_endpoint_mismatch_fails_before_submission() -> None:
    preview, chunks = _preview()
    local = RecordingMapper(
        LOCAL_MAPPER_MODEL,
        [RESPONSE],
        endpoint="http://localhost:1234/v1",
    )
    result = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=lambda: RecordingMapper(
            CLOUD_MAPPER_MODEL,
            [ProviderFailure(FailureKind.CONTENT_REFUSAL, "refused")],
        ),
        local_factory=lambda: local,
        cancelled=lambda: False,
    )[0]
    assert local.chunks == []
    assert result.failure_kind is FailureKind.IDENTITY
    assert result.requested_model == result.resolved_model == LOCAL_MAPPER_MODEL


def test_local_only_constructs_zero_cloud_providers_and_submits_each_packet_once() -> None:
    preview, chunks = _preview(2, mode=ExecutionMode.LOCAL_ONLY)
    cloud_constructed: list[bool] = []
    local = RecordingMapper(LOCAL_MAPPER_MODEL, [RESPONSE, RESPONSE])
    results = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=lambda: cloud_constructed.append(True),  # type: ignore[arg-type,func-returns-value]
        local_factory=lambda: local,
        cancelled=lambda: False,
    )
    assert cloud_constructed == []
    assert preview.maximum_hosted_planned == preview.maximum_hosted_absolute == 0
    assert local.packets == [serialize_chunk_packet(chunk) for chunk in chunks]
    assert [result.origin for result in results] == [ProviderOrigin.LOCAL_ONLY] * 2
    assert all(result.requested_model == LOCAL_MAPPER_MODEL for result in results)
    assert all(result.resolved_model == LOCAL_MAPPER_MODEL for result in results)


def test_local_only_cancellation_keeps_local_provenance_for_later_chunks() -> None:
    preview, chunks = _preview(2, mode=ExecutionMode.LOCAL_ONLY)
    local = RecordingMapper(
        LOCAL_MAPPER_MODEL,
        [ProviderFailure(FailureKind.CANCELLED, "cancelled"), RESPONSE],
    )
    results = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=None,
        local_factory=lambda: local,
        cancelled=lambda: False,
    )
    assert [result.status for result in results] == [ChunkStatus.CANCELLED] * 2
    assert all(result.requested_model == LOCAL_MAPPER_MODEL for result in results)
    assert all(result.resolved_model == LOCAL_MAPPER_MODEL for result in results)
    assert all(result.reasoning is None and result.fast_mode is None for result in results)


def test_local_content_refusal_remains_distinct() -> None:
    preview, chunks = _preview(mode=ExecutionMode.LOCAL_ONLY)
    result = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=None,
        local_factory=lambda: RecordingMapper(
            LOCAL_MAPPER_MODEL,
            [ProviderFailure(FailureKind.CONTENT_REFUSAL, "private refusal")],
        ),
        cancelled=lambda: False,
    )[0]
    assert result.failure_kind is FailureKind.CONTENT_REFUSAL
    assert result.sanitized_reason == "The local mapper declined this section."


def test_completed_chunk_is_retained_and_boundary_cancellation_cancels_active_mapper() -> None:
    preview, chunks = _preview(2, fallback=False)
    cloud = RecordingMapper(CLOUD_MAPPER_MODEL, [RESPONSE, RESPONSE])

    results = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=lambda: cloud,
        local_factory=None,
        cancelled=lambda: len(cloud.chunks) == 1,
    )

    assert [result.status for result in results] == [ChunkStatus.COMPLETE, ChunkStatus.CANCELLED]
    assert cloud.chunks == [chunks[0]]
    assert cloud.cancelled is True


def test_provider_cancellation_stops_later_submissions_and_cancels_mapper() -> None:
    preview, chunks = _preview(2, fallback=False)
    cloud = RecordingMapper(
        CLOUD_MAPPER_MODEL,
        [ProviderFailure(FailureKind.CANCELLED, "raw cancellation"), RESPONSE],
    )
    results = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=lambda: cloud,
        local_factory=None,
        cancelled=lambda: False,
    )
    assert cloud.chunks == [chunks[0]]
    assert cloud.cancelled is True
    assert [result.status for result in results] == [ChunkStatus.CANCELLED] * 2


def test_cancellation_callback_cancels_mapper_while_submission_is_active() -> None:
    preview, chunks = _preview(2, fallback=False)
    cloud = BlockingMapper()
    results = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=lambda: cloud,
        local_factory=None,
        cancelled=lambda: cloud.started,
    )
    assert cloud.cancelled is True
    assert cloud.chunks == [chunks[0]]
    assert [result.status for result in results] == [ChunkStatus.CANCELLED] * 2


def test_confirmation_identity_or_packet_change_fails_before_factories() -> None:
    preview, chunks = _preview()
    changed = (replace(chunks[0], raw_text="changed", packet_hash="f" * 64),)
    constructed: list[str] = []
    with pytest.raises(ValueError):
        execute_chunks(
            preview,
            preview.confirmation_hash,
            changed,
            cloud_factory=lambda: constructed.append("cloud"),  # type: ignore[arg-type,func-returns-value]
            local_factory=lambda: constructed.append("local"),  # type: ignore[arg-type,func-returns-value]
            cancelled=lambda: False,
        )
    assert constructed == []
