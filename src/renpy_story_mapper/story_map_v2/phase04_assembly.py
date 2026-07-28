"""Assembly over the exact frozen Phase 04 StoryChunkPlan.

There is deliberately no StoryPlan or planner input at this boundary.  Missing or unusable prose
fills the predetermined slot with Python-owned structural fallback; it never causes replanning.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Never

from renpy_story_mapper.story_map_v2.phase04_chunk_plan import (
    StoryChunkDescriptor,
    StoryChunkPlan,
)


class FrozenAssemblyError(ValueError):
    """Chunk prose cannot be bound to the exact frozen plan."""


def _trimmed(value: str, label: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{label} must be a non-empty trimmed string")


@dataclass(frozen=True)
class ChunkProseResult:
    story_chunk_plan_identity: str
    chunk_id: str
    request_hash: str
    title: str
    overview: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.story_chunk_plan_identity, "StoryChunkPlan identity"),
            (self.chunk_id, "chunk ID"),
            (self.request_hash, "request hash"),
            (self.title, "chunk title"),
            (self.overview, "chunk overview"),
        ):
            _trimmed(value, label)


@dataclass(frozen=True)
class StructuralChunkFallback:
    chunk_id: str
    scope_id: str
    placement_ids: tuple[str, ...]
    structural_flags: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class FrozenAssemblySlot:
    descriptor: StoryChunkDescriptor
    prose: ChunkProseResult | None
    fallback: StructuralChunkFallback | None

    def __post_init__(self) -> None:
        if (self.prose is None) == (self.fallback is None):
            raise ValueError("assembly slot requires exactly one prose or structural fallback")


@dataclass(frozen=True)
class FrozenChunkAssembly:
    story_chunk_plan_identity: str
    source_identity: str
    coverage_hash: str
    slots: tuple[FrozenAssemblySlot, ...]


def _fallback(chunk: StoryChunkDescriptor) -> StructuralChunkFallback:
    reason = "provider_result_unavailable"
    if chunk.structural_fallback_only:
        reason = (
            chunk.structural_fallback_reason
            or "atomic_scene_request_exceeds_hard_ceiling"
        )
    return StructuralChunkFallback(
        chunk_id=chunk.chunk_id,
        scope_id=chunk.scope_id,
        placement_ids=chunk.placement_ids,
        structural_flags=chunk.structural_flags,
        reason=reason,
    )


def assemble_frozen_chunk_plan(
    plan: StoryChunkPlan,
    results: tuple[ChunkProseResult, ...],
    *,
    replanning_trap: Callable[[], Never] | None = None,
) -> FrozenChunkAssembly:
    """Fill exact frozen slots and intentionally discard any replanning capability.

    ``replanning_trap`` exists solely as an executable integration trap: callers/tests can supply a
    function that raises or records a call.  Assembly never invokes it and cannot accept material
    from which a new plan could be derived.
    """

    _ = replanning_trap
    chunks_by_id = {chunk.chunk_id: chunk for chunk in plan.chunks}
    supplied: dict[str, ChunkProseResult] = {}
    for result in results:
        if result.chunk_id in supplied:
            raise FrozenAssemblyError(f"duplicate chunk result {result.chunk_id!r}")
        if result.story_chunk_plan_identity != plan.identity:
            raise FrozenAssemblyError("chunk result plan identity does not match")
        chunk = chunks_by_id.get(result.chunk_id)
        if chunk is None:
            raise FrozenAssemblyError(f"foreign chunk result {result.chunk_id!r}")
        if chunk.structural_fallback_only:
            raise FrozenAssemblyError("structural-only chunk cannot accept provider prose")
        if result.request_hash != chunk.request_hash:
            raise FrozenAssemblyError("chunk result request hash does not match the frozen plan")
        supplied[result.chunk_id] = result

    slots = tuple(
        FrozenAssemblySlot(
            descriptor=chunk,
            prose=supplied.get(chunk.chunk_id),
            fallback=None if chunk.chunk_id in supplied else _fallback(chunk),
        )
        for chunk in plan.chunks
    )
    flattened = tuple(
        placement_id for slot in slots for placement_id in slot.descriptor.placement_ids
    )
    if flattened != plan.covered_placement_ids:
        raise FrozenAssemblyError("frozen assembly coverage differs from the exact chunk plan")
    return FrozenChunkAssembly(
        story_chunk_plan_identity=plan.identity,
        source_identity=plan.source_identity,
        coverage_hash=plan.coverage_hash,
        slots=slots,
    )
