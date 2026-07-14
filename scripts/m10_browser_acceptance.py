# ruff: noqa: E501
"""Real Chrome/Edge acceptance for the hardened M10 inspection experience."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

import renpy_story_mapper.project_analysis as project_analysis
from renpy_story_mapper.project import create_ingested_project, refresh_ingested_project
from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.security import SessionSecurity
from renpy_story_mapper.web.server import LocalWebServer, start_in_thread
from renpy_story_mapper.web.state import UserStateStore

ROOT: Final = Path(__file__).resolve().parents[1]
STATIC: Final = ROOT / "src" / "renpy_story_mapper" / "web" / "static"
FIXTURE: Final = ROOT / "tests" / "fixtures" / "m10" / "canonical_constructs.rpy"
ZOOMS: Final = (100, 200)
VIEWPORTS: Final = {100: (1440, 900), 200: (720, 450)}
SEARCH_TARGET: Final = "Scene 44 unique text."
SUPPRESSED_SEARCH_TARGET: Final = "label dynamic_dispatch:"
OPAQUE_STATUS: Final = "Unsupported creator Python · preserved, not executed"
CHROME_CANDIDATES: Final = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)


def _m07_harness() -> Any:
    path = Path(__file__).with_name("m07_browser_acceptance.py")
    spec = importlib.util.spec_from_file_location("rsm_m10_cdp_driver", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("The existing browser CDP driver could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


M07_HARNESS = _m07_harness()


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


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_project(root: Path, *, failed_refresh: bool) -> Path:
    source = root / "game" / "story.rpy"
    source.parent.mkdir(parents=True)
    padding = "".join(
        f'\nlabel padding_{index:02d}:\n    "Scene {index:02d} unique text."\n    return\n'
        for index in range(45)
    )
    source.write_text(FIXTURE.read_text(encoding="utf-8") + padding, encoding="utf-8")
    destination = root / ("m10-failed.rsmproj" if failed_refresh else "m10-current.rsmproj")
    create_ingested_project(destination, source.parent).close()
    if not failed_refresh:
        return destination

    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "The temporary branch rejoins.", "The changed branch would rejoin."
        ),
        encoding="utf-8",
    )
    original = project_analysis.project_route_map

    def fail_route(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("injected M10 browser route projection failure")

    project_analysis.project_route_map = fail_route  # type: ignore[assignment]
    try:
        try:
            refresh_ingested_project(destination, source.parent)
        except RuntimeError as error:
            if "injected M10 browser route projection failure" not in str(error):
                raise
        else:
            raise AssertionError("The failed-refresh fixture unexpectedly completed")
    finally:
        project_analysis.project_route_map = original
    return destination


def _initial_failure_project(root: Path, *, phase: str) -> Path:
    source = root / "game" / "story.rpy"
    source.parent.mkdir(parents=True)
    padding = "".join(
        f'\nlabel padding_{index:02d}:\n    "Scene {index:02d} unique text."\n    return\n'
        for index in range(45)
    )
    source.write_text(FIXTURE.read_text(encoding="utf-8") + padding, encoding="utf-8")
    destination = root / f"m10-{phase}-failure.rsmproj"
    if phase == "simplified_projection":
        attribute = "project_inspection_graph"
        message = "injected M10 browser simplified projection failure"
    elif phase == "control_flow":
        attribute = "analyze_control_flow"
        message = "injected M10 browser control-flow failure"
    else:
        raise ValueError(f"Unsupported initial failure phase: {phase}")
    original = getattr(project_analysis, attribute)

    def fail_phase(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError(message)

    setattr(project_analysis, attribute, fail_phase)
    try:
        try:
            create_ingested_project(destination, source.parent)
        except RuntimeError as error:
            if message not in str(error):
                raise
        else:
            raise AssertionError(f"The {phase} failure fixture unexpectedly completed")
    finally:
        setattr(project_analysis, attribute, original)
    return destination


def _screenshot(session: Any, path: Path) -> None:
    path.write_bytes(
        base64.b64decode(
            session.command(
                "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
            )["data"]
        )
    )


def _launch(browser: Path, zoom: int, profile: Path) -> subprocess.Popen[bytes]:
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
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _session(browser: Path, zoom: int, profile: Path) -> tuple[subprocess.Popen[bytes], Any]:
    process = _launch(browser, zoom, profile)
    active = profile / "DevToolsActivePort"
    deadline = time.monotonic() + 15
    while not active.is_file() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not active.is_file():
        process.terminate()
        raise RuntimeError("Chrome did not publish its DevTools port")
    port = int(active.read_text(encoding="utf-8").splitlines()[0])
    session = M07_HARNESS._Cdp(
        str(M07_HARNESS._devtools_page(port)["webSocketDebuggerUrl"])
    )
    session.command("Page.enable")
    session.command("Runtime.enable")
    session.command("Network.enable")
    session.command("Log.enable")
    width, height = VIEWPORTS[zoom]
    session.command(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": width,
            "height": height,
            "deviceScaleFactor": 2 if zoom == 200 else 1,
            "mobile": False,
        },
    )
    return process, session


def _browser_diagnostics(
    session: Any, *, allowed_error_suffixes: tuple[str, ...] = ()
) -> tuple[int, list[str], int]:
    requests = [
        event["params"]["request"]["url"]
        for event in session.events
        if event.get("method") == "Network.requestWillBeSent"
    ]
    remote = [
        url for url in requests if urlsplit(url).hostname not in {"127.0.0.1", "localhost"}
    ]
    errors = []
    allowed_errors = 0
    for event in session.events:
        if event.get("method") == "Runtime.exceptionThrown":
            errors.append(event)
        elif event.get("method") == "Log.entryAdded":
            entry = event.get("params", {}).get("entry", {})
            text = str(entry.get("text", ""))
            url = str(entry.get("url", ""))
            if any(url.endswith(suffix) for suffix in allowed_error_suffixes):
                allowed_errors += 1
                continue
            if "frame-ancestors" not in text and not url.endswith("/favicon.ico"):
                errors.append(event)
    if remote:
        raise AssertionError(f"Remote browser requests observed: {remote}")
    if errors:
        raise AssertionError(f"Browser errors observed: {errors}")
    return len(requests), remote, allowed_errors


def _layout(session: Any) -> dict[str, Any]:
    value = session.evaluate(
        """(() => { const vw=document.documentElement.clientWidth; const offenders=[...document.body.querySelectorAll('*')].filter(x=>!x.closest('#mapViewport')&&!x.closest('dialog')&&x.getBoundingClientRect().right>vw+1).map(x=>x.id||x.className).slice(0,10); return {scrollWidth:document.documentElement.scrollWidth,clientWidth:vw,offenders}; })()"""
    )
    if value["offenders"]:
        raise AssertionError(f"Layout overflow escaped the map pan surface: {value}")
    return value


def _capture_current(browser: Path, output: Path, zoom: int, origin: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="rsm-m10-current-chrome-", ignore_cleanup_errors=True) as temporary:
        process, session = _session(browser, zoom, Path(temporary))
        try:
            session.command("Page.navigate", {"url": origin})
            session.wait("document.readyState === 'complete' && !!document.querySelector('.recent-card')")
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait("document.querySelectorAll('.station').length > 0 && document.querySelector('#inspectionMapButton').getAttribute('aria-pressed') === 'true'")
            default = session.evaluate(
                "({badge:document.querySelector('#projectBadge').textContent,generation:document.querySelector('#generationStatus').textContent,failureHidden:document.querySelector('#analysisFailureBanner').hidden,mode:document.querySelector('#inspectionMapButton').getAttribute('aria-pressed'),status:document.querySelector('#pageStatus').textContent})"
            )
            if default["badge"] != "M10 Inspection" or default["mode"] != "true":
                raise AssertionError(f"Current M10 inspection was not the default: {default}")
            if not default["failureHidden"] or not default["generation"].startswith("current"):
                raise AssertionError(f"Current generation status was not honest: {default}")
            default_shot = output / f"m10-default-{zoom}.png"
            _screenshot(session, default_shot)

            session.evaluate(
                f"(() => {{ const input=document.querySelector('#searchInput'); input.value={json.dumps(SUPPRESSED_SEARCH_TARGET)}; input.dispatchEvent(new Event('input',{{bubbles:true}})); }})()"
            )
            session.wait(
                f"import('./app.js').then(m=>m.state.mode==='canonical' && m.state.detail?.element?.attributes?.source_text==={json.dumps(SUPPRESSED_SEARCH_TARGET)} && !document.querySelector('#detailView').hidden)"
            )
            suppressed_search = session.evaluate(
                "import('./app.js').then(m=>({mode:m.state.mode,detailId:m.state.detail.element.id,sourceText:m.state.detail.element.attributes.source_text,targetView:m.state.page.search.focus.target_view,canonicalId:m.state.page.search.focus.canonical_id,button:document.querySelector('#canonicalMapButton').getAttribute('aria-pressed')}))"
            )
            if suppressed_search["detailId"] != suppressed_search["canonicalId"]:
                raise AssertionError(
                    f"Suppressed search did not open exact canonical detail: {suppressed_search}"
                )
            suppressed_shot = output / f"m10-suppressed-canonical-{zoom}.png"
            _screenshot(session, suppressed_shot)
            session.evaluate("document.querySelector('#backToRouteMap').click()")
            session.wait("document.querySelector('#routeMapView').hidden === false")

            session.evaluate("document.querySelector('#canonicalMapButton').click()")
            session.wait("document.querySelector('#canonicalMapButton').getAttribute('aria-pressed') === 'true'")
            session.evaluate(
                f"(() => {{ const input=document.querySelector('#searchInput'); input.value={json.dumps(SEARCH_TARGET)}; input.dispatchEvent(new Event('input',{{bubbles:true}})); }})()"
            )
            session.wait(
                f"import('./app.js').then(m=>m.state.page?.search?.query==={json.dumps(SEARCH_TARGET.casefold())} && Number(m.state.page?.search?.focus?.offset)>=30 && m.state.page.nodes.some(n=>n.id===m.state.page.search.focus.element_id))"
            )
            search = session.evaluate(
                "import('./app.js').then(m=>({query:m.state.page.search.query,focus:m.state.page.search.focus,pageStatus:document.querySelector('#pageStatus').textContent,selected:m.graph.selectedId,nodeIds:m.state.page.nodes.map(n=>n.id)}))"
            )
            if search["focus"]["offset"] < 30 or search["focus"]["element_id"] not in search["nodeIds"]:
                raise AssertionError(f"Whole-graph search did not center an off-page result: {search}")
            search_shot = output / f"m10-whole-graph-search-{zoom}.png"
            _screenshot(session, search_shot)

            session.evaluate("document.querySelector('#inspectionMapButton').click()")
            session.wait("document.querySelector('#inspectionMapButton').getAttribute('aria-pressed') === 'true'")
            session.evaluate(
                "(() => { const input=document.querySelector('#searchInput'); input.value='Help'; input.dispatchEvent(new Event('input',{bubbles:true})); })()"
            )
            session.wait("import('./app.js').then(m=>m.state.page?.search?.query==='help' && m.graph.nodes.some(n=>n.title==='Help'))")
            outcome_id = session.evaluate(
                "import('./app.js').then(m=>{const node=m.graph.nodes.find(n=>n.title==='Help'); document.querySelector(`[data-element-id=\"${CSS.escape(node.id)}\"]`).click(); return node.id;})"
            )
            session.wait(
                f"import('./app.js').then(m=>m.state.detail?.element?.id==={json.dumps(outcome_id)} && !document.querySelector('#detailView').hidden)"
            )
            root_detail = session.evaluate(
                "import('./app.js').then(m=>({linkedKinds:[...new Set(m.state.detail.linked_records.map(x=>x.kind))].sort(),evidence:m.state.detail.evidence.length,proofs:m.state.detail.proofs.length,regions:m.state.detail.regions.length,facts:m.state.detail.facts.length}))"
            )
            required = {"evidence", "fact", "proof", "region"}
            if not required.issubset(root_detail["linkedKinds"]):
                raise AssertionError(f"Outcome detail omitted direct derivation links: {root_detail}")

            direct: dict[str, Any] = {}
            for kind in ("region", "fact", "evidence", "proof"):
                if kind != "region":
                    session.evaluate(
                        f"document.querySelector('[data-element-id={json.dumps(outcome_id)}]').click()"
                    )
                    session.wait(
                        f"import('./app.js').then(m=>m.state.detail?.element?.id==={json.dumps(outcome_id)})"
                    )
                clicked = session.evaluate(
                    f"(() => {{ const button=[...document.querySelectorAll('#linkedRecords .linked-record')].find(x=>x.textContent.startsWith({json.dumps(kind + ' ·')})); if(!button) return false; button.click(); return true; }})()"
                )
                if not clicked:
                    raise AssertionError(f"Direct {kind} detail link was not rendered")
                expected_kind = "branch_region" if kind == "region" else kind
                session.wait(
                    f"import('./app.js').then(m=>m.state.detail?.element?.kind==={json.dumps(expected_kind)})"
                )
                direct[kind] = session.evaluate(
                    "import('./app.js').then(m=>({id:m.state.detail.element.id,kind:m.state.detail.element.kind,evidence:m.state.detail.evidence.length,proofs:m.state.detail.proofs.length,regionRecords:document.querySelectorAll('#regionDerivation .derivation-record').length,proofRecords:document.querySelectorAll('#proofDerivation .derivation-record').length}))"
                )
            if direct["region"]["regionRecords"] < 1 or direct["proof"]["proofRecords"] < 1:
                raise AssertionError(f"Region/proof derivations were not rendered directly: {direct}")
            if direct["fact"]["evidence"] < 1 or direct["evidence"]["evidence"] < 1:
                raise AssertionError(f"Fact/evidence detail omitted exact source evidence: {direct}")
            derivation_shot = output / f"m10-direct-proof-detail-{zoom}.png"
            _screenshot(session, derivation_shot)

            session.evaluate("document.querySelector('#backToRouteMap').click(); document.querySelector('#canonicalMapButton').click()")
            session.wait("document.querySelector('#canonicalMapButton').getAttribute('aria-pressed') === 'true'")
            session.evaluate(
                "(() => { const input=document.querySelector('#searchInput'); input.value='$ trust = 0'; input.dispatchEvent(new Event('input',{bubbles:true})); })()"
            )
            session.wait("import('./app.js').then(m=>m.state.page?.search?.query==='$ trust = 0' && m.graph.nodes.some(n=>n.unsupported_status))")
            session.evaluate(
                "import('./app.js').then(m=>{const node=m.graph.nodes.find(n=>n.unsupported_status); document.querySelector(`[data-element-id=\"${CSS.escape(node.id)}\"]`).click();})"
            )
            session.wait(
                f"document.querySelector('#detailSummary').textContent==={json.dumps(OPAQUE_STATUS)}"
            )
            opaque = session.evaluate(
                "import('./app.js').then(m=>({sourceKind:m.state.detail.element.source_kind,unsupportedStatus:m.state.detail.element.unsupported_status,summary:document.querySelector('#detailSummary').textContent}))"
            )
            if opaque["summary"] != OPAQUE_STATUS or opaque["unsupportedStatus"] != OPAQUE_STATUS:
                raise AssertionError(f"Opaque creator-Python status was not exact: {opaque}")
            opaque_shot = output / f"m10-opaque-status-{zoom}.png"
            _screenshot(session, opaque_shot)

            layout = _layout(session)
            request_count, remote, allowed_errors = _browser_diagnostics(session)
            return {
                "zoom_percent": zoom,
                "viewport": {"width": VIEWPORTS[zoom][0], "height": VIEWPORTS[zoom][1]},
                "default": default,
                "suppressed_canonical_search": suppressed_search,
                "whole_graph_search": search,
                "root_detail": root_detail,
                "direct_details": direct,
                "opaque": opaque,
                "layout": layout,
                "request_count": request_count,
                "remote_requests": len(remote),
                "expected_optional_api_rejections": allowed_errors,
                "screenshots": {
                    path.stem: {"file": path.name, "sha256": _hash(path)}
                    for path in (
                        default_shot,
                        suppressed_shot,
                        search_shot,
                        derivation_shot,
                        opaque_shot,
                    )
                },
            }
        finally:
            session.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def _capture_failure(browser: Path, output: Path, zoom: int, origin: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="rsm-m10-failure-chrome-", ignore_cleanup_errors=True) as temporary:
        process, session = _session(browser, zoom, Path(temporary))
        try:
            session.command("Page.navigate", {"url": origin})
            session.wait("document.readyState === 'complete' && !!document.querySelector('.recent-card')")
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait("!document.querySelector('#analysisFailureBanner').hidden && document.querySelectorAll('.station').length > 0")
            failure = session.evaluate(
                "import('./app.js').then(m=>({mode:m.state.mode,mapVisible:!document.querySelector('#mapLayout').hidden,title:document.querySelector('#analysisFailureTitle').textContent,summary:document.querySelector('#analysisFailureSummary').textContent,completed:document.querySelector('#analysisCompletedPhases').textContent,generation:m.state.page.generation_status}))"
            )
            if failure["mode"] != "inspection" or not failure["mapVisible"]:
                raise AssertionError(f"Failed refresh did not enter the retained M10 workspace: {failure}")
            if failure["generation"]["freshness"] != "stale" or not failure["generation"]["last_known_good"]:
                raise AssertionError(f"Failed refresh did not expose last-known-good status: {failure}")
            if failure["generation"]["failure"]["phase"] != "route_map":
                raise AssertionError(f"Failure phase was not visible and exact: {failure}")
            if "Showing last-known-good results" not in failure["summary"]:
                raise AssertionError(f"Failure banner hid the retained-result state: {failure}")
            shot = output / f"m10-retained-failure-{zoom}.png"
            _screenshot(session, shot)
            layout = _layout(session)
            request_count, remote, allowed_errors = _browser_diagnostics(
                session,
                allowed_error_suffixes=(
                    "/api/v1/m08/comparison",
                    "/api/v1/m07/organization",
                ),
            )
            return {
                "zoom_percent": zoom,
                "failure": failure,
                "layout": layout,
                "request_count": request_count,
                "remote_requests": len(remote),
                "expected_optional_api_rejections": allowed_errors,
                "screenshot": {"file": shot.name, "sha256": _hash(shot)},
            }
        finally:
            session.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def _capture_canonical_only(
    browser: Path, output: Path, zoom: int, origin: str
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix="rsm-m10-canonical-only-chrome-", ignore_cleanup_errors=True
    ) as temporary:
        process, session = _session(browser, zoom, Path(temporary))
        try:
            session.command("Page.navigate", {"url": origin})
            session.wait(
                "document.readyState === 'complete' && !!document.querySelector('.recent-card')"
            )
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait(
                "!document.querySelector('#analysisFailureBanner').hidden && document.querySelectorAll('.station').length > 0 && document.querySelector('#canonicalMapButton').getAttribute('aria-pressed') === 'true'"
            )
            state = session.evaluate(
                "import('./app.js').then(m=>({mode:m.state.mode,mapVisible:!document.querySelector('#mapLayout').hidden,partialHidden:document.querySelector('#partialAnalysisPanel').hidden,inspectionDisabled:document.querySelector('#inspectionMapButton').disabled,canonicalDisabled:document.querySelector('#canonicalMapButton').disabled,badge:document.querySelector('#projectBadge').textContent,title:document.querySelector('#analysisFailureTitle').textContent,summary:document.querySelector('#analysisFailureSummary').textContent,completed:document.querySelector('#analysisCompletedPhases').textContent,generation:m.state.page.generation_status,nodeCount:m.state.page.nodes.length}))"
            )
            generation = state["generation"]
            if state["mode"] != "canonical" or state["badge"] != "M10 Canonical":
                raise AssertionError(
                    f"Canonical authority was not selected after projection failure: {state}"
                )
            if (
                not state["mapVisible"]
                or not state["partialHidden"]
                or not state["inspectionDisabled"]
                or state["canonicalDisabled"]
            ):
                raise AssertionError(
                    f"Canonical-only controls did not reflect availability: {state}"
                )
            if (
                generation["freshness"] != "current"
                or generation["canonical_availability"] != "current_complete"
                or generation["simplified_availability"] != "none"
                or generation["failure"]["phase"] != "simplified_projection"
            ):
                raise AssertionError(f"Canonical-only generation state was not exact: {state}")
            if "Showing current retained results" not in state["summary"]:
                raise AssertionError(f"Canonical-only failure banner was not explicit: {state}")
            session.evaluate(
                "new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))"
            )
            shot = output / f"m10-canonical-only-{zoom}.png"
            _screenshot(session, shot)
            layout = _layout(session)
            request_count, remote, allowed_errors = _browser_diagnostics(
                session,
                allowed_error_suffixes=(
                    "/api/v1/m08/comparison",
                    "/api/v1/m07/organization",
                ),
            )
            return {
                "zoom_percent": zoom,
                "canonical_only": state,
                "layout": layout,
                "request_count": request_count,
                "remote_requests": len(remote),
                "expected_optional_api_rejections": allowed_errors,
                "screenshot": {"file": shot.name, "sha256": _hash(shot)},
            }
        finally:
            session.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def _capture_partial_analysis(
    browser: Path, output: Path, zoom: int, origin: str
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix="rsm-m10-partial-chrome-", ignore_cleanup_errors=True
    ) as temporary:
        process, session = _session(browser, zoom, Path(temporary))
        try:
            session.command("Page.navigate", {"url": origin})
            session.wait(
                "document.readyState === 'complete' && !!document.querySelector('.recent-card')"
            )
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait(
                "!document.querySelector('#analysisFailureBanner').hidden && !document.querySelector('#partialAnalysisPanel').hidden && document.querySelector('#mapLayout').hidden"
            )
            state = session.evaluate(
                "import('./app.js').then(m=>({mode:m.state.mode,mapHidden:document.querySelector('#mapLayout').hidden,partialVisible:!document.querySelector('#partialAnalysisPanel').hidden,stationCount:document.querySelectorAll('.station').length,title:document.querySelector('#analysisFailureTitle').textContent,summary:document.querySelector('#analysisFailureSummary').textContent,completed:document.querySelector('#analysisCompletedPhases').textContent,partialSummary:document.querySelector('#partialAnalysisSummary').textContent,generation:m.state.analysisStatus}))"
            )
            generation = state["generation"]
            expected_phases = ["source_inventory", "parse", "graph", "semantic_state"]
            if not state["mapHidden"] or not state["partialVisible"] or state["stationCount"]:
                raise AssertionError(f"Early failure rendered an unbacked map: {state}")
            if (
                generation["failure"]["phase"] != "control_flow"
                or generation["canonical_availability"] != "none"
                or generation["simplified_availability"] != "none"
                or generation["completed_phases"] != expected_phases
            ):
                raise AssertionError(f"Bounded partial-analysis state was not exact: {state}")
            if "No retained map is available" not in state["summary"]:
                raise AssertionError(f"Partial-analysis failure banner was not explicit: {state}")
            if any(phase.replace("_", " ") not in state["partialSummary"] for phase in expected_phases):
                raise AssertionError(f"Completed phases were not rendered in the partial panel: {state}")
            session.evaluate(
                "new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))"
            )
            shot = output / f"m10-bounded-partial-analysis-{zoom}.png"
            _screenshot(session, shot)
            layout = _layout(session)
            request_count, remote, allowed_errors = _browser_diagnostics(
                session,
                allowed_error_suffixes=(
                    "/api/v1/m08/comparison",
                    "/api/v1/m07/organization",
                ),
            )
            return {
                "zoom_percent": zoom,
                "partial_analysis": state,
                "layout": layout,
                "request_count": request_count,
                "remote_requests": len(remote),
                "expected_optional_api_rejections": allowed_errors,
                "screenshot": {"file": shot.name, "sha256": _hash(shot)},
            }
        finally:
            session.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def _serve(
    project: Path,
    state_path: Path,
    provider_counter: list[int],
    capture: Any,
) -> Any:
    state = UserStateStore(state_path)
    state.record_project(project)

    def forbidden_provider(_scope: object) -> object:
        provider_counter[0] += 1
        raise AssertionError("M10 browser acceptance must not construct a provider")

    api = ProjectApi(_NoDialogs(), state_store=state, m07_provider_factory=forbidden_provider)
    server = LocalWebServer(
        "127.0.0.1",
        0,
        api,
        static_root=STATIC,
        security=SessionSecurity("m10-acceptance-session", "m10-acceptance-csrf"),
    )
    thread = start_in_thread(server)
    try:
        return capture(f"http://127.0.0.1:{server.port}/")
    finally:
        server.close_service()
        thread.join(timeout=5)
        api.close()


def run(output: Path, *, browser: Path | None = None) -> dict[str, Any]:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    selected_browser = browser or _browser()
    provider_counter = [0]
    with tempfile.TemporaryDirectory(prefix="rsm-m10-browser-") as temporary:
        root = Path(temporary)
        current = _fixture_project(root / "current", failed_refresh=False)
        failed = _fixture_project(root / "failed", failed_refresh=True)
        canonical_only = _initial_failure_project(
            root / "canonical-only", phase="simplified_projection"
        )
        partial = _initial_failure_project(root / "partial", phase="control_flow")
        captures: dict[str, Any] = {}
        failures: dict[str, Any] = {}
        canonical_only_captures: dict[str, Any] = {}
        partial_analysis_captures: dict[str, Any] = {}
        for zoom in ZOOMS:
            captures[str(zoom)] = _serve(
                current,
                root / f"current-state-{zoom}.json",
                provider_counter,
                lambda origin, value=zoom: _capture_current(
                    selected_browser, output, value, origin
                ),
            )
            failures[str(zoom)] = _serve(
                failed,
                root / f"failed-state-{zoom}.json",
                provider_counter,
                lambda origin, value=zoom: _capture_failure(
                    selected_browser, output, value, origin
                ),
            )
            canonical_only_captures[str(zoom)] = _serve(
                canonical_only,
                root / f"canonical-only-state-{zoom}.json",
                provider_counter,
                lambda origin, value=zoom: _capture_canonical_only(
                    selected_browser, output, value, origin
                ),
            )
            partial_analysis_captures[str(zoom)] = _serve(
                partial,
                root / f"partial-state-{zoom}.json",
                provider_counter,
                lambda origin, value=zoom: _capture_partial_analysis(
                    selected_browser, output, value, origin
                ),
            )
    if provider_counter[0]:
        raise AssertionError("Provider construction occurred during M10 browser acceptance")
    result = {
        "origin": "127.0.0.1 ephemeral",
        "server": "LocalWebServer",
        "api": "ProjectApi",
        "project": "generated temporary SQLite projects",
        "provider_constructions": provider_counter[0],
        "remote_requests": 0,
        "captures": captures,
        "failed_refresh_captures": failures,
        "canonical_only_captures": canonical_only_captures,
        "partial_analysis_captures": partial_analysis_captures,
    }
    (output / "m10-browser-acceptance.json").write_text(
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
