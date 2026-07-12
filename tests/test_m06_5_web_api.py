from __future__ import annotations

import http.client
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from renpy_story_mapper.project import create_ingested_project
from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.security import MAX_JSON_BODY, SessionSecurity, redact_message
from renpy_story_mapper.web.server import LocalWebServer, start_in_thread
from renpy_story_mapper.web.state import UserStateStore


@dataclass
class FakeDialogs:
    source: Path | None = None
    project_open: Path | None = None
    project_save: Path | None = None

    def choose_source(self, _kind: str) -> Path | None:
        return self.source

    def choose_open_project(self) -> Path | None:
        return self.project_open

    def choose_save_project(self) -> Path | None:
        return self.project_save


@pytest.fixture
def analyzed_project(tmp_path: Path) -> Path:
    source = tmp_path / "story.rpy"
    source.write_text(
        'label start:\n    "Hello"\n    menu:\n        "Leave":\n            return\n',
        encoding="utf-8",
    )
    destination = tmp_path / "story.rsmproj"
    project = create_ingested_project(destination, source)
    project.close()
    return destination


@pytest.fixture
def running_server(tmp_path: Path, analyzed_project: Path) -> Any:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text(
        '<meta name="rsm-session" content=""><meta name="rsm-csrf" content="">',
        encoding="utf-8",
    )
    dialogs = FakeDialogs(project_open=analyzed_project)
    api = ProjectApi(dialogs, state_store=UserStateStore(tmp_path / "state.json"))
    security = SessionSecurity("session-secret", "csrf-secret")
    server = LocalWebServer("127.0.0.1", 0, api, static_root=static, security=security)
    thread = start_in_thread(server)
    yield server
    server.close_service()
    thread.join(timeout=5)
    assert not thread.is_alive()


def request(
    server: LocalWebServer,
    method: str,
    path: str,
    *,
    body: object | None = None,
    host: str | None = None,
    origin: str | None = None,
    session: str | None = "session-secret",
    csrf: str | None = "csrf-secret",
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any], dict[str, str]]:
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    payload = None if body is None else json.dumps(body).encode()
    headers = {"Host": host or f"127.0.0.1:{server.port}", "Accept": "application/json"}
    if session is not None:
        headers["X-RSM-Session"] = session
    if method != "GET":
        headers["Content-Type"] = "application/json"
        headers["Origin"] = origin or f"http://127.0.0.1:{server.port}"
        if csrf is not None:
            headers["X-RSM-CSRF"] = csrf
    if extra_headers:
        headers.update(extra_headers)
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    result = json.loads(raw) if raw else {}
    response_headers = {key: value for key, value in response.getheaders()}
    connection.close()
    return response.status, result, response_headers


def test_bootstrap_contract_security_headers_and_injected_tokens(
    running_server: LocalWebServer,
) -> None:
    status, body, headers = request(running_server, "GET", "/api/v1/bootstrap")
    assert status == 200
    assert body["api_version"] == "v1"
    assert body["limits"] == {"nodes": 80, "edges": 120, "items": 240, "results": 100}
    assert body["routes"]["search"] == "/api/v1/story/search"
    assert headers["Cache-Control"].startswith("no-store")
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"

    connection = http.client.HTTPConnection("127.0.0.1", running_server.port)
    connection.request("GET", "/", headers={"Host": f"127.0.0.1:{running_server.port}"})
    response = connection.getresponse()
    html = response.read().decode()
    connection.close()
    assert 'content="session-secret"' in html
    assert 'content="csrf-secret"' in html


def test_explicit_shutdown_route_responds_before_requesting_app_exit(
    running_server: LocalWebServer,
) -> None:
    requested = threading.Event()
    running_server.shutdown_callback = requested.set

    status, body, _headers = request(
        running_server, "POST", "/api/v1/shutdown", body={}
    )

    assert status == 200
    assert body == {"state": "shutting_down"}
    assert requested.wait(timeout=1)


@pytest.mark.parametrize(
    ("overrides", "expected_status", "code"),
    [
        ({"host": "evil.example"}, 400, "invalid_host"),
        ({"origin": "http://evil.example"}, 403, "invalid_origin"),
        ({"session": "wrong"}, 401, "invalid_session"),
        ({"csrf": "wrong"}, 403, "invalid_csrf"),
    ],
)
def test_rejects_invalid_request_authentication(
    running_server: LocalWebServer,
    overrides: dict[str, str],
    expected_status: int,
    code: str,
) -> None:
    status, body, _headers = request(
        running_server, "POST", "/api/v1/native-picker", body={"kind": "project"}, **overrides
    )
    assert status == expected_status
    assert body["error"]["code"] == code


def test_rejects_traversal_and_oversized_body(running_server: LocalWebServer) -> None:
    status, body, _headers = request(running_server, "GET", "/%2e%2e/secret")
    assert status == 400
    assert body["error"]["code"] == "invalid_path"

    status, body, _headers = request(
        running_server,
        "POST",
        "/api/v1/native-picker",
        body={},
        extra_headers={"Content-Length": str(MAX_JSON_BODY + 1)},
    )
    assert status == 413
    assert body["error"]["code"] == "body_too_large"


def test_non_loopback_bind_refused() -> None:
    with pytest.raises(ValueError, match=r"127\.0\.0\.1"):
        LocalWebServer("0.0.0.0", 0, ProjectApi(FakeDialogs()))


def test_shutdown_returns_with_persistent_keep_alive_client(tmp_path: Path) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("ready", encoding="utf-8")
    server = LocalWebServer(
        "127.0.0.1",
        0,
        ProjectApi(FakeDialogs(), state_store=UserStateStore(tmp_path / "state.json")),
        static_root=static,
    )
    server_thread = start_in_thread(server)
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    connection.request("GET", "/", headers={"Host": f"127.0.0.1:{server.port}"})
    response = connection.getresponse()
    assert response.read() == b"ready"
    assert response.getheader("Connection") == "close"

    close_thread = threading.Thread(target=server.close_service)
    close_thread.start()
    try:
        close_thread.join(timeout=1)
        assert not close_thread.is_alive(), "shutdown waited for a keep-alive request thread"
    finally:
        connection.close()
        close_thread.join(timeout=5)
        if server_thread.is_alive():
            server_thread.join(timeout=5)


def test_open_view_evidence_and_no_provider_construction(
    running_server: LocalWebServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    import renpy_story_mapper.organization as organization

    monkeypatch.setattr(
        organization,
        "CodexCliProvider",
        lambda _mode: pytest.fail("project open/render constructed an AI provider"),
    )
    status, picked, _headers = request(
        running_server, "POST", "/api/v1/native-picker", body={"kind": "project"}
    )
    assert status == 200
    assert "selection_id" in picked and "\\" not in json.dumps(picked)
    status, opened, _headers = request(
        running_server,
        "POST",
        "/api/v1/projects/open",
        body={"selection_id": picked["selection_id"]},
    )
    assert status == 200
    assert opened["analysis"]["state"] == "running"
    for _ in range(100):
        _status, progress, _headers = request(running_server, "GET", "/api/v1/analysis/progress")
        if progress["state"] != "running":
            break
        time.sleep(0.01)
    assert progress["state"] == "completed"

    status, view, _headers = request(
        running_server,
        "POST",
        "/api/v1/story/view",
        body={"level": "arcs", "node_limit": 80, "edge_limit": 120},
    )
    assert status == 200
    assert 0 < len(view["nodes"]) <= 80
    assert len(view["edges"]) <= 120
    status, evidence, _headers = request(
        running_server,
        "POST",
        "/api/v1/story/evidence",
        body={"node_id": view["nodes"][0]["id"], "limit": 25},
    )
    assert status == 200
    assert evidence["node_id"] == view["nodes"][0]["id"]
    assert evidence["records"]


def test_settings_and_recent_projects_are_durable(tmp_path: Path, analyzed_project: Path) -> None:
    state = UserStateStore(tmp_path / "web-state.json")
    state.record_project(analyzed_project)
    saved = state.save_settings({"theme": "dark", "zoom": 2})
    assert saved["theme"] == "dark"
    reopened = UserStateStore(state.path)
    assert reopened.settings()["zoom"] == 2
    assert reopened.recent_projects() == (analyzed_project.resolve(),)


def test_organization_requires_fresh_explicit_consent_before_provider(
    running_server: LocalWebServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    import renpy_story_mapper.organization as organization

    constructed = False

    def provider(_mode: object) -> object:
        nonlocal constructed
        constructed = True
        return object()

    monkeypatch.setattr(organization, "CodexCliProvider", provider)
    status, body, _headers = request(
        running_server,
        "POST",
        "/api/v1/organization/consent",
        body={"consent": False, "scope_ids": []},
    )
    assert status == 400
    assert body["error"]["code"] == "invalid_request"
    assert not constructed


def test_sanitized_error_redacts_local_paths() -> None:
    assert "prave" not in redact_message(r"failed at C:\\Users\\prave\\secret\\story.rpy")
    assert "[local path]" in redact_message(r"failed at C:\\Users\\prave\\secret\\story.rpy")
