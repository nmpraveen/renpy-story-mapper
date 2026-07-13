"""Command-line entry point for non-live M08 evaluation artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from renpy_story_mapper.evaluation.contracts import EvaluationDecision, sha256_json
from renpy_story_mapper.evaluation.loading import ArtifactError, load_baseline, load_candidate
from renpy_story_mapper.evaluation.manifest import EvaluationManifest, ManifestError
from renpy_story_mapper.evaluation.runner import evaluate


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _validate_manifest(args: argparse.Namespace) -> int:
    manifest = EvaluationManifest.load(args.manifest)
    print(f"Manifest: {manifest.id}")
    print(f"Scopes: {len(manifest.scopes)}")
    print(f"SHA-256: {sha256_json(manifest.to_dict())}")
    print("Provider calls: 0 (manifest validation is local and path-slot only)")
    return 0


def _evaluate(args: argparse.Namespace) -> int:
    manifest = EvaluationManifest.load(args.manifest)
    baseline = load_baseline(args.baseline)
    candidate = load_candidate(args.candidate)
    report = evaluate(manifest, args.scope, baseline, candidate)
    output = Path(args.output)
    _write_json(output, report.to_dict())
    if args.comparison_output:
        _write_json(Path(args.comparison_output), report.comparison.to_dict())
    print(f"Decision: {report.decision.value}")
    print(f"Score: {report.score:.6f}")
    print(f"Report SHA-256: {report.digest}")
    print(f"Report: {output.resolve()}")
    print("Provider calls made by evaluator: 0")
    return 0 if report.decision is not EvaluationDecision.REJECTED else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m renpy_story_mapper.evaluation",
        description="Compare deterministic authority and validated story organization offline.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser(
        "validate-manifest", help="validate safety, path-slot, scope, and rubric contracts"
    )
    validate.add_argument("--manifest", required=True)
    validate.set_defaults(handler=_validate_manifest)

    run = commands.add_parser(
        "evaluate", help="score a technical baseline and validated organization without a provider"
    )
    run.add_argument("--manifest", required=True)
    run.add_argument("--scope", required=True)
    run.add_argument("--baseline", required=True)
    run.add_argument("--candidate", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--comparison-output")
    run.set_defaults(handler=_evaluate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    handler: Any = args.handler
    try:
        return int(handler(args))
    except (ArtifactError, ManifestError, KeyError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
