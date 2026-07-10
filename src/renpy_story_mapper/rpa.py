from __future__ import annotations

import hashlib
import io
import os
import pickle
import stat
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, NoReturn

from renpy_story_mapper.errors import ArchiveFormatError

HEADER_LIMIT = 128
DEFAULT_MAX_COMPRESSED_INDEX = 64 * 1024 * 1024
DEFAULT_MAX_DECOMPRESSED_INDEX = 128 * 1024 * 1024
DEFAULT_MAX_ENTRY_SIZE = 512 * 1024 * 1024
DEFAULT_MAX_ENTRIES = 100_000
DEFAULT_MAX_TOTAL_LOGICAL_SIZE = 4 * 1024 * 1024 * 1024
DEFAULT_MAX_CHUNKS = 1_000_000
IO_CHUNK_SIZE = 1024 * 1024


class _RestrictedUnpickler(pickle.Unpickler):
    """Unpickler that permits only pickle's inert built-in data opcodes."""

    def find_class(self, module: str, name: str) -> NoReturn:
        raise ArchiveFormatError(f"RPA index attempted to load global {module}.{name}")

    def persistent_load(self, pid: object) -> NoReturn:
        raise ArchiveFormatError(f"RPA index used forbidden persistent id {pid!r}")


@dataclass(frozen=True)
class RpaChunk:
    offset: int
    length: int
    prefix: bytes


@dataclass(frozen=True)
class RpaEntry:
    path: str
    chunks: tuple[RpaChunk, ...]

    @property
    def size(self) -> int:
        return sum(len(chunk.prefix) + chunk.length for chunk in self.chunks)


@dataclass(frozen=True)
class ArchiveFingerprint:
    size: int
    sha256: str
    last_write_time_utc: str

    def to_dict(self) -> dict[str, object]:
        return {
            "size": self.size,
            "sha256": self.sha256,
            "last_write_time_utc": self.last_write_time_utc,
        }


def fingerprint_file(path: Path) -> ArchiveFingerprint:
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ArchiveFormatError(f"archive is not a regular file: {path}")

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(IO_CHUNK_SIZE):
            digest.update(block)

    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ArchiveFormatError("archive changed while it was being fingerprinted")

    from datetime import UTC, datetime

    modified = datetime.fromtimestamp(after.st_mtime, UTC).isoformat().replace("+00:00", "Z")
    return ArchiveFingerprint(after.st_size, digest.hexdigest(), modified)


class RpaArchive:
    """Read-only RPA 3.0 archive with bounded, restrictive index parsing."""

    def __init__(
        self,
        path: Path,
        *,
        max_compressed_index: int = DEFAULT_MAX_COMPRESSED_INDEX,
        max_decompressed_index: int = DEFAULT_MAX_DECOMPRESSED_INDEX,
        max_entry_size: int = DEFAULT_MAX_ENTRY_SIZE,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_total_logical_size: int = DEFAULT_MAX_TOTAL_LOGICAL_SIZE,
        max_chunks: int = DEFAULT_MAX_CHUNKS,
    ) -> None:
        self.path = path.resolve(strict=True)
        self.max_compressed_index = max_compressed_index
        self.max_decompressed_index = max_decompressed_index
        self.max_entry_size = max_entry_size
        self.max_entries = max_entries
        self.max_total_logical_size = max_total_logical_size
        self.max_chunks = max_chunks
        self._file_size = self.path.stat().st_size
        self._header_end = 0
        self._index_offset = 0
        self._key = 0
        self._entries: dict[str, RpaEntry] = {}
        self._load()

    @property
    def entries(self) -> tuple[RpaEntry, ...]:
        return tuple(self._entries[name] for name in sorted(self._entries))

    @property
    def index_offset(self) -> int:
        return self._index_offset

    def get(self, name: str) -> RpaEntry:
        try:
            return self._entries[name]
        except KeyError as error:
            raise ArchiveFormatError(f"archive entry does not exist: {name}") from error

    def iter_entry_bytes(self, entry: RpaEntry | str) -> Iterator[bytes]:
        selected = self.get(entry) if isinstance(entry, str) else entry
        with self.path.open("rb") as stream:
            for chunk in selected.chunks:
                if chunk.prefix:
                    yield chunk.prefix
                stream.seek(chunk.offset)
                remaining = chunk.length
                while remaining:
                    block = stream.read(min(IO_CHUNK_SIZE, remaining))
                    if not block:
                        raise ArchiveFormatError(
                            f"unexpected end of archive while reading {selected.path}"
                        )
                    remaining -= len(block)
                    yield block

    def read_entry(self, entry: RpaEntry | str, *, limit: int | None = None) -> bytes:
        selected = self.get(entry) if isinstance(entry, str) else entry
        effective_limit = self.max_entry_size if limit is None else min(limit, self.max_entry_size)
        if selected.size > effective_limit:
            raise ArchiveFormatError(
                f"entry {selected.path} is {selected.size} bytes, over limit {effective_limit}"
            )
        return b"".join(self.iter_entry_bytes(selected))

    def hash_entry(self, entry: RpaEntry | str) -> str:
        digest = hashlib.sha256()
        for block in self.iter_entry_bytes(entry):
            digest.update(block)
        return digest.hexdigest()

    def _load(self) -> None:
        with self.path.open("rb") as stream:
            header = stream.readline(HEADER_LIMIT + 1)
            if len(header) > HEADER_LIMIT or not header.endswith(b"\n"):
                raise ArchiveFormatError("RPA header is missing or too long")
            self._header_end = stream.tell()
            self._parse_header(header)
            index_bytes = self._decompress_index(stream)

        index_stream = io.BytesIO(index_bytes)
        try:
            raw_index = _RestrictedUnpickler(index_stream).load()
        except ArchiveFormatError:
            raise
        except (pickle.UnpicklingError, EOFError, ValueError, TypeError) as error:
            raise ArchiveFormatError(f"invalid RPA index pickle: {error}") from error
        if index_stream.read(1):
            raise ArchiveFormatError("RPA index contains trailing pickle data")

        self._entries = self._validate_index(raw_index)

    def _parse_header(self, header: bytes) -> None:
        try:
            text = header.decode("ascii").strip()
        except UnicodeDecodeError as error:
            raise ArchiveFormatError("RPA header is not ASCII") from error
        fields = text.split()
        if len(fields) != 3 or fields[0] != "RPA-3.0":
            raise ArchiveFormatError("only RPA-3.0 archives are supported")
        try:
            index_offset = int(fields[1], 16)
            key = int(fields[2], 16)
        except ValueError as error:
            raise ArchiveFormatError("RPA header contains invalid hexadecimal fields") from error
        if index_offset < self._header_end or index_offset >= self._file_size:
            raise ArchiveFormatError("RPA index offset is outside the archive")
        self._index_offset = index_offset
        self._key = key

    def _decompress_index(self, stream: BinaryIO) -> bytes:
        compressed_size = self._file_size - self._index_offset
        if compressed_size > self.max_compressed_index:
            raise ArchiveFormatError(
                f"compressed RPA index is {compressed_size} bytes, over limit "
                f"{self.max_compressed_index}"
            )
        stream.seek(self._index_offset)
        decompressor = zlib.decompressobj()
        output = bytearray()
        remaining = compressed_size
        while remaining:
            block = stream.read(min(IO_CHUNK_SIZE, remaining))
            if not block:
                raise ArchiveFormatError("truncated RPA index")
            remaining -= len(block)
            try:
                decoded = decompressor.decompress(
                    block, self.max_decompressed_index - len(output) + 1
                )
            except zlib.error as error:
                raise ArchiveFormatError(f"invalid compressed RPA index: {error}") from error
            output.extend(decoded)
            if len(output) > self.max_decompressed_index or decompressor.unconsumed_tail:
                raise ArchiveFormatError("decompressed RPA index exceeds safety limit")
        try:
            output.extend(decompressor.flush(self.max_decompressed_index - len(output) + 1))
        except zlib.error as error:
            raise ArchiveFormatError(f"invalid compressed RPA index: {error}") from error
        if len(output) > self.max_decompressed_index:
            raise ArchiveFormatError("decompressed RPA index exceeds safety limit")
        if not decompressor.eof:
            raise ArchiveFormatError("truncated compressed RPA index")
        if decompressor.unused_data:
            raise ArchiveFormatError("trailing data after compressed RPA index")
        return bytes(output)

    def _validate_index(self, raw_index: object) -> dict[str, RpaEntry]:
        if not isinstance(raw_index, dict):
            raise ArchiveFormatError("RPA index root must be a dictionary")
        if len(raw_index) > self.max_entries:
            raise ArchiveFormatError(f"RPA index has more than {self.max_entries} entries")

        validated: dict[str, RpaEntry] = {}
        casefolded: set[str] = set()
        total_logical_size = 0
        total_chunks = 0
        for raw_name, raw_chunks in raw_index.items():
            name = self._validate_name(raw_name)
            folded = name.casefold()
            if folded in casefolded:
                raise ArchiveFormatError(f"duplicate case-insensitive archive path: {name}")
            casefolded.add(folded)
            if not isinstance(raw_chunks, (list, tuple)) or not raw_chunks:
                raise ArchiveFormatError(f"entry {name} has no valid chunks")

            chunks: list[RpaChunk] = []
            total = 0
            for raw_chunk in raw_chunks:
                total_chunks += 1
                if total_chunks > self.max_chunks:
                    raise ArchiveFormatError(
                        f"RPA index has more than {self.max_chunks} chunks"
                    )
                if not isinstance(raw_chunk, tuple) or len(raw_chunk) not in (2, 3):
                    raise ArchiveFormatError(f"entry {name} has a malformed chunk")
                raw_offset, raw_length = raw_chunk[0], raw_chunk[1]
                if type(raw_offset) is not int or type(raw_length) is not int:
                    raise ArchiveFormatError(f"entry {name} has non-integer offset or length")
                offset = raw_offset ^ self._key
                length = raw_length ^ self._key
                prefix_value = raw_chunk[2] if len(raw_chunk) == 3 else b""
                if not isinstance(prefix_value, bytes):
                    raise ArchiveFormatError(f"entry {name} has a non-bytes prefix")
                if offset < self._header_end or length < 0 or offset + length > self._index_offset:
                    raise ArchiveFormatError(f"entry {name} points outside the archive data region")
                total += len(prefix_value) + length
                total_logical_size += len(prefix_value) + length
                if total_logical_size > self.max_total_logical_size:
                    raise ArchiveFormatError(
                        "aggregate logical archive size exceeds safety limit"
                    )
                if total > self.max_entry_size:
                    raise ArchiveFormatError(
                        f"entry {name} exceeds the {self.max_entry_size}-byte safety limit"
                    )
                chunks.append(RpaChunk(offset, length, prefix_value))
            validated[name] = RpaEntry(name, tuple(chunks))
        return validated

    @staticmethod
    def _validate_name(raw_name: object) -> str:
        if isinstance(raw_name, bytes):
            try:
                name = raw_name.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ArchiveFormatError("archive path is not valid UTF-8") from error
        elif isinstance(raw_name, str):
            name = raw_name
        else:
            raise ArchiveFormatError("archive path is not text")

        if not name or "\x00" in name or "\\" in name:
            raise ArchiveFormatError(f"unsafe archive path: {name!r}")
        raw_parts = name.split("/")
        if any(part in ("", ".", "..") for part in raw_parts):
            raise ArchiveFormatError(f"unsafe archive path: {name!r}")
        path = PurePosixPath(name)
        if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
            raise ArchiveFormatError(f"unsafe archive path: {name!r}")
        if any(":" in part for part in path.parts):
            raise ArchiveFormatError(f"unsafe archive path: {name!r}")
        normalized = path.as_posix()
        if os.path.normcase(normalized).startswith(os.path.normcase("../")):
            raise ArchiveFormatError(f"unsafe archive path: {name!r}")
        return normalized
