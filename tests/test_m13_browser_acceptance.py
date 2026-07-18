from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts" / "m13_browser_acceptance.py"


def _module() -> object:
    spec = importlib.util.spec_from_file_location("m13_browser_acceptance", HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_m13_real_browser_harness_covers_narrative_consent_and_evidence() -> None:
    source = HARNESS.read_text(encoding="utf-8")
    for marker in (
        "LocalWebServer",
        "ProjectApi",
        "SimulatedNarrativeProvider",
        "create_ingested_project",
        "narrativeToggle",
        "narrativeConsentDialog",
        "Requested / resolved model",
        "Provider settings",
        "Consent manifest",
        "Selected scope",
        "Privacy mode",
        "Logical jobs",
        "Estimated provider calls",
        "Estimated tokens",
        "Estimated cost",
        "Hard limits",
        "M12 material",
        "interpretationPanel",
        "narrative-citation-selection",
        "Open Detail and Evidence",
        "detail_evidence",
        "route_map",
        "deterministic_title_restored",
        "cache_replay",
        "remote_requests",
        "source_fingerprints",
        "authority_snapshots",
        "m13-consent-{zoom}.png",
        "m13-narrative-detail-{zoom}.png",
        "m13-job-drawer-{zoom}.png",
        "_browser_diagnostics",
        "--output-dir",
    ):
        assert marker in source
    module = _module()
    assert module.ZOOMS == (100, 200)  # type: ignore[attr-defined]
    assert module.CONSENT_FIELDS == (  # type: ignore[attr-defined]
        "Provider",
        "Requested / resolved model",
        "Provider settings",
        "Consent manifest",
        "Selected scope",
        "Privacy mode",
        "Logical jobs",
        "Estimated provider calls",
        "Estimated tokens",
        "Estimated cost",
        "Hard limits",
        "M12 material",
    )


def test_m13_browser_harness_help_uses_the_output_directory_contract() -> None:
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
def test_m13_real_browser_narrative_run(tmp_path: Path) -> None:
    module = _module()
    report = module.run(tmp_path / "browser")  # type: ignore[attr-defined]
    assert report["status"] == "passed"
    assert report["remote_requests"] == 0
    assert report["navigation_levels"] == ["route_map", "detail_evidence"]
