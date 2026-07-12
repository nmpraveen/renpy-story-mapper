from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path
from typing import Any

from renpy_story_mapper import __version__
from renpy_story_mapper.errors import StoryMapperError
from renpy_story_mapper.graph import build_graph
from renpy_story_mapper.importer import inventory_archive, iter_utf8_lines
from renpy_story_mapper.ingestion import IngestionOptions, ingest_input, inspect_input
from renpy_story_mapper.ingestion.export import export_recovered_sources
from renpy_story_mapper.parser import parse_script
from renpy_story_mapper.project import (
    Project,
    create_ingested_project,
    delete_project,
    refresh_ingested_project,
)
from renpy_story_mapper.rpa import ArchiveFingerprint, RpaArchive, fingerprint_file
from renpy_story_mapper.semantic import build_semantic_story
from renpy_story_mapper.storage import ProjectStorageError


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _reject_archive_output(archive: Path, outputs: list[Path]) -> None:
    archive_resolved = archive.resolve(strict=True)
    for output in outputs:
        if output.resolve(strict=False) == archive_resolved:
            raise StoryMapperError(f"refusing to overwrite input archive with output: {output}")


def _manifest_with_integrity(
    manifest: dict[str, object], *, before: ArchiveFingerprint, after: ArchiveFingerprint
) -> dict[str, object]:
    value = dict(manifest)
    value["archive_integrity"] = {
        "verified_unchanged": before == after,
        "before": before.to_dict(),
        "after": after.to_dict(),
    }
    return value


def _inspect(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    output = Path(args.output)
    if input_path.is_file():
        _reject_archive_output(input_path, [output])
    plan = inspect_input(input_path, _ingestion_options(args))
    manifest = {
        "schema_version": 2,
        "requested_path": str(plan.requested_path),
        "resolved_input": str(plan.resolved_input),
        "input_kind": plan.input_kind.value,
        "source_root": None if plan.source_root is None else str(plan.source_root),
        "existing_project": (None if plan.existing_project is None else str(plan.existing_project)),
        "warnings": list(plan.warnings),
        "candidates": [_candidate_value(item) for item in plan.candidates],
        "selected": [_candidate_value(item) for item in plan.selected],
    }
    _write_json(output, manifest)
    print(f"Inspected {len(plan.candidates)} candidates; selected {len(plan.selected)} sources.")
    print(f"Manifest: {output.resolve()}")
    return 0


def _candidate_value(value: object) -> dict[str, object]:
    from renpy_story_mapper.ingestion.contracts import SourceCandidate

    if not isinstance(value, SourceCandidate):
        raise TypeError("ingestion candidate has an unexpected type")
    return {
        "logical_path": value.logical_path,
        "tier": value.tier.value,
        "locator": value.locator,
        "input_sha256": value.input_hash,
        "size_bytes": value.size_bytes,
        "archive_entry": value.archive_entry,
    }


def _ingestion_options(args: argparse.Namespace) -> IngestionOptions:
    raw_cache = getattr(args, "cache_root", None)
    return IngestionOptions(
        allow_partial_recovery=bool(getattr(args, "allow_partial_recovery", False)),
        cache_root=None if raw_cache is None else Path(raw_cache),
    )


def _analyze(args: argparse.Namespace) -> int:
    archive_path = Path(args.archive)
    output_dir = Path(args.output_dir)
    manifest_path = output_dir / "import-manifest.json"
    graph_path = output_dir / "story-graph.json"
    semantic_path = output_dir / "semantic-story.json"
    _reject_archive_output(archive_path, [manifest_path, graph_path, semantic_path])
    before = fingerprint_file(archive_path)
    archive = RpaArchive(archive_path)
    inventory = inventory_archive(archive, before)

    modules = []
    for entry in inventory.selected_sources:
        lines = iter_utf8_lines(archive.iter_entry_bytes(entry), source=entry.path)
        modules.append(parse_script(entry.path, lines))
    if not modules:
        raise StoryMapperError(
            "archive contains no .rpy source; Phase 1 intentionally does not decompile .rpyc"
        )

    all_paths = {module.path for module in modules}
    scope_paths: set[str] | None = None
    if args.scope_glob:
        scope_paths = {
            path
            for path in all_paths
            if any(fnmatch.fnmatchcase(path, pattern) for pattern in args.scope_glob)
        }
        if not scope_paths:
            raise StoryMapperError(
                f"scope patterns matched no source paths: {', '.join(args.scope_glob)}"
            )

    graph = build_graph(modules, entry_label=args.entry_label, scope_paths=scope_paths)
    diagnostic_modules = (
        modules
        if scope_paths is None
        else [module for module in modules if module.path in scope_paths]
    )
    diagnostics = [item for module in diagnostic_modules for item in module.diagnostics]
    diagnostics.sort(
        key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    graph["diagnostics"] = diagnostics
    counts = graph["counts"]
    assert isinstance(counts, dict)
    counts["diagnostics"] = len(diagnostics)
    semantic_story = build_semantic_story(graph)

    after = fingerprint_file(archive_path)
    if before != after:
        raise StoryMapperError("archive hash, size, or modification time changed during analysis")
    manifest = _manifest_with_integrity(inventory.manifest, before=before, after=after)

    _write_json(manifest_path, manifest)
    _write_json(graph_path, graph)
    _write_json(semantic_path, semantic_story)

    print(
        f"Graph from label {args.entry_label!r}: {counts['nodes']} nodes, "
        f"{counts['edges']} edges, {counts['unresolved']} unresolved."
    )
    print(f"Manifest: {manifest_path.resolve()}")
    print(f"Graph: {graph_path.resolve()}")
    print(f"Semantic story: {semantic_path.resolve()}")
    return 0


def _project_create(args: argparse.Namespace) -> int:
    source = Path(args.source).resolve(strict=True)
    project_path = Path(args.project)
    _reject_project_in_source(source, project_path)
    project = create_ingested_project(
        project_path,
        source,
        entry_label=args.entry_label,
        options=_ingestion_options(args),
    )
    try:
        snapshot = project.snapshot()
        print(_project_summary(snapshot))
        print(f"Project: {project.path}")
    finally:
        project.close()
    return 0


def _project_refresh(args: argparse.Namespace) -> int:
    source = Path(args.source).resolve(strict=True)
    project_path = Path(args.project)
    _reject_project_in_source(source, project_path)
    report = refresh_ingested_project(
        project_path,
        source,
        options=_ingestion_options(args),
    )
    print(
        f"Parsed {len(report.parsed_sources)}; reused {len(report.reused_sources)}; "
        f"invalidated {len(report.invalidated_sources)}; removed {len(report.removed_sources)}."
    )
    return 0


def _project_show(args: argparse.Namespace) -> int:
    with Project.open(args.project) as project:
        snapshot = project.snapshot()
        if args.output:
            output = Path(args.output)
            _write_json(output, snapshot)
            print(f"Snapshot: {output.resolve()}")
        print(_project_summary(snapshot))
    return 0


def _project_delete(args: argparse.Namespace) -> int:
    project_path = Path(args.project).resolve(strict=True)
    delete_project(project_path)
    print(f"Deleted project: {project_path}")
    return 0


def _recover_export(args: argparse.Namespace) -> int:
    result = ingest_input(args.input, _ingestion_options(args))
    destination = export_recovered_sources(result, args.destination)
    print(f"Recovered-source export: {destination}")
    return 0


def _project_summary(snapshot: dict[str, object]) -> str:
    def count(name: str) -> int:
        value = snapshot.get(name)
        return len(value) if isinstance(value, list) else 0

    graph = snapshot.get("graph")
    graph_counts = graph.get("counts", {}) if isinstance(graph, dict) else {}
    nodes = graph_counts.get("nodes", 0) if isinstance(graph_counts, dict) else 0
    edges = graph_counts.get("edges", 0) if isinstance(graph_counts, dict) else 0
    return (
        f"Project snapshot: {nodes} nodes, {edges} edges, "
        f"{count('requirements')} requirements, {count('effects')} effects, "
        f"{count('unresolved')} unresolved."
    )


def _reject_project_in_source(source: Path, project_path: Path) -> None:
    destination = project_path.resolve(strict=False)
    if destination == source:
        raise StoryMapperError("project path cannot overwrite the selected source")
    if source.is_dir():
        try:
            destination.relative_to(source)
        except ValueError:
            return
        raise StoryMapperError("project path must be outside the selected game folder")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="renpy-story-mapper",
        description="Safely inventory RPA 3.0 archives and build inert Ren'Py control-flow graphs.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="write a deterministic input manifest")
    inspect_parser.add_argument("input", help="game folder, source, archive, or project")
    inspect_parser.add_argument(
        "--output", default="artifacts/import-manifest.json", help="manifest JSON path"
    )
    inspect_parser.add_argument("--cache-root")
    inspect_parser.set_defaults(handler=_inspect)

    analyze_parser = subparsers.add_parser(
        "analyze", help="inventory source and build a source-linked directed graph"
    )
    analyze_parser.add_argument("archive", help="path to an RPA 3.0 archive")
    analyze_parser.add_argument(
        "--output-dir", default="artifacts/sample", help="artifact output directory"
    )
    analyze_parser.add_argument("--entry-label", default="start", help="static entry label")
    analyze_parser.add_argument(
        "--scope-glob",
        action="append",
        help="include labels in matching archive source paths; repeatable",
    )
    analyze_parser.set_defaults(handler=_analyze)

    project_parser = subparsers.add_parser(
        "project", help="create, refresh, inspect, or delete a durable SQLite project"
    )
    project_commands = project_parser.add_subparsers(dest="project_command", required=True)

    create_parser = project_commands.add_parser("create", help="analyze into a new project")
    create_parser.add_argument("source", help="game source folder or scripts.rpa archive")
    create_parser.add_argument("project", help="new .rsmproj path outside the game folder")
    create_parser.add_argument("--entry-label", default="start", help="static entry label")
    create_parser.add_argument("--allow-partial-recovery", action="store_true")
    create_parser.add_argument("--cache-root")
    create_parser.set_defaults(handler=_project_create)

    refresh_parser = project_commands.add_parser(
        "refresh", help="incrementally refresh an existing project"
    )
    refresh_parser.add_argument("source", help="game source folder or scripts.rpa archive")
    refresh_parser.add_argument("project", help="existing .rsmproj path")
    refresh_parser.add_argument("--allow-partial-recovery", action="store_true")
    refresh_parser.add_argument("--cache-root")
    refresh_parser.set_defaults(handler=_project_refresh)

    show_parser = project_commands.add_parser("show", help="summarize a durable project")
    show_parser.add_argument("project", help="existing .rsmproj path")
    show_parser.add_argument("--output", help="optional deterministic JSON snapshot path")
    show_parser.set_defaults(handler=_project_show)

    delete_parser = project_commands.add_parser("delete", help="delete a durable project")
    delete_parser.add_argument("project", help="existing .rsmproj path")
    delete_parser.set_defaults(handler=_project_delete)

    export_parser = subparsers.add_parser(
        "recover-export", help="explicitly export reconstructed source with provenance"
    )
    export_parser.add_argument("input", help="compiled source, archive, or game folder")
    export_parser.add_argument("destination", help="new destination outside the source/game")
    export_parser.add_argument("--allow-partial-recovery", action="store_true")
    export_parser.add_argument("--cache-root")
    export_parser.set_defaults(handler=_recover_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    handler: Any = args.handler
    try:
        return int(handler(args))
    except (ProjectStorageError, StoryMapperError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
