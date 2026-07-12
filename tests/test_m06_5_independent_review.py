from __future__ import annotations

import http.client
import json
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from renpy_story_mapper.presentation import PresentationService
from renpy_story_mapper.project import Project, create_ingested_project
from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.security import SessionSecurity
from renpy_story_mapper.web.server import LocalWebServer, start_in_thread
from renpy_story_mapper.web.state import UserStateStore

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "renpy_story_mapper" / "web" / "static"


@dataclass
class _Dialogs:
    source: Path | None = None
    project_open: Path | None = None
    project_save: Path | None = None

    def choose_source(self, _kind: str) -> Path | None:
        return self.source

    def choose_open_project(self) -> Path | None:
        return self.project_open

    def choose_save_project(self) -> Path | None:
        return self.project_save


def _text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _request(
    server: LocalWebServer,
    method: str,
    path: str,
    *,
    body: object | None = None,
) -> tuple[int, dict[str, Any]]:
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    payload = None if body is None else json.dumps(body).encode()
    headers = {
        "Host": f"127.0.0.1:{server.port}",
        "Accept": "application/json",
        "X-RSM-Session": "session-secret",
    }
    if method != "GET":
        headers.update(
            {
                "Content-Type": "application/json",
                "Origin": f"http://127.0.0.1:{server.port}",
                "X-RSM-CSRF": "csrf-secret",
            }
        )
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    result = json.loads(response.read())
    connection.close()
    return response.status, result


def _wait_for_task(server: LocalWebServer) -> dict[str, Any]:
    for _ in range(200):
        status, progress = _request(server, "GET", "/api/v1/analysis/progress")
        assert status == 200
        if progress["state"] != "running":
            return progress
        time.sleep(0.01)
    raise AssertionError("project operation did not finish")


def test_production_picker_shapes_create_and_refresh_a_real_project(tmp_path: Path) -> None:
    source = tmp_path / "story.rpy"
    source.write_text('label start:\n    "Hello"\n', encoding="utf-8")
    project_path = tmp_path / "story.rsmproj"
    server = LocalWebServer(
        "127.0.0.1",
        0,
        ProjectApi(
            _Dialogs(source=source, project_save=project_path),
            state_store=UserStateStore(tmp_path / "state.json"),
        ),
        security=SessionSecurity("session-secret", "csrf-secret"),
    )
    thread = start_in_thread(server)
    try:
        status, source_pick = _request(
            server, "POST", "/api/v1/native-picker", body={"kind": "source"}
        )
        assert status == 200
        status, save_pick = _request(
            server, "POST", "/api/v1/native-picker", body={"kind": "project_save"}
        )
        assert status == 200
        assert set(source_pick) == {"selection_id", "display_name", "kind"}
        assert set(save_pick) == {"selection_id", "display_name", "kind"}

        status, started = _request(
            server,
            "POST",
            "/api/v1/projects/create",
            body={
                "source_selection_id": source_pick["selection_id"],
                "project_selection_id": save_pick["selection_id"],
            },
        )
        assert status == 200
        assert started["analysis"]["state"] == "running"
        assert _wait_for_task(server)["state"] == "completed"
        assert project_path.is_file()

        source.write_text(
            'label start:\n    "Hello"\n\nlabel added:\n    return\n', encoding="utf-8"
        )
        status, refreshed = _request(
            server, "POST", "/api/v1/projects/refresh", body={}
        )
        assert status == 200
        assert refreshed["analysis"]["state"] == "running"
        assert _wait_for_task(server)["state"] == "completed"
    finally:
        server.close_service()
        thread.join(timeout=5)

    app = _text("app.js")
    api = _text("api.js")
    create_flow = app[
        app.index("async function createFromSource") : app.index("async function openSelection")
    ]
    assert "target.selection_id" in create_flow
    assert "if (!targetId)" in create_flow
    assert "api.create(sourceId, targetId)" in create_flow
    assert "api.create(sourceId, target.id)" not in create_flow
    assert "ENDPOINTS.projectsRefresh" in api
    assert "api.refresh(" in app
    assert '$("#refreshProject").addEventListener("click", refreshProject)' in app


def test_known_dynamic_jump_is_authoritatively_unresolved(tmp_path: Path) -> None:
    source = ROOT / "tests" / "fixtures" / "m05" / "complex_branching" / "complex_story.rpy"
    project_path = tmp_path / "complex.rsmproj"
    with create_ingested_project(project_path, source) as project:
        connection = project._require_open()
        emergency = connection.execute(
            "SELECT node.node_id,node.parent_id,parent.parent_id AS scene_id "
            "FROM presentation_nodes node "
            "JOIN presentation_nodes parent ON parent.node_id=node.parent_id "
            "WHERE node.level=3 AND node.source_path=? AND node.start_line=?",
            ("game/complex_story.rpy", 298),
        ).fetchone()
        normal = connection.execute(
            "SELECT node_id FROM presentation_nodes WHERE level=3 AND "
            "json_extract(CAST(payload_json AS TEXT),'$.source_text')=?",
            ("jump harbor_arrival",),
        ).fetchone()
        assert emergency is not None and normal is not None

    server = LocalWebServer(
        "127.0.0.1",
        0,
        ProjectApi(
            _Dialogs(project_open=project_path),
            state_store=UserStateStore(tmp_path / "complex-state.json"),
        ),
        security=SessionSecurity("session-secret", "csrf-secret"),
    )
    thread = start_in_thread(server)
    try:
        status, picked = _request(
            server, "POST", "/api/v1/native-picker", body={"kind": "project"}
        )
        assert status == 200
        status, _opened = _request(
            server,
            "POST",
            "/api/v1/projects/open",
            body={"selection_id": picked["selection_id"]},
        )
        assert status == 200
        assert _wait_for_task(server)["state"] == "completed"

        def focused(level: str, node_id: str) -> dict[str, Any]:
            view_status, view = _request(
                server,
                "POST",
                "/api/v1/story/view",
                body={"level": level, "focus_ids": [node_id]},
            )
            assert view_status == 200
            assert len(view["nodes"]) == 1
            return view["nodes"][0]

        emergency_node = focused("evidence", str(emergency["node_id"]))
        assert emergency_node["kind"] == "jump"
        assert emergency_node["unresolved"] is True
        assert focused("evidence", str(normal["node_id"]))["unresolved"] is False
        assert focused("events", str(emergency["parent_id"]))["unresolved"] is True
        assert focused("arcs", str(emergency["scene_id"]))["unresolved"] is True
    finally:
        server.close_service()
        thread.join(timeout=5)


def _pending_draft(project_path: Path) -> tuple[str, dict[str, object]]:
    with PresentationService.open(project_path):
        pass
    with Project.open(project_path) as project:
        service = project.organization_service()
        rows = project._require_open().execute(
            "SELECT node_id,parent_id FROM presentation_nodes WHERE level=3 "
            "ORDER BY sort_key,node_id"
        )
        by_parent: dict[str, list[str]] = {}
        for row in rows:
            by_parent.setdefault(str(row["parent_id"]), []).append(str(row["node_id"]))
        events = [
            {
                "id": f"event-{index}",
                "title": f"Event {index}",
                "summary": "Independent review candidate.",
                "beat_ids": beat_ids,
            }
            for index, beat_ids in enumerate(by_parent.values())
        ]
        candidate: dict[str, object] = {
            "events": events,
            "arcs": [
                {
                    "id": "arc-1",
                    "title": "Independent review arc",
                    "summary": "Independent review candidate.",
                    "event_ids": [str(event["id"]) for event in events],
                }
            ],
            "claims": [],
        }
        run_id = service.create_run(
            provider_mode="local",
            model_profile="independent-test",
            model_fingerprint="independent-test",
            prompt_version="independent-test",
            output_schema_version="independent-test",
            generation="independent-test",
        )
        service.finish_run(run_id, "completed", elapsed_ms=1, usage={})
        return service.create_draft(run_id, "independent-test", candidate), candidate


def test_draft_review_contract_is_exact_and_pagination_is_bounded(tmp_path: Path) -> None:
    project_path = tmp_path / "review.rsmproj"
    with create_ingested_project(
        project_path, ROOT / "tests" / "fixtures" / "m05" / "organization"
    ):
        pass
    draft_id, candidate = _pending_draft(project_path)
    server = LocalWebServer(
        "127.0.0.1",
        0,
        ProjectApi(
            _Dialogs(project_open=project_path),
            state_store=UserStateStore(tmp_path / "review-state.json"),
        ),
        security=SessionSecurity("session-secret", "csrf-secret"),
    )
    thread = start_in_thread(server)
    try:
        status, picked = _request(
            server, "POST", "/api/v1/native-picker", body={"kind": "project"}
        )
        assert status == 200
        status, _opened = _request(
            server,
            "POST",
            "/api/v1/projects/open",
            body={"selection_id": picked["selection_id"]},
        )
        assert status == 200
        assert _wait_for_task(server)["state"] == "completed"

        status, envelope = _request(server, "GET", "/api/v1/organization/draft")
        assert status == 200
        assert [draft["id"] for draft in envelope["drafts"]] == [draft_id]
        assert envelope["reviews"][draft_id] == []
        status, blocked = _request(
            server,
            "POST",
            "/api/v1/organization/apply",
            body={"draft_id": draft_id},
        )
        assert status == 409
        assert blocked["error"]["code"] == "draft_review_incomplete"

        expected_reviews = 0
        for target_kind, key in (("arc", "arcs"), ("event", "events")):
            groups = candidate[key]
            assert isinstance(groups, list)
            for group in groups:
                assert isinstance(group, dict)
                status, reviewed = _request(
                    server,
                    "POST",
                    "/api/v1/organization/review",
                    body={
                        "draft_id": draft_id,
                        "target_kind": target_kind,
                        "target_id": group["id"],
                        "decision": "approved",
                    },
                )
                assert status == 200
                assert reviewed["decision"] == "approved"
                expected_reviews += 1

        status, decided = _request(server, "GET", "/api/v1/organization/draft")
        assert status == 200
        assert len(decided["reviews"][draft_id]) == expected_reviews
        status, applied = _request(
            server,
            "POST",
            "/api/v1/organization/apply",
            body={"draft_id": draft_id},
        )
        assert status == 200
        assert applied == {"draft_id": draft_id, "status": "applied"}
    finally:
        server.close_service()
        thread.join(timeout=5)

    contract = _text("contract.js")
    api = _text("api.js")
    app = _text("app.js")
    html = _text("index.html")

    assert 'organizationReview: "/api/v1/organization/review"' in contract
    assert "ENDPOINTS.organizationReview" in api
    assert "draft_id: draftId" in api
    assert "target_kind: targetKind" in api
    assert "target_id: targetId" in api
    assert "decision" in api
    assert "const REVIEW_PAGE_SIZE = 40" in app
    assert "candidates.slice(start, start + REVIEW_PAGE_SIZE)" in app
    assert "Math.ceil(candidates.length / REVIEW_PAGE_SIZE)" in app
    assert "decided !== candidates.length" in app
    assert "api.reviewDraftGroup" in app
    assert 'id="applyDraft"' in html and "disabled>Apply Draft" in html


def test_connection_close_header_is_enforced_by_the_http_lifecycle(tmp_path: Path) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("ready", encoding="utf-8")
    server = LocalWebServer(
        "127.0.0.1",
        0,
        ProjectApi(_Dialogs(), state_store=UserStateStore(tmp_path / "state.json")),
        static_root=static,
    )
    thread = start_in_thread(server)
    client = socket.create_connection(("127.0.0.1", server.port), timeout=2)
    client.settimeout(1)
    request = (
        f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\nConnection: keep-alive\r\n\r\n"
    ).encode("ascii")
    try:
        client.sendall(request + request)
        response = bytearray()
        while True:
            try:
                chunk = client.recv(65_536)
            except TimeoutError:
                break
            if not chunk:
                break
            response.extend(chunk)
    finally:
        client.close()
        server.close_service()
        thread.join(timeout=5)

    assert bytes(response).count(b"HTTP/1.1 200 OK") == 1
    assert not thread.is_alive()
