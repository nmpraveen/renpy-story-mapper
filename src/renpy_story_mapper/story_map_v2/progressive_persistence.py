"""Small persistence seam for the Phase 05 progressive story page."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final, Protocol

from renpy_story_mapper.story_map_v2.phase03_contracts import STORY_PAGE_SCHEMA

PROGRESSIVE_STORY_MAP_COLLECTION: Final = "story_map_v2"
PROGRESSIVE_STORY_MAP_KEY: Final = "phase05_progressive"
PROGRESSIVE_STORY_MAP_MARKER: Final = "Phase 05 progressive story walk"


class ProgressiveStoryMapPayloadError(ValueError):
    """The optional progressive story page is present but is not usable."""


class _PayloadProject(Protocol):
    def payload(self, collection: str, key: str) -> object | None: ...


def load_progressive_story_map(project: _PayloadProject) -> dict[str, object] | None:
    """Return the optional progressive page without affecting legacy persistence."""

    raw = project.payload(PROGRESSIVE_STORY_MAP_COLLECTION, PROGRESSIVE_STORY_MAP_KEY)
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ProgressiveStoryMapPayloadError("progressive story map must be an object")
    page = {str(key): value for key, value in raw.items()}
    if page.get("schema") != STORY_PAGE_SCHEMA:
        raise ProgressiveStoryMapPayloadError("progressive story map has the wrong schema")
    if page.get("status") not in {"synthesized", "fallback"}:
        raise ProgressiveStoryMapPayloadError("progressive story map is not readable")
    notes = page.get("analysis_notes")
    if not isinstance(notes, Sequence) or isinstance(notes, str | bytes | bytearray):
        raise ProgressiveStoryMapPayloadError("progressive story map has no analysis notes")
    if not any(
        isinstance(note, str) and note.startswith(PROGRESSIVE_STORY_MAP_MARKER)
        for note in notes
    ):
        raise ProgressiveStoryMapPayloadError("progressive story map marker is missing")
    if not isinstance(page.get("sections"), Sequence) or isinstance(
        page.get("sections"), str | bytes | bytearray
    ):
        raise ProgressiveStoryMapPayloadError("progressive story map sections are invalid")
    return page
