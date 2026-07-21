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


def test_ai_story_map_contract_remains_compatible_but_selector_is_retired() -> None:
    app = _text("app.js")
    html = _text("index.html")
    contract = _text("contract.js")
    assert 'id="aiMapButton"' not in html and 'id="technicalMapButton"' not in html
    assert "inspectionCurrent" in app and "canonicalCurrent" in app
    assert "comparison.default_view" not in app
    assert "state.aiPage" not in app and "state.technicalPage" not in app
    assert "authority_unchanged" in contract
    assert "/api/v1/m08/ai-story-map" in contract
    assert "/api/v1/m08/ai-story-detail" in contract
    assert "/api/v1/m08/comparison" in contract
    assert "api.aiStoryMap(" not in app and "api.aiStoryDetail(" not in app
    assert "async aiStoryMap" in _text("api.js")


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


def test_bounded_organization_contract_remains_without_normal_ui_calls() -> None:
    app = _text("app.js")
    api = _text("api.js")
    contract = _text("contract.js")
    assert "visibleRouteNodeIds" not in app
    assert "api.resolveBoundedWindow(" not in app
    assert "api.prepareOrganization(" not in app
    assert "organizationStartPayload" in api
    assert "prepared.scope_ids" in api and "prepared.window_ids" in api
    assert "exactOrganizationModel" in contract and "exactOrganizationBudgets" in contract


def test_organization_progress_and_review_controls_are_retired() -> None:
    app = _text("app.js")
    html = _text("index.html")
    for element_id in (
        "cancelOrganization",
        "resumeOrganization",
        "reviewPartial",
        "applyAssembly",
        "discardAssembly",
    ):
        assert f'id="{element_id}"' not in html
    assert "pollOrganization" not in app


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


def test_route_map_keeps_flexible_row_when_fallback_notice_is_hidden() -> None:
    css = _text("styles.css")
    assert 'grid-template-areas: "commandbar" "fallback" "failure" "partial" "map"' in css
    assert "grid-area: commandbar" in css
    assert "grid-area: fallback" in css
    assert "grid-area: map" in css
    old_layout = (
        'grid-template-areas: "commandbar" "fallback" "failure" "partial" "map" '
        '"organization"'
    )
    assert old_layout not in css


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
        "Route Map did not retain the flexible viewport row",
    ):
        assert marker in source
    spec = importlib.util.spec_from_file_location("m08_browser_acceptance", HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.ZOOMS == (100, 200)
    assert module.VIEWPORTS == {100: (1440, 900), 200: (720, 450)}


def test_ai_incident_cursor_contract_remains_in_compatibility_client() -> None:
    app = _text("app.js")
    api = _text("api.js")
    contract = _text("contract.js")
    assert "edge_next_cursor" not in app
    assert "edgeCursor: state.edgeCursor" in app
    assert "const target = state.cursorHistory.pop()" in app
    assert "body.edge_cursor = edgeCursor" in api
    assert "incident_to_node_slice" in contract
    assert "AI Story Map returned an unrelated edge" in contract
    assert "AI Story Map continuation endpoints are incomplete" in contract
