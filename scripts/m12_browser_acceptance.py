# ruff: noqa: E501
"""Exercise the real M12 local route workflow in Chrome or Edge."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from renpy_story_mapper.m12_service import M12RouteService
from renpy_story_mapper.organization.contracts import OrganizationProvider
from renpy_story_mapper.organization.parallel import RouteScope
from renpy_story_mapper.project import create_ingested_project
from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.security import SessionSecurity
from renpy_story_mapper.web.server import LocalWebServer, start_in_thread
from renpy_story_mapper.web.state import UserStateStore

ROOT: Final = Path(__file__).resolve().parents[1]
STATIC: Final = ROOT / "src" / "renpy_story_mapper" / "web" / "static"
FIXTURE: Final = ROOT / "tests" / "fixtures" / "m12" / "route_targets.rpy"
ZOOMS: Final = (100, 200)
BADGES: Final = (
    "Confirmed route",
    "Route with prerequisites",
    "Best known route",
    "No proven route",
)


def _browser_driver() -> Any:
    path = Path(__file__).with_name("m10_browser_acceptance.py")
    spec = importlib.util.spec_from_file_location("rsm_m12_browser_driver", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("The existing real-browser CDP driver could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DRIVER = _browser_driver()


class _NoDialogs:
    def choose_source(self, _kind: str) -> Path | None:
        return None

    def choose_open_project(self) -> Path | None:
        return None

    def choose_save_project(self) -> Path | None:
        return None


def _fingerprint(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
    }


def _artifact(path: Path, root: Path) -> dict[str, object]:
    return {
        "file": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def _fixture_project(root: Path) -> tuple[Path, Path, dict[str, object]]:
    source = root / "game" / "story.rpy"
    source.parent.mkdir(parents=True)
    source.write_bytes(FIXTURE.read_bytes())
    before = _fingerprint(source)
    project = root / "m12-browser.rsmproj"
    create_ingested_project(project, source.parent).close()
    return project, source, before


def _wait_for_download(folder: Path) -> Path:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        matches = tuple(folder.glob("route-*.json"))
        if len(matches) == 1 and not tuple(folder.glob("*.crdownload")):
            return matches[0]
        time.sleep(0.05)
    raise AssertionError("The visible M12 JSON export did not finish")


def _capture(
    browser: Path,
    output: Path,
    zoom: int,
    origin: str,
    operation_idle: Callable[[], bool],
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(
        prefix="rsm-m12-chrome-", ignore_cleanup_errors=True
    ) as temporary:
        process, session = DRIVER._session(browser, zoom, Path(temporary))
        try:
            session.command("Browser.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(output)})
            session.command("Page.navigate", {"url": origin})
            session.wait("document.readyState === 'complete' && !!document.querySelector('.recent-card')")
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait("document.querySelectorAll('.station').length > 0 && document.querySelector('#sceneMapButton').getAttribute('aria-pressed') === 'true'")
            selected = session.evaluate(
                "import('./app.js').then(m=>{const node=m.graph.nodes.find(item=>item.title==='Foyer'); if(!node) throw new Error('Foyer scene is not on the first bounded page'); document.querySelector(`[data-element-id=\"${CSS.escape(node.id)}\"]`).click(); return {id:node.id,title:node.title,levelCount:document.querySelectorAll('[data-level]').length,levels:[...document.querySelectorAll('[data-level]')].map(item=>item.dataset.level).sort()};})"
            )
            if selected["levelCount"] != 2 or selected["levels"] != ["detail_evidence", "route_map"]:
                raise AssertionError(f"M12 introduced a third navigation level: {selected}")
            session.wait(
                "document.documentElement.dataset.activeLevel==='detail_evidence' && !document.querySelector('#detailView').hidden"
            )
            session.evaluate("document.querySelector('#backToRouteMap').click()")
            session.wait(
                "document.documentElement.dataset.activeLevel==='route_map' && !document.querySelector('#routeMapView').hidden"
            )
            session.wait("import('./app.js').then(m=>m.state.route.phase==='ready' && document.querySelector('#routeDestination').textContent==='Foyer')")

            action_text = session.evaluate("document.querySelector('#solveRoute').textContent")
            if action_text != "How do I reach this?":
                raise AssertionError(f"M12 route action text changed unexpectedly: {action_text!r}")

            session.evaluate("document.querySelector('#solveRoute').click()")
            session.wait("import('./app.js').then(m=>m.state.route.phase==='running' && !document.querySelector('#cancelRoute').hidden)")
            session.evaluate("document.querySelector('#cancelRoute').click()")
            session.wait("import('./app.js').then(m=>m.state.route.phase==='cancelled' && !document.querySelector('#retryRoute').hidden && document.querySelector('#routeStatus').textContent.includes('cancelled'))")
            cancelled = session.evaluate(
                "import('./app.js').then(m=>({phase:m.state.route.phase,status:document.querySelector('#routeStatus').textContent,result:m.state.route.result,retryVisible:!document.querySelector('#retryRoute').hidden}))"
            )
            if cancelled["result"] is not None or not cancelled["retryVisible"]:
                raise AssertionError(f"Cancellation published or replaced a route: {cancelled}")
            session.evaluate(
                "import('./api.js').then(async ({LocalApi})=>{const api=new LocalApi(); for(let index=0;index<80;index+=1){const progress=await api.progress(); const task=progress.task||progress; if(!['pending','running'].includes(task.state)) return task.state; await new Promise(resolve=>setTimeout(resolve,25));} throw new Error('cancelled server task did not settle');})"
            )
            idle_deadline = time.monotonic() + 10
            while not operation_idle() and time.monotonic() < idle_deadline:
                time.sleep(0.01)
            if not operation_idle():
                raise AssertionError("M12 cancelled worker did not become idle")

            session.evaluate("document.querySelector('#retryRoute').click()")
            try:
                session.wait("import('./app.js').then(m=>m.state.route.phase==='complete' && !!m.state.route.result && !document.querySelector('#routeResult').hidden)")
            except TimeoutError as error:
                retry_state = session.evaluate(
                    "import('./app.js').then(m=>({phase:m.state.route.phase,error:m.state.route.error,status:document.querySelector('#routeStatus').textContent,toast:document.querySelector('#toast').textContent,requestIdentity:m.state.route.requestIdentity,progressLabel:m.state.route.progressLabel}))"
                )
                raise AssertionError(f"M12 retry did not complete: {retry_state}") from error
            result = session.evaluate(
                "import('./app.js').then(m=>({badge:document.querySelector('#routeBadge').textContent,status:m.state.route.result.status,complete:m.state.route.result.complete,cached:m.state.route.cached,instructionTexts:[...document.querySelectorAll('#recommendedRouteBody .route-section:first-child ol li')].map(item=>item.textContent),orderedSections:[...document.querySelectorAll('#recommendedRouteBody .route-section h4')].map(item=>item.textContent),technicalSummary:document.querySelector('#routeTechnical summary').textContent,exportVisible:!document.querySelector('#exportRouteJson').hidden,requestIdentity:m.state.route.result.request_identity,provenance:m.state.route.result.recommended?.provenance||null}))"
            )
            if result["badge"] not in BADGES or not result["instructionTexts"]:
                raise AssertionError(f"M12 omitted its badge or ordered deterministic instructions: {result}")
            if result["orderedSections"][:2] != ["Instructions", "Ordered human scenes"]:
                raise AssertionError(f"M12 route sections are not separated and ordered: {result}")
            if not result["provenance"] or not result["provenance"].get("node_ids"):
                raise AssertionError(f"M12 omitted exact M10/M11 provenance: {result}")
            if not result["exportVisible"] or result["technicalSummary"] != "Technical status and evidence":
                raise AssertionError(f"M12 omitted export or technical/evidence expansion: {result}")
            claim = session.evaluate(
                "(()=>{const details=document.querySelector('#recommendedRouteBody .route-claim'); if(!details) throw new Error('route claim details are missing'); details.open=true; const value=JSON.parse(details.querySelector('pre').textContent); return {evidenceIds:value.evidence_ids||[],edgeId:value.edge_id||null,factId:value.fact_id||null};})()"
            )
            if not claim["evidenceIds"]:
                raise AssertionError(f"M12 route claim omitted exact evidence IDs: {claim}")
            session.evaluate("document.querySelector('#routeTechnical').open=true; document.querySelector('.route-provenance').open=true")
            session.evaluate(
                "document.querySelector('#recommendedRoute').scrollIntoView({block:'start'})"
            )
            session.evaluate(
                "new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))"
            )
            result_view = session.evaluate(
                "(()=>{const panel=document.querySelector('#routePanel').getBoundingClientRect(); const result=document.querySelector('#recommendedRoute').getBoundingClientRect(); return {activeLevel:document.documentElement.dataset.activeLevel,routeMapHidden:document.querySelector('#routeMapView').hidden,detailHidden:document.querySelector('#detailView').hidden,panelInViewport:panel.bottom>0&&panel.top<window.innerHeight,resultInViewport:result.bottom>0&&result.top<window.innerHeight};})()"
            )
            if result_view != {
                "activeLevel": "route_map",
                "routeMapHidden": False,
                "detailHidden": True,
                "panelInViewport": True,
                "resultInViewport": True,
            }:
                raise AssertionError(f"Route result was not visible before capture: {result_view}")
            result_shot = output / f"m12-route-result-{zoom}.png"
            DRIVER._screenshot(session, result_shot)
            result_shot_hash = hashlib.sha256(result_shot.read_bytes()).hexdigest()

            session.evaluate(
                "import('./app.js').then(m=>{const other=m.graph.nodes.find(item=>item.title==='Courtyard'); if(!other) throw new Error('alternate selection is unavailable'); document.querySelector(`[data-element-id=\"${CSS.escape(other.id)}\"]`).click();})"
            )
            session.wait("import('./app.js').then(m=>m.state.route.phase==='stale' && m.state.route.sourceId!==m.state.route.activeSourceId)")
            session.evaluate("document.querySelector('#openRouteEvidence').click()")
            session.wait("document.documentElement.dataset.activeLevel==='detail_evidence' && !document.querySelector('#detailView').hidden")
            detail = session.evaluate(
                "import('./app.js').then(m=>({activeLevel:document.documentElement.dataset.activeLevel,detailLevel:m.state.detail?.level,detailId:m.state.detail?.element?.id,backText:document.querySelector('#backToRouteMap').textContent,canonicalEscapeVisible:!document.querySelector('#canonicalEscapeButton').hidden,levelCount:document.querySelectorAll('[data-level]').length}))"
            )
            if detail["activeLevel"] != "detail_evidence" or detail["levelCount"] != 2:
                raise AssertionError(f"Detail/Evidence did not remain the second and final level: {detail}")
            if detail["detailId"] != selected["id"]:
                raise AssertionError(
                    f"Detail/Evidence followed the mutable selection instead of the solved route: {detail}"
                )
            session.evaluate(
                "document.querySelector('#detailView').scrollIntoView({block:'start'})"
            )
            session.evaluate(
                "new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))"
            )
            detail_shot = output / f"m12-route-evidence-{zoom}.png"
            DRIVER._screenshot(session, detail_shot)
            detail_shot_hash = hashlib.sha256(detail_shot.read_bytes()).hexdigest()
            if result_shot_hash == detail_shot_hash:
                raise AssertionError("Route result and Detail/Evidence captures are unexpectedly identical")
            session.evaluate("document.querySelector('#backToRouteMap').click()")
            session.wait("document.documentElement.dataset.activeLevel==='route_map'")
            session.evaluate(
                "import('./app.js').then(m=>document.querySelector(`[data-element-id=\"${CSS.escape(m.state.route.activeSourceId)}\"]`).click())"
            )
            session.wait("import('./app.js').then(m=>m.state.route.sourceId===m.state.route.activeSourceId)")

            session.evaluate("document.querySelector('#exportRouteJson').click()")
            exported = _wait_for_download(output)
            exported_json = json.loads(exported.read_text(encoding="utf-8"))
            if exported_json.get("request_identity") != result["requestIdentity"]:
                raise AssertionError("The visible export did not preserve the exact route identity")

            session.evaluate("document.querySelector('#solveRoute').click()")
            session.wait("import('./app.js').then(m=>m.state.route.phase==='complete' && m.state.route.cached===true)")
            cached = session.evaluate(
                "import('./app.js').then(m=>({cached:m.state.route.cached,status:document.querySelector('#routeStatus').textContent,identity:m.state.route.result.request_identity,badge:m.state.route.result.badge}))"
            )
            if cached["identity"] != result["requestIdentity"] or cached["badge"] != result["badge"]:
                raise AssertionError(f"Cached replay changed the normalized route: {cached}")

            layout = DRIVER._layout(session)
            request_count, remote, allowed_errors = DRIVER._browser_diagnostics(session)
            return {
                "zoom_percent": zoom,
                "viewport": {
                    "width": DRIVER.VIEWPORTS[zoom][0],
                    "height": DRIVER.VIEWPORTS[zoom][1],
                },
                "selected": selected,
                "route_action": action_text,
                "cancelled": cancelled,
                "result": {
                    "badge": result["badge"],
                    "status": result["status"],
                    "complete": result["complete"],
                    "instruction_count": len(result["instructionTexts"]),
                    "section_titles": result["orderedSections"],
                    "request_identity": result["requestIdentity"],
                    "provenance_node_count": len(result["provenance"]["node_ids"]),
                    "claim_evidence_count": len(claim["evidenceIds"]),
                },
                "result_view": result_view,
                "detail": detail,
                "cached_replay": cached,
                "layout": layout,
                "browser_request_count": request_count,
                "remote_requests": len(remote),
                "allowed_browser_errors": allowed_errors,
                "artifacts": [
                    _artifact(result_shot, output.parent),
                    _artifact(detail_shot, output.parent),
                    _artifact(exported, output.parent),
                ],
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

    def forbidden_provider(_scope: RouteScope) -> OrganizationProvider:
        provider_counter[0] += 1
        raise AssertionError("M12 browser acceptance must not construct a provider")

    api = ProjectApi(_NoDialogs(), state_store=state, m07_provider_factory=forbidden_provider)
    server = LocalWebServer(
        "127.0.0.1",
        0,
        api,
        static_root=STATIC,
        security=SessionSecurity("m12-acceptance-session", "m12-acceptance-csrf"),
    )
    original_solve = M12RouteService.solve
    first_attempt = [True]

    def injected_first_cancellation(
        service: M12RouteService,
        prepared: Any,
        *,
        cancelled: Any = None,
        emergency_seconds: float = 30.0,
    ) -> Any:
        if first_attempt[0]:
            first_attempt[0] = False
            deadline = time.monotonic() + 10
            while cancelled is not None and not cancelled() and time.monotonic() < deadline:
                time.sleep(0.01)
        return original_solve(
            service,
            prepared,
            cancelled=cancelled,
            emergency_seconds=emergency_seconds,
        )

    M12RouteService.solve = injected_first_cancellation  # type: ignore[method-assign]
    thread = start_in_thread(server)
    try:
        return capture(
            f"http://127.0.0.1:{server.port}/",
            lambda: api._future is None or api._future.done(),
        )
    finally:
        M12RouteService.solve = original_solve  # type: ignore[method-assign]
        server.close_service()
        thread.join(timeout=5)
        api.close()


def run(output_dir: Path, *, browser: Path | None = None) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    selected_browser = browser or DRIVER._browser()
    provider_counter = [0]
    source_fingerprints: dict[str, object] = {}
    captures: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="rsm-m12-browser-") as temporary:
        root = Path(temporary)
        for zoom in ZOOMS:
            project, source, before = _fixture_project(root / str(zoom))
            captures[str(zoom)] = _serve(
                project,
                root / f"state-{zoom}.json",
                provider_counter,
                lambda origin, operation_idle, value=zoom: _capture(
                    selected_browser,
                    output_dir / f"zoom-{value}",
                    value,
                    origin,
                    operation_idle,
                ),
            )
            after = _fingerprint(source)
            if before != after:
                raise AssertionError("M12 browser acceptance modified its input source")
            source_fingerprints[str(zoom)] = {"before": before, "after": after}
    if provider_counter[0]:
        raise AssertionError("Provider construction occurred during M12 browser acceptance")
    report = {
        "schema_version": 1,
        "status": "passed",
        "browser": str(selected_browser),
        "origin": "127.0.0.1 ephemeral",
        "navigation_levels": ["route_map", "detail_evidence"],
        "badges": list(BADGES),
        "provider_constructions": provider_counter[0],
        "remote_requests": 0,
        "creator_or_game_executions": 0,
        "source_fingerprints": source_fingerprints,
        "captures": captures,
    }
    (output_dir / "acceptance.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8", newline="\n"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--browser", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.output_dir, browser=arguments.browser), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
