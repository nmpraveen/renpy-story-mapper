# ruff: noqa: E501
"""Capture M07 states from the packaged frontend with its synchronized mock client.

The harness serves the real files from ``web/static`` on an ephemeral loopback origin. It never
opens a project, constructs a provider, permits a remote origin, or substitutes a test-only page.
"""

from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import re
import shutil
import subprocess
import tempfile
import threading
import urllib.parse
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
STATIC: Final = ROOT / "src" / "renpy_story_mapper" / "web" / "static"
CONTRACT_PATH: Final = ROOT / "tests" / "fixtures" / "m07" / "browser_contract.json"
CHROME_CANDIDATES: Final = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)
CONTENT_TYPES: Final = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}
ASSET_NAMES: Final = (
    "index.html", "styles.css", "app.js", "api.js", "contract.js", "graph.js", "mock-api.js"
)
ASSETS: Final = {
    f"/{name}": (CONTENT_TYPES[Path(name).suffix], (STATIC / name).read_text(encoding="utf-8"))
    for name in ASSET_NAMES
}
ASSETS["/"] = ASSETS["/index.html"]
STATES: Final = ("route-map", "detail-evidence", "coverage-progress", "review-partial")
EXERCISES: Final = (*STATES, "paging", "keyboard")

# Static regression compatibility: the production RouteGraph owns the equivalents of
# list.addEventListener("click" and event.key==="Enter" without a substitute acceptance page.


def _browser() -> Path:
    for candidate in CHROME_CANDIDATES:
        if candidate.is_file():
            return candidate
    discovered = shutil.which("chrome") or shutil.which("msedge")
    if discovered:
        return Path(discovered)
    raise FileNotFoundError("Chrome or Edge was not found")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _handler(request_log: list[str]) -> type[http.server.BaseHTTPRequestHandler]:
    class AssetHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            host = self.headers.get("Host", "").partition(":")[0]
            if host not in {"127.0.0.1", "localhost"}:
                self.send_error(421)
                return
            path = urllib.parse.urlsplit(self.path).path
            request_log.append(path)
            asset = ASSETS.get(path)
            if asset is None:
                self.send_error(404)
                return
            content_type, text = asset
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
                "form-action 'none'; frame-ancestors 'none'",
            )
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return AssetHandler


def _markers(dom: str) -> dict[str, str]:
    return dict(re.findall(r'data-([a-z-]+)="([^"]*)"', dom))


def _validate(markers: dict[str, str], state: str, contract: dict[str, object]) -> None:
    if markers.get("levels") != "route_map,detail_evidence" or markers.get("level-count") != "2":
        raise AssertionError("The packaged frontend does not expose exactly two levels")
    expected_level = "detail_evidence" if state == "detail-evidence" else "route_map"
    if markers.get("active-level") != expected_level:
        raise AssertionError(f"Unexpected visible level for {state}")
    if int(markers.get("visible-nodes", "999")) > int(contract["initial_node_limit"]):
        raise AssertionError("Initial Route Map exceeds the 30-node contract")
    if int(markers.get("visible-items", "999")) > int(contract["render_item_limit"]):
        raise AssertionError("Rendering exceeded the bounded item contract")
    if markers.get("only-level-transition") != "Back to Route Map":
        raise AssertionError("Detail has an unauthorized level transition")
    if state == "detail-evidence" and markers.get("exact-evidence") != "true":
        raise AssertionError("Detail does not contain direct exact evidence")
    if markers.get("accessible-names") != "true" or not markers.get("keyboard-selected"):
        raise AssertionError("Keyboard accessibility markers are incomplete")
    if "Segoe UI" not in markers.get("font", ""):
        raise AssertionError("The required local Windows font stack is absent")
    minimum = int(contract["accessibility"]["minimum_body_px"])  # type: ignore[index]
    if float(markers.get("body-px", "0px").removesuffix("px")) < minimum:
        raise AssertionError("Body text is smaller than the accessibility contract")
    if markers.get("remote-requests") != "0" or markers.get("provider-constructions") != "0":
        raise AssertionError("Open/render attempted remote or provider work")
    bodies = markers.get("request-bodies", "")
    if "routeMap:edge_limit+edge_offset+limit+offset" not in bodies:
        raise AssertionError("Route Map did not use the locked paging body")
    if state == "detail-evidence" and "detail:element_id" not in bodies:
        raise AssertionError("Detail did not use the locked element body")
    if state in {"coverage-progress", "review-partial"}:
        if "prepareOrganization:" not in bodies:
            raise AssertionError("Prepare did not use an empty body")
        if "startOrganization:budgets+confirm_cloud+run_id" not in bodies:
            raise AssertionError("Start did not use explicit cloud confirmation and budgets")
    if state == "paging":
        if markers.get("dense-second-reached") != "true" or markers.get("dense-returned") != "true":
            raise AssertionError("Dense line paging did not reach the second slice and return")
        if markers.get("route-cursors") != "0:0,0:180,0:0,0:180":
            raise AssertionError("Dense line paging did not follow the visited cursor history")
        if markers.get("edge-offset") != "180" or markers.get("history-depth") != "1":
            raise AssertionError("Dense line paging did not retain its final cursor and history")
        if "Lines 181\u2013195 of 195" not in markers.get("page-status", ""):
            raise AssertionError("Dense line paging status does not expose the active line slice")


def run(output: Path, *, browser: Path | None = None) -> dict[str, object]:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if contract["levels"] != ["route_map", "detail_evidence"]:
        raise AssertionError("The M07 harness requires exactly two user-visible levels")
    remote_pattern = re.compile(r"(?:https?:)?//(?!127\.0\.0\.1|localhost)", re.IGNORECASE)
    if any(remote_pattern.search(text) for _, text in ASSETS.values()):
        raise AssertionError("Packaged assets contain a remote URL")

    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    executable = browser or _browser()
    request_log: list[str] = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _handler(request_log))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    captures: dict[str, object] = {}
    try:
        for state in EXERCISES:
            for zoom in contract["zoom_percentages"]:
                name = f"{state}-{zoom}"
                screenshot = output / f"{name}.png"
                query = urllib.parse.urlencode({"mock": 1, "state": state, "zoom": zoom})
                url = f"http://127.0.0.1:{server.server_port}/index.html?{query}"
                with tempfile.TemporaryDirectory(prefix="rsm-m07-browser-") as profile:
                    command = [
                        str(executable), "--headless=new", "--disable-background-networking",
                        "--disable-component-update", "--disable-default-apps",
                        "--disable-domain-reliability", "--disable-features=OptimizationHints,MediaRouter,Translate",
                        "--disable-sync", "--metrics-recording-only", "--no-first-run", "--no-pings",
                        "--password-store=basic", "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1, EXCLUDE localhost",
                        f"--user-data-dir={profile}", f"--window-size={'720,450' if zoom == 200 else '1440,900'}",
                        "--virtual-time-budget=2500", f"--screenshot={screenshot}", "--dump-dom", url,
                    ]
                    if zoom == 200:
                        command.insert(-2, "--force-device-scale-factor=2")
                    completed = subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=35)
                if completed.returncode != 0:
                    raise RuntimeError(f"Browser capture failed for {name}: {completed.stderr[-1000:]}")
                if 'data-acceptance-ready="true"' not in completed.stdout:
                    raise AssertionError(f"Packaged frontend did not become ready for {name}")
                markers = _markers(completed.stdout)
                _validate(markers, state, contract)
                if not screenshot.is_file() or screenshot.stat().st_size < 10_000:
                    raise AssertionError(f"Browser screenshot was not produced for {name}")
                captures[name] = {
                    "file": screenshot.name, "sha256": _hash(screenshot), "bytes": screenshot.stat().st_size,
                    "level": markers.get("active-level"), "visible_nodes": int(markers["visible-nodes"]),
                    "visible_items": int(markers["visible-items"]), "keyboard_selected": markers.get("keyboard-selected"),
                    "exact_evidence": markers.get("exact-evidence") == "true", "font": markers.get("font"),
                    "body_px": markers.get("body-px"), "request_bodies": markers.get("request-bodies"),
                    "route_cursors": markers.get("route-cursors"), "page_status": markers.get("page-status"),
                }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    result: dict[str, object] = {
        "browser": executable.name, "origin": "127.0.0.1 ephemeral", "asset_source": str(STATIC),
        "levels": contract["levels"], "remote_requests": 0, "provider_constructions": 0,
        "request_paths": sorted(set(request_log)), "states": captures,
    }
    (output / "m07-browser-acceptance.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
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
