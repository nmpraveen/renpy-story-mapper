from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "renpy_story_mapper" / "web" / "static"
HARNESS = ROOT / "scripts" / "m15_1_track_c_browser_acceptance.py"


def _text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _module() -> object:
    spec = importlib.util.spec_from_file_location("m15_1_track_c_browser_acceptance", HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_normal_story_surface_is_bounded_semantic_flow() -> None:
    html = _text("index.html")
    css = _text("styles.css")
    app = _text("app.js")
    assert 'data-story-map-layout="normal-flow-vertical"' in html
    assert 'id="storyMapFlow"' in html and 'role="feed"' in html
    assert 'html[data-narrative-presentation="semantic-flow"] .graph-surface' in css
    assert 'width: min(100%, 896px)' in css
    assert "@container story-choice (min-width: 600px)" in css
    assert "renderStoryMapFlow(nodes, edges)" in app
    assert 'node.kind !== "technical_coverage"' in app


def test_two_stage_controls_are_separate_and_never_implicit() -> None:
    html = _text("index.html")
    api = _text("api.js")
    app = _text("app.js")
    for control in (
        "prepareBoundaries",
        "prepareSummaries",
        "confirmStoryMapStage",
        "cancelStoryMapBuild",
        "resumeStoryMapBuild",
        "retryStoryMapBuild",
    ):
        assert f'id="{control}"' in html
    for action in (
        '"prepare_boundaries"',
        '"start_boundaries"',
        '"prepare_summaries"',
        '"start_summaries"',
    ):
        assert action in api
    normal_entry = app[
        app.index("async function enterAvailableWorkspace") : app.index("function nextCursor")
    ]
    assert "prepareStoryBoundaries" not in normal_entry
    assert "startStoryBoundaries" not in normal_entry
    assert "prepareStorySummaries" not in normal_entry
    assert "startStorySummaries" not in normal_entry
    assert "async function pollStoryMapBuild" in app
    assert "await api.storyMapBuildStatus()" in app
    assert "await reloadStoryMapAfterBuild()" in app
    assert "async function loadStoryMapBuildStatus" in app
    status_start = app.index("async function loadNarrativeRunStatus")
    status_end = app.index("async function loadNarrative()")
    status_loader = app[status_start:status_end]
    assert "await loadStoryMapBuildStatus()" in status_loader


def test_real_browser_harness_checks_responsive_evidence_and_exact_navigation() -> None:
    source = HARNESS.read_text(encoding="utf-8")
    for marker in (
        "semantic_outline_v2.json",
        '"100": (1440, 900, 1)',
        '"200": (720, 450, 2)',
        '"narrow": (560, 900, 1)',
        "expected_ids",
        "Detail/Evidence mapping is not exhaustive and unique",
        "gridTemplateColumns",
        "opened_by_keyboard",
        "hidden_nonmatches",
        "overlaps",
        "contained",
        "provider_constructions",
        "m12_solve_or_destination_requests",
        "m15-1-story-map-{label}.png",
        "m15-1-story-map-expanded-{label}.png",
        "m15-1-story-map-section-{label}.png",
        "m15-1-detail-{label}.png",
        "Expanded Story Map is not a full-page capture",
        "Two-stage consent did not expose every exact bound fact",
        "_exercise_product_prepare_cancel",
        "m15_provider_factory=forbidden_provider",
    ):
        assert marker in source


@pytest.mark.hardware_sensitive
@pytest.mark.skipif(
    os.environ.get("RSM_RUN_BROWSER_ACCEPTANCE") != "1",
    reason="set RSM_RUN_BROWSER_ACCEPTANCE=1 for real Chrome acceptance",
)
def test_m15_1_real_browser_track_c(tmp_path: Path) -> None:
    module = _module()
    report = module.run(tmp_path / "browser")  # type: ignore[attr-defined]
    assert report["status"] == "passed"
    assert report["provider_constructions"] == 0
    assert report["remote_requests"] == 0
    assert report["m12_solve_or_destination_requests"] == 0
    assert report["product_lifecycle"]["preview"]["confirmEnabled"] is True
    assert report["product_lifecycle"]["cancelled"]["state"] == "cancelled"
