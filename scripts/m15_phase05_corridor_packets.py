from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from renpy_story_mapper.story_map_v2.whole_game_corridors import (
    build_whole_game_corridor_packets,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export deterministic Phase 05 whole-game story-corridor packets."
    )
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def _load_payload(
    connection: sqlite3.Connection,
    collection: str,
    key: str,
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


def _parsed_sources(
    connection: sqlite3.Connection,
) -> tuple[list[Mapping[str, object]], str]:
    rows = connection.execute(
        """SELECT record_key,CAST(payload_json AS TEXT),payload_hash
           FROM payloads WHERE collection='parsed_source' ORDER BY record_key"""
    ).fetchall()
    if not rows:
        raise ValueError("project has no parsed_source payloads")
    parsed: list[Mapping[str, object]] = []
    bindings: list[tuple[str, str]] = []
    for key, raw_json, payload_hash in rows:
        value = json.loads(str(raw_json))
        if not isinstance(value, dict):
            raise ValueError(f"parsed_source/{key} must be an object")
        parsed.append(cast(Mapping[str, object], value))
        bindings.append((str(key), str(payload_hash)))
    digest = hashlib.sha256(
        json.dumps(bindings, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return parsed, digest


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _coverage_report(result: Mapping[str, object]) -> str:
    counts = cast(Mapping[str, object], result["counts"])
    checks = cast(Mapping[str, object], cast(Mapping[str, object], result["coverage"])["checks"])
    exclusion_reasons = cast(Mapping[str, object], counts["filtered_statement_reasons"])
    return "\n".join(
        [
            "# M15 Phase 05 whole-game corridor packet coverage",
            "",
            f"- Coverage grade: **{result['coverage_grade']}**",
            f"- Packets: **{counts['packets']}**",
            (
                "- Reachable statements: "
                f"{counts['included_narrative_statements']} included + "
                f"{counts['excluded_non_story_statements']} reasoned non-story exclusions = "
                f"{counts['reachable_statement_nodes']} total"
            ),
            (
                "- Labels: "
                f"{counts['reachable_labels']} reachable + {counts['unreachable_labels']} "
                f"unreachable = {counts['total_labels']} total"
            ),
            (
                "- Python mechanics: "
                f"{counts['mechanics']} retained, including "
                f"{counts['state_effects']} direct state effects"
            ),
            (
                "- Rejoins: "
                f"{counts['incoming_rejoin_packets']} packets with "
                f"{counts['incoming_rejoin_route_origins']} incoming route origins"
            ),
            "- Exclusion reasons: "
            + ", ".join(f"{name}={count}" for name, count in exclusion_reasons.items()),
            "",
            "## Checks",
            "",
            *[f"- {name}: **{'PASS' if passed else 'FAIL'}**" for name, passed in checks.items()],
            "",
            "## Limitations",
            "",
            *[f"- {item}" for item in cast(list[object], result["limitations"])],
            "",
        ]
    )


def main() -> int:
    args = _arguments()
    project = args.project.resolve(strict=True)
    output_dir = args.output_dir.resolve()
    if project == output_dir or output_dir in project.parents:
        raise ValueError("output directory must be separate from the read-only project")

    connection = sqlite3.connect(f"{project.as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        graph, graph_hash = _load_payload(connection, "m01_graph", "authoritative")
        control_flow, control_flow_hash = _load_payload(
            connection, "m06_control_flow", "authoritative"
        )
        parsed, parsed_hash = _parsed_sources(connection)
    finally:
        connection.close()

    result = build_whole_game_corridor_packets(
        parsed,
        graph,
        control_flow,
        authority_bindings={
            "m01_graph/authoritative": graph_hash,
            "m06_control_flow/authoritative": control_flow_hash,
            "parsed_source/set": parsed_hash,
        },
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    packets_path = output_dir / "whole-game-corridor-packets.json"
    report_path = output_dir / "PACKET_COVERAGE.md"
    _write_json(packets_path, result)
    report_path.write_text(_coverage_report(result), encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "packets": str(packets_path),
                "report": str(report_path),
                "coverage_grade": result["coverage_grade"],
                "counts": result["counts"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
