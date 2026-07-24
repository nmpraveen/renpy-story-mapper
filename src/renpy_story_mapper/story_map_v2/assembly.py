"""Track A seam for chronological partial-capable core assembly."""

from renpy_story_mapper.story_map_v2.contracts import CoreChunk, StoryMapCore, StoryScope


def assemble_core(scope: StoryScope, chunks: tuple[CoreChunk, ...]) -> StoryMapCore:
    """Assemble accepted and missing chunks without discarding mechanics. Track A owns it."""

    raise NotImplementedError
