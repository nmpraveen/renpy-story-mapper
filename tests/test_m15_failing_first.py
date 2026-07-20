from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("module_name", "public_name"),
    (
        ("renpy_story_mapper.narrative_map.corridors", "build_narrative_corridors"),
        ("renpy_story_mapper.narrative_map.assembly", "assemble_narrative_events"),
        ("renpy_story_mapper.narrative_map.projection", "build_narrative_map"),
        ("renpy_story_mapper.narrative_map.persistence", "NarrativeMapRepository"),
        ("renpy_story_mapper.narrative_map.validation", "validate_boundary_response"),
        ("renpy_story_mapper.narrative_map.validation", "validate_event_summary_response"),
        ("renpy_story_mapper.narrative_map.workflow", "NarrativeBoundaryWorkflow"),
        ("renpy_story_mapper.narrative_map.service", "NarrativeMapService"),
    ),
)
def test_track_interfaces_exist(module_name: str, public_name: str) -> None:
    spec = importlib.util.find_spec(module_name)
    assert spec is not None, f"failing-first: {module_name} is not implemented"
    module = __import__(module_name, fromlist=[public_name])
    assert hasattr(module, public_name), f"failing-first: {module_name}.{public_name} is missing"


def test_normal_browser_retires_route_solver_and_legacy_ai_controls() -> None:
    static = ROOT / "src" / "renpy_story_mapper" / "web" / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    app = (static / "app.js").read_text(encoding="utf-8")

    for forbidden in (
        'id="routePanel"',
        'id="solveRoute"',
        "How do I reach this?",
        "Reach this scene",
        "AI Story Map",
        "M07 Structure",
    ):
        assert forbidden not in html, f"failing-first: normal browser still contains {forbidden}"
    assert "state.aiPage" not in app


def test_exact_msday1_fixture_and_current_fragmentation_baseline() -> None:
    fixture_root = ROOT / "MsDay1"
    source = fixture_root / "input" / "game" / "v0.01_clean.rpy"
    project = ROOT / "tmp" / "msday1-sentinel-validation.rsmproj"
    if not source.is_file() or not project.is_file():
        pytest.skip("private MsDay1 acceptance fixture is not present in this worktree")

    assert hashlib.sha256(source.read_bytes()).hexdigest() == (
        "14aa44ed95dec5402dfb02a1c4e01e63b3f3e329cf04fec37b04edebb5d588a6"
    )
    assert len(source.read_bytes().splitlines()) == 793

    with sqlite3.connect(project) as database:
        payload = database.execute(
            "SELECT json_array_length(json_extract(payload_json, '$.result.scenes')) "
            "FROM payloads WHERE collection = 'm11_phase_results' "
            "AND record_key LIKE 'scene_assembly:%'"
        ).fetchone()
    assert payload == (165,)


def test_exact_msday1_golden_choice_rejoins_and_terrance_janet_boundary() -> None:
    acceptance = ROOT / "scripts" / "m15_provider_free_acceptance.py"
    assert acceptance.is_file(), "failing-first: exact M15 provider-free runner is missing"
    spec = importlib.util.spec_from_file_location("m15_provider_free_acceptance", acceptance)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evaluator = getattr(module, "evaluate_exact_msday1", None)
    assert callable(evaluator), "failing-first: exact Day 1 evaluator is missing"

    report = evaluator(ROOT / "MsDay1", ROOT / "tmp" / "msday1-sentinel-validation.rsmproj")
    assert report["terrance_choice_rejoins"] == [[143, 165], [191, 233]]
    assert report["faye_choice_rejoins"] == [[623, 793], [674, 793]]
    assert report["terrance_event_end_line"] < 280
    assert report["janet_event_start_line"] == 280
    assert report["technical_setup_end_line"] == 26
    assert 27 <= report["prologue_event_start_line"] <= 51
    assert report["day1_event_start_line"] == 52
    assert report["major_event_order"] == ["prologue", "terrance", "janet", "dinner", "faye"]
    assert report["blocked_technical_titles"] == []
