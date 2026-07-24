"""Track B seam for exact preview, cloud mapping, and bounded local execution."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from renpy_story_mapper.story_map_v2.contracts import (
    ChunkExecutionResult,
    ExecutionMode,
    FailureKind,
    MapperResponse,
    RunPreview,
    StoryChunk,
    StoryScope,
)

LOCAL_MAPPER_MODEL = "qwen3.5-35b-a3b-uncensored-hauhaucs-aggressive"


class ProviderFailure(RuntimeError):
    def __init__(self, kind: FailureKind, reason: str) -> None:
        super().__init__(reason)
        self.kind = kind


class ChunkMapper(Protocol):
    @property
    def resolved_model(self) -> str: ...

    def map_chunk(self, chunk: StoryChunk) -> MapperResponse: ...

    def cancel(self) -> None: ...


MapperFactory = Callable[[], ChunkMapper]
Cancelled = Callable[[], bool]


def prepare_preview(
    scope: StoryScope,
    chunks: tuple[StoryChunk, ...],
    *,
    mode: ExecutionMode,
    allow_local_fallback: bool,
    local_model: str | None = None,
) -> RunPreview:
    """Create a zero-submit preview whose hash binds every executable input. Track B owns it."""

    raise NotImplementedError


def execute_chunks(
    preview: RunPreview,
    confirmed_hash: str,
    chunks: tuple[StoryChunk, ...],
    *,
    cloud_factory: MapperFactory | None,
    local_factory: MapperFactory | None,
    cancelled: Cancelled,
) -> tuple[ChunkExecutionResult, ...]:
    """Execute confirmed chunks with refusal-only fallback or deliberate local-only mode."""

    raise NotImplementedError
