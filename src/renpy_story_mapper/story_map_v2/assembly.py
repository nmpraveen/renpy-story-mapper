"""Chronological, partial-capable Story Map V2 core assembly."""

from __future__ import annotations

from dataclasses import replace

from renpy_story_mapper.story_map_v2.contracts import (
    STORY_MAP_V2_SCHEMA,
    ChoiceMechanic,
    ChunkStatus,
    CoreChunk,
    ProviderOrigin,
    StoryChunk,
    StoryMapCore,
    StoryScope,
)
from renpy_story_mapper.story_map_v2.planner import plan_chunks


class CoreAssemblyError(ValueError):
    """Supplied chunks cannot be matched honestly to the deterministic chunk plan."""


def _exact_choices(
    planned: StoryChunk,
    choices: dict[str, ChoiceMechanic],
) -> tuple[ChoiceMechanic, ...]:
    try:
        return tuple(choices[key] for key in planned.choice_keys if choices[key].story_choice)
    except KeyError as exc:
        raise CoreAssemblyError(
            f"planned chunk references unknown deterministic choice {exc.args[0]!r}"
        ) from exc


def _validate_execution(chunk: CoreChunk) -> None:
    execution = chunk.execution
    if execution is None:
        return
    if execution.chunk_identity != chunk.chunk_identity:
        raise CoreAssemblyError("chunk execution identity does not match its core chunk")
    if execution.origin is not chunk.origin:
        raise CoreAssemblyError("chunk execution origin does not match its core chunk")
    if execution.status is not chunk.status:
        raise CoreAssemblyError("chunk execution status does not match its core chunk")


def _normalize_chunk(
    chunk: CoreChunk,
    planned: StoryChunk,
    choices: dict[str, ChoiceMechanic],
) -> CoreChunk:
    if type(chunk.status) is not ChunkStatus or type(chunk.origin) is not ProviderOrigin:
        raise CoreAssemblyError("core chunk has an invalid status or provider origin")
    if chunk.status is ChunkStatus.COMPLETE and chunk.origin is ProviderOrigin.MISSING:
        raise CoreAssemblyError("a complete core chunk cannot have missing provider origin")
    _validate_execution(chunk)
    exact = _exact_choices(planned, choices)
    if chunk.choices and chunk.choices != exact:
        raise CoreAssemblyError("core chunk deterministic choice mechanics do not match the scope")
    return chunk if chunk.choices == exact else replace(chunk, choices=exact)


def _missing_chunk(
    planned: StoryChunk,
    choices: dict[str, ChoiceMechanic],
) -> CoreChunk:
    return CoreChunk(
        chunk_identity=planned.identity,
        status=ChunkStatus.MISSING,
        origin=ProviderOrigin.MISSING,
        events=(),
        choices=_exact_choices(planned, choices),
        warnings=("No mapper result was supplied for this deterministic chunk.",),
    )


def _combined_text(chunks: tuple[CoreChunk, ...], attribute: str) -> str | None:
    values = [getattr(chunk, attribute) for chunk in chunks]
    retained = [value for value in values if isinstance(value, str)]
    return "\n\n".join(retained) if retained else None


def assemble_core(scope: StoryScope, chunks: tuple[CoreChunk, ...]) -> StoryMapCore:
    """Validate supplied chunk order, fill omissions, and retain every valid partial result."""

    planned = plan_chunks(scope)
    expected_positions = {chunk.identity: index for index, chunk in enumerate(planned)}
    supplied_by_identity: dict[str, CoreChunk] = {}
    supplied_positions: list[int] = []
    for chunk in chunks:
        if chunk.chunk_identity in supplied_by_identity:
            raise CoreAssemblyError(
                f"duplicate core chunk identity {chunk.chunk_identity!r} was supplied"
            )
        position = expected_positions.get(chunk.chunk_identity)
        if position is None:
            raise CoreAssemblyError(f"unknown core chunk identity {chunk.chunk_identity!r}")
        supplied_by_identity[chunk.chunk_identity] = chunk
        supplied_positions.append(position)
    if supplied_positions != sorted(supplied_positions):
        raise CoreAssemblyError("core chunks are out of deterministic chronological order")

    choices = {choice.key: choice for choice in scope.choices}
    assembled: list[CoreChunk] = []
    for expected in planned:
        supplied = supplied_by_identity.get(expected.identity)
        assembled.append(
            _missing_chunk(expected, choices)
            if supplied is None
            else _normalize_chunk(supplied, expected, choices)
        )
    result = tuple(assembled)
    complete = len(result) == len(chunks) and all(
        chunk.status is ChunkStatus.COMPLETE for chunk in result
    )
    return StoryMapCore(
        schema=STORY_MAP_V2_SCHEMA,
        source_identity=scope.source_identity,
        status=ChunkStatus.COMPLETE if complete else ChunkStatus.PARTIAL,
        chunks=result,
        title=_combined_text(result, "scope_title"),
        overview=_combined_text(result, "scope_overview"),
    )
