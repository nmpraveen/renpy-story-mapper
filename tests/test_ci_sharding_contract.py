from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest
from scripts.ci_aggregate import evaluate_truth_table
from scripts.ci_changed_files import classify_changes
from scripts.ci_pytest_shard import (
    ShardConfig,
    ShardConfigurationError,
    assign_collected_nodes,
    build_plan,
    build_proof,
    load_and_validate_plan,
    load_shard_config,
)
from scripts.ci_verify_shards import verify_reports

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "scripts" / "ci-pytest-shards.json"
WORKFLOW = ROOT / ".github" / "workflows" / "pull-request-checks.yml"
VALIDATION_SCRIPT = ROOT / "scripts" / "validate.ps1"
LONG_LIVE_TESTS = (
    "tests/test_m13_live_acceptance.py::"
    "test_live_acceptance_preview_never_submits_and_exact_confirmation_replays",
    "tests/test_m13_live_acceptance.py::"
    "test_live_acceptance_retains_two_partial_scenes_and_replays_without_calls",
)


def _configuration_payload() -> dict[str, object]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def test_repository_collection_is_complete_disjoint_and_deterministic(tmp_path: Path) -> None:
    proof_one = tmp_path / "proof-one.json"
    proof_two = tmp_path / "proof-two.json"

    for proof in (proof_one, proof_two):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "ci_pytest_shard.py"),
                "--verify-only",
                "--proof-json",
                str(proof),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    first = json.loads(proof_one.read_text(encoding="utf-8"))
    second = json.loads(proof_two.read_text(encoding="utf-8"))
    assert first == second
    assert first["lane_count"] == 4
    assert first["collected_count"] > 1_400
    assert sum(lane["node_count"] for lane in first["lanes"]) == first["collected_count"]
    assert len({lane["node_sha256"] for lane in first["lanes"]}) == 4


def test_two_long_m13_live_acceptance_tests_are_in_different_stable_lanes() -> None:
    config = load_shard_config(CONFIG)
    assignments = assign_collected_nodes(config, LONG_LIVE_TESTS)
    owners = {
        node: lane_id
        for lane_id, nodes in assignments.items()
        for node in nodes
    }

    assert owners[LONG_LIVE_TESTS[0]] != owners[LONG_LIVE_TESTS[1]]
    assert owners == {
        LONG_LIVE_TESTS[0]: "shard-1",
        LONG_LIVE_TESTS[1]: "shard-2",
    }


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda payload: payload["lanes"].pop(), "exactly four lanes"),
        (
            lambda payload: payload["lanes"][1]["files"].append(
                payload["lanes"][0]["files"][0]
            ),
            "assigned more than once",
        ),
        (
            lambda payload: payload["lanes"][0].update({"id": "unstable-name"}),
            "lane IDs",
        ),
    ],
)
def test_invalid_shard_settings_fail_closed(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    payload = _configuration_payload()
    mutation(payload)  # type: ignore[operator]
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ShardConfigurationError, match=message):
        load_shard_config(invalid)


def test_workflow_keeps_stable_aggregate_check_and_all_required_lanes() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("name: Deterministic checks (Python 3.12)") == 1
    for dependency in (
        "classify-changes",
        "workflow-contract",
        "test-plan",
        "quality",
        "package",
        "deterministic-pytest",
    ):
        assert f"      - {dependency}" in workflow
    assert "if: ${{ always() }}" in workflow
    assert "matrix:" in workflow
    for lane in ("shard-1", "shard-2", "shard-3", "shard-4"):
        assert lane in workflow
    assert "timeout-minutes:" not in workflow
    assert "CLASSIFIER_RESULT" in workflow
    assert "CONTRACT_RESULT" in workflow
    assert "SHARDS_RESULT" in workflow
    assert "python scripts/ci_aggregate.py" in workflow


def test_workflow_exposes_durations_junit_and_streamed_test_output() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "--durations=50" in workflow
    assert "--junit-xml" in workflow
    assert "actions/upload-artifact@" in workflow
    assert "if: ${{ always() }}" in workflow
    assert "ci-shard-${{ matrix.shard }}" in workflow


def test_main_whitespace_check_is_cumulative_across_cancelled_runs() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    whitespace_step = workflow.split("- name: Check changed whitespace", 1)[1].split(
        "- name: Set up Python",
        1,
    )[0]

    assert "github.event.pull_request.number || github.ref" in workflow
    assert "github.event.pull_request.base.sha" in whitespace_step
    assert "$emptyTree = @() | git mktree" in whitespace_step
    assert 'git diff --check "$emptyTree..HEAD" --' in whitespace_step
    assert "github.event.before" not in whitespace_step


def test_tracked_head_passes_functional_empty_tree_whitespace_check() -> None:
    empty_tree = subprocess.run(
        ["git", "mktree"],
        cwd=ROOT,
        input="",
        capture_output=True,
        text=True,
        check=False,
    )
    assert empty_tree.returncode == 0, empty_tree.stderr

    whitespace = subprocess.run(
        ["git", "diff", "--check", f"{empty_tree.stdout.strip()}..HEAD", "--"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert whitespace.returncode == 0, whitespace.stdout + whitespace.stderr


def test_release_validation_preserves_no_timeout_and_streams_subprocesses() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    validation = VALIDATION_SCRIPT.read_text(encoding="utf-8")

    assert "validate.ps1 -Tier Release -ReleaseComponent Quality -NoTimeout" in workflow
    assert "validate.ps1 -Tier Release -ReleaseComponent Package -NoTimeout" in workflow
    assert "RedirectStandardOutput = $true" in validation
    assert "RedirectStandardError = $true" in validation
    assert "ReadLineAsync" in validation
    assert "ValidationProcessJob" in validation
    assert "ReadToEndAsync" not in validation


@pytest.mark.parametrize(
    "event_name, head_ref, changes, expected",
    [
        ("pull_request", "codex/docs", (("M", "docs/guide.md"),), "docs-only"),
        ("pull_request", "codex/docs", (("A", "docs/new.md"),), "docs-only"),
        ("pull_request", "codex/docs", (("D", "docs/old.md"),), "full"),
        (
            "pull_request",
            "codex/docs",
            (("R100", "docs/old.md", "docs/new.md"),),
            "full",
        ),
        ("pull_request", "codex/docs", (("M", "src/product.py"),), "full"),
        ("pull_request", "codex/docs", (), "full"),
        ("push", "", (("M", "docs/guide.md"),), "full"),
        (
            "pull_request",
            "codex/m15-phase04-full-game",
            (("M", "docs/guide.md"),),
            "full",
        ),
    ],
)
def test_changed_file_classifier_fails_closed(
    event_name: str,
    head_ref: str,
    changes: tuple[tuple[str, ...], ...],
    expected: str,
) -> None:
    assert classify_changes(event_name, head_ref, changes) == expected


def _four_lane_sample() -> tuple[
    ShardConfig,
    tuple[str, ...],
    dict[str, tuple[str, ...]],
]:
    config = load_shard_config(CONFIG)
    nodes = (
        LONG_LIVE_TESTS[0] + "[case-a]",
        LONG_LIVE_TESTS[1] + "[case-b]",
        f"{config.lanes[2].files[0]}::test_sample_lane_three",
        f"{config.lanes[3].files[0]}::test_sample_lane_four",
    )
    assignments = assign_collected_nodes(config, nodes, require_nonempty_lanes=True)
    return config, nodes, assignments


def test_parameterized_long_test_proof_resolves_without_stop_iteration() -> None:
    config, nodes, assignments = _four_lane_sample()
    proof = build_proof(config, nodes, assignments)

    assert proof["long_test_lanes"] == {
        LONG_LIVE_TESTS[0]: "shard-1",
        LONG_LIVE_TESTS[1]: "shard-2",
    }


def test_plan_round_trip_and_four_report_verifier(tmp_path: Path) -> None:
    config, nodes, assignments = _four_lane_sample()
    plan = build_plan(
        config_path=CONFIG,
        config=config,
        node_ids=nodes,
        assignments=assignments,
    )
    plan_path = tmp_path / "ci-test-plan.json"
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    loaded_nodes, loaded_assignments, loaded_plan = load_and_validate_plan(
        plan_path,
        config_path=CONFIG,
        config=config,  # type: ignore[arg-type]
    )
    assert loaded_nodes == nodes
    assert loaded_assignments == assignments
    assert loaded_plan == plan

    artifacts = tmp_path / "artifacts"
    collection_sha256 = plan["proof"]["collection_sha256"]
    for lane_id, lane_nodes in assignments.items():
        lane_root = artifacts / f"ci-shard-{lane_id}"
        lane_root.mkdir(parents=True)
        junit_name = f"junit-{lane_id}.xml"
        suite = ElementTree.Element(
            "testsuite",
            tests=str(len(lane_nodes)),
            failures="0",
            errors="0",
            skipped="0",
        )
        ElementTree.ElementTree(suite).write(
            lane_root / junit_name,
            encoding="utf-8",
            xml_declaration=True,
        )
        lane_proof = next(item for item in plan["proof"]["lanes"] if item["id"] == lane_id)
        report = {
            "schema_version": 1,
            "lane_id": lane_id,
            "collection_sha256": collection_sha256,
            "selected_count": len(lane_nodes),
            "selected_sha256": lane_proof["node_sha256"],
            "selected_nodes": list(lane_nodes),
            "durations": 50,
            "exit_code": 0,
            "junit_file": junit_name,
            "junit_counts": {
                "tests": len(lane_nodes),
                "failures": 0,
                "errors": 0,
                "skipped": 0,
            },
        }
        (lane_root / f"selection-{lane_id}.json").write_text(
            json.dumps(report),
            encoding="utf-8",
        )

    result = verify_reports(plan_path, artifacts)
    assert result["status"] == "passed"
    assert result["tests"] == 4


def test_aggregate_truth_table_accepts_only_exact_full_or_docs_states() -> None:
    fixed = {"classifier": "success", "contract": "success"}
    assert evaluate_truth_table(
        "true",
        fixed | {name: "success" for name in ("plan", "quality", "package", "shards")},
    )
    assert not evaluate_truth_table(
        "false",
        fixed | {name: "skipped" for name in ("plan", "quality", "package", "shards")},
    )
    for run_full, bad_state in (("true", "skipped"), ("false", "success")):
        expected_state = "success" if run_full == "true" else "skipped"
        results = fixed | {
            name: bad_state if name == "shards" else expected_state
            for name in ("plan", "quality", "package", "shards")
        }
        with pytest.raises(ValueError):
            evaluate_truth_table(run_full, results)
