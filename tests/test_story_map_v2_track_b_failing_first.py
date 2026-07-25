from __future__ import annotations

from renpy_story_mapper.story_map_v2.contracts import (
    ChunkStatus,
    DensityMetrics,
    ExecutionMode,
    FailureKind,
    MapperResponse,
    ProviderOrigin,
    StoryChunk,
    canonical_hash,
)
from renpy_story_mapper.story_map_v2.provider_policy import (
    LOCAL_MAPPER_ENDPOINT,
    LOCAL_MAPPER_MODEL,
    ProviderFailure,
    execute_chunks,
    prepare_preview,
)
from story_map_v2_fixtures import scope, span


class FakeMapper:
    def __init__(
        self,
        model: str,
        outcomes: list[MapperResponse | ProviderFailure],
        calls: list[str],
    ) -> None:
        self._model = model
        self.endpoint = LOCAL_MAPPER_ENDPOINT
        self._outcomes = outcomes
        self.calls = calls
        self.cancelled = False

    @property
    def resolved_model(self) -> str:
        return self._model

    def map_chunk(self, chunk):
        self.calls.append(chunk.identity)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, ProviderFailure):
            raise outcome
        return outcome

    def cancel(self) -> None:
        self.cancelled = True


EMPTY_RESPONSE = MapperResponse("Scope", "Overview", (), ())


def fixture_chunks(count: int = 1):
    spans = tuple(
        span(f"s{index}", index * 10 + 1, index * 10 + 9, 100, boundary=True)
        for index in range(count)
    )
    value = scope(spans)
    chunks = tuple(
        StoryChunk(
            index=index,
            span_keys=(item.key,),
            choice_keys=(),
            raw_text=item.raw_text,
            mechanics='{"choices":[]}',
            raw_tokens=item.estimated_tokens,
            density=DensityMetrics(),
            packet_hash=canonical_hash({"span_key": item.key, "raw_text": item.raw_text}),
        )
        for index, item in enumerate(spans, start=1)
    )
    return value, chunks


def never_cancelled() -> bool:
    return False


def test_preview_binds_exact_cloud_identity_limits_and_fields() -> None:
    value, chunks = fixture_chunks()
    preview = prepare_preview(
        value,
        chunks,
        mode=ExecutionMode.CLOUD_PRIMARY,
        allow_local_fallback=True,
        local_model=LOCAL_MAPPER_MODEL,
    )
    assert preview.cloud_settings is not None
    assert preview.cloud_settings.model == "gpt-5.6-luna"
    assert preview.cloud_settings.reasoning == "high"
    assert preview.cloud_settings.fast_mode is False
    assert preview.maximum_hosted_planned == 6
    assert preview.maximum_hosted_absolute == 8
    assert set(preview.transmitted_fields) == {"raw_text", "mechanics"}
    assert preview.local_endpoint == LOCAL_MAPPER_ENDPOINT


def test_all_cloud_success_constructs_cloud_only_after_confirmation() -> None:
    value, chunks = fixture_chunks()
    preview = prepare_preview(
        value, chunks, mode=ExecutionMode.CLOUD_PRIMARY, allow_local_fallback=False
    )
    constructed: list[str] = []
    calls: list[str] = []

    def cloud_factory():
        constructed.append("cloud")
        return FakeMapper("gpt-5.6-luna", [EMPTY_RESPONSE], calls)

    results = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=cloud_factory,
        local_factory=None,
        cancelled=never_cancelled,
    )
    assert constructed == ["cloud"]
    assert results[0].origin is ProviderOrigin.CLOUD
    assert results[0].status is ChunkStatus.COMPLETE


def test_content_refusal_uses_opt_in_same_packet_local_fallback() -> None:
    value, chunks = fixture_chunks()
    preview = prepare_preview(
        value,
        chunks,
        mode=ExecutionMode.CLOUD_PRIMARY,
        allow_local_fallback=True,
        local_model=LOCAL_MAPPER_MODEL,
    )
    cloud_calls: list[str] = []
    local_calls: list[str] = []
    results = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=lambda: FakeMapper(
            "gpt-5.6-luna",
            [ProviderFailure(FailureKind.CONTENT_REFUSAL, "declined")],
            cloud_calls,
        ),
        local_factory=lambda: FakeMapper(LOCAL_MAPPER_MODEL, [EMPTY_RESPONSE], local_calls),
        cancelled=never_cancelled,
    )
    assert cloud_calls == local_calls == [chunks[0].identity]
    assert results[0].origin is ProviderOrigin.LOCAL_FALLBACK


def test_timeout_and_bad_json_never_trigger_local_fallback() -> None:
    value, chunks = fixture_chunks()
    preview = prepare_preview(
        value,
        chunks,
        mode=ExecutionMode.CLOUD_PRIMARY,
        allow_local_fallback=True,
        local_model=LOCAL_MAPPER_MODEL,
    )
    local_constructed: list[str] = []
    for kind in (FailureKind.TIMEOUT, FailureKind.INVALID_RESPONSE):
        results = execute_chunks(
            preview,
            preview.confirmation_hash,
            chunks,
            cloud_factory=lambda kind=kind: FakeMapper(
                "gpt-5.6-luna", [ProviderFailure(kind, "failed")], []
            ),
            local_factory=lambda: (
                local_constructed.append("local")
                or FakeMapper(LOCAL_MAPPER_MODEL, [EMPTY_RESPONSE], [])
            ),
            cancelled=never_cancelled,
        )
        assert results[0].origin is ProviderOrigin.MISSING
        assert results[0].failure_kind is kind
    assert local_constructed == []


def test_local_only_has_zero_cloud_construction_and_visible_origin() -> None:
    value, chunks = fixture_chunks()
    preview = prepare_preview(
        value,
        chunks,
        mode=ExecutionMode.LOCAL_ONLY,
        allow_local_fallback=False,
        local_model=LOCAL_MAPPER_MODEL,
    )
    cloud_constructed: list[str] = []
    results = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=lambda: (
            cloud_constructed.append("cloud") or FakeMapper("gpt-5.6-luna", [EMPTY_RESPONSE], [])
        ),
        local_factory=lambda: FakeMapper(LOCAL_MAPPER_MODEL, [EMPTY_RESPONSE], []),
        cancelled=never_cancelled,
    )
    assert preview.maximum_hosted_planned == preview.maximum_hosted_absolute == 0
    assert preview.cloud_settings is None
    assert cloud_constructed == []
    assert results[0].origin is ProviderOrigin.LOCAL_ONLY


def test_cancellation_prevents_later_submissions() -> None:
    value, chunks = fixture_chunks(2)
    preview = prepare_preview(
        value, chunks, mode=ExecutionMode.CLOUD_PRIMARY, allow_local_fallback=False
    )
    calls: list[str] = []

    def cancelled() -> bool:
        return len(calls) >= 1

    results = execute_chunks(
        preview,
        preview.confirmation_hash,
        chunks,
        cloud_factory=lambda: FakeMapper("gpt-5.6-luna", [EMPTY_RESPONSE, EMPTY_RESPONSE], calls),
        local_factory=None,
        cancelled=cancelled,
    )
    assert calls == [chunks[0].identity]
    assert results[-1].status is ChunkStatus.CANCELLED
