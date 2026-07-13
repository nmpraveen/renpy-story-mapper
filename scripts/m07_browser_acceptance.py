# ruff: noqa: E501
"""Exercise packaged M07 UI through LocalWebServer and a real temporary SQLite project."""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import secrets
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

from renpy_story_mapper.project import create_ingested_project
from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.security import SessionSecurity
from renpy_story_mapper.web.server import LocalWebServer, start_in_thread
from renpy_story_mapper.web.state import UserStateStore

ROOT: Final = Path(__file__).resolve().parents[1]
STATIC: Final = ROOT / "src" / "renpy_story_mapper" / "web" / "static"
ZOOMS: Final = (100, 200)
CHROME_CANDIDATES: Final = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)


@dataclass
class _NoDialogs:
    def choose_source(self, _kind: str) -> Path | None:
        return None

    def choose_open_project(self) -> Path | None:
        return None

    def choose_save_project(self) -> Path | None:
        return None


def _browser() -> Path:
    for candidate in CHROME_CANDIDATES:
        if candidate.is_file():
            return candidate
    discovered = shutil.which("chrome") or shutil.which("msedge")
    if discovered:
        return Path(discovered)
    raise FileNotFoundError("Chrome or Edge was not found")


class _Cdp:
    """Small dependency-free Chrome DevTools client used only by this acceptance harness."""

    def __init__(self, websocket_url: str) -> None:
        parsed = urlsplit(websocket_url)
        self.socket = socket.create_connection(
            (parsed.hostname or "127.0.0.1", parsed.port or 80), timeout=10
        )
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        request = (
            f"GET {target} HTTP/1.1\r\nHost: {parsed.netloc}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\nOrigin: http://127.0.0.1\r\n\r\n"
        )
        self.socket.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            response += self.socket.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(
                f"Chrome DevTools websocket refused the connection: {response[:200]!r}"
            )
        self.identifier = 0
        self.events: list[dict[str, Any]] = []

    def close(self) -> None:
        self.socket.close()

    def _send_frame(self, payload: bytes, opcode: int = 1) -> None:
        mask = secrets.token_bytes(4)
        length = len(payload)
        header = bytearray([0x80 | opcode])
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask)
        encoded = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self.socket.sendall(bytes(header) + encoded)

    def _exact(self, length: int) -> bytes:
        data = b""
        while len(data) < length:
            chunk = self.socket.recv(length - len(data))
            if not chunk:
                raise ConnectionError("Chrome DevTools websocket closed")
            data += chunk
        return data

    def _receive(self) -> dict[str, Any]:
        fragments = bytearray()
        while True:
            first, second = self._exact(2)
            final, opcode, length = bool(first & 0x80), first & 0x0F, second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._exact(8))[0]
            masked = bool(second & 0x80)
            mask = self._exact(4) if masked else b""
            payload = self._exact(length)
            if masked:
                payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
            if opcode == 8:
                raise ConnectionError("Chrome closed its DevTools websocket")
            if opcode == 9:
                self._send_frame(payload, opcode=10)
                continue
            fragments.extend(payload)
            if final:
                return json.loads(fragments.decode("utf-8"))

    def command(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.identifier += 1
        identifier = self.identifier
        self._send_frame(
            json.dumps({"id": identifier, "method": method, "params": params or {}}).encode()
        )
        while True:
            message = self._receive()
            if message.get("id") == identifier:
                if "error" in message:
                    raise RuntimeError(f"CDP {method} failed: {message['error']}")
                return dict(message.get("result", {}))
            self.events.append(message)

    def evaluate(self, expression: str) -> Any:
        result = self.command(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        return result.get("result", {}).get("value")

    def wait(self, expression: str, timeout: float = 15) -> Any:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.evaluate(expression)
            if value:
                return value
            time.sleep(0.1)
        raise TimeoutError(f"Browser condition did not become true: {expression}")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _project(root: Path) -> Path:
    source = root / "game" / "routes.rpy"
    source.parent.mkdir()
    choices = "\n".join(
        f'        "Route {index:02d}":\n            jump ending_{index:02d}' for index in range(16)
    )
    endings = "\n\n".join(
        f'label ending_{index:02d}:\n    "Ending {index:02d}."\n    return' for index in range(16)
    )
    source.write_text(f"label start:\n    menu:\n{choices}\n\n{endings}\n", encoding="utf-8")
    destination = root / "live-acceptance.rsmproj"
    create_ingested_project(destination, source.parent).close()
    return destination


def _devtools_page(port: int) -> dict[str, Any]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connection.request("GET", "/json")
    response = connection.getresponse()
    pages = json.loads(response.read())
    connection.close()
    return next(page for page in pages if page.get("type") == "page")


def _capture(browser: Path, output: Path, zoom: int, origin: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix="rsm-m07-chrome-", ignore_cleanup_errors=True
    ) as profile:
        profile_path = Path(profile)
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
            f"--user-data-dir={profile}",
            "about:blank",
        ]
        if zoom == 200:
            command.insert(-1, "--force-device-scale-factor=2")
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        active = profile_path / "DevToolsActivePort"
        deadline = time.monotonic() + 15
        while not active.is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not active.is_file():
            process.terminate()
            raise RuntimeError("Chrome did not publish its DevTools port")
        port = int(active.read_text(encoding="utf-8").splitlines()[0])
        session: _Cdp | None = None
        try:
            session = _Cdp(str(_devtools_page(port)["webSocketDebuggerUrl"]))
            session.command("Page.enable")
            session.command("Runtime.enable")
            session.command("Network.enable")
            session.command("Log.enable")
            session.command(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": 720 if zoom == 200 else 1440,
                    "height": 450 if zoom == 200 else 900,
                    "deviceScaleFactor": 2 if zoom == 200 else 1,
                    "mobile": False,
                },
            )
            session.command("Page.navigate", {"url": origin})
            session.wait(
                "document.readyState === 'complete' && !!document.querySelector('.recent-card')"
            )
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait(
                "document.querySelectorAll('.station').length > 0 && !document.querySelector('#routeMapView').hidden"
            )
            route_shot = output / f"route-map-{zoom}.png"
            route_shot.write_bytes(
                base64.b64decode(
                    session.command(
                        "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                    )["data"]
                )
            )
            route_state = session.evaluate(
                """(() => { const items=[...document.querySelectorAll('[data-element-id]')]; const active=document.querySelector('[aria-selected="true"]'); const viewport=document.querySelector('#mapViewport'); viewport.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true})); return {lanes:[...new Set([...document.querySelectorAll('.station')].map(x=>x.dataset.laneId))],portals:document.querySelectorAll('.continuation-portal').length,items:items.length,before:active?.dataset.elementId,after:document.querySelector('[aria-selected="true"]')?.dataset.elementId}; })()"""
            )
            session.evaluate("document.querySelector('#organizeButton').click()")
            session.wait("document.querySelector('#consentDialog').open")
            session.evaluate("document.querySelector('#consentDialog').close()")
            first_status = session.evaluate("document.querySelector('#pageStatus').textContent")
            if not session.evaluate("!document.querySelector('#nextPage').disabled"):
                raise AssertionError("Live fixture did not produce a second bounded route page")
            session.evaluate("document.querySelector('#nextPage').click()")
            session.wait(
                f"document.querySelector('#pageStatus').textContent !== {json.dumps(first_status)}"
            )
            continuation_count = session.evaluate(
                "document.querySelectorAll('.continuation-portal').length"
            )
            if not continuation_count:
                diagnostics = session.evaluate(
                    "({status:document.querySelector('#pageStatus').textContent,items:[...document.querySelectorAll('[data-element-id]')].map(x=>x.className)})"
                )
                raise AssertionError(
                    f"Cross-page edges were not rendered as continuation portals: {diagnostics}"
                )
            continuation_shot = output / f"continuations-{zoom}.png"
            continuation_shot.write_bytes(
                base64.b64decode(
                    session.command(
                        "Page.captureScreenshot",
                        {"format": "png", "captureBeyondViewport": False},
                    )["data"]
                )
            )
            session.evaluate(
                "(document.querySelector('.continuation-portal') || document.querySelector('.edge-stop') || document.querySelector('.station')).click()"
            )
            session.wait(
                "!document.querySelector('#detailView').hidden && document.querySelectorAll('[data-evidence-id]').length > 0"
            )
            detail_shot = output / f"detail-evidence-{zoom}.png"
            detail_shot.write_bytes(
                base64.b64decode(
                    session.command(
                        "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
                    )["data"]
                )
            )
            detail_state = session.evaluate(
                "({evidence:document.querySelectorAll('[data-evidence-id]').length,bodyPx:getComputedStyle(document.body).fontSize,width:document.documentElement.scrollWidth,client:document.documentElement.clientWidth})"
            )
            requests = [
                event["params"]["request"]["url"]
                for event in session.events
                if event.get("method") == "Network.requestWillBeSent"
            ]
            prepare_requests = [
                event["params"]["request"]
                for event in session.events
                if event.get("method") == "Network.requestWillBeSent"
                and event["params"]["request"]["url"].endswith("/api/v1/m07/organization/prepare")
            ]
            if len(prepare_requests) != 1:
                raise AssertionError("Live acceptance did not issue exactly one prepare request")
            prepare_body = json.loads(prepare_requests[0].get("postData", "{}"))
            expected_budgets = {
                "soft_seconds": 600,
                "hard_seconds": 900,
                "soft_tokens": 1_500_000,
                "hard_tokens": 2_000_000,
                "hard_calls": 48,
            }
            if {key: prepare_body.get(key) for key in expected_budgets} != expected_budgets:
                raise AssertionError(f"Prepare budget mismatch: {prepare_body}")
            remote = [
                url for url in requests if urlsplit(url).hostname not in {"127.0.0.1", "localhost"}
            ]
            errors = []
            for event in session.events:
                if event.get("method") == "Runtime.exceptionThrown":
                    errors.append(event)
                elif event.get("method") == "Log.entryAdded":
                    entry = event.get("params", {}).get("entry", {})
                    text = str(entry.get("text", ""))
                    url = str(entry.get("url", ""))
                    if "frame-ancestors" not in text and not url.endswith("/favicon.ico"):
                        errors.append(event)
            if remote:
                raise AssertionError(f"Remote browser requests observed: {remote}")
            if errors:
                raise AssertionError(f"Browser errors observed: {errors}")
            if route_state["before"] == route_state["after"]:
                raise AssertionError("Keyboard navigation did not move selection")
            if route_state["items"] > 240:
                raise AssertionError("Initial rendering exceeded 240 items")
            if float(str(detail_state["bodyPx"]).removesuffix("px")) < 16:
                raise AssertionError("Body text is smaller than 16px")
            return {
                "zoom_percent": zoom,
                "route_screenshot": route_shot.name,
                "route_sha256": _hash(route_shot),
                "detail_screenshot": detail_shot.name,
                "detail_sha256": _hash(detail_shot),
                "lane_ids": sorted(route_state["lanes"]),
                "continuation_portals": continuation_count,
                "continuation_screenshot": continuation_shot.name,
                "continuation_sha256": _hash(continuation_shot),
                "rendered_items": route_state["items"],
                "exact_evidence_records": detail_state["evidence"],
                "body_px": detail_state["bodyPx"],
                "document_width": detail_state["width"],
                "client_width": detail_state["client"],
                "request_count": len(requests),
                "prepare_budgets": expected_budgets,
                "remote_requests": 0,
            }
        finally:
            if session is not None:
                session.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def run(output: Path, *, browser: Path | None = None) -> dict[str, Any]:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    provider_constructions = 0
    with tempfile.TemporaryDirectory(prefix="rsm-m07-live-") as temporary:
        root = Path(temporary)
        project = _project(root)
        state = UserStateStore(root / "web-state.json")
        state.record_project(project)

        def forbidden_provider(_scope: object) -> object:
            nonlocal provider_constructions
            provider_constructions += 1
            raise AssertionError("The acceptance path must not construct a provider")

        api = ProjectApi(_NoDialogs(), state_store=state, m07_provider_factory=forbidden_provider)
        server = LocalWebServer(
            "127.0.0.1",
            0,
            api,
            static_root=STATIC,
            security=SessionSecurity("acceptance-session", "acceptance-csrf"),
        )
        thread = start_in_thread(server)
        try:
            origin = f"http://127.0.0.1:{server.port}/"
            captures = {
                str(zoom): _capture(browser or _browser(), output, zoom, origin) for zoom in ZOOMS
            }
        finally:
            server.close_service()
            thread.join(timeout=5)
    if provider_constructions:
        raise AssertionError("Provider construction occurred during live acceptance")
    result = {
        "origin": "127.0.0.1 ephemeral",
        "server": "LocalWebServer",
        "api": "ProjectApi",
        "project": "temporary SQLite .rsmproj",
        "provider_constructions": provider_constructions,
        "remote_requests": 0,
        "captures": captures,
    }
    (output / "m07-live-browser-acceptance.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--browser", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.output, browser=arguments.browser), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
