# ruff: noqa: E501
"""Real Chrome/Edge acceptance for the browser-only M08 AI Story Map experience."""

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

from renpy_story_mapper import storage
from renpy_story_mapper.m07_model import CheckpointStatus
from renpy_story_mapper.organization.contracts import (
    InterpretationClaim,
    OrganizationChunkResult,
    OrganizationGroup,
    OrganizationStage,
)
from renpy_story_mapper.organization.persistence import encode_organization_result
from renpy_story_mapper.project import Project, create_ingested_project
from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.security import SessionSecurity
from renpy_story_mapper.web.server import LocalWebServer, start_in_thread
from renpy_story_mapper.web.state import UserStateStore

ROOT: Final = Path(__file__).resolve().parents[1]
STATIC: Final = ROOT / "src" / "renpy_story_mapper" / "web" / "static"
ZOOMS: Final = (100, 200)
VIEWPORTS: Final = {100: (1440, 900), 200: (720, 450)}
CHROME_CANDIDATES: Final = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)


def _m07_harness() -> Any:
    path = Path(__file__).with_name("m07_browser_acceptance.py")
    spec = importlib.util.spec_from_file_location("rsm_m07_browser_harness", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("The existing browser harness could not be loaded")
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


def _fixture_project(root: Path) -> Path:
    source = root / "game" / "story.rpy"
    source.parent.mkdir()
    source.write_text(
        """label start:
    $ trust = 0
    $ courage = 0
    "Avery returns to the old observatory."
    menu:
        "Tell Morgan the truth" if courage >= 0:
            $ trust += 1
            jump confession
        "Search alone":
            jump search

label search:
    "Avery finds Morgan's letter."
    menu:
        "Read it":
            $ courage += 1
        "Leave it sealed":
            $ trust -= 1
    jump reunion

label confession:
    "Morgan hears the confession."
    jump reunion

label reunion:
    "The two paths meet beneath the telescope."
    menu:
        "Stay together" if trust >= 0:
            jump hopeful_ending
        "Walk away":
            jump quiet_ending

label hopeful_ending:
    "They repair the observatory together."
    return

label quiet_ending:
    "Avery leaves before dawn."
    return
"""
        + "\n".join(
            f'''\nlabel pagination_{index:02d}:\n    "Avery records observatory note {index}."\n    {f"jump pagination_{index + 1:02d}" if index < 34 else "return"}\n'''
            for index in range(35)
        ),
        encoding="utf-8",
    )
    destination = root / "m08-browser.rsmproj"
    create_ingested_project(destination, source.parent).close()
    _persist_organization(destination, apply=True, title="The Observatory Choice")
    _persist_organization(destination, apply=False, title="A Revised Observatory Choice")
    return destination


def _generation(project: Project) -> tuple[dict[str, object], str]:
    route = project.payload("m07_route_map", "authoritative")
    if not isinstance(route, dict):
        raise ValueError("fixture route authority is unavailable")
    return route, hashlib.sha256(storage.canonical_json(route)).hexdigest()


def _persist_organization(project_path: Path, *, apply: bool, title: str) -> str:
    with Project.open(project_path) as project:
        route, generation = _generation(project)
        service = project.m07_model_service()
        applied = service.applied_assembly(generation=generation)
        if not apply and applied is not None:
            payload = storage.decode_json(storage.canonical_json(applied.payload))
            if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                raise ValueError("applied fixture assembly is invalid")
            for item in payload["items"]:
                if isinstance(item, dict):
                    item["correction"] = {
                        "title": title,
                        "summary": "Avery chooses honesty or a solitary search before the routes meet under the telescope.",
                    }
                    item["pinned"] = True
            payload_hash = hashlib.sha256(storage.canonical_json(payload)).hexdigest()
            assembly_id = f"assembly_{payload_hash[:20]}"
            connection = project._require_open()
            with storage.transaction(connection):
                connection.execute(
                    """INSERT INTO m07_assemblies(
                       assembly_id,generation,status,payload_json,payload_hash,coverage_json,
                       created_utc,applied_utc) VALUES (?,?,'draft',?,?,?,?,NULL)
                       ON CONFLICT(assembly_id) DO UPDATE SET status='draft',
                       payload_json=excluded.payload_json,payload_hash=excluded.payload_hash,
                       coverage_json=excluded.coverage_json,applied_utc=NULL""",
                    (
                        assembly_id,
                        generation,
                        storage.canonical_json(payload),
                        payload_hash,
                        storage.canonical_json(service.coverage(generation=generation).to_dict()),
                        storage.utc_now(),
                    ),
                )
            return assembly_id
        checkpoints = {item.scope_id: item for item in service.checkpoints(generation=generation)}
        nodes_by_id = {
            str(item["id"]): item for item in route["nodes"] if isinstance(item, dict)
        }
        for scope in route["scopes"]:
            if not isinstance(scope, dict):
                continue
            scope_id = str(scope["id"])
            members = [str(item) for item in scope["node_ids"]]
            checkpoint = checkpoints.get(scope_id)
            if checkpoint is not None and checkpoint.status is CheckpointStatus.PENDING:
                groups: list[OrganizationGroup] = []
                raw_groups: list[dict[str, object]] = []
                ungrouped: list[str] = []
                for index, member in enumerate(members):
                    evidence_ids = tuple(
                        item
                        for item in nodes_by_id[member]["evidence_ids"]
                        if isinstance(item, str)
                    )
                    if not evidence_ids:
                        ungrouped.append(member)
                        continue
                    group_id = f"event_{scope_id}_{index:03d}"
                    claim_text = "This evidence-backed route event advances the observatory story."
                    groups.append(
                        OrganizationGroup(
                            id=group_id,
                            title="The Observatory Choice",
                            summary="Avery chooses honesty or a solitary search before the routes meet under the telescope.",
                            member_ids=(member,),
                            characters=(),
                            importance="turning point",
                            outcomes=("Trust and courage shape the final decision.",),
                            promoted_fact_ids=(),
                            claims=(InterpretationClaim(claim_text, evidence_ids),),
                            warnings=(),
                        )
                    )
                    raw_groups.append(
                        {
                            "id": group_id,
                            "title": "The Observatory Choice",
                            "summary": "Avery chooses honesty or a solitary search before the routes meet under the telescope.",
                            "member_ids": [member],
                            "characters": [],
                            "importance": "turning point",
                            "outcomes": ["Trust and courage shape the final decision."],
                            "promoted_fact_ids": [],
                            "claims": [
                                {"text": claim_text, "evidence_ids": list(evidence_ids)}
                            ],
                            "warnings": [],
                        }
                    )
                result = OrganizationChunkResult(
                    stage=OrganizationStage.EVENTS,
                    groups=tuple(groups),
                    ungrouped_ids=tuple(ungrouped),
                    raw_normalized={
                        "stage": "events",
                        "groups": raw_groups,
                        "ungrouped_ids": ungrouped,
                    },
                )
                service.transition(scope_id, CheckpointStatus.IN_FLIGHT)
                service.transition(
                    scope_id,
                    CheckpointStatus.VALIDATED,
                    result={"organization_result": encode_organization_result(result)},
                )
            service.set_override(
                scope_id,
                generation=generation,
                correction={
                    "title": title,
                    "summary": "Avery chooses honesty or a solitary search before the routes meet under the telescope.",
                },
                pinned=True,
            )
        assembly = service.assemble(generation=generation)
        if apply:
            service.apply(assembly.assembly_id, generation=generation)
        return assembly.assembly_id


def _screenshot(session: Any, path: Path) -> None:
    path.write_bytes(
        base64.b64decode(
            session.command(
                "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
            )["data"]
        )
    )


def _capture(
    browser: Path, output: Path, zoom: int, origin: str, project_path: Path
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="rsm-m08-chrome-", ignore_cleanup_errors=True) as profile:
        profile_path = Path(profile)
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
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        active = profile_path / "DevToolsActivePort"
        deadline = time.monotonic() + 15
        while not active.is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not active.is_file():
            process.terminate()
            raise RuntimeError("Chrome did not publish its DevTools port")
        port = int(active.read_text(encoding="utf-8").splitlines()[0])
        session: Any = None
        try:
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
            session.command("Page.navigate", {"url": origin})
            session.wait("document.readyState === 'complete' && !!document.querySelector('.recent-card')")
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait("document.querySelectorAll('.station').length > 0 && document.querySelector('#aiMapButton').getAttribute('aria-pressed') === 'true'")

            ai_shot = output / f"ai-story-map-{zoom}.png"
            _screenshot(session, ai_shot)
            initial = session.evaluate(
                "({badge:document.querySelector('#projectBadge').textContent,titles:[...document.querySelectorAll('.station-title')].map(x=>x.textContent),ids:[...document.querySelectorAll('.station')].map(x=>x.dataset.elementId),status:document.querySelector('#pageStatus').textContent,items:document.querySelectorAll('[data-element-id]').length})"
            )
            if document_next_disabled := session.evaluate("document.querySelector('#nextPage').disabled"):
                raise AssertionError(f"AI pagination fixture did not expose Next: {document_next_disabled}")
            session.evaluate("document.querySelector('#nextPage').click()")
            session.wait("!document.querySelector('#previousPage').disabled && document.querySelector('#pageStatus').textContent !== " + json.dumps(initial["status"]))
            forward = session.evaluate("({ids:[...document.querySelectorAll('.station')].map(x=>x.dataset.elementId),status:document.querySelector('#pageStatus').textContent,continuations:document.querySelectorAll('.continuation-portal').length})")
            session.evaluate("document.querySelector('#previousPage').click()")
            session.wait("document.querySelector('#pageStatus').textContent === " + json.dumps(initial["status"]))
            restored = session.evaluate("({ids:[...document.querySelectorAll('.station')].map(x=>x.dataset.elementId),status:document.querySelector('#pageStatus').textContent})")
            session.evaluate("document.querySelector('#nextPage').click()")
            session.wait("document.querySelector('#pageStatus').textContent === " + json.dumps(forward["status"]))
            repeated = session.evaluate("({ids:[...document.querySelectorAll('.station')].map(x=>x.dataset.elementId),status:document.querySelector('#pageStatus').textContent,continuations:document.querySelectorAll('.continuation-portal').length})")
            session.evaluate("document.querySelector('#previousPage').click()")
            session.wait("document.querySelector('#pageStatus').textContent === " + json.dumps(initial["status"]))
            if restored != {"ids": initial["ids"], "status": initial["status"]}:
                raise AssertionError(f"AI Previous did not restore the exact initial page: {restored}")
            if repeated != forward or forward["continuations"] < 1:
                raise AssertionError(f"AI Next was not deterministic with a continuation portal: {forward} / {repeated}")
            session.evaluate("document.querySelector('#technicalMapButton').click()")
            session.wait("document.querySelector('#technicalMapButton').getAttribute('aria-pressed') === 'true'")
            technical_shot = output / f"technical-comparison-{zoom}.png"
            _screenshot(session, technical_shot)
            session.evaluate("document.querySelector('#aiMapButton').click()")
            session.wait("document.querySelector('#aiMapButton').getAttribute('aria-pressed') === 'true'")

            keyboard = session.evaluate(
                "(() => { const v=document.querySelector('#mapViewport'); const before=document.querySelector('[aria-selected=\"true\"]')?.dataset.elementId; v.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true})); return {before,after:document.querySelector('[aria-selected=\"true\"]')?.dataset.elementId}; })()"
            )
            session.evaluate("document.querySelector('#selectVisibleNodes').click()")
            session.wait("document.querySelector('#scopePreview').textContent.includes('authority')")
            preview = session.evaluate("document.querySelector('#scopePreview').textContent")
            session.evaluate("document.querySelector('#organizeButton').click()")
            session.wait("document.querySelector('#consentDialog').open")
            consent_shot = output / f"exact-consent-{zoom}.png"
            _screenshot(session, consent_shot)
            consent = session.evaluate(
                "({text:document.querySelector('#consentFacts').textContent,confirm:document.querySelector('#confirmOrganization').textContent})"
            )
            session.evaluate("document.querySelector('#consentDialog').close()")

            # Exercise cancel and resume without starting a provider. The test deliberately exposes
            # the controls while retaining the exact provider-free preview prepared above.
            session.evaluate("document.querySelector('#cancelOrganization').hidden=false; document.querySelector('#cancelOrganization').click()")
            session.wait("[...performance.getEntriesByType('resource')].some(x=>x.name.endsWith('/api/v1/m07/organization/cancel'))")
            session.evaluate("document.querySelector('#resumeOrganization').hidden=false; document.querySelector('#resumeOrganization').click()")
            session.wait("document.querySelector('#consentDialog').open")
            session.evaluate("document.querySelector('#consentDialog').close()")

            session.wait("!document.querySelector('#reviewPartial').hidden")
            session.evaluate("document.querySelector('#reviewPartial').click()")
            session.wait("document.querySelector('#reviewDialog').open")
            review_shot = output / f"review-apply-{zoom}.png"
            _screenshot(session, review_shot)
            session.evaluate("document.querySelector('#applyAssembly').click()")
            session.wait("!document.querySelector('#reviewDialog').open && document.querySelector('#aiMapButton').getAttribute('aria-pressed') === 'true'")

            discarded_draft_id = _persist_organization(
                project_path, apply=False, title="Discarded Browser Revision"
            )
            with Project.open(project_path) as inspected:
                _route, inspected_generation = _generation(inspected)
                inspected_draft = inspected.m07_model_service().current_draft(
                    generation=inspected_generation
                )
                if inspected_draft is None or inspected_draft.assembly_id != discarded_draft_id:
                    raise AssertionError("The persisted discard draft was not durable")
            session.evaluate("import('./app.js').then(m=>m.loadOrganization())")
            try:
                session.wait("!document.querySelector('#reviewPartial').hidden", timeout=5)
            except TimeoutError as exc:
                status = session.evaluate("import('./app.js').then(m=>m.state.organization)")
                raise AssertionError(f"Persisted discard draft was not reviewable: {status}") from exc
            session.evaluate("document.querySelector('#reviewPartial').click()")
            session.wait("document.querySelector('#reviewDialog').open")
            session.evaluate("document.querySelector('#discardAssembly').click()")
            session.wait("!document.querySelector('#reviewDialog').open")

            session.evaluate(
                "import('./app.js').then(({graph}) => { const node=graph.nodes.find(item=>Number(item.evidence_count)>0); if(!node) throw new Error('No evidence-backed AI event is visible'); document.querySelector(`[data-element-id=\"${node.id}\"]`).click(); })"
            )
            session.wait("!document.querySelector('#detailView').hidden && document.querySelectorAll('[data-evidence-id]').length > 0")
            detail_shot = output / f"detail-evidence-{zoom}.png"
            _screenshot(session, detail_shot)
            detail = session.evaluate(
                "({evidence:document.querySelectorAll('[data-evidence-id]').length,claims:document.querySelectorAll('.interpretation.claim').length,members:document.querySelectorAll('.member-node,.member-edge').length,sourceLines:[...document.querySelectorAll('.source-line')].map(x=>x.textContent)})"
            )

            layout = session.evaluate(
                "(() => { const vw=document.documentElement.clientWidth; const offenders=[...document.body.querySelectorAll('*')].filter(x=>!x.closest('#mapViewport')&&!x.closest('dialog')&&x.getBoundingClientRect().right>vw+1).map(x=>x.id||x.className).slice(0,10); return {scrollWidth:document.documentElement.scrollWidth,clientWidth:vw,offenders}; })()"
            )
            requests = [
                event["params"]["request"]
                for event in session.events
                if event.get("method") == "Network.requestWillBeSent"
            ]
            remote = [
                item["url"]
                for item in requests
                if urlsplit(item["url"]).hostname not in {"127.0.0.1", "localhost"}
            ]
            start_requests = [
                item for item in requests if item["url"].endswith("/api/v1/m07/organization/start")
            ]
            errors = [
                event
                for event in session.events
                if event.get("method") == "Runtime.exceptionThrown"
                or (
                    event.get("method") == "Log.entryAdded"
                    and "frame-ancestors"
                    not in str(event.get("params", {}).get("entry", {}).get("text", ""))
                    and not str(event.get("params", {}).get("entry", {}).get("url", "")).endswith("/favicon.ico")
                )
            ]
            if remote:
                raise AssertionError(f"Remote browser requests observed: {remote}")
            if start_requests:
                raise AssertionError("The non-live browser acceptance unexpectedly started a provider run")
            if errors:
                raise AssertionError(f"Browser errors observed: {errors}")
            if keyboard["before"] == keyboard["after"]:
                raise AssertionError("Keyboard navigation did not move map selection")
            if initial["items"] > 240:
                raise AssertionError("Initial AI Story Map exceeded the 240-item rendering boundary")
            if layout["offenders"]:
                raise AssertionError(f"Layout overflow escaped the map pan surface: {layout}")
            if not all("source unavailable" not in line for line in detail["sourceLines"]):
                raise AssertionError(f"Qualified source evidence was not rendered: {detail}")
            required_consent = (
                "gpt-5.6-luna",
                "high reasoning",
                "fast mode off",
                "Authority hash",
                "Selection hash",
                "Recovered-source acknowledgement",
                "Time budgets",
                "Token budgets",
                "Call budget",
            )
            if any(item not in consent["text"] for item in required_consent):
                raise AssertionError(f"Consent summary is incomplete: {consent}")
            return {
                "zoom_percent": zoom,
                "viewport": {"width": width, "height": height},
                "default_view": initial["badge"],
                "human_titles": initial["titles"],
                "rendered_items": initial["items"],
                "pagination": {"initial": initial["status"], "forward": forward, "restored": restored},
                "keyboard_navigation": keyboard,
                "provider_free_preview": preview,
                "consent_complete": True,
                "review_apply_discard": True,
                "cancel_resume": True,
                "detail": detail,
                "layout": layout,
                "request_count": len(requests),
                "remote_requests": 0,
                "provider_start_requests": 0,
                "screenshots": {
                    path.stem: {"file": path.name, "sha256": _hash(path)}
                    for path in (ai_shot, technical_shot, consent_shot, review_shot, detail_shot)
                },
            }
        finally:
            if session is not None:
                session.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def run(output: Path, *, browser: Path | None = None) -> dict[str, Any]:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    provider_constructions = 0
    with tempfile.TemporaryDirectory(prefix="rsm-m08-browser-") as temporary:
        root = Path(temporary)
        project = _fixture_project(root)
        state = UserStateStore(root / "web-state.json")
        state.record_project(project)

        def forbidden_provider(_scope: object) -> object:
            nonlocal provider_constructions
            provider_constructions += 1
            raise AssertionError("M08 non-live browser acceptance must not construct a provider")

        api = ProjectApi(_NoDialogs(), state_store=state, m07_provider_factory=forbidden_provider)
        server = LocalWebServer(
            "127.0.0.1",
            0,
            api,
            static_root=STATIC,
            security=SessionSecurity("m08-acceptance-session", "m08-acceptance-csrf"),
        )
        thread = start_in_thread(server)
        try:
            origin = f"http://127.0.0.1:{server.port}/"
            selected_browser = browser or _browser()
            captures: dict[str, Any] = {}
            for index, zoom in enumerate(ZOOMS):
                if index:
                    _persist_organization(
                        project,
                        apply=False,
                        title=f"A Revised Observatory Choice {zoom}",
                    )
                captures[str(zoom)] = _capture(
                    selected_browser, output, zoom, origin, project
                )
        finally:
            server.close_service()
            thread.join(timeout=5)
    if provider_constructions:
        raise AssertionError("Provider construction occurred during M08 browser acceptance")
    result = {
        "origin": "127.0.0.1 ephemeral",
        "server": "LocalWebServer",
        "api": "ProjectApi",
        "project": "generated temporary SQLite project",
        "organization": "persisted deterministic mock assembly",
        "provider_constructions": 0,
        "provider_start_requests": 0,
        "remote_requests": 0,
        "captures": captures,
    }
    (output / "m08-browser-acceptance.json").write_text(
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
