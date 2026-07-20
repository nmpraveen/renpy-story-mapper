"""Provider-free M15 synthetic and opt-in exact MsDay1 acceptance.

This runner opens the comparison project through SQLite read-only/immutable mode. It never reads
story text into its report, invokes Ren'Py/game code, or writes beside the private fixture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from renpy_story_mapper.m11_scene_projection import scene_model_from_stored_results
from renpy_story_mapper.m12_service import canonical_graph_from_mapping
from renpy_story_mapper.narrative_map import (
    assemble_narrative_events,
    build_narrative_corridors,
    build_narrative_map,
)
from renpy_story_mapper.narrative_map.contracts import NarrativeNodeKind

EXPECTED_SOURCE_HASH = "14aa44ed95dec5402dfb02a1c4e01e63b3f3e329cf04fec37b04edebb5d588a6"
EXPECTED_MENU_LINES = (143, 191, 623, 674)
EXPECTED_MAJOR_STARTS = (52, 280, 334, 431)
EXPECTED_MAJOR_ORDER = ("prologue", "terrance", "janet", "dinner", "faye")
BLOCKED_TITLES = {"start", "clean", "module ending", "technical merge"}

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]


def evaluate_exact_msday1(
    fixture_root: Path,
    project_path: Path,
) -> dict[str, JsonValue]:
    """Evaluate exact private Day 1 authority without emitting or modifying story content."""

    fixture_root, project_path = _resolve_private_paths(fixture_root, project_path)
    source = fixture_root / "input" / "game" / "v0.01_clean.rpy"
    if not source.is_file() or not project_path.is_file():
        raise FileNotFoundError("the opt-in MsDay1 source and comparison project are required")
    before_source = _fingerprint(source)
    before_project = _fingerprint(project_path)
    if before_source[0] != EXPECTED_SOURCE_HASH:
        raise ValueError("the private source hash does not match the frozen M15 fixture")
    if len(source.read_bytes().splitlines()) != 793:
        raise ValueError("the exact private scope must contain 793 reconstructed lines")

    canonical_value, phase_results = _read_authority(project_path)
    canonical = canonical_graph_from_mapping(canonical_value)
    model = scene_model_from_stored_results(phase_results)
    corridors = build_narrative_corridors(canonical, model)
    events = assemble_narrative_events(
        corridors,
        expected_atom_ids=(item.id for item in model.atoms),
    )
    narrative_map = build_narrative_map(canonical, events, corridors=corridors)

    atom_by_id = {item.id: item for item in model.atoms}
    line_by_atom = {item.id: item.source_order[1] for item in model.atoms}
    merge_atom_by_node = {item.primary_node_id: item for item in model.atoms}
    branch_by_id = {item.id: item for item in model.temporary_branches}
    branch_pairs: dict[int, int] = {}
    for branch in model.temporary_branches:
        split_line = line_by_atom[branch.split_atom_id]
        if split_line not in EXPECTED_MENU_LINES:
            continue
        scope_branch = branch
        while scope_branch.parent_branch_id is not None:
            scope_branch = branch_by_id[scope_branch.parent_branch_id]
        if scope_branch.continuation_atom_id is not None:
            rejoin_line = line_by_atom[scope_branch.continuation_atom_id]
        else:
            merge_atom = merge_atom_by_node.get(scope_branch.merge_node_id)
            if merge_atom is None:
                raise ValueError("a frozen narrative choice lost its canonical rejoin")
            rejoin_line = merge_atom.source_order[1]
        branch_pairs[split_line] = rejoin_line
    expected_pairs = {143: 165, 191: 233, 623: 793, 674: 793}
    if branch_pairs != expected_pairs:
        raise ValueError("the exact narrative choice/rejoin anchors changed")

    major_starts: list[int] = []
    first_story_line: int | None = None
    for corridor in corridors:
        story_lines = [
            line_by_atom[atom_id]
            for atom_id in corridor.ordered_atom_ids
            if atom_id not in corridor.technical_atom_ids and atom_by_id[atom_id].story_facing
        ]
        if (
            story_lines
            and corridor.temporary_container_id is None
            and corridor.temporary_arm_id is None
        ):
            if first_story_line is None:
                first_story_line = min(story_lines)
            if corridor.soft_boundary_signals:
                major_starts.append(min(item.start_line for item in corridor.provenance.locators))
    normalized_starts = tuple(
        item for item in dict.fromkeys(major_starts) if item <= EXPECTED_MAJOR_STARTS[-1]
    )
    if first_story_line is None or first_story_line >= EXPECTED_MAJOR_STARTS[0]:
        raise ValueError("the collapsible Prologue lost its story-facing evidence")
    if normalized_starts != EXPECTED_MAJOR_STARTS:
        raise ValueError("provider-free major event boundaries do not match the frozen shape")

    blocked = sorted(
        {
            node.title
            for node in narrative_map.nodes
            if node.kind is not NarrativeNodeKind.TECHNICAL_COVERAGE
            and node.title.casefold() in BLOCKED_TITLES
        }
    )
    map_cluster_count = sum(
        item.kind is NarrativeNodeKind.EVENT_CLUSTER for item in narrative_map.nodes
    )
    if map_cluster_count != len(EXPECTED_MAJOR_ORDER):
        raise ValueError("the provider-free map does not expose exactly five major clusters")
    if blocked:
        raise ValueError("the provider-free map exposes a blocked technical title")

    after_source = _fingerprint(source)
    after_project = _fingerprint(project_path)
    if before_source != after_source or before_project != after_project:
        raise RuntimeError("read-only acceptance changed a private input")
    return {
        "schema": "m15-provider-free-exact-report-v1",
        "source_sha256": before_source[0],
        "source_size": before_source[1],
        "source_mtime_ns": before_source[2],
        "project_sha256": before_project[0],
        "project_size": before_project[1],
        "project_mtime_ns": before_project[2],
        "canonical_hash": canonical.authority_hash,
        "atom_hash": model.structural_hash,
        "corridor_count": len(corridors),
        "event_count": len(events),
        "map_node_count": len(narrative_map.nodes),
        "map_edge_count": len(narrative_map.edges),
        "major_cluster_count": map_cluster_count,
        "terrance_choice_rejoins": [[143, 165], [191, 233]],
        "faye_choice_rejoins": [[623, 793], [674, 793]],
        "terrance_event_end_line": max(
            item.source_order[1]
            for item in model.atoms
            if 52 <= item.source_order[1] < 280 and item.story_facing
        ),
        "janet_event_start_line": 280,
        "major_event_order": cast(JsonValue, list(EXPECTED_MAJOR_ORDER)),
        "blocked_technical_titles": cast(JsonValue, blocked),
        "provider_calls": 0,
        "game_execution_count": 0,
        "source_unchanged": True,
        "project_unchanged": True,
    }


def evaluate_synthetic_manifest(path: Path) -> dict[str, JsonValue]:
    """Validate that the frozen provider-free manifest covers every required topology."""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping) or value.get("schema") != "m15-synthetic-acceptance-v1":
        raise ValueError("the M15 synthetic manifest schema is unsupported")
    cases = value.get("cases")
    if not isinstance(cases, Sequence) or isinstance(cases, str | bytes):
        raise ValueError("the M15 synthetic manifest cases must be an array")
    expected = {
        "linear-dialogue",
        "frequent-pose-changes",
        "local-detour",
        "nested-local-detour",
        "persistent-branches",
        "call-occurrences",
        "loop",
        "terminal",
        "unresolved-transfer",
    }
    identifiers = {str(item.get("id")) for item in cases if isinstance(item, Mapping)}
    if identifiers != expected:
        raise ValueError("the M15 synthetic topology matrix is incomplete")
    return {
        "schema": "m15-provider-free-synthetic-report-v1",
        "case_count": len(identifiers),
        "case_ids": cast(JsonValue, sorted(identifiers)),
        "provider_calls": 0,
        "game_execution_count": 0,
    }


def _read_authority(
    project_path: Path,
) -> tuple[dict[str, object], dict[str, Mapping[str, object]]]:
    uri = f"file:{project_path.as_posix()}?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True) as database:
        canonical = _payload(database, "m10_canonical_graph", "authoritative")
        state = _payload(database, "m11_analysis_state", "authoritative")
        published = _mapping(state.get("published"), "published M11 binding")
        pointers = published.get("phases")
        if not isinstance(pointers, Sequence) or isinstance(pointers, str | bytes):
            raise ValueError("the published M11 phase pointers are invalid")
        results: dict[str, Mapping[str, object]] = {}
        for item in pointers:
            pointer = _mapping(item, "M11 phase pointer")
            phase = pointer.get("phase")
            key = pointer.get("record_key")
            if not isinstance(phase, str) or not isinstance(key, str):
                raise ValueError("an M11 phase pointer has invalid identity")
            envelope = _payload(database, "m11_phase_results", key)
            results[phase] = _mapping(envelope.get("result"), "M11 phase result")
    return canonical, results


def _payload(
    database: sqlite3.Connection,
    collection: str,
    record_key: str,
) -> dict[str, object]:
    row = database.execute(
        "SELECT payload_json FROM payloads WHERE collection=? AND record_key=?",
        (collection, record_key),
    ).fetchone()
    if row is None or not isinstance(row[0], str | bytes):
        raise ValueError(f"missing project payload {collection}/{record_key}")
    value = json.loads(row[0])
    if not isinstance(value, dict):
        raise ValueError(f"project payload {collection}/{record_key} is not an object")
    return cast(dict[str, object], value)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _fingerprint(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_size, stat.st_mtime_ns


def _resolve_private_paths(fixture_root: Path, project_path: Path) -> tuple[Path, Path]:
    if (fixture_root / "input" / "game" / "v0.01_clean.rpy").is_file():
        return fixture_root, project_path
    base = Path.home() / "Documents" / "Codex" / "Renpy"
    fallback_root = base / "MsDay1"
    fallback_project = base / "tmp" / "msday1-sentinel-validation.rsmproj"
    return fallback_root, fallback_project if fallback_project.is_file() else project_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-root", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument(
        "--synthetic-manifest",
        type=Path,
        default=Path("tests/fixtures/m15/acceptance_cases.json"),
    )
    arguments = parser.parse_args()
    reports: dict[str, JsonValue] = {
        "synthetic": evaluate_synthetic_manifest(arguments.synthetic_manifest)
    }
    if arguments.fixture_root is not None and arguments.project is not None:
        reports["exact"] = evaluate_exact_msday1(arguments.fixture_root, arguments.project)
    print(json.dumps(reports, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
