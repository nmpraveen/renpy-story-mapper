# ruff: noqa: E501
"""Real-Chrome evidence for the M15.1 normal-flow Story Map renderer."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.security import SessionSecurity
from renpy_story_mapper.web.server import LocalWebServer, start_in_thread
from renpy_story_mapper.web.state import UserStateStore

ROOT: Final = Path(__file__).resolve().parents[1]
STATIC: Final = ROOT / "src" / "renpy_story_mapper" / "web" / "static"
OUTLINE: Final = ROOT / "tests" / "fixtures" / "m15_1" / "semantic_outline_v2.json"
VIEWPORTS: Final = {"100": (1440, 900, 1), "200": (720, 450, 2), "narrow": (560, 900, 1)}


def _driver() -> Any:
    path = Path(__file__).with_name("m10_browser_acceptance.py")
    spec = importlib.util.spec_from_file_location("rsm_m15_1_browser_driver", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("The packaged Chrome driver could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DRIVER = _driver()


class _NoDialogs:
    def choose_source(self, _kind: str) -> None:
        return None

    def choose_open_project(self) -> None:
        return None

    def choose_save_project(self) -> None:
        return None


def _payload() -> dict[str, object]:
    frozen = json.loads(OUTLINE.read_text(encoding="utf-8"))
    expected = frozen["expected"]
    clusters = expected["ordered_cluster_ids"]
    beats = expected["ordered_beat_ids"]
    choices = expected["choice_ids"]
    nodes = [
        _node(clusters[0], "major_cluster", "Opening", 1),
        _node(beats[0], "beat", "A quiet arrival", 2, clusters[0]),
        _node(beats[1], "beat", "The visit begins", 3, clusters[0]),
        _node(clusters[1], "major_cluster", "The visit", 4),
        _node(beats[2], "beat", "A difficult question", 5, clusters[1]),
        _node(choices[0], "choice", "Stop here or continue?", 6, beats[2], choice_id=choices[0]),
        _node(expected["outer_arm_ids"][0], "choice_arm", "Stop", 7, choices[0], choice_id=choices[0], arm_id=expected["outer_arm_ids"][0]),
        _node(expected["outer_arm_ids"][1], "choice_arm", "Continue", 8, choices[0], choice_id=choices[0], arm_id=expected["outer_arm_ids"][1]),
        _node(choices[1], "choice", "Pause or keep going?", 9, choices[0], choice_id=choices[1], parent_arm_id=expected["outer_arm_ids"][1]),
        _node(expected["inner_arm_ids"][0], "choice_arm", "Pause", 10, choices[1], choice_id=choices[1], arm_id=expected["inner_arm_ids"][0]),
        _node(expected["inner_arm_ids"][1], "choice_arm", "Keep going", 11, choices[1], choice_id=choices[1], arm_id=expected["inner_arm_ids"][1]),
        _node("rejoin_inner", "rejoin", "Proven rejoin", 12, choices[1]),
        _node("rejoin_outer", "rejoin", "Shared proven rejoin", 13, choices[0]),
        _node(beats[3], "beat", "The conversation settles", 14, clusters[1]),
        _node(beats[4], "ending", "End of extracted story", 15, clusters[1]),
    ]
    edge_pairs = [
        (clusters[0], beats[0]), (beats[0], beats[1]), (clusters[1], beats[2]),
        (beats[2], choices[0]), (choices[0], expected["outer_arm_ids"][0]),
        (choices[0], expected["outer_arm_ids"][1]), (expected["outer_arm_ids"][1], choices[1]),
        (choices[1], expected["inner_arm_ids"][0]), (choices[1], expected["inner_arm_ids"][1]),
        (expected["inner_arm_ids"][0], "rejoin_inner"), (expected["inner_arm_ids"][1], "rejoin_inner"),
        (expected["outer_arm_ids"][0], "rejoin_outer"), ("rejoin_inner", "rejoin_outer"),
        ("rejoin_outer", beats[3]), (beats[3], beats[4]),
    ]
    edges = [
        {
            "id": f"edge_{index:02d}", "source_id": source, "target_id": target,
            "kind": "rejoin" if "rejoin" in target else "continuation", "navigation": {"mode": "detail_evidence", "target_id": f"edge_{index:02d}"},
        }
        for index, (source, target) in enumerate(edge_pairs, 1)
    ]
    return {
        "schema": "m15-narrative-map-page-v1", "status": "available", "level": "narrative_map",
        "presentation_levels": ["narrative_map", "detail_evidence"], "build_state": "complete",
        "outline_label": "Synthetic story", "nodes": nodes, "edges": edges, "lanes": [],
        "provider_calls": 0, "m12_requests": 0,
    }


def _node(
    node_id: str,
    kind: str,
    title: str,
    order: int,
    parent: str | None = None,
    **extra: object,
) -> dict[str, object]:
    return {
        "id": node_id, "kind": kind, "title": title, "summary": f"Evidence-linked synthetic {kind.replace('_', ' ')}.",
        "order": order, "parent_node_id": parent, "navigation": {"mode": "detail_evidence", "target_id": node_id}, **extra,
    }


def _png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"Browser artifact is not a PNG: {path}")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def _clip_screenshot(session: Any, path: Path, clip: dict[str, float]) -> tuple[int, int]:
    data = session.command(
        "Page.captureScreenshot",
        {"format": "png", "fromSurface": True, "captureBeyondViewport": True, "clip": {**clip, "scale": 1}},
    )["data"]
    path.write_bytes(base64.b64decode(data))
    return _png_size(path)


def _full_screenshot(session: Any, path: Path) -> tuple[int, int]:
    size = session.command("Page.getLayoutMetrics", {})["cssContentSize"]
    return _clip_screenshot(
        session,
        path,
        {"x": 0, "y": 0, "width": math.ceil(size["width"]), "height": math.ceil(size["height"])},
    )


def _capture(browser: Path, origin: str, output: Path, label: str) -> dict[str, object]:
    width, height, scale = VIEWPORTS[label]
    with tempfile.TemporaryDirectory(prefix=f"rsm-m15-1-{label}-", ignore_cleanup_errors=True) as temporary:
        process, session = DRIVER._session(browser, 200 if scale == 2 else 100, Path(temporary))
        try:
            session.command("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": scale, "mobile": False})
            session.command("Page.navigate", {"url": origin})
            session.wait("document.readyState==='complete'&&!!document.querySelector('#storyMapFlow')")
            payload = json.dumps(_payload())
            session.evaluate(
                "import('./app.js').then(m=>{"
                f"const page={payload};m.state.mode='narrative';m.state.page=page;"
                "document.documentElement.dataset.mapMode='narrative';document.querySelector('#welcomeView').hidden=true;"
                "document.querySelector('#workspaceView').hidden=false;document.querySelector('#routeMapView').hidden=false;"
                "m.api.narrativeMap=async query=>({...page,search:{query,matches:query?page.nodes.filter(item=>(item.title+' '+item.summary).toLocaleLowerCase().includes(query.toLocaleLowerCase())).map(item=>({id:item.id,title:item.title})):[]}});"
                "m.api.narrativeDetail=async id=>({status:'available',level:'detail_evidence',element:{id,kind:'story item',title:id,summary:'Exact synthetic detail.'},predecessor_ids:[],successor_ids:[],member_route_nodes:[],member_route_edges:[],choices:[],requirements:[],effects:[],dialogue:[],narration:[],facts:[],evidence:[{id:'evidence_'+id,kind:'source',payload:{source_text:'Synthetic evidence.'},source:{path:'synthetic/story.rpy',start:{line:1},end:{line:1}},line_basis:'physical_source'}],provider_calls:0,m12_requests:0});"
                "m.renderMap();return true;})"
            )
            session.wait("document.querySelectorAll('#storyMapFlow button[data-element-id]').length>0")
            initial_disclosure = session.evaluate(
                "(()=>{const item=document.querySelectorAll('#storyMapFlow details.story-section')[1];item.querySelector('summary').focus();return item.open;})()"
            )
            session.command("Input.dispatchKeyEvent", {"type": "keyDown", "key": " ", "code": "Space", "windowsVirtualKeyCode": 32})
            session.command("Input.dispatchKeyEvent", {"type": "keyUp", "key": " ", "code": "Space", "windowsVirtualKeyCode": 32})
            session.wait("document.querySelectorAll('#storyMapFlow details.story-section')[1].open")
            disclosure = {"initially_open": initial_disclosure, "opened_by_keyboard": True}
            geometry = session.evaluate(
                "(()=>{const flow=document.querySelector('#storyMapFlow'),fr=flow.getBoundingClientRect();"
                "const buttons=[...flow.querySelectorAll('button[data-element-id]')],arms=[...flow.querySelectorAll('.story-choice-arms')];"
                "const boxes=buttons.map(b=>{const r=b.getBoundingClientRect();return {id:b.dataset.elementId,w:r.width,h:r.height,left:r.left,right:r.right,top:r.top,bottom:r.bottom,position:getComputedStyle(b).position}}).filter(item=>item.w>0&&item.h>0);"
                "const overlaps=[];for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++){const a=boxes[i],b=boxes[j];if(Math.min(a.right,b.right)-Math.max(a.left,b.left)>2&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>2)overlaps.push([a.id,b.id]);}"
                "const contained=arms.every(a=>{const c=a.closest('.story-choice').getBoundingClientRect(),r=a.getBoundingClientRect();return r.left>=c.left&&r.right<=c.right&&r.top>=c.top&&r.bottom<=c.bottom;});"
                "return {flow:{width:fr.width,left:fr.left,right:fr.right},document:{scrollWidth:document.documentElement.scrollWidth,clientWidth:document.documentElement.clientWidth},overlaps,contained,"
                "graphDisplay:getComputedStyle(document.querySelector('#graphSurface')).display,worldTransform:getComputedStyle(document.querySelector('#mapWorld')).transform,"
                "sections:flow.querySelectorAll('.story-section').length,choices:flow.querySelectorAll('.story-choice').length,armCards:flow.querySelectorAll('.story-arm-card').length,rejoins:flow.querySelectorAll('.story-rejoin').length,"
                "armLayouts:arms.map(a=>({columns:getComputedStyle(a).gridTemplateColumns.split(' ').filter(Boolean).length,choiceWidth:a.closest('.story-choice').getBoundingClientRect().width})),boxes,ids:buttons.map(b=>b.dataset.elementId),"
                "nested:!!flow.querySelector('[data-arm-id=outer_continue] .story-choice'),text:flow.textContent};})()"
            )
            expected_ids = {item["id"] for item in _payload()["nodes"]} | {item["id"] for item in _payload()["edges"]}  # type: ignore[index]
            observed_ids = set(geometry["ids"])
            if observed_ids != expected_ids or len(geometry["ids"]) != len(expected_ids):
                raise AssertionError(f"Detail/Evidence mapping is not exhaustive and unique: {expected_ids ^ observed_ids}")
            if geometry["flow"]["width"] > 896.5 or geometry["document"]["scrollWidth"] != geometry["document"]["clientWidth"]:
                raise AssertionError(f"Story Map escaped its bounded normal-flow column: {geometry}")
            if geometry["graphDisplay"] != "none" or geometry["worldTransform"] not in {"none", "matrix(1, 0, 0, 1, 0, 0)"}:
                raise AssertionError(f"Narrative mode exposed a global canvas world: {geometry}")
            if min(item["h"] for item in geometry["boxes"]) < 28 or any(item["position"] == "absolute" for item in geometry["boxes"]):
                raise AssertionError(f"Story controls are not normal-flow usable targets: {geometry}")
            if geometry["overlaps"] or not geometry["contained"]:
                raise AssertionError(f"Story choices overlap or escape containment: {geometry}")
            if (geometry["sections"], geometry["choices"], geometry["armCards"], geometry["rejoins"], geometry["nested"]) != (2, 2, 4, 2, True):
                raise AssertionError(f"Choice ownership or rejoin composition changed: {geometry}")
            if any(
                item["columns"] != (2 if item["choiceWidth"] >= 600 else 1)
                for item in geometry["armLayouts"]
            ):
                raise AssertionError(
                    f"Choice arms do not meet their contained 600 CSS px breakpoint: {geometry['armLayouts']}"
                )
            if any(token in geometry["text"] for token in ("Technical coverage", "Narrative event at line", "menu:")):
                raise AssertionError("Generic technical labels entered narrative mode")
            first_id = session.evaluate(
                "(()=>{const item=document.querySelector('#storyMapFlow button[data-element-id]');item.focus();return item.dataset.elementId;})()"
            )
            session.command("Input.dispatchKeyEvent", {"type": "keyDown", "key": " ", "code": "Space", "windowsVirtualKeyCode": 32})
            session.command("Input.dispatchKeyEvent", {"type": "keyUp", "key": " ", "code": "Space", "windowsVirtualKeyCode": 32})
            session.wait(f"import('./app.js').then(m=>m.state.detail?.element?.id==={json.dumps(first_id)})")
            session.evaluate("document.querySelector('#backToRouteMap').click()")
            keyboard_detail = {"element_id": first_id, "matched": True}
            session.evaluate(
                "(()=>{const input=document.querySelector('#searchInput');input.value='quiet arrival';input.dispatchEvent(new Event('input',{bubbles:true}));})()"
            )
            session.wait("import('./app.js').then(m=>m.state.page?.search?.query==='quiet arrival')")
            search_hidden = session.evaluate("document.querySelectorAll('#storyMapFlow .story-search-hidden').length")
            if not search_hidden:
                raise AssertionError("Real-browser Story Map search did not filter nonmatches")
            session.evaluate(
                "(()=>{const input=document.querySelector('#searchInput');input.value='';input.dispatchEvent(new Event('input',{bubbles:true}));})()"
            )
            session.wait("import('./app.js').then(m=>m.state.page?.search?.query===null)")
            search_restored = session.evaluate("document.querySelectorAll('#storyMapFlow .story-search-hidden').length")
            if search_restored:
                raise AssertionError("Clearing Story Map search did not restore the outline")
            search = {"hidden_nonmatches": search_hidden, "restored_hidden": search_restored}
            detail = session.evaluate(
                "import('./app.js').then(async m=>{const buttons=[...document.querySelectorAll('#storyMapFlow button[data-element-id]')];const failures=[];"
                "for(const button of buttons){button.click();await new Promise(r=>setTimeout(r,0));if(m.state.detail?.element?.id!==button.dataset.elementId||m.state.detail?.evidence?.length!==1)failures.push(button.dataset.elementId);document.querySelector('#backToRouteMap').click();}"
                "return {checked:buttons.length,failures};})"
            )
            if detail["failures"]:
                raise AssertionError(f"Detail/Evidence identity mismatches: {detail}")
            manifest = {
                "expires_at": "2030-01-01T00:00:00Z", "job_count": 2,
                "source_hash": "source_synthetic", "authority_hash": "authority_synthetic",
                "correction_hash": "correction_synthetic", "prompt_hash": "prompt_synthetic",
                "schema_hash": "schema_synthetic", "membership_hash": "membership_synthetic",
                "input_hash": "input_synthetic", "privacy_scope": "synthetic_only",
                "provider": {"requested_model": "gpt-5.6-sol", "resolved_model": "gpt-5.6-sol", "settings": {"model_reasoning_effort": "medium", "fast_mode": False}},
                "limits": {"max_provider_calls": 2, "max_total_tokens": 4096, "timeout_seconds": 120, "max_concurrency": 1},
            }
            session.evaluate(
                "import('./app.js').then(m=>{"
                f"const manifest={json.dumps(manifest)};"
                "m.api.prepareStoryBoundaries=async()=>({...manifest,state:'awaiting_boundary_consent',manifest_id:'boundary_synthetic'});"
                "m.api.startStoryBoundaries=async manifest_id=>({...manifest,state:'boundaries_running',manifest_id});"
                "m.api.storyMapBuildStatus=async()=>{window.__m15StoryPolls=(window.__m15StoryPolls||0)+1;return {...manifest,state:'membership_frozen'};};"
                "m.api.prepareStorySummaries=async()=>({...manifest,state:'awaiting_summary_consent',manifest_id:'summary_synthetic'});"
                "m.state.page.build_state='not_started';m.state.storyMapBuild=null;m.renderMap();"
                "document.querySelector('#buildStoryMap').click();document.querySelector('#prepareBoundaries').click();return true;})"
            )
            session.wait("document.querySelector('#storyMapConsentDialog').open")
            boundary_consent = session.evaluate(
                "(()=>({title:document.querySelector('#storyMapConsentTitle').textContent,text:document.querySelector('#storyMapConsentFacts').textContent,disabled:document.querySelector('#confirmStoryMapStage').disabled}))()"
            )
            reprepare_enabled = session.evaluate("document.querySelector('#cancelStoryMapConsent').click();!document.querySelector('#prepareBoundaries').disabled")
            if not reprepare_enabled:
                raise AssertionError("Cancelling a zero-submit boundary preview prevented re-review")
            session.evaluate("document.querySelector('#prepareBoundaries').click()")
            session.wait("document.querySelector('#storyMapConsentDialog').open")
            session.evaluate("document.querySelector('#confirmStoryMapStage').click()")
            session.wait("import('./app.js').then(m=>window.__m15StoryPolls===1&&m.state.storyMapBuild?.state==='membership_frozen')")
            lifecycle = session.evaluate("import('./app.js').then(m=>({polls:window.__m15StoryPolls,state:m.state.storyMapBuild.state,summaryEnabled:!document.querySelector('#prepareSummaries').disabled}))")
            if lifecycle != {"polls": 1, "state": "membership_frozen", "summaryEnabled": True}:
                raise AssertionError(f"Confirmed boundary build did not poll into the summary stage: {lifecycle}")
            session.evaluate("document.querySelector('#prepareSummaries').click()")
            session.wait("document.querySelector('#storyMapConsentDialog').open")
            summary_consent = session.evaluate(
                "(()=>({title:document.querySelector('#storyMapConsentTitle').textContent,text:document.querySelector('#storyMapConsentFacts').textContent,disabled:document.querySelector('#confirmStoryMapStage').disabled}))()"
            )
            required_consent_text = ("Source", "Authority", "Correction", "Prompt / schema", "Membership", "Provider profile", "Privacy scope", "Resource ceilings")
            if boundary_consent["disabled"] or summary_consent["disabled"] or any(token not in boundary_consent["text"] or token not in summary_consent["text"] for token in required_consent_text):
                raise AssertionError(f"Two-stage consent did not expose every exact bound fact: {boundary_consent}, {summary_consent}")
            if boundary_consent["title"] == summary_consent["title"] or "boundary_synthetic" not in boundary_consent["text"] or "summary_synthetic" not in summary_consent["text"]:
                raise AssertionError("Boundary and frozen-summary consent previews were not distinct")
            consent = {"boundaries": boundary_consent, "summaries": summary_consent, "lifecycle": lifecycle, "cancel_reprepare": reprepare_enabled}
            session.evaluate(
                "import('./app.js').then(m=>{document.querySelector('#cancelStoryMapConsent').click();document.querySelector('#closeStoryMapBuild').click();"
                "m.state.page.build_state='complete';m.state.storyMapBuild=null;m.renderMap();return true;})"
            )
            session.evaluate("window.scrollTo(0,0);document.querySelector('#mapLayout').scrollTop=0")
            map_path = output / f"m15-1-story-map-{label}.png"
            map_size = _full_screenshot(session, map_path)
            session.evaluate(
                "(()=>{document.querySelectorAll('#storyMapFlow details.story-section').forEach(item=>item.open=true);"
                "document.documentElement.style.height='auto';document.documentElement.style.overflow='visible';"
                "document.body.style.height='auto';document.body.style.overflow='visible';"
                "document.querySelector('.app-shell').style.height='auto';document.querySelector('main').style.height='auto';"
                "document.querySelector('#workspaceView').style.height='auto';document.querySelector('#routeMapView').style.height='auto';"
                "document.querySelector('.map-tools').style.position='static';document.querySelector('.map-status').style.position='static';"
                "const layout=document.querySelector('#mapLayout');layout.style.overflow='visible';layout.style.height='auto';return true;})()"
            )
            expanded_path = output / f"m15-1-story-map-expanded-{label}.png"
            expanded_size = _full_screenshot(session, expanded_path)
            if expanded_size[1] <= height * scale:
                raise AssertionError(f"Expanded Story Map is not a full-page capture: {expanded_size}, viewport={height * scale}")
            section_rect = session.evaluate(
                "(()=>{const r=document.querySelectorAll('#storyMapFlow details.story-section')[1].getBoundingClientRect();return {x:r.left+scrollX,y:r.top+scrollY,width:r.width,height:r.height};})()"
            )
            section_path = output / f"m15-1-story-map-section-{label}.png"
            section_size = _clip_screenshot(session, section_path, section_rect)
            session.evaluate("document.querySelector('#storyMapFlow button[data-element-id]').click()")
            session.wait("document.documentElement.dataset.activeLevel==='detail_evidence'")
            detail_path = output / f"m15-1-detail-{label}.png"
            detail_size = _full_screenshot(session, detail_path)
            requests = [event["params"]["request"]["url"] for event in session.events if event.get("method") == "Network.requestWillBeSent"]
            remote = [url for url in requests if urlsplit(url).hostname not in {"127.0.0.1", "localhost"}]
            forbidden = [url for url in requests if "/m12/" in url or "/semantic/start_" in url]
            if remote or forbidden:
                raise AssertionError(f"Normal navigation made forbidden requests: remote={remote}, forbidden={forbidden}")
            return {
                "viewport": {"width": width, "height": height, "device_scale_factor": scale},
                "geometry": geometry, "detail_navigation": detail, "disclosure": disclosure,
                "keyboard_detail": keyboard_detail, "search": search, "consent": consent,
                "requests": {"total": len(requests), "remote": len(remote), "provider_or_m12": len(forbidden)},
                "screenshots": {
                    "map": {"file": map_path.name, "size": map_size, "sha256": hashlib.sha256(map_path.read_bytes()).hexdigest()},
                    "expanded": {"file": expanded_path.name, "size": expanded_size, "sha256": hashlib.sha256(expanded_path.read_bytes()).hexdigest()},
                    "section": {"file": section_path.name, "size": section_size, "sha256": hashlib.sha256(section_path.read_bytes()).hexdigest()},
                    "detail": {"file": detail_path.name, "size": detail_size, "sha256": hashlib.sha256(detail_path.read_bytes()).hexdigest()},
                },
            }
        finally:
            session.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def run(output_dir: Path, *, browser: Path | None = None) -> dict[str, object]:
    output = output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    selected_browser = browser or DRIVER._browser()
    provider_constructions = [0]

    def forbidden_provider(*_args: object, **_kwargs: object) -> object:
        provider_constructions[0] += 1
        raise AssertionError("Browser rendering must not construct a provider")

    with tempfile.TemporaryDirectory(prefix="rsm-m15-1-server-") as temporary:
        api = ProjectApi(_NoDialogs(), state_store=UserStateStore(Path(temporary) / "state.json"), m07_provider_factory=forbidden_provider, m13_provider_factory=forbidden_provider)
        server = LocalWebServer("127.0.0.1", 0, api, static_root=STATIC, security=SessionSecurity("m15-1-session", "m15-1-csrf"))
        thread = start_in_thread(server)
        try:
            origin = f"http://127.0.0.1:{server.port}/"
            captures = {label: _capture(selected_browser, origin, output, label) for label in VIEWPORTS}
        finally:
            server.close_service()
            thread.join(timeout=5)
            api.close()
    if provider_constructions[0]:
        raise AssertionError("A provider was constructed during browser acceptance")
    report = {
        "status": "passed", "fixture": str(OUTLINE.relative_to(ROOT)).replace("\\", "/"),
        "provider_constructions": 0, "m12_solve_or_destination_requests": 0, "remote_requests": 0,
        "captures": captures,
    }
    report_path = output / "m15-1-track-c-browser-acceptance.json"
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
