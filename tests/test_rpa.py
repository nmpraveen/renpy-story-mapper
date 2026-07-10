from __future__ import annotations

import io
import pickle
import zlib
from pathlib import Path
from typing import Any

import pytest

from renpy_story_mapper.cli import main
from renpy_story_mapper.errors import ArchiveFormatError
from renpy_story_mapper.importer import inventory_archive, iter_utf8_lines
from renpy_story_mapper.project import (
    create_archive_project,
    open_project,
    refresh_archive_project,
)
from renpy_story_mapper.rpa import RpaArchive, fingerprint_file

KEY = 0x42424242


def make_archive(
    path: Path,
    files: dict[str, bytes],
    *,
    index_override: object | None = None,
    pickled_index: bytes | None = None,
) -> Path:
    header_placeholder = b"RPA-3.0 0000000000000000 42424242\n"
    payload = bytearray()
    index: dict[str, list[tuple[int, int]]] = {}
    offset = len(header_placeholder)
    for name, content in files.items():
        payload.extend(content)
        index[name] = [(offset ^ KEY, len(content) ^ KEY)]
        offset += len(content)
    raw_index = (
        pickled_index
        if pickled_index is not None
        else pickle.dumps(index if index_override is None else index_override, protocol=2)
    )
    header = f"RPA-3.0 {offset:016x} {KEY:08x}\n".encode("ascii")
    assert len(header) == len(header_placeholder)
    path.write_bytes(header + payload + zlib.compress(raw_index))
    return path


def test_safe_archive_streams_entries_and_inventory_prefers_source(tmp_path: Path) -> None:
    archive_path = make_archive(
        tmp_path / "scripts.rpa",
        {"game/script.rpy": b"label start:\n    return\n", "game/script.rpyc": b"compiled"},
    )
    before = fingerprint_file(archive_path)
    archive = RpaArchive(archive_path)
    result = inventory_archive(archive, before)
    assert b"".join(archive.iter_entry_bytes("game/script.rpy")) == (b"label start:\n    return\n")
    assert result.manifest["counts"] == {
        "entries": 2,
        "by_extension": {".rpy": 1, ".rpyc": 1},
        "source_compiled_pairs": 1,
        "selected_source_files": 1,
    }
    assert result.selected_sources[0].path == "game/script.rpy"
    assert fingerprint_file(archive_path) == before


class _Dangerous:
    def __reduce__(self) -> tuple[Any, tuple[str]]:
        return eval, ("40 + 2",)


def test_restrictive_unpickler_rejects_globals(tmp_path: Path) -> None:
    archive_path = make_archive(tmp_path / "global.rpa", {}, index_override={"bad": _Dangerous()})
    with pytest.raises(ArchiveFormatError, match="attempted to load global"):
        RpaArchive(archive_path)


class _PersistentPickler(pickle.Pickler):
    def persistent_id(self, obj: object) -> str | None:
        return "forbidden" if obj == "MARKER" else None


def test_restrictive_unpickler_rejects_persistent_ids(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    _PersistentPickler(buffer, protocol=2).dump({"bad": "MARKER"})
    archive_path = make_archive(tmp_path / "persistent.rpa", {}, pickled_index=buffer.getvalue())
    with pytest.raises(ArchiveFormatError, match="persistent id"):
        RpaArchive(archive_path)


@pytest.mark.parametrize(
    "unsafe",
    [
        "../escape.rpy",
        "/absolute.rpy",
        "C:/drive.rpy",
        "a\\b.rpy",
        "foo//bar.rpy",
        "foo/./bar.rpy",
        "foo/",
    ],
)
def test_archive_rejects_path_traversal_and_unsafe_paths(tmp_path: Path, unsafe: str) -> None:
    header_size = len(b"RPA-3.0 0000000000000000 42424242\n")
    index = {unsafe: [(header_size ^ KEY, 0 ^ KEY)]}
    archive_path = make_archive(tmp_path / "unsafe.rpa", {}, index_override=index)
    with pytest.raises(ArchiveFormatError, match="unsafe archive path"):
        RpaArchive(archive_path)


def test_archive_rejects_invalid_offsets(tmp_path: Path) -> None:
    index = {"game/script.rpy": [(9_999_999 ^ KEY, 12 ^ KEY)]}
    archive_path = make_archive(tmp_path / "offset.rpa", {}, index_override=index)
    with pytest.raises(ArchiveFormatError, match="outside the archive data region"):
        RpaArchive(archive_path)


@pytest.mark.parametrize(
    "malformed",
    [
        {"game/script.rpy": "not chunks"},
        {"game/script.rpy": [(1,)]},
        {"game/script.rpy": [(True, 1)]},
    ],
)
def test_archive_rejects_malformed_entries(tmp_path: Path, malformed: object) -> None:
    archive_path = make_archive(tmp_path / "malformed.rpa", {}, index_override=malformed)
    with pytest.raises(ArchiveFormatError):
        RpaArchive(archive_path)


def test_archive_rejects_trailing_pickle_data(tmp_path: Path) -> None:
    raw = pickle.dumps({}, protocol=2) + pickle.dumps({}, protocol=2)
    archive_path = make_archive(tmp_path / "trailing.rpa", {}, pickled_index=raw)
    with pytest.raises(ArchiveFormatError, match="trailing pickle data"):
        RpaArchive(archive_path)


def test_archive_rejects_unreasonable_decompression_size(tmp_path: Path) -> None:
    archive_path = make_archive(tmp_path / "large-index.rpa", {"a": b"x"})
    with pytest.raises(ArchiveFormatError, match="decompressed RPA index exceeds"):
        RpaArchive(archive_path, max_decompressed_index=4)


def test_archive_rejects_unreasonable_aggregate_logical_size(tmp_path: Path) -> None:
    archive_path = make_archive(tmp_path / "aggregate.rpa", {"a": b"123", "b": b"456"})
    with pytest.raises(ArchiveFormatError, match="aggregate logical archive size"):
        RpaArchive(archive_path, max_total_logical_size=5)


def test_cli_refuses_to_overwrite_input_archive(tmp_path: Path) -> None:
    archive_path = make_archive(tmp_path / "scripts.rpa", {"game/script.rpy": b"label start:\n"})
    before = archive_path.read_bytes()
    assert main(["inspect", str(archive_path), "--output", str(archive_path)]) == 2
    assert archive_path.read_bytes() == before


def test_cli_analyze_writes_deterministic_semantic_story(tmp_path: Path) -> None:
    archive_path = make_archive(
        tmp_path / "scripts.rpa",
        {
            "game/script.rpy": (
                b'label start:\n    "Opening."\n    jump ending\n\n'
                b'label ending:\n    "Done."\n    return\n'
            )
        },
    )
    before = fingerprint_file(archive_path)
    first_output = tmp_path / "first"
    second_output = tmp_path / "second"

    assert main(["analyze", str(archive_path), "--output-dir", str(first_output)]) == 0
    assert main(["analyze", str(archive_path), "--output-dir", str(second_output)]) == 0

    first = (first_output / "semantic-story.json").read_bytes()
    second = (second_output / "semantic-story.json").read_bytes()
    assert first == second
    assert b'"schema_version": 1' in first
    assert fingerprint_file(archive_path) == before


def test_archive_project_is_durable_incremental_and_read_only(tmp_path: Path) -> None:
    archive_path = make_archive(
        tmp_path / "scripts.rpa",
        {
            "game/script.rpy": (
                b"label start:\n    if wits > 0:\n        $ love += 1\n    return\n"
            ),
            "game/script.rpyc": b"compiled",
        },
    )
    project_path = tmp_path / "story.rsmproj"
    before = fingerprint_file(archive_path)

    project = create_archive_project(project_path, archive_path)
    authoritative = project.authoritative_bytes()
    snapshot = project.snapshot()
    project.close()

    assert snapshot["import_manifest"]["archive_integrity"]["verified_unchanged"] is True
    assert snapshot["requirements"][0]["original_expression"] == "wits > 0"
    assert snapshot["effects"][0]["original_expression"] == "love += 1"
    report = refresh_archive_project(project_path, archive_path)
    assert report.parsed_sources == ()
    assert report.reused_sources == ("game/script.rpy",)
    reopened = open_project(project_path)
    try:
        assert reopened.authoritative_bytes() == authoritative
    finally:
        reopened.close()
    assert fingerprint_file(archive_path) == before


def test_incremental_utf8_decoder_handles_split_characters() -> None:
    encoded = 'label start:\n    "café"\n'.encode()
    split = encoded.index(b"\xc3") + 1
    assert list(iter_utf8_lines([encoded[:split], encoded[split:]], source="test.rpy")) == [
        "label start:\n",
        '    "café"\n',
    ]
