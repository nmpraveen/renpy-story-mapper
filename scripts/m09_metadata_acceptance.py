from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from pathlib import Path
from typing import cast

from renpy_story_mapper import storage
from renpy_story_mapper.project import Project
from renpy_story_mapper.project_analysis import create_input_project, refresh_input_project
from renpy_story_mapper.rpa import fingerprint_file
from renpy_story_mapper.web.api import ProjectApi

_AUTHORITY_COLLECTIONS = (
    "effects",
    "gates",
    "m01_graph",
    "m02_semantic",
    "m06_control_flow",
    "m07_route_map",
    "unresolved",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the read-only M09 metadata acceptance")
    parser.add_argument("--game-folder", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    arguments = parser.parse_args()

    game = arguments.game_folder.resolve(strict=True)
    output = arguments.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    project_path = output / "msdenvers-m09.rsmproj"
    report_path = output / "acceptance.json"
    if project_path.exists() or report_path.exists():
        raise FileExistsError("M09 acceptance output already exists; select an empty directory")

    archives = tuple(game / name for name in ("scripts.rpa", "extras.rpa"))
    before = [_fingerprint(path) for path in archives]
    started = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="rsm-m09-baseline-") as temporary:
        baseline_path = Path(temporary) / "baseline.rsmproj"
        create_input_project(baseline_path, archives[0]).close()
        with Project.open(baseline_path) as baseline:
            baseline_authority = _authority_hash(baseline)

    create_input_project(project_path, game).close()
    created_seconds = time.perf_counter() - started
    with Project.open(project_path) as project:
        authority = _authority_hash(project)
        metadata = project.payload("story_metadata", "authoritative")
        if not isinstance(metadata, dict):
            raise AssertionError("story metadata payload is missing")
        graph = storage.canonical_json(project.payload("m01_graph", "authoritative"))
        if b"primeira_memoria" in graph:
            raise AssertionError("secondary replay label entered the canonical graph")
        source_rows = project.sources()
        derivations = project.source_derivations()
        state = project.payload("state_registry", "authoritative")
        if not isinstance(state, list):
            raise AssertionError("state registry is missing")
        integrity = str(project._require_open().execute("PRAGMA integrity_check").fetchone()[0])

    refresh_started = time.perf_counter()
    refresh = refresh_input_project(project_path, game)
    refresh_seconds = time.perf_counter() - refresh_started
    after = [_fingerprint(path) for path in archives]
    if before != after:
        raise AssertionError("a read-only acceptance archive changed")
    if authority != baseline_authority:
        raise AssertionError("metadata enrichment changed deterministic authority")
    if refresh.parsed_sources:
        raise AssertionError("unchanged refresh reparsed canonical story sources")

    provider_calls: list[object] = []

    def forbidden_provider(scope: object) -> object:
        provider_calls.append(scope)
        raise AssertionError("project opening must not construct a provider")

    api = ProjectApi(_NoDialogs(), m07_provider_factory=forbidden_provider)
    api._project_path = project_path
    try:
        search_page = cast(
            dict[str, object],
            api.dispatch(
                "POST",
                "/api/v1/story/search",
                {"query": "Gene points", "limit": 25},
            ),
        )
    finally:
        api.close()
    search_items = cast(list[object], search_page["items"])
    if not search_items:
        raise AssertionError("readable metadata label is not searchable through the browser API")
    if provider_calls:
        raise AssertionError("browser project opening invoked a provider")

    state_by_name = {
        str(item["original_name"]): item
        for item in state
        if isinstance(item, dict) and isinstance(item.get("original_name"), str)
    }
    expected_labels = {
        name: cast(dict[str, object], state_by_name[name]).get("display_name")
        for name in ("lust", "gen", "loi_rom", "wanda_dom")
        if name in state_by_name
    }
    report = {
        "schema_version": 1,
        "game_folder": str(game),
        "project": str(project_path),
        "safety": {
            "game_python_executed": False,
            "cloud_ai_invoked": False,
            "archives_unchanged": True,
            "replay_in_canonical_graph": False,
        },
        "archives": before,
        "authority": {
            "baseline_sha256": baseline_authority,
            "enriched_sha256": authority,
            "unchanged": True,
        },
        "sources": {
            "inventory": len(source_rows),
            "derivations": len(derivations),
            "canonical": sum(
                1 for item in cast(list[dict[str, object]], metadata["sources"])
                if item.get("role") == "canonical"
            ),
            "secondary_metadata": sum(
                1 for item in cast(list[dict[str, object]], metadata["sources"])
                if item.get("role") == "secondary_metadata"
            ),
        },
        "metadata": {
            "characters": len(cast(list[object], metadata["characters"])),
            "state_hints": len(cast(list[object], metadata["state_hints"])),
            "scene_titles": len(cast(list[object], metadata["scene_titles"])),
            "diagnostics": len(cast(list[object], metadata["diagnostics"])),
            "labeled_state_variables": sum(
                1 for item in state if isinstance(item, dict) and item.get("metadata_display_name")
            ),
            "declared_defaults": sum(
                1 for item in state if isinstance(item, dict) and item.get("default_declared")
            ),
            "expected_labels": expected_labels,
        },
        "performance": {
            "create_seconds": round(created_seconds, 3),
            "unchanged_refresh_seconds": round(refresh_seconds, 3),
            "unchanged_refresh_parsed_sources": len(refresh.parsed_sources),
        },
        "browser_api": {
            "readable_label_search_results": len(search_items),
            "provider_calls": len(provider_calls),
        },
        "sqlite_integrity_check": integrity,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _authority_hash(project: Project) -> str:
    rows = project._require_open().execute(
        f"""SELECT collection,record_key,payload_hash FROM payloads
            WHERE collection IN ({','.join('?' for _ in _AUTHORITY_COLLECTIONS)})
            ORDER BY collection,record_key""",
        _AUTHORITY_COLLECTIONS,
    )
    digest = hashlib.sha256()
    for row in rows:
        digest.update(storage.canonical_json([str(value) for value in row]))
    return digest.hexdigest()


def _fingerprint(path: Path) -> dict[str, object]:
    value = fingerprint_file(path)
    return {
        "name": path.name,
        "sha256": value.sha256,
        "size_bytes": value.size,
        "last_write_time_utc": value.last_write_time_utc,
    }


class _NoDialogs:
    def choose_source(self, _kind: str) -> None:
        return None

    def choose_open_project(self) -> None:
        return None

    def choose_save_project(self) -> None:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
