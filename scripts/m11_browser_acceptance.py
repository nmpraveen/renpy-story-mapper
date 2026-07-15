# ruff: noqa: E501
"""Exercise the packaged M11 scene experience in real Chrome/Edge at 100% and 200%."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

from renpy_story_mapper.organization.contracts import OrganizationProvider
from renpy_story_mapper.organization.parallel import RouteScope
from renpy_story_mapper.project import create_ingested_project
from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.security import SessionSecurity
from renpy_story_mapper.web.server import LocalWebServer, start_in_thread
from renpy_story_mapper.web.state import UserStateStore

ROOT: Final = Path(__file__).resolve().parents[1]
STATIC: Final = ROOT / "src" / "renpy_story_mapper" / "web" / "static"
FIXTURE: Final = ROOT / "tests" / "fixtures" / "m11" / "human_scenes.rpy"
ZOOMS: Final = (100, 200)


def _browser_driver() -> Any:
    path = Path(__file__).with_name("m10_browser_acceptance.py")
    spec = importlib.util.spec_from_file_location("rsm_m11_browser_driver", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("The existing browser CDP driver could not be loaded")
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


def _fixture_project(root: Path) -> Path:
    source = root / "game" / "story.rpy"
    source.parent.mkdir(parents=True)
    padding = "".join(
        f'\nlabel appendix_{index:02d}:\n    scene bg appendix_{index:02d}\n    "Appendix scene {index:02d}."\n    return\n'
        for index in range(45)
    )
    source.write_text(FIXTURE.read_text(encoding="utf-8") + padding, encoding="utf-8")
    project = root / "m11-browser.rsmproj"
    create_ingested_project(project, source.parent).close()
    return project


def _capture(browser: Path, output: Path, zoom: int, origin: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix="rsm-m11-chrome-", ignore_cleanup_errors=True
    ) as temporary:
        process, session = DRIVER._session(browser, zoom, Path(temporary))
        try:
            session.command("Page.navigate", {"url": origin})
            session.wait("document.readyState === 'complete' && !!document.querySelector('.recent-card')")
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait(
                "document.querySelectorAll('.station').length > 0 && document.querySelector('#sceneMapButton').getAttribute('aria-pressed') === 'true'"
            )
            default = session.evaluate(
                "import('./app.js').then(m=>{const sceneNodes=m.graph.nodes.filter(node=>node.presentation_kind==='scene_occurrence'&&!node.occurrence_id); const laneCounts=new Map(); for(const node of sceneNodes) laneCounts.set(node.lane_id,(laneCounts.get(node.lane_id)||0)+1); const sameLaneId=[...laneCounts].sort((left,right)=>right[1]-left[1]||String(left[0]).localeCompare(String(right[0])))[0]?.[0]; const sameLaneScenes=sceneNodes.filter(node=>node.lane_id===sameLaneId); const coordinate=node=>{const position=m.graph.positions.get(node.id); return `${position?.x}:${position?.y}`;}; const coordinates=sameLaneScenes.map(coordinate); const allCoordinates=m.graph.nodes.map(coordinate); const byLane=new Map(); for(const node of m.graph.nodes){const values=byLane.get(node.lane_id)||[]; values.push(node); byLane.set(node.lane_id,values);} const duplicatePairs=[...byLane.values()].flatMap(nodes=>nodes.flatMap((left,index)=>nodes.slice(index+1).filter(right=>coordinate(left)===coordinate(right)).map(right=>[left.id,right.id]))); const cards=[...document.querySelectorAll('.station')]; return {mode:m.state.mode,badge:document.querySelector('#projectBadge').textContent,title:document.querySelector('#mapTitle').textContent,nodes:m.state.page.nodes.length,relationships:m.state.page.edges.length,chapterBands:m.state.page.chapter_bands.length,chapterIndexHidden:document.querySelector('#chapterIndex').hidden,laneCount:document.querySelectorAll('#laneList .line-key').length,persistentCards:m.graph.nodes.filter(node=>node.lane_kind==='persistent').length,status:document.querySelector('#pageStatus').textContent,nextDisabled:document.querySelector('#nextPage').disabled,renderedCards:cards.length,renderedCardIds:cards.map(card=>card.dataset.elementId),loadedNodeIds:m.graph.nodes.map(node=>node.id),sameLaneId,sameLaneCount:sameLaneScenes.length,sameLaneCoordinates:coordinates,distinctGraphPositions:new Set(allCoordinates).size,distinctSameLaneCoordinates:new Set(coordinates).size,duplicateSameLanePairs:duplicatePairs,pageOrderMapped:m.graph.nodes.every(node=>Number.isFinite(node.order)&&Number(node.order)===Number(node.page_order))};})"
            )
            if (
                default["mode"] != "scenes"
                or default["badge"] != "M11 Scenes"
                or default["title"] != "Scenes and chapters"
                or default["nodes"] > 30
                or default["relationships"] > 180
                or default["chapterIndexHidden"]
            ):
                raise AssertionError(f"M11 was not the bounded primary scene view: {default}")
            if (
                default["sameLaneCount"] < 10
                or default["renderedCards"] != default["nodes"]
                or set(default["renderedCardIds"]) != set(default["loadedNodeIds"])
                or default["distinctGraphPositions"] != default["nodes"]
                or default["distinctSameLaneCoordinates"] != default["sameLaneCount"]
                or default["duplicateSameLanePairs"]
                or not default["pageOrderMapped"]
            ):
                raise AssertionError(f"M11 same-lane scene cards overlap or are missing: {default}")
            map_shot = output / f"m11-scenes-{zoom}.png"
            DRIVER._screenshot(session, map_shot)

            route_page = {
                "offset": 0,
                "nodes": default["nodes"],
                "relationships": default["relationships"],
                "persistentCards": default["persistentCards"],
                "nextDisabled": default["nextDisabled"],
            }
            while not route_page["persistentCards"] and not route_page["nextDisabled"]:
                prior_offset = route_page["offset"]
                session.evaluate("document.querySelector('#nextPage').click()")
                session.wait(f"import('./app.js').then(m=>m.state.offset>{prior_offset})")
                route_page = session.evaluate(
                    "import('./app.js').then(m=>({offset:m.state.offset,nodes:m.state.page.nodes.length,relationships:m.state.page.edges.length,persistentCards:m.graph.nodes.filter(node=>node.lane_kind==='persistent').length,nextDisabled:document.querySelector('#nextPage').disabled}))"
                )
                if route_page["nodes"] > 30 or route_page["relationships"] > 180:
                    raise AssertionError(f"M11 pagination exceeded browser bounds: {route_page}")
            if not route_page["persistentCards"]:
                raise AssertionError(f"M11 persistent lane has no rendered scene card: {route_page}")
            session.evaluate(
                "import('./app.js').then(m=>{const node=m.graph.nodes.filter(item=>item.lane_kind==='persistent').sort((left,right)=>left.order-right.order)[0]; const position=m.graph.positions.get(node.id); m.graph.scale=.5; m.graph.offset={x:260-position.x*.5,y:20}; m.graph.transform(); document.querySelector('#mapViewport').scrollIntoView({block:'center'});})"
            )
            route_shot = output / f"m11-scenes-cards-{zoom}.png"
            DRIVER._screenshot(session, route_shot)

            session.evaluate(
                "document.querySelector('#sceneMapButton').click(); const input=document.querySelector('#searchInput'); input.value='Temporary choice'; input.dispatchEvent(new Event('input',{bubbles:true}));"
            )
            session.wait(
                "import('./app.js').then(m=>m.state.mode==='scenes' && m.graph.nodes.some(n=>n.presentation_kind==='temporary_branch'))"
            )
            session.evaluate(
                "Promise.all([import('./app.js'),import('./api.js')]).then(async ([m,{LocalApi}])=>{const api=new LocalApi(); const nodes=m.graph.nodes.filter(n=>n.presentation_kind==='temporary_branch'); const details=await Promise.all(nodes.map(async node=>({node,detail:await api.sceneDetail(node.id)}))); const selected=details.find(item=>item.detail.temporary_branch?.arms?.some(arm=>(arm.scene_ids?.length||0)>=2)); if(!selected) throw new Error('No temporary multi-scene branch is visible'); window.__m11EvidenceBranchId=String(selected.node.id); document.querySelector(`[data-element-id=\"${CSS.escape(selected.node.id)}\"]`).click(); return true;})"
            )
            session.wait(
                "import('./app.js').then(m=>Boolean(window.__m11EvidenceBranchId) && m.state.detail?.element?.id===window.__m11EvidenceBranchId && !document.querySelector('#detailView').hidden)"
            )
            detail = session.evaluate(
                "import('./app.js').then(m=>({level:m.state.detail.level,temporary:m.state.detail.temporary_branch!==null,atoms:m.state.detail.atoms.length,armLocal:m.state.detail.arm_local_scenes.length,armSceneCounts:m.state.detail.temporary_branch.arms.map(arm=>arm.scene_ids.length),evidence:m.state.detail.evidence.length,canonicalEscapes:m.state.detail.canonical_escape_ids.length,interpretationHidden:document.querySelector('#interpretationPanel').hidden,escapeHidden:document.querySelector('#canonicalEscapeButton').hidden}))"
            )
            if (
                detail["level"] != "scene_detail"
                or not detail["temporary"]
                or max(detail["armSceneCounts"], default=0) < 2
                or not detail["canonicalEscapes"]
                or not detail["interpretationHidden"]
                or detail["escapeHidden"]
            ):
                raise AssertionError(f"M11 branch detail omitted deterministic provenance: {detail}")
            detail_shot = output / f"m11-scene-detail-{zoom}.png"
            DRIVER._screenshot(session, detail_shot)

            session.evaluate("document.querySelector('#canonicalEscapeButton').click()")
            session.wait(
                "document.querySelector('#canonicalMapButton').getAttribute('aria-pressed') === 'true' && document.querySelector('#routeMapView').hidden === false"
            )
            canonical_escape = session.evaluate(
                "import('./app.js').then(m=>({mode:m.state.mode,selected:m.state.selectedId,button:document.querySelector('#canonicalMapButton').getAttribute('aria-pressed')}))"
            )
            if canonical_escape["mode"] != "canonical" or canonical_escape["button"] != "true":
                raise AssertionError(f"Canonical escape did not reach M10 authority: {canonical_escape}")
            escape_shot = output / f"m11-canonical-escape-{zoom}.png"
            DRIVER._screenshot(session, escape_shot)

            layout = DRIVER._layout(session)
            request_count, remote, allowed_errors = DRIVER._browser_diagnostics(session)
            return {
                "zoom_percent": zoom,
                "viewport": {
                    "width": DRIVER.VIEWPORTS[zoom][0],
                    "height": DRIVER.VIEWPORTS[zoom][1],
                },
                "default": default,
                "paged": route_page,
                "detail": detail,
                "canonical_escape": canonical_escape,
                "layout": layout,
                "browser_requests": request_count,
                "remote_requests": remote,
                "allowed_browser_errors": allowed_errors,
                "screenshots": [
                    map_shot.name,
                    route_shot.name,
                    detail_shot.name,
                    escape_shot.name,
                ],
            }
        finally:
            session.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except Exception:
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
        raise AssertionError("M11 browser acceptance must not construct a provider")

    api = ProjectApi(_NoDialogs(), state_store=state, m07_provider_factory=forbidden_provider)
    server = LocalWebServer(
        "127.0.0.1",
        0,
        api,
        static_root=STATIC,
        security=SessionSecurity("m11-acceptance-session", "m11-acceptance-csrf"),
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
    output.mkdir(parents=True, exist_ok=False)
    selected_browser = browser or DRIVER._browser()
    provider_counter = [0]
    with tempfile.TemporaryDirectory(prefix="rsm-m11-browser-") as temporary:
        root = Path(temporary)
        project = _fixture_project(root)
        captures = {
            str(zoom): _serve(
                project,
                root / f"state-{zoom}.json",
                provider_counter,
                lambda origin, value=zoom: _capture(selected_browser, output, value, origin),
            )
            for zoom in ZOOMS
        }
    if provider_counter[0]:
        raise AssertionError("Provider construction occurred during M11 browser acceptance")
    report = {
        "schema_version": 1,
        "status": "passed",
        "browser": str(selected_browser),
        "origin": "127.0.0.1 ephemeral",
        "provider_constructions": provider_counter[0],
        "remote_requests": 0,
        "captures": captures,
    }
    (output / "acceptance.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8", newline="\n"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--browser", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.output, browser=arguments.browser), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
