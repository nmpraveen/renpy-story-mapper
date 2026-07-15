"""Measure deterministic M11 growth through linear and scene-rich projects."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from itertools import pairwise
from pathlib import Path

from renpy_story_mapper.m11_persistence import M11_PHASES, M11Availability
from renpy_story_mapper.m11_scene_projection import (
    build_scene_assembly,
    stored_scene_model_mapping,
)
from renpy_story_mapper.project import Project, create_ingested_project
from renpy_story_mapper.storage import canonical_json

STATEMENT_COUNTS = (500, 1_000, 2_000)
WORKLOADS = ("linear", "scene_rich")
MAX_SIZE_GROWTH = 2.6
MAX_ASSEMBLY_TIME_GROWTH = 3.5
ASSEMBLY_TIMING_REPEATS = 3


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
    measurements = [
        _measure(output_dir, count, workload)
        for workload in WORKLOADS
        for count in STATEMENT_COUNTS
    ]
    by_workload_count = {
        (str(item["workload"]), _as_int(item["statements"], "statements")): item
        for item in measurements
    }
    growth: list[dict[str, object]] = []
    for workload in WORKLOADS:
        for lower_count, upper_count in pairwise(STATEMENT_COUNTS):
            lower = by_workload_count[(workload, lower_count)]
            upper = by_workload_count[(workload, upper_count)]
            payload_growth = _growth_ratio(upper, lower, "m11_payload_bytes")
            model_growth = _growth_ratio(upper, lower, "scene_model_bytes")
            assembly_time_growth = _growth_ratio(
                upper,
                lower,
                "assembly_validation_seconds",
            )
            if payload_growth >= MAX_SIZE_GROWTH or model_growth >= MAX_SIZE_GROWTH:
                raise AssertionError(
                    f"M11 {workload} {lower_count}-to-{upper_count} size growth "
                    "approaches quadratic"
                )
            if assembly_time_growth >= MAX_ASSEMBLY_TIME_GROWTH:
                raise AssertionError(
                    f"M11 {workload} {lower_count}-to-{upper_count} assembly/validation "
                    "timing approaches quadratic"
                )
            growth.append(
                {
                    "workload": workload,
                    "from_statements": lower_count,
                    "to_statements": upper_count,
                    "m11_payload": round(payload_growth, 6),
                    "scene_model": round(model_growth, 6),
                    "assembly_validation_time": round(assembly_time_growth, 6),
                }
            )

    for measurement in measurements:
        if _as_int(measurement["story_atoms"], "story atoms") != _as_int(
            measurement["canonical_nodes"], "canonical nodes"
        ):
            raise AssertionError("M11 does not retain exactly one atom per canonical node")
        if _as_int(measurement["coverage_entries"], "coverage entries") != _as_int(
            measurement["canonical_records"], "canonical records"
        ):
            raise AssertionError("M11 canonical coverage is not exact")
        if measurement["workload"] == "scene_rich":
            linear = by_workload_count[("linear", _as_int(measurement["statements"], "statements"))]
            if _as_int(measurement["scenes"], "scenes") <= _as_int(
                linear["scenes"], "linear scenes"
            ):
                raise AssertionError("scene-rich acceptance lost reinforced scene transitions")
            if not _as_int(
                measurement["accepted_scene_candidates"], "accepted scene candidates"
            ) or not _as_int(
                measurement["rejected_scene_candidates"], "rejected scene candidates"
            ):
                raise AssertionError(
                    "scene-rich acceptance did not retain both accepted and rejected candidates"
                )
    report: dict[str, object] = {
        "schema_version": 1,
        "status": "passed",
        "measurements": measurements,
        "growth": growth,
        "limits": {
            "maximum_size_growth": MAX_SIZE_GROWTH,
            "maximum_assembly_validation_time_growth": MAX_ASSEMBLY_TIME_GROWTH,
        },
    }
    (output_dir / "acceptance.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8", newline="\n"
    )
    (output_dir / "ACCEPTANCE_REPORT.md").write_text(
        _markdown(report), encoding="utf-8", newline="\n"
    )
    return report


def _measure(output_dir: Path, statements: int, workload: str) -> dict[str, object]:
    source_path = output_dir / f"{workload}-{statements}.rpy"
    source = _source(workload, statements)
    source_path.write_text(source, encoding="utf-8", newline="\n")
    source_before = _fingerprint(source_path)
    project_path = output_dir / f"{workload}-{statements}.rsmproj"
    started = time.perf_counter()
    create_ingested_project(project_path, source_path).close()
    elapsed = time.perf_counter() - started
    if source_before != _fingerprint(source_path):
        raise AssertionError("M11 scale acceptance modified its source fixture")
    with Project.open(project_path) as project:
        canonical = _mapping(
            project.payload("m10_canonical_graph", "authoritative"), "canonical"
        )
        selection = project.m11_persistence().select(canonical)
        rows = project._require_open().execute(
            "SELECT length(payload_json) FROM payloads WHERE collection='m11_phase_results'"
        ).fetchall()
    if (
        selection.availability is not M11Availability.CURRENT_COMPLETE
        or selection.phase_results is None
    ):
        raise AssertionError("M11 scale project lacks a current four-phase publication")
    if tuple(selection.phase_results) != M11_PHASES:
        raise AssertionError("M11 scale project has an unexpected phase set")
    assembly_times: list[float] = []
    for _index in range(ASSEMBLY_TIMING_REPEATS):
        assembly_started = time.perf_counter()
        rebuilt_assembly = build_scene_assembly(
            canonical,
            selection.phase_results["story_atoms"],
            selection.phase_results["scene_boundaries"],
        )
        assembly_times.append(time.perf_counter() - assembly_started)
        if rebuilt_assembly != selection.phase_results["scene_assembly"]:
            raise AssertionError("replayed M11 assembly/validation changed persisted output")
    model = stored_scene_model_mapping(selection.phase_results)
    boundaries = _records(model.get("boundaries"), "boundaries")
    coverage = _mapping(model.get("coverage"), "coverage")
    collections = ("nodes", "edges", "regions", "facts")
    canonical_records = sum(len(_records(canonical.get(key), key)) for key in collections)
    phase_bytes = {
        phase: len(canonical_json(dict(selection.phase_results[phase])))
        for phase in M11_PHASES
    }
    return {
        "workload": workload,
        "statements": statements,
        "canonical_nodes": len(_records(canonical.get("nodes"), "nodes")),
        "canonical_records": canonical_records,
        "story_atoms": len(_records(model.get("atoms"), "atoms")),
        "scenes": len(_records(model.get("scenes"), "scenes")),
        "accepted_scene_candidates": sum(
            item.get("status") == "accepted"
            and item.get("rule_id")
            in {
                "minimum_narrative_run",
                "reinforced_location_transition",
                "reinforced_resolved_transfer",
            }
            for item in boundaries
        ),
        "rejected_scene_candidates": sum(
            item.get("status") == "rejected"
            and item.get("rule_id") == "scene_reset_candidate"
            for item in boundaries
        ),
        "coverage_entries": len(_records(coverage.get("entries"), "coverage entries")),
        "scene_model_bytes": len(canonical_json(dict(model))),
        "m11_payload_bytes": sum(int(row[0]) for row in rows),
        "phase_bytes": phase_bytes,
        "sqlite_project_bytes": project_path.stat().st_size,
        "total_analysis_seconds": round(elapsed, 6),
        "assembly_validation_seconds": round(min(assembly_times), 6),
        "source_unchanged": True,
    }


def _source(workload: str, statements: int) -> str:
    if workload == "linear":
        body = "".join(
            f'    "Linear statement {index}."\n' for index in range(statements)
        )
    elif workload == "scene_rich":
        body = "".join(
            f"    scene scale_location_{index}\n"
            f'    "Scene-rich statement {index}."\n'
            for index in range(statements)
        )
    else:
        raise ValueError(f"unknown M11 scale workload {workload!r}")
    return f"label start:\n{body}"


def _growth_ratio(
    upper: Mapping[str, object],
    lower: Mapping[str, object],
    key: str,
) -> float:
    upper_value = _as_number(upper[key], key)
    lower_value = _as_number(lower[key], key)
    if lower_value <= 0:
        raise AssertionError(f"M11 scale measurement {key} must be positive")
    return upper_value / lower_value


def _markdown(report: Mapping[str, object]) -> str:
    rows = _records(report["measurements"], "measurements")
    lines = [
        "# M11 linear scale acceptance",
        "",
        f"Status: **{report['status']}**",
        "",
        "| Workload | Statements | Atoms | Scenes | Coverage | M11 bytes | Model bytes | "
        "Analysis | Assembly + validation |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(
        "| {workload} | {statements} | {story_atoms} | {scenes} | {coverage_entries} | "
        "{m11_payload_bytes} | {scene_model_bytes} | {total_analysis_seconds} s | "
        "{assembly_validation_seconds} s |".format(**item)
        for item in rows
    )
    lines.extend(("", "Doubling growth:", ""))
    lines.extend(
        "- {workload} {from_statements} to {to_statements}: payload **{m11_payload}x**, "
        "model **{scene_model}x**, assembly/validation **{assembly_validation_time}x**.".format(
            **item
        )
        for item in _records(report["growth"], "growth")
    )
    return "\n".join(lines) + "\n"


def _fingerprint(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_size, stat.st_mtime_ns


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


def _as_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


def _as_number(value: object, name: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    return float(value)


if __name__ == "__main__":
    raise SystemExit(main())
