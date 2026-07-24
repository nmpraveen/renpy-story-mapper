"""Track A seam for mapper validation and deterministic mechanics overlay."""

from renpy_story_mapper.story_map_v2.contracts import (
    CoreChunk,
    MapperResponse,
    ProviderOrigin,
    StoryChunk,
    StoryScope,
)


class MapperValidationError(ValueError):
    """A mapper response contradicts the small V2 structural contract."""


def validate_and_overlay(
    scope: StoryScope,
    chunk: StoryChunk,
    response: MapperResponse,
    *,
    origin: ProviderOrigin,
) -> CoreChunk:
    """Validate approximate AI text and overlay exact Python mechanics. Track A owns it."""

    raise NotImplementedError
