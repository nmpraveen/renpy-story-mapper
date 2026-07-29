from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

GRADES = ("PASS", "PARTIAL", "LOW", "FAIL")
REQUIRED_RESULT_FIELDS = (
    "canonical_packet_index",
    "corridor_id",
    "title",
    "summary",
    "detail",
    "presentation_children",
    "branch_consequence",
    "fidelity_grade",
    "packet_shape_grade",
    "grade_reason",
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and merge Phase 05 whole-game AI summary partitions."
    )
    parser.add_argument("--canonical-packets", type=Path, required=True)
    parser.add_argument("--first-ten", type=Path, required=True)
    parser.add_argument("--bulk-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return cast(dict[str, Any], value)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _normalize_canary(item: Mapping[str, Any]) -> dict[str, Any]:
    children: list[dict[str, str]] = []
    for beat in cast(Sequence[Mapping[str, Any]], item.get("beats", [])):
        children.append(
            {
                "title": str(beat["title"]),
                "summary": str(beat["summary"]),
            }
        )
    return {
        "canonical_packet_index": item["canonical_packet_index"],
        "corridor_id": item["corridor_id"],
        "title": item["title"],
        "summary": item["short_summary"],
        "detail": item["detail_summary"],
        "presentation_children": children,
        "branch_consequence": item["branch_consequence"],
        "fidelity_grade": item["summary_fidelity_grade"],
        "packet_shape_grade": item["packet_shape_grade"],
        "grade_reason": item["grade_reason"],
    }


def _validate_result(item: Mapping[str, Any]) -> None:
    missing = [field for field in REQUIRED_RESULT_FIELDS if field not in item]
    if missing:
        raise ValueError(f"summary result is missing fields: {', '.join(missing)}")
    if not isinstance(item["canonical_packet_index"], int):
        raise ValueError("canonical_packet_index must be an integer")
    for field in (
        "corridor_id",
        "title",
        "summary",
        "detail",
        "branch_consequence",
        "grade_reason",
    ):
        if not isinstance(item[field], str):
            raise ValueError(f"{field} must be a string")
    if item["fidelity_grade"] not in GRADES:
        raise ValueError(f"invalid fidelity grade: {item['fidelity_grade']}")
    if item["packet_shape_grade"] not in GRADES:
        raise ValueError(f"invalid packet-shape grade: {item['packet_shape_grade']}")
    children = item["presentation_children"]
    if not isinstance(children, list):
        raise ValueError("presentation_children must be a list")
    for child in children:
        if not isinstance(child, dict):
            raise ValueError("presentation child must be an object")
        if not isinstance(child.get("title"), str) or not isinstance(child.get("summary"), str):
            raise ValueError("presentation child requires string title and summary")
        if "detail" in child and not isinstance(child["detail"], str):
            raise ValueError("presentation child detail must be a string when supplied")


def _grade_counts(results: Sequence[Mapping[str, Any]], field: str) -> dict[str, int]:
    counts = Counter(str(item[field]) for item in results)
    return {grade: counts[grade] for grade in GRADES}


def _report(merged: Mapping[str, Any]) -> str:
    fidelity = cast(Mapping[str, int], merged["fidelity_grade_counts"])
    shape = cast(Mapping[str, int], merged["packet_shape_grade_counts"])
    excluded = cast(Sequence[Mapping[str, Any]], merged["reader_excluded"])
    return "\n".join(
        [
            "# M15 Phase 05 whole-game AI summary coverage",
            "",
            f"- Summary coverage: **PASS ({merged['packet_count']}/{merged['packet_count']})**",
            f"- Deferred: **{len(cast(Sequence[object], merged['deferred']))}**",
            f"- Reader-visible story corridors: **{merged['reader_packet_count']}**",
            f"- Reader-excluded technical corridors: **{len(excluded)}**",
            "- Fidelity grades: " + ", ".join(f"{key}={value}" for key, value in fidelity.items()),
            "- Packet-shape grades: " + ", ".join(f"{key}={value}" for key, value in shape.items()),
            "",
            "## Reader exclusions",
            "",
            *[
                (
                    f"- Packet {item['canonical_packet_index']} (`{item['corridor_id']}`): "
                    f"{item['title']} - {item['grade_reason']}"
                )
                for item in excluded
            ],
            "",
            "## Reader policy",
            "",
            "- Exclude only packet-shape FAIL items, which are non-story technical messages.",
            (
                "- Keep PASS, PARTIAL, and LOW corridors visible; their grades remain "
                "available for QA."
            ),
            (
                "- Python corridor IDs and order remain the mechanical authority. "
                "AI prose is presentation only."
            ),
            "",
        ]
    )


def main() -> int:
    args = _arguments()
    canonical_path = args.canonical_packets.resolve(strict=True)
    first_ten_path = args.first_ten.resolve(strict=True)
    bulk_dir = args.bulk_dir.resolve(strict=True)
    output_dir = args.output_dir.resolve()

    canonical = _load_object(canonical_path)
    packets = canonical.get("packets")
    if not isinstance(packets, list) or not packets:
        raise ValueError("canonical packet artifact must contain a non-empty packets list")

    canary = _load_object(first_ten_path)
    canary_results = canary.get("results")
    if not isinstance(canary_results, list) or len(canary_results) != 10:
        raise ValueError("first-ten artifact must contain exactly 10 results")
    results = [_normalize_canary(cast(Mapping[str, Any], item)) for item in canary_results]

    source_paths = [canonical_path, first_ten_path]
    expected_start = 11
    for part_number in range(1, 5):
        part_path = bulk_dir / f"part-{part_number:02d}.json"
        part = _load_object(part_path)
        source_paths.append(part_path)
        start = part.get("range_start")
        end = part.get("range_end")
        expected_count = part.get("expected_count")
        part_results = part.get("results")
        deferred = part.get("deferred")
        if start != expected_start or not isinstance(end, int):
            raise ValueError(f"{part_path} has a non-contiguous range")
        if expected_count != end - start + 1:
            raise ValueError(f"{part_path} expected_count does not match its range")
        if not isinstance(part_results, list) or not isinstance(deferred, list):
            raise ValueError(f"{part_path} results and deferred must be lists")
        if deferred:
            raise ValueError(
                f"{part_path} contains deferred items; merge requires complete coverage"
            )
        if len(part_results) != expected_count:
            raise ValueError(f"{part_path} result count does not match its range")
        results.extend(cast(list[dict[str, Any]], part_results))
        expected_start = end + 1

    if len(results) != len(packets):
        raise ValueError(
            f"summary count {len(results)} does not match canonical packet count {len(packets)}"
        )

    seen_indices: set[int] = set()
    seen_corridors: set[str] = set()
    for expected_index, (summary, packet) in enumerate(zip(results, packets, strict=True), start=1):
        _validate_result(summary)
        index = cast(int, summary["canonical_packet_index"])
        corridor_id = cast(str, summary["corridor_id"])
        if index != expected_index:
            raise ValueError(f"expected packet index {expected_index}, found {index}")
        if not isinstance(packet, dict) or corridor_id != packet.get("corridor_id"):
            raise ValueError(f"corridor mismatch at canonical packet index {expected_index}")
        if index in seen_indices or corridor_id in seen_corridors:
            raise ValueError(f"duplicate summary at canonical packet index {expected_index}")
        seen_indices.add(index)
        seen_corridors.add(corridor_id)

    fidelity_counts = _grade_counts(results, "fidelity_grade")
    shape_counts = _grade_counts(results, "packet_shape_grade")
    reader_excluded = [
        {
            "canonical_packet_index": item["canonical_packet_index"],
            "corridor_id": item["corridor_id"],
            "title": item["title"],
            "grade_reason": item["grade_reason"],
        }
        for item in results
        if item["packet_shape_grade"] == "FAIL"
    ]

    merged = {
        "schema": "m15-phase05-whole-game-ai-summaries-v1",
        "canonical_input": str(canonical_path),
        "authority_bindings": canary.get("authority_bindings", {}),
        "packet_count": len(results),
        "reader_packet_count": len(results) - len(reader_excluded),
        "reader_excluded": reader_excluded,
        "deferred": [],
        "fidelity_grade_counts": fidelity_counts,
        "packet_shape_grade_counts": shape_counts,
        "source_hashes": {path.name: _hash(path) for path in source_paths},
        "results": results,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    merged_path = output_dir / "whole-game-ai-summaries.json"
    report_path = output_dir / "SUMMARY_COVERAGE.md"
    _write_json(merged_path, merged)
    report_path.write_text(_report(merged), encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "summaries": str(merged_path),
                "report": str(report_path),
                "packet_count": len(results),
                "reader_packet_count": merged["reader_packet_count"],
                "fidelity_grade_counts": fidelity_counts,
                "packet_shape_grade_counts": shape_counts,
                "summaries_sha256": _hash(merged_path),
                "report_sha256": _hash(report_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
