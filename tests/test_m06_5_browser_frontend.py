from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "renpy_story_mapper" / "web" / "static"
SCRIPTS = ("app.js", "api.js", "contract.js", "story-map-v2-diff.js")


def _text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _canonical_text_hash(data: bytes) -> str:
    content = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(content.encode()).hexdigest()


def test_assets_are_local_and_csp_compatible() -> None:
    html = _text("index.html")
    assets = "\n".join(_text(name) for name in ("index.html", "styles.css", *SCRIPTS))
    assert "Content-Security-Policy" in html
    assert "script-src 'self'" in html
    assert not re.search(r"https?://|//cdn", assets, re.IGNORECASE)
    assert '<script type="module" src="./app.js"></script>' in html
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>\s*\S", html, re.IGNORECASE)
    assert "eval(" not in assets
    assert "new Function" not in assets
    assert "analytics" not in assets.casefold()


def test_no_inline_style_attributes_under_strict_style_src() -> None:
    """`style-src 'self'` blocks markup style attributes; CSSOM writes stay allowed."""
    assert not re.search(r"<[^>]+\sstyle=", _text("index.html"), re.IGNORECASE)


def test_dom_rendering_is_xss_safe_and_has_no_html_sinks() -> None:
    javascript = "\n".join(_text(name) for name in SCRIPTS)
    assert ".textContent" in javascript
    assert "createElement(" in javascript
    assert ".innerHTML" not in javascript
    assert ".outerHTML" not in javascript
    assert "insertAdjacentHTML" not in javascript
    assert "document.write" not in javascript


def test_routes_are_versioned_and_centralized() -> None:
    contract = _text("contract.js")
    assert contract.count('"/api/v1/') >= 17
    for name in ("app.js", "api.js"):
        assert '"/api/v1/' not in _text(name)
    assert 'shutdown: "/api/v1/shutdown"' in contract
    assert 'id="quitButton"' in _text("index.html")
    assert "await api.shutdown()" in _text("app.js")


def test_keyboard_focus_and_two_levels_are_implemented() -> None:
    html = _text("index.html")
    app = _text("app.js")
    assert 'data-level="route_map"' in html and 'data-level="detail_evidence"' in html
    assert html.count('data-level="') == 2
    assert 'id="backToRouteMap"' in html
    assert 'if (event.key === "Escape")' in app
    assert 'event.key === "/"' in app
    assert ":focus-visible" in _text("styles.css")
    assert "Skip to story" in html


def test_picker_shape_and_refresh_lifecycle_are_wired() -> None:
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


def test_story_reader_is_the_only_map_surface() -> None:
    """The loopback story reader is the sole product surface; milestone views are gone."""
    html = _text("index.html")
    app = _text("app.js")
    for removed in (
        'id="mapLayout"',
        'id="mapViewport"',
        'id="edgeCanvas"',
        'class="commandbar"',
        'class="view-switch"',
        'id="routePanel"',
        'id="narrativeDrawer"',
        'id="organizationPanel"',
        'id="consentDialog"',
        'id="reviewDialog"',
        'id="zoomIn"',
        'id="fitMap"',
    ):
        assert removed not in html, removed
    for removed in ("function renderMap(", "function switchMode(", "new RouteGraph("):
        assert removed not in app, removed
    assert not (STATIC / "graph.js").exists()


def test_responsive_reader_breakpoints_are_present() -> None:
    css = _text("styles.css")
    assert "@media (max-width: 1240px)" in css
    assert "@media (max-width: 900px)" in css
    assert "@media (max-width: 620px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "minmax(0, 1fr)" in css


def test_asset_manifest_hashes_are_deterministic() -> None:
    manifest = json.loads(_text("asset-manifest.json"))
    assert manifest["format"] == 2
    assert manifest["hash_basis"] == "sha256-utf8-lf"
    for name, expected in manifest["assets"].items():
        raw = (STATIC / name).read_bytes()
        assert _canonical_text_hash(raw) == expected
        simulated_windows = raw.decode("utf-8").replace("\r\n", "\n").replace("\n", "\r\n")
        assert _canonical_text_hash(simulated_windows.encode()) == expected
