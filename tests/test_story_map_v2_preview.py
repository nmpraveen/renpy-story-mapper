from __future__ import annotations

from dataclasses import replace

import pytest

from renpy_story_mapper.story_map_v2.contracts import (
    MAPPER_SCHEMA_VERSION,
    DensityMetrics,
    ExecutionMode,
    ProviderSettings,
    StoryChunk,
    StoryScope,
    canonical_hash,
)
from renpy_story_mapper.story_map_v2.provider_policy import (
    CLOUD_MAPPER_MODEL,
    LOCAL_MAPPER_ENDPOINT,
    LOCAL_MAPPER_MODEL,
    MAPPER_PROMPT_VERSION,
    PRIVACY_EXCLUSIONS,
    execute_chunks,
    prepare_preview,
)
from story_map_v2_fixtures import scope, span


def _fixture() -> tuple[StoryScope, tuple[StoryChunk, ...]]:
    spans = (
        span("one", 1, 9, 100, boundary=True),
        span("two", 10, 19, 120, boundary=True),
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
            packet_hash=canonical_hash({"span": item.key, "raw_text": item.raw_text}),
        )
        for index, item in enumerate(spans, start=1)
    )
    return value, chunks


def test_preview_is_zero_submit_and_binds_ordered_packets_and_privacy() -> None:
    value, chunks = _fixture()
    factories: list[str] = []

    preview = prepare_preview(
        value,
        chunks,
        mode=ExecutionMode.CLOUD_PRIMARY,
        allow_local_fallback=True,
        local_model=LOCAL_MAPPER_MODEL,
    )

    assert factories == []
    assert preview.source_identity == value.source_identity
    assert preview.chunk_identities == tuple(chunk.identity for chunk in chunks)
    assert preview.packet_hashes == tuple(chunk.packet_hash for chunk in chunks)
    assert preview.payload_hashes == tuple(chunk.payload_hash for chunk in chunks)
    assert preview.transmitted_fields == ("raw_text", "mechanics")
    assert preview.prompt_version == MAPPER_PROMPT_VERSION
    assert preview.mapper_schema == MAPPER_SCHEMA_VERSION == "story-map-v2-mapper-v2"
    assert preview.cloud_settings == ProviderSettings(CLOUD_MAPPER_MODEL, "high", False)
    assert preview.maximum_hosted_planned == 6
    assert preview.maximum_hosted_absolute == 8
    assert preview.maximum_local == len(chunks)
    assert preview.privacy_exclusions == PRIVACY_EXCLUSIONS
    assert preview.mode is ExecutionMode.CLOUD_PRIMARY
    assert preview.allow_local_fallback is True
    assert preview.local_model == LOCAL_MAPPER_MODEL
    assert preview.local_endpoint == LOCAL_MAPPER_ENDPOINT


def test_stale_mapper_schema_confirmation_fails_before_any_factory() -> None:
    value, chunks = _fixture()
    preview = prepare_preview(
        value,
        chunks,
        mode=ExecutionMode.CLOUD_PRIMARY,
        allow_local_fallback=False,
    )
    stale = replace(preview, mapper_schema="story-map-v2-mapper-v1")
    constructed: list[str] = []

    assert stale.confirmation_hash != preview.confirmation_hash
    with pytest.raises(ValueError, match="mapper schema changed"):
        execute_chunks(
            stale,
            stale.confirmation_hash,
            chunks,
            cloud_factory=lambda: constructed.append("cloud"),  # type: ignore[arg-type,return-value]
            local_factory=lambda: constructed.append("local"),  # type: ignore[arg-type,return-value]
            cancelled=lambda: False,
        )
    assert constructed == []


def test_preview_binds_endpoint_in_confirmation_and_rejects_non_loopback() -> None:
    value, chunks = _fixture()
    preview = prepare_preview(
        value,
        chunks,
        mode=ExecutionMode.LOCAL_ONLY,
        allow_local_fallback=False,
        local_endpoint="http://localhost:1234/v1",
    )
    assert preview.local_endpoint == "http://localhost:1234/v1"
    assert replace(preview, local_endpoint=LOCAL_MAPPER_ENDPOINT).confirmation_hash != (
        preview.confirmation_hash
    )

    for endpoint in ("https://127.0.0.1:1234/v1", "http://example.com:1234/v1"):
        with pytest.raises(ValueError, match="loopback"):
            prepare_preview(
                value,
                chunks,
                mode=ExecutionMode.LOCAL_ONLY,
                allow_local_fallback=False,
                local_endpoint=endpoint,
            )


def test_confirmed_endpoint_mutation_fails_before_any_factory() -> None:
    value, chunks = _fixture()
    preview = prepare_preview(
        value,
        chunks,
        mode=ExecutionMode.LOCAL_ONLY,
        allow_local_fallback=False,
    )
    changed = replace(preview, local_endpoint="http://example.com:1234/v1")
    constructed: list[str] = []

    with pytest.raises(ValueError, match="loopback"):
        execute_chunks(
            changed,
            changed.confirmation_hash,
            chunks,
            cloud_factory=lambda: constructed.append("cloud"),  # type: ignore[arg-type,return-value]
            local_factory=lambda: constructed.append("local"),  # type: ignore[arg-type,return-value]
            cancelled=lambda: False,
        )
    assert constructed == []


@pytest.mark.parametrize(
    "changed_chunk",
    [
        lambda chunk: replace(chunk, raw_text="changed provider-facing story"),
        lambda chunk: replace(chunk, mechanics='{"choices":[{"key":"changed"}]}'),
    ],
)
def test_provider_payload_mutation_with_unchanged_packet_hash_fails_before_factories(
    changed_chunk,
) -> None:
    value, chunks = _fixture()
    preview = prepare_preview(
        value,
        chunks,
        mode=ExecutionMode.CLOUD_PRIMARY,
        allow_local_fallback=False,
    )
    current_chunks = (changed_chunk(chunks[0]), chunks[1])
    assert current_chunks[0].packet_hash == chunks[0].packet_hash
    assert current_chunks[0].identity == chunks[0].identity
    assert current_chunks[0].payload_hash != chunks[0].payload_hash
    constructed: list[str] = []

    with pytest.raises(ValueError, match="payload"):
        execute_chunks(
            preview,
            preview.confirmation_hash,
            current_chunks,
            cloud_factory=lambda: constructed.append("cloud"),  # type: ignore[arg-type,return-value]
            local_factory=lambda: constructed.append("local"),  # type: ignore[arg-type,return-value]
            cancelled=lambda: False,
        )
    assert constructed == []


@pytest.mark.parametrize("mutation", ["confirmation", "chunks", "settings"])
def test_confirmation_or_plan_change_fails_before_any_factory(mutation: str) -> None:
    value, chunks = _fixture()
    preview = prepare_preview(
        value,
        chunks,
        mode=ExecutionMode.CLOUD_PRIMARY,
        allow_local_fallback=False,
    )
    confirmed_hash = preview.confirmation_hash
    current_chunks = chunks
    if mutation == "confirmation":
        confirmed_hash = "0" * 64
    elif mutation == "chunks":
        current_chunks = (
            replace(chunks[0], raw_text="changed story", packet_hash="1" * 64),
            chunks[1],
        )
    else:
        preview = replace(preview, cloud_settings=ProviderSettings("substitute", "high", False))
        confirmed_hash = preview.confirmation_hash
    constructed: list[str] = []

    with pytest.raises(ValueError):
        execute_chunks(
            preview,
            confirmed_hash,
            current_chunks,
            cloud_factory=lambda: constructed.append("cloud"),  # type: ignore[arg-type,return-value]
            local_factory=lambda: constructed.append("local"),  # type: ignore[arg-type,return-value]
            cancelled=lambda: False,
        )

    assert constructed == []


def test_preview_rejects_more_than_six_planned_cloud_packets() -> None:
    value, chunks = _fixture()
    expanded = tuple(
        replace(
            chunks[index % len(chunks)],
            index=index + 1,
            packet_hash=canonical_hash({"packet": index}),
        )
        for index in range(7)
    )

    with pytest.raises(ValueError, match="six-call ceiling"):
        prepare_preview(
            value,
            expanded,
            mode=ExecutionMode.CLOUD_PRIMARY,
            allow_local_fallback=False,
        )
