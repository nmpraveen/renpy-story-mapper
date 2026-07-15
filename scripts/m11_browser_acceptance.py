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
                "import('./app.js').then(m=>({mode:m.state.mode,badge:document.querySelector('#projectBadge').textContent,title:document.querySelector('#mapTitle').textContent,nodes:m.state.page.nodes.length,relationships:m.state.page.edges.length,chapterBands:m.state.page.chapter_bands.length,chapterIndexHidden:document.querySelector('#chapterIndex').hidden,laneCount:document.querySelectorAll('#laneList .line-key').length,status:document.querySelector('#pageStatus').textContent,nextDisabled:document.querySelector('#nextPage').disabled}))"
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
            map_shot = output / f"m11-scenes-{zoom}.png"
            DRIVER._screenshot(session, map_shot)

            if not default["nextDisabled"]:
                session.evaluate("document.querySelector('#nextPage').click()")
                session.wait("import('./app.js').then(m=>m.state.offset>=30)")
                paged = session.evaluate(
                    "import('./app.js').then(m=>({offset:m.state.offset,nodes:m.state.page.nodes.length,relationships:m.state.page.edges.length}))"
                )
                if paged["nodes"] > 30 or paged["relationships"] > 180:
                    raise AssertionError(f"M11 pagination exceeded browser bounds: {paged}")
            else:
                paged = {"offset": 0, "nodes": default["nodes"], "relationships": default["relationships"]}

            session.evaluate(
                "document.querySelector('#sceneMapButton').click(); const input=document.querySelector('#searchInput'); input.value='Temporary choice'; input.dispatchEvent(new Event('input',{bubbles:true}));"
            )
            session.wait(
                "import('./app.js').then(m=>m.state.mode==='scenes' && m.graph.nodes.some(n=>n.presentation_kind==='temporary_branch'))"
            )
            branch_id = session.evaluate(
                "import('./app.js').then(m=>{const node=m.graph.nodes.find(n=>n.presentation_kind==='temporary_branch'); document.querySelector(`[data-element-id=\"${CSS.escape(node.id)}\"]`).click(); return node.id;})"
            )
            session.wait(
                f"import('./app.js').then(m=>m.state.detail?.element?.id==={json.dumps(branch_id)} && !document.querySelector('#detailView').hidden)"
            )
            detail = session.evaluate(
                "import('./app.js').then(m=>({level:m.state.detail.level,temporary:m.state.detail.temporary_branch!==null,atoms:m.state.detail.atoms.length,armLocal:m.state.detail.arm_local_scenes.length,evidence:m.state.detail.evidence.length,canonicalEscapes:m.state.detail.canonical_escape_ids.length,interpretationHidden:document.querySelector('#interpretationPanel').hidden,escapeHidden:document.querySelector('#canonicalEscapeButton').hidden}))"
            )
            if (
                detail["level"] != "scene_detail"
                or not detail["temporary"]
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
                "paged": paged,
                "detail": detail,
                "canonical_escape": canonical_escape,
                "layout": layout,
                "browser_requests": request_count,
                "remote_requests": remote,
                "allowed_browser_errors": allowed_errors,
                "screenshots": [map_shot.name, detail_shot.name, escape_shot.name],
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
