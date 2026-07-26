# ruff: noqa: E501
"""Run the public provider-free M15.1 Phase 04 reader scale/browser matrix."""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

ROOT: Final = Path(__file__).resolve().parents[1]
FIXTURES: Final = ROOT / "tests" / "fixtures" / "story_map_v2"
PROFILE_PATH: Final = FIXTURES / "phase04_scale_profile_v1.json"
BASE_CONTRACT_PATH: Final = FIXTURES / "phase04_reader_contract_v1.json"
V2_CONTRACT_PATH: Final = FIXTURES / "phase04_reader_contract_v2.json"
HTML_PATH: Final = FIXTURES / "phase04_scale_harness.html"
HARNESS_JS_PATH: Final = FIXTURES / "phase04_scale_harness.js"
DIFF_JS_PATH: Final = (
    ROOT / "src" / "renpy_story_mapper" / "web" / "static" / "story-map-v2-diff.js"
)
SCHEMA: Final = "story-map-v2-reader-contract-v2"


class InvalidCursor(ValueError):
    pass


class StaleRevision(ValueError):
    pass


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain an object")
    return value


def contract_bundle() -> dict[str, Any]:
    base = _load_object(BASE_CONTRACT_PATH)
    extension = _load_object(V2_CONTRACT_PATH)
    return {
        **base,
        "schema": extension["schema"],
        "extends": extension["extends"],
        "delta": extension["delta"],
    }


class ScaleDataset:
    """Deterministic lazy v2 API fixture; it stores no monolithic story payload."""

    def __init__(self) -> None:
        self.profile = _load_object(PROFILE_PATH)
        self.contract = contract_bundle()
        counts = self.profile["counts"]
        self.event_count = int(counts["events"])
        self.choice_count = int(counts["choices"])
        self.arm_count = int(counts["arms"])
        self.rejoin_count = int(counts["rejoins"])
        self.section_count = int(counts["sections"])
        base, remainder = divmod(self.event_count, self.section_count)
        self.section_sizes = tuple(
            base + (1 if index < remainder else 0) for index in range(self.section_count)
        )
        starts: list[int] = []
        current = 0
        for size in self.section_sizes:
            starts.append(current)
            current += size
        self.section_starts = tuple(starts)
        if current != self.event_count:
            raise AssertionError("scale fixture event distribution drifted")
        self._secret = b"phase04-public-cursor-v1"
        self.reset()

    def reset(self) -> None:
        self.map_revision = 7
        self.freshness = "current"
        self.wording_epoch = 0
        self.view_state: dict[str, Any] = {
            "section_id": "section:0",
            "selection_id": "event:0",
            "focus_id": "event:0",
            "viewport": {"scroll_top": 0, "zoom": 1.0},
            "hide_new": False,
        }

    def _base(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "map_revision": self.map_revision,
            "generation_id": f"generation:scale:{self.map_revision}",
        }

    def section_for_event(self, event_index: int) -> int:
        if event_index < 0 or event_index >= self.event_count:
            raise KeyError("unknown event")
        low, high = 0, self.section_count
        while low + 1 < high:
            middle = (low + high) // 2
            if self.section_starts[middle] <= event_index:
                low = middle
            else:
                high = middle
        return low

    def section_events(self, section_index: int) -> range:
        if section_index < 0 or section_index >= self.section_count:
            raise KeyError("unknown section")
        start = self.section_starts[section_index]
        return range(start, start + self.section_sizes[section_index])

    def manifest(self) -> dict[str, Any]:
        sections = []
        for index, size in enumerate(self.section_sizes):
            is_new = index == self.section_count - 1
            route_id = "route:persistent-50" if 100 <= index < 150 else None
            summary_suffix = " Revised wording." if self.wording_epoch and index == 0 else ""
            sections.append(
                {
                    "id": f"section:{index}",
                    "order": index,
                    "title": f"Section {index + 1}",
                    "summary": f"Public deterministic section {index + 1}.{summary_suffix}",
                    "route_id": route_id,
                    "status": "complete",
                    "event_count": size,
                    "is_new": is_new,
                    "new_facts": (
                        [{"kind": "ending", "fact_id": "ending:final"}] if is_new else []
                    ),
                }
            )
        return {
            **self._base(),
            "freshness": self.freshness,
            "status": "complete",
            "overview": {
                "title": "Deterministic full-story scale fixture",
                "summary": "Wording-only refresh." if self.wording_epoch else "Initial wording.",
            },
            "counts": {
                "sections": self.section_count,
                "events": self.event_count,
                "choices": self.choice_count,
                "arms": self.arm_count,
                "rejoins": self.rejoin_count,
                "endings": 1,
            },
            "sections": sections,
            "landmarks": [
                {
                    "kind": "route",
                    "id": "route:persistent-50",
                    "section_id": "section:100",
                    "selection_id": f"event:{self.section_starts[100]}",
                    "title": "Fifty-section route",
                },
                {
                    "kind": "ending",
                    "id": "ending:final",
                    "section_id": "section:255",
                    "selection_id": "event:4999",
                    "title": "Final target",
                },
            ],
            "new_facts": {
                "baseline_generation_id": "generation:scale:6",
                "facts": [
                    {
                        "kind": "ending",
                        "fact_id": "ending:final",
                        "section_ids": ["section:255"],
                    },
                    {
                        "kind": "arm",
                        "fact_id": "arm:303",
                        "section_ids": ["section:0"],
                    },
                ],
            },
        }

    def status(self) -> dict[str, Any]:
        return {
            **self._base(),
            "run_id": "run:public-scale",
            "freshness": self.freshness,
            "state": "complete",
            "coverage": {"completed_chunks": 256, "total_chunks": 256, "event_fraction": 1.0},
            "progress": {
                "completed_jobs": 256,
                "total_jobs": 256,
                "failed_jobs": 0,
                "indeterminate_jobs": 0,
            },
            "actions": {
                "can_cancel": False,
                "can_resume": False,
                "retry_approval_required": False,
            },
            "current_complete_generation": f"generation:scale:{self.map_revision}",
            "active_build_generation": None,
        }

    def _event_item(self, event_index: int) -> dict[str, Any]:
        is_final = event_index == self.event_count - 1
        return {
            "id": f"event:{event_index}",
            "kind": "ending" if is_final else "event",
            "order": event_index,
            "title": "Final target" if is_final else f"Event {event_index}",
            "summary": f"Deterministic event {event_index}.",
            "selection_id": f"event:{event_index}",
            "is_new": is_final,
            "new_facts": ([{"kind": "ending", "fact_id": "ending:final"}] if is_final else []),
        }

    def section_page(self, body: Mapping[str, Any]) -> dict[str, Any]:
        self._require_revision(body)
        section_id = str(body["section_id"])
        section_index = int(section_id.removeprefix("section:"))
        event_ids = self.section_events(section_index)
        items: list[dict[str, Any]] = []
        item_ids: list[str] = []
        for event_index in event_ids:
            event = self._event_item(event_index)
            choice = {
                "id": f"choice:{event_index}",
                "kind": "choice",
                "order": event_index,
                "title": f"Choice {event_index}",
                "summary": "Four deterministic alternatives.",
                "selection_id": f"choice:{event_index}",
                "is_new": False,
                "new_facts": [],
            }
            items.extend((event, choice))
            item_ids.extend((event["id"], choice["id"]))
        return {
            **self._base(),
            "resource_id": section_id,
            "items": items,
            "shells": [
                {
                    "id": f"shell:{section_id}",
                    "kind": "timeline",
                    "item_ids": item_ids,
                    "parent_shell_id": None,
                    "route_id": "route:persistent-50" if 100 <= section_index < 150 else None,
                    "rejoin_selection_id": None,
                }
            ],
            "rendered_item_count": len(items),
            "next_cursor": None,
        }

    def branch_page(self, body: Mapping[str, Any]) -> dict[str, Any]:
        self._require_revision(body)
        branch_id = str(body["branch_id"])
        choice_index = int(branch_id.removeprefix("choice:"))
        limit = int(body.get("limit", 240))
        if limit < 1 or limit > 240:
            raise ValueError("invalid limit")
        offset = 0
        cursor = body.get("cursor")
        if cursor is not None:
            offset = self._read_cursor(
                str(cursor), endpoint="branch_page", resource_id=branch_id, limit=limit
            )
        arm_total = 304 if choice_index == 0 else 4
        stop = min(offset + limit, arm_total)
        items: list[dict[str, Any]] = []
        shells: list[dict[str, Any]] = []
        for ordinal in range(offset, stop):
            arm_id = f"arm:{ordinal}" if choice_index == 0 else f"arm:{choice_index}:{ordinal}"
            is_new = choice_index == 0 and ordinal == 303
            depth = ordinal + 1 if choice_index == 0 and ordinal < 8 else 1
            item = {
                "id": arm_id,
                "kind": "arm",
                "order": ordinal,
                "title": f"Arm {choice_index}.{ordinal}",
                "selection_id": arm_id,
                "condition": None if ordinal % 2 == 0 else f"flag_{choice_index} > 0",
                "effects": [f"route_{choice_index}_{ordinal} = true"],
                "depth": depth,
                "is_new": is_new,
                "new_facts": ([{"kind": "arm", "fact_id": "arm:303"}] if is_new else []),
            }
            items.append(item)
            rejoin = self._rejoin_for_choice(choice_index)
            shells.append(
                {
                    "id": f"shell:{arm_id}",
                    "kind": "branch",
                    "item_ids": [arm_id],
                    "parent_shell_id": (
                        f"shell:arm:{ordinal - 1}"
                        if choice_index == 0 and 1 < depth <= 8
                        else f"shell:choice:{choice_index}"
                    ),
                    "route_id": "route:persistent-50"
                    if 100 <= self.section_for_event(choice_index) < 150
                    else None,
                    "rejoin_selection_id": rejoin,
                }
            )
        next_cursor = (
            self._cursor("branch_page", branch_id, stop, limit) if stop < arm_total else None
        )
        return {
            **self._base(),
            "resource_id": branch_id,
            "items": items,
            "shells": shells,
            "rendered_item_count": len(items),
            "next_cursor": next_cursor,
        }

    def _rejoin_for_choice(self, choice_index: int) -> str | None:
        if choice_index >= self.rejoin_count:
            return None
        if choice_index == 19:
            return f"event:{self.section_starts[20]}"
        return f"event:{min(choice_index + 1, self.event_count - 1)}"

    def locate(self, body: Mapping[str, Any]) -> dict[str, Any]:
        self._require_revision(body)
        selection_id = str(body["selection_id"])
        branch_id: str | None = None
        page_cursor: str | None = None
        if selection_id.startswith("event:") or selection_id.startswith("choice:"):
            event_index = int(selection_id.split(":", 1)[1])
            section_index = self.section_for_event(event_index)
            item_id = selection_id
            shell_id = f"shell:section:{section_index}"
        elif selection_id.startswith("arm:"):
            parts = selection_id.split(":")
            if len(parts) == 2:
                choice_index, ordinal = 0, int(parts[1])
            elif len(parts) == 3:
                choice_index, ordinal = int(parts[1]), int(parts[2])
            else:
                raise KeyError("unknown selection")
            section_index = self.section_for_event(choice_index)
            branch_id = f"choice:{choice_index}"
            offset = (ordinal // 240) * 240
            page_cursor = self._cursor("branch_page", branch_id, offset, 240) if offset else None
            item_id = selection_id
            shell_id = f"shell:{selection_id}"
        else:
            raise KeyError("unknown selection")
        return {
            **self._base(),
            "selection_id": selection_id,
            "location": {
                "section_id": f"section:{section_index}",
                "branch_id": branch_id,
                "page_cursor": page_cursor,
                "shell_id": shell_id,
                "item_id": item_id,
            },
        }

    def search(self, body: Mapping[str, Any]) -> dict[str, Any]:
        self._require_revision(body)
        query = str(body.get("query", ""))
        results = []
        if "final target" in query.casefold():
            results.append(
                {
                    "selection_id": "event:4999",
                    "kind": "ending",
                    "title": "Final target",
                    "snippet": "The final-section target.",
                    "section_id": "section:255",
                    "is_loaded": False,
                }
            )
        return {**self._base(), "query": query, "results": results, "next_cursor": None}

    def path_page(self, body: Mapping[str, Any]) -> dict[str, Any]:
        self._require_revision(body)
        selection_id = str(body["selection_id"])
        items = [
            {
                "id": f"path-step:{index}",
                "kind": "path_step",
                "order": index,
                "title": f"Persistent route section {index + 1}",
                "selection_id": f"event:{self.section_starts[100 + index]}",
            }
            for index in range(50)
        ]
        items.append(
            {
                "id": "path-step:final",
                "kind": "path_step",
                "order": 50,
                "title": "Final target",
                "selection_id": selection_id,
            }
        )
        return self._page(selection_id, items, "path", "route:persistent-50", None)

    def detail_page(self, body: Mapping[str, Any]) -> dict[str, Any]:
        self._require_revision(body)
        selection_id = str(body["selection_id"])
        items = [
            {
                "id": "detail:summary",
                "kind": "summary",
                "title": "Final target",
                "text": "The public fixture reaches the final section.",
            },
            {
                "id": "detail:evidence",
                "kind": "evidence",
                "title": "Evidence",
                "relative_path": "game/public_scale_story.rpy",
                "start_line": 5000,
                "end_line": 5001,
                "line_basis": "physical",
            },
        ]
        return self._page(selection_id, items, "detail", None, None)

    def _page(
        self,
        resource_id: str,
        items: list[dict[str, Any]],
        kind: str,
        route_id: str | None,
        rejoin: str | None,
    ) -> dict[str, Any]:
        return {
            **self._base(),
            "resource_id": resource_id,
            "items": items,
            "shells": [
                {
                    "id": f"shell:{kind}",
                    "kind": kind,
                    "item_ids": [str(item["id"]) for item in items],
                    "parent_shell_id": None,
                    "route_id": route_id,
                    "rejoin_selection_id": rejoin,
                }
            ],
            "rendered_item_count": len(items),
            "next_cursor": None,
        }

    def read_view_state(self, body: Mapping[str, Any]) -> dict[str, Any]:
        self._require_revision(body)
        return {
            **self._base(),
            "view_key": str(body["view_key"]),
            "state": dict(self.view_state),
        }

    def save_view_state(self, body: Mapping[str, Any]) -> dict[str, Any]:
        self._require_revision(body)
        state = body.get("state")
        if not isinstance(state, dict) or not isinstance(state.get("hide_new"), bool):
            raise ValueError("invalid view state")
        self.view_state = dict(state)
        return {
            **self._base(),
            "view_key": str(body["view_key"]),
            "state": dict(self.view_state),
        }

    def refresh(self) -> dict[str, Any]:
        self.map_revision += 1
        self.freshness = "stale"
        self.wording_epoch += 1
        return {**self._base(), "freshness": self.freshness}

    def _require_revision(self, body: Mapping[str, Any]) -> None:
        if body.get("map_revision") != self.map_revision:
            raise StaleRevision("stale map revision")

    def _cursor(self, endpoint: str, resource_id: str, offset: int, limit: int) -> str:
        payload = json.dumps(
            {
                "schema": SCHEMA,
                "map_revision": self.map_revision,
                "endpoint": endpoint,
                "resource_id": resource_id,
                "order": "authority",
                "offset": offset,
                "limit": limit,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        signature = hashlib.sha256(self._secret + payload).hexdigest()[:24]
        return f"{encoded}.{signature}"

    def _read_cursor(self, token: str, *, endpoint: str, resource_id: str, limit: int) -> int:
        try:
            encoded, signature = token.split(".", 1)
            payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            expected = hashlib.sha256(self._secret + payload).hexdigest()[:24]
            if signature != expected:
                raise InvalidCursor("cursor signature mismatch")
            value = json.loads(payload)
        except (ValueError, json.JSONDecodeError) as error:
            raise InvalidCursor("invalid cursor") from error
        if value.get("map_revision") != self.map_revision:
            raise StaleRevision("stale cursor revision")
        expected_fields = {
            "schema": SCHEMA,
            "endpoint": endpoint,
            "resource_id": resource_id,
            "order": "authority",
            "limit": limit,
        }
        if any(value.get(key) != expected_value for key, expected_value in expected_fields.items()):
            raise InvalidCursor("cursor binding mismatch")
        offset = value.get("offset")
        if not isinstance(offset, int) or offset < 0:
            raise InvalidCursor("cursor offset is invalid")
        return offset


def _handler(dataset: ScaleDataset) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "StoryMapScaleHarness/1"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:
            route = urlsplit(self.path).path
            if route == "/favicon.ico":
                self.send_response(HTTPStatus.NO_CONTENT)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            assets = {
                "/": (HTML_PATH, "text/html; charset=utf-8"),
                "/harness.js": (HARNESS_JS_PATH, "text/javascript; charset=utf-8"),
                "/static/story-map-v2-diff.js": (DIFF_JS_PATH, "text/javascript; charset=utf-8"),
            }
            if route == "/contract":
                self._json(HTTPStatus.OK, dataset.contract)
                return
            asset = assets.get(route)
            if asset is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            data = asset[0].read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", asset[1])
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 1_048_576:
                    raise ValueError("request is too large")
                raw = self.rfile.read(length)
                body = json.loads(raw or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("request body must be an object")
                route = urlsplit(self.path).path
                routes = dataset.contract["routes"]
                if route == routes["manifest"]:
                    payload = dataset.manifest()
                elif route == routes["status"]:
                    payload = dataset.status()
                elif route == routes["section_page"]:
                    payload = dataset.section_page(body)
                elif route == routes["branch_page"]:
                    payload = dataset.branch_page(body)
                elif route == routes["locate"]:
                    payload = dataset.locate(body)
                elif route == routes["search"]:
                    payload = dataset.search(body)
                elif route == routes["path_page"]:
                    payload = dataset.path_page(body)
                elif route == routes["detail_page"]:
                    payload = dataset.detail_page(body)
                elif route == routes["view_state"]:
                    payload = dataset.read_view_state(body)
                elif route == routes["save_view_state"]:
                    payload = dataset.save_view_state(body)
                elif route == "/harness/refresh":
                    payload = dataset.refresh()
                else:
                    self._error(HTTPStatus.NOT_FOUND, "not_found", "Unknown local harness route.")
                    return
                self._json(HTTPStatus.OK, payload, bounded_page="-page" in route)
            except StaleRevision:
                self._json(
                    HTTPStatus.CONFLICT,
                    {
                        "error": {
                            "code": "stale_map_revision",
                            "message": "The requested map revision is stale.",
                        },
                        "map_revision": dataset.map_revision,
                    },
                )
            except InvalidCursor:
                self._error(HTTPStatus.BAD_REQUEST, "invalid_cursor", "The cursor is invalid.")
            except (KeyError, TypeError, ValueError) as error:
                self._error(HTTPStatus.BAD_REQUEST, "invalid_request", str(error))

        def _error(self, status: HTTPStatus, code: str, message: str) -> None:
            self._json(
                status,
                {
                    "error": {"code": code, "message": message},
                    "map_revision": dataset.map_revision,
                },
            )

        def _json(
            self, status: HTTPStatus, payload: Mapping[str, Any], *, bounded_page: bool = False
        ) -> None:
            data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
            if bounded_page and len(data) > 1_048_576:
                raise AssertionError("fixture page exceeds the 1 MiB contract")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

    return Handler


def _cdp_module() -> Any:
    path = ROOT / "scripts" / "m07_browser_acceptance.py"
    spec = importlib.util.spec_from_file_location("rsm_phase04_cdp", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the repository CDP driver")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _devtools_page(port: int) -> dict[str, Any]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connection.request("GET", "/json")
    response = connection.getresponse()
    pages = json.loads(response.read())
    connection.close()
    return next(page for page in pages if page.get("type") == "page")


def _capture_profile(
    driver: Any,
    browser: Path,
    origin: str,
    output_dir: Path,
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    profile_id = str(profile["id"])
    width, height = int(profile["width"]), int(profile["height"])
    scale = int(profile["device_scale_factor"])
    with tempfile.TemporaryDirectory(
        prefix=f"rsm-p4-{profile_id}-", ignore_cleanup_errors=True
    ) as user_data:
        command = [
            str(browser),
            "--headless=new",
            "--remote-debugging-port=0",
            "--remote-allow-origins=*",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-domain-reliability",
            "--disable-features=OptimizationHints,MediaRouter,Translate",
            "--disable-sync",
            "--metrics-recording-only",
            "--no-first-run",
            "--no-pings",
            "--password-store=basic",
            "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1, EXCLUDE localhost",
            f"--user-data-dir={user_data}",
            "about:blank",
        ]
        if scale == 2:
            command.insert(-1, "--force-device-scale-factor=2")
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        active = Path(user_data) / "DevToolsActivePort"
        deadline = time.monotonic() + 20
        while not active.is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not active.is_file():
            process.terminate()
            raise RuntimeError("Chrome did not publish its DevTools port")
        port = int(active.read_text(encoding="utf-8").splitlines()[0])
        session: Any | None = None
        try:
            session = driver._Cdp(str(_devtools_page(port)["webSocketDebuggerUrl"]))
            for domain in (
                "Page.enable",
                "Runtime.enable",
                "Network.enable",
                "Log.enable",
                "Performance.enable",
            ):
                session.command(domain)
            session.command(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": width,
                    "height": height,
                    "deviceScaleFactor": scale,
                    "mobile": False,
                },
            )
            session.command("Page.navigate", {"url": origin})
            startup_navigation_retries = 0
            try:
                session.wait("window.harnessState?.ready === true", timeout=15)
            except TimeoutError:
                startup_navigation_retries = 1
                first_navigation = session.evaluate(
                    "({href:location.href,ready:document.readyState,"
                    "errors:window.harnessState?.errors || null})"
                )
                session.command("Page.navigate", {"url": origin})
                try:
                    session.wait("window.harnessState?.ready === true", timeout=20)
                except TimeoutError as error:
                    raise TimeoutError(
                        f"Harness did not initialize after one local navigation retry: "
                        f"{first_navigation}"
                    ) from error
            initial = session.evaluate(
                "({freshness:document.querySelector('#freshness').dataset.freshness,errors:window.harnessState.errors})"
            )
            if initial["freshness"] != "current" or initial["errors"]:
                raise AssertionError(f"initial current presentation failed: {initial}")

            session.evaluate("window.phase04Harness.searchFinal()")
            session.wait(
                "window.harnessState.searchCount === 1 && window.harnessState.selectionId === 'event:4999'"
            )
            new_before_hide = session.evaluate(
                "({markers:document.querySelectorAll('.badge--new').length,facts:window.harnessState.apiNewFactCount,section:window.harnessState.sectionId})"
            )
            if new_before_hide != {"markers": 1, "facts": 1, "section": "section:255"}:
                raise AssertionError(f"API NEW marker failed: {new_before_hide}")

            session.evaluate("window.phase04Harness.openPath('event:4999')")
            session.wait(
                "window.harnessState.pathCount === 1 && !document.querySelector('#side-panel').hidden"
            )
            session.evaluate("window.phase04Harness.openDetail('event:4999')")
            session.wait(
                "window.harnessState.detailCount === 1 && document.querySelector('#side-panel h2').textContent === 'Detail / Evidence'"
            )
            session.evaluate("window.phase04Harness.closePanel()")
            session.wait(
                "window.harnessState.backCount === 1 && document.querySelector('#side-panel').hidden"
            )

            session.evaluate("window.phase04Harness.locateSelection('arm:303')")
            session.wait(
                "window.harnessState.branchLocateCount === 1 && window.harnessState.selectionId === 'arm:303'"
            )
            located_branch = session.evaluate(
                "({resource:window.harnessState.currentPage.resource_id,items:window.harnessState.branchItems,selected:window.harnessState.selectionId})"
            )
            if located_branch != {"resource": "choice:0", "items": 64, "selected": "arm:303"}:
                raise AssertionError(f"v2 unloaded branch locate failed: {located_branch}")

            session.evaluate("window.phase04Harness.tamperCursor()")
            session.wait("window.harnessState.invalidCursorCount === 1")
            session.evaluate("window.phase04Harness.openBranch('choice:0')")
            session.wait(
                "window.harnessState.branchItems === 240 && window.harnessState.branchCursor !== null"
            )
            first_branch_page = session.evaluate("window.harnessState.branchItems")
            session.evaluate("window.phase04Harness.nextBranchPage()")
            session.wait(
                "window.harnessState.branchItems === 64 && window.harnessState.branchCursor === null"
            )

            session.evaluate("window.phase04Harness.openBranch('choice:19')")
            session.wait("window.harnessState.crossSectionRejoin !== null")
            cross_rejoin = session.evaluate("window.harnessState.crossSectionRejoin")
            if cross_rejoin != "event:400":
                raise AssertionError(f"cross-section rejoin drifted: {cross_rejoin}")

            session.evaluate("window.phase04Harness.searchFinal()")
            session.wait(
                "window.harnessState.searchCount === 2 && window.harnessState.selectionId === 'event:4999'"
            )
            save_before = session.evaluate("window.harnessState.viewSaveCount")
            session.evaluate(
                "(() => { const value=document.querySelector('#hide-new'); value.checked=true; value.dispatchEvent(new Event('change',{bubbles:true})); })()"
            )
            session.wait(
                f"window.harnessState.hideNew === true && document.querySelectorAll('.badge--new').length === 0 && window.harnessState.viewSaveCount > {save_before}"
            )
            hidden_new = session.evaluate(
                "({markers:document.querySelectorAll('.badge--new').length,facts:window.harnessState.apiNewFactCount,nodes:document.querySelectorAll('.story-node').length})"
            )
            if hidden_new["markers"] != 0 or hidden_new["facts"] != 1:
                raise AssertionError(f"hide NEW changed API facts: {hidden_new}")

            session.evaluate("window.phase04Harness.reopen()")
            session.wait(
                "window.harnessState.reopenCount === 1 && window.harnessState.hideNew === true && window.harnessState.selectionId === 'event:4999'"
            )
            session.evaluate("window.phase04Harness.refresh()")
            session.wait(
                "window.harnessState.refreshCount === 1 && window.harnessState.staleCount === 1 && document.querySelector('#freshness').dataset.freshness === 'stale'"
            )
            session.evaluate("window.phase04Harness.loadSection('section:0')")
            session.wait("window.harnessState.sectionId === 'section:0'")
            wording_only = session.evaluate(
                "({markers:document.querySelectorAll('.badge--new').length,facts:window.harnessState.apiNewFactCount,freshness:document.querySelector('#freshness').dataset.freshness})"
            )
            if wording_only != {"markers": 0, "facts": 0, "freshness": "stale"}:
                raise AssertionError(f"wording-only refresh created NEW: {wording_only}")

            metrics = session.evaluate(
                "({innerWidth,innerHeight,liveStoryNodes:window.phase04Harness.liveStoryNodes(),domNodes:document.querySelectorAll('*').length,scrollWidth:document.documentElement.scrollWidth,clientWidth:document.documentElement.clientWidth,errors:window.harnessState.errors.slice(),selection:window.harnessState.selectionId,hideNew:window.harnessState.hideNew})"
            )
            performance_metrics = session.command("Performance.getMetrics").get("metrics", [])
            heap_bytes = int(
                next(
                    (
                        entry["value"]
                        for entry in performance_metrics
                        if entry["name"] == "JSHeapUsedSize"
                    ),
                    0,
                )
            )
            screenshot = output_dir / f"phase04-scale-{profile_id}.png"
            screenshot.write_bytes(
                base64.b64decode(
                    session.command(
                        "Page.captureScreenshot",
                        {"format": "png", "captureBeyondViewport": False},
                    )["data"]
                )
            )
            session.command("Runtime.evaluate", {"expression": "0"})
            local_hosts = {"127.0.0.1", "localhost", ""}
            remote_requests = []
            browser_errors = []
            browser_error_summaries = []
            expected_fail_closed_logs = []
            for event in session.events:
                if event.get("method") == "Network.requestWillBeSent":
                    url = str(event.get("params", {}).get("request", {}).get("url", ""))
                    if urlsplit(url).hostname not in local_hosts and not url.startswith(
                        ("data:", "about:")
                    ):
                        remote_requests.append(url)
                if event.get("method") == "Runtime.exceptionThrown":
                    browser_errors.append(event)
                    details = event.get("params", {}).get("exceptionDetails", {})
                    browser_error_summaries.append(
                        str(details.get("exception", {}).get("description") or details.get("text"))
                    )
                if (
                    event.get("method") == "Log.entryAdded"
                    and event.get("params", {}).get("entry", {}).get("level") == "error"
                ):
                    entry = event.get("params", {}).get("entry", {})
                    entry_url = str(entry.get("url", ""))
                    entry_path = urlsplit(entry_url).path
                    summary = f"{entry.get('source')}: {entry.get('text')} ({entry_url})"
                    if entry_path in {
                        "/api/v1/story-map-v2/branch-page",
                        "/api/v1/story-map-v2/section-page",
                    }:
                        expected_fail_closed_logs.append(summary)
                    else:
                        browser_errors.append(event)
                        browser_error_summaries.append(summary)
            bounds = _load_object(PROFILE_PATH)["bounds"]
            if metrics["liveStoryNodes"] > int(bounds["live_story_nodes"]):
                raise AssertionError(f"live story nodes exceeded bound: {metrics}")
            if metrics["domNodes"] > int(bounds["dom_nodes"]):
                raise AssertionError(f"DOM nodes exceeded bound: {metrics}")
            if heap_bytes > int(bounds["heap_bytes"]):
                raise AssertionError(f"JS heap exceeded bound: {heap_bytes}")
            if metrics["scrollWidth"] > metrics["clientWidth"]:
                raise AssertionError(f"horizontal overflow at {profile_id}: {metrics}")
            if metrics["errors"] or browser_errors or remote_requests:
                raise AssertionError(
                    f"browser diagnostics failed: state={metrics['errors']}, "
                    f"errors={browser_error_summaries}, remote={remote_requests}"
                )
            if len(expected_fail_closed_logs) != 2:
                raise AssertionError(
                    f"expected one invalid-cursor and one stale-revision log: "
                    f"{expected_fail_closed_logs}"
                )
            return {
                "profile": profile_id,
                "startup_navigation_retries": startup_navigation_retries,
                "viewport": {"width": width, "height": height, "device_scale_factor": scale},
                "live_story_nodes": metrics["liveStoryNodes"],
                "dom_nodes": metrics["domNodes"],
                "js_heap_used_bytes": heap_bytes,
                "horizontal_overflow": False,
                "remote_requests": 0,
                "browser_errors": 0,
                "expected_fail_closed_http_responses": 2,
                "current_presented": True,
                "stale_presented": True,
                "wording_only_new_markers": 0,
                "api_new_before_hide": new_before_hide,
                "api_new_hidden": hidden_new,
                "oversized_branch_pages": [first_branch_page, 64],
                "invalid_cursor_rejected": True,
                "unloaded_branch_locate": located_branch,
                "cross_section_rejoin": cross_rejoin,
                "search_final_section": True,
                "path_detail_back": True,
                "reopen_restored": True,
                "refresh_stale_409": True,
                "screenshot": screenshot.name,
                "screenshot_sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
            }
        finally:
            if session is not None:
                session.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _structural_evidence(dataset: ScaleDataset) -> dict[str, Any]:
    profile = dataset.profile
    counts = profile["counts"]
    if counts != {
        "events": 5000,
        "choices": 5000,
        "arms": 20300,
        "rejoins": 2000,
        "sections": 256,
    }:
        raise AssertionError(f"scale counts drifted: {counts}")
    computed_counts = {
        "events": sum(dataset.section_sizes),
        "choices": dataset.event_count,
        "arms": 304 + (dataset.choice_count - 1) * 4,
        "rejoins": sum(
            dataset._rejoin_for_choice(index) is not None for index in range(dataset.choice_count)
        ),
        "sections": len(dataset.section_sizes),
    }
    if computed_counts != counts:
        raise AssertionError(f"scale generator does not produce declared counts: {computed_counts}")
    manifest = dataset.manifest()
    route_sections = [
        section for section in manifest["sections"] if section["route_id"] == "route:persistent-50"
    ]
    branch = dataset.branch_page({"map_revision": 7, "branch_id": "choice:0", "limit": 240})
    if len(route_sections) != 50 or max(item["depth"] for item in branch["items"]) != 8:
        raise AssertionError("persistent-route or depth-eight evidence drifted")
    nested_shells = branch["shells"][:8]
    for index, shell in enumerate(nested_shells):
        expected_parent = "shell:choice:0" if index == 0 else f"shell:arm:{index - 1}"
        if shell["parent_shell_id"] != expected_parent:
            raise AssertionError("depth-eight shell ancestry drifted")
    second = dataset.branch_page(
        {
            "map_revision": 7,
            "branch_id": "choice:0",
            "limit": 240,
            "cursor": branch["next_cursor"],
        }
    )
    located = dataset.locate({"map_revision": 7, "selection_id": "arm:303"})
    if located["location"]["branch_id"] != "choice:0" or located["location"]["page_cursor"] is None:
        raise AssertionError("v2 unloaded-branch locate identity drifted")
    return {
        "counts": computed_counts,
        "persistent_route_sections": len(route_sections),
        "maximum_nesting_depth": 8,
        "oversized_branch_items": len(branch["items"]) + len(second["items"]),
        "oversized_branch_pages": [len(branch["items"]), len(second["items"])],
        "cross_section_rejoin": dataset._rejoin_for_choice(19),
        "final_section_target": "event:4999",
        "v2_unloaded_branch_id": located["location"]["branch_id"],
        "v2_unloaded_branch_cursor": True,
    }


def run(output_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    dataset = ScaleDataset()
    structural = _structural_evidence(dataset)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(dataset))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    driver = _cdp_module()
    browser = driver._browser()
    origin = f"http://127.0.0.1:{server.server_address[1]}/"
    captures: list[dict[str, Any]] = []
    started = time.perf_counter()
    try:
        for profile in dataset.profile["profiles"]:
            dataset.reset()
            captures.append(_capture_profile(driver, browser, origin, output_dir, profile))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    report = {
        "schema": "story-map-v2-phase04-scale-acceptance-v1",
        "reader_schema": SCHEMA,
        "status": "passed",
        "provider_calls": 0,
        "remote_requests": 0,
        "game_or_creator_code_executed": False,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "structural": structural,
        "profiles": captures,
        "bounds": dataset.profile["bounds"],
    }
    (output_dir / "acceptance.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8", newline="\n"
    )
    (output_dir / "ACCEPTANCE_REPORT.md").write_text(
        _markdown(report), encoding="utf-8", newline="\n"
    )
    return report


def _markdown(report: Mapping[str, Any]) -> str:
    structural = report["structural"]
    lines = [
        "# M15.1 Phase 04 public scale acceptance",
        "",
        "Status: **passed**",
        "",
        f"Reader schema: `{report['reader_schema']}`",
        "",
        f"Counts: {structural['counts']['events']} events, {structural['counts']['choices']} choices, "
        f"{structural['counts']['arms']} arms, {structural['counts']['rejoins']} rejoins, "
        f"{structural['counts']['sections']} sections.",
        "",
        "| Profile | Live story nodes | DOM nodes | JS heap bytes | Remote | Stale/current |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for capture in report["profiles"]:
        lines.append(
            f"| {capture['profile']} | {capture['live_story_nodes']} | {capture['dom_nodes']} | "
            f"{capture['js_heap_used_bytes']} | {capture['remote_requests']} | pass |"
        )
    lines.extend(
        [
            "",
            "Search/locate, v2 unloaded-branch routing, oversized cursor paging/tamper rejection, "
            "cross-section rejoin, 50-section path, Detail/Back, refresh/stale 409, reopen/view state, "
            "API-authored NEW/hide behavior, wording-only invariance, and zero remote assets passed "
            "in all profiles.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
