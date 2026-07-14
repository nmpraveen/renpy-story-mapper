"""Validate M10 against independently authored private MsDenvers Day 1 facts."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from renpy_story_mapper.project import Project, create_ingested_project
from renpy_story_mapper.storage import canonical_json

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "tests" / "private" / "m10_msdenvers_day1_ground_truth.json"
DEFAULT_SOURCE = Path(
    r"C:\Users\prave\AppData\Local\RenPyStoryMapper\recovery-cache-v1\d8"
    r"\d8a8c2470ee58d5d55f0ab04d6a71fa19c5a68ce86d880c83e0f72107cf91f4c"
    r"\source.rpy"
)
DEFAULT_ARCHIVE = Path(
    r"C:\Users\prave\Downloads\JD\MsDenvers-0 1 2 7-p"
    r"\MsDenvers-0.1.2.7-pc\game\scripts.rpa"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    report = run(
        manifest_path=args.manifest,
        source_path=args.source,
        archive_path=args.archive,
        output_dir=args.output_dir,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def run(
    *,
    manifest_path: Path,
    source_path: Path,
    archive_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    manifest_path = manifest_path.resolve(strict=True)
    source_path = source_path.resolve(strict=True)
    archive_path = archive_path.resolve(strict=True)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest = _mapping(json.loads(manifest_path.read_text(encoding="utf-8")), "manifest")
    source_before = _fingerprint(source_path)
    archive_before = _fingerprint(archive_path)
    started = time.perf_counter()

    direct = _verify_manifest_against_source(manifest, source_path)
    first_path = output_dir / "msdenvers-day1-first.rsmproj"
    second_path = output_dir / "msdenvers-day1-replay.rsmproj"
    first_started = time.perf_counter()
    create_ingested_project(first_path, source_path).close()
    first_seconds = time.perf_counter() - first_started
    second_started = time.perf_counter()
    create_ingested_project(second_path, source_path).close()
    second_seconds = time.perf_counter() - second_started

    first = _payloads(first_path)
    second = _payloads(second_path)
    canonical = first["canonical"]
    projection = first["projection"]
    analysis_state = first["analysis_state"]
    canonical_stable = canonical_json(canonical) == canonical_json(second["canonical"])
    projection_stable = canonical_json(projection) == canonical_json(second["projection"])
    if not canonical_stable or not projection_stable:
        raise AssertionError("unchanged private input did not produce stable structural output")

    graph_result = _validate_graph(manifest, canonical, projection, analysis_state)
    source_after = _fingerprint(source_path)
    archive_after = _fingerprint(archive_path)
    if source_before != source_after or archive_before != archive_after:
        raise AssertionError("private acceptance changed a read-only source")
    hardcoded = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "src" / "renpy_story_mapper").rglob("*.py")
        if "msdenvers" in path.read_text(encoding="utf-8").casefold()
    ]
    if hardcoded:
        raise AssertionError(f"production code contains game-specific names: {hardcoded}")

    report: dict[str, object] = {
        "schema_version": 1,
        "status": "passed",
        "manifest": str(manifest_path),
        "ground_truth_authorship": manifest.get("authorship"),
        "safety": {
            "game_or_creator_python_executed": False,
            "provider_calls": 0,
            "source_unchanged": source_before == source_after,
            "archive_unchanged": archive_before == archive_after,
            "production_game_hardcodes": hardcoded,
        },
        "direct_source_verification": direct,
        "graph_validation": graph_result,
        "determinism": {
            "canonical_structural_bytes_equal": canonical_stable,
            "projection_structural_bytes_equal": projection_stable,
            "canonical_hash": _sha256(canonical_json(canonical)),
            "projection_hash": _sha256(canonical_json(projection)),
        },
        "timings": {
            "first_analysis_seconds": round(first_seconds, 3),
            "replay_analysis_seconds": round(second_seconds, 3),
            "total_seconds": round(time.perf_counter() - started, 3),
        },
        "artifacts": {
            "first_project": str(first_path),
            "replay_project": str(second_path),
        },
    }
    (output_dir / "acceptance.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8", newline="\n"
    )
    (output_dir / "ACCEPTANCE_REPORT.md").write_text(
        _markdown(report), encoding="utf-8", newline="\n"
    )
    return report


def _verify_manifest_against_source(
    manifest: Mapping[str, object], source_path: Path
) -> dict[str, object]:
    lines = source_path.read_text(encoding="utf-8").splitlines()
    source = _mapping(manifest.get("source"), "manifest.source")
    actual_hash = _sha256(source_path.read_bytes())
    if actual_hash != str(source.get("sha256")):
        raise AssertionError("private source does not match the independently authored manifest")
    checked_lines: set[int] = set()
    choices = _records(manifest.get("choices"), "manifest.choices")
    for choice in choices:
        _expect_line(lines, _integer(choice, "menu_line"), "menu:")
        checked_lines.add(_integer(choice, "menu_line"))
        for arm in _records(choice.get("ordered_arms"), "choice.ordered_arms"):
            caption = str(arm["caption"])
            caption_line = _integer(arm, "caption_line")
            _expect_line(lines, caption_line, f'"{caption}":')
            target_line = _integer(arm, "target_line")
            _expect_line(lines, target_line, str(arm["target_text"]))
            checked_lines.update((caption_line, target_line))
        rejoin_line = _integer(choice, "rejoin_line")
        _expect_line(lines, rejoin_line, str(choice["rejoin_text"]))
        checked_lines.add(rejoin_line)
    for key in ("conditions", "effects"):
        for item in _records(manifest.get(key), f"manifest.{key}"):
            line = _integer(item, "line")
            _expect_line(lines, line, str(item["expression"]))
            checked_lines.add(line)
    for item in _records(manifest.get("visibility_cases"), "manifest.visibility_cases"):
        line = _integer(item, "line")
        _expect_line(lines, line, str(item["source_text"]))
        checked_lines.add(line)
    return {
        "source_sha256": actual_hash,
        "choice_count": len(choices),
        "arm_count": sum(
            len(_records(item.get("ordered_arms"), "choice.ordered_arms")) for item in choices
        ),
        "independently_checked_source_lines": len(checked_lines),
    }


def _validate_graph(
    manifest: Mapping[str, object],
    canonical: Mapping[str, object],
    projection: Mapping[str, object],
    analysis_state: Mapping[str, object],
) -> dict[str, object]:
    canonical_nodes = _records(canonical.get("nodes"), "canonical.nodes")
    canonical_edges = _records(canonical.get("edges"), "canonical.edges")
    evidence = _records(canonical.get("evidence"), "canonical.evidence")
    facts = _records(canonical.get("facts"), "canonical.facts")
    projected_nodes = _records(projection.get("nodes"), "projection.nodes")
    projected_edges = _records(projection.get("edges"), "projection.edges")
    projected_regions = _records(projection.get("regions"), "projection.regions")
    node_by_id = {str(item["id"]): item for item in canonical_nodes}
    evidence_by_id = {str(item["id"]): item for item in evidence}
    choices = _records(manifest.get("choices"), "manifest.choices")
    source = _mapping(manifest.get("source"), "manifest.source")
    day1_start = _integer(source, "day1_start_line")
    day2_start = _integer(source, "day2_start_line")

    day1_outcomes = [
        item
        for item in projected_nodes
        if item.get("kind") == "choice_outcome"
        and day1_start <= _entry_line(item, node_by_id, evidence_by_id) < day2_start
    ]
    expected_arm_count = _integer(
        _mapping(manifest.get("bounds"), "bounds"), "expected_day1_arm_count"
    )
    if len(day1_outcomes) != expected_arm_count:
        raise AssertionError(
            f"Day 1 outcome count mismatch: {len(day1_outcomes)} != {expected_arm_count}"
        )
    outcomes_by_line = {
        _entry_line(item, node_by_id, evidence_by_id): item for item in day1_outcomes
    }
    matched_regions: set[str] = set()
    rejoin_records: list[dict[str, object]] = []
    for choice in choices:
        arms = _records(choice.get("ordered_arms"), "choice.ordered_arms")
        outcomes = [outcomes_by_line[_integer(arm, "caption_line")] for arm in arms]
        if [str(item["title"]) for item in outcomes] != [str(item["caption"]) for item in arms]:
            raise AssertionError("Day 1 captions or arm order differ from the source manifest")
        if [
            _integer(_mapping(item.get("attributes"), "outcome.attributes"), "ordinal")
            for item in outcomes
        ] != list(range(len(arms))):
            raise AssertionError("Day 1 projected arm ordinals are incorrect")
        region_ids = {
            str(_mapping(item.get("attributes"), "outcome.attributes")["canonical_region_id"])
            for item in outcomes
        }
        if len(region_ids) != 1:
            raise AssertionError("choice arms do not share one canonical region")
        region_id = region_ids.pop()
        matched_regions.add(region_id)
        region = next(
            item for item in projected_regions if item["canonical_region_id"] == region_id
        )
        merge = region.get("merge_node_id")
        split = region.get("split_node_id")
        if not isinstance(merge, str) or not isinstance(split, str):
            raise AssertionError("a source-proven Day 1 choice lacks its split or rejoin")
        for arm, outcome in zip(arms, outcomes, strict=True):
            target_line = _integer(arm, "target_line")
            member_lines = _member_lines(outcome, node_by_id, evidence_by_id)
            if target_line not in member_lines:
                raise AssertionError(
                    f"branch target line {target_line} is absent from {arm['caption']!r}"
                )
            if not _reachable(str(outcome["id"]), merge, projected_edges):
                raise AssertionError(f"choice outcome {arm['caption']!r} does not reach its rejoin")
        rejoin_records.append(
            {
                "manifest_line": choice["rejoin_line"],
                "manifest_text": choice["rejoin_text"],
                "canonical_region_id": region_id,
                "projected_merge_node_id": merge,
            }
        )

    _verify_facts(manifest, facts, evidence_by_id)
    visible_lines = {
        line
        for item in canonical_nodes
        for line in _evidence_lines(_strings(item.get("evidence_ids")), evidence_by_id)
    }
    for item in _records(manifest.get("visibility_cases"), "manifest.visibility_cases"):
        if _integer(item, "line") not in visible_lines:
            raise AssertionError(f"source visibility case at line {item['line']} disappeared")
    bounds = _mapping(manifest.get("bounds"), "manifest.bounds")
    maximum = _integer(bounds, "maximum_whole_project_projection_nodes")
    if len(projected_nodes) > maximum or len(projected_nodes) >= len(canonical_nodes):
        raise AssertionError("the simplified graph is not compact relative to canonical authority")
    if analysis_state.get("status") != "current_complete":
        raise AssertionError("private analysis did not complete on one generation")
    if projection.get("source_generation") != canonical.get("source_generation"):
        raise AssertionError("private graph projections mixed source generations")
    return {
        "canonical_nodes": len(canonical_nodes),
        "canonical_edges": len(canonical_edges),
        "simplified_nodes": len(projected_nodes),
        "simplified_edges": len(projected_edges),
        "day1_choices": len(matched_regions),
        "day1_outcomes": len(day1_outcomes),
        "choice_rejoins": rejoin_records,
        "conditions_verified": len(_records(manifest.get("conditions"), "conditions")),
        "effects_verified": len(_records(manifest.get("effects"), "effects")),
        "visibility_cases_verified": len(
            _records(manifest.get("visibility_cases"), "visibility_cases")
        ),
        "source_generation": projection.get("source_generation"),
    }


def _verify_facts(
    manifest: Mapping[str, object],
    facts: Sequence[Mapping[str, object]],
    evidence_by_id: Mapping[str, Mapping[str, object]],
) -> None:
    for manifest_key, fact_kind in (("conditions", "requirement"), ("effects", "effect")):
        for expected in _records(manifest.get(manifest_key), manifest_key):
            line = _integer(expected, "line")
            expression = str(expected["expression"])
            matches = [
                item
                for item in facts
                if item.get("kind") == fact_kind
                and _fact_expression(item) == expression
                and line in _evidence_lines(_strings(item.get("evidence_ids")), evidence_by_id)
            ]
            if not matches:
                raise AssertionError(f"missing {fact_kind} {expression!r} at source line {line}")


def _payloads(path: Path) -> dict[str, Mapping[str, object]]:
    with Project.open(path) as project:
        integrity = str(project._require_open().execute("PRAGMA integrity_check").fetchone()[0])
        values = {
            "canonical": project.payload("m10_canonical_graph", "authoritative"),
            "projection": project.payload("m10_inspection_projection", "authoritative"),
            "analysis_state": project.payload("m10_analysis_state", "authoritative"),
        }
    if integrity != "ok":
        raise AssertionError(f"private project integrity check failed: {integrity}")
    return {key: _mapping(value, key) for key, value in values.items()}


def _entry_line(
    outcome: Mapping[str, object],
    node_by_id: Mapping[str, Mapping[str, object]],
    evidence_by_id: Mapping[str, Mapping[str, object]],
) -> int:
    attributes = _mapping(outcome.get("attributes"), "outcome.attributes")
    entry = node_by_id[str(attributes["canonical_entry_node_id"])]
    lines = _evidence_lines(_strings(entry.get("evidence_ids")), evidence_by_id)
    if len(lines) != 1:
        raise AssertionError("choice outcome entry does not have one exact source location")
    return next(iter(lines))


def _member_lines(
    outcome: Mapping[str, object],
    node_by_id: Mapping[str, Mapping[str, object]],
    evidence_by_id: Mapping[str, Mapping[str, object]],
) -> set[int]:
    return {
        line
        for node_id in _strings(outcome.get("canonical_node_ids"))
        for line in _evidence_lines(
            _strings(node_by_id[node_id].get("evidence_ids")), evidence_by_id
        )
    }


def _evidence_lines(
    evidence_ids: Sequence[str],
    evidence_by_id: Mapping[str, Mapping[str, object]],
) -> set[int]:
    result: set[int] = set()
    for evidence_id in evidence_ids:
        source = _mapping(evidence_by_id[evidence_id].get("source"), "evidence.source")
        start = source.get("start")
        if isinstance(start, Mapping) and isinstance(start.get("line"), int):
            result.add(cast(int, start["line"]))
        elif isinstance(source.get("start_line"), int):
            result.add(cast(int, source["start_line"]))
    return result


def _fact_expression(item: Mapping[str, object]) -> str:
    attributes = _mapping(item.get("attributes"), "fact.attributes")
    return str(attributes.get("original_expression") or attributes.get("expression") or "")


def _reachable(source: str, target: str, edges: Sequence[Mapping[str, object]]) -> bool:
    outgoing: dict[str, list[str]] = {}
    for edge in edges:
        outgoing.setdefault(str(edge["source_id"]), []).append(str(edge["target_id"]))
    queue = deque([source])
    visited = {source}
    while queue:
        current = queue.popleft()
        if current == target:
            return True
        for successor in outgoing.get(current, ()):
            if successor not in visited:
                visited.add(successor)
                queue.append(successor)
    return False


def _expect_line(lines: Sequence[str], line_number: int, expected: str) -> None:
    actual = lines[line_number - 1].strip()
    if expected not in actual:
        raise AssertionError(
            f"ground truth source mismatch at line {line_number}: {actual!r} lacks {expected!r}"
        )


def _markdown(report: Mapping[str, object]) -> str:
    graph = _mapping(report["graph_validation"], "graph_validation")
    timings = _mapping(report["timings"], "timings")
    return (
        "# M10 private MsDenvers Day 1 acceptance\n\n"
        f"Status: **{report['status']}**\n\n"
        f"- Day 1 choices: {graph['day1_choices']}\n"
        f"- Day 1 outcomes: {graph['day1_outcomes']}\n"
        f"- Canonical graph: {graph['canonical_nodes']} nodes / {graph['canonical_edges']} edges\n"
        "- Simplified graph: "
        f"{graph['simplified_nodes']} nodes / {graph['simplified_edges']} edges\n"
        f"- Provider calls: 0\n"
        f"- First analysis: {timings['first_analysis_seconds']} s\n"
        f"- Replay analysis: {timings['replay_analysis_seconds']} s\n"
        "- Canonical and simplified structural bytes were stable on replay.\n"
        "- Source and archive fingerprints were unchanged.\n"
    )


def _fingerprint(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {"size": stat.st_size, "sha256": _sha256(path.read_bytes())}


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _records(value: object, name: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{name} must contain objects")
    return tuple(item for item in value if isinstance(item, Mapping))


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _integer(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"{key} must be an integer")
    return item


if __name__ == "__main__":
    raise SystemExit(main())
