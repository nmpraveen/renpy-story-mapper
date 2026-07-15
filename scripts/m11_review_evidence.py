"""Generate privacy-safe M11 scene-quality evidence for pull-request review.

This diagnostic reads an already-published M11 project.  It never reads recovered
game source and deliberately omits canonical labels, speakers, and source text from
its output.  The private ground-truth manifest supplies only the four independently
reviewed Day 1 source-line anchors.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from renpy_story_mapper.m11_persistence import M11Availability
from renpy_story_mapper.m11_scene_projection import scene_model_from_phase_results
from renpy_story_mapper.project import Project

STRENGTHS = ("hard", "strong", "weak", "conflict")
MIN_REPRESENTATIVE_SCENES = 15
MAX_REPRESENTATIVE_SCENES = 20


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    arguments = parser.parse_args()
    report = generate(arguments.project, arguments.manifest, arguments.output_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def generate(project_path: Path, manifest_path: Path, output_dir: Path) -> dict[str, object]:
    manifest = _mapping(json.loads(manifest_path.read_text(encoding="utf-8")), "manifest")
    with Project.open(project_path.resolve(strict=True)) as project:
        canonical = _mapping(
            project.payload("m10_canonical_graph", "authoritative"), "canonical graph"
        )
        selection = project.m11_persistence().select(canonical)
    if (
        selection.availability is not M11Availability.CURRENT_COMPLETE
        or selection.phase_results is None
    ):
        raise RuntimeError("project does not contain a current complete M11 publication")

    phases = selection.phase_results
    model = scene_model_from_phase_results(
        canonical,
        phases["story_atoms"],
        phases["scene_boundaries"],
        phases["scene_assembly"],
    )
    model.validate()

    atom_counts = sorted(len(scene.atom_ids) for scene in model.scenes)
    singleton_count = atom_counts.count(1)
    distribution: dict[str, object] = {
        "scene_count": len(atom_counts),
        "singleton_count": singleton_count,
        "singleton_percentage": round(100.0 * singleton_count / len(atom_counts), 3),
        "median": statistics.median(atom_counts),
        "p75": _nearest_rank(atom_counts, 0.75),
        "p90": _nearest_rank(atom_counts, 0.90),
        "p99": _nearest_rank(atom_counts, 0.99),
        "maximum": max(atom_counts),
        "percentile_method": "nearest-rank for p75/p90/p99; conventional median",
    }

    accepted = [boundary for boundary in model.boundaries if boundary.status.value == "accepted"]
    accepted_by_strength = Counter(boundary.strength.value for boundary in accepted)
    rule_counts = Counter(
        (boundary.strength.value, boundary.rule_id, boundary.reason) for boundary in accepted
    )
    boundary_evidence: dict[str, object] = {
        "accepted_total": len(accepted),
        "accepted_by_strength": {
            strength: accepted_by_strength.get(strength, 0) for strength in STRENGTHS
        },
        "accepted_by_rule_and_reason": [
            {
                "strength": strength,
                "rule_id": rule_id,
                "reason": reason,
                "count": count,
            }
            for (strength, rule_id, reason), count in sorted(rule_counts.items())
        ],
    }

    representative_scenes, choice_anchors = _representative_scenes(model, manifest)
    report: dict[str, object] = {
        "schema_version": 1,
        "evidence_kind": "M11 privacy-safe scene-quality diagnostic",
        "corpus": "private MsDenvers acceptance result",
        "privacy": {
            "commercial_source_or_assets_included": False,
            "dialogue_or_source_text_included": False,
            "absolute_local_paths_included": False,
            "descriptions": "generic atom/source-kind counts only",
        },
        "authority": {
            "canonical_hash": model.binding.canonical_hash,
            "source_generation": model.binding.source_generation,
            "scene_model_hash": model.structural_hash,
        },
        "scene_atom_count_distribution": distribution,
        "accepted_boundaries": boundary_evidence,
        "day1_choice_anchors": choice_anchors,
        "representative_scenes": representative_scenes,
    }
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    _assert_safe_output(encoded)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "scene-quality.json").write_text(encoded, encoding="utf-8", newline="\n")
    markdown = _markdown(report)
    _assert_safe_output(markdown)
    (output_dir / "SCENE_QUALITY_EVIDENCE.md").write_text(markdown, encoding="utf-8", newline="\n")
    return report


def _representative_scenes(
    model: Any, manifest: Mapping[str, object]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    atom_by_id = {atom.id: atom for atom in model.atoms}
    scene_by_id = {scene.id: scene for scene in model.scenes}
    scene_by_atom = {atom_id: scene for scene in model.scenes for atom_id in scene.atom_ids}
    boundary_by_id = {boundary.id: boundary for boundary in model.boundaries}
    lane_by_id = {lane.id: lane for lane in model.lanes}
    chapter_by_id = {chapter.id: chapter for chapter in model.chapters}
    branch_by_split = {branch.split_atom_id: branch for branch in model.temporary_branches}
    branch_by_id = {branch.id: branch for branch in model.temporary_branches}

    atoms_by_line: dict[int, list[Any]] = {}
    for atom in model.atoms:
        atoms_by_line.setdefault(atom.source_order[1], []).append(atom)

    selected_ids: list[str] = []
    contexts: dict[str, list[dict[str, object]]] = {}
    anchors: list[dict[str, object]] = []

    def select(scene_id: str, choice_index: int, role: str) -> None:
        if scene_id not in selected_ids:
            selected_ids.append(scene_id)
        contexts.setdefault(scene_id, []).append({"choice_index": choice_index, "role": role})

    choices = _records(manifest.get("choices"), "manifest.choices")
    first_choice = choices[0]
    first_menu_line = _integer(first_choice.get("menu_line"), "choice.menu_line")
    first_menu_atom = _unique_line_atom(atoms_by_line, first_menu_line, "menu")
    anchor_source_path = str(first_menu_atom.source_order[0]).replace("\\", "/")
    for choice_index, choice in enumerate(choices, start=1):
        menu_line = _integer(choice.get("menu_line"), "choice.menu_line")
        menu_atom = _unique_line_atom(atoms_by_line, menu_line, "menu", anchor_source_path)
        branch = branch_by_split.get(menu_atom.id)
        if branch is None:
            raise AssertionError(f"Day 1 choice {choice_index} has no M11 container")
        parent_scene = scene_by_id[branch.parent_scene_id]
        select(parent_scene.id, choice_index, "choice_parent")

        arm_scene_counts: list[int] = []
        extra_tail: tuple[int, str] | None = None
        for arm in branch.arms:
            arm_scene_counts.append(len(arm.scene_ids))
            if not arm.scene_ids:
                continue
            select(arm.scene_ids[0], choice_index, f"arm_{arm.ordinal}_entry")
            if arm.scene_ids[-1] != arm.scene_ids[0]:
                candidate = (len(arm.scene_ids), arm.scene_ids[-1])
                if extra_tail is None or candidate[0] > extra_tail[0]:
                    extra_tail = candidate
        if extra_tail is not None:
            select(extra_tail[1], choice_index, "longest_arm_tail")

        rejoin_line = _integer(choice.get("rejoin_line"), "choice.rejoin_line")
        rejoin_atom = _unique_line_atom(atoms_by_line, rejoin_line, "scene", anchor_source_path)
        rejoin_scene = scene_by_atom[rejoin_atom.id]
        select(rejoin_scene.id, choice_index, "exact_rejoin")
        anchors.append(
            {
                "choice_index": choice_index,
                "menu_locator": _locator(menu_atom),
                "rejoin_locator": _locator(rejoin_atom),
                "temporary_container_id": branch.id,
                "canonical_region_id": branch.canonical_region_id,
                "parent_scene_id": parent_scene.id,
                "arm_scene_counts": arm_scene_counts,
                "rejoin_scene_id": rejoin_scene.id,
            }
        )

    if len(selected_ids) < MIN_REPRESENTATIVE_SCENES:
        for choice in anchors:
            branch = branch_by_id[str(choice["temporary_container_id"])]
            for arm in branch.arms:
                for scene_id in arm.scene_ids:
                    if scene_id in selected_ids:
                        continue
                    select(
                        scene_id,
                        _integer(choice["choice_index"], "choice_index"),
                        f"arm_{arm.ordinal}_additional",
                    )
                    if len(selected_ids) >= MIN_REPRESENTATIVE_SCENES:
                        break
                if len(selected_ids) >= MIN_REPRESENTATIVE_SCENES:
                    break
            if len(selected_ids) >= MIN_REPRESENTATIVE_SCENES:
                break
    if not MIN_REPRESENTATIVE_SCENES <= len(selected_ids) <= MAX_REPRESENTATIVE_SCENES:
        raise AssertionError(f"representative scene selection produced {len(selected_ids)} records")

    records: list[dict[str, object]] = []
    for scene_id in selected_ids:
        scene = scene_by_id[scene_id]
        atoms = [atom_by_id[atom_id] for atom_id in scene.atom_ids]
        boundary = boundary_by_id[scene.boundary_id]
        lane = lane_by_id[scene.lane_id]
        chapter = chapter_by_id[scene.chapter_id]
        memberships: list[dict[str, object]] = []
        for branch in model.temporary_branches:
            if branch.parent_scene_id == scene.id:
                memberships.append(
                    {"container_id": branch.id, "role": "parent_scene", "arm_ordinal": None}
                )
            for arm in branch.arms:
                if scene.id in arm.scene_ids:
                    memberships.append(
                        {
                            "container_id": branch.id,
                            "role": "arm_local_scene",
                            "arm_ordinal": arm.ordinal,
                        }
                    )
        atom_kinds = Counter(atom.kind.value for atom in atoms)
        source_kinds = Counter(atom.source_kind or "unspecified" for atom in atoms)
        story_facing = sum(1 for atom in atoms if atom.story_facing)
        records.append(
            {
                "scene_id": scene.id,
                "lane": {"id": lane.id, "kind": lane.kind.value},
                "chapter": {"id": chapter.id, "ordinal": chapter.ordinal},
                "atom_count": len(atoms),
                "first_source_locator": _locator(atoms[0]),
                "last_source_locator": _locator(atoms[-1]),
                "accepted_boundary_reasons": (
                    [
                        {
                            "boundary_id": boundary.id,
                            "strength": boundary.strength.value,
                            "rule_id": boundary.rule_id,
                            "reason": boundary.reason,
                        }
                    ]
                    if boundary.status.value == "accepted"
                    else []
                ),
                "scene_start_decision": {
                    "boundary_id": boundary.id,
                    "status": boundary.status.value,
                    "strength": boundary.strength.value,
                    "rule_id": boundary.rule_id,
                    "reason": boundary.reason,
                },
                "temporary_container_membership": memberships,
                "choice_context": contexts[scene.id],
                "source_description": _generic_description(
                    atom_kinds, source_kinds, story_facing, len(atoms)
                ),
            }
        )
    return records, anchors


def _generic_description(
    atom_kinds: Counter[str],
    source_kinds: Counter[str],
    story_facing: int,
    total: int,
) -> str:
    kind_summary = ", ".join(f"{kind}={count}" for kind, count in sorted(atom_kinds.items()))
    source_summary = ", ".join(f"{kind}={count}" for kind, count in sorted(source_kinds.items()))
    return (
        f"Generic structural description: atom kinds [{kind_summary}]; source kinds "
        f"[{source_summary}]; story-facing={story_facing}; supporting={total - story_facing}."
    )


def _locator(atom: Any) -> str:
    raw_path, line, column, _node_id = atom.source_order
    normalized = str(raw_path).replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    lowered = [part.lower() for part in parts]
    if "game" in lowered:
        parts = parts[lowered.index("game") :]
    elif normalized.startswith("/") or (parts and ":" in parts[0]):
        parts = (parts[-1],)
    safe_parts = tuple(part for part in parts if part not in {"", ".", "..", "/"})
    safe_path = "/".join(safe_parts) or "unknown-source"
    return f"{safe_path}:{line}:{column}"


def _unique_line_atom(
    atoms_by_line: Mapping[int, Sequence[Any]],
    line: int,
    source_kind: str,
    source_path: str | None = None,
) -> Any:
    matches = [
        atom
        for atom in atoms_by_line.get(line, ())
        if atom.source_kind == source_kind
        and (source_path is None or str(atom.source_order[0]).replace("\\", "/") == source_path)
    ]
    if len(matches) != 1:
        raise AssertionError(f"line {line} expected one {source_kind!r} atom, found {len(matches)}")
    return matches[0]


def _nearest_rank(values: Sequence[int], percentile: float) -> int:
    return values[max(0, math.ceil(percentile * len(values)) - 1)]


def _markdown(report: Mapping[str, object]) -> str:
    distribution = _mapping(
        report["scene_atom_count_distribution"], "scene atom-count distribution"
    )
    boundaries = _mapping(report["accepted_boundaries"], "accepted boundaries")
    strengths = _mapping(boundaries["accepted_by_strength"], "boundary strengths")
    rules = _records(boundaries["accepted_by_rule_and_reason"], "boundary rules")
    scenes = _records(report["representative_scenes"], "representative scenes")
    lines = [
        "# M11 scene-quality review evidence",
        "",
        "This report is a review-only diagnostic generated from the accepted private M11 result. "
        "It contains structural identifiers, relative source locators, and generic atom-kind "
        "descriptions only. It contains no commercial dialogue, commercial source text, or "
        "commercial images/assets.",
        "",
        "## Scene atom-count distribution",
        "",
        "| Measure | Value |",
        "| --- | ---: |",
        f"| Scenes | {distribution['scene_count']} |",
        f"| Singleton scenes | {distribution['singleton_count']} "
        f"({distribution['singleton_percentage']}%) |",
        f"| Median atoms | {distribution['median']} |",
        f"| p75 atoms | {distribution['p75']} |",
        f"| p90 atoms | {distribution['p90']} |",
        f"| p99 atoms | {distribution['p99']} |",
        f"| Maximum atoms | {distribution['maximum']} |",
        "",
        f"Percentiles: {distribution['percentile_method']}.",
        "",
        "## Accepted boundaries",
        "",
        f"Accepted total: **{boundaries['accepted_total']}**.",
        "",
        "| Strength | Accepted |",
        "| --- | ---: |",
    ]
    lines.extend(f"| {strength} | {strengths[strength]} |" for strength in STRENGTHS)
    lines.extend(
        [
            "",
            "| Strength | Rule | Count | Deterministic reason |",
            "| --- | --- | ---: | --- |",
        ]
    )
    lines.extend(
        f"| {row['strength']} | `{row['rule_id']}` | {row['count']} | {row['reason']} |"
        for row in rules
    )
    lines.extend(
        [
            "",
            "## Representative Day 1 choice and rejoin scenes",
            "",
            f"The {len(scenes)} records below cover the four independently reviewed choice/rejoin "
            "anchors. Descriptions are intentionally structural rather than narrative.",
            "",
            "| Scene | Lane / chapter | Atoms | First -> last locator | Boundary | "
            "Temporary membership | Choice context | Description |",
            "| --- | --- | ---: | --- | --- | --- | --- | --- |",
        ]
    )
    for scene in scenes:
        lane = _mapping(scene["lane"], "scene lane")
        chapter = _mapping(scene["chapter"], "scene chapter")
        accepted_reasons = _records(scene["accepted_boundary_reasons"], "scene boundary reasons")
        start_decision = _mapping(scene["scene_start_decision"], "scene start decision")
        if accepted_reasons:
            boundary = accepted_reasons[0]
            boundary_text = (
                f"{boundary['strength']} / `{boundary['rule_id']}`: {boundary['reason']}"
            )
        else:
            boundary_text = (
                "none; stored start candidate "
                f"{start_decision['status']} {start_decision['strength']} / "
                f"`{start_decision['rule_id']}`"
            )
        memberships = _records(scene["temporary_container_membership"], "temporary membership")
        membership_text = (
            "; ".join(
                f"`{item['container_id']}` {item['role']}"
                + (f" arm {item['arm_ordinal']}" if item.get("arm_ordinal") is not None else "")
                for item in memberships
            )
            or "none"
        )
        contexts = _records(scene["choice_context"], "choice context")
        context_text = "; ".join(
            f"choice {item['choice_index']} {item['role']}" for item in contexts
        )
        lines.append(
            f"| `{scene['scene_id']}` | `{lane['id']}` ({lane['kind']}) / "
            f"`{chapter['id']}` | {scene['atom_count']} | "
            f"`{scene['first_source_locator']}` -> `{scene['last_source_locator']}` | "
            f"{boundary_text} | "
            f"{membership_text} | {context_text} | {scene['source_description']} |"
        )
    lines.extend(
        [
            "",
            "## Synthetic browser evidence",
            "",
            "These captures use only `tests/fixtures/m11/human_scenes.rpy` plus generated "
            "synthetic "
            "appendix labels. The scene overview shows the common spine and the persistent-lane "
            "presentation for the M10-classified terminal split; the "
            "detail view shows a temporary multi-scene branch and deterministic provenance; the "
            "canonical escape shows the direct M10 authority path.",
            "",
            "| Review requirement | 100% evidence | 200% evidence |",
            "| --- | --- | --- |",
            "| Common spine and separate persistent/terminal lanes | `m11-scenes-100.png` | "
            "`m11-scenes-cards-200.png` |",
            "| Temporary multi-scene branch | `m11-scene-detail-100.png` | "
            "`m11-scene-detail-200.png` |",
            "| Scene-detail provenance and M10 escape | `m11-scene-detail-100.png`, "
            "`m11-canonical-escape-100.png` | `m11-scene-detail-200.png`, "
            "`m11-canonical-escape-200.png` |",
            "",
            "### 100%",
            "",
            "![M11 scene overview at 100%](screenshots/m11-scenes-100.png)",
            "",
            "![M11 temporary branch detail at 100%](screenshots/m11-scene-detail-100.png)",
            "",
            "![M11 canonical provenance escape at 100%](screenshots/m11-canonical-escape-100.png)",
            "",
            "### 200%",
            "",
            "![M11 scene overview at 200%](screenshots/m11-scenes-200.png)",
            "",
            "![M11 scene cards and lanes at 200%](screenshots/m11-scenes-cards-200.png)",
            "",
            "![M11 temporary branch detail at 200%](screenshots/m11-scene-detail-200.png)",
            "",
            "![M11 canonical provenance escape at 200%](screenshots/m11-canonical-escape-200.png)",
            "",
        ]
    )
    return "\n".join(lines)


def _assert_safe_output(value: str) -> None:
    lowered = value.lower()
    forbidden = ("c:\\", "c:/users/", '"source_text"', '"speaker"', '"label"')
    found = [token for token in forbidden if token in lowered]
    if found:
        raise AssertionError(f"unsafe review evidence tokens: {found}")


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


def _integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
