from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts" / "m12_scale_acceptance.py"


def _module() -> object:
    spec = importlib.util.spec_from_file_location("m12_scale_acceptance", HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_m12_scale_harness_contract_is_target_specific_and_deterministic() -> None:
    source = HARNESS.read_text(encoding="utf-8")
    for marker in (
        "M12RouteService",
        "load_m12_authority",
        "solve_route",
        "numeric_projection",
        "pure_expansion_replay_identical",
        "cache_replay_identical",
        "all_target_preprocessing",
        "selected_target_solves",
        "limit_profile",
        "expanded_states",
        "retained_states",
        "peak_frontier_states",
        "prefix_records",
        "bounded_alternatives",
        "bounded_loop",
        "numeric_thresholds",
        "hardware_sensitive",
        "semantic_pass_fail_uses_these_values",
        "source_unchanged",
        "--output-dir",
    ):
        assert marker in source
    module = _module()
    assert module.STATEMENT_COUNTS == (24, 48, 96)  # type: ignore[attr-defined]


def test_m12_scale_harness_runs_a_bounded_real_project_matrix(tmp_path: Path) -> None:
    module = _module()
    report = module.run(  # type: ignore[attr-defined]
        tmp_path / "scale",
        statement_counts=(4, 8),
        include_complex=True,
    )
    assert report["status"] == "passed"
    assert report["target_specific"] is True
    assert report["all_target_preprocessing"] is False
    complex_result = report["complex_workload"]
    assert complex_result["bounded_alternatives"] is True
    assert complex_result["bounded_loop"] is True
    assert complex_result["cache_replay"] is True
    persisted = json.loads((tmp_path / "scale" / "acceptance.json").read_text(encoding="utf-8"))
    assert persisted == report
    observations = json.loads(
        (tmp_path / "scale" / "observations.json").read_text(encoding="utf-8")
    )
    assert observations["hardware_sensitive"] is True
    assert observations["semantic_pass_fail_uses_these_values"] is False


def test_m12_scale_harness_help_uses_the_output_directory_contract() -> None:
    completed = subprocess.run(
        [sys.executable, str(HARNESS), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "--output-dir" in completed.stdout
