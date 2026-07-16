# ruff: noqa: E501
"""Exercise the M13 Narrative workflow in real Chrome or Edge at 100% and 200%."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from scripts.m13_provider_free_acceptance import SimulatedNarrativeProvider
else:
    try:
        from scripts.m13_provider_free_acceptance import SimulatedNarrativeProvider
    except ModuleNotFoundError:
        from m13_provider_free_acceptance import SimulatedNarrativeProvider

from renpy_story_mapper.m12_service import M12RouteService
from renpy_story_mapper.narrative.authority import load_narrative_authority
from renpy_story_mapper.organization.contracts import OrganizationProvider
from renpy_story_mapper.organization.parallel import RouteScope
from renpy_story_mapper.project import Project, create_ingested_project
from renpy_story_mapper.storage import canonical_json
from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.security import SessionSecurity
from renpy_story_mapper.web.server import LocalWebServer, start_in_thread
from renpy_story_mapper.web.state import UserStateStore

ROOT: Final = Path(__file__).resolve().parents[1]
STATIC: Final = ROOT / "src" / "renpy_story_mapper" / "web" / "static"
FIXTURE: Final = ROOT / "tests" / "fixtures" / "m12" / "route_targets.rpy"
ZOOMS: Final = (100, 200)
SELECTED_MODEL: Final = "browser-selected-runtime-model"
CONSENT_FIELDS: Final = (
    "Provider",
    "Requested / resolved model",
    "Selected scope",
    "Privacy mode",
    "Logical jobs",
    "Estimated provider calls",
    "Estimated tokens",
    "Estimated cost",
    "Hard limits",
    "M12 material",
)


def _browser_driver() -> Any:
    path = Path(__file__).with_name("m10_browser_acceptance.py")
    spec = importlib.util.spec_from_file_location("rsm_m13_browser_driver", path)
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


def _authority_snapshot(path: Path) -> dict[str, object]:
    with Project.open(path) as project:
        authority = load_narrative_authority(project, include_m12=True)
    return {
        "binding": authority.binding.to_dict(),
        "m12_normalized_sha256": hashlib.sha256(
            canonical_json(list(authority.m12_results))
        ).hexdigest(),
        "m12_result_count": len(authority.m12_results),
    }


def _fixture_project(root: Path) -> tuple[Path, Path, dict[str, object]]:
    source = root / "game" / "story.rpy"
    source.parent.mkdir(parents=True)
    source.write_bytes(FIXTURE.read_bytes())
    before = _fingerprint(source)
    project_path = root / "m13-browser.rsmproj"
    with create_ingested_project(project_path, source.parent) as project:
        service = M12RouteService(project)
        destinations = service.destinations(limit=50)["nodes"]
        if not isinstance(destinations, list):
            raise AssertionError("M12 destination catalog is malformed")
        destination = next(
            item
            for item in destinations
            if isinstance(item, Mapping) and item.get("kind") == "generic_scene"
        )
        kind = destination.get("kind")
        target_id = destination.get("target_id")
        if not isinstance(kind, str) or not isinstance(target_id, str):
            raise AssertionError("M12 acceptance destination is malformed")
        outcome = service.solve(service.prepare(kind, target_id))
        if outcome.result is None:
            raise AssertionError("M13 browser fixture did not persist an M12 result")
    return project_path, source, before


def _provider_metrics(
    providers: list[SimulatedNarrativeProvider],
) -> dict[str, int]:
    return {
        "constructions": len(providers),
        "submit_calls": sum(len(provider.call_item_counts) for provider in providers),
        "submitted_items": sum(
            sum(provider.call_item_counts) for provider in providers
        ),
        "status_calls": sum(provider.status_calls for provider in providers),
    }


def _capture(
    browser: Path,
    output: Path,
    zoom: int,
    origin: str,
    metrics: Callable[[], dict[str, int]],
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(
        prefix="rsm-m13-chrome-", ignore_cleanup_errors=True
    ) as temporary:
        process, session = DRIVER._session(browser, zoom, Path(temporary))
        try:
            session.command("Page.navigate", {"url": origin})
            session.wait(
                "document.readyState === 'complete' && !!document.querySelector('.recent-card')"
            )
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait(
                "document.querySelectorAll('.station').length > 0 && document.querySelector('#sceneMapButton').getAttribute('aria-pressed') === 'true' && !document.querySelector('#narrativeToggle').disabled"
            )
            default = session.evaluate(
                "import('./app.js').then(m=>({mode:m.state.mode,narrativeEnabled:m.state.narrativeEnabled,narrativeJobs:m.state.narrativeJobs.length,toggleChecked:document.querySelector('#narrativeToggle').checked,toggleDisabled:document.querySelector('#narrativeToggle').disabled,status:document.querySelector('#narrativeRunStatus').textContent,levelCount:document.querySelectorAll('[data-level]').length,levels:[...document.querySelectorAll('[data-level]')].map(item=>item.dataset.level).sort(),firstTitle:document.querySelector('.station-title')?.textContent||null}))"
            )
            if default != {
                "mode": "scenes",
                "narrativeEnabled": False,
                "narrativeJobs": 0,
                "toggleChecked": False,
                "toggleDisabled": False,
                "status": "Cloud AI is off. Preparing a manifest sends no story material.",
                "levelCount": 2,
                "levels": ["detail_evidence", "route_map"],
                "firstTitle": default["firstTitle"],
            }:
                raise AssertionError(f"M13 was not optional and off by default: {default}")
            if metrics()["submit_calls"]:
                raise AssertionError("M13 transmitted provider input on project open")

            session.evaluate("document.querySelector('#narrativeJobsButton').click()")
            session.wait("document.querySelector('#narrativeDrawer').hidden === false")
            session.evaluate(
                f"(()=>{{const input=document.querySelector('#narrativeModel');input.value={json.dumps(SELECTED_MODEL)};input.dispatchEvent(new Event('input',{{bubbles:true}}));document.querySelector('#narrativeRunForm').requestSubmit();}})()"
            )
            session.wait(
                "import('./app.js').then(m=>document.querySelector('#narrativeConsentDialog').open && !!m.state.narrativePreparation && m.state.narrativeRun?.state==='prepared')",
                timeout=30,
            )
            if metrics()["submit_calls"]:
                raise AssertionError("M13 transmitted provider input before manifest confirmation")
            consent = session.evaluate(
                "import('./app.js').then(m=>{const rows=Object.fromEntries([...document.querySelectorAll('#narrativeConsentFacts dt')].map(term=>[term.textContent,term.nextElementSibling?.textContent||'']));const dialog=document.querySelector('#narrativeConsentDialog');const card=dialog.querySelector('.dialog-card');const rect=dialog.getBoundingClientRect();return {rows,preparation:m.state.narrativePreparation,run:m.state.narrativeRun,layout:{left:rect.left,top:rect.top,right:rect.right,bottom:rect.bottom,width:rect.width,height:rect.height,viewportWidth:innerWidth,viewportHeight:innerHeight,scrollHeight:dialog.scrollHeight,clientHeight:dialog.clientHeight,cardScrollHeight:card.scrollHeight,cardClientHeight:card.clientHeight},confirmDisabled:document.querySelector('#confirmNarrative').disabled};})"
            )
            if tuple(consent["rows"]) != CONSENT_FIELDS:
                raise AssertionError(f"Manifest consent fields changed: {consent['rows']}")
            if SELECTED_MODEL not in consent["rows"]["Requested / resolved model"]:
                raise AssertionError(f"Runtime model identity is missing: {consent['rows']}")
            if consent["rows"]["Privacy mode"] != "Fact only":
                raise AssertionError(f"Fact-only consent was not explicit: {consent['rows']}")
            if consent["rows"]["M12 material"] != "Included":
                raise AssertionError(f"M12 disclosure is missing: {consent['rows']}")
            if consent["confirmDisabled"] or consent["run"]["cloud_enabled"]:
                raise AssertionError(f"Prepared consent enabled cloud transmission early: {consent}")
            consent_layout = consent["layout"]
            if (
                consent_layout["left"] < -1
                or consent_layout["right"] > consent_layout["viewportWidth"] + 1
                or consent_layout["top"] < -1
                or consent_layout["bottom"] > consent_layout["viewportHeight"] + 1
            ):
                raise AssertionError(f"M13 consent escaped the viewport: {consent_layout}")
            consent_shot = output / f"m13-consent-{zoom}.png"
            DRIVER._screenshot(session, consent_shot)

            consent_action = session.evaluate(
                "new Promise(resolve=>{const card=document.querySelector('#narrativeConsentDialog .dialog-card');card.scrollTop=card.scrollHeight;requestAnimationFrame(()=>{const button=document.querySelector('#confirmNarrative');const rect=button.getBoundingClientRect();resolve({left:rect.left,top:rect.top,right:rect.right,bottom:rect.bottom,viewportWidth:innerWidth,viewportHeight:innerHeight,cardScrollTop:card.scrollTop});});})"
            )
            if (
                consent_action["left"] < -1
                or consent_action["right"] > consent_action["viewportWidth"] + 1
                or consent_action["top"] < -1
                or consent_action["bottom"] > consent_action["viewportHeight"] + 1
            ):
                raise AssertionError(
                    f"M13 consent action is unreachable at {zoom}%: {consent_action}"
                )

            session.evaluate("document.querySelector('#confirmNarrative').click()")
            session.wait(
                "import('./app.js').then(m=>m.state.narrativeRun?.state==='succeeded')",
                timeout=90,
            )
            session.wait(
                "import('./app.js').then(m=>m.state.narrativeSnapshot?.coverage?.expected_scene_jobs>0 && m.state.narrativeSnapshot.coverage.published_scene_jobs===m.state.narrativeSnapshot.coverage.expected_scene_jobs)",
                timeout=30,
            )
            first_run_metrics = metrics()
            if first_run_metrics["submit_calls"] < 1 or first_run_metrics["submitted_items"] < 1:
                raise AssertionError("Confirmed M13 browser run made no structured provider calls")
            run_result = session.evaluate(
                "import('./app.js').then(m=>({state:m.state.narrativeRun.state,runId:m.state.narrativeRun.latest_run.run_id,usage:m.state.narrativeRun.latest_run.usage,coverage:m.state.narrativeSnapshot.coverage,status:document.querySelector('#narrativeRunStatus').textContent,jobCount:m.state.narrativeJobs.length}))"
            )
            if run_result["usage"]["provider_calls"] < 1:
                raise AssertionError(f"M13 browser usage did not record provider calls: {run_result}")

            session.evaluate(
                "(()=>{const toggle=document.querySelector('#narrativeToggle');toggle.checked=true;toggle.dispatchEvent(new Event('change',{bubbles:true}));})()"
            )
            session.wait("import('./app.js').then(m=>m.state.narrativeEnabled===true)")
            overlay = session.evaluate(
                "import('./app.js').then(m=>{const node=m.graph.nodes.find(item=>m.state.narrativeByOwner.has(item.scene_id||item.id));if(!node)throw new Error('No published scene artifact is visible');const owner=node.scene_id||node.id;const job=m.state.narrativeByOwner.get(owner);const station=document.querySelector(`[data-element-id=\"${CSS.escape(node.id)}\"]`);return {elementId:node.id,ownerId:owner,artifactId:job.artifact.artifact_id,deterministicTitle:node.deterministic_title||m.state.scenePage.nodes.find(item=>item.id===node.id)?.title||null,narrativeTitle:node.title,renderedTitle:station.querySelector('.station-title').textContent,coverageText:document.querySelector('#coverageSummary').textContent};})"
            )
            if overlay["narrativeTitle"] != overlay["renderedTitle"]:
                raise AssertionError(f"Narrative title was not projected onto the scene map: {overlay}")
            if overlay["narrativeTitle"] == overlay["deterministicTitle"]:
                raise AssertionError(f"Narrative toggle did not visibly change the title: {overlay}")
            if "Narrative 100%" not in overlay["coverageText"]:
                raise AssertionError(f"Narrative coverage is absent from the scene view: {overlay}")

            session.evaluate(
                f"document.querySelector('[data-element-id={json.dumps(overlay['elementId'])}]').click()"
            )
            session.wait(
                "import('./app.js').then(m=>document.documentElement.dataset.activeLevel==='detail_evidence' && !!m.state.detail?.narrative_artifact && !document.querySelector('#interpretationPanel').hidden)"
            )
            detail = session.evaluate(
                "import('./app.js').then(m=>({title:document.querySelector('#detailTitle').textContent,summary:document.querySelector('#detailSummary').textContent,publication:m.state.detail.narrative_artifact.publication,claimClasses:[...document.querySelectorAll('#interpretations .narrative-claim')].map(item=>item.dataset.claimClass),labels:[...document.querySelectorAll('#interpretations .narrative-claim strong')].map(item=>item.textContent),levelCount:document.querySelectorAll('[data-level]').length}))"
            )
            if detail["levelCount"] != 2 or "factual" not in detail["claimClasses"]:
                raise AssertionError(f"Narrative detail changed levels or omitted factual labels: {detail}")
            session.evaluate("document.querySelector('#interpretations .narrative-claim button').click()")
            session.wait("document.querySelectorAll('#interpretations .narrative-citation').length > 0")
            scene_citations = session.evaluate(
                "({count:document.querySelectorAll('#interpretations .narrative-citation').length,labels:[...document.querySelectorAll('#interpretations .narrative-citation strong')].map(item=>item.textContent)})"
            )
            if scene_citations["count"] < 1 or not all(
                label.startswith(("M10", "M11", "M12"))
                for label in scene_citations["labels"]
            ):
                raise AssertionError(f"Scene citations did not resolve owned authority: {scene_citations}")
            session.evaluate("document.querySelector('#detailView').scrollIntoView({block:'start'})")
            session.evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))")
            detail_shot = output / f"m13-narrative-detail-{zoom}.png"
            DRIVER._screenshot(session, detail_shot)

            session.evaluate(
                "document.querySelector('#backToRouteMap').click();if(document.querySelector('#narrativeDrawer').hidden)document.querySelector('#narrativeJobsButton').click()"
            )
            session.wait("document.documentElement.dataset.activeLevel==='route_map' && document.querySelector('#narrativeDrawer').hidden===false")
            plot = session.evaluate(
                "import('./app.js').then(async m=>{const index=m.state.narrativeJobs.findIndex(job=>job.kind==='plot');if(index<0||index>=120)throw new Error('Plot job is outside the bounded drawer');const job=m.state.narrativeJobs[index];const artifact=await m.api.narrativeArtifact(job.artifact.artifact_id);const record=document.querySelectorAll('#narrativeJobList .narrative-job')[index];record.querySelector('button').click();return {index,title:job.artifact.title,artifactId:job.artifact.artifact_id,artifactClaimCount:artifact.claims.length,artifactPublication:artifact.publication};})"
            )
            if plot["artifactClaimCount"] < 1:
                raise AssertionError(f"Published plot artifact has no evidence-linked claim: {plot}")
            try:
                session.wait(
                    f"!!document.querySelectorAll('#narrativeJobList .narrative-job')[{int(plot['index'])}].querySelector('.narrative-claim button')"
                )
            except TimeoutError as error:
                diagnostic = session.evaluate(
                    f"(()=>{{const record=document.querySelectorAll('#narrativeJobList .narrative-job')[{int(plot['index'])}];return {{recordText:record?.textContent||null,buttonTexts:[...(record?.querySelectorAll('button')||[])].map(item=>item.textContent),toast:document.querySelector('#toast').textContent,toastHidden:document.querySelector('#toast').hidden,jobCount:document.querySelectorAll('#narrativeJobList .narrative-job').length}};}})()"
                )
                raise AssertionError(
                    f"Plot artifact did not render in the job drawer: artifact={plot}, ui={diagnostic}"
                ) from error
            session.evaluate(
                f"document.querySelectorAll('#narrativeJobList .narrative-job')[{int(plot['index'])}].querySelector('.narrative-claim button').click()"
            )
            session.wait(
                f"document.querySelectorAll('#narrativeJobList .narrative-job')[{int(plot['index'])}].querySelectorAll('.narrative-citation').length > 0"
            )
            plot_citations = session.evaluate(
                f"(()=>{{const record=document.querySelectorAll('#narrativeJobList .narrative-job')[{int(plot['index'])}];record.scrollIntoView({{block:'start'}});return {{count:record.querySelectorAll('.narrative-citation').length,labels:[...record.querySelectorAll('.narrative-citation strong')].map(item=>item.textContent)}};}})()"
            )
            if plot_citations["count"] < 1:
                raise AssertionError("Lazy plot claim-DAG citations did not reach direct evidence")
            drawer_shot = output / f"m13-job-drawer-{zoom}.png"
            DRIVER._screenshot(session, drawer_shot)

            session.evaluate(
                "document.querySelector('#closeNarrativeDrawer').click();(()=>{const toggle=document.querySelector('#narrativeToggle');toggle.checked=false;toggle.dispatchEvent(new Event('change',{bubbles:true}));})()"
            )
            session.wait("import('./app.js').then(m=>m.state.narrativeEnabled===false)")
            deterministic = session.evaluate(
                f"document.querySelector('[data-element-id={json.dumps(overlay['elementId'])}] .station-title').textContent"
            )
            if deterministic != overlay["deterministicTitle"]:
                raise AssertionError(
                    f"Turning Narrative off did not restore deterministic M11: {deterministic!r}"
                )

            calls_before_replay = metrics()["submit_calls"]
            session.evaluate("document.querySelector('#narrativeJobsButton').click();document.querySelector('#narrativeRunForm').requestSubmit()")
            session.wait(
                "import('./app.js').then(m=>document.querySelector('#narrativeConsentDialog').open && m.state.narrativeRun?.state==='prepared')",
                timeout=30,
            )
            session.evaluate("document.querySelector('#confirmNarrative').click()")
            session.wait(
                f"import('./app.js').then(m=>m.state.narrativeRun?.state==='succeeded' && m.state.narrativeRun.latest_run.run_id!=={json.dumps(run_result['runId'])})",
                timeout=60,
            )
            replay = session.evaluate(
                "import('./app.js').then(m=>({state:m.state.narrativeRun.state,providerCalls:m.state.narrativeRun.latest_run.usage.provider_calls,status:document.querySelector('#narrativeRunStatus').textContent,coverage:m.state.narrativeSnapshot.coverage}))"
            )
            if replay["providerCalls"] != 0 or metrics()["submit_calls"] != calls_before_replay:
                raise AssertionError(f"Exact browser cache replay called the provider: {replay}")

            session.evaluate("new Promise(resolve=>setTimeout(resolve,1200))")

            layout = DRIVER._layout(session)
            request_count, remote, allowed_errors = DRIVER._browser_diagnostics(session)
            return {
                "zoom_percent": zoom,
                "viewport": {
                    "width": DRIVER.VIEWPORTS[zoom][0],
                    "height": DRIVER.VIEWPORTS[zoom][1],
                },
                "default": default,
                "consent": {
                    "rows": consent["rows"],
                    "layout": consent_layout,
                    "action_layout": consent_action,
                    "cloud_enabled_before_confirmation": consent["run"]["cloud_enabled"],
                },
                "first_run": run_result,
                "overlay": overlay,
                "detail": detail,
                "scene_citations": scene_citations,
                "plot": plot,
                "plot_citations": plot_citations,
                "deterministic_title_restored": True,
                "cache_replay": replay,
                "provider_metrics": metrics(),
                "layout": layout,
                "browser_request_count": request_count,
                "remote_requests": len(remote),
                "allowed_browser_errors": allowed_errors,
                "artifacts": [
                    _artifact(consent_shot, output.parent),
                    _artifact(detail_shot, output.parent),
                    _artifact(drawer_shot, output.parent),
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
    providers: list[SimulatedNarrativeProvider],
    capture: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    state = UserStateStore(state_path)
    state.record_project(project)

    def forbidden_organization_provider(_scope: RouteScope) -> OrganizationProvider:
        raise AssertionError("M13 browser acceptance must not construct an M07 provider")

    def m13_provider() -> SimulatedNarrativeProvider:
        provider = SimulatedNarrativeProvider(content_variant="browser-accepted")
        providers.append(provider)
        return provider

    api = ProjectApi(
        _NoDialogs(),
        state_store=state,
        m07_provider_factory=forbidden_organization_provider,
        m13_provider_factory=m13_provider,
    )
    server = LocalWebServer(
        "127.0.0.1",
        0,
        api,
        static_root=STATIC,
        security=SessionSecurity("m13-acceptance-session", "m13-acceptance-csrf"),
    )
    thread = start_in_thread(server)
    try:
        return capture(f"http://127.0.0.1:{server.port}/")
    finally:
        server.close_service()
        thread.join(timeout=5)
        api.close()


def run(output_dir: Path, *, browser: Path | None = None) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    selected_browser = browser or DRIVER._browser()
    static_paths = tuple(
        STATIC / name for name in ("index.html", "app.js", "api.js", "contract.js", "styles.css")
    )
    static_before = {path.name: _fingerprint(path) for path in static_paths}
    source_fingerprints: dict[str, object] = {}
    authority_snapshots: dict[str, object] = {}
    captures: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="rsm-m13-browser-") as temporary:
        root = Path(temporary)
        for zoom in ZOOMS:
            project, source, source_before = _fixture_project(root / str(zoom))
            authority_before = _authority_snapshot(project)
            providers: list[SimulatedNarrativeProvider] = []
            metrics_reader = partial(_provider_metrics, providers)
            capture_one: Callable[[str], dict[str, Any]] = partial(
                _capture,
                selected_browser,
                output_dir / f"zoom-{zoom}",
                zoom,
                metrics=metrics_reader,
            )
            captures[str(zoom)] = _serve(
                project,
                root / f"state-{zoom}.json",
                providers,
                capture_one,
            )
            source_after = _fingerprint(source)
            authority_after = _authority_snapshot(project)
            if source_before != source_after:
                raise AssertionError("M13 browser acceptance modified its input source")
            if authority_before != authority_after:
                raise AssertionError("M13 browser acceptance changed M10, M11, or M12 authority")
            source_fingerprints[str(zoom)] = {
                "before": source_before,
                "after": source_after,
            }
            authority_snapshots[str(zoom)] = {
                "before": authority_before,
                "after": authority_after,
            }
    static_after = {path.name: _fingerprint(path) for path in static_paths}
    if static_before != static_after:
        raise AssertionError("M13 browser acceptance modified packaged web assets")
    report = {
        "schema": "m13-browser-acceptance-v1",
        "status": "passed",
        "browser": str(selected_browser),
        "origin": "127.0.0.1 ephemeral",
        "zooms": list(ZOOMS),
        "navigation_levels": ["route_map", "detail_evidence"],
        "cloud_provider": "structured offline simulator through production boundary",
        "remote_requests": 0,
        "creator_or_game_executions": 0,
        "static_assets": {"before": static_before, "after": static_after},
        "source_fingerprints": source_fingerprints,
        "authority_snapshots": authority_snapshots,
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
    print(
        json.dumps(
            run(arguments.output_dir, browser=arguments.browser),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
