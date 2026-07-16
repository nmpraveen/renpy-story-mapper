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
        "accounting_units",
        "serialized_prefix_bytes",
        "completed_under_normal_v1_budgets",
        "exact_linear_parent_prefix",
        "--profile",
        "linear-prefix",
        "--linear-edge-counts",
        "bounded_alternatives",
        "bounded_loop",
        "exact_loop_acceleration",
        "numeric_thresholds",
        "hardware_sensitive",
        "semantic_pass_fail_uses_these_values",
        "source_unchanged",
        "--output-dir",
    ):
        assert marker in source
    module = _module()
    assert module.STATEMENT_COUNTS == (24, 48, 96)  # type: ignore[attr-defined]
    assert module.LINEAR_EDGE_COUNTS == (500, 1_000, 2_000)  # type: ignore[attr-defined]


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
    assert complex_result["exact_loop_acceleration"] is True
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
    assert "--profile" in completed.stdout
    assert "linear-prefix" in completed.stdout
    assert "--linear-edge-counts" in completed.stdout


def test_exact_linear_profile_emits_deterministic_report_bytes(tmp_path: Path) -> None:
    module = _module()
    first = module.run_exact_linear_scale(  # type: ignore[attr-defined]
        tmp_path / "first",
        edge_counts=(9,),
    )
    second = module.run_exact_linear_scale(  # type: ignore[attr-defined]
        tmp_path / "second",
        edge_counts=(9,),
    )
    first_bytes = (tmp_path / "first" / "acceptance.json").read_bytes()
    second_bytes = (tmp_path / "second" / "acceptance.json").read_bytes()

    assert first == second
    assert first_bytes == second_bytes
    assert first["profile"] == "exact_linear_parent_prefix"
    measurement = first["linear_measurements"][0]
    assert measurement["requested_route_edges"] == 9
    assert measurement["route_edge_count"] == 9
    assert measurement["complete"] is True
    assert measurement["completed_under_normal_v1_budgets"] is True
    assert measurement["accounting_units"] > 0
    assert measurement["serialized_prefix_bytes"] > 0


def test_exact_linear_profile_cli_accepts_a_focused_edge_matrix(tmp_path: Path) -> None:
    output_dir = tmp_path / "cli"
    completed = subprocess.run(
        [
            sys.executable,
            str(HARNESS),
            "--output-dir",
            str(output_dir),
            "--profile",
            "linear-prefix",
            "--linear-edge-counts",
            "9",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["edge_counts"] == [9]
    assert report["linear_measurements"][0]["route_edge_count"] == 9


def test_exact_linear_doubling_contract_rejects_superlinear_accounting() -> None:
    module = _module()
    lower = _growth_measurement(500, accounting_units=5_000, serialized_prefix_bytes=50_000)
    upper = _growth_measurement(1_000, accounting_units=10_000, serialized_prefix_bytes=100_000)
    growth = module._exact_linear_growth(lower, upper)  # type: ignore[attr-defined]
    assert growth["accounting_units_growth"] == 2.0
    assert growth["serialized_prefix_bytes_growth"] == 2.0

    upper["accounting_units"] = 20_000
    try:
        module._exact_linear_growth(lower, upper)  # type: ignore[attr-defined]
    except AssertionError as exc:
        assert "accounting_units growth" in str(exc)
    else:
        raise AssertionError("quadratic accounting growth was accepted")


def _growth_measurement(
    route_edges: int,
    *,
    accounting_units: int,
    serialized_prefix_bytes: int,
) -> dict[str, int]:
    return {
        "requested_route_edges": route_edges,
        "expanded_states": route_edges,
        "retained_states": route_edges,
        "prefix_records": route_edges + 1,
        "accounting_units": accounting_units,
        "serialized_prefix_bytes": serialized_prefix_bytes,
        "result_bytes": route_edges * 100,
    }
