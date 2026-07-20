from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "renpy_story_mapper" / "web" / "static"


def _text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_scene_api_is_retained_but_narrative_map_is_primary() -> None:
    html = _text("index.html")
    app = _text("app.js")
    api = _text("api.js")
    contract = _text("contract.js")
    assert 'id="sceneMapButton"' not in html
    assert 'id="chapterIndex"' in html
    assert 'id="chapterList"' in html
    assert 'mode: "narrative"' in app
    assert "api.sceneMap" not in app and "api.sceneDetail" not in app
    assert "async sceneMap" in api and "async sceneDetail" in api
    assert "api.narrativeMap(" in app
    assert "relationship_limit" in api
    assert 'sceneMap: "/api/v1/m11/scene-map"' in contract
    assert 'sceneDetail: "/api/v1/m11/detail"' in contract
    assert "value.nodes.length > RENDER_LIMITS.nodes" in contract
    assert "value.relationships.length > RENDER_LIMITS.edges" in contract
    assert "membership_reference_count" in contract
    assert 'narrativeMap: "/api/v1/m15/narrative-map"' in contract


def test_narrative_detail_has_provenance_escape_without_ai_interpretation() -> None:
    html = _text("index.html")
    app = _text("app.js")

    assert 'id="canonicalEscapeButton"' in html
    assert 'id="interpretationPanel"' in html
    assert '$("#interpretationPanel").hidden = state.mode === "narrative"' in app
    assert "await api.narrativeDetail(elementId)" in app
    assert "detail.canonical_focus_id" in app
    assert "renderTechnicalMembers(detail)" in app
    assert "renderInspectionDerivations(detail)" in app


def test_narrative_map_falls_back_explicitly_to_m10_inspection() -> None:
    html = _text("index.html")
    app = _text("app.js")

    assert 'id="fallbackTitle">Narrative Map unavailable.' in html
    assert "Deterministic inspection fallback" in app
    assert 'state.mode = "inspection"' in app


def test_real_browser_acceptance_covers_both_zoom_levels_and_canonical_escape() -> None:
    harness = (
        Path(__file__).resolve().parents[1] / "scripts" / "m11_browser_acceptance.py"
    ).read_text(encoding="utf-8")

    assert "ZOOMS: Final = (100, 200)" in harness
    assert "m11-scenes-{zoom}.png" in harness
    assert "m11-scenes-cards-{zoom}.png" in harness
    assert "m11-scene-detail-{zoom}.png" in harness
    assert "m11-canonical-escape-{zoom}.png" in harness
    assert "canonicalEscapeButton" in harness
    assert "_browser_diagnostics" in harness
    assert "forbidden_provider" in harness
    assert 'default["sameLaneCount"] < 10' in harness
    assert 'default["renderedCards"] != default["nodes"]' in harness
    assert 'set(default["renderedCardIds"]) != set(default["loadedNodeIds"])' in harness
    assert 'default["distinctGraphPositions"] != default["nodes"]' in harness
    assert 'default["distinctSameLaneCoordinates"] != default["sameLaneCount"]' in harness
    assert 'default["duplicateSameLanePairs"]' in harness
    assert 'not default["pageOrderMapped"]' in harness
    assert 'not route_page["persistentCards"]' in harness
    assert "No temporary multi-scene branch is visible" in harness
    assert 'max(detail["armSceneCounts"], default=0) < 2' in harness
