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
from renpy_story_mapper.parser import parse_script
from renpy_story_mapper.rpa import ArchiveFingerprint, RpaArchive, fingerprint_file


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
    archive_path = Path(args.archive)
    output = Path(args.output)
    _reject_archive_output(archive_path, [output])
    before = fingerprint_file(archive_path)
    archive = RpaArchive(archive_path)
    result = inventory_archive(archive, before)
    after = fingerprint_file(archive_path)
    if before != after:
        raise StoryMapperError("archive hash, size, or modification time changed during inspection")
    manifest = _manifest_with_integrity(result.manifest, before=before, after=after)
    _write_json(output, manifest)
    counts = manifest["counts"]
    assert isinstance(counts, dict)
    print(
        f"Inspected {counts['entries']} entries; selected "
        f"{counts['selected_source_files']} source files."
    )
    print(f"Manifest: {output.resolve()}")
    return 0


def _analyze(args: argparse.Namespace) -> int:
    archive_path = Path(args.archive)
    output_dir = Path(args.output_dir)
    manifest_path = output_dir / "import-manifest.json"
    graph_path = output_dir / "story-graph.json"
    _reject_archive_output(archive_path, [manifest_path, graph_path])
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

    after = fingerprint_file(archive_path)
    if before != after:
        raise StoryMapperError("archive hash, size, or modification time changed during analysis")
    manifest = _manifest_with_integrity(inventory.manifest, before=before, after=after)

    _write_json(manifest_path, manifest)
    _write_json(graph_path, graph)

    print(
        f"Graph from label {args.entry_label!r}: {counts['nodes']} nodes, "
        f"{counts['edges']} edges, {counts['unresolved']} unresolved."
    )
    print(f"Manifest: {manifest_path.resolve()}")
    print(f"Graph: {graph_path.resolve()}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="renpy-story-mapper",
        description="Safely inventory RPA 3.0 archives and build inert Ren'Py control-flow graphs.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="write a deterministic import manifest")
    inspect_parser.add_argument("archive", help="path to an RPA 3.0 archive")
    inspect_parser.add_argument(
        "--output", default="artifacts/import-manifest.json", help="manifest JSON path"
    )
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    handler: Any = args.handler
    try:
        return int(handler(args))
    except (StoryMapperError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
