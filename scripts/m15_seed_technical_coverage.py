"""Create an explicit M15 working copy with one locator-proven technical prefix."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from renpy_story_mapper.narrative_map import SourceLocator
from renpy_story_mapper.narrative_map.coverage_corrections import (
    seed_leading_technical_correction_working_copy,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-project", type=Path, required=True)
    parser.add_argument("--output-project", type=Path, required=True)
    parser.add_argument(
        "--locator",
        nargs=4,
        action="append",
        metavar=("RELATIVE_PATH", "START_LINE", "END_LINE", "LINE_BASIS"),
        required=True,
    )
    arguments = parser.parse_args()
    locators = tuple(
        SourceLocator(path, int(start), int(end), basis)
        for path, start, end, basis in arguments.locator
    )
    source_before = _fingerprint(arguments.source_project)
    write = seed_leading_technical_correction_working_copy(
        arguments.source_project,
        arguments.output_project,
        locators,
    )
    source_after = _fingerprint(arguments.source_project)
    if source_before != source_after:
        raise RuntimeError("source comparison project changed while seeding the working copy")
    print(
        json.dumps(
            {
                "schema": "m15-leading-technical-working-copy-report-v1",
                "output_project": str(arguments.output_project.resolve()),
                "correction_id": write.correction_id,
                "normalized_hash": write.normalized_hash,
                "locator_count": len(locators),
                "reused": write.reused,
                "source_project_sha256": source_before[0],
                "source_project_size": source_before[1],
                "source_project_mtime_ns": source_before[2],
                "source_project_unchanged": True,
                "provider_calls": 0,
                "game_execution_count": 0,
            },
            sort_keys=True,
        )
    )
    return 0


def _fingerprint(path: Path) -> tuple[str, int, int]:
    resolved = path.resolve()
    stat = resolved.stat()
    return hashlib.sha256(resolved.read_bytes()).hexdigest(), stat.st_size, stat.st_mtime_ns


if __name__ == "__main__":
    raise SystemExit(main())
