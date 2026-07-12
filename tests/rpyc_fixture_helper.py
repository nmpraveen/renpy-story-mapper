"""Trusted test-only generator for tiny synthetic modern RPYC files."""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path


def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository / "src"))
    from renpy_story_mapper.ingestion._vendor.unrpyc.decompiler import renpycompat

    label_name = sys.argv[1]
    line = int(sys.argv[2])
    label_type = next(item for item in renpycompat.SPECIAL_CLASSES if item.__name__ == "Label")
    return_type = next(item for item in renpycompat.SPECIAL_CLASSES if item.__name__ == "Return")
    label = label_type()
    label.__dict__["name"] = label_name
    label.linenumber = line
    label.filename = "generated.rpy"
    returned = return_type()
    returned.linenumber = line + 1
    returned.filename = "generated.rpy"
    label.block = [returned]
    pickled = renpycompat.pickle_safe_dumps(({}, [label]))
    payload = zlib.compress(pickled)
    start = 10 + 12 + 12
    output = (
        b"RENPY RPC2"
        + struct.pack("<III", 1, start, len(payload))
        + struct.pack("<III", 0, 0, 0)
        + payload
    )
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
