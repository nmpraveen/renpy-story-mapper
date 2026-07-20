from __future__ import annotations

import importlib.util
import os
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
        "#fitMap",
        "scaled",
        "restored_scale",
        "new PointerEvent('pointerdown'",
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
