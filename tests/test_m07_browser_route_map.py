from __future__ import annotations

import importlib.util
import json
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


def test_exactly_two_visible_levels_and_one_transition() -> None:
    assets = _assets()
    html = _text("index.html")
    assert 'data-level="route_map"' in html
    assert 'data-level="detail_evidence"' in html
    assert assets.count("Back to Route Map") >= 1
    assert not re.search(r"\bLevel\s*[123]\b", assets, re.IGNORECASE)
    assert not re.search(r"Back to (?:Arcs|Events)", assets, re.IGNORECASE)
    assert "semantic zoom" not in assets.casefold()
    assert "Detail / Evidence" in html


def test_locked_api_routes_and_bodies_are_centralized() -> None:
    contract = _text("contract.js")
    api = _text("api.js")
    expected = {
        "routeMap": "/api/v1/m07/route-map",
        "routeDetail": "/api/v1/m07/detail",
        "organization": "/api/v1/m07/organization",
        "organizationPrepare": "/api/v1/m07/organization/prepare",
        "organizationStart": "/api/v1/m07/organization/start",
        "organizationCancel": "/api/v1/m07/organization/cancel",
        "assemblyApply": "/api/v1/m07/assembly/apply",
    }
    for name, route in expected.items():
        assert f'{name}: "{route}"' in contract
    assert "body: { offset, limit }" in api
    assert "body: { element_id: elementId }" in api
    assert "body: { run_id: runId, confirm_cloud: true, budgets }" in api
    assert "body: { assembly_id: assemblyId }" in api
    for name in ("app.js", "api.js", "graph.js", "mock-api.js"):
        if name != "api.js":
            assert '"/api/v1/m07/' not in _text(name)


def test_route_grammar_is_line_first_bounded_and_keyboard_openable() -> None:
    graph = _text("graph.js")
    css = _text("styles.css")
    contract = _text("contract.js")
    mock = _text("mock-api.js")
    assert "nodes: 30" in contract and "items: 240" in contract
    assert "bezierCurveTo" in graph and "technical_corridor" in mock
    grammar_terms = (
        "local_detour",
        "persistent_route",
        "proven_merge",
        "loop_choice",
        "unresolved",
    )
    for grammar in grammar_terms:
        assert grammar in mock or grammar in graph
    for key in ("ArrowRight", "ArrowLeft", "ArrowUp", "ArrowDown", "Home", "End", "Enter"):
        assert key in graph
    assert "edge-stop" in graph and "onOpen?.(edge)" in graph
    assert ".station[data-kind=\"choice\"]" in css
    assert ".station[data-kind=\"merge\"]" in css
    assert ".station[data-kind=\"terminal\"]" in css
    assert ".station[data-kind=\"unresolved\"]" in css


def test_direct_detail_contains_exact_evidence_and_interpretation_links() -> None:
    app = _text("app.js")
    mock = _text("mock-api.js")
    html = _text("index.html")
    fields = (
        "predecessor_ids",
        "successor_ids",
        "choices",
        "gates",
        "effects",
        "dialogue",
        "narration",
        "interpretations",
        "evidence",
    )
    for field in fields:
        assert field in app or field in mock
    assert "dataset.evidenceId" in app
    assert "source.path" in app and "source.start_line" in app and "source.basis" in app
    assert "evidence_ids" in app
    assert 'id="pathStrip"' in html


def test_paging_filters_selection_and_physical_zoom_stay_on_route_map() -> None:
    app = _text("app.js")
    html = _text("index.html")
    assert "loadRoutePage(state.page.next_offset)" in app
    assert "Math.max(0, state.offset - ROUTE_PAGE_SIZE)" in app
    assert "state.selectedId" in app
    assert "include_technical" in app and "include_unresolved" in app
    assert 'id="zoomIn"' in html and 'id="zoomOut"' in html and 'id="fitMap"' in html
    zoom_region = app[app.index('$("#zoomIn")') : app.index('$("#backToRouteMap")')]
    assert "showLevel" not in zoom_region


def test_organization_is_prepare_then_confirmed_start_and_partial_apply() -> None:
    app = _text("app.js")
    mock = _text("mock-api.js")
    assert app.index("prepareOrganization()") < app.index("startOrganization()")
    start = app[
        app.index("async function startOrganization()") :
        app.index("async function pollOrganization()")
    ]
    assert "api.startOrganization" in start
    assert '$("#confirmOrganization").addEventListener' in app
    assert "api.cancelOrganization" in app and "api.applyAssembly" in app
    terms = (
        "validated", "technical", "pending", "calls", "tokens", "coverage", "eta", "partial"
    )
    for term in terms:
        assert term in app.casefold() or term in mock.casefold()
    assert "provider_constructed: false" in mock


def test_local_assets_are_xss_safe_accessible_and_responsive() -> None:
    assets = _assets()
    javascript = "\n".join(_text(name) for name in ("app.js", "graph.js", "mock-api.js"))
    assert not re.search(r"https?://|//cdn", assets, re.IGNORECASE)
    assert ".innerHTML" not in javascript and ".outerHTML" not in javascript
    assert "eval(" not in assets and "new Function" not in assets
    assert "createElement(" in javascript and ".textContent" in javascript
    css = _text("styles.css")
    assert 'font-family: "Segoe UI", system-ui, sans-serif' in css
    assert "font-size: 16px" in css and "font-size: 14px" in css
    assert ":focus-visible" in css
    assert "@media (max-width: 780px)" in css and "@media (max-width: 480px)" in css
    assert "prefers-reduced-motion" not in css  # no decorative motion exists
    assert "Content-Security-Policy" in _text("index.html")


def test_acceptance_harness_loads_packaged_assets() -> None:
    source = HARNESS.read_text(encoding="utf-8")
    assert "STATIC / name" in source
    assert "mock\": 1" in source
    assert "force-device-scale-factor=2" in source
    assert "provider_constructions" in source and '"remote_requests": 0' in source
    assert "EXERCISES" in source and '"paging"' in source and '"keyboard"' in source
    spec = importlib.util.spec_from_file_location("m07_browser_acceptance", HARNESS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.STATES == ("route-map", "detail-evidence", "coverage-progress", "review-partial")
    assert module.ASSETS["/index.html"][1] == _text("index.html")
    contract_path = ROOT / "tests" / "fixtures" / "m07" / "browser_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract["levels"] == ["route_map", "detail_evidence"]
