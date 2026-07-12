"""Isolated Unrpyc worker. This module is launched in a bounded child process only."""

from __future__ import annotations

import hashlib
import io
import json
import os
import struct
import sys
import zlib
from pathlib import Path
from typing import NoReturn


class HelperFailure(Exception):
    pass


_AUDIT_WORK_ROOT: Path | None = None
_AUDIT_READ_ROOTS: tuple[Path, ...] = ()


class _BoundedLog(list[str]):
    def __init__(self, limit: int) -> None:
        super().__init__()
        self._limit = limit
        self._size = 0

    def append(self, value: str) -> None:
        size = len(value.encode("utf-8", errors="replace"))
        if self._size + size > self._limit:
            raise HelperFailure("recovery warnings exceed configured log limit")
        self._size += size
        super().append(value)


class _BoundedTextWriter(io.TextIOBase):
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._size = 0
        self._parts: list[str] = []

    def writable(self) -> bool:
        return True

    def write(self, value: str) -> int:
        encoded_size = len(value.encode("utf-8"))
        if self._size + encoded_size > self._limit:
            raise HelperFailure("reconstructed output exceeds configured byte limit")
        self._size += encoded_size
        self._parts.append(value)
        return len(value)

    def value(self) -> str:
        return "".join(self._parts)


def _audit(event: str, args: tuple[object, ...]) -> None:
    forbidden = (
        "socket.",
        "subprocess.",
        "os.system",
        "os.posix_spawn",
        "os.spawn",
        "ctypes.dlopen",
    )
    if event.startswith(forbidden):
        raise PermissionError(f"helper operation is disabled: {event}")
    if event == "open" and args and not isinstance(args[0], int):
        raw_path = args[0]
        if not isinstance(raw_path, str | bytes | os.PathLike):
            raise PermissionError(f"helper filesystem operation is disabled: {event}")
        path = Path(os.fsdecode(raw_path)).resolve()
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else 0
        writing = (
            isinstance(mode, str)
            and any(marker in mode for marker in ("w", "a", "x", "+"))
        ) or (
            isinstance(flags, int)
            and bool(
                flags
                & (
                    os.O_WRONLY
                    | os.O_RDWR
                    | os.O_CREAT
                    | os.O_TRUNC
                    | os.O_APPEND
                )
            )
        )
        allowed = (
            (_AUDIT_WORK_ROOT,) if writing else (*_AUDIT_READ_ROOTS, _AUDIT_WORK_ROOT)
        )
        if not any(root is not None and _is_within(path, root) for root in allowed):
            raise PermissionError(f"helper filesystem operation is disabled: {event}")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _bounded_decompress(blob: bytes, limit: int) -> bytes:
    try:
        decoder = zlib.decompressobj()
        output = decoder.decompress(blob, limit + 1)
        if len(output) > limit or decoder.unconsumed_tail:
            raise HelperFailure("compiled payload exceeds decompression limit")
        tail = decoder.flush(limit + 1 - len(output))
        output += tail
    except zlib.error as exc:
        raise HelperFailure("compiled payload is not valid zlib data") from exc
    if len(output) > limit or not decoder.eof or decoder.unused_data:
        raise HelperFailure("compiled payload is truncated, oversized, or has trailing data")
    return output


def _modern_payload(raw: bytes, max_decompressed_bytes: int) -> bytes:
    if not raw.startswith(b"RENPY RPC2"):
        raise HelperFailure(
            "unsupported compiled source: only modern RENPY RPC2 inputs are accepted"
        )
    position = 10
    chunks: dict[int, bytes] = {}
    for expected_slot in range(1, 4097):
        if position + 12 > len(raw):
            raise HelperFailure("malformed RENPY RPC2 chunk table")
        slot, start, length = struct.unpack_from("<III", raw, position)
        position += 12
        if slot == 0:
            break
        if slot != expected_slot:
            raise HelperFailure("unsupported modified RENPY RPC2 chunk table")
        end = start + length
        if end < start or start < position or end > len(raw):
            raise HelperFailure("RENPY RPC2 chunk points outside the input")
        chunks[slot] = raw[start:end]
    else:
        raise HelperFailure("RENPY RPC2 chunk table exceeds slot limit")
    if 1 not in chunks:
        raise HelperFailure("RENPY RPC2 source AST chunk is missing")
    return _bounded_decompress(chunks[1], max_decompressed_bytes)


def _safe_child(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise HelperFailure("helper path escapes its private working directory") from exc
    return resolved


def _run(work_root: Path) -> dict[str, object]:
    request_path = work_root / "request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        raise HelperFailure("helper request must be a JSON object")
    input_path = _safe_child(work_root / str(request["input_name"]), work_root)
    output_path = _safe_child(work_root / str(request["output_name"]), work_root)
    max_input = int(request["max_input_bytes"])
    max_output = int(request["max_output_bytes"])
    max_decompressed = int(request["max_decompressed_bytes"])
    max_log = int(request["max_log_bytes"])
    size = input_path.stat().st_size
    if size > max_input:
        raise HelperFailure("compiled source exceeds configured input limit")
    raw = input_path.read_bytes()
    if len(raw) != size:
        raise HelperFailure("compiled source changed during helper read")
    payload = _modern_payload(raw, max_decompressed)

    vendor_root = Path(__file__).resolve().parent / "_vendor" / "unrpyc"
    sys.path.insert(0, str(vendor_root))
    import decompiler  # type: ignore[import-not-found]
    from decompiler.renpycompat import (  # type: ignore[import-not-found]
        pickle_detect_python2,
        pickle_safe_loads,
    )

    if pickle_detect_python2(payload):
        raise HelperFailure("unsupported ancient Python 2-era compiled source")
    try:
        _metadata, statements = pickle_safe_loads(payload)
    except Exception as exc:
        raise HelperFailure("unsupported, obfuscated, or malformed compiled source") from exc
    logs = _BoundedLog(max_log)
    writer = _BoundedTextWriter(max_output)
    options = decompiler.Options(
        log=logs,
        translator=None,
        init_offset=False,
        sl_custom_names=None,
    )
    decompiler.pprint(writer, statements, options)
    output = writer.value().encode("utf-8")
    output_path.write_bytes(output)
    sanitized = tuple(str(item).replace("\r", " ").replace("\n", " ")[:240] for item in logs)
    return {
        "status": "ok",
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "output_sha256": hashlib.sha256(output).hexdigest(),
        "output_size": len(output),
        "complete": not sanitized,
        "warnings": list(sanitized),
    }


def _fail(work_root: Path, message: str) -> NoReturn:
    clean = " ".join(message.replace("\x00", "").split())[:500]
    (work_root / "result.json").write_text(
        json.dumps({"status": "error", "error": clean}, sort_keys=True),
        encoding="utf-8",
    )
    raise SystemExit(2)


def main() -> int:
    global _AUDIT_READ_ROOTS, _AUDIT_WORK_ROOT
    if len(sys.argv) != 2:
        return 64
    work_root = Path(sys.argv[1]).resolve(strict=True)
    _AUDIT_WORK_ROOT = work_root
    vendor_root = Path(__file__).resolve().parent / "_vendor" / "unrpyc"
    stdlib_root = Path(os.__file__).resolve().parent
    _AUDIT_READ_ROOTS = (vendor_root, stdlib_root)
    sys.addaudithook(_audit)
    try:
        result = _run(work_root)
    except Exception as exc:
        _fail(work_root, str(exc) or type(exc).__name__)
    (work_root / "result.json").write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
