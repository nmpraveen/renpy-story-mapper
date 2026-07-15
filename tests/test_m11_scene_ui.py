from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "renpy_story_mapper" / "web" / "static"


def _text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_scene_presentation_is_the_primary_bounded_packaged_view() -> None:
    html = _text("index.html")
    app = _text("app.js")
    api = _text("api.js")
    contract = _text("contract.js")
    graph = _text("graph.js")

    assert 'id="sceneMapButton"' in html
    assert 'id="chapterIndex"' in html
    assert 'id="chapterList"' in html
    assert 'mode: "scenes"' in app
    assert 'state.mode = "scenes"' in app
    assert "state.scenePage" in app
    assert "api.sceneMap" in app and "api.sceneDetail" in app
    assert "relationship_limit" in api
    assert 'sceneMap: "/api/v1/m11/scene-map"' in contract
    assert 'sceneDetail: "/api/v1/m11/detail"' in contract
    assert "value.nodes.length > RENDER_LIMITS.nodes" in contract
    assert "value.relationships.length > RENDER_LIMITS.edges" in contract
    assert "membership_reference_count" in contract
    assert "interactive: false" in app
    assert "edge.interactive !== false" in graph
    assert '.sort((left, right) => Number(left.ordinal || 0)' in app


def test_scene_detail_has_provenance_escape_without_ai_interpretation() -> None:
    html = _text("index.html")
    app = _text("app.js")

    assert 'id="canonicalEscapeButton"' in html
    assert 'id="interpretationPanel"' in html
    assert '$("#interpretationPanel").hidden = sceneMode' in app
    assert "detail.canonical_records?.[0]?.id" in app
    assert "detail.canonical_escape_ids?.[0]" in app
    assert "detail.atoms" in app
    assert "temporary_branch.arms" in app
    assert "detail.selected_occurrence" in app
    assert "detail.boundary" in app
    assert 'openDetail(lane.id)' in app
    assert 'openDetail(chapter.id)' in app


def test_scene_map_falls_back_explicitly_to_m10_inspection() -> None:
    html = _text("index.html")
    app = _text("app.js")

    assert 'id="fallbackTitle">Scene presentation unavailable.' in html
    assert "M10 Inspection" in app
    assert 'state.mode = "inspection"' in app


def test_real_browser_acceptance_covers_both_zoom_levels_and_canonical_escape() -> None:
    harness = (
        Path(__file__).resolve().parents[1] / "scripts" / "m11_browser_acceptance.py"
    ).read_text(encoding="utf-8")

    assert "ZOOMS: Final = (100, 200)" in harness
    assert "m11-scenes-{zoom}.png" in harness
    assert "m11-scene-detail-{zoom}.png" in harness
    assert "m11-canonical-escape-{zoom}.png" in harness
    assert "canonicalEscapeButton" in harness
    assert "_browser_diagnostics" in harness
    assert "forbidden_provider" in harness
