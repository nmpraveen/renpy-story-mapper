"""Exercise selected private M12 targets without exposing or executing private inputs."""

from __future__ import annotations

import argparse
import builtins
import hashlib
import json
import os
import runpy
import shutil
import socket
import subprocess
import sys
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from unittest import mock

from renpy_story_mapper import storage
from renpy_story_mapper.m12_service import M12RouteService, load_m12_authority
from renpy_story_mapper.project import Project

MANIFEST_SCHEMA = "m12-private-target-selection-v1"
REPORT_SCHEMA = "m12-private-acceptance-v1"
TARGET_ROLES = frozenset({"hidden_or_gated", "ending", "persistent_lane"})
HIDDEN_OR_GATED_KINDS = frozenset({"temporary_outcome", "exact_occurrence"})
MIN_HIDDEN_OR_GATED_TARGETS = 3
COMMITMENT_KINDS = frozenset({"terminal", "persistent_lane"})
ROUTE_BADGES = frozenset(
    {
        "Confirmed route",
        "Route with prerequisites",
        "Best known route",
        "No proven route",
    }
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--walkthrough", type=Path)
    args = parser.parse_args()
    report = run(
        baseline_path=args.baseline,
        archive_path=args.archive,
        targets_path=args.targets,
        output_path=args.output,
        walkthrough_path=args.walkthrough,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def run(
    *,
    baseline_path: Path,
    archive_path: Path,
    targets_path: Path,
    output_path: Path,
    walkthrough_path: Path | None = None,
) -> dict[str, object]:
    baseline = baseline_path.resolve(strict=True)
    archive = archive_path.resolve(strict=True)
    targets = targets_path.resolve(strict=True)
    walkthrough = walkthrough_path.resolve(strict=True) if walkthrough_path else None
    output = output_path.resolve()
    _require_isolated_output(output, (baseline, archive, targets, walkthrough))
    if output.exists():
        raise FileExistsError("private M12 output must not already exist")

    selection = _load_selection(targets)
    inputs = tuple(path for path in (baseline, archive, targets, walkthrough) if path is not None)
    before = {path: _fingerprint(path) for path in inputs}
    adjacent_before = _adjacent_snapshots(inputs)
    output.mkdir(parents=True, exist_ok=False)
    working_project = output / "m12-private-working.rsmproj"
    shutil.copy2(baseline, working_project)

    with (
        _offline_nonexecution_boundary() as safety,
        Project.open(working_project) as project,
    ):
        service = M12RouteService(project)
        authority = load_m12_authority(project)
        catalog = _catalog(service)
        _validate_selection(selection, catalog)
        observations = tuple(_exercise_target(service, target) for target in selection)

    working_project.unlink()
    for suffix in ("-wal", "-shm"):
        adjacent = Path(f"{working_project}{suffix}")
        if adjacent.exists():
            adjacent.unlink()

    if any(safety.values()):
        raise AssertionError("private M12 acceptance crossed an execution or remote boundary")
    after = {path: _fingerprint(path) for path in inputs}
    if before != after:
        raise AssertionError("private M12 acceptance changed an accepted input")
    if adjacent_before != _adjacent_snapshots(inputs):
        raise AssertionError("private M12 acceptance wrote beside a private input")

    archive_fingerprint = before[archive]
    report: dict[str, object] = {
        "schema": REPORT_SCHEMA,
        "status": "passed",
        "authority": {
            "source_generation": authority.graph.source_generation,
            "canonical_hash": authority.canonical_hash,
            "scene_model_hash": authority.scene_model.structural_hash,
        },
        "coverage": {
            "selected_targets": len(observations),
            "hidden_or_gated_targets": sum(
                item["role"] == "hidden_or_gated" for item in observations
            ),
            "ending_targets": sum(item["role"] == "ending" for item in observations),
            "persistent_lane_targets": sum(
                item["role"] == "persistent_lane" for item in observations
            ),
            "catalog_destination_kinds": sorted({str(item["kind"]) for item in catalog}),
        },
        "results": list(observations),
        "determinism": {
            "all_exact_replays_hit_cache": all(
                bool(item["exact_replay_cache_hit"]) for item in observations
            ),
            "all_normalized_replays_equal": all(
                bool(item["normalized_replay_equal"]) for item in observations
            ),
        },
        "input_integrity": {
            "baseline_unchanged": True,
            "archive_unchanged": True,
            "target_selection_unchanged": True,
            "walkthrough_unchanged": walkthrough is not None,
            "adjacent_private_files_unchanged": True,
            "archive": archive_fingerprint,
        },
        "walkthrough_diagnostic": {
            "provided": walkthrough is not None,
            "used_for_route_correctness": False,
        },
        "safety": {
            "provider_constructions": safety["provider_constructions"],
            "network_requests": safety["network_requests"],
            "subprocess_executions": safety["subprocess_executions"],
            "creator_code_executions": safety["creator_code_executions"],
            "renpy_or_game_executed": False,
            "private_paths_recorded": False,
        },
        "artifacts": {
            "aggregate_report": "acceptance.json",
            "working_project_retained": False,
        },
    }
    report_bytes = json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    (output / "acceptance.json").write_bytes(report_bytes)
    return report


def _load_selection(path: Path) -> tuple[dict[str, str], ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping) or raw.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("private target selection schema is unsupported")
    items = raw.get("targets")
    if not isinstance(items, Sequence) or isinstance(items, str | bytes):
        raise ValueError("private target selection requires a targets array")
    result: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, Mapping) or set(item) != {"role", "kind", "target_id"}:
            raise ValueError("each private target must contain only role, kind, and target_id")
        role, kind, target_id = item.get("role"), item.get("kind"), item.get("target_id")
        if (
            not isinstance(role, str)
            or role not in TARGET_ROLES
            or not isinstance(kind, str)
            or not kind
            or not isinstance(target_id, str)
            or not target_id
        ):
            raise ValueError("private target selection contains an invalid target")
        result.append({"role": role, "kind": kind, "target_id": target_id})
    hidden_or_gated = [item for item in result if item["role"] == "hidden_or_gated"]
    if len(hidden_or_gated) < MIN_HIDDEN_OR_GATED_TARGETS:
        raise ValueError(
            f"private acceptance requires at least {MIN_HIDDEN_OR_GATED_TARGETS} "
            "selected hidden or gated targets"
        )
    if any(item["kind"] not in HIDDEN_OR_GATED_KINDS for item in hidden_or_gated):
        raise ValueError(
            "hidden or gated selections require temporary outcomes or exact occurrences"
        )
    identities = [(item["kind"], item["target_id"]) for item in result]
    if len(identities) != len(set(identities)):
        raise ValueError("private target selection cannot contain duplicate destinations")
    return tuple(result)


def _catalog(service: M12RouteService) -> tuple[Mapping[str, object], ...]:
    offset = 0
    result: list[Mapping[str, object]] = []
    while True:
        page = service.destinations(offset=offset, limit=50)
        nodes = page.get("nodes")
        if not isinstance(nodes, Sequence) or isinstance(nodes, str | bytes):
            raise AssertionError("M12 destination catalog is malformed")
        result.extend(item for item in nodes if isinstance(item, Mapping))
        next_offset = page.get("next_offset")
        if next_offset is None:
            break
        if not isinstance(next_offset, int) or next_offset <= offset or next_offset > 10_000:
            raise AssertionError("M12 destination catalog pagination is not bounded")
        offset = next_offset
    return tuple(result)


def _validate_selection(
    selection: Sequence[Mapping[str, str]], catalog: Sequence[Mapping[str, object]]
) -> None:
    available = {(str(item.get("kind")), str(item.get("target_id"))) for item in catalog}
    missing = [
        (item["role"], item["kind"])
        for item in selection
        if (item["kind"], item["target_id"]) not in available
    ]
    if missing:
        raise AssertionError(f"selected private targets are unavailable: {missing!r}")
    commitment_available = any(str(item.get("kind")) in COMMITMENT_KINDS for item in catalog)
    commitment_selected = any(item["kind"] in COMMITMENT_KINDS for item in selection)
    if commitment_available and not commitment_selected:
        raise AssertionError("an ending or persistent lane is available but was not selected")


def _exercise_target(service: M12RouteService, target: Mapping[str, str]) -> dict[str, object]:
    prepared = service.prepare(target["kind"], target["target_id"])
    first = service.solve(prepared)
    replay = service.solve(prepared)
    if first.result is None or replay.result is None:
        raise AssertionError("selected private target produced no normalized route result")
    if first.result.get("badge") not in ROUTE_BADGES:
        raise AssertionError("selected private target produced no proven best-known route")
    recommended = first.result.get("recommended")
    if recommended is None:
        if target["role"] == "hidden_or_gated":
            raise AssertionError("selected hidden or gated target lacks a recommended route")
        if first.result.get("badge") != "No proven route":
            raise AssertionError("a route-less result must use the honest no-proven-route badge")
        instructions: Sequence[object] = ()
        scene_ids: Sequence[object] = ()
        requirements: Sequence[object] = ()
        warnings: Sequence[object] = ()
        provenance: Mapping[str, object] = {}
    elif isinstance(recommended, Mapping):
        instructions = _sequence(recommended.get("instructions"))
        scene_ids = _sequence(recommended.get("scene_ids"))
        requirements = _sequence(recommended.get("requirements"))
        warnings = _sequence(recommended.get("uncertainty_warnings"))
        raw_provenance = recommended.get("provenance")
        provenance = raw_provenance if isinstance(raw_provenance, Mapping) else {}
        if not instructions or not scene_ids or not provenance:
            raise AssertionError("selected private route lacks instructions, scenes, or provenance")
    else:
        raise AssertionError("selected private route recommendation is malformed")
    if not replay.cached:
        raise AssertionError("selected private route did not reuse its exact cache entry")
    first_bytes = storage.canonical_json(dict(first.result))
    replay_bytes = storage.canonical_json(dict(replay.result))
    return {
        "role": target["role"],
        "kind": target["kind"],
        "status": str(first.result.get("status")),
        "badge": str(first.result.get("badge")),
        "ordered_scene_count": len(scene_ids),
        "instruction_count": len(instructions),
        "requirement_count": len(requirements),
        "warning_count": len(warnings),
        "provenance_counts": {
            key: len(_sequence(provenance.get(key)))
            for key in (
                "node_ids",
                "edge_ids",
                "fact_ids",
                "evidence_ids",
                "proof_ids",
                "scene_ids",
                "occurrence_ids",
            )
        },
        "exact_replay_cache_hit": replay.cached,
        "normalized_replay_equal": first_bytes == replay_bytes,
    }


def _sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, Sequence) and not isinstance(value, str | bytes) else ()


def _fingerprint(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": stat.st_size,
        "last_write_time_utc": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
    }


def _adjacent_snapshots(paths: Sequence[Path]) -> dict[Path, tuple[tuple[str, int, int], ...]]:
    parents = {path.parent for path in paths}
    return {
        parent: tuple(
            sorted(
                (item.name, item.stat().st_size, item.stat().st_mtime_ns)
                for item in parent.iterdir()
                if item.is_file()
            )
        )
        for parent in parents
    }


def _require_isolated_output(output: Path, inputs: Sequence[Path | None]) -> None:
    input_paths = tuple(path for path in inputs if path is not None)
    if output in input_paths or output.parent in {path.parent for path in input_paths}:
        raise ValueError("private M12 output must be isolated from private input directories")
    if any(output.is_relative_to(path) for path in input_paths if path.is_dir()):
        raise ValueError("private M12 output cannot be inside a private input")


@contextmanager
def _offline_nonexecution_boundary() -> Iterator[dict[str, int]]:
    counts = {
        "provider_constructions": 0,
        "network_requests": 0,
        "subprocess_executions": 0,
        "creator_code_executions": 0,
    }

    def block(name: str) -> Callable[..., None]:
        def blocked(*_args: object, **_kwargs: object) -> None:
            counts[name] += 1
            raise AssertionError(f"private M12 acceptance crossed {name}")

        return blocked

    provider_module = ModuleType("renpy_story_mapper.organization.provider")

    class ProviderBomb:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            block("provider_constructions")()

    provider_module.__dict__["CodexCliProvider"] = ProviderBomb
    network = block("network_requests")
    process = block("subprocess_executions")
    creator = block("creator_code_executions")
    with (
        mock.patch.dict(
            sys.modules,
            {"renpy_story_mapper.organization.provider": provider_module},
        ),
        mock.patch.object(socket.socket, "connect", network),
        mock.patch.object(socket, "create_connection", network),
        mock.patch.object(urllib.request.OpenerDirector, "open", network),
        mock.patch.object(subprocess, "Popen", process),
        mock.patch.object(subprocess, "run", process),
        mock.patch.object(os, "system", process),
        mock.patch.object(runpy, "run_path", creator),
        mock.patch.object(runpy, "run_module", creator),
        mock.patch.object(builtins, "exec", creator),
        mock.patch.object(builtins, "eval", creator),
    ):
        yield counts


if __name__ == "__main__":
    raise SystemExit(main())
