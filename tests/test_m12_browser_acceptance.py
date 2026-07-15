from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts" / "m12_browser_acceptance.py"


def _module() -> object:
    spec = importlib.util.spec_from_file_location("m12_browser_acceptance", HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_m12_real_browser_harness_covers_the_local_route_workflow() -> None:
    source = HARNESS.read_text(encoding="utf-8")
    for marker in (
        "LocalWebServer",
        "ProjectApi",
        "M12RouteService",
        "create_ingested_project",
        "forbidden_provider",
        "Browser.setDownloadBehavior",
        "How do I reach this?",
        "Confirmed route",
        "Route with prerequisites",
        "Best known route",
        "No proven route",
        "m12-route-result-{zoom}.png",
        "m12-route-evidence-{zoom}.png",
        "cancelRoute",
        "retryRoute",
        "routeTechnical",
        "route-provenance",
        "openRouteEvidence",
        "exportRouteJson",
        "detail_evidence",
        "route_map",
        "remote_requests",
        "provider_constructions",
        "creator_or_game_executions",
        "source_fingerprints",
        "_browser_diagnostics",
        "sha256",
        "--output-dir",
    ):
        assert marker in source
    module = _module()
    assert module.ZOOMS == (100, 200)  # type: ignore[attr-defined]
    assert module.BADGES == (  # type: ignore[attr-defined]
        "Confirmed route",
        "Route with prerequisites",
        "Best known route",
        "No proven route",
    )


def test_m12_browser_harness_help_uses_the_output_directory_contract() -> None:
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
    reason="set RSM_RUN_BROWSER_ACCEPTANCE=1 for the real Chrome/Edge acceptance",
)
def test_m12_real_browser_bounded_run(tmp_path: Path) -> None:
    module = _module()
    report = module.run(tmp_path / "browser")  # type: ignore[attr-defined]
    assert report["status"] == "passed"
    assert report["remote_requests"] == 0
    assert report["provider_constructions"] == 0
