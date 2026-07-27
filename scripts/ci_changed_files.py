from __future__ import annotations

import argparse
import subprocess
from collections.abc import Sequence
from pathlib import Path

FINAL_PRODUCT_HEAD = "codex/m15-phase04-full-game"


def classify_changes(
    event_name: str,
    head_ref: str,
    changes: Sequence[tuple[str, ...]],
) -> str:
    if event_name != "pull_request" or head_ref == FINAL_PRODUCT_HEAD or not changes:
        return "full"
    for change in changes:
        if len(change) != 2 or change[0] not in {"A", "M"}:
            return "full"
        path = change[1].replace("\\", "/")
        if not path.startswith("docs/") or path.startswith("docs/../"):
            return "full"
    return "docs-only"


def read_name_status(base: str, head: str, root: Path) -> tuple[tuple[str, ...], ...]:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-status",
            "-z",
            "--diff-filter=ACDMRTUXB",
            f"{base}...{head}",
        ],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
    tokens = result.stdout.decode("utf-8", errors="strict").split("\0")
    if tokens and tokens[-1] == "":
        tokens.pop()
    changes: list[tuple[str, ...]] = []
    index = 0
    while index < len(tokens):
        status = tokens[index]
        index += 1
        path_count = 2 if status.startswith(("R", "C")) else 1
        if index + path_count > len(tokens):
            raise RuntimeError("git diff returned an incomplete name-status record")
        paths = tuple(tokens[index : index + path_count])
        changes.append((status, *paths))
        index += path_count
    return tuple(changes)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Classify strict docs-only pull request changes.")
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--head-ref", default="")
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--github-output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    changes = (
        read_name_status(arguments.base, arguments.head, arguments.root)
        if arguments.event_name == "pull_request"
        else ()
    )
    mode = classify_changes(arguments.event_name, arguments.head_ref, changes)
    with arguments.github_output.open("a", encoding="utf-8") as output:
        output.write(f"mode={mode}\n")
        output.write(f"run_full={'true' if mode == 'full' else 'false'}\n")
    print(f"CI change classification: {mode}; records={len(changes)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
