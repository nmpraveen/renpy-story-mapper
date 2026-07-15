"""Measure M11 on the accepted private MsDenvers M10 canonical project."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import socket
import sys
import time
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from unittest import mock

from renpy_story_mapper.m11_persistence import M11_PHASES, M11Availability
from renpy_story_mapper.m11_scene_model import SceneModel
from renpy_story_mapper.m11_scene_projection import (
    scene_model_from_phase_results,
    stored_scene_model_mapping,
)
from renpy_story_mapper.project import Project, refresh_ingested_project
from renpy_story_mapper.project_analysis import _build_and_publish_m11
from renpy_story_mapper.storage import canonical_json
from renpy_story_mapper.web.scene_api import scene_page

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "tests" / "private" / "m10_msdenvers_day1_ground_truth.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--game-folder", type=Path, required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    report = run(
        baseline_path=args.baseline,
        manifest_path=args.manifest,
        source_path=args.source,
        archive_path=args.archive,
        game_folder_path=args.game_folder,
        output_dir=args.output_dir,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def run(
    *,
    baseline_path: Path,
    manifest_path: Path,
    source_path: Path,
    archive_path: Path,
    game_folder_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    baseline_path = baseline_path.resolve(strict=True)
    manifest_path = manifest_path.resolve(strict=True)
    source_path = source_path.resolve(strict=True)
    archive_path = archive_path.resolve(strict=True)
    game_folder_path = game_folder_path.resolve(strict=True)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest = _mapping(json.loads(manifest_path.read_text(encoding="utf-8")), "manifest")
    direct_ground_truth = _verify_manifest_against_source(manifest, source_path)
    immutable_before = {
        "baseline": _fingerprint(baseline_path),
        "source": _fingerprint(source_path),
        "archive": _fingerprint(archive_path),
    }
    first_path = output_dir / "msdenvers-m11-first.rsmproj"
    replay_path = output_dir / "msdenvers-m11-replay.rsmproj"
    shutil.copy2(baseline_path, first_path)
    baseline_size = first_path.stat().st_size

    with _offline_acceptance_boundary() as safety_counts:
        first_seconds, first = _publish_m11(first_path, manifest)
        before_unchanged = _project_fingerprint(first_path)
        refresh_started = time.perf_counter()
        refresh = refresh_ingested_project(first_path, game_folder_path)
        unchanged_seconds = time.perf_counter() - refresh_started
        after_unchanged = _project_fingerprint(first_path)
        shutil.copy2(baseline_path, replay_path)
        replay_seconds, replay = _publish_m11(replay_path, manifest)

    if before_unchanged != after_unchanged:
        raise AssertionError("unchanged private refresh wrote project bytes")
    if tuple(refresh.reused_phases[-4:]) != M11_PHASES:
        raise AssertionError("unchanged private refresh did not reuse all M11 phases")
    if first["phase_hashes"] != replay["phase_hashes"]:
        raise AssertionError("fresh M11 replay changed deterministic phase bytes")
    if first["model_hash"] != replay["model_hash"]:
        raise AssertionError("fresh M11 replay changed the scene model")
    if any(safety_counts.values()):
        raise AssertionError("M11 private acceptance crossed a provider or network boundary")

    immutable_after = {
        "baseline": _fingerprint(baseline_path),
        "source": _fingerprint(source_path),
        "archive": _fingerprint(archive_path),
    }
    if immutable_before != immutable_after:
        raise AssertionError("M11 private acceptance changed an accepted input")
    first_size = first_path.stat().st_size
    payload_delta = _as_int(first["m11_payload_bytes"], "M11 payload bytes")
    targets = {
        "m11_cold_seconds_at_most_8": first_seconds <= 8.0,
        "unchanged_refresh_seconds_at_most_2": unchanged_seconds <= 2.0,
        "m11_payload_bytes_at_most_32_mib": payload_delta <= 32 * 1024 * 1024,
        "sqlite_project_bytes_below_300_mib": first_size < 300 * 1024 * 1024,
    }
    report: dict[str, object] = {
        "schema_version": 1,
        "status": "passed",
        "authority": {
            "baseline_project": str(baseline_path),
            "canonical_hash": first["canonical_hash"],
            "source_generation": first["source_generation"],
            "m10_rebuilt": False,
            "m11_phases": list(M11_PHASES),
        },
        "ground_truth": {**direct_ground_truth, **_mapping(first["ground_truth"], "ground truth")},
        "determinism": {
            "phase_hashes_equal": first["phase_hashes"] == replay["phase_hashes"],
            "scene_model_hash_equal": first["model_hash"] == replay["model_hash"],
            "unchanged_refresh_wrote_bytes": False,
        },
        "safety": {
            "source_unchanged": True,
            "archive_unchanged": True,
            "accepted_baseline_unchanged": True,
            "provider_constructions": safety_counts["provider_constructions"],
            "remote_requests": safety_counts["remote_requests"],
            "game_or_creator_python_executed": False,
        },
        "timings": {
            "m11_cold_publish_seconds": round(first_seconds, 3),
            "m11_replay_publish_seconds": round(replay_seconds, 3),
            "unchanged_full_refresh_seconds": round(unchanged_seconds, 3),
        },
        "sizes": {
            "baseline_sqlite_bytes": baseline_size,
            "m11_sqlite_bytes": first_size,
            "sqlite_delta_bytes": first_size - baseline_size,
            "m11_payload_bytes": payload_delta,
            "phase_bytes": first["phase_bytes"],
        },
        "scene_model": first["counts"],
        "bounded_map": first["bounded_map"],
        "performance_targets": targets,
        "performance_targets_are_release_blockers": False,
        "artifacts": {"first_project": str(first_path), "replay_project": str(replay_path)},
    }
    (output_dir / "acceptance.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8", newline="\n"
    )
    (output_dir / "ACCEPTANCE_REPORT.md").write_text(
        _markdown(report), encoding="utf-8", newline="\n"
    )
    return report


def _publish_m11(
    project_path: Path, manifest: Mapping[str, object]
) -> tuple[float, dict[str, object]]:
    with Project.open(project_path) as project:
        canonical = _mapping(
            project.payload("m10_canonical_graph", "authoritative"), "canonical"
        )
        row = project._require_open().execute(
            """SELECT payload_hash FROM payloads
               WHERE collection='m10_canonical_graph' AND record_key='authoritative'"""
        ).fetchone()
        if row is None:
            raise AssertionError("private project lacks canonical authority")
        started = time.perf_counter()
        _build_and_publish_m11(
            project,
            canonical,
            canonical_hash=str(row["payload_hash"]),
            cancel_check=None,
            progress=None,
        )
        elapsed = time.perf_counter() - started
        selection = project.m11_persistence().select(canonical)
        rows = project._require_open().execute(
            "SELECT length(payload_json) FROM payloads WHERE collection='m11_phase_results'"
        ).fetchall()
    if (
        selection.availability is not M11Availability.CURRENT_COMPLETE
        or selection.phase_results is None
    ):
        raise AssertionError("private project lacks a current M11 publication")
    phases = selection.phase_results
    if tuple(phases) != M11_PHASES:
        raise AssertionError("private project did not publish exactly four M11 phases")
    model = scene_model_from_phase_results(
        canonical,
        phases["story_atoms"],
        phases["scene_boundaries"],
        phases["scene_assembly"],
    )
    model.validate()
    ground_truth = _validate_manifest_against_m11(manifest, canonical, model)
    model_mapping = stored_scene_model_mapping(phases)
    presentation = _mapping(phases["scene_presentation"], "presentation")
    page = scene_page(
        model_mapping,
        presentation,
        current_source_generation=model.binding.source_generation,
        current_canonical_hash=model.binding.canonical_hash,
    )
    region_kinds = {
        str(item["id"]): str(item.get("kind", ""))
        for item in _records(canonical.get("regions"), "regions")
    }
    if any(
        lane.canonical_region_id is not None
        and region_kinds[lane.canonical_region_id] not in {"persistent_route", "terminal_split"}
        for lane in model.lanes
    ):
        raise AssertionError("temporary private branch was promoted to a persistent lane")
    if '"source_text"' in b"".join(
        canonical_json(dict(phases[phase])) for phase in M11_PHASES
    ).decode("utf-8"):
        raise AssertionError("M11 duplicated source text in durable phase payloads")
    canonical_records = sum(
        len(_records(canonical.get(key), key)) for key in ("nodes", "edges", "regions", "facts")
    )
    if len(model.coverage.entries) != canonical_records:
        raise AssertionError("private M11 coverage is not exact")
    phase_bytes = {phase: len(canonical_json(dict(phases[phase]))) for phase in M11_PHASES}
    counts = {
        "canonical_nodes": len(_records(canonical.get("nodes"), "nodes")),
        "story_atoms": len(model.atoms),
        "scenes": len(model.scenes),
        "chapters": len(model.chapters),
        "temporary_branches": len(model.temporary_branches),
        "persistent_lanes": sum(1 for lane in model.lanes if lane.canonical_region_id),
        "lanes_total": len(model.lanes),
        "call_site_occurrences": len(model.occurrences),
        "loop_hubs": len(model.loop_hubs),
        "repeatable_scenes": sum(
            1 for scene in model.scenes if scene.repeatability.value == "repeatable"
        ),
        "coverage_entries": len(model.coverage.entries),
        "mean_atoms_per_scene": round(len(model.atoms) / max(len(model.scenes), 1), 3),
    }
    return elapsed, {
        "canonical_hash": model.binding.canonical_hash,
        "source_generation": model.binding.source_generation,
        "model_hash": model.structural_hash,
        "phase_hashes": {
            phase: hashlib.sha256(canonical_json(dict(phases[phase]))).hexdigest()
            for phase in M11_PHASES
        },
        "phase_bytes": phase_bytes,
        "m11_payload_bytes": sum(int(row[0]) for row in rows),
        "counts": counts,
        "bounded_map": {
            "status": page["status"],
            "nodes": len(_records(page.get("nodes"), "page nodes")),
            "relationships": len(
                _records(page.get("relationships"), "page relationships")
            ),
            "node_limit": page["limit"],
            "relationship_limit": page["relationship_limit"],
        },
        "ground_truth": ground_truth,
    }


def _project_fingerprint(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size


def _markdown(report: Mapping[str, object]) -> str:
    timings = _mapping(report["timings"], "timings")
    sizes = _mapping(report["sizes"], "sizes")
    counts = _mapping(report["scene_model"], "scene model")
    targets = _mapping(report["performance_targets"], "targets")
    lines = [
        "# M11 private MsDenvers acceptance",
        "",
        f"Status: **{report['status']}**",
        "",
        "Cold M11 publication: "
        f"**{timings['m11_cold_publish_seconds']} s**; unchanged full refresh: "
        f"**{timings['unchanged_full_refresh_seconds']} s**.",
        "M11 durable payloads: "
        f"**{sizes['m11_payload_bytes']} bytes**; SQLite delta: "
        f"**{sizes['sqlite_delta_bytes']} bytes**.",
        "",
        f"The canonical graph produced {counts['story_atoms']} deterministic atoms, "
        f"{counts['scenes']} scenes, {counts['chapters']} chapters, "
        f"{counts['temporary_branches']} temporary branches, and "
        f"{counts['persistent_lanes']} persistent route lanes.",
        "",
        "Performance targets are diagnostic, not release blockers:",
    ]
    lines.extend(f"- {key}: **{'met' if value else 'missed'}**" for key, value in targets.items())
    return "\n".join(lines) + "\n"


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


def _strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be an array")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must contain strings")
    return tuple(item for item in value if isinstance(item, str))


def _as_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


def _fingerprint(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "size": stat.st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "modified_ns": stat.st_mtime_ns,
    }


@contextmanager
def _offline_acceptance_boundary() -> Iterator[dict[str, int]]:
    counts = {"provider_constructions": 0, "remote_requests": 0}

    def block_provider(*_args: object, **_kwargs: object) -> None:
        counts["provider_constructions"] += 1
        raise AssertionError("M11 acceptance attempted to construct an organization provider")

    def block_network(*_args: object, **_kwargs: object) -> None:
        counts["remote_requests"] += 1
        raise AssertionError("M11 acceptance attempted a network request")

    provider_module = ModuleType("renpy_story_mapper.organization.provider")

    class ProviderBomb:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            block_provider()

    provider_module.__dict__["CodexCliProvider"] = ProviderBomb
    with (
        mock.patch.dict(
            sys.modules,
            {"renpy_story_mapper.organization.provider": provider_module},
        ),
        mock.patch.object(socket.socket, "connect", block_network),
        mock.patch.object(socket, "create_connection", block_network),
        mock.patch.object(urllib.request.OpenerDirector, "open", block_network),
    ):
        yield counts


def _verify_manifest_against_source(
    manifest: Mapping[str, object], source_path: Path
) -> dict[str, object]:
    lines = source_path.read_text(encoding="utf-8").splitlines()
    source = _mapping(manifest.get("source"), "manifest.source")
    actual_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if actual_hash != str(source.get("sha256")):
        raise AssertionError("private source does not match the independent manifest")
    checked_lines: set[int] = set()
    choices = _records(manifest.get("choices"), "manifest.choices")
    for choice in choices:
        menu_line = _manifest_int(choice, "menu_line")
        _expect_line(lines, menu_line, "menu:")
        checked_lines.add(menu_line)
        for arm in _records(choice.get("ordered_arms"), "choice.ordered_arms"):
            caption_line = _manifest_int(arm, "caption_line")
            target_line = _manifest_int(arm, "target_line")
            _expect_line(lines, caption_line, f'"{arm["caption"]}":')
            _expect_line(lines, target_line, str(arm["target_text"]))
            checked_lines.update((caption_line, target_line))
        rejoin_line = _manifest_int(choice, "rejoin_line")
        _expect_line(lines, rejoin_line, str(choice["rejoin_text"]))
        checked_lines.add(rejoin_line)
    for key in ("conditions", "effects"):
        for item in _records(manifest.get(key), f"manifest.{key}"):
            line = _manifest_int(item, "line")
            _expect_line(lines, line, str(item["expression"]))
            checked_lines.add(line)
    for item in _records(manifest.get("visibility_cases"), "manifest.visibility_cases"):
        line = _manifest_int(item, "line")
        _expect_line(lines, line, str(item["source_text"]))
        checked_lines.add(line)
    return {
        "source_sha256": actual_hash,
        "choice_count": len(choices),
        "arm_count": sum(
            len(_records(item.get("ordered_arms"), "choice.ordered_arms"))
            for item in choices
        ),
        "independently_checked_source_lines": len(checked_lines),
    }


def _validate_manifest_against_m11(
    manifest: Mapping[str, object],
    canonical: Mapping[str, object],
    model: SceneModel,
) -> dict[str, object]:
    nodes = {
        str(item["id"]): item
        for item in _records(canonical.get("nodes"), "canonical.nodes")
    }
    regions = {
        str(item["id"]): item
        for item in _records(canonical.get("regions"), "canonical.regions")
    }
    atom_by_node = {atom.primary_node_id: atom for atom in model.atoms}
    scene_by_atom = {
        atom_id: scene
        for scene in model.scenes
        for atom_id in scene.atom_ids
    }
    branch_by_split = {
        branch.split_atom_id: branch for branch in model.temporary_branches
    }
    branch_by_id = {branch.id: branch for branch in model.temporary_branches}

    def anchor(line: int, expected: str, source_kind: str | None = None) -> str:
        matches = []
        for atom in model.atoms:
            if atom.source_order[1] != line:
                continue
            node = nodes[atom.primary_node_id]
            attributes = _mapping(node.get("attributes"), "canonical node attributes")
            if expected not in str(attributes.get("source_text", "")):
                continue
            if source_kind is not None and attributes.get("source_kind") != source_kind:
                continue
            matches.append(atom.id)
        if len(matches) != 1:
            raise AssertionError(
                f"private M11 anchor {line}:{expected!r} resolved {len(matches)} times"
            )
        return matches[0]

    def authored_kind(expected: str) -> str | None:
        stripped = expected.strip()
        if stripped.startswith("scene "):
            return "scene"
        if stripped.startswith("if "):
            return "if"
        if stripped.startswith("$"):
            return "opaque"
        return None

    checked_arms = 0
    checked_rejoins = 0
    checked_memberships = 0
    for choice in _records(manifest.get("choices"), "manifest.choices"):
        menu_atom_id = anchor(_manifest_int(choice, "menu_line"), "menu:", "menu")
        branch = branch_by_split.get(menu_atom_id)
        if branch is None:
            raise AssertionError("manifest choice is not represented by a temporary container")
        region = regions[branch.canonical_region_id]
        if region.get("kind") not in {
            "local_detour",
            "optional_detour",
            "reconvergent_route_segment",
        }:
            raise AssertionError("manifest temporary choice has non-temporary M10 ownership")
        if region.get("merge_node_id") != branch.merge_node_id:
            raise AssertionError("manifest choice rejoin disagrees with M10 authority")
        if menu_atom_id not in scene_by_atom or (
            menu_atom_id not in scene_by_atom[menu_atom_id].atom_ids
        ):
            raise AssertionError("manifest choice is detached from its parent scene")

        expected_arms = _records(choice.get("ordered_arms"), "choice.ordered_arms")
        if len(expected_arms) != len(branch.arms):
            raise AssertionError("manifest choice arm count disagrees with M11")
        sibling_scene_ids: set[str] = set()
        expanded = any(arm.scene_ids for arm in branch.arms)
        for expected_arm, arm in zip(expected_arms, branch.arms, strict=True):
            caption_atom_id = anchor(
                _manifest_int(expected_arm, "caption_line"),
                f'"{expected_arm["caption"]}":',
                "menu_choice",
            )
            target_atom_id = anchor(
                _manifest_int(expected_arm, "target_line"),
                str(expected_arm["target_text"]),
                authored_kind(str(expected_arm["target_text"])),
            )
            if not {caption_atom_id, target_atom_id} <= set(arm.atom_ids):
                raise AssertionError("manifest choice arm has incorrect atom ownership")
            local_scene_ids = set(arm.scene_ids)
            if sibling_scene_ids & local_scene_ids:
                raise AssertionError("private temporary arms share an arm-local scene")
            sibling_scene_ids.update(local_scene_ids)
            for scene_id in arm.scene_ids:
                scene = next(item for item in model.scenes if item.id == scene_id)
                if not set(scene.atom_ids) <= set(arm.atom_ids):
                    raise AssertionError("private arm-local scene escapes canonical membership")
                if branch.continuation_atom_id in scene.atom_ids:
                    raise AssertionError("private arm-local scene crosses the exact rejoin")
            if expanded and scene_by_atom[target_atom_id].id not in local_scene_ids:
                raise AssertionError("representative private arm target lacks a local scene")
            checked_arms += 1
            checked_memberships += 2

        rejoin_atom_id = anchor(
            _manifest_int(choice, "rejoin_line"),
            str(choice["rejoin_text"]),
            authored_kind(str(choice["rejoin_text"])),
        )
        continuation_atom_id = branch.continuation_atom_id
        parent_branch_id = branch.parent_branch_id
        while continuation_atom_id != rejoin_atom_id and parent_branch_id is not None:
            parent_branch = branch_by_id[parent_branch_id]
            continuation_atom_id = parent_branch.continuation_atom_id
            parent_branch_id = parent_branch.parent_branch_id
        if continuation_atom_id != rejoin_atom_id:
            raise AssertionError("manifest choice continuation disagrees with M11 exact rejoin")
        if any(rejoin_atom_id in arm.atom_ids for arm in branch.arms):
            raise AssertionError("private continuation is incorrectly owned by a choice arm")
        checked_rejoins += 1

    atom_by_id = {atom.id: atom for atom in model.atoms}
    scene_labels = [
        {
            str(nodes[atom_by_id[atom_id].primary_node_id].get("label", ""))
            for atom_id in scene.atom_ids
            if atom_by_id[atom_id].story_facing
        }
        for scene in model.scenes
    ]
    if any(len(labels) > 1 for labels in scene_labels):
        raise AssertionError("private scene crosses unrelated canonical procedures")

    persistent_regions = {
        region_id: region
        for region_id, region in regions.items()
        if region.get("kind") in {"persistent_route", "terminal_split"}
    }
    canonical_by_origin = {
        str(origin.get("record_id")): region_id
        for region_id, region in persistent_regions.items()
        for origin in _records(region.get("origins"), "region.origins")
        if origin.get("collection") == "m06_control_flow"
    }
    lanes_by_region_arm = {
        (lane.canonical_region_id, lane.arm_ordinal): lane
        for lane in model.lanes
        if lane.canonical_region_id is not None
    }
    nested_lane_checks = 0
    for lane in lanes_by_region_arm.values():
        region_id = lane.canonical_region_id
        if region_id is None:
            raise AssertionError("private persistent lane lacks its canonical region")
        region = persistent_regions[region_id]
        split_node_id = str(region["split_node_id"])
        if lane.split_atom_id != atom_by_node[split_node_id].id:
            raise AssertionError("private lane split anchor disagrees with M10")
        if lane.merge_node_id != region.get("merge_node_id"):
            raise AssertionError("private lane merge anchor disagrees with M10")
        attributes = _mapping(region.get("attributes"), "region.attributes")
        parent_value = attributes.get("parent_region_id")
        parent_region_id = (
            canonical_by_origin.get(parent_value)
            if isinstance(parent_value, str)
            else None
        )
        if parent_region_id is None:
            continue
        parent = persistent_regions[parent_region_id]
        containing = [
            arm
            for arm in _records(
                _mapping(parent.get("attributes"), "region.attributes").get("arms"),
                "region.arms",
            )
            if split_node_id
            in {
                str(arm["entry_node_id"]),
                *_strings(arm.get("member_node_ids"), "arm.member_node_ids"),
            }
        ]
        if len(containing) == 1:
            expected_parent = lanes_by_region_arm[
                (parent_region_id, _manifest_int(containing[0], "ordinal"))
            ]
            if lane.parent_lane_id != expected_parent.id:
                raise AssertionError("private nested lane lost canonical parent ownership")
            nested_lane_checks += 1

    return {
        "m11_choice_containers_checked": len(
            _records(manifest.get("choices"), "manifest.choices")
        ),
        "m11_arms_checked": checked_arms,
        "m11_rejoins_checked": checked_rejoins,
        "m11_representative_memberships_checked": checked_memberships,
        "m11_illegal_procedure_cuts": 0,
        "m11_nested_lane_parent_checks": nested_lane_checks,
    }


def _manifest_int(value: Mapping[str, object], key: str) -> int:
    result = value.get(key)
    if not isinstance(result, int) or isinstance(result, bool):
        raise ValueError(f"manifest {key} must be an integer")
    return result


def _expect_line(lines: Sequence[str], line_number: int, expected: str) -> None:
    if line_number < 1 or line_number > len(lines) or expected not in lines[line_number - 1]:
        raise AssertionError(f"private source line {line_number} does not match ground truth")


if __name__ == "__main__":
    raise SystemExit(main())
