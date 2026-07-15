from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from renpy_story_mapper.project import Project, create_ingested_project
from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.state import UserStateStore

FIXTURE = Path(__file__).parent / "fixtures" / "m11" / "human_scenes.rpy"


@dataclass
class _Dialogs:
    def choose_source(self, _kind: str) -> None:
        return None

    def choose_open_project(self) -> None:
        return None

    def choose_save_project(self) -> None:
        return None


def _project(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    project_path = tmp_path / "story.rsmproj"
    create_ingested_project(project_path, source).close()
    return source, project_path


def test_project_api_serves_bounded_scene_map_without_canonical_decode_and_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, project_path = _project(tmp_path)
    api = ProjectApi(_Dialogs(), state_store=UserStateStore(tmp_path / "state.json"))
    api._retain_project_path(project_path, source)
    original_payload = Project.payload

    def guarded_payload(self: Project, collection: str, key: str) -> object | None:
        if collection == "m10_canonical_graph":
            raise AssertionError("scene map decoded the canonical graph")
        return original_payload(self, collection, key)

    try:
        with monkeypatch.context() as context:
            context.setattr(Project, "payload", guarded_payload)
            page = api.dispatch(
                "POST",
                "/api/v1/m11/scene-map",
                {
                    "offset": 0,
                    "limit": 30,
                    "relationship_offset": 0,
                    "relationship_limit": 180,
                },
            )
        assert page["status"] == "available"
        assert len(page["nodes"]) <= 30
        assert len(page["relationships"]) <= 180
        occurrence = next(item for item in page["nodes"] if item.get("occurrence_id"))
        detail = api.dispatch(
            "POST",
            "/api/v1/m11/detail",
            {"element_id": occurrence["id"]},
        )
        assert detail["status"] == "available"
        assert detail["selected_occurrence_id"] == occurrence["id"]
        assert detail["canonical_escape_ids"]
        assert len(detail["evidence"]) <= 60
    finally:
        api.close()


def test_unavailable_m11_returns_explicit_m10_fallback(tmp_path: Path) -> None:
    source, project_path = _project(tmp_path)
    with Project.open(project_path) as project:
        project._require_open().execute(
            "DELETE FROM payloads WHERE collection='m11_analysis_state'"
        )

    api = ProjectApi(_Dialogs(), state_store=UserStateStore(tmp_path / "state.json"))
    try:
        api._retain_project_path(project_path, source)
        page = api.dispatch("POST", "/api/v1/m11/scene-map", {})
        assert page["status"] == "unavailable"
        assert page["reason"] == "m11_not_published"
        assert page["fallback"] == {
            "route": "/api/v1/m10/inspection-map",
            "view": "simplified",
        }
    finally:
        api.close()
