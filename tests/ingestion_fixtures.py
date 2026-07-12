"""Generated, non-story M06 fixtures; no recovered game content is stored in the repository."""

from __future__ import annotations

import pickle
import subprocess
import sys
import zlib
from pathlib import Path

_RPA_KEY = 0x42424242


def make_rpa(path: Path, files: dict[str, bytes]) -> Path:
    header_placeholder = b"RPA-3.0 0000000000000000 42424242\n"
    payload = bytearray()
    index: dict[str, list[tuple[int, int]]] = {}
    offset = len(header_placeholder)
    for name, content in files.items():
        payload.extend(content)
        index[name] = [(offset ^ _RPA_KEY, len(content) ^ _RPA_KEY)]
        offset += len(content)
    header = f"RPA-3.0 {offset:016x} {_RPA_KEY:08x}\n".encode("ascii")
    path.write_bytes(header + payload + zlib.compress(pickle.dumps(index, protocol=2)))
    return path


def make_modern_rpyc(*, label_name: str = "start", line: int = 1) -> bytes:
    helper = Path(__file__).with_name("rpyc_fixture_helper.py")
    executable = str(getattr(sys, "_base_executable", sys.executable))
    completed = subprocess.run(
        [executable, "-I", "-S", "-B", str(helper), label_name, str(line)],
        check=True,
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )
    return completed.stdout
