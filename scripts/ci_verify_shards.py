from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ElementTree
from collections.abc import Sequence
from pathlib import Path
from typing import Any

EXPECTED_LANES = ("shard-1", "shard-2", "shard-3", "shard-4")


def _sha256_lines(lines: Sequence[str]) -> str:
    payload = "".join(f"{line}\n" for line in lines).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _junit_counts(path: Path) -> dict[str, int]:
    root = ElementTree.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root)
    return {
        field: sum(int(suite.attrib.get(field, "0")) for suite in suites)
        for field in ("tests", "failures", "errors", "skipped")
    }


def verify_reports(plan_path: Path, artifacts_root: Path) -> dict[str, object]:
    plan = _read_object(plan_path)
    proof = plan.get("proof")
    assignments = plan.get("assignments")
    if not isinstance(proof, dict) or not isinstance(assignments, dict):
        raise ValueError("CI test plan must contain proof and assignments objects")
    collection_sha256 = proof.get("collection_sha256")
    inventory = plan.get("collected_nodes")
    if not isinstance(collection_sha256, str) or not isinstance(inventory, list):
        raise ValueError("CI test plan collection proof is incomplete")

    report_paths = sorted(artifacts_root.rglob("selection-shard-*.json"))
    if len(report_paths) != 4:
        raise ValueError(f"expected four shard selection reports, found {len(report_paths)}")
    seen_nodes: set[str] = set()
    lane_summaries: list[dict[str, object]] = []
    seen_lanes: set[str] = set()
    for report_path in report_paths:
        report = _read_object(report_path)
        lane_id = report.get("lane_id")
        if lane_id not in EXPECTED_LANES or lane_id in seen_lanes:
            raise ValueError(f"invalid or duplicate shard lane report: {lane_id!r}")
        seen_lanes.add(lane_id)
        nodes = report.get("selected_nodes")
        expected_nodes = assignments.get(lane_id)
        if not isinstance(nodes, list) or nodes != expected_nodes:
            raise ValueError(f"{lane_id} selected nodes do not match the canonical plan")
        if report.get("collection_sha256") != collection_sha256:
            raise ValueError(f"{lane_id} collection hash does not match the canonical plan")
        if report.get("selected_count") != len(nodes):
            raise ValueError(f"{lane_id} selected count is inconsistent")
        if report.get("selected_sha256") != _sha256_lines(nodes):
            raise ValueError(f"{lane_id} selected hash is inconsistent")
        if report.get("durations") != 50 or report.get("exit_code") != 0:
            raise ValueError(f"{lane_id} did not complete the required durations=50 test run")
        duplicates = seen_nodes.intersection(nodes)
        if duplicates:
            raise ValueError(f"shard reports overlap: {sorted(duplicates)[:3]}")
        seen_nodes.update(nodes)

        junit_file = report.get("junit_file")
        if not isinstance(junit_file, str):
            raise ValueError(f"{lane_id} does not name its JUnit report")
        junit_paths = list(report_path.parent.rglob(junit_file))
        if len(junit_paths) != 1:
            raise ValueError(f"{lane_id} expected one JUnit report, found {len(junit_paths)}")
        counts = _junit_counts(junit_paths[0])
        if counts != report.get("junit_counts"):
            raise ValueError(f"{lane_id} JUnit counts do not match its selection report")
        if counts["tests"] != len(nodes) or counts["failures"] or counts["errors"]:
            raise ValueError(f"{lane_id} JUnit does not prove a complete successful selection")
        lane_summaries.append({"id": lane_id, "tests": len(nodes), "junit": counts})

    if seen_lanes != set(EXPECTED_LANES):
        raise ValueError(f"missing shard lanes: {sorted(set(EXPECTED_LANES) - seen_lanes)}")
    if seen_nodes != set(inventory) or len(seen_nodes) != len(inventory):
        raise ValueError("shard report union does not equal the canonical collected inventory")
    return {
        "status": "passed",
        "collection_sha256": collection_sha256,
        "tests": len(inventory),
        "lanes": sorted(lane_summaries, key=lambda item: str(item["id"])),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify four exact successful pytest shard reports."
    )
    parser.add_argument("--plan-json", type=Path, required=True)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    result = verify_reports(arguments.plan_json, arguments.artifacts_root)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
