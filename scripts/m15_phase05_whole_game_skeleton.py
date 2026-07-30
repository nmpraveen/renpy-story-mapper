from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from renpy_story_mapper.story_map_v2.whole_game_skeleton import build_whole_game_skeleton


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Project the Phase 05 whole-game skeleton from read-only authoritative facts."
    )
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--parser-coverage", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def _load_payload(
    connection: sqlite3.Connection,
    collection: str,
    key: str = "authoritative",
) -> tuple[Mapping[str, object], str]:
    row = connection.execute(
        """SELECT CAST(payload_json AS TEXT),payload_hash
           FROM payloads WHERE collection=? AND record_key=?""",
        (collection, key),
    ).fetchone()
    if row is None:
        raise ValueError(f"missing {collection}/{key} payload")
    value = json.loads(str(row[0]))
    if not isinstance(value, dict):
        raise ValueError(f"{collection}/{key} payload must be an object")
    return cast(Mapping[str, object], value), str(row[1])


def _load_json(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return cast(Mapping[str, object], value)


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _coverage_report(result: Mapping[str, object]) -> str:
    coverage = cast(Mapping[str, object], result["coverage"])
    counts = cast(Mapping[str, object], coverage["counts"])
    story_counts = cast(Mapping[str, object], result["counts"])
    unresolved = cast(list[object], coverage["unresolved_facts"])
    limitations = cast(list[object], result["limitations"])
    return "\n".join(
        [
            "# M15 Phase 05 whole-game structure coverage",
            "",
            f"- Entry label: `{result['entry_label']}`",
            f"- Parser extraction grade: **{result['parser_extraction_grade']}**",
            f"- Story coverage grade: **{result['story_coverage_grade']}**",
            f"- Resolution state: **{result['resolution_state']}**",
            (
                "- Labels: "
                f"{counts['reached_labels']} reached + {counts['unreachable_labels']} unreachable "
                f"= {counts['total_parser_labels']} total"
            ),
            f"- Reachable unresolved mechanics surfaced: {len(unresolved)}",
            (
                "- Structure: "
                f"{story_counts['menus']} menus / {story_counts['menu_arms']} menu arms, "
                f"{story_counts['conditions']} conditions / "
                f"{story_counts['condition_arms']} condition arms, "
                f"{story_counts['calls']} calls / {story_counts['returns']} return edges"
            ),
            (
                "- Control-flow facts: "
                f"{story_counts['route_arms']} route arms, "
                f"{story_counts['loop_components']} loop components, "
                f"{story_counts['terminals']} terminals, "
                f"{story_counts['demonstrated_rejoins']} demonstrated merge nodes"
            ),
            "",
            "## Limitations",
            "",
            *[f"- {item}" for item in limitations],
            "",
        ]
    )


def main() -> int:
    args = _arguments()
    project = args.project.resolve()
    parser_coverage_path = args.parser_coverage.resolve()
    output_dir = args.output_dir.resolve()
    if not project.is_file():
        raise FileNotFoundError(project)
    if not parser_coverage_path.is_file():
        raise FileNotFoundError(parser_coverage_path)
    if project == output_dir or parser_coverage_path == output_dir:
        raise ValueError("output directory must be separate from read-only inputs")

    connection = sqlite3.connect(f"{project.as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        graph, graph_hash = _load_payload(connection, "m01_graph")
        control_flow, control_flow_hash = _load_payload(connection, "m06_control_flow")
    finally:
        connection.close()
    parser_coverage = _load_json(parser_coverage_path)
    result = build_whole_game_skeleton(
        graph,
        control_flow=control_flow,
        parser_coverage=parser_coverage,
        authority_bindings={
            "m01_graph/authoritative": graph_hash,
            "m06_control_flow/authoritative": control_flow_hash,
        },
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    skeleton_path = output_dir / "whole-game-skeleton.json"
    coverage_path = output_dir / "coverage.json"
    report_path = output_dir / "COVERAGE.md"
    _write_json(skeleton_path, result)
    _write_json(
        coverage_path,
        {
            "entry_label": result["entry_label"],
            "parser_extraction_grade": result["parser_extraction_grade"],
            "story_coverage_grade": result["story_coverage_grade"],
            "resolution_state": result["resolution_state"],
            "parser_extraction": result["parser_extraction"],
            "coverage": result["coverage"],
            "counts": result["counts"],
            "control_flow_diagnostics": result["control_flow_diagnostics"],
            "authority_bindings": result["authority_bindings"],
            "limitations": result["limitations"],
        },
    )
    report_path.write_text(_coverage_report(result), encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "skeleton": str(skeleton_path),
                "coverage": str(coverage_path),
                "report": str(report_path),
                "coverage_counts": cast(Mapping[str, object], result["coverage"])["counts"],
                "parser_extraction_grade": result["parser_extraction_grade"],
                "story_coverage_grade": result["story_coverage_grade"],
                "resolution_state": result["resolution_state"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
