from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from renpy_story_mapper.project import PayloadRecord, Project
from renpy_story_mapper.story_map_v2.progressive_story import PHASE05_PROGRESSIVE_KEY
from renpy_story_mapper.story_map_v2.whole_game_reader import build_whole_game_reader_page


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assemble and persist the M15 Phase 05 whole-game scrolling reader."
    )
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--skeleton", type=Path, required=True)
    parser.add_argument("--corridors", type=Path, required=True)
    parser.add_argument("--summaries", type=Path, required=True)
    parser.add_argument("--name-overrides", type=Path)
    parser.add_argument("--story-names-only", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def _json(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return cast(Mapping[str, object], value)


def _payload(connection: sqlite3.Connection, collection: str) -> tuple[Mapping[str, object], str]:
    row = connection.execute(
        """SELECT CAST(payload_json AS TEXT),payload_hash FROM payloads
           WHERE collection=? AND record_key='authoritative'""",
        (collection,),
    ).fetchone()
    if row is None:
        raise ValueError(f"missing {collection}/authoritative")
    value = json.loads(str(row[0]))
    if not isinstance(value, dict):
        raise ValueError(f"{collection}/authoritative must be an object")
    return cast(Mapping[str, object], value), str(row[1])


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _name_inventory_payload(items: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema": "story-map-v2-name-inventory-v1",
        "uncovered_count": len(items),
        "items": items,
    }


def _first_ten_name_packet(items: list[dict[str, object]]) -> dict[str, object]:
    canary = items[:10]
    return {
        "schema": "story-map-v2-name-canary-v1",
        "uncovered_count": len(items),
        "canary_count": len(canary),
        "wording_only": True,
        "items": canary,
    }


def _reader_counts(
    page: Mapping[str, object],
    graph: Mapping[str, object],
    control_flow: Mapping[str, object],
    skeleton: Mapping[str, object],
    corridors: Mapping[str, object],
    summaries: Mapping[str, object],
) -> dict[str, int]:
    controls = 0
    menu_controls = 0
    condition_controls = 0
    route_arms = 0
    nested_controls = 0
    maximum_depth = 0
    label_events = 0
    outcomes = {"continues": 0, "rejoins": 0, "ends": 0, "unresolved": 0}

    def visit_choice(choice: Mapping[str, object], depth: int = 0) -> None:
        nonlocal controls, menu_controls, condition_controls, route_arms
        nonlocal nested_controls, maximum_depth
        controls += 1
        nested_controls += int(depth > 0)
        maximum_depth = max(maximum_depth, depth)
        if choice.get("control_kind") == "decision":
            menu_controls += 1
        else:
            condition_controls += 1
        raw_arms = choice.get("arms")
        if not isinstance(raw_arms, list):
            raise ValueError("reader choice has no arms")
        route_arms += len(raw_arms)
        for raw_arm in raw_arms:
            if not isinstance(raw_arm, dict):
                raise ValueError("reader arm must be an object")
            outcome = raw_arm.get("outcome_kind")
            if outcome not in outcomes:
                raise ValueError("reader arm has an invalid outcome kind")
            outcomes[cast(str, outcome)] += 1
            nested = raw_arm.get("nested_choices")
            if not isinstance(nested, list):
                raise ValueError("reader arm has no nested choices")
            for raw_choice in nested:
                if not isinstance(raw_choice, dict):
                    raise ValueError("nested reader choice must be an object")
                visit_choice(raw_choice, depth + 1)
            route_flow = raw_arm.get("route_flow", [])
            if not isinstance(route_flow, list):
                raise ValueError("reader arm route flow must be an array")
            for raw_item in route_flow:
                if not isinstance(raw_item, dict):
                    raise ValueError("reader route-flow item must be an object")
                if raw_item.get("kind") == "event":
                    raw_event = raw_item.get("event")
                    if not isinstance(raw_event, dict):
                        raise ValueError("reader route-flow event must be an object")
                    visit_event(raw_event)

    def visit_event(event: Mapping[str, object]) -> None:
        nonlocal label_events
        label_events += 1
        raw_choices = event.get("choices")
        if not isinstance(raw_choices, list):
            raise ValueError("reader event has no choices")
        for raw_choice in raw_choices:
            if not isinstance(raw_choice, dict):
                raise ValueError("reader choice must be an object")
            visit_choice(raw_choice)

    sections = page.get("sections")
    if not isinstance(sections, list):
        raise ValueError("reader page has no sections")
    root_events: list[Mapping[str, object]] = []
    for raw_section in sections:
        if not isinstance(raw_section, dict) or not isinstance(raw_section.get("events"), list):
            raise ValueError("reader section has no events")
        root_events.extend(cast(list[Mapping[str, object]], raw_section["events"]))
    for event in root_events:
        visit_event(event)

    raw_results = summaries.get("results")
    raw_excluded = summaries.get("reader_excluded")
    raw_packets = corridors.get("packets")
    raw_counts = corridors.get("counts")
    if not all(isinstance(value, list) for value in (raw_results, raw_excluded, raw_packets)):
        raise ValueError("reader inputs have invalid result arrays")
    excluded_ids = {
        item["corridor_id"]
        for item in cast(list[dict[str, object]], raw_excluded)
        if isinstance(item, dict) and isinstance(item.get("corridor_id"), str)
    }
    low_ids = {
        item["corridor_id"]
        for item in cast(list[dict[str, object]], raw_results)
        if isinstance(item, dict)
        and isinstance(item.get("corridor_id"), str)
        and item.get("packet_shape_grade") == "LOW"
        and item["corridor_id"] not in excluded_ids
    }
    mechanics = raw_counts.get("mechanic_kinds") if isinstance(raw_counts, dict) else None
    unresolved = mechanics.get("unresolved", 0) if isinstance(mechanics, dict) else 0
    if not isinstance(unresolved, int):
        raise ValueError("unresolved mechanic count must be an integer")
    raw_nodes = graph.get("nodes")
    raw_regions = control_flow.get("regions")
    if not isinstance(raw_nodes, list) or not isinstance(raw_regions, list):
        raise ValueError("authority inputs have invalid control arrays")
    controls_by_id = {
        item["id"]: item
        for item in cast(list[dict[str, object]], raw_nodes)
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and item.get("reachable_from_entry") is True
        and item.get("kind") in {"menu", "if"}
    }
    regions_by_split = {
        item["split_node_id"]: item
        for item in cast(list[dict[str, object]], raw_regions)
        if isinstance(item, dict) and item.get("split_node_id") in controls_by_id
    }
    structural_arms = sum(
        len(item["arm_ids"])
        for item in regions_by_split.values()
        if isinstance(item.get("arm_ids"), list)
    )
    structural_menus = sum(item.get("kind") == "menu" for item in controls_by_id.values())
    structural_conditions = sum(item.get("kind") == "if" for item in controls_by_id.values())
    skeleton_counts = skeleton.get("counts")
    if not isinstance(skeleton_counts, dict):
        raise ValueError("whole-game skeleton has no structural counts")
    skeleton_coverage = skeleton.get("coverage")
    coverage_counts = (
        skeleton_coverage.get("counts") if isinstance(skeleton_coverage, dict) else None
    )
    if not isinstance(coverage_counts, dict):
        raise ValueError("whole-game skeleton has no coverage counts")

    def skeleton_count(name: str) -> int:
        value = skeleton_counts.get(name)
        if not isinstance(value, int):
            raise ValueError(f"whole-game skeleton count {name} is invalid")
        return value

    reachable_labels = coverage_counts.get("reached_labels")
    if not isinstance(reachable_labels, int):
        raise ValueError("whole-game skeleton reachable label count is invalid")
    return {
        "label_events": label_events,
        "reachable_labels": reachable_labels,
        "controls": len(controls_by_id),
        "menu_controls": structural_menus,
        "condition_controls": structural_conditions,
        "route_arms": structural_arms,
        "all_m06_route_arms": skeleton_count("route_arms"),
        "demonstrated_rejoin_points": skeleton_count("demonstrated_rejoins"),
        "loop_components": skeleton_count("loop_components"),
        "terminals": skeleton_count("terminals"),
        "visible_controls": controls,
        "secondary_controls": len(controls_by_id) - controls,
        "visible_route_arms": route_arms,
        "visible_menu_controls": menu_controls,
        "visible_condition_controls": condition_controls,
        "nested_visible_controls": nested_controls,
        "maximum_visible_control_depth": maximum_depth,
        "visible_continuations": outcomes["continues"],
        "visible_rejoins": outcomes["rejoins"],
        "visible_endings": outcomes["ends"],
        "visible_unresolved_routes": outcomes["unresolved"],
        "reader_corridors": len(cast(list[object], raw_packets)) - len(excluded_ids),
        "low_fragments_stitched": len(low_ids),
        "technical_fail_packets_excluded": len(excluded_ids),
        "unresolved_mechanics": unresolved,
    }


def main() -> int:
    args = _arguments()
    source_project = args.project.resolve()
    output_dir = args.output_dir.resolve()
    inputs = [
        source_project,
        args.skeleton.resolve(),
        args.corridors.resolve(),
        args.summaries.resolve(),
    ]
    name_override_path = args.name_overrides.resolve() if args.name_overrides else None
    if name_override_path is not None:
        inputs.append(name_override_path)
    for path in inputs:
        if not path.is_file():
            raise FileNotFoundError(path)
    output_dir.mkdir(parents=True, exist_ok=True)
    page_path = output_dir / "whole-game-story-page.json"
    project_path = output_dir / "MsDenvers-whole-game-reader.rsmproj"
    source_hash_before = _file_hash(source_project)

    connection = sqlite3.connect(f"{source_project.as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        graph, graph_hash = _payload(connection, "m01_graph")
        control_flow, control_flow_hash = _payload(connection, "m06_control_flow")
    finally:
        connection.close()

    skeleton = _json(inputs[1])
    corridors = _json(inputs[2])
    summaries = _json(inputs[3])
    name_overrides = _json(name_override_path) if name_override_path is not None else None
    bindings = corridors.get("authority_bindings")
    if isinstance(bindings, dict):
        expected = {
            "m01_graph/authoritative": graph_hash,
            "m06_control_flow/authoritative": control_flow_hash,
        }
        for key, digest in expected.items():
            if bindings.get(key) != digest:
                raise ValueError(f"corridor authority binding mismatch for {key}")

    name_inventory: list[dict[str, object]] = []
    page = build_whole_game_reader_page(
        graph,
        control_flow,
        skeleton,
        corridors,
        summaries,
        name_overrides=name_overrides,
        name_inventory=name_inventory,
    )
    inventory_path = output_dir / "story-name-inventory.json"
    canary_path = output_dir / "story-name-first-10.json"
    _write(inventory_path, _name_inventory_payload(name_inventory))
    _write(canary_path, _first_ten_name_packet(name_inventory))
    if not args.story_names_only:
        _write(page_path, page)
        shutil.copy2(source_project, project_path)
        with Project.open(project_path) as project:
            project.write_payloads(
                [
                    PayloadRecord(
                        "story_map_v2",
                        PHASE05_PROGRESSIVE_KEY,
                        page,
                    )
                ]
            )
    source_hash_after = _file_hash(source_project)
    if source_hash_after != source_hash_before:
        raise RuntimeError("the read-only source project changed during reader assembly")

    report = {
        "source_project": str(source_project),
        "story_name_inventory": str(inventory_path),
        "story_name_first_10": str(canary_path),
        "uncovered_story_names": len(name_inventory),
        "accepted_story_name_overrides": (
            len(name_overrides.get("names", name_overrides)) if name_overrides else 0
        ),
        "counts": _reader_counts(page, graph, control_flow, skeleton, corridors, summaries),
        "source_project_sha256": source_hash_after,
        "source_project_unchanged": source_hash_after == source_hash_before,
    }
    if not args.story_names_only:
        report.update({"project_copy": str(project_path), "page": str(page_path)})
    _write(output_dir / "reader-assembly-report.json", report)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
