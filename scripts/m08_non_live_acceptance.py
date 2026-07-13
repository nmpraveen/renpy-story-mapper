"""Run the checked-in M08 evaluation path without constructing or invoking a provider."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from renpy_story_mapper.evaluation.contracts import (
    AccountingSnapshot,
    EvaluationDecision,
    Provenance,
    ProviderProfile,
)
from renpy_story_mapper.evaluation.loading import load_baseline, load_candidate
from renpy_story_mapper.evaluation.manifest import EvaluationManifest
from renpy_story_mapper.evaluation.runner import evaluate

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "m08"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def run(output_dir: Path | None) -> dict[str, object]:
    manifest = EvaluationManifest.load(FIXTURES / "evaluation-manifest.json")
    baseline = load_baseline(FIXTURES / "technical-baseline.json")
    candidate = load_candidate(FIXTURES / "validated-ai.json")
    fresh = evaluate(manifest, "complex-fixture", baseline, candidate)
    repeated = evaluate(manifest, "complex-fixture", baseline, candidate)
    if fresh.decision is not EvaluationDecision.ACCEPTED or fresh.digest != repeated.digest:
        raise RuntimeError("fresh evaluation was rejected or nondeterministic")

    replay_candidate = replace(
        candidate,
        run_id="mock-zero-call-replay",
        accounting=AccountingSnapshot(0, 0, 0, 0, 41, 4, 0, 0, 0, True),
        provider=ProviderProfile(False, "gpt-5.6-luna", "high", False),
        provenance=Provenance("mocked_replay", False, False, False),
    )
    replay = evaluate(manifest, "complex-fixture", baseline, replay_candidate)
    if replay.decision is not EvaluationDecision.ACCEPTED or replay.comparison.accounting.calls:
        raise RuntimeError("zero-call replay was not accepted")

    strict_scope = replace(
        manifest.scope("complex-fixture"),
        bounds=replace(
            manifest.scope("complex-fixture").bounds,
            window=replace(
                manifest.scope("complex-fixture").bounds.window,
                require_strict_subset=True,
            ),
        ),
    )
    strict_manifest = replace(manifest, scopes=(strict_scope, *manifest.scopes[1:]))
    global_rejection = evaluate(strict_manifest, "complex-fixture", baseline, candidate)
    if global_rejection.decision is not EvaluationDecision.REJECTED:
        raise RuntimeError("a global parent scope was accepted as a bounded window")

    summary: dict[str, object] = {
        "schema_version": 1,
        "provider_calls_made_by_harness": 0,
        "fresh_decision": fresh.decision.value,
        "fresh_report_sha256": fresh.digest,
        "repeated_report_sha256": repeated.digest,
        "replay_decision": replay.decision.value,
        "replay_report_sha256": replay.digest,
        "replay_calls": replay.comparison.accounting.calls,
        "global_scope_decision": global_rejection.decision.value,
        "global_scope_report_sha256": global_rejection.digest,
    }
    if output_dir is not None:
        _write(output_dir / "fresh-report.json", fresh.to_dict())
        _write(output_dir / "replay-report.json", replay.to_dict())
        _write(output_dir / "browser-comparison.json", fresh.comparison.to_dict())
        _write(output_dir / "acceptance-summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    summary = run(args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
