"""Measure deterministic M10 linear-proof scaling through persisted projects."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from renpy_story_mapper.project import Project, create_ingested_project

STATEMENT_COUNTS = (500, 1_000, 2_000)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    report = run(args.output_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def run(output_dir: Path) -> dict[str, object]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    measurements = [_measure(output_dir, count) for count in STATEMENT_COUNTS]
    by_count = {int(item["statements"]): item for item in measurements}
    at_500 = by_count[500]
    at_1000 = by_count[1_000]
    at_2000 = by_count[2_000]
    if int(at_2000["reachability_inputs"]) > 4 * int(at_2000["canonical_nodes"]):
        raise AssertionError("2,000-statement reachability proof inputs exceed the linear bound")
    if int(at_2000["canonical_payload_bytes"]) >= 12_000_000:
        raise AssertionError("2,000-statement canonical payload exceeds the 12 MB bound")
    growth = int(at_1000["canonical_payload_bytes"]) / int(
        at_500["canonical_payload_bytes"]
    )
    if growth >= 2.6:
        raise AssertionError("500-to-1,000 canonical payload growth approaches quadratic")
    report: dict[str, object] = {
        "schema_version": 1,
        "status": "passed",
        "measurements": measurements,
        "canonical_payload_growth_500_to_1000": round(growth, 6),
        "bounds": {
            "reachability_inputs_per_node_maximum": 4,
            "canonical_payload_2000_maximum_bytes": 12_000_000,
            "payload_growth_500_to_1000_maximum": 2.6,
        },
    }
    (output_dir / "acceptance.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8", newline="\n"
    )
    (output_dir / "ACCEPTANCE_REPORT.md").write_text(
        _markdown(report), encoding="utf-8", newline="\n"
    )
    return report


def _measure(output_dir: Path, statements: int) -> dict[str, object]:
    source_path = output_dir / f"linear-{statements}.rpy"
    source = "label start:\n" + "".join(
        f'    "Linear statement {index}."\n' for index in range(statements)
    )
    source_path.write_text(source, encoding="utf-8", newline="\n")
    source_before = _fingerprint(source_path)
    project_path = output_dir / f"linear-{statements}.rsmproj"
    started = time.perf_counter()
    create_ingested_project(project_path, source_path).close()
    elapsed = time.perf_counter() - started
    source_after = _fingerprint(source_path)
    if source_before != source_after:
        raise AssertionError("scale acceptance modified its source fixture")
    with Project.open(project_path) as project:
        canonical = _mapping(
            project.payload("m10_canonical_graph", "authoritative"), "canonical graph"
        )
        state = _mapping(project.payload("m10_analysis_state", "authoritative"), "analysis state")
        row = project._require_open().execute(
            """SELECT length(payload_json),payload_hash FROM payloads
               WHERE collection='m10_canonical_graph' AND record_key='authoritative'"""
        ).fetchone()
    if row is None:
        raise AssertionError("scale project lacks its canonical payload")
    proofs = _records(canonical.get("proofs"), "canonical proofs")
    reachability_inputs = sum(
        len(_strings(item.get("input_ids")))
        for item in proofs
        if item.get("kind") == "resolved_static_reachability"
    )
    phase_seconds = {
        str(item["phase"]): item["duration_seconds"]
        for item in _records(state.get("phases"), "analysis phases")
    }
    result = {
        "statements": statements,
        "canonical_nodes": len(_records(canonical.get("nodes"), "canonical nodes")),
        "canonical_edges": len(_records(canonical.get("edges"), "canonical edges")),
        "reachability_inputs": reachability_inputs,
        "canonical_payload_bytes": int(row[0]),
        "canonical_payload_sha256": str(row[1]),
        "sqlite_project_bytes": project_path.stat().st_size,
        "canonical_phase_seconds": phase_seconds["canonical_graph"],
        "total_analysis_seconds": round(elapsed, 6),
        "source_unchanged": True,
    }
    del canonical, state, proofs
    gc.collect()
    return result


def _markdown(report: Mapping[str, object]) -> str:
    rows = _records(report["measurements"], "measurements")
    lines = [
        "# M10 linear scale acceptance",
        "",
        f"Status: **{report['status']}**",
        "",
        "| Statements | Nodes | Proof inputs | Canonical bytes | SQLite bytes | Canonical phase |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(
        "| {statements} | {canonical_nodes} | {reachability_inputs} | "
        "{canonical_payload_bytes} | {sqlite_project_bytes} | {canonical_phase_seconds} s |".format(
            **item
        )
        for item in rows
    )
    lines.extend(
        (
            "",
            "500-to-1,000 canonical payload growth: "
            f"**{report['canonical_payload_growth_500_to_1000']}x**.",
        )
    )
    return "\n".join(lines) + "\n"


def _fingerprint(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
    }


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _records(value: object, name: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be an array")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{name} must contain objects")
    return tuple(item for item in value if isinstance(item, Mapping))


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


if __name__ == "__main__":
    raise SystemExit(main())
