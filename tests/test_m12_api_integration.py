from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from renpy_story_mapper.m12_service import M12RouteService
from renpy_story_mapper.project import (
    Project,
    create_ingested_project,
    refresh_ingested_project,
)
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


def _project(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    project_path = tmp_path / "story.rsmproj"
    create_ingested_project(project_path, source).close()
    return source, project_path


def _api(tmp_path: Path, source: Path, project_path: Path) -> ProjectApi:
    api = ProjectApi(_Dialogs(), state_store=UserStateStore(tmp_path / "state.json"))
    api._retain_project_path(project_path, source)
    return api


def _foyer_destination(api: ProjectApi) -> dict[str, object]:
    page = api.dispatch(
        "POST",
        "/api/v1/m12/destinations",
        {"query": "Foyer", "offset": 0, "limit": 30},
    )
    return next(item for item in page["nodes"] if item["kind"] == "generic_scene")


def _wait(api: ProjectApi) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        progress = api.dispatch("GET", "/api/v1/analysis/progress", {})
        if progress["state"] not in {"pending", "running"}:
            return progress
        time.sleep(0.01)
    raise AssertionError("M12 route solve did not finish")


def test_m12_api_lists_solves_returns_and_reuses_exact_route(tmp_path: Path) -> None:
    source, project_path = _project(tmp_path)
    api = _api(tmp_path, source, project_path)
    try:
        bootstrap = api.dispatch("GET", "/api/v1/bootstrap", {})
        assert bootstrap["routes"]["m12"] == {
            "destinations": "/api/v1/m12/destinations",
            "solve": "/api/v1/m12/solve",
            "result": "/api/v1/m12/result",
        }
        destination = _foyer_destination(api)
        started = api.dispatch(
            "POST",
            "/api/v1/m12/solve",
            {
                "destination_kind": destination["kind"],
                "target_id": destination["target_id"],
            },
        )
        assert started["cached"] is False
        assert started["analysis"]["kind"] == "m12_route_solve"
        assert _wait(api)["state"] == "completed"
        result = api.dispatch(
            "POST",
            "/api/v1/m12/result",
            {"request_identity": started["request_identity"]},
        )
        assert result["request_identity"] == started["request_identity"]
        assert result["status"] == "confirmed"
        assert result["badge"] == "Confirmed route"
        assert result["complete"] is True
        assert result["recommended"]["instructions"]
        assert result["recommended"]["provenance"]["node_ids"]

        replay = api.dispatch(
            "POST",
            "/api/v1/m12/solve",
            {
                "destination_kind": destination["kind"],
                "target_id": destination["target_id"],
            },
        )
        assert replay["cached"] is True
        assert replay["request_identity"] == started["request_identity"]
        assert replay["result"] == result
    finally:
        api.close()


def test_m12_api_rejects_unknown_fields_and_stale_results(tmp_path: Path) -> None:
    source, project_path = _project(tmp_path)
    api = _api(tmp_path, source, project_path)
    try:
        destination = _foyer_destination(api)
        with pytest.raises(ValueError, match="unsupported fields"):
            api.dispatch(
                "POST",
                "/api/v1/m12/solve",
                {
                    "destination_kind": destination["kind"],
                    "target_id": destination["target_id"],
                    "extra": True,
                },
            )
        started = api.dispatch(
            "POST",
            "/api/v1/m12/solve",
            {
                "destination_kind": destination["kind"],
                "target_id": destination["target_id"],
            },
        )
        assert _wait(api)["state"] == "completed"

        story = source / "story.rpy"
        story.write_text(story.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        refresh_ingested_project(project_path, source)
        with pytest.raises(ApiProblem) as raised:
            api.dispatch(
                "POST",
                "/api/v1/m12/result",
                {"request_identity": started["request_identity"]},
            )
        assert raised.value.status == 409
        assert raised.value.code == "m12_result_stale"
    finally:
        api.close()


def test_m12_api_reports_emergency_attempt_as_uncached_and_retryable(tmp_path: Path) -> None:
    source, project_path = _project(tmp_path)
    api = _api(tmp_path, source, project_path)
    try:
        destination = _foyer_destination(api)
        with Project.open(project_path) as project:
            prepared = M12RouteService(project).prepare(
                str(destination["kind"]), str(destination["target_id"])
            )
        request_identity = prepared.request.identity
        api._remember_m12_identity(request_identity, prepared.identity)
        api._m12_attempts[request_identity] = {
            "schema": "m12-route-attempt-diagnostic-v1",
            "identity_hash": prepared.identity.identity_hash,
            "status": "emergency_abort",
            "reason": "emergency wall-clock abort",
            "volatile_metrics": {},
            "cached": False,
        }

        with pytest.raises(ApiProblem) as raised:
            api.dispatch(
                "POST",
                "/api/v1/m12/result",
                {"request_identity": request_identity},
            )

        assert raised.value.status == 409
        assert raised.value.code == "m12_attempt_incomplete"
        assert raised.value.message == (
            "The emergency wall-clock guard stopped the route attempt. "
            "No normalized result was published or cached."
        )
    finally:
        api.close()
