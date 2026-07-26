from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "scripts" / "ci-pytest-shards.json"
EXPECTED_LANE_IDS = ("shard-1", "shard-2", "shard-3", "shard-4")


class ShardConfigurationError(ValueError):
    """Raised when the explicit CI shard contract is incomplete or ambiguous."""


@dataclass(frozen=True)
class ShardLane:
    lane_id: str
    files: tuple[str, ...]
    nodes: tuple[str, ...]


@dataclass(frozen=True)
class ShardConfig:
    marker_expression: str
    timing_file: str
    lanes: tuple[ShardLane, ...]
    long_test_nodes: tuple[str, ...]
    estimated_lane_seconds: tuple[float, ...]


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ShardConfigurationError(f"{field} must be a non-empty string")
    return value


def _require_string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ShardConfigurationError(f"{field} must be a list of strings")
    return tuple(value)


def load_shard_config(path: Path = DEFAULT_CONFIG) -> ShardConfig:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShardConfigurationError(f"cannot read shard configuration {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ShardConfigurationError("shard configuration version must be exactly 1")

    marker_expression = _require_string(payload.get("marker_expression"), "marker_expression")
    lane_payloads = payload.get("lanes")
    if not isinstance(lane_payloads, list) or len(lane_payloads) != 4:
        raise ShardConfigurationError("shard configuration must contain exactly four lanes")

    lanes: list[ShardLane] = []
    file_owners: dict[str, str] = {}
    node_owners: dict[str, str] = {}
    for index, lane_payload in enumerate(lane_payloads):
        if not isinstance(lane_payload, dict):
            raise ShardConfigurationError(f"lanes[{index}] must be an object")
        lane_id = _require_string(lane_payload.get("id"), f"lanes[{index}].id")
        files = _require_string_list(lane_payload.get("files"), f"lanes[{index}].files")
        nodes = _require_string_list(lane_payload.get("nodes", []), f"lanes[{index}].nodes")
        if not files:
            raise ShardConfigurationError(f"lane {lane_id} must contain at least one test file")
        for file_path in files:
            normalized = file_path.replace("\\", "/")
            if normalized != file_path or not normalized.startswith("tests/test_"):
                raise ShardConfigurationError(
                    f"invalid test file path {file_path!r}; "
                    "use tests/test_*.py with forward slashes"
                )
            if normalized in file_owners:
                raise ShardConfigurationError(
                    f"test file {normalized} is assigned more than once: "
                    f"{file_owners[normalized]} and {lane_id}"
                )
            file_owners[normalized] = lane_id
        for node_id in nodes:
            normalized = node_id.replace("\\", "/")
            if normalized != node_id or "::" not in normalized:
                raise ShardConfigurationError(
                    f"invalid node override {node_id!r}; use a full pytest node ID"
                )
            if normalized in node_owners:
                raise ShardConfigurationError(
                    f"test node {normalized} is assigned more than once: "
                    f"{node_owners[normalized]} and {lane_id}"
                )
            node_owners[normalized] = lane_id
        lanes.append(ShardLane(lane_id=lane_id, files=files, nodes=nodes))

    actual_lane_ids = tuple(lane.lane_id for lane in lanes)
    if actual_lane_ids != EXPECTED_LANE_IDS:
        raise ShardConfigurationError(
            f"lane IDs and order must be exactly {', '.join(EXPECTED_LANE_IDS)}"
        )

    for node_id in node_owners:
        file_path = node_id.split("::", 1)[0]
        if file_path not in file_owners:
            raise ShardConfigurationError(
                f"node override {node_id} belongs to unassigned test file {file_path}"
            )

    long_test_nodes = _require_string_list(payload.get("long_test_nodes"), "long_test_nodes")
    if len(long_test_nodes) != 2 or set(long_test_nodes) != set(node_owners):
        raise ShardConfigurationError(
            "long_test_nodes must name exactly the two explicit node overrides"
        )
    long_owners = {node_owners[node_id] for node_id in long_test_nodes}
    if len(long_owners) != 2:
        raise ShardConfigurationError("the two long tests must be assigned to different lanes")

    timing_file = _require_string(payload.get("timing_file"), "timing_file")
    if not timing_file.startswith("scripts/") or ".." in Path(timing_file).parts:
        raise ShardConfigurationError("timing_file must be a repository scripts/ path")
    timing_path = ROOT / timing_file
    try:
        timing_payload: Any = json.loads(timing_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        message = f"cannot read frozen timing file {timing_path}: {exc}"
        raise ShardConfigurationError(message) from exc
    if not isinstance(timing_payload, dict) or timing_payload.get("version") != 1:
        raise ShardConfigurationError("frozen timing file version must be exactly 1")
    file_seconds = timing_payload.get("file_seconds")
    long_seconds = timing_payload.get("long_test_seconds")
    if not isinstance(file_seconds, dict) or set(file_seconds) != set(file_owners):
        raise ShardConfigurationError(
            "frozen timing files must exactly match explicit shard test files"
        )
    if not isinstance(long_seconds, dict) or set(long_seconds) != set(long_test_nodes):
        raise ShardConfigurationError(
            "frozen long-test timings must exactly match explicit node overrides"
        )
    all_weights = (*file_seconds.values(), *long_seconds.values())
    if not all(isinstance(value, (int, float)) and value > 0 for value in all_weights):
        raise ShardConfigurationError("every frozen timing weight must be a positive number")

    expected_files: dict[str, set[str]] = {lane_id: set() for lane_id in EXPECTED_LANE_IDS}
    estimated_totals = [0.0, 0.0, 0.0, 0.0]
    for node_id, seconds in long_seconds.items():
        estimated_totals[EXPECTED_LANE_IDS.index(node_owners[node_id])] += float(seconds)
    for file_path, seconds in sorted(
        file_seconds.items(),
        key=lambda item: (-float(item[1]), item[0]),
    ):
        lane_index = min(range(4), key=lambda index: (estimated_totals[index], index))
        expected_files[EXPECTED_LANE_IDS[lane_index]].add(file_path)
        estimated_totals[lane_index] += float(seconds)
    for lane in lanes:
        if set(lane.files) != expected_files[lane.lane_id]:
            raise ShardConfigurationError(
                f"lane {lane.lane_id} is not the deterministic frozen-timing LPT assignment"
            )

    return ShardConfig(
        marker_expression=marker_expression,
        timing_file=timing_file,
        lanes=tuple(lanes),
        long_test_nodes=long_test_nodes,
        estimated_lane_seconds=tuple(round(value, 6) for value in estimated_totals),
    )


def validate_repository_files(config: ShardConfig, root: Path = ROOT) -> None:
    configured = {file_path for lane in config.lanes for file_path in lane.files}
    discovered = {
        path.relative_to(root).as_posix()
        for path in (root / "tests").glob("test_*.py")
        if path.is_file()
    }
    missing = sorted(discovered - configured)
    stale = sorted(configured - discovered)
    if missing or stale:
        raise ShardConfigurationError(
            "explicit shard files do not exactly match repository tests; "
            f"unassigned={missing}, stale={stale}"
        )


def _matches_override(node_id: str, override: str) -> bool:
    return node_id == override or node_id.startswith(override + "[")


def assign_collected_nodes(
    config: ShardConfig,
    node_ids: Sequence[str],
    *,
    require_nonempty_lanes: bool = False,
) -> dict[str, tuple[str, ...]]:
    file_owners = {
        file_path: lane.lane_id for lane in config.lanes for file_path in lane.files
    }
    node_owners = {node_id: lane.lane_id for lane in config.lanes for node_id in lane.nodes}
    matched_overrides: set[str] = set()
    assignments: dict[str, list[str]] = {lane.lane_id: [] for lane in config.lanes}
    seen: set[str] = set()

    for raw_node_id in node_ids:
        node_id = raw_node_id.replace("\\", "/")
        if node_id in seen:
            raise ShardConfigurationError(f"pytest collected duplicate node ID {node_id}")
        seen.add(node_id)
        file_path = node_id.split("::", 1)[0]
        if file_path not in file_owners:
            raise ShardConfigurationError(f"collected node is not assigned to a lane: {node_id}")
        matches = [override for override in node_owners if _matches_override(node_id, override)]
        if len(matches) > 1:
            raise ShardConfigurationError(
                f"collected node matches multiple explicit overrides: {node_id}: {matches}"
            )
        if matches:
            matched_overrides.add(matches[0])
            owner = node_owners[matches[0]]
        else:
            owner = file_owners[file_path]
        assignments[owner].append(node_id)

    unmatched = sorted(set(node_owners) - matched_overrides)
    if unmatched:
        raise ShardConfigurationError(f"configured node overrides were not collected: {unmatched}")
    if not seen:
        raise ShardConfigurationError("pytest collection produced no deterministic test nodes")
    if require_nonempty_lanes and any(not assignments[lane.lane_id] for lane in config.lanes):
        raise ShardConfigurationError("every configured lane must receive at least one test node")

    return {lane_id: tuple(nodes) for lane_id, nodes in assignments.items()}


def _collection_environment(root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    source_path = str(root / "src")
    current_python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        source_path
        if not current_python_path
        else source_path + os.pathsep + current_python_path
    )
    environment["PYTHONHASHSEED"] = "0"
    return environment


def collect_deterministic_nodes(config: ShardConfig, root: Path = ROOT) -> tuple[str, ...]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "-m",
        config.marker_expression,
    ]
    result = subprocess.run(
        command,
        cwd=root,
        env=_collection_environment(root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ShardConfigurationError(
            "pytest collection failed before sharding:\n" + result.stdout + result.stderr
        )
    node_ids = tuple(
        line.strip().replace("\\", "/")
        for line in result.stdout.splitlines()
        if line.strip().replace("\\", "/").startswith("tests/") and "::" in line
    )
    return node_ids


def _sha256_lines(lines: Sequence[str]) -> str:
    payload = "".join(f"{line}\n" for line in lines).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_proof(
    config: ShardConfig,
    node_ids: Sequence[str],
    assignments: dict[str, tuple[str, ...]],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "marker_expression": config.marker_expression,
        "lane_count": len(config.lanes),
        "collected_count": len(node_ids),
        "collection_sha256": _sha256_lines(node_ids),
        "estimated_lane_seconds": {
            lane.lane_id: config.estimated_lane_seconds[index]
            for index, lane in enumerate(config.lanes)
        },
        "long_test_lanes": _long_test_lane_proof(config, assignments),
        "lanes": [
            {
                "id": lane.lane_id,
                "node_count": len(assignments[lane.lane_id]),
                "node_sha256": _sha256_lines(assignments[lane.lane_id]),
            }
            for lane in config.lanes
        ],
    }


def _long_test_lane_proof(
    config: ShardConfig,
    assignments: dict[str, tuple[str, ...]],
) -> dict[str, str]:
    proof: dict[str, str] = {}
    for override in config.long_test_nodes:
        owners = {
            lane_id
            for lane_id, nodes in assignments.items()
            if any(_matches_override(node_id, override) for node_id in nodes)
        }
        if len(owners) != 1:
            raise ShardConfigurationError(
                f"long-test override {override} must resolve to exactly one lane; "
                f"resolved={sorted(owners)}"
            )
        proof[override] = owners.pop()
    return proof


def build_plan(
    *,
    config_path: Path,
    config: ShardConfig,
    node_ids: Sequence[str],
    assignments: dict[str, tuple[str, ...]],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "config_sha256": _sha256_file(config_path),
        "timing_sha256": _sha256_file(ROOT / config.timing_file),
        "proof": build_proof(config, node_ids, assignments),
        "collected_nodes": list(node_ids),
        "assignments": {
            lane.lane_id: list(assignments[lane.lane_id]) for lane in config.lanes
        },
    }


def load_and_validate_plan(
    path: Path,
    *,
    config_path: Path,
    config: ShardConfig,
) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]], dict[str, object]]:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShardConfigurationError(f"cannot read CI test plan {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ShardConfigurationError("CI test plan schema_version must be exactly 1")
    if payload.get("config_sha256") != _sha256_file(config_path):
        raise ShardConfigurationError("CI test plan does not match the exact shard configuration")
    if payload.get("timing_sha256") != _sha256_file(ROOT / config.timing_file):
        raise ShardConfigurationError("CI test plan does not match the frozen timing weights")
    raw_nodes = payload.get("collected_nodes")
    if not isinstance(raw_nodes, list) or not all(isinstance(item, str) for item in raw_nodes):
        raise ShardConfigurationError("CI test plan collected_nodes must be a list of strings")
    node_ids = tuple(raw_nodes)
    assignments = assign_collected_nodes(config, node_ids, require_nonempty_lanes=True)
    expected = build_plan(
        config_path=config_path,
        config=config,
        node_ids=node_ids,
        assignments=assignments,
    )
    if payload != expected:
        raise ShardConfigurationError(
            "CI test plan assignments or proof do not match the collected inventory"
        )
    return node_ids, assignments, payload


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_shard(
    *,
    root: Path,
    lane_id: str,
    nodes: Sequence[str],
    canonical_nodes: Sequence[str],
    marker_expression: str,
    junit_xml: Path,
    selection_json: Path,
    durations: int,
    collection_sha256: str,
) -> int:
    junit_xml.parent.mkdir(parents=True, exist_ok=True)
    selection_json.parent.mkdir(parents=True, exist_ok=True)
    import pytest

    class ExactSelectionPlugin:
        @pytest.hookimpl(trylast=True)
        def pytest_collection_modifyitems(self, config: Any, items: list[Any]) -> None:
            actual_nodes = tuple(item.nodeid.replace("\\", "/") for item in items)
            if actual_nodes != tuple(canonical_nodes):
                raise ShardConfigurationError(
                    "in-process pytest inventory drifted from the canonical plan; "
                    f"planned={len(canonical_nodes)}, actual={len(actual_nodes)}"
                )
            selected_set = set(nodes)
            selected_items = [
                item for item in items if item.nodeid.replace("\\", "/") in selected_set
            ]
            selected_ids = {item.nodeid.replace("\\", "/") for item in selected_items}
            missing = sorted(selected_set - selected_ids)
            if missing:
                raise ShardConfigurationError(
                    f"in-process pytest collection omitted planned nodes: {missing[:5]}"
                )
            deselected = [item for item in items if item not in selected_items]
            items[:] = selected_items
            config.hook.pytest_deselected(items=deselected)

    arguments = [
        "-q",
        "-m",
        marker_expression,
        f"--durations={durations}",
        f"--junitxml={junit_xml}",
        "tests",
    ]
    print(
        f"Running {lane_id}: {len(nodes)} deterministic tests; "
        f"JUnit={junit_xml}; durations={durations}",
        flush=True,
    )
    previous_directory = Path.cwd()
    previous_python_path = os.environ.get("PYTHONPATH")
    previous_hash_seed = os.environ.get("PYTHONHASHSEED")
    import_paths = (str(root), str(root / "src"))
    inserted_paths = [path for path in import_paths if path not in sys.path]
    for path in reversed(inserted_paths):
        sys.path.insert(0, path)
    os.chdir(root)
    os.environ.update(_collection_environment(root))
    try:
        exit_code = int(pytest.main(arguments, plugins=[ExactSelectionPlugin()]))
    finally:
        os.chdir(previous_directory)
        if previous_python_path is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = previous_python_path
        if previous_hash_seed is None:
            os.environ.pop("PYTHONHASHSEED", None)
        else:
            os.environ["PYTHONHASHSEED"] = previous_hash_seed
        for path in inserted_paths:
            sys.path.remove(path)

    junit_counts: dict[str, int] = {}
    if junit_xml.is_file():
        root_element = ElementTree.parse(junit_xml).getroot()
        suites = [root_element] if root_element.tag == "testsuite" else list(root_element)
        for field in ("tests", "failures", "errors", "skipped"):
            junit_counts[field] = sum(int(suite.attrib.get(field, "0")) for suite in suites)
    report = {
        "schema_version": 1,
        "lane_id": lane_id,
        "collection_sha256": collection_sha256,
        "selected_count": len(nodes),
        "selected_sha256": _sha256_lines(nodes),
        "selected_nodes": list(nodes),
        "durations": durations,
        "exit_code": exit_code,
        "junit_file": junit_xml.name,
        "junit_counts": junit_counts,
    }
    _write_json(selection_json, report)
    return exit_code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify and run one explicit deterministic pytest CI shard."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--shard", choices=EXPECTED_LANE_IDS)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--write-plan", type=Path)
    parser.add_argument("--plan-json", type=Path)
    parser.add_argument("--proof-json", type=Path)
    parser.add_argument("--junit-xml", type=Path)
    parser.add_argument("--selection-json", type=Path)
    parser.add_argument("--durations", type=int, default=50)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    selected_modes = sum(
        (arguments.verify_only, arguments.write_plan is not None, arguments.shard is not None)
    )
    if selected_modes != 1:
        raise ShardConfigurationError(
            "choose exactly one of --verify-only, --write-plan, or --shard"
        )
    if arguments.durations < 0:
        raise ShardConfigurationError("--durations must be non-negative")
    if arguments.shard and arguments.junit_xml is None:
        raise ShardConfigurationError("--junit-xml is required when running a shard")
    if arguments.shard and arguments.selection_json is None:
        raise ShardConfigurationError("--selection-json is required when running a shard")
    if arguments.shard and arguments.plan_json is None:
        raise ShardConfigurationError("--plan-json is required when running a shard")
    if arguments.plan_json is not None and arguments.shard is None:
        raise ShardConfigurationError("--plan-json is valid only with --shard")

    config = load_shard_config(arguments.config)
    validate_repository_files(config, ROOT)
    if arguments.shard:
        node_ids, assignments, plan = load_and_validate_plan(
            arguments.plan_json,
            config_path=arguments.config,
            config=config,
        )
        proof = plan["proof"]
        if not isinstance(proof, dict):
            raise ShardConfigurationError("CI test plan proof must be an object")
        live_node_ids = collect_deterministic_nodes(config, ROOT)
        if live_node_ids != node_ids:
            raise ShardConfigurationError(
                "lane collection does not exactly match the canonical CI test plan inventory"
            )
        live_assignments = assign_collected_nodes(
            config,
            live_node_ids,
            require_nonempty_lanes=True,
        )
        if live_assignments != assignments:
            raise ShardConfigurationError(
                "lane assignment does not exactly match the canonical CI test plan"
            )
    else:
        node_ids = collect_deterministic_nodes(config, ROOT)
        assignments = assign_collected_nodes(config, node_ids, require_nonempty_lanes=True)
        proof = build_proof(config, node_ids, assignments)
        if arguments.write_plan:
            _write_json(
                arguments.write_plan,
                build_plan(
                    config_path=arguments.config,
                    config=config,
                    node_ids=node_ids,
                    assignments=assignments,
                ),
            )
    if arguments.proof_json:
        _write_json(arguments.proof_json, proof)
    print(json.dumps(proof, sort_keys=True), flush=True)
    if arguments.verify_only or arguments.write_plan:
        return 0
    return run_shard(
        root=ROOT,
        lane_id=arguments.shard,
        nodes=assignments[arguments.shard],
        canonical_nodes=node_ids,
        marker_expression=config.marker_expression,
        junit_xml=arguments.junit_xml,
        selection_json=arguments.selection_json,
        durations=arguments.durations,
        collection_sha256=str(proof["collection_sha256"]),
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ShardConfigurationError as exc:
        print(f"CI shard configuration error: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2) from exc
