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
        "mock-api.js",
    )
    assets = "\n".join(_text(name) for name in names)
    assert "Content-Security-Policy" in html
    assert "script-src 'self'" in html
    assert not re.search(r"https?://|//cdn", assets, re.IGNORECASE)
    assert "<script type=\"module\" src=\"./app.js\"></script>" in html
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>\s*\S", html, re.IGNORECASE)
    assert "eval(" not in assets
    assert "new Function" not in assets
    assert "analytics" not in assets.casefold()


def test_dom_rendering_is_xss_safe_and_has_no_html_sinks() -> None:
    javascript = "\n".join(_text(name) for name in ("app.js", "graph.js", "mock-api.js"))
    assert ".textContent" in javascript
    assert "createElement(" in javascript
    assert ".innerHTML" not in javascript
    assert ".outerHTML" not in javascript
    assert "insertAdjacentHTML" not in javascript
    assert "document.write" not in javascript


def test_routes_are_versioned_and_centralized() -> None:
    contract = _text("contract.js")
    assert contract.count('"/api/v1/') >= 18
    for name in ("app.js", "api.js", "graph.js", "mock-api.js"):
        assert '"/api/v1/' not in _text(name)
    routes = (
        "story/view",
        "story/search",
        "story/evidence",
        "story/facts",
        "organization/apply",
        "organization/discard",
        "organization/review",
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
    assert "nodes: 80" in contract and "edges: 120" in contract and "items: 240" in contract
    assert "Graph render boundary exceeded" in graph
    assert "bezierCurveTo" in graph and "stroke()" in graph
    assert 'id="overflowStatus"' in html
    assert "node_continuation?.has_more" in app


def test_keyboard_focus_tabs_and_map_commands_are_implemented() -> None:
    html = _text("index.html")
    graph = _text("graph.js")
    app = _text("app.js")
    for key in ("ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Enter"):
        assert key in graph
    for key in ("ArrowLeft", "ArrowRight", "Home", "End"):
        assert key in app
    assert 'aria-keyshortcuts="/"' in html
    assert 'role="tablist"' in html and 'role="tabpanel"' in html
    assert ":focus-visible" in _text("styles.css")


def test_organization_is_never_implicit() -> None:
    app = _text("app.js")
    start_body = app[app.index("async function start()") :]
    assert "api.consent(" not in start_body
    assert "api.consent(" in app
    assert app.index("api.consent(") > app.index('$("#confirmOrganization").addEventListener')
    assert "organizationConsent" in _text("contract.js")


def test_production_picker_shape_and_refresh_lifecycle_are_wired() -> None:
    app = _text("app.js")
    api = _text("api.js")
    mock = _text("mock-api.js")
    html = _text("index.html")
    assert "target.id || target.selection_id" in app
    assert 'selection_id: "opaque-project-save"' in mock
    assert "refresh()" in api and "ENDPOINTS.projectsRefresh" in api
    assert 'id="refreshProject"' in html and ">Refresh</button>" in html
    assert '$("#refreshProject").addEventListener("click", refreshProject)' in app
    assert "await pollProgress()" in app


def test_unresolved_filter_uses_only_authoritative_production_field() -> None:
    app = _text("app.js")
    mock = _text("mock-api.js")
    assert "unresolved: node.unresolved === true" in app
    assert "payload.unresolved" not in app
    assert "if (!state.settings.include_unresolved)" in app
    assert "unresolved: index % 11 === 7" in mock


def test_production_review_shape_decisions_and_pagination_are_explicit() -> None:
    app = _text("app.js")
    api = _text("api.js")
    mock = _text("mock-api.js")
    html = _text("index.html")
    assert "draft.candidate?.arcs" in app and "draft.candidate?.events" in app
    assert "envelope.reviews?.[draft.id]" in app
    assert "group.event_ids" in app and "group.beat_ids" in app
    assert "target_kind: targetKind" in api and "target_id: targetId" in api
    assert "draft_id: draftId" in api and "decision" in api
    assert "REVIEW_PAGE_SIZE = 40" in app
    assert ".slice(start, start + REVIEW_PAGE_SIZE)" in app
    assert 'id="applyDraft"' in html and "disabled>Apply Draft" in html
    assert "candidate.decision" in app and "api.reviewDraftGroup" in app
    assert "candidate: { arcs, events }" in mock and 'reviews: { "draft-demo"' in mock


def test_responsive_and_200_percent_zoom_contracts_are_present() -> None:
    css = _text("styles.css")
    acceptance = (ROOT / "scripts" / "m06_5_browser_acceptance.py").read_text(encoding="utf-8")
    assert "@media (max-width: 780px)" in css
    assert "@media (max-width: 480px)" in css
    assert "minmax(0, 1fr)" in css
    assert '("events", 200)' in acceptance
    assert "720,450" in acceptance and "1440,900" in acceptance
    assert "--force-device-scale-factor=2" in acceptance


def test_asset_manifest_hashes_are_deterministic() -> None:
    manifest = json.loads(_text("asset-manifest.json"))
    assert manifest["format"] == 2
    assert manifest["hash_basis"] == "sha256-utf8-lf"
    for name, expected in manifest["assets"].items():
        raw = (STATIC / name).read_bytes()
        assert _canonical_text_hash(raw) == expected
        simulated_windows = raw.decode("utf-8").replace("\r\n", "\n").replace(
            "\n", "\r\n"
        )
        assert _canonical_text_hash(simulated_windows.encode()) == expected
