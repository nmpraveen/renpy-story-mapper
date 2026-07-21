from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_track_c_story_map_is_normal_flow_and_has_build_controls() -> None:
    html = (ROOT / "src/renpy_story_mapper/web/static/index.html").read_text(encoding="utf-8")
    assert 'data-story-map-layout="normal-flow-vertical"' in html
    assert 'data-action="build-story-map"' in html
    assert 'aria-label="Story Map"' in html


def test_track_c_uses_two_stage_production_api() -> None:
    api = (ROOT / "src/renpy_story_mapper/web/static/api.js").read_text(encoding="utf-8")
    for token in ("prepare_boundaries", "start_boundaries", "prepare_summaries", "start_summaries"):
        assert token in api


def test_track_c_contract_forbids_global_canvas_layout() -> None:
    fixture = (ROOT / "tests/fixtures/m15_1/story_map_ui_contract_v2.json").read_text(
        encoding="utf-8"
    )
    styles = (ROOT / "src/renpy_story_mapper/web/static/styles.css").read_text(
        encoding="utf-8"
    )
    assert "normal_flow_vertical" in fixture
    assert ".story-map-normal-flow" in styles
