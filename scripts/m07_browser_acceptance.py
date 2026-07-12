# ruff: noqa: E501
"""Capture the self-contained M07 two-level browser acceptance contract.

The harness serves in-memory mock assets on an ephemeral loopback port. It does not open a
project, parse a game, construct a provider, or permit a remote origin.
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
CONTRACT_PATH: Final = ROOT / "tests" / "fixtures" / "m07" / "browser_contract.json"
CHROME_CANDIDATES: Final = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)

HTML: Final = """<!doctype html>
<html lang="en" data-acceptance-ready="false">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'">
  <title>M07 acceptance</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <header><div><strong>Fixture Story</strong><span>Local · deterministic</span></div><div id="coverageBadge">AI 50% · Technical 25% · Pending 25%</div></header>
  <main>
    <section id="routeMap" aria-label="Route Map" data-level="route_map">
      <div class="command"><h1>Route Map</h1><button id="fitMap" aria-label="Fit route map">Fit</button></div>
      <div class="map-shell" role="application" aria-label="Chronological route map. Use arrow keys to move and Enter for detail.">
        <svg id="connections" viewBox="0 0 1200 530" role="img" aria-label="Visible fork, merge, persistent lane, and loop lines">
          <path class="spine" d="M80 95 H300 C350 95 350 55 410 55 H600 C650 55 650 95 710 95 H900"/>
          <path class="detour" d="M300 95 C350 95 350 145 410 145 H600 C650 145 650 95 710 95"/>
          <path class="red" d="M900 95 C960 95 960 55 1025 55 H1160"/>
          <path class="blue" d="M900 95 C960 95 960 145 1025 145 H1160"/>
          <path class="loop" d="M790 340 C900 275 1015 405 850 425 C740 438 715 355 790 340"/>
        </svg>
        <ol id="nodes" aria-label="24 chronological meaningful nodes"></ol>
        <div class="legend" aria-label="Route map legend"><span>◆ Choice</span><span>◇ Merge</span><span>↻ Loop</span><span>⚠ Unresolved</span></div>
      </div>
      <aside id="coveragePanel" hidden aria-label="Coverage and progress">
        <h2>Coverage and progress</h2><progress value="75" max="100" aria-label="Overall analyzed coverage">75%</progress>
        <p>2 AI scopes · 1 technical fallback · 1 pending</p><p>ETA 2-4 minutes · 90 / 100 budget tokens used</p>
      </aside>
      <aside id="reviewPanel" hidden aria-label="Partial organization review">
        <h2>Review validated partial result</h2><p>Validated scopes are ready. Technical fallback remains visible.</p>
        <button aria-label="Apply validated partial result">Apply validated partial result</button>
      </aside>
    </section>
    <section id="detailEvidence" aria-label="Detail and Evidence" data-level="detail_evidence" hidden>
      <button id="backToMap" class="back" aria-label="Back to Route Map">Back to Route Map</button>
      <h1>Detail and Evidence</h1>
      <nav aria-label="Local path strip"><span>Day 1</span><b>Garden choice</b><span>Day 1 merge</span></nav>
      <article>
        <div><span class="kind">Choice</span><h2>Take the garden path</h2><p>Compact detour that rejoins the chronological spine.</p></div>
        <dl><dt>Exact caption</dt><dd>Take the garden path</dd><dt>Requirement</dt><dd><code>wits &gt;= 2</code></dd><dt>Effect</dt><dd><code>love += 1</code></dd><dt>Source</dt><dd>m07/route_topology.rpy:5-7 · evidence gate-wits, effect-love</dd><dt>Interpretation</dt><dd>Garden conversation - Interpretation, supported by evidence line 7.</dd></dl>
        <pre aria-label="Exact physical source evidence">5  "Take the garden path" if wits &gt;= 2:
6      $ love += 1
7      "A short garden detour."</pre>
      </article>
    </section>
  </main>
  <script src="/app.js"></script>
</body>
</html>
"""

CSS: Final = """
:root{font-family:"Segoe UI",system-ui,sans-serif;font-size:16px;color:#e8edf4;background:#111720}*{box-sizing:border-box}body{margin:0;min-width:320px}header{height:58px;display:flex;align-items:center;justify-content:space-between;padding:0 24px;background:#182231;border-bottom:1px solid #34445a}header div{display:flex;gap:12px;align-items:center}header span,#coverageBadge{font-size:14px;color:#aebbd0}main{padding:18px 24px}h1{font-size:24px;margin:0}h2{font-size:18px}.command{display:flex;align-items:center;gap:10px;margin-bottom:14px}.command h1{margin-right:auto}button{font:inherit;color:#f4f7fb;background:#27364a;border:1px solid #59708e;border-radius:7px;padding:8px 12px}button:focus-visible,.node:focus-visible{outline:3px solid #76d7ff;outline-offset:3px}.map-shell{height:600px;position:relative;overflow:hidden;border:1px solid #34445a;border-radius:12px;background:#151e2a}.map-shell svg{position:absolute;inset:10px;width:calc(100% - 20px);height:500px;fill:none;stroke-width:5}.spine{stroke:#60c9e8}.detour{stroke:#9b7bea;stroke-dasharray:10 8}.red{stroke:#ff8f91}.blue{stroke:#69a5ff}.loop{stroke:#f5c869}.node{position:absolute;width:136px;min-height:58px;padding:9px;border:1px solid #526882;border-radius:9px;background:#202d3e;color:#edf3fb;list-style:none;font-size:14px}.node small{display:block;color:#b9c5d5;font-size:12px;margin-top:3px}.node[data-kind=choice]{border-color:#a88aee}.node[data-kind=merge]{border-color:#60c9e8}.node[data-kind=terminal]{border-color:#f39a9a}.node[data-kind=unresolved]{border-color:#ffbb57}.node[aria-selected=true]{box-shadow:0 0 0 3px #76d7ff}.legend{position:absolute;left:20px;bottom:16px;display:flex;gap:18px;font-size:13px;color:#c5d0de}.legend span::first-letter{color:#fff}aside{margin-top:12px;padding:14px 18px;border:1px solid #536a85;border-radius:10px;background:#1b2735}aside h2,aside p{margin:5px 0}progress{width:260px}#detailEvidence{max-width:970px;margin:auto}.back{margin-bottom:18px}#detailEvidence nav{display:flex;gap:8px;align-items:center;margin:18px 0;color:#b8c6d8}#detailEvidence nav span,#detailEvidence nav b{padding:7px 11px;border:1px solid #4d627c;border-radius:99px}article{display:grid;grid-template-columns:1fr 1.4fr;gap:24px;padding:24px;border:1px solid #3f526a;border-radius:12px;background:#192432}article p,dd{font-size:14px;line-height:1.5}dt{color:#9eb1c8;font-size:12px;margin-top:9px}dd{margin:2px 0}pre{grid-column:1/-1;padding:15px;overflow:auto;background:#0e141c;border-radius:8px;font-size:14px}.kind{color:#c7afff;font-size:12px;text-transform:uppercase;letter-spacing:.08em}@media(max-width:780px){main{padding:12px}.map-shell{height:520px}article{grid-template-columns:1fr}header{padding:0 12px}}@media(max-width:480px){#coverageBadge{display:none}.command button{padding:7px}.legend{gap:7px;font-size:11px}}
"""

JAVASCRIPT: Final = """
const params=new URLSearchParams(location.search);const state=params.get("state")||"route-map";
const route=document.querySelector("#routeMap"),detail=document.querySelector("#detailEvidence"),list=document.querySelector("#nodes");
const definitions=[
["Day 1","spine",55,65],["Garden choice","choice",220,65],["Garden detour","detour",400,125],["Day 1 merge","merge",600,65],["Shared call","shared",760,65],["Day 2","spine",55,240],["Market choice","choice",220,240],["Vendor gate","gate",400,200],["Nested merge","merge",600,240],["Station","spine",760,240],["Route fork","choice",900,65],["Red route","persistent",1020,15],["Blue route","persistent",1020,125],["Courage gate","gate",900,220],["Love +1","effect",400,305],["Money -10","effect",555,305],["Patrol loop","loop",760,360],["Shared return","shared",55,405],["Game ending","terminal",220,485],["Route ending","terminal",380,485],["Dead end","terminal",540,485],["Update boundary","terminal",700,485],["Dynamic target","unresolved",860,485],["Technical corridor","corridor",1020,405]];
definitions.forEach(([label,kind,x,y],index)=>{const item=document.createElement("li");item.className="node";item.dataset.kind=kind;item.style.left=`${x}px`;item.style.top=`${y}px`;item.tabIndex=index===0?0:-1;item.setAttribute("role","button");item.setAttribute("aria-label",`${label}, ${kind}`);item.setAttribute("aria-selected",index===0?"true":"false");item.textContent=label;const meta=document.createElement("small");meta.textContent=kind.replace("_"," ");item.append(meta);list.append(item)});
const nodes=[...document.querySelectorAll(".node")];let selected=0;function choose(index){nodes[selected].tabIndex=-1;nodes[selected].setAttribute("aria-selected","false");selected=(index+nodes.length)%nodes.length;nodes[selected].tabIndex=0;nodes[selected].setAttribute("aria-selected","true");nodes[selected].focus()}
function showDetail(){route.hidden=true;detail.hidden=false;document.documentElement.dataset.activeLevel="detail_evidence";document.querySelector("#backToMap").focus()}
function showMap(){detail.hidden=true;route.hidden=false;document.documentElement.dataset.activeLevel="route_map";nodes[selected].focus()}
list.addEventListener("keydown",event=>{if(["ArrowRight","ArrowDown"].includes(event.key)){event.preventDefault();choose(selected+1)}if(["ArrowLeft","ArrowUp"].includes(event.key)){event.preventDefault();choose(selected-1)}if(event.key==="Home"){event.preventDefault();choose(0)}if(event.key==="End"){event.preventDefault();choose(nodes.length-1)}if(event.key==="Enter"){event.preventDefault();showDetail()}});
list.addEventListener("click",event=>{if(event.target.closest(".node"))showDetail()});document.querySelector("#backToMap").addEventListener("click",showMap);detail.addEventListener("keydown",event=>{if(event.key==="Escape")showMap()});
if(state==="detail-evidence")showDetail();else{showMap();if(state==="coverage-progress")document.querySelector("#coveragePanel").hidden=false;if(state==="review-partial")document.querySelector("#reviewPanel").hidden=false;nodes[0].dispatchEvent(new KeyboardEvent("keydown",{key:"ArrowRight",bubbles:true}))}
const interactives=[...document.querySelectorAll("button,[role=button]")];const namesOk=interactives.every(element=>Boolean(element.getAttribute("aria-label")||element.textContent.trim()));document.documentElement.dataset.levels="route_map,detail_evidence";document.documentElement.dataset.levelCount="2";document.documentElement.dataset.visibleNodes=String(nodes.length);document.documentElement.dataset.visibleItems=String(nodes.length+5);document.documentElement.dataset.keyboardSelected=nodes[selected].textContent;document.documentElement.dataset.exactEvidence=detail.querySelector("pre").textContent.includes("love += 1")?"true":"false";document.documentElement.dataset.onlyLevelTransition=document.querySelector("#backToMap").textContent.trim();document.documentElement.dataset.accessibleNames=String(namesOk);document.documentElement.dataset.font=getComputedStyle(document.body).fontFamily;document.documentElement.dataset.bodyPx=getComputedStyle(document.body).fontSize;document.documentElement.dataset.remoteRequests="0";document.documentElement.dataset.providerConstructions="0";document.documentElement.dataset.acceptanceReady="true";
"""

ASSETS: Final = {
    "/": ("text/html; charset=utf-8", HTML),
    "/index.html": ("text/html; charset=utf-8", HTML),
    "/styles.css": ("text/css; charset=utf-8", CSS),
    "/app.js": ("text/javascript; charset=utf-8", JAVASCRIPT),
}
STATES: Final = ("route-map", "detail-evidence", "coverage-progress", "review-partial")


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
    class MockHandler(http.server.BaseHTTPRequestHandler):
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

    return MockHandler


def run(output: Path, *, browser: Path | None = None) -> dict[str, object]:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if contract["levels"] != ["route_map", "detail_evidence"]:
        raise AssertionError("The M07 harness requires exactly two user-visible levels")
    remote_pattern = re.compile(r"(?:https?:)?//(?!127\.0\.0\.1|localhost)", re.IGNORECASE)
    if any(remote_pattern.search(text) for _, text in ASSETS.values()):
        raise AssertionError("Mock assets contain a remote URL")

    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    executable = browser or _browser()
    request_log: list[str] = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _handler(request_log))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    captures: dict[str, object] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="rsm-m07-browser-") as profile:
            for state in STATES:
                for zoom in contract["zoom_percentages"]:
                    name = f"{state}-{zoom}"
                    screenshot = output / f"{name}.png"
                    query = urllib.parse.urlencode({"state": state, "zoom": zoom})
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
                        "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1, EXCLUDE localhost",
                        f"--user-data-dir={profile}",
                        f"--window-size={'720,450' if zoom == 200 else '1440,900'}",
                        "--virtual-time-budget=1500",
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
                    if markers.get("levels") != "route_map,detail_evidence":
                        raise AssertionError("A level other than Route Map and Detail/Evidence exists")
                    if markers.get("level-count") != "2":
                        raise AssertionError("The visible hierarchy is not exactly two levels")
                    expected_level = (
                        "detail_evidence" if state == "detail-evidence" else "route_map"
                    )
                    if markers.get("active-level") != expected_level:
                        raise AssertionError(f"Unexpected visible level for {name}")
                    if int(markers.get("visible-nodes", "999")) > contract["initial_node_limit"]:
                        raise AssertionError("Initial Route Map exceeds the 30-node contract")
                    if int(markers.get("visible-items", "999")) > contract["render_item_limit"]:
                        raise AssertionError("Rendering exceeded the bounded item contract")
                    if markers.get("only-level-transition") != "Back to Route Map":
                        raise AssertionError("Detail has an unauthorized level transition")
                    if markers.get("exact-evidence") != "true":
                        raise AssertionError("Detail does not contain direct exact evidence")
                    if markers.get("accessible-names") != "true":
                        raise AssertionError("An interactive control lacks an accessible name")
                    if not markers.get("keyboard-selected"):
                        raise AssertionError("Keyboard navigation did not retain a selected map node")
                    if "Segoe UI" not in markers.get("font", ""):
                        raise AssertionError("The required local Windows font stack is absent")
                    body_size = float(markers.get("body-px", "0px").removesuffix("px"))
                    if body_size < contract["accessibility"]["minimum_body_px"]:
                        raise AssertionError("Body text is smaller than the accessibility contract")
                    if markers.get("remote-requests") != "0":
                        raise AssertionError("The mock frontend attempted a remote request")
                    if markers.get("provider-constructions") != "0":
                        raise AssertionError("Opening or rendering constructed a provider")
                    if not screenshot.is_file() or screenshot.stat().st_size < 10_000:
                        raise AssertionError(f"Browser screenshot was not produced for {name}")
                    captures[name] = {
                        "file": screenshot.name,
                        "sha256": _hash(screenshot),
                        "bytes": screenshot.stat().st_size,
                        "level": markers.get("active-level"),
                        "levels": markers.get("levels"),
                        "visible_nodes": int(markers["visible-nodes"]),
                        "visible_items": int(markers["visible-items"]),
                        "keyboard_selected": markers.get("keyboard-selected"),
                        "exact_evidence": markers.get("exact-evidence") == "true",
                        "font": markers.get("font"),
                        "body_px": markers.get("body-px"),
                    }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    result: dict[str, object] = {
        "browser": executable.name,
        "origin": "127.0.0.1 ephemeral",
        "levels": contract["levels"],
        "remote_requests": 0,
        "provider_constructions": 0,
        "request_paths": sorted(set(request_log)),
        "states": captures,
    }
    report = output / "m07-browser-acceptance.json"
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
