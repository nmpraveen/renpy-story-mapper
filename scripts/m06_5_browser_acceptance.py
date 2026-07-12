"""Capture deterministic frontend states in local headless Chrome.

This harness serves only packaged static assets from loopback and uses the typed mock contract.
It never opens a game, project, provider, or external origin.
"""

from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import re
import shutil
import socket
import socketserver
import subprocess
import tempfile
import threading
import urllib.parse
from pathlib import Path
from typing import Final

STATIC_ROOT: Final = (
    Path(__file__).resolve().parents[1] / "src" / "renpy_story_mapper" / "web" / "static"
)
CHROME_CANDIDATES: Final = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)
STATES: Final = (
    ("welcome", 100),
    ("events", 100),
    ("evidence", 100),
    ("review", 100),
    ("progress", 100),
    ("events", 200),
)


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(
        self,
        request: socket.socket,
        client_address: tuple[str, int],
        server: socketserver.BaseServer,
    ) -> None:
        super().__init__(request, client_address, server, directory=str(STATIC_ROOT))

    def end_headers(self) -> None:
        policy = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
            "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        )
        self.send_header("Content-Security-Policy", policy)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        super().end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return


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


def run(output: Path, *, browser: Path | None = None) -> dict[str, object]:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    executable = browser or _browser()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    captures: dict[str, object] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="rsm-browser-acceptance-") as profile:
            for state, zoom in STATES:
                name = f"{state}-{zoom}"
                screenshot = output / f"{name}.png"
                query = urllib.parse.urlencode({"mock": "1", "state": state, "zoom": zoom})
                url = f"http://127.0.0.1:{server.server_port}/index.html?{query}"
                command = [
                    str(executable),
                    "--headless=new",
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
                    f"--user-data-dir={profile}",
                    f"--window-size={'720,450' if zoom == 200 else '1440,900'}",
                    "--virtual-time-budget=2500",
                    f"--screenshot={screenshot}",
                    "--dump-dom",
                    url,
                ]
                if zoom == 200:
                    command.insert(-2, "--force-device-scale-factor=2")
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
                if completed.returncode != 0:
                    raise RuntimeError(
                        f"Browser capture failed for {name}: {completed.stderr[-1000:]}"
                    )
                if 'data-acceptance-ready="true"' not in completed.stdout:
                    raise AssertionError(f"Frontend did not become ready for {name}")
                markers = dict(re.findall(r'data-([a-z-]+)="([^"]*)"', completed.stdout))
                if int(markers.get("visible-items", "0")) > 240:
                    raise AssertionError(f"Frontend exceeded the item boundary for {name}")
                if state != "welcome" and not markers.get("keyboard-selected"):
                    raise AssertionError(
                        f"Frontend selection was not keyboard-addressable for {name}"
                    )
                if state == "evidence" and not markers.get("exact-evidence"):
                    raise AssertionError("Exact evidence traversal did not complete")
                if markers.get("organization-starts", "0") != "0":
                    raise AssertionError(f"Implicit organization request observed for {name}")
                if not screenshot.is_file() or screenshot.stat().st_size < 10_000:
                    raise AssertionError(f"Browser screenshot was not produced for {name}")
                captures[name] = {
                    "file": screenshot.name,
                    "sha256": _hash(screenshot),
                    "bytes": screenshot.stat().st_size,
                    "exit_code": completed.returncode,
                    "visible_items": int(markers.get("visible-items", "0")),
                    "keyboard_selected": markers.get("keyboard-selected", ""),
                    "exact_evidence": markers.get("exact-evidence", ""),
                    "organization_starts": int(markers.get("organization-starts", "0")),
                }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    result: dict[str, object] = {
        "browser": executable.name,
        "origin": "127.0.0.1 ephemeral",
        "remote_requests": 0,
        "production_node_runtime": False,
        "states": captures,
    }
    report = output / "browser-acceptance.json"
    report.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
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
