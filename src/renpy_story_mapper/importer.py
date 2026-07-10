from __future__ import annotations

import codecs
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath

from renpy_story_mapper.errors import ArchiveFormatError
from renpy_story_mapper.rpa import ArchiveFingerprint, RpaArchive, RpaEntry


@dataclass(frozen=True)
class InventoryResult:
    manifest: dict[str, object]
    selected_sources: tuple[RpaEntry, ...]


def iter_utf8_lines(chunks: Iterable[bytes], *, source: str) -> Iterator[str]:
    """Incrementally decode UTF-8 archive bytes and yield physical source lines."""

    decoder = codecs.getincrementaldecoder("utf-8-sig")("strict")
    pending = ""
    try:
        for chunk in chunks:
            pending += decoder.decode(chunk)
            lines = pending.splitlines(keepends=True)
            pending = (
                lines.pop() if lines and not lines[-1].endswith(("\r", "\n")) else ""
            )
            yield from lines
        pending += decoder.decode(b"", final=True)
    except UnicodeDecodeError as error:
        raise ArchiveFormatError(f"{source} is not valid UTF-8 source: {error}") from error
    if pending:
        yield pending


def inventory_archive(
    archive: RpaArchive,
    fingerprint: ArchiveFingerprint,
) -> InventoryResult:
    entries: list[dict[str, object]] = []
    by_stem: dict[str, dict[str, RpaEntry]] = {}

    for entry in archive.entries:
        suffix = PurePosixPath(entry.path).suffix.lower()
        stem = entry.path[: -len(suffix)] if suffix else entry.path
        digest = archive.hash_entry(entry)
        entry_value: dict[str, object] = {
            "path": entry.path,
            "size": entry.size,
            "sha256": digest,
            "extension": suffix,
        }
        entries.append(entry_value)
        if suffix in (".rpy", ".rpyc"):
            by_stem.setdefault(stem, {})[suffix] = entry

    pairings: list[dict[str, object]] = []
    selected: list[RpaEntry] = []
    for stem in sorted(by_stem):
        variants = by_stem[stem]
        source = variants.get(".rpy")
        compiled = variants.get(".rpyc")
        chosen = source or compiled
        if source is not None:
            selected.append(source)
        pairings.append(
            {
                "stem": stem,
                "source": source.path if source else None,
                "compiled": compiled.path if compiled else None,
                "selected": chosen.path if chosen else None,
                "selection_reason": "source_preferred" if source else "compiled_only",
                "decompilation_attempted": False,
            }
        )

    counts: dict[str, int] = {}
    for item in entries:
        extension = str(item["extension"])
        counts[extension] = counts.get(extension, 0) + 1

    manifest: dict[str, object] = {
        "schema_version": 1,
        "import_policy": {
            "archive_mode": "read_only_streaming",
            "source_preferred": True,
            "decompilation_attempted": False,
            "creator_code_executed": False,
        },
        "archive": {
            "path": str(archive.path),
            **fingerprint.to_dict(),
            "format": "RPA-3.0",
            "index_offset": archive.index_offset,
        },
        "counts": {
            "entries": len(entries),
            "by_extension": dict(sorted(counts.items())),
            "source_compiled_pairs": sum(
                1 for variants in by_stem.values() if ".rpy" in variants and ".rpyc" in variants
            ),
            "selected_source_files": len(selected),
        },
        "entries": entries,
        "pairings": pairings,
    }
    return InventoryResult(manifest, tuple(sorted(selected, key=lambda item: item.path)))
