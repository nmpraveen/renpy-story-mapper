from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts" / "m15_browser_acceptance.py"


def _module() -> object:
    spec = importlib.util.spec_from_file_location("m15_browser_acceptance", HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_m15_browser_harness_covers_track_c_gates() -> None:
    source = HARNESS.read_text(encoding="utf-8")
    for marker in (
        "LocalWebServer",
        "ProjectApi",
        "control_regions.rpy",
        "FORBIDDEN_NORMAL_ROUTES",
        "/api/v1/m12/destinations",
        "/api/v1/m12/solve",
        "provider_constructions",
        "remote_requests",
        "choiceArms",
        "rejoins",
        "overlaps",
        "finiteEdges",
        "serverEdges",
        "technical_toggle",
        "hiddenContinuity",
        "correctionStatus",
        "technical_correction_id",
        "#fitMap",
        "scaled",
        "restored_scale",
        "Input.dispatchMouseEvent",
        "elementFromPoint",
        "pan_stress",
        "search_semantics",
        "repeated-title",
        "Input.dispatchKeyEvent",
        "detail_evidence",
        "Content-Security-Policy",
        "m15-track-c-map-{zoom}.png",
        "m15-track-c-detail-{zoom}.png",
        "--output-dir",
    ):
        assert marker in source
    module = _module()
    assert module.ZOOMS == (100, 200)  # type: ignore[attr-defined]


def test_m15_browser_harness_help_uses_output_directory_contract() -> None:
    completed = subprocess.run(
        [sys.executable, str(HARNESS), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "--output-dir" in completed.stdout
    assert "--browser" in completed.stdout


@pytest.mark.skipif(
    shutil.which("node") is None,
    reason="Node.js is required for browser client behavior checks",
)
def test_workspace_background_completion_preserves_an_active_viewport() -> None:
    app = (ROOT / "src" / "renpy_story_mapper" / "web" / "static" / "app.js").read_text(
        encoding="utf-8"
    )
    start = app.index("async function enterAvailableWorkspace")
    end = app.index("\n}\n", start) + 2
    behavior = app[start:end]
    script = f"""
      {behavior}
      const calls = [];
      const showPrimary = (value) => calls.push(["primary", value]);
      const showLevel = (value) => calls.push(["level", value]);
      const resetRoutePaging = async () => {{ calls.push(["initial-render"]); return true; }};
      const loadNarrative = async () => calls.push(["narrative"]);
      const loadNarrativeRunStatus = async () => calls.push(["status"]);
      const renderMap = (options = {{}}) => calls.push(["final-render", options]);
      const available = await enterAvailableWorkspace();
      process.stdout.write(JSON.stringify({{ available, calls }}));
    """
    completed = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["available"] is True
    assert result["calls"][-1] == ["final-render", {"preserveViewport": True}]


@pytest.mark.skipif(
    shutil.which("node") is None,
    reason="Node.js is required for browser client behavior checks",
)
def test_narrative_search_preserves_matching_selection_and_falls_back_when_absent() -> None:
    app = (ROOT / "src" / "renpy_story_mapper" / "web" / "static" / "app.js").read_text(
        encoding="utf-8"
    )
    start = app.index("async function searchM10WholeGraph")
    end = app.index("\n}\n", start) + 2
    behavior = app[start:end]
    script = f"""
      {behavior}
      const input = {{ value: "Repeated title" }};
      const status = {{ textContent: "" }};
      const $ = (selector) => selector === "#searchInput" ? input : status;
      const calls = [];
      const renders = [];
      const response = {{ status: "available", nodes: [
        {{ id: "node-first", title: "Repeated title", summary: "first" }},
        {{ id: "node-selected", title: "Repeated title", summary: "second" }},
        {{ id: "node-other", title: "Different title", summary: "third" }},
      ], edges: [], search: {{ query: "Repeated title", matches: [
        {{ id: "node-first", title: "Repeated title" }},
        {{ id: "node-selected", title: "Repeated title" }},
      ] }} }};
      const state = {{ mode: "narrative", selectedId: "node-selected", page: response }};
      const api = {{ narrativeMap: async (query, focus) => {{
        calls.push([query, focus]); return response;
      }} }};
      const normalizedPage = (page) => page;
      const renderMap = (options) => renders.push(options);
      const renderAnalysisAvailability = () => {{}};
      const CSS = {{ escape: (value) => value }};
      const graph = {{ world: {{ querySelector: () => null }} }};
      await searchM10WholeGraph();
      const retained = state.selectedId;
      state.selectedId = "node-other";
      await searchM10WholeGraph();
      const fallback = state.selectedId;
      state.selectedId = "node-selected";
      input.value = "";
      await searchM10WholeGraph();
      process.stdout.write(JSON.stringify({{
        retained, fallback, empty: state.selectedId, calls, renders
      }}));
    """
    completed = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["retained"] == "node-selected"
    assert result["fallback"] == "node-first"
    assert result["empty"] == "node-selected"
    assert result["calls"] == [
        ["Repeated title", "node-selected"],
        ["Repeated title", "node-other"],
        [None, "node-selected"],
    ]
    assert result["renders"] == [
        {"preserveViewport": True},
        {"preserveViewport": True},
        {"preserveViewport": True},
    ]


@pytest.mark.hardware_sensitive
@pytest.mark.skipif(
    os.environ.get("RSM_RUN_BROWSER_ACCEPTANCE") != "1",
    reason="set RSM_RUN_BROWSER_ACCEPTANCE=1 for real Chrome acceptance",
)
def test_m15_real_browser_track_c(tmp_path: Path) -> None:
    module = _module()
    report = module.run(tmp_path / "browser")  # type: ignore[attr-defined]
    assert report["status"] == "passed"
    assert report["provider_constructions"] == 0
    assert report["remote_requests"] == 0
    assert report["m12_solve_or_destination_requests"] == 0
