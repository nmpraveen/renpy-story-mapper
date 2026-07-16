from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from renpy_story_mapper.project import create_ingested_project
from renpy_story_mapper.web.api import ApiProblem, ProjectApi
from renpy_story_mapper.web.state import UserStateStore

FIXTURE = Path(__file__).parent / "fixtures" / "m12" / "route_targets.rpy"


@dataclass
class _Dialogs:
    def choose_source(self, _kind: str) -> None:
        return None

    def choose_open_project(self) -> None:
        return None

    def choose_save_project(self) -> None:
        return None


def _api(tmp_path: Path) -> ProjectApi:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    project_path = tmp_path / "story.rsmproj"
    create_ingested_project(project_path, source).close()
    api = ProjectApi(_Dialogs(), state_store=UserStateStore(tmp_path / "state.json"))
    api._retain_project_path(project_path, source)
    return api


def test_m13_api_advertises_bounded_provider_free_snapshot(tmp_path: Path) -> None:
    api = _api(tmp_path)
    try:
        bootstrap = api.dispatch("GET", "/api/v1/bootstrap", {})
        assert bootstrap["routes"]["m13"] == {
            "snapshot": "/api/v1/m13/snapshot",
            "artifact": "/api/v1/m13/artifact",
            "citations": "/api/v1/m13/citations",
        }
        snapshot = api.dispatch(
            "POST",
            "/api/v1/m13/snapshot",
            {"offset": 0, "limit": 25},
        )
        assert snapshot["status"] == "available"
        assert snapshot["cloud_enabled"] is False
        assert snapshot["total"] == 0
        assert snapshot["coverage"]["expected_scene_jobs"] > 0

        with pytest.raises(ValueError, match="unsupported fields"):
            api.dispatch(
                "POST",
                "/api/v1/m13/snapshot",
                {"offset": 0, "limit": 25, "raw_prompt": True},
            )
    finally:
        api.close()


def test_m13_api_fails_closed_for_unknown_artifact_and_claim(tmp_path: Path) -> None:
    api = _api(tmp_path)
    try:
        with pytest.raises(ApiProblem) as artifact_error:
            api.dispatch(
                "POST",
                "/api/v1/m13/artifact",
                {"artifact_id": "m13_artifact_unknown"},
            )
        assert artifact_error.value.status == 404
        assert artifact_error.value.code == "m13_artifact_not_found"

        with pytest.raises(ApiProblem) as claim_error:
            api.dispatch(
                "POST",
                "/api/v1/m13/citations",
                {"claim_id": "m13_claim_unknown"},
            )
        assert claim_error.value.status == 404
        assert claim_error.value.code == "m13_claim_not_found"
    finally:
        api.close()
