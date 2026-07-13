from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "renpy_story_mapper" / "web" / "static"
HARNESS = ROOT / "scripts" / "m08_browser_acceptance.py"


def _text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _assets() -> str:
    return "\n".join(
        _text(name)
        for name in ("index.html", "styles.css", "app.js", "api.js", "contract.js", "graph.js")
    )


def test_ai_story_map_is_applied_default_with_exact_technical_comparison() -> None:
    app = _text("app.js")
    html = _text("index.html")
    contract = _text("contract.js")
    assert 'id="aiMapButton"' in html and 'id="technicalMapButton"' in html
    assert "comparison.default_view === \"ai_story_map\"" in app
    assert "state.aiPage" in app and "state.technicalPage" in app
    assert "authority_unchanged" in contract
    assert "/api/v1/m08/ai-story-map" in contract
    assert "/api/v1/m08/ai-story-detail" in contract
    assert "/api/v1/m08/comparison" in contract
    assert "source_kind" in app and "presentation_role" in app
    assert "Untitled story event" in app and "node.summary" in app


def test_exactly_two_levels_and_detail_contains_all_verification_surfaces() -> None:
    html = _text("index.html")
    app = _text("app.js")
    assert html.count('data-level="') == 2
    assert 'data-level="route_map"' in html
    assert 'data-level="detail_evidence"' in html
    assert "Back to Route Map" in html
    assert 'id="technicalMembers"' in html
    assert "member_route_nodes" in app and "member_route_edges" in app
    assert "detail.facts" in app and "detail.claims" in app
    assert "candidate.correction" in app and "candidate.pinned" in app
    assert "evidenceLineBasis" in app
    assert not re.search(r"\bLevel\s*[123]\b", _assets(), re.IGNORECASE)


def test_bounded_preview_and_consent_echo_remain_exact_and_nonempty() -> None:
    app = _text("app.js")
    api = _text("api.js")
    contract = _text("contract.js")
    assert "visibleRouteNodeIds" in app
    assert "api.resolveBoundedWindow({ node_ids: nodeIds })" in app
    assert "api.setOrganizationSelection([], [state.windowResolution.selection_request])" in app
    assert "if (!nodeIds.length)" in app
    assert "api.prepareOrganization()" in app
    for label in (
        "Boundaries",
        "Evidence / facts",
        "Input hash",
        "Authority hash",
        "Selection hash",
        "Recovered-source acknowledgement",
        "Provider",
        "Time budgets",
        "Token budgets",
        "Call budget",
    ):
        assert label in app
    assert "organizationStartPayload" in api
    assert "prepared.scope_ids" in api and "prepared.window_ids" in api
    assert "exactOrganizationModel" in contract and "exactOrganizationBudgets" in contract


def test_progress_review_and_fallback_language_are_honest() -> None:
    app = _text("app.js")
    html = _text("index.html")
    fields = ("validated", "fallback", "pending", "cancelled", "calls", "tokens", "eta", "cached")
    for field in fields:
        assert field in app
    assert "partial with fallback" in app
    assert 'id="cancelOrganization"' in html
    assert 'id="resumeOrganization"' in html
    assert 'id="reviewPartial"' in html
    assert 'id="applyAssembly"' in html
    assert 'id="discardAssembly"' in html
    assert "never mislabel" not in app


def test_editorial_cartography_is_local_restrained_and_free_of_mojibake() -> None:
    assets = _assets()
    css = _text("styles.css")
    assert "Georgia" in css and "Segoe UI" in css
    assert "--paper:" in css and "--ink:" in css and "--accent:" in css
    assert "station-summary" in css and "detour_annotation" in css
    assert "bezierCurveTo" in _text("graph.js")
    assert "linear-gradient" not in css and "radial-gradient" not in css
    assert not re.search(r"Ã|Â|â|�", assets)
    assert not re.search(r"https?://|//cdn", assets, re.IGNORECASE)
    assert ".card-grid" not in css


def test_real_browser_harness_covers_wide_narrow_zero_provider_workflows() -> None:
    source = HARNESS.read_text(encoding="utf-8")
    for marker in (
        "LocalWebServer",
        "ProjectApi",
        "create_ingested_project",
        "forbidden_provider",
        "ai-story-map-{zoom}.png",
        "technical-comparison-{zoom}.png",
        "exact-consent-{zoom}.png",
        "detail-evidence-{zoom}.png",
        "review-apply-{zoom}.png",
        "#cancelOrganization",
        "#resumeOrganization",
        "#applyAssembly",
        "#discardAssembly",
        "Network.requestWillBeSent",
        "provider_start_requests",
        "offenders",
        "#nextPage",
        "#previousPage",
        "continuation-portal",
        "AI Previous did not restore the exact initial page",
        "AI Next was not deterministic with a continuation portal",
    ):
        assert marker in source
    spec = importlib.util.spec_from_file_location("m08_browser_acceptance", HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.ZOOMS == (100, 200)
    assert module.VIEWPORTS == {100: (1440, 900), 200: (720, 450)}


def test_ai_next_previous_use_exact_incident_cursor_history() -> None:
    app = _text("app.js")
    api = _text("api.js")
    contract = _text("contract.js")
    assert "edge_next_cursor" in app and "edgeCursor: state.edgeCursor" in app
    assert 'edgeCursor: state.mode === "ai" ? state.page.edge_next_cursor : null' in app
    assert "edgeCursor: null" in app
    assert (
        "state.cursorHistory.push({ offset: state.offset, edgeOffset: state.edgeOffset, "
        "edgeCursor: state.edgeCursor })" in app
    )
    assert "const target = state.cursorHistory.pop()" in app
    assert "body.edge_cursor = edgeCursor" in api
    assert "incident_to_node_slice" in contract
    assert "AI Story Map returned an unrelated edge" in contract
    assert "AI Story Map continuation endpoints are incomplete" in contract
