from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "renpy_story_mapper" / "web" / "static"


def _text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _canonical_text_hash(data: bytes) -> str:
    content = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(content.encode()).hexdigest()


def test_assets_are_local_and_csp_compatible() -> None:
    html = _text("index.html")
    names = (
        "index.html",
        "styles.css",
        "app.js",
        "api.js",
        "contract.js",
        "graph.js",
    )
    assets = "\n".join(_text(name) for name in names)
    assert "Content-Security-Policy" in html
    assert "script-src 'self'" in html
    assert not re.search(r"https?://|//cdn", assets, re.IGNORECASE)
    assert '<script type="module" src="./app.js"></script>' in html
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>\s*\S", html, re.IGNORECASE)
    assert "eval(" not in assets
    assert "new Function" not in assets
    assert "analytics" not in assets.casefold()


def test_dom_rendering_is_xss_safe_and_has_no_html_sinks() -> None:
    javascript = "\n".join(_text(name) for name in ("app.js", "graph.js"))
    assert ".textContent" in javascript
    assert "createElement(" in javascript
    assert ".innerHTML" not in javascript
    assert ".outerHTML" not in javascript
    assert "insertAdjacentHTML" not in javascript
    assert "document.write" not in javascript


def test_routes_are_versioned_and_centralized() -> None:
    contract = _text("contract.js")
    assert contract.count('"/api/v1/') >= 17
    for name in ("app.js", "api.js", "graph.js"):
        assert '"/api/v1/' not in _text(name)
    routes = (
        "m07/route-map",
        "m07/detail",
        "m07/organization/prepare",
        "m07/organization/start",
        "m07/organization/cancel",
        "m07/assembly/apply",
    )
    for route in routes:
        assert route in contract
    assert 'shutdown: "/api/v1/shutdown"' in contract
    assert 'id="quitButton"' in _text("index.html")
    assert "await api.shutdown()" in _text("app.js")


def test_render_boundary_overflow_and_visible_lines_are_explicit() -> None:
    contract = _text("contract.js")
    graph = _text("graph.js")
    app = _text("app.js")
    html = _text("index.html")
    assert "nodes: 30" in contract and "edges: 180" in contract and "items: 240" in contract
    assert "Route Map render boundary exceeded" in graph
    assert "bezierCurveTo" in graph and "stroke()" in graph
    assert 'id="pageStatus"' in html
    assert "state.page?.next_offset" in app


def test_keyboard_focus_tabs_and_map_commands_are_implemented() -> None:
    html = _text("index.html")
    graph = _text("graph.js")
    for key in ("ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End", "Enter"):
        assert key in graph
    assert 'aria-keyshortcuts="/"' in html
    assert 'id="backToRouteMap"' in html and "Back to Route Map" in html
    assert 'data-level="route_map"' in html and 'data-level="detail_evidence"' in html
    assert ":focus-visible" in _text("styles.css")


def test_organization_is_never_implicit() -> None:
    app = _text("app.js")
    api = _text("api.js")
    assert "api.prepareOrganization()" in app
    assert '$("#consentDialog").showModal()' in app
    assert "api.startOrganization" in app
    assert "confirm_cloud: true" in api
    assert "organizationPrepare" in _text("contract.js")


def test_production_picker_shape_and_refresh_lifecycle_are_wired() -> None:
    app = _text("app.js")
    api = _text("api.js")
    html = _text("index.html")
    assert "source.selection_id || source.id" in app
    assert "destination.selection_id || destination.id" in app
    assert not (STATIC / "mock-api.js").exists()
    assert "refresh()" in api and "ENDPOINTS.projectsRefresh" in api
    assert 'id="refreshProject"' in html and ">Refresh</button>" in html
    assert '$("#refreshProject").addEventListener("click", async () =>' in app
    assert "await api.refresh()" in app and "const completed = await pollAnalysis()" in app
    reset = app[app.index("async function resetRoutePaging()") : app.index("function nextCursor()")]
    assert "state.cursorHistory = []" in reset
    assert "await loadRoutePage({ offset: 0, edgeOffset: 0 })" in reset


def test_unresolved_filter_uses_only_authoritative_production_field() -> None:
    app = _text("app.js")
    assert "if (!state.settings.include_unresolved && node.unresolved)" in app
    assert "payload.unresolved" not in app


def test_production_review_shape_decisions_and_pagination_are_explicit() -> None:
    app = _text("app.js")
    api = _text("api.js")
    html = _text("index.html")
    assert "state.organization?.coverage" in app
    assert "value.assembly_id" in app
    assert "assembly_id: assemblyId" in api
    assert "ENDPOINTS.assemblyApply" in api
    assert "api.applyAssembly" in app
    assert 'id="reviewPartial"' in html and 'id="applyAssembly"' in html


def test_responsive_and_200_percent_zoom_contracts_are_present() -> None:
    css = _text("styles.css")
    acceptance = (ROOT / "scripts" / "m07_browser_acceptance.py").read_text(encoding="utf-8")
    assert "@media (max-width: 780px)" in css
    assert "@media (max-width: 480px)" in css
    assert "minmax(0, 1fr)" in css
    assert 'f"route-map-{zoom}.png"' in acceptance
    assert 'f"detail-evidence-{zoom}.png"' in acceptance
    assert '"width": 720 if zoom == 200 else 1440' in acceptance
    assert "--force-device-scale-factor=2" in acceptance


def test_asset_manifest_hashes_are_deterministic() -> None:
    manifest = json.loads(_text("asset-manifest.json"))
    assert manifest["format"] == 2
    assert manifest["hash_basis"] == "sha256-utf8-lf"
    for name, expected in manifest["assets"].items():
        raw = (STATIC / name).read_bytes()
        assert _canonical_text_hash(raw) == expected
        simulated_windows = raw.decode("utf-8").replace("\r\n", "\n").replace("\n", "\r\n")
        assert _canonical_text_hash(simulated_windows.encode()) == expected
