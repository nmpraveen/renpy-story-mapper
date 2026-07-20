# ruff: noqa: E501
"""Real Chrome Track C acceptance at 100% and 200% with sanitized inputs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit
from urllib.request import urlopen

from renpy_story_mapper.project import create_ingested_project
from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.security import SessionSecurity
from renpy_story_mapper.web.server import LocalWebServer, start_in_thread
from renpy_story_mapper.web.state import UserStateStore

ROOT: Final = Path(__file__).resolve().parents[1]
STATIC: Final = ROOT / "src" / "renpy_story_mapper" / "web" / "static"
FIXTURE: Final = ROOT / "tests" / "fixtures" / "m06" / "control_regions.rpy"
ZOOMS: Final = (100, 200)
FORBIDDEN_NORMAL_ROUTES: Final = (
    "/api/v1/m12/destinations",
    "/api/v1/m12/solve",
    "/api/v1/m07/organization/prepare",
    "/api/v1/m07/organization/start",
    "/api/v1/m13/prepare",
    "/api/v1/m13/start",
)


def _driver() -> Any:
    path = Path(__file__).with_name("m10_browser_acceptance.py")
    spec = importlib.util.spec_from_file_location("rsm_m15_browser_driver", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("The packaged real-browser CDP driver could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DRIVER = _driver()


class _NoDialogs:
    def choose_source(self, _kind: str) -> Path | None:
        return None

    def choose_open_project(self) -> Path | None:
        return None

    def choose_save_project(self) -> Path | None:
        return None


def _fixture_project(root: Path) -> tuple[Path, Path, str]:
    source = root / "game" / "story.rpy"
    source.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURE, source)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    project_path = root / "m15-track-c-browser.rsmproj"
    with create_ingested_project(project_path, source.parent):
        pass
    return project_path, source, source_hash


def _requests(session: Any) -> list[str]:
    return [
        event["params"]["request"]["url"]
        for event in session.events
        if event.get("method") == "Network.requestWillBeSent"
    ]


def _assert_normal_requests(session: Any) -> dict[str, object]:
    requests = _requests(session)
    paths = [urlsplit(value).path for value in requests]
    forbidden = [path for path in paths if path in FORBIDDEN_NORMAL_ROUTES]
    remote = [
        value
        for value in requests
        if urlsplit(value).hostname not in {"127.0.0.1", "localhost"}
    ]
    if forbidden:
        raise AssertionError(f"Retired/provider routes were requested: {forbidden}")
    if remote:
        raise AssertionError(f"Remote browser requests were observed: {remote}")
    return {
        "request_count": len(requests),
        "forbidden_requests": forbidden,
        "remote_requests": remote,
        "m12_requests": sum(path.startswith("/api/v1/m12/") for path in paths),
        "provider_start_requests": sum(path in FORBIDDEN_NORMAL_ROUTES[2:] for path in paths),
    }


def _geometry(session: Any) -> dict[str, object]:
    serialized = session.evaluate(
        """import('./app.js').then(m => {
          const stations=[...document.querySelectorAll('.station')];
          const boxes=stations.map(node=>({id:node.dataset.elementId,kind:node.dataset.kind,rect:node.getBoundingClientRect()}));
          const overlaps=[];
          for(let i=0;i<boxes.length;i++) for(let j=i+1;j<boxes.length;j++) {
            const a=boxes[i].rect,b=boxes[j].rect;
            if(Math.min(a.right,b.right)-Math.max(a.left,b.left)>4&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>4) overlaps.push([boxes[i].id,boxes[j].id]);
          }
          return JSON.stringify({
            stations:stations.length,
            clusters:document.querySelectorAll('.event-cluster-frame').length,
            choiceArms:stations.filter(node=>node.dataset.kind==='choice_arm').length,
            rejoins:stations.filter(node=>node.dataset.kind==='rejoin').length,
            overlaps,
            worldWidth:document.querySelector('#mapWorld').scrollWidth,
            worldHeight:document.querySelector('#mapWorld').scrollHeight,
            viewportWidth:document.querySelector('#mapViewport').clientWidth,
            viewportHeight:document.querySelector('#mapViewport').clientHeight,
            edgePositions:m.graph.edgePositions.size,
            finiteEdges:[...m.graph.edgePositions.values()].filter(v=>[v.source.x,v.source.y,v.target.x,v.target.y].every(Number.isFinite)).length,
            serverEdges:m.state.page.edges.length,
            technicalNodes:stations.filter(node=>node.dataset.kind==='technical_coverage').length,
            scale:m.graph.scale,
          });
        })"""
    )
    result = json.loads(serialized)
    if not isinstance(result, dict) or "overlaps" not in result:
        raise AssertionError(f"Narrative Map geometry probe failed: {result!r}")
    if result["overlaps"]:
        raise AssertionError(f"Narrative Map cards overlap: {result['overlaps']}")
    if not result["clusters"] or not result["choiceArms"] or not result["rejoins"]:
        raise AssertionError(f"Nested Track C geometry was not rendered: {result}")
    if result["edgePositions"] != result["finiteEdges"]:
        raise AssertionError(f"A Narrative Map connector was severed: {result}")
    if result["edgePositions"] != result["serverEdges"]:
        raise AssertionError(f"A server-projected Narrative Map connector disappeared: {result}")
    if not result["technicalNodes"]:
        raise AssertionError(f"Technical Narrative Map coverage was not delivered: {result}")
    return result


def _capture(browser: Path, output: Path, zoom: int, origin: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="rsm-m15-chrome-", ignore_cleanup_errors=True) as temporary:
        process, session = DRIVER._session(browser, zoom, Path(temporary))
        try:
            session.command("Page.navigate", {"url": origin})
            session.wait("document.readyState==='complete'&&!!document.querySelector('.recent-card')")
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait("import('./app.js').then(m=>m.state.mode==='narrative'&&document.querySelectorAll('.station').length>0)")
            normal = session.evaluate(
                "import('./app.js').then(m=>({mode:m.state.mode,badge:document.querySelector('#projectBadge').textContent,"
                "routePanel:!!document.querySelector('#routePanel'),solveRoute:!!document.querySelector('#solveRoute'),"
                "organization:!!document.querySelector('#organizationPanel'),mapNodes:m.state.page.nodes.length,"
                "mapEdges:m.state.page.edges.length,selected:m.state.selectedId,level:document.documentElement.dataset.activeLevel}))"
            )
            if normal["mode"] != "narrative" or normal["badge"] != "Narrative Map":
                raise AssertionError(f"Narrative Map was not the default browser journey: {normal}")
            if normal["routePanel"] or normal["solveRoute"] or normal["organization"]:
                raise AssertionError(f"A retired visible surface remains: {normal}")

            technical = session.evaluate(
                "import('./app.js').then(m=>{const toggle=document.querySelector('#technicalToggle');"
                "const count=()=>document.querySelectorAll('.station[data-kind=technical_coverage]').length;"
                "const initial=count();toggle.checked=true;toggle.dispatchEvent(new Event('change',{bubbles:true}));"
                "const before=count();toggle.checked=false;toggle.dispatchEvent(new Event('change',{bubbles:true}));"
                "const hidden=count();toggle.checked=true;toggle.dispatchEvent(new Event('change',{bubbles:true}));"
                "return {initial,before,hidden,restored:count(),server:m.state.page.nodes.filter(n=>n.kind==='technical_coverage').length};})"
            )
            if not technical["before"] or technical["hidden"] or technical["restored"] != technical["before"]:
                raise AssertionError(f"Technical coverage control did not change the visible map: {technical}")

            geometry = _geometry(session)
            layout = DRIVER._layout(session)
            if geometry["scale"] < 0.8:
                raise AssertionError(f"The default Narrative Map is not readable at normal scale: {geometry}")

            session.evaluate("document.querySelector('#fitMap').click()")
            fitted = session.evaluate(
                "import('./app.js').then(m=>{const v=document.querySelector('#mapViewport');"
                "return {scale:m.graph.scale,bounds:m.graph.bounds,viewport:{width:v.clientWidth,height:v.clientHeight},"
                "scaled:{width:m.graph.bounds.width*m.graph.scale,height:m.graph.bounds.height*m.graph.scale}};})"
            )
            if fitted["scaled"]["width"] > fitted["viewport"]["width"] - 24 or fitted["scaled"]["height"] > fitted["viewport"]["height"] - 24:
                raise AssertionError(f"Fit did not contain the whole Narrative Map: {fitted}")
            restored_scale = session.evaluate(
                "import('./app.js').then(m=>{while(m.graph.scale<.8)m.graph.zoomBy(.1);"
                "document.querySelector('#zoomValue').textContent=`${Math.round(m.graph.scale*100)}%`;return m.graph.scale;})"
            )
            if restored_scale < 0.8:
                raise AssertionError(f"Narrative Map readability could not be restored after Fit: {restored_scale}")

            pan_before = session.evaluate("import('./app.js').then(m=>({x:m.graph.offset.x,y:m.graph.offset.y}))")
            session.evaluate(
                "(()=>{const v=document.querySelector('#mapViewport');"
                "const r=v.getBoundingClientRect();"
                "Object.defineProperty(v,'setPointerCapture',{value:()=>{},configurable:true});"
                "v.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:7,pointerType:'mouse',button:0,buttons:1,clientX:r.left+8,clientY:r.top+8}));"
                "v.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,pointerId:7,pointerType:'mouse',button:0,buttons:1,clientX:r.left+63,clientY:r.top+43}));"
                "v.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:7,pointerType:'mouse',button:0,buttons:0,clientX:r.left+63,clientY:r.top+43}));"
                "delete v.setPointerCapture;})()"
            )
            pan = session.evaluate("import('./app.js').then(m=>({x:m.graph.offset.x,y:m.graph.offset.y}))")
            if pan == pan_before:
                raise AssertionError(f"Pointer pan did not move the Narrative Map: {pan}")

            session.evaluate("document.querySelector('#zoomIn').click();document.querySelector('#zoomOut').click()")
            selected_before = session.evaluate("import('./app.js').then(m=>m.state.selectedId)")
            title = session.evaluate("document.querySelector('.station[aria-selected=true] .station-title').textContent")
            session.evaluate(
                f"(()=>{{const input=document.querySelector('#searchInput');input.value={json.dumps(title)};input.dispatchEvent(new Event('input',{{bubbles:true}}));}})()"
            )
            session.wait("import('./app.js').then(m=>m.state.page.search?.query===document.querySelector('#searchInput').value)")
            selected_after = session.evaluate("import('./app.js').then(m=>m.state.selectedId)")
            if selected_before != selected_after:
                raise AssertionError(f"Search did not preserve the selected element: {selected_before} -> {selected_after}")

            session.evaluate("document.querySelector('.station[aria-selected=true]').focus()")
            session.command("Input.dispatchKeyEvent", {"type": "keyDown", "key": "ArrowRight", "code": "ArrowRight"})
            session.command("Input.dispatchKeyEvent", {"type": "keyUp", "key": "ArrowRight", "code": "ArrowRight"})
            keyboard_selected = session.evaluate("import('./app.js').then(m=>m.state.selectedId)")
            session.evaluate("document.querySelector('#mapViewport').scrollIntoView({block:'center'});document.querySelector('#toast').hidden=true")
            map_shot = output / f"m15-track-c-map-{zoom}.png"
            DRIVER._screenshot(session, map_shot)
            session.command("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter"})
            session.command("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter"})
            session.wait("document.documentElement.dataset.activeLevel==='detail_evidence'&&document.querySelectorAll('.evidence-record').length>0")
            detail = session.evaluate("import('./app.js').then(m=>({id:m.state.detail.element.id,evidence:m.state.detail.evidence.length,providerCalls:m.state.detail.provider_calls,m12Requests:m.state.detail.m12_requests}))")
            detail_shot = output / f"m15-track-c-detail-{zoom}.png"
            DRIVER._screenshot(session, detail_shot)
            session.command("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape"})
            session.command("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "code": "Escape"})
            session.wait("document.documentElement.dataset.activeLevel==='route_map'")

            request_evidence = _assert_normal_requests(session)
            DRIVER._browser_diagnostics(session)
            return {
                "zoom_percent": zoom,
                "default": normal,
                "geometry": geometry,
                "technical_toggle": technical,
                "fit": fitted,
                "restored_scale": restored_scale,
                "layout": layout,
                "pan_offset": pan,
                "search_selection": {"before": selected_before, "after": selected_after},
                "keyboard_selection": keyboard_selected,
                "detail": detail,
                "requests": request_evidence,
                "screenshots": {
                    "map": {"file": map_shot.name, "sha256": hashlib.sha256(map_shot.read_bytes()).hexdigest()},
                    "detail": {"file": detail_shot.name, "sha256": hashlib.sha256(detail_shot.read_bytes()).hexdigest()},
                },
            }
        finally:
            session.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def _serve(project: Path, state_path: Path, provider_counter: list[int], capture: Any) -> Any:
    state = UserStateStore(state_path)
    state.record_project(project)

    def forbidden_provider(*_args: object, **_kwargs: object) -> object:
        provider_counter[0] += 1
        raise AssertionError("Track C browser journeys must not construct a provider")

    api = ProjectApi(
        _NoDialogs(),
        state_store=state,
        m07_provider_factory=forbidden_provider,
        m13_provider_factory=forbidden_provider,
    )
    server = LocalWebServer(
        "127.0.0.1",
        0,
        api,
        static_root=STATIC,
        security=SessionSecurity("m15-acceptance-session", "m15-acceptance-csrf"),
    )
    thread = start_in_thread(server)
    try:
        origin = f"http://127.0.0.1:{server.port}/"
        with urlopen(origin, timeout=5) as response:
            csp = response.headers.get("Content-Security-Policy", "")
        if "default-src 'self'" not in csp or "connect-src 'self'" not in csp:
            raise AssertionError(f"Packaged CSP is incomplete: {csp}")
        return capture(origin), csp
    finally:
        server.close_service()
        thread.join(timeout=5)
        api.close()


def run(output_dir: Path, *, browser: Path | None = None) -> dict[str, object]:
    output = output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    selected_browser = browser or DRIVER._browser()
    provider_counter = [0]
    captures: dict[str, object] = {}
    policies: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="rsm-m15-browser-") as temporary:
        root = Path(temporary)
        project, source, source_hash = _fixture_project(root)
        for zoom in ZOOMS:
            capture, csp = _serve(
                project,
                root / f"state-{zoom}.json",
                provider_counter,
                lambda origin, value=zoom: _capture(selected_browser, output, value, origin),
            )
            captures[str(zoom)] = capture
            policies[str(zoom)] = csp
        if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
            raise AssertionError("The sanitized browser fixture changed during acceptance")
    if provider_counter[0]:
        raise AssertionError("Provider construction occurred during Track C acceptance")
    report = {
        "status": "passed",
        "origin": "127.0.0.1 ephemeral",
        "server": "LocalWebServer",
        "api": "ProjectApi",
        "input": "sanitized tests/fixtures/m06/control_regions.rpy",
        "zooms": list(ZOOMS),
        "provider_constructions": provider_counter[0],
        "remote_requests": 0,
        "m12_solve_or_destination_requests": 0,
        "csp": policies,
        "captures": captures,
    }
    report_path = output / "m15-track-c-browser-acceptance.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--browser", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.output_dir, browser=arguments.browser), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
