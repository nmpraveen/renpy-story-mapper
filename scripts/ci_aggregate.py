from __future__ import annotations

import argparse
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

FULL_JOBS = ("plan", "quality", "package", "shards")


def evaluate_truth_table(run_full: str, results: Mapping[str, str]) -> bool:
    if results.get("classifier") != "success" or results.get("contract") != "success":
        raise ValueError("classifier and workflow contract must both succeed")
    if run_full == "true":
        invalid = {name: results.get(name) for name in FULL_JOBS if results.get(name) != "success"}
        if invalid:
            raise ValueError(f"full deterministic jobs must all succeed: {invalid}")
        return True
    if run_full == "false":
        invalid = {name: results.get(name) for name in FULL_JOBS if results.get(name) != "skipped"}
        if invalid:
            raise ValueError(f"docs-only full jobs must all be skipped: {invalid}")
        return False
    raise ValueError("classifier must emit run_full=true or run_full=false")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate the stable CI aggregate truth table.")
    parser.add_argument("--github-output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    results = {
        "classifier": os.environ.get("CLASSIFIER_RESULT", ""),
        "contract": os.environ.get("CONTRACT_RESULT", ""),
        "plan": os.environ.get("PLAN_RESULT", ""),
        "quality": os.environ.get("QUALITY_RESULT", ""),
        "package": os.environ.get("PACKAGE_RESULT", ""),
        "shards": os.environ.get("SHARDS_RESULT", ""),
    }
    verify_reports = evaluate_truth_table(os.environ.get("RUN_FULL", ""), results)
    with arguments.github_output.open("a", encoding="utf-8") as output:
        output.write(f"verify_reports={'true' if verify_reports else 'false'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
