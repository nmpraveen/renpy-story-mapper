from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from renpy_story_mapper.project import PayloadRecord, Project, create_ingested_project
from renpy_story_mapper.story_map_v2.phase03_contracts import STORY_PAGE_SCHEMA
from renpy_story_mapper.story_map_v2.progressive_persistence import (
    PROGRESSIVE_STORY_MAP_COLLECTION,
    PROGRESSIVE_STORY_MAP_KEY,
    PROGRESSIVE_STORY_MAP_MARKER,
)
from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.contracts import STORY_MAP_V2_API_ROUTES
from renpy_story_mapper.web.state import UserStateStore


@dataclass
class _Dialogs:
    def choose_source(self, _kind: str) -> None:
        return None

    def choose_open_project(self) -> None:
        return None

    def choose_save_project(self) -> None:
        return None


def _progressive_page(marker: str = PROGRESSIVE_STORY_MAP_MARKER) -> dict[str, object]:
    return {
        "schema": STORY_PAGE_SCHEMA,
        "status": "synthesized",
        "reason": None,
        "title": "Terrance story proof",
        "overview": "The progressive route proof.",
        "analysis_notes": [f"{marker}: runtime-backed Terrance section"],
        "sections": [],
    }


def test_map_prefers_valid_progressive_record_and_invalid_marker_falls_back(
    tmp_path: Path,
) -> None:
    source = tmp_path / "story.rpy"
    source.write_text('label start:\n    "Hello"\n    return\n', encoding="utf-8")
    project_path = tmp_path / "story.rsmproj"
    create_ingested_project(project_path, source).close()
    with Project.open(project_path) as project:
        project.write_payloads(
            (
                PayloadRecord(
                    PROGRESSIVE_STORY_MAP_COLLECTION,
                    PROGRESSIVE_STORY_MAP_KEY,
                    _progressive_page(),
                ),
            )
        )

    api = ProjectApi(_Dialogs(), state_store=UserStateStore(tmp_path / "state.json"))
    api._retain_project_path(project_path, source)
    try:
        assert api.dispatch("POST", STORY_MAP_V2_API_ROUTES["map"], {}) == _progressive_page()

        with Project.open(project_path) as project:
            project.write_payloads(
                (
                    PayloadRecord(
                        PROGRESSIVE_STORY_MAP_COLLECTION,
                        PROGRESSIVE_STORY_MAP_KEY,
                        _progressive_page("wrong marker"),
                    ),
                )
            )
        fallback = api.dispatch("POST", STORY_MAP_V2_API_ROUTES["map"], {})
        assert fallback["status"] == "unavailable"
    finally:
        api.close()
