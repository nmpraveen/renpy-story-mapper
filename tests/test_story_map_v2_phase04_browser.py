# ruff: noqa: E501
from __future__ import annotations

import copy
import http.server
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "renpy_story_mapper" / "web" / "static"
BASE_FIXTURE = ROOT / "tests" / "fixtures" / "story_map_v2" / "phase04_reader_contract_v1.json"
V2_FIXTURE = ROOT / "tests" / "fixtures" / "story_map_v2" / "phase04_reader_contract_v2.json"
WORKFLOW_FIXTURE = ROOT / "tests" / "fixtures" / "story_map_v2" / "phase04_workflow_http_v2.json"
SCHEMA = "story-map-v2-reader-contract-v2"


def _text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _promote_v2(value: Any) -> Any:
    if isinstance(value, dict):
        promoted = {key: _promote_v2(child) for key, child in value.items()}
        if promoted.get("schema") == "story-map-v2-reader-contract-v1":
            promoted["schema"] = SCHEMA
        return promoted
    if isinstance(value, list):
        return [_promote_v2(child) for child in value]
    return copy.deepcopy(value)


def _fixture() -> dict[str, Any]:
    base = json.loads(BASE_FIXTURE.read_text(encoding="utf-8"))
    extension = json.loads(V2_FIXTURE.read_text(encoding="utf-8"))
    promoted = _promote_v2(base)
    promoted["schema"] = SCHEMA
    promoted["examples"]["locate"] = extension["examples"]["branch_location"]
    promoted["examples"]["manifest"]["sections"].append({"id": "section:epilogue", "order": 2, "title": "Epilogue", "summary": "A final quiet beat.", "route_id": None, "status": "complete", "event_count": 1, "is_new": False, "new_facts": []})
    promoted["examples"]["manifest"]["counts"]["sections"] = 3
    promoted["examples"]["manifest"]["counts"]["events"] = 5
    return promoted


def test_reader_v2_static_contract_and_transport_are_bounded() -> None:
    contract = _text("contract.js")
    api = _text("api.js")
    app = _text("app.js")
    html = _text("index.html")

    assert 'STORY_READER_SCHEMA = "story-map-v2-reader-contract-v2"' in contract
    assert "location.branch_id" in contract
    assert 'this.storyReaderRoutes = null' in api
    assert "storyReaderPathFor" in api
    assert "serialized_bytes_per_page" in api
    assert "live_story_items" in app
    assert "server-authored shell" in app
    assert "decode" not in app[app.index("async function locateStoryReaderSelection"):app.index("async function searchStoryReader")]
    assert "Path to this moment" in html
    assert "Source / Evidence" in html
    assert 'STORY_WORKFLOW_CONTRACT = "story-map-v2-workflow-http-v2"' in contract
    assert "configureStoryWorkflow" in api
    assert 'command === "retry"' not in api
    assert "story-map-v2-workflow-http-v1" not in "\n".join((contract, api, app))
    assert "story_map_v2_workflow" in app
    assert 'id="storyPrepareAction"' in html and "disabled" in html[html.index('id="storyPrepareAction"') : html.index('id="storyPrepareAction"') + 160]
    assert 'id="storyRunDetails"' in html and 'id="storyRunRows"' in html
    assert "renderStoryWorkflowDetails" in app
    assert "/workflow/approve" not in "\n".join((contract, api, app, html))


def test_reader_contract_rejects_v1_locate_and_accepts_v2_branch_identity() -> None:
    fixture = _fixture()
    script = f"""
      import {{ assertStoryReaderLocate }} from {json.dumps((STATIC / 'contract.js').as_uri())};
      const good = {json.dumps(fixture['examples']['locate'])};
      assertStoryReaderLocate(good, 7, 'arm:a');
      const bad = structuredClone(good); delete bad.location.branch_id;
      try {{ assertStoryReaderLocate(bad, 7, 'arm:a'); process.exit(2); }} catch (error) {{
        if (!String(error.message).includes('opaque branch resource')) process.exit(3);
      }}
    """
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_workflow_contract_accepts_loopback_primary_and_rejects_no_provider() -> None:
    fixture = json.loads(WORKFLOW_FIXTURE.read_text(encoding="utf-8"))
    response = fixture["examples"]["successes"]["prepare"]
    preview = response["preview"]
    preview["policy"]["cloud"] = None
    local = preview["policy"]["loopback"]
    for key in ("section_synthesis", "rollup_synthesis"):
        preview["policy"][key].update(
            provider=local["provider"],
            model=local["model"],
            reasoning=None,
            fast_mode=None,
            mode="loopback",
        )
    preview["privacy"].update(
        cloud_story_content=False, loopback_story_content=True
    )
    script = f"""
      import {{ assertStoryWorkflowResponse }} from {json.dumps((STATIC / 'contract.js').as_uri())};
      const good = {json.dumps(response)};
      assertStoryWorkflowResponse(good, 'prepare');
      const bad = structuredClone(good); bad.preview.policy.loopback = null;
      try {{ assertStoryWorkflowResponse(bad, 'prepare'); process.exit(2); }} catch (error) {{
        if (!String(error.message).includes('local primary provider')) process.exit(3);
      }}
    """
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


class _ReaderHandler(http.server.BaseHTTPRequestHandler):
    fixture = _fixture()
    workflow_fixture = json.loads(WORKFLOW_FIXTURE.read_text(encoding="utf-8"))
    revision = 7
    view_state: dict[str, Any] | None = None
    requests: ClassVar[list[tuple[str, dict[str, Any]]]] = []
    delayed_kind: str | None = None
    delayed_resource: str | None = None
    delay_started: threading.Event | None = None
    delay_release: threading.Event | None = None
    delay_finished: threading.Event | None = None
    advertise_workflow = False
    workflow_status_mode = "complete"
    workflow_local_only = False
    reader_available = True

    def log_message(self, _format: str, *args: object) -> None:
        return

    @classmethod
    def reset(cls) -> None:
        cls.revision = 7
        cls.view_state = None
        cls.requests = []
        cls.delayed_kind = None
        cls.delayed_resource = None
        cls.delay_started = None
        cls.delay_release = None
        cls.delay_finished = None
        cls.advertise_workflow = False
        cls.workflow_status_mode = "complete"
        cls.workflow_local_only = False
        cls.reader_available = True

    def _at_revision(self, value: Any) -> Any:
        result = copy.deepcopy(value)

        def visit(item: Any) -> None:
            if isinstance(item, dict):
                if "map_revision" in item:
                    item["map_revision"] = self.revision
                if "generation_id" in item:
                    item["generation_id"] = f"generation:complete:{self.revision}"
                for child in item.values():
                    visit(child)
            elif isinstance(item, list):
                for child in item:
                    visit(child)

        visit(result)
        return result

    def _json(self, value: Any, status: int = 200) -> None:
        encoded = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        try:
            self.wfile.write(encoded)
        finally:
            if getattr(self, "_delayed_request", False) and type(self).delay_finished is not None:
                type(self).delay_finished.set()

    def do_GET(self) -> None:
        if self.path == "/api/v1/bootstrap":
            self._json(
                {
                    "api_version": "v1",
                    "recent_projects": [{"selection_id": "reader-project", "name": "Reader fixture", "source_type": "Project", "organization": "Story Map V2"}],
                    "settings": {"theme": "light", "include_technical": True, "include_unresolved": True},
                    "contracts": {},
                    "routes": {
                        "story_map_v2_reader": {
                            "schema": SCHEMA,
                            "routes": self.fixture["routes"],
                            "limits": self.fixture["limits"],
                        },
                        **(
                            copy.deepcopy(self.workflow_fixture["routes"])
                            if type(self).advertise_workflow
                            else {}
                        ),
                    },
                }
            )
            return
        relative = "index.html" if self.path in {"/", "/index.html"} else self.path.lstrip("/")
        target = (STATIC / relative).resolve()
        if STATIC.resolve() not in target.parents or not target.is_file():
            self.send_error(404)
            return
        content = target.read_bytes()
        media = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".json": "application/json"}.get(target.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        type(self).requests.append((self.path, body))
        workflow_routes = self.workflow_fixture["routes"]["story_map_v2_workflow"]
        workflow_command = next((key for key, route in workflow_routes.items() if key != "contract" and route == self.path), None)
        if workflow_command is not None:
            response = copy.deepcopy(self.workflow_fixture["examples"]["successes"][workflow_command])
            if type(self).workflow_local_only:
                preview = response["preview"]
                local = preview["policy"]["loopback"]
                preview["policy"]["cloud"] = None
                for key in ("section_synthesis", "rollup_synthesis"):
                    preview["policy"][key].update({"provider": local["provider"], "model": local["model"], "reasoning": None, "fast_mode": None, "mode": "loopback"})
                preview["privacy"].update({"cloud_story_content": False, "loopback_story_content": True})
            if workflow_command == "status" and type(self).workflow_status_mode == "complete":
                response["status"].update({"pending_jobs": 0, "active_jobs": 0, "accepted_jobs": 3, "structural_fallback_jobs": 0, "resumable_jobs": 0, "indeterminate_jobs": 0, "can_cancel": False, "can_resume": False, "indeterminate_retries": []})
                type(self).revision = 8
            elif workflow_command == "status" and type(self).workflow_status_mode == "resumable":
                response["status"].update({"pending_jobs": 1, "active_jobs": 0, "accepted_jobs": 1, "structural_fallback_jobs": 0, "resumable_jobs": 1, "indeterminate_jobs": 0, "can_cancel": True, "can_resume": True, "indeterminate_retries": []})
            self._json(response)
            return
        if self.path == "/api/v1/projects/open":
            self._json({"project": {"name": "Reader fixture"}, "analysis": {"state": "complete"}})
            return
        if self.path not in {self.fixture["routes"][key] for key in self.fixture["routes"]}:
            self.send_error(404)
            return
        if self.path not in {self.fixture["routes"]["manifest"], self.fixture["routes"]["status"]} and body.get("map_revision") != self.revision:
            self._json({"error": {"code": "stale_map_revision", "message": "The requested map revision is stale."}, "map_revision": self.revision}, status=409)
            return
        examples = self.fixture["examples"]
        resource = body.get("section_id") or body.get("branch_id") or body.get("selection_id") or body.get("query")
        kind = next((key for key, route in self.fixture["routes"].items() if route == self.path), None)
        self._delayed_request = kind == type(self).delayed_kind and resource == type(self).delayed_resource
        if self._delayed_request and type(self).delay_release is not None:
            if type(self).delay_started is not None:
                type(self).delay_started.set()
            type(self).delay_release.wait(timeout=10)
        if self.path == self.fixture["routes"]["manifest"]:
            if type(self).reader_available:
                self._json(self._at_revision(examples["manifest"]))
            else:
                self._json({"error": {"code": "story_map_unavailable", "message": "No story generation is available."}}, status=404)
        elif self.path == self.fixture["routes"]["status"]:
            self._json(self._at_revision(examples["status"]))
        elif self.path == self.fixture["routes"]["section_page"]:
            if body["section_id"] == "section:prologue" and body.get("cursor") == "cursor:section:page-two":
                page = copy.deepcopy(examples["section_page"])
                page["items"] = [{"id": "event:page-two", "kind": "event", "order": 3, "title": "Later in Prologue", "summary": "This target is on the second section page.", "selection_id": "event:page-two", "is_new": False, "new_facts": []}]
                page["shells"] = [{"id": "shell:prologue:two", "kind": "timeline", "item_ids": ["event:page-two"], "parent_shell_id": None, "route_id": None, "rejoin_selection_id": None}]
                page["rendered_item_count"] = 1
                page["next_cursor"] = None
                self._json(self._at_revision(page))
            elif body["section_id"] in {"section:ending", "section:epilogue"}:
                page = copy.deepcopy(examples["section_page"])
                ending = body["section_id"] == "section:ending"
                resource = "ending" if ending else "epilogue"
                page["resource_id"] = body["section_id"]
                page["items"] = [{"id": f"event:{resource}", "kind": "event", "order": 0, "title": "Shared Ending" if ending else "Afterward", "summary": "Both routes arrive here." if ending else "The story settles.", "selection_id": f"event:{resource}", "is_new": ending, "new_facts": [{"kind": "ending", "fact_id": "ending:shared"}] if ending else []}]
                page["shells"] = [{"id": f"shell:{resource}", "kind": "timeline", "item_ids": [f"event:{resource}"], "parent_shell_id": None, "route_id": None, "rejoin_selection_id": None}]
                page["rendered_item_count"] = 1
                self._json(self._at_revision(page))
            else:
                self._json(self._at_revision(examples["section_page"]))
        elif self.path == self.fixture["routes"]["branch_page"]:
            self._json(self._at_revision(examples["branch_page"]))
        elif self.path == self.fixture["routes"]["search"]:
            result = self._at_revision(examples["search"])
            result["query"] = body["query"]
            selection_id = "event:page-two" if body["query"] == "page two" else "arm:a"
            result["results"][0].update({"selection_id": selection_id, "title": f"{body['query'].title()} result", "section_id": "section:prologue", "is_loaded": False})
            self._json(result)
        elif self.path == self.fixture["routes"]["locate"]:
            selection_id = body["selection_id"]
            location = self._at_revision(examples["locate"])
            location["selection_id"] = selection_id
            if selection_id in {"event:intro", "event:rejoin", "event:page-two"}:
                page_cursor = "cursor:section:page-two" if selection_id == "event:page-two" else None
                item_id = "event:page-two" if page_cursor else selection_id
                location["location"] = {"section_id": "section:prologue", "branch_id": None, "page_cursor": page_cursor, "shell_id": "shell:prologue:two" if page_cursor else "shell:prologue", "item_id": item_id}
            else:
                location["location"] = {"section_id": "section:prologue", "branch_id": "choice:first", "page_cursor": None, "shell_id": "shell:branch:a", "item_id": "arm:a"}
            self._json(location)
        elif self.path == self.fixture["routes"]["path_page"]:
            page = self._at_revision(examples["path_page"])
            page["resource_id"] = body["selection_id"]
            self._json(page)
        elif self.path == self.fixture["routes"]["detail_page"]:
            page = self._at_revision(examples["detail_page"])
            page["resource_id"] = body["selection_id"]
            page["items"][0]["title"] = "Arrival" if body["selection_id"] == "event:intro" else "Route A"
            page["items"][0]["text"] = f"Detail for {body['selection_id']}."
            self._json(page)
        elif self.path == self.fixture["routes"]["view_state"]:
            state = type(self).view_state or {"section_id": "section:prologue", "selection_id": None, "focus_id": None, "viewport": {"scroll_top": 0, "zoom": 1.0}, "hide_new": False}
            response = self._at_revision(examples["view_state"])
            response["state"] = copy.deepcopy(state)
            self._json(response)
        elif self.path == self.fixture["routes"]["save_view_state"]:
            type(self).view_state = copy.deepcopy(body["state"])
            response = self._at_revision(examples["view_state"])
            response["state"] = copy.deepcopy(type(self).view_state)
            self._json(response)
@contextmanager
def _server(*, workflow: bool = False, workflow_status_mode: str = "complete", reader_available: bool = True, workflow_local_only: bool = False) -> Iterator[str]:
    _ReaderHandler.reset()
    _ReaderHandler.advertise_workflow = workflow
    _ReaderHandler.workflow_status_mode = workflow_status_mode
    _ReaderHandler.workflow_local_only = workflow_local_only
    _ReaderHandler.reader_available = reader_available
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _ReaderHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()


def _browser_driver() -> Any:
    source_root = str(ROOT / "src")
    if source_root not in sys.path:
        sys.path.insert(0, source_root)
    path = ROOT / "scripts" / "m10_browser_acceptance.py"
    spec = importlib.util.spec_from_file_location("m15_phase04_reader_driver", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_reader_v2_late_section_path_and_detail_responses_cannot_steal_state() -> None:
    driver = _browser_driver()
    try:
        browser = driver._browser()
    except FileNotFoundError:
        pytest.skip("Chrome or Edge is unavailable")
    with _server() as origin, tempfile.TemporaryDirectory(prefix="rsm-m15-p4-reader-races-", ignore_cleanup_errors=True) as temporary:
        process, session = driver._session(browser, 100, Path(temporary))
        try:
            session.command("Page.navigate", {"url": origin})
            session.wait("document.readyState === 'complete' && !!document.querySelector('.recent-card')")
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait("document.querySelector('#storySections h2')?.textContent === 'Prologue'")

            started = threading.Event()
            release = threading.Event()
            finished = threading.Event()
            _ReaderHandler.delayed_kind = "section_page"
            _ReaderHandler.delayed_resource = "section:epilogue"
            _ReaderHandler.delay_started = started
            _ReaderHandler.delay_release = release
            _ReaderHandler.delay_finished = finished
            session.evaluate("document.querySelector('#storySectionIndex [data-section-id=\"section:epilogue\"]').click()")
            assert started.wait(5), "delayed section request did not start"
            session.evaluate("document.querySelector('#storySectionIndex [data-section-id=\"section:prologue\"]').click()")
            session.wait("document.querySelector('#storySections h2')?.textContent === 'Prologue'")
            release.set()
            assert finished.wait(5), "delayed section request did not finish"
            assert session.evaluate("document.querySelector('#storySections h2').textContent") == "Prologue"

            started = threading.Event()
            release = threading.Event()
            finished = threading.Event()
            _ReaderHandler.delayed_kind = "search"
            _ReaderHandler.delayed_resource = "slow"
            _ReaderHandler.delay_started = started
            _ReaderHandler.delay_release = release
            _ReaderHandler.delay_finished = finished
            session.evaluate("document.querySelector('#storySearchInput').value='slow'; document.querySelector('#storySearchInput').dispatchEvent(new Event('input',{bubbles:true}))")
            assert started.wait(5), "delayed search request did not start"
            session.evaluate("document.querySelector('#storySearchInput').value='route'; document.querySelector('#storySearchInput').dispatchEvent(new Event('input',{bubbles:true}))")
            session.wait("document.querySelector('.story-search-result strong')?.textContent === 'Route result'")
            release.set()
            assert finished.wait(5), "delayed search request did not finish"
            assert session.evaluate("document.querySelector('.story-search-result strong').textContent") == "Route result"

            started = threading.Event()
            release = threading.Event()
            finished = threading.Event()
            _ReaderHandler.delayed_kind = "locate"
            _ReaderHandler.delayed_resource = "arm:a"
            _ReaderHandler.delay_started = started
            _ReaderHandler.delay_release = release
            _ReaderHandler.delay_finished = finished
            session.evaluate("document.querySelector('.story-search-result').click()")
            assert started.wait(5), "delayed locate request did not start"
            session.evaluate("document.querySelector('.story-rejoin button').click()")
            session.wait("document.activeElement?.dataset?.storySelectionId === 'event:rejoin'")
            release.set()
            assert finished.wait(5), "delayed locate request did not finish"
            assert session.evaluate("document.activeElement?.dataset?.storySelectionId") == "event:rejoin"

            session.evaluate("document.querySelector('.story-branch-action').click()")
            session.wait("!!document.querySelector('[data-reader-item-id=\"arm:a\"] [data-story-selection-id]')")
            started = threading.Event()
            release = threading.Event()
            finished = threading.Event()
            _ReaderHandler.delayed_kind = "path_page"
            _ReaderHandler.delayed_resource = "arm:a"
            _ReaderHandler.delay_started = started
            _ReaderHandler.delay_release = release
            _ReaderHandler.delay_finished = finished
            session.evaluate("document.querySelector('[data-reader-item-id=\"arm:a\"] [data-story-selection-id]').click()")
            assert started.wait(5), "delayed path request did not start"
            session.evaluate("document.querySelector('#closeStoryPath').click()")
            release.set()
            assert finished.wait(5), "delayed path request did not finish"
            assert session.evaluate("document.querySelector('#storyPathPanel').hidden") is True

            started = threading.Event()
            release = threading.Event()
            finished = threading.Event()
            _ReaderHandler.delayed_kind = "detail_page"
            _ReaderHandler.delayed_resource = "arm:a"
            _ReaderHandler.delay_started = started
            _ReaderHandler.delay_release = release
            _ReaderHandler.delay_finished = finished
            session.evaluate("document.querySelector('[data-reader-item-id=\"arm:a\"] .story-detail-button').click()")
            assert started.wait(5), "delayed detail request did not start"
            session.evaluate("document.querySelector('[data-reader-item-id=\"event:intro\"] .story-detail-button').click()")
            session.wait("!document.querySelector('#detailView').hidden && document.querySelector('#detailTitle').textContent === 'Arrival'")
            release.set()
            assert finished.wait(5), "delayed detail request did not finish"
            assert session.evaluate("document.querySelector('#detailTitle').textContent") == "Arrival"
            session.evaluate("document.querySelector('#backToRouteMap').click()")
            session.wait("document.activeElement?.dataset?.storySelectionId === 'event:intro'")
        finally:
            session.close()
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def test_workflow_v2_preview_requires_approval_and_uses_only_advertised_actions() -> None:
    driver = _browser_driver()
    try:
        browser = driver._browser()
    except FileNotFoundError:
        pytest.skip("Chrome or Edge is unavailable")
    with _server(workflow=True, workflow_status_mode="resumable", workflow_local_only=True) as origin, tempfile.TemporaryDirectory(prefix="rsm-m15-p4-workflow-", ignore_cleanup_errors=True) as temporary:
        process, session = driver._session(browser, 100, Path(temporary))
        try:
            session.command("Page.navigate", {"url": origin})
            session.wait("document.readyState === 'complete' && !!document.querySelector('.recent-card')")
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait("!document.querySelector('#storyBrowser').hidden && !document.querySelector('#storyPrepareAction').disabled")
            session.evaluate("document.querySelector('#storyPrepareAction').click()")
            session.wait("document.querySelector('#storyApprovalDialog').open")
            facts = session.evaluate("document.querySelector('#storyApprovalFacts').innerText")
            for expected in ("loopback-fixture", "qwen-fixture", "Not specified", "No private story text is sent to the cloud provider.", "Private story text may be sent to the configured local provider.", "1 chunk · 1 job", "6", "0"):
                assert expected in facts
            workflow_requests = [request for request in _ReaderHandler.requests if "/workflow/" in request[0]]
            assert workflow_requests == [("/api/v1/story-map-v2/workflow/prepare", {"contract": "story-map-v2-workflow-http-v2"})]
            assert session.evaluate("!document.querySelector('#storyCancelRun').hidden && document.querySelector('#storyResumeRun').hidden")

            session.evaluate("document.querySelector('#approveStoryGeneration').click()")
            session.wait("!document.querySelector('#storyResumeRun').hidden")
            session.evaluate("document.querySelector('#storyRunDetails').open = true")
            job_progress = session.evaluate("({hidden:document.querySelector('#storyRunDetails').hidden,rows:document.querySelectorAll('#storyRunRows tr').length,text:document.querySelector('#storyRunRows').innerText})")
            assert job_progress["hidden"] is False
            assert job_progress["rows"] == 1
            for expected in ("Query 1: story section 1, part 1", "Passed", "Added", "AI summary accepted"):
                assert expected in job_progress["text"]
            start = next(request for request in _ReaderHandler.requests if request[0].endswith("/start"))
            assert start[1] == {"contract": "story-map-v2-workflow-http-v2", "run_id": "run:fixture", "preview_identity": "a" * 64}
            session.evaluate("document.querySelector('#storyResumeRun').click()")
            session.wait("performance.getEntriesByType('resource').some(entry => entry.name.endsWith('/workflow/resume'))")
            resume = next(request for request in _ReaderHandler.requests if request[0].endswith("/resume"))
            assert resume[1] == {"contract": "story-map-v2-workflow-http-v2", "run_id": "run:fixture", "preview_identity": "a" * 64}
            session.evaluate("document.querySelector('#storyCancelRun').click()")
            session.wait("document.querySelector('#storyCancelRun').hidden")
            assert not [request for request in _ReaderHandler.requests if request[0].endswith("/retry")]
        finally:
            session.close()
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


@pytest.mark.parametrize(
    ("profile", "zoom", "width", "height", "device_scale"),
    [("desktop", 100, 1440, 900, 1), ("effective_200", 200, 720, 450, 2)],
)
def test_workflow_v2_first_generation_is_visible_without_reader_manifest(
    profile: str, zoom: int, width: int, height: int, device_scale: int
) -> None:
    driver = _browser_driver()
    try:
        browser = driver._browser()
    except FileNotFoundError:
        pytest.skip("Chrome or Edge is unavailable")
    with _server(workflow=True, reader_available=False) as origin, tempfile.TemporaryDirectory(prefix=f"rsm-m15-p4-first-generation-{profile}-", ignore_cleanup_errors=True) as temporary:
        process, session = driver._session(browser, zoom, Path(temporary))
        try:
            session.command("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": device_scale, "mobile": False})
            session.command("Page.navigate", {"url": origin})
            session.wait("document.readyState === 'complete' && !!document.querySelector('.recent-card')")
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait("!document.querySelector('#workspaceView').hidden && document.querySelector('#storyBrowser').hidden && document.querySelector('#storyPrepareAction').closest('.masthead-actions') && !document.querySelector('#storyPrepareAction').disabled")
            placement = session.evaluate("({label:document.querySelector('#storyPrepareAction').textContent,routeMapVisible:!document.querySelector('#routeMapView').hidden,overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth})")
            assert placement == {"label": "Generate", "routeMapVisible": True, "overflow": 0}
            session.evaluate("document.querySelector('#storyPrepareAction').click()")
            session.wait("document.querySelector('#storyApprovalDialog').open")
            facts = session.evaluate("document.querySelector('#storyApprovalFacts').innerText")
            for expected in ("codex-cli", "gpt-5.6-terra", "Private story text may be sent", "Maximum calls"):
                assert expected in facts
            session.evaluate("document.querySelector('#closeStoryApproval').click(); document.querySelector('#homeButton').click()")
            session.wait("!document.querySelector('#welcomeView').hidden && document.querySelector('#storyPrepareAction').hidden")
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait("!document.querySelector('#workspaceView').hidden && document.querySelector('#storyPrepareAction').closest('.masthead-actions') && !document.querySelector('#storyPrepareAction').hidden && !document.querySelector('#storyPrepareAction').disabled")
            workflow_requests = [request for request in _ReaderHandler.requests if "/workflow/" in request[0]]
            assert workflow_requests == [("/api/v1/story-map-v2/workflow/prepare", {"contract": "story-map-v2-workflow-http-v2"})]
        finally:
            session.close()
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def test_workflow_v2_reopen_restores_status_and_resumes_without_starting_again() -> None:
    driver = _browser_driver()
    try:
        browser = driver._browser()
    except FileNotFoundError:
        pytest.skip("Chrome or Edge is unavailable")
    with _server(workflow=True, workflow_status_mode="resumable") as origin, tempfile.TemporaryDirectory(prefix="rsm-m15-p4-workflow-reopen-", ignore_cleanup_errors=True) as temporary:
        process, session = driver._session(browser, 100, Path(temporary))
        try:
            session.command("Page.navigate", {"url": origin})
            session.wait("document.readyState === 'complete' && !!document.querySelector('.recent-card')")
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait("!document.querySelector('#storyPrepareAction').disabled")
            session.evaluate("document.querySelector('#storyPrepareAction').click()")
            session.wait("document.querySelector('#storyApprovalDialog').open")
            session.evaluate("document.querySelector('#approveStoryGeneration').click()")
            session.wait("!document.querySelector('#storyResumeRun').hidden && document.querySelector('#storyRunProgress').textContent === '1 of 3 jobs completed'")
            stored = session.evaluate("JSON.parse(localStorage.getItem('rsm.story-map-v2.workflow.v2'))")
            assert stored == {"contract": "story-map-v2-workflow-http-v2", "run_id": "run:fixture", "preview_identity": "a" * 64}
            starts_before = len([request for request in _ReaderHandler.requests if request[0].endswith("/workflow/start")])
            statuses_before = len([request for request in _ReaderHandler.requests if request[0].endswith("/workflow/status")])

            session.evaluate("document.documentElement.dataset.testReload='old'; location.reload()")
            session.wait("document.documentElement.dataset.testReload !== 'old' && document.readyState === 'complete' && !!document.querySelector('.recent-card')")
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait("!document.querySelector('#storyResumeRun').hidden && document.querySelector('#storyRunProgress').textContent === '1 of 3 jobs completed'")
            assert len([request for request in _ReaderHandler.requests if request[0].endswith("/workflow/status")]) > statuses_before
            assert len([request for request in _ReaderHandler.requests if request[0].endswith("/workflow/start")]) == starts_before == 1
            assert not [request for request in _ReaderHandler.requests if request[0].endswith("/workflow/prepare")][1:]

            session.evaluate("document.querySelector('#storyResumeRun').click()")
            session.wait("performance.getEntriesByType('resource').filter(entry => entry.name.endsWith('/workflow/resume')).length === 1")
            resumes = [request for request in _ReaderHandler.requests if request[0].endswith("/workflow/resume")]
            assert len(resumes) == 1
            assert resumes[0][1] == {"contract": "story-map-v2-workflow-http-v2", "run_id": "run:fixture", "preview_identity": "a" * 64}
            session.evaluate("document.querySelector('#storyCancelRun').click()")
            session.wait("localStorage.getItem('rsm.story-map-v2.workflow.v2') === null")
        finally:
            session.close()
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


@pytest.mark.parametrize(
    ("profile", "zoom", "width", "height", "device_scale"),
    [("desktop", 100, 1440, 900, 1), ("effective_200", 200, 720, 450, 2), ("narrow", 100, 390, 844, 1)],
)
def test_workflow_v2_completion_refreshes_reader_without_layout_overflow(
    profile: str, zoom: int, width: int, height: int, device_scale: int
) -> None:
    driver = _browser_driver()
    try:
        browser = driver._browser()
    except FileNotFoundError:
        pytest.skip("Chrome or Edge is unavailable")
    with _server(workflow=True) as origin, tempfile.TemporaryDirectory(prefix=f"rsm-m15-p4-workflow-{profile}-", ignore_cleanup_errors=True) as temporary:
        process, session = driver._session(browser, zoom, Path(temporary))
        try:
            session.command("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": device_scale, "mobile": False})
            session.command("Page.navigate", {"url": origin})
            session.wait("document.readyState === 'complete' && !!document.querySelector('.recent-card')")
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait("!document.querySelector('#storyPrepareAction').disabled")
            session.evaluate("document.querySelector('#storyPrepareAction').click()")
            session.wait("document.querySelector('#storyApprovalDialog').open")
            session.evaluate("document.querySelector('#approveStoryGeneration').click()")
            session.wait("document.querySelector('#storyBrowser').dataset.mapRevision === '8' && document.querySelector('#storyRunProgress').textContent === '3 of 3 jobs completed'")
            result = session.evaluate("({generation:document.querySelector('#storyBrowser').dataset.generationId,overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,progress:document.querySelector('#storyRunProgress').textContent,cancelHidden:document.querySelector('#storyCancelRun').hidden,resumeHidden:document.querySelector('#storyResumeRun').hidden})")
            assert result == {"generation": "generation:complete:8", "overflow": 0, "progress": "3 of 3 jobs completed", "cancelHidden": True, "resumeHidden": True}, {"result": result, "toast": session.evaluate("document.querySelector('#toast').textContent"), "requests": _ReaderHandler.requests[-12:]}
        finally:
            session.close()
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


@pytest.mark.parametrize(
    ("profile", "zoom", "width", "height", "device_scale"),
    [("desktop", 100, 1440, 900, 1), ("effective_200", 200, 720, 450, 2), ("narrow", 100, 390, 844, 1)],
)
def test_reader_v2_real_browser_lazy_reader_and_restoration(
    profile: str, zoom: int, width: int, height: int, device_scale: int
) -> None:
    driver = _browser_driver()
    try:
        browser = driver._browser()
    except FileNotFoundError:
        pytest.skip("Chrome or Edge is unavailable")
    with _server() as origin, tempfile.TemporaryDirectory(prefix=f"rsm-m15-p4-reader-{profile}-", ignore_cleanup_errors=True) as temporary:
        process, session = driver._session(browser, zoom, Path(temporary))
        try:
            session.command("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": device_scale, "mobile": False})
            session.command("Page.navigate", {"url": origin})
            session.wait("document.readyState === 'complete' && !!document.querySelector('.recent-card')")
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait("!document.querySelector('#storyBrowser').hidden && document.querySelectorAll('[data-reader-item-id]').length === 3")
            initial = session.evaluate("({revision:document.querySelector('#storyBrowser').dataset.mapRevision,live:Number(document.querySelector('#storyBrowser').dataset.liveStoryItems),sections:document.querySelectorAll('#storySections > .story-section').length,branchCalls:0,overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,prepareDisabled:document.querySelector('#storyPrepareAction').disabled})")
            assert initial == {"revision": "7", "live": 3, "sections": 1, "branchCalls": 0, "overflow": 0, "prepareDisabled": True}
            assert not [request for request in _ReaderHandler.requests if request[0] == _ReaderHandler.fixture["routes"]["branch_page"]]

            session.evaluate("document.querySelector('.story-branch-action').focus(); document.querySelector('.story-branch-action').click()")
            session.wait("document.querySelectorAll('.story-branch-page:not([hidden]) [data-reader-item-id]').length === 2")
            disclosure = session.evaluate("({focused:document.activeElement===document.querySelector('.story-branch-action'),visible:!document.querySelector('.story-branch-action').hidden,expanded:document.querySelector('.story-branch-action').getAttribute('aria-expanded')})")
            assert disclosure == {"focused": True, "visible": True, "expanded": "true"}
            session.evaluate("document.querySelector('#storySearchInput').value='route'; document.querySelector('#storySearchInput').dispatchEvent(new Event('input',{bubbles:true}))")
            session.wait("!document.querySelector('#storySearchResults').hidden && !!document.querySelector('.story-search-result')")
            session.evaluate("document.querySelector('.story-search-result').click()")
            session.wait("document.activeElement?.dataset?.storySelectionId === 'arm:a'")
            session.evaluate("document.activeElement.click()")
            session.wait("!document.querySelector('#storyPathPanel').hidden && document.querySelector('#storyPathSteps').children.length === 2")
            assert "Path" in session.evaluate("document.querySelector('#storyPathTitle').textContent") or session.evaluate("document.querySelector('#storyPathTitle').textContent") == "Take Route A"
            entry_scroll = session.evaluate("const browser=document.querySelector('#storyBrowser'); browser.style.height='120px'; browser.style.overflow='auto'; browser.scrollTop=80; document.querySelector('[data-story-selection-id=\"arm:a\"][aria-selected=\"true\"]').focus(); browser.scrollTop")
            session.evaluate("document.querySelector('#storyDetailAction').click()")
            session.wait("!document.querySelector('#detailView').hidden && document.querySelector('#evidenceList').textContent.includes('game/story.rpy')")
            session.evaluate("document.querySelector('#backToRouteMap').click()")
            session.wait("document.activeElement?.dataset?.storySelectionId === 'arm:a'")
            assert session.evaluate("document.querySelector('#storyBrowser').scrollTop") == entry_scroll

            saved_before = session.evaluate("document.querySelector('#storyBrowser').dataset.viewStateSaved || ''")
            content_requests_before = len(_ReaderHandler.requests)
            session.evaluate("document.querySelector('.story-branch-page [data-reader-item-id]').dataset.preserveMarker='hydrated'; document.querySelector('[data-story-selection-id=\"arm:a\"][aria-selected=\"true\"]').focus()")
            session.evaluate("document.querySelector('#storyHideNew').click()")
            session.wait("document.querySelector('#storyBrowser').classList.contains('hide-new')")
            session.wait(f"document.querySelector('#storyBrowser').dataset.viewStateSaved?.startsWith('7:') && document.querySelector('#storyBrowser').dataset.viewStateSaved !== {json.dumps(saved_before)}")
            preserved = session.evaluate("({marker:document.querySelector('.story-branch-page [data-reader-item-id]')?.dataset.preserveMarker || null,selected:document.querySelector('[data-story-selection-id=\"arm:a\"][aria-selected=\"true\"]')?.dataset.storySelectionId || null,focused:document.activeElement?.dataset?.storySelectionId || null,scroll:document.querySelector('#storyBrowser').scrollTop})")
            assert preserved == {"marker": "hydrated", "selected": "arm:a", "focused": "arm:a", "scroll": entry_scroll}
            new_requests = _ReaderHandler.requests[content_requests_before:]
            assert [request[0] for request in new_requests] == [_ReaderHandler.fixture["routes"]["save_view_state"]]

            session.evaluate("document.querySelector('#storySearchInput').value='page two'; document.querySelector('#storySearchInput').dispatchEvent(new Event('input',{bubbles:true}))")
            session.wait("document.querySelector('.story-search-result strong')?.textContent === 'Page Two result'")
            session.evaluate("document.querySelector('.story-search-result').click()")
            session.wait("document.activeElement?.dataset?.storySelectionId === 'event:page-two'")
            page_two_requests = [request for request in _ReaderHandler.requests if request[0] == _ReaderHandler.fixture["routes"]["section_page"] and request[1].get("cursor") == "cursor:section:page-two"]
            assert page_two_requests and page_two_requests[-1][1]["section_id"] == "section:prologue"

            session.evaluate("const section=document.querySelector('#storySections'); const other=Number(document.querySelector('#storyPathPanel').dataset.storyRecords||0)+Number(document.querySelector('#detailView').dataset.storyRecords||0)+Number(document.querySelector('#storySearchResults').dataset.storyRecords||0); const existing=section.querySelectorAll('[data-reader-item-id]').length; for(let i=existing+other;i<600;i++){const node=document.createElement('i'); node.dataset.readerItemId=`budget:${i}`; node.dataset.budgetFixture='true'; section.append(node)} document.querySelector('#storySearchInput').value='over cap'; document.querySelector('#storySearchInput').dispatchEvent(new Event('input',{bubbles:true}))")
            session.wait("document.querySelector('#toast').textContent.includes('live story-record limit')")
            assert session.evaluate("document.querySelectorAll('[data-reader-item-id]').length+Number(document.querySelector('#storyPathPanel').dataset.storyRecords||0)+Number(document.querySelector('#detailView').dataset.storyRecords||0)+Number(document.querySelector('#storySearchResults').dataset.storyRecords||0)") <= 600
            session.evaluate("document.querySelectorAll('[data-budget-fixture]').forEach(node=>node.remove())")
            session.evaluate("document.documentElement.dataset.testReload='old'; location.reload()")
            session.wait("document.documentElement.dataset.testReload !== 'old' && document.readyState === 'complete' && !!document.querySelector('.recent-card')")
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait("!document.querySelector('#storyBrowser').hidden || !document.querySelector('#toast').hidden")
            reopen = session.evaluate("({visible:!document.querySelector('#storyBrowser').hidden,checked:document.querySelector('#storyHideNew').checked,toast:document.querySelector('#toast').textContent,revision:document.querySelector('#storyBrowser').dataset.mapRevision,active:document.activeElement?.dataset?.storySelectionId || null})")
            assert reopen["visible"] and reopen["checked"], {"browser": reopen, "view_state": _ReaderHandler.view_state, "requests": _ReaderHandler.requests[-12:]}
            assert reopen["active"] == "event:page-two"
            assert not [request for request in _ReaderHandler.requests if "/workflow/" in request[0]]
            restored = session.evaluate("({selected:document.querySelector('[data-story-selection-id=\"event:page-two\"][aria-selected=\"true\"]')?.dataset.storySelectionId || null,live:Number(document.querySelector('#storyBrowser').dataset.liveStoryItems),overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,remote:[...performance.getEntriesByType('resource')].map(x=>x.name).filter(x=>!x.startsWith(location.origin))})")
            assert restored["selected"] == "event:page-two"
            assert restored["live"] <= 600
            assert restored["overflow"] == 0
            assert restored["remote"] == []

            _ReaderHandler.revision = 8
            session.evaluate("document.querySelector('#storySearchInput').value='ending'; document.querySelector('#storySearchInput').dispatchEvent(new Event('input',{bubbles:true}))")
            session.wait("document.querySelector('#storyBrowser').dataset.mapRevision === '8'")
            assert session.evaluate("document.querySelector('#storyMapStatus').textContent") == "Current map"
        finally:
            session.close()
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            shutil.rmtree(temporary, ignore_errors=True)
