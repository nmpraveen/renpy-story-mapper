"""Track A seam for coherent Story Map V2 chunk planning."""

from renpy_story_mapper.story_map_v2.contracts import ChunkProfile, StoryChunk, StoryScope


class ChunkPlanningError(ValueError):
    """The scope cannot be partitioned without violating a coherent boundary."""


DEFAULT_CHUNK_PROFILE = ChunkProfile()


def plan_chunks(
    scope: StoryScope,
    profile: ChunkProfile = DEFAULT_CHUNK_PROFILE,
) -> tuple[StoryChunk, ...]:
    """Plan coherent source-ordered chunks. Implemented by Track A."""

    raise NotImplementedError
