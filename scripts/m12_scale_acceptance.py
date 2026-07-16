"""Measure deterministic target-specific M12 solving over bounded synthetic projects."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

from renpy_story_mapper.m12_model import (
    DeterministicLimitProfile,
    InitialStateValue,
    InitialValueKind,
    StateVariableIdentity,
)
from renpy_story_mapper.m12_service import M12RouteService, load_m12_authority
from renpy_story_mapper.m12_solver import numeric_projection, solve_route
from renpy_story_mapper.project import Project, create_ingested_project
from renpy_story_mapper.storage import canonical_json

ROOT = Path(__file__).resolve().parents[1]
COMPLEX_FIXTURE = ROOT / "tests" / "fixtures" / "m12" / "route_targets.rpy"
STATEMENT_COUNTS = (24, 48, 96)
LINEAR_EDGE_COUNTS = (500, 1_000, 2_000)
MAX_EXPANSION_GROWTH = 3.0
MIN_APPROXIMATE_DOUBLING = 1.75
MAX_APPROXIMATE_DOUBLING = 2.35


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--profile",
        choices=("default", "linear-prefix"),
        default="default",
        help=(
            "run the existing mixed workload or the focused exact 500/1000/2000-edge "
            "parent-prefix acceptance"
        ),
    )
    parser.add_argument(
        "--linear-edge-counts",
        nargs="+",
        type=int,
        default=LINEAR_EDGE_COUNTS,
        metavar="EDGES",
        help="exact ascending route-edge counts for the linear-prefix profile",
    )
    args = parser.parse_args()
    if args.profile == "linear-prefix":
        report = run_exact_linear_scale(
            args.output_dir,
            edge_counts=tuple(args.linear_edge_counts),
        )
    else:
        report = run(args.output_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def run(
    output_dir: Path,
    *,
    statement_counts: Sequence[int] = STATEMENT_COUNTS,
    include_complex: bool = True,
) -> dict[str, object]:
    counts = tuple(statement_counts)
    if not counts or any(value < 1 for value in counts) or tuple(sorted(set(counts))) != counts:
        raise ValueError("statement counts must be unique positive ascending integers")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    observations: list[dict[str, object]] = []
    measurements = [
        _measure_linear(output_dir, count, observations) for count in counts
    ]
    growth: list[dict[str, object]] = []
    for lower, upper in pairwise(measurements):
        expanded_growth = _ratio(upper, lower, "expanded_states")
        if expanded_growth >= MAX_EXPANSION_GROWTH:
            raise AssertionError(
                "selected-target deterministic expansion growth approaches quadratic"
            )
        if _as_int(upper["route_edge_count"], "upper route edges") <= _as_int(
            lower["route_edge_count"], "lower route edges"
        ):
            raise AssertionError("larger linear workload did not retain the longer target path")
        growth.append(
            {
                "from_statements": lower["statements"],
                "to_statements": upper["statements"],
                "expanded_state_growth": round(expanded_growth, 6),
            }
        )

    complex_result = _measure_complex(output_dir, observations) if include_complex else None
    report: dict[str, object] = {
        "schema_version": 1,
        "status": "passed",
        "target_specific": True,
        "all_target_preprocessing": False,
        "linear_measurements": measurements,
        "growth": growth,
        "complex_workload": complex_result,
        "limits": {"maximum_expansion_growth": MAX_EXPANSION_GROWTH},
    }
    report_bytes = json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    (output_dir / "acceptance.json").write_bytes(report_bytes)
    observations_report = {
        "schema_version": 1,
        "hardware_sensitive": True,
        "semantic_pass_fail_uses_these_values": False,
        "observations": observations,
    }
    (output_dir / "observations.json").write_text(
        json.dumps(observations_report, indent=2, sort_keys=True),
        encoding="utf-8",
        newline="\n",
    )
    return report


def run_exact_linear_scale(
    output_dir: Path,
    *,
    edge_counts: Sequence[int] = LINEAR_EDGE_COUNTS,
) -> dict[str, object]:
    """Prove exact long linear routes stay within the unchanged v1 semantic budgets."""

    counts = tuple(edge_counts)
    if not counts or any(value < 9 for value in counts) or tuple(sorted(set(counts))) != counts:
        raise ValueError("edge counts must be unique ascending integers of at least nine")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    observations: list[dict[str, object]] = []
    measurements = [
        _measure_exact_linear_edges(output_dir, count, observations) for count in counts
    ]
    growth = [
        _exact_linear_growth(lower, upper)
        for lower, upper in pairwise(measurements)
    ]
    report: dict[str, object] = {
        "schema_version": 1,
        "status": "passed",
        "profile": "exact_linear_parent_prefix",
        "target_specific": True,
        "all_target_preprocessing": False,
        "normal_v1_budgets": DeterministicLimitProfile().to_dict(),
        "edge_counts": list(counts),
        "linear_measurements": measurements,
        "growth": growth,
        "limits": {
            "minimum_approximate_doubling": MIN_APPROXIMATE_DOUBLING,
            "maximum_approximate_doubling": MAX_APPROXIMATE_DOUBLING,
        },
    }
    _write_reports(output_dir, report, observations)
    return report


def _measure_exact_linear_edges(
    output_dir: Path,
    route_edges: int,
    observations: list[dict[str, object]],
) -> dict[str, object]:
    statements, padding, source = _linear_source_for_route_edges(route_edges)
    measurement = _measure_linear_source(
        output_dir,
        workload=f"linear-edges-{route_edges}",
        source_text=source,
        observations=observations,
    )
    actual_edges = _as_int(measurement["route_edge_count"], "route edge count")
    if actual_edges != route_edges:
        raise AssertionError(
            f"exact linear route requested {route_edges} edges but emitted {actual_edges}"
        )
    if measurement["complete"] is not True:
        raise AssertionError(
            f"exact {route_edges}-edge linear route did not complete under normal v1 budgets: "
            f"{measurement['termination_reason']}"
        )
    if measurement["limit_profile"] != DeterministicLimitProfile().to_dict():
        raise AssertionError("exact linear scale changed the normal v1 budget profile")
    return {
        "requested_route_edges": route_edges,
        "source_step_labels": statements,
        "source_padding_statements": padding,
        **measurement,
        "completed_under_normal_v1_budgets": True,
    }


def _exact_linear_growth(
    lower: Mapping[str, object],
    upper: Mapping[str, object],
) -> dict[str, object]:
    lower_edges = _as_int(lower["requested_route_edges"], "lower route edges")
    upper_edges = _as_int(upper["requested_route_edges"], "upper route edges")
    expected = upper_edges / lower_edges
    ratios = {
        key: round(_ratio(upper, lower, key), 6)
        for key in (
            "expanded_states",
            "retained_states",
            "prefix_records",
            "accounting_units",
            "serialized_prefix_bytes",
            "result_bytes",
        )
    }
    if expected == 2.0:
        for key in ("accounting_units", "serialized_prefix_bytes"):
            ratio = ratios[key]
            if not MIN_APPROXIMATE_DOUBLING <= ratio <= MAX_APPROXIMATE_DOUBLING:
                raise AssertionError(
                    f"{key} growth {ratio} is not approximately linear when route edges double"
                )
    return {
        "from_route_edges": lower_edges,
        "to_route_edges": upper_edges,
        "expected_route_growth": round(expected, 6),
        **{f"{key}_growth": value for key, value in ratios.items()},
    }


def _measure_linear(
    output_dir: Path,
    statements: int,
    observations: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "statements": statements,
        **_measure_linear_source(
            output_dir,
            workload=f"linear-{statements}",
            source_text=_linear_source(statements),
            observations=observations,
        ),
    }


def _measure_linear_source(
    output_dir: Path,
    *,
    workload: str,
    source_text: str,
    observations: list[dict[str, object]],
) -> dict[str, object]:
    source_path = output_dir / f"{workload}.rpy"
    source_path.write_text(source_text, encoding="utf-8", newline="\n")
    source_before = _fingerprint(source_path)
    project_path = output_dir / f"{workload}.rsmproj"
    started = time.perf_counter()
    create_ingested_project(project_path, source_path).close()
    analysis_seconds = time.perf_counter() - started
    if source_before != _fingerprint(source_path):
        raise AssertionError("M12 scale acceptance modified a synthetic source")
    with Project.open(project_path) as project:
        service = M12RouteService(project)
        page = service.destinations(query="Scale Finish", limit=50)
        destination = _destination(page, title="Scale Finish")
        prepared = service.prepare(str(destination["kind"]), str(destination["target_id"]))
        pure_first = solve_route(
            prepared.authority.graph,
            prepared.authority.scene_model,
            prepared.request,
            canonical_hash=prepared.authority.canonical_hash,
        )
        pure_second = solve_route(
            prepared.authority.graph,
            prepared.authority.scene_model,
            prepared.request,
            canonical_hash=prepared.authority.canonical_hash,
        )
        if pure_first.result is None or pure_second.result is None:
            raise AssertionError("linear selected-target solve did not return a normalized result")
        if pure_first.result.normalized_bytes() != pure_second.result.normalized_bytes():
            raise AssertionError("linear deterministic expansion replay changed normalized bytes")
        first = service.solve(prepared)
        replay = service.solve(prepared)
    if first.result is None or replay.result is None or not replay.cached:
        raise AssertionError("linear selected-target cache replay failed")
    normalized = canonical_json(dict(first.result))
    replay_bytes = canonical_json(dict(replay.result))
    if normalized != replay_bytes:
        raise AssertionError("cached replay changed deterministic route bytes")
    budget = _mapping(first.result.get("budget_usage"), "budget usage")
    limits = prepared.request.limits.to_dict()
    recommended_value = first.result.get("recommended")
    if recommended_value is None:
        raise AssertionError(
            "linear selected-target solve returned no route: "
            f"status={first.result.get('status')}, "
            f"termination={first.result.get('termination_reason')}, "
            "budget_usage="
            f"{json.dumps(first.result.get('budget_usage'), sort_keys=True)}"
        )
    recommended = _mapping(recommended_value, "recommended route")
    prefix_bytes = _serialized_prefix_bytes(recommended)
    observations.append(
        {
            "workload": workload,
            "analysis_seconds": round(analysis_seconds, 6),
            "sqlite_project_bytes": project_path.stat().st_size,
        }
    )
    return {
        "source_sha256": source_before["sha256"],
        "canonical_nodes": len(prepared.authority.graph.nodes),
        "scene_count": len(prepared.authority.scene_model.scenes),
        "selected_destination_kind": destination["kind"],
        "selected_destination_id": destination["target_id"],
        "solver_version": prepared.request.solver_version,
        "limit_profile": limits,
        "request_identity": prepared.identity.identity_hash,
        "status": first.result["status"],
        "complete": first.result["complete"],
        "termination_reason": first.result["termination_reason"],
        "expanded_states": budget["expanded_states"],
        "retained_states": budget["retained_states"],
        "peak_frontier_states": budget["peak_frontier_states"],
        "prefix_records": budget["prefix_records"],
        "accounting_units": budget["accounting_units"],
        "route_edge_count": len(_values(recommended.get("edge_ids"), "route edges")),
        "serialized_prefix_bytes": prefix_bytes,
        "instruction_count": len(_records(recommended.get("instructions"), "instructions")),
        "alternatives": len(_records(first.result.get("alternatives"), "alternatives")),
        "result_bytes": len(normalized),
        "result_sha256": hashlib.sha256(normalized).hexdigest(),
        "pure_expansion_replay_identical": True,
        "cache_replay_identical": True,
        "source_unchanged": True,
        "selected_target_solves": 1,
    }


def _measure_complex(
    output_dir: Path,
    observations: list[dict[str, object]],
) -> dict[str, object]:
    source_path = output_dir / "complex-route.rpy"
    source_path.write_bytes(COMPLEX_FIXTURE.read_bytes())
    source_before = _fingerprint(source_path)
    project_path = output_dir / "complex-route.rsmproj"
    started = time.perf_counter()
    create_ingested_project(project_path, source_path).close()
    analysis_seconds = time.perf_counter() - started
    if source_before != _fingerprint(source_path):
        raise AssertionError("M12 complex scale acceptance modified its source")
    summaries: dict[str, object] = {}
    with Project.open(project_path) as project:
        service = M12RouteService(project)
        authority = load_m12_authority(project)
        selected_target_solves = 0
        targets = (
            ("confirmed", "Foyer"),
            ("alternatives", "Memory"),
            ("threshold_loop", "Observatory"),
        )
        for name, query in targets:
            destination = _destination(service.destinations(query=query, limit=50), title=query)
            prepared = service.prepare(str(destination["kind"]), str(destination["target_id"]))
            pure_first = solve_route(
                authority.graph,
                authority.scene_model,
                prepared.request,
                canonical_hash=authority.canonical_hash,
            )
            pure_second = solve_route(
                authority.graph,
                authority.scene_model,
                prepared.request,
                canonical_hash=authority.canonical_hash,
            )
            if pure_first.result is None or pure_second.result is None:
                raise AssertionError(f"{name} did not return deterministic normalized bytes")
            if pure_first.result.normalized_bytes() != pure_second.result.normalized_bytes():
                raise AssertionError(f"{name} expansion-budget replay changed normalized bytes")
            first = service.solve(prepared)
            replay = service.solve(prepared)
            selected_target_solves += 1
            if first.result is None or replay.result is None or not replay.cached:
                raise AssertionError(f"{name} exact-key cache replay failed")
            normalized = canonical_json(dict(first.result))
            if normalized != canonical_json(dict(replay.result)):
                raise AssertionError(f"{name} cache replay changed normalized bytes")
            alternatives = _records(first.result.get("alternatives"), "alternatives")
            if len(alternatives) > prepared.request.limits.alternatives:
                raise AssertionError("M12 alternatives exceeded the deterministic limit")
            recommended_value = first.result.get("recommended")
            recommended = (
                _mapping(recommended_value, "recommended")
                if recommended_value is not None
                else None
            )
            summary: dict[str, object] = {
                "query": query,
                "destination_kind": destination["kind"],
                "destination_id": destination["target_id"],
                "request_identity": prepared.identity.identity_hash,
                "status": first.result["status"],
                "termination_reason": first.result["termination_reason"],
                "complete": first.result["complete"],
                "alternative_count": len(alternatives),
                "loop_count": 0 if recommended is None else recommended.get("loop_count", 0),
                "budget_usage": first.result["budget_usage"],
                "result_sha256": hashlib.sha256(normalized).hexdigest(),
                "pure_expansion_replay_identical": True,
                "cache_replay_identical": True,
            }
            summaries[name] = summary
            if name == "threshold_loop":
                bounded_request = replace(
                    prepared.request,
                    initial_state=(
                        InitialStateValue(
                            StateVariableIdentity("store", "score", None),
                            InitialValueKind.ENTRY_PRECONDITION,
                            0,
                        ),
                    ),
                    limits=replace(
                        prepared.request.limits,
                        repetition_per_transition=3,
                    ),
                )
                bounded_first = solve_route(
                    authority.graph,
                    authority.scene_model,
                    bounded_request,
                    canonical_hash=authority.canonical_hash,
                )
                bounded_second = solve_route(
                    authority.graph,
                    authority.scene_model,
                    bounded_request,
                    canonical_hash=authority.canonical_hash,
                )
                if bounded_first.result is None or bounded_second.result is None:
                    raise AssertionError("bounded threshold replay returned no result")
                if (
                    bounded_first.result.normalized_bytes()
                    != bounded_second.result.normalized_bytes()
                ):
                    raise AssertionError("bounded threshold replay changed normalized bytes")
                summary["exact_acceleration_termination"] = (
                    bounded_first.result.termination_reason
                )
                summary["exact_acceleration_complete"] = bounded_first.result.complete
                bounded_route = bounded_first.result.recommended
                summary["exact_acceleration_repeat_counts"] = (
                    []
                    if bounded_route is None
                    else [
                        item.repeated_count
                        for item in bounded_route.repeated_action_claims
                    ]
                )
        projection = numeric_projection(
            authority.graph,
            {item.id for item in authority.graph.nodes},
        )
    alternatives_summary = _mapping(summaries["alternatives"], "alternatives summary")
    threshold_summary = _mapping(summaries["threshold_loop"], "threshold summary")
    if _as_int(alternatives_summary["alternative_count"], "alternative count") < 1:
        raise AssertionError(
            "complex selected target did not retain a bounded material alternative"
        )
    if threshold_summary.get("exact_acceleration_termination") != "exhaustive" or not bool(
        threshold_summary.get("exact_acceleration_complete")
    ):
        raise AssertionError(
            "exact threshold loop did not complete through conservative acceleration"
        )
    repeat_counts = _values(
        threshold_summary.get("exact_acceleration_repeat_counts"),
        "exact acceleration repeat counts",
    )
    if not repeat_counts or not all(isinstance(item, int) and item > 1 for item in repeat_counts):
        raise AssertionError("exact threshold loop omitted its proven repeat count")
    thresholds = {
        key: list(values) for key, values in sorted(projection.thresholds.items())
    }
    if not any(3 in values for values in thresholds.values()):
        raise AssertionError("complex numeric projection omitted the proven score threshold")
    observations.append(
        {
            "workload": "complex-route",
            "analysis_seconds": round(analysis_seconds, 6),
            "sqlite_project_bytes": project_path.stat().st_size,
        }
    )
    return {
        "source_sha256": source_before["sha256"],
        "canonical_nodes": len(authority.graph.nodes),
        "scene_count": len(authority.scene_model.scenes),
        "limit_profile_version": prepared.request.limits.version,
        "selected_target_solves": selected_target_solves,
        "all_target_preprocessing": False,
        "bounded_alternatives": True,
        "bounded_loop": True,
        "exact_loop_acceleration": True,
        "numeric_thresholds": thresholds,
        "cache_replay": True,
        "source_unchanged": True,
        "targets": summaries,
    }


def _linear_source(statements: int) -> str:
    chunks = [
        "label start:\n",
        "    scene scale_start\n",
        '    "Begin selected-target scale route."\n',
        "    jump scale_step_0000\n",
    ]
    for index in range(statements):
        next_label = f"scale_step_{index + 1:04d}" if index + 1 < statements else "scale_target"
        chunks.extend(
            (
                f"\nlabel scale_step_{index:04d}:\n",
                f"    scene scale_location_{index:04d}\n",
                f'    "Selected target step {index:04d}."\n',
                f"    jump {next_label}\n",
            )
        )
    chunks.extend(
        (
            "\nlabel scale_target:\n",
            "    scene scale_finish\n",
            '    "Scale finish target."\n',
            "    return\n",
        )
    )
    return "".join(chunks)


def _linear_source_for_route_edges(route_edges: int) -> tuple[int, int, str]:
    """Build a real-project linear route whose accepted path has exactly ``route_edges``."""

    if route_edges < 9:
        raise ValueError("exact linear route requires at least nine edges")
    step_labels = (route_edges - 5) // 4
    padding = route_edges - ((4 * step_labels) + 5)
    source = _linear_source(step_labels)
    start_jump = "    jump scale_step_0000\n"
    if source.count(start_jump) != 1:
        raise AssertionError("linear source template lost its unique start jump")
    padding_source = "".join(
        f'    "Exact route padding {index}."\n' for index in range(padding)
    )
    return step_labels, padding, source.replace(
        start_jump,
        f"{padding_source}{start_jump}",
        1,
    )


def _serialized_prefix_bytes(route: Mapping[str, object]) -> int:
    """Serialize the accepted parent-pointer shape without retaining full path copies."""

    node_ids = _values(route.get("node_ids"), "route nodes")
    edge_ids = _values(route.get("edge_ids"), "route edges")
    if len(node_ids) != len(edge_ids) + 1:
        raise AssertionError("accepted route does not form one parent-linked prefix chain")
    records: list[dict[str, object]] = []
    for index, node_id in enumerate(node_ids):
        records.append(
            {
                "prefix_id": index,
                "parent_id": None if index == 0 else index - 1,
                "node_id": node_id,
                "incoming_edge_id": None if index == 0 else edge_ids[index - 1],
            }
        )
    return len(canonical_json(records))


def _write_reports(
    output_dir: Path,
    report: Mapping[str, object],
    observations: Sequence[Mapping[str, object]],
) -> None:
    report_bytes = json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    (output_dir / "acceptance.json").write_bytes(report_bytes)
    observations_report = {
        "schema_version": 1,
        "hardware_sensitive": True,
        "semantic_pass_fail_uses_these_values": False,
        "observations": list(observations),
    }
    (output_dir / "observations.json").write_text(
        json.dumps(observations_report, indent=2, sort_keys=True),
        encoding="utf-8",
        newline="\n",
    )


def _destination(page: Mapping[str, object], *, title: str) -> Mapping[str, object]:
    candidates = [
        item
        for item in _records(page.get("nodes"), "destination nodes")
        if item.get("kind") == "generic_scene"
        and str(item.get("title", "")).casefold() == title.casefold()
    ]
    if not candidates:
        candidates = [
            item
            for item in _records(page.get("nodes"), "destination nodes")
            if item.get("kind") == "generic_scene"
        ]
    if not candidates:
        raise AssertionError(f"No supported generic-scene destination matched {title!r}")
    return sorted(candidates, key=lambda item: str(item.get("target_id")))[0]


def _fingerprint(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
    }


def _ratio(upper: Mapping[str, object], lower: Mapping[str, object], key: str) -> float:
    lower_value = _as_int(lower[key], key)
    if lower_value < 1:
        raise AssertionError(f"{key} must be positive")
    return _as_int(upper[key], key) / lower_value


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


def _values(value: object, name: str) -> tuple[object, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be an array")
    return tuple(value)


def _as_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
