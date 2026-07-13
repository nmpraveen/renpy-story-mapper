from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "renpy_story_mapper" / "web" / "static"
HARNESS = ROOT / "scripts" / "m07_browser_acceptance.py"


def _text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _assets() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(STATIC.iterdir())
        if path.suffix in {".html", ".js", ".css", ".md"}
    )


def test_two_levels_and_production_local_api_only() -> None:
    html = _text("index.html")
    app = _text("app.js")
    assert 'data-level="route_map"' in html
    assert 'data-level="detail_evidence"' in html
    assert "Back to Route Map" in html
    assert "new LocalApi()" in app
    assert "MockApi" not in app
    assert not (STATIC / "mock-api.js").exists()
    assert not re.search(r"\bLevel\s*[123]\b", _assets(), re.IGNORECASE)


def test_arbitrary_lanes_and_truthful_route_geometry() -> None:
    graph = _text("graph.js")
    app = _text("app.js")
    html = _text("index.html")
    assert "laneOrder(nodes, lanes" in graph
    assert "stableHue" in graph
    assert "const laneY" not in graph
    assert "lane_id in" not in graph
    assert 'role.includes("loop") || tx <= sx' in graph
    assert "edge.gate_ids?.length" in graph
    assert "edge.proven_merge" in graph
    assert 'kind === "terminal"' in graph
    assert 'id="laneList"' in html
    assert "state.page?.lanes || []" in app


def test_cross_page_edges_are_selectable_continuation_portals() -> None:
    graph = _text("graph.js")
    app = _text("app.js")
    css = _text("styles.css")
    assert "missingSource" in graph and "missingTarget" in graph
    assert '"continuation-portal"' in graph
    assert "Continues from" in graph and "Continues to" in graph
    assert "ids.has(edge.source_id) || ids.has(edge.target_id)" in app
    assert "continuations" in app
    assert ".continuation-portal" in css


def test_real_nested_evidence_and_non_authoritative_ai_review() -> None:
    app = _text("app.js")
    html = _text("index.html")
    contract = _text("API_CONTRACT.md")
    assert "payload.provenance" in app and "payload.choices" in app
    assert "source.start?.line" in app and "source.end?.line" in app
    assert "ai_candidates" in app and "claims" in app
    assert "candidate.correction" in app and "candidate.pinned" in app
    assert "technical map is authoritative" in app
    assert "Candidates do not replace the technical map until applied" in html
    assert 'id="discardAssembly"' in html and 'id="applyAssembly"' in html
    assert "project unchanged" in app
    assert "/api/v1/m07/assembly/discard" in contract


def test_polling_waits_for_actual_terminal_status() -> None:
    app = _text("app.js")
    polling = app[
        app.index("async function pollOrganization()") : app.index("function showReview()")
    ]
    assert "while (active.has(state.organization?.status))" in polling
    assert "await loadOrganization()" in polling
    assert "running" in polling and "cancelling" in polling and "queued" in polling


def test_bounded_search_navigation_and_accessibility_contracts() -> None:
    app = _text("app.js")
    graph = _text("graph.js")
    css = _text("styles.css")
    contract = _text("contract.js")
    assert "nodes: 30" in contract and "edges: 180" in contract and "items: 240" in contract
    assert "global_navigation" in app and "global_search" in app
    for key in ("ArrowRight", "ArrowLeft", "ArrowUp", "ArrowDown", "Home", "End", "Enter"):
        assert key in graph
    assert ":focus-visible" in css
    assert "@media (max-width: 780px)" in css and "@media (max-width: 480px)" in css
    assert "font-size: 16px" in css
    assert "Content-Security-Policy" in _text("index.html")


def test_api_fails_closed_on_unbounded_or_incomplete_prepare_binding() -> None:
    api = _text("api.js")
    app = _text("app.js")
    assert "DEFAULT_ORGANIZATION_BUDGETS" in api
    for field in ("soft_seconds", "hard_seconds", "soft_tokens", "hard_tokens", "hard_calls"):
        assert field in api
    for value in (
        "soft_seconds: 600",
        "hard_seconds: 900",
        "soft_tokens: 1500000",
        "hard_tokens: 2000000",
        "hard_calls: 48",
    ):
        assert value in api
    assert "Number.isInteger" in api
    assert "Prepared organization binding is incomplete" in api
    assert "scope_ids: prepared.scope_ids, budgets" in api
    assert "api.startOrganization(state.prepared)" in app
    assert "const completed = await pollAnalysis()" in app


def test_live_harness_uses_real_server_api_sqlite_and_blocks_provider() -> None:
    source = HARNESS.read_text(encoding="utf-8")
    assert "LocalWebServer" in source and "ProjectApi" in source
    assert "create_ingested_project" in source and ".rsmproj" in source
    assert "forbidden_provider" in source
    assert "Network.requestWillBeSent" in source
    assert "--force-device-scale-factor=2" in source
    assert '"width": 720 if zoom == 200 else 1440' in source
    assert '"height": 450 if zoom == 200 else 900' in source
    spec = importlib.util.spec_from_file_location("m07_browser_acceptance", HARNESS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.ZOOMS == (100, 200)
