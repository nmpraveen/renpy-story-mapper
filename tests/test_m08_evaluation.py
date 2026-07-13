from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from renpy_story_mapper.evaluation.cli import main
from renpy_story_mapper.evaluation.contracts import (
    AccountingSnapshot,
    AuthoritySnapshot,
    CoverageSnapshot,
    EvaluationCandidate,
    EvaluationDecision,
    EvaluationStatus,
    EvaluationWindowSnapshot,
    EvidenceReference,
    FeatureAnnotation,
    InterpretationClaim,
    Provenance,
    ProviderProfile,
    TechnicalBaseline,
)
from renpy_story_mapper.evaluation.loading import load_baseline, load_candidate
from renpy_story_mapper.evaluation.manifest import EvaluationManifest, ManifestError
from renpy_story_mapper.evaluation.runner import evaluate

FIXTURES = Path(__file__).parent / "fixtures" / "m08"
MANIFEST = FIXTURES / "evaluation-manifest.json"
BASELINE = FIXTURES / "technical-baseline.json"
CANDIDATE = FIXTURES / "validated-ai.json"
INVALID_CASES = json.loads((FIXTURES / "invalid-ai-cases.json").read_text(encoding="utf-8"))


def _inputs() -> tuple[EvaluationManifest, TechnicalBaseline, EvaluationCandidate]:
    return EvaluationManifest.load(MANIFEST), load_baseline(BASELINE), load_candidate(CANDIDATE)


def test_manifest_covers_all_inputs_and_external_windows_are_unresolved_slots() -> None:
    manifest = EvaluationManifest.load(MANIFEST)
    assert len(manifest.scopes) == 7
    complex_scope = manifest.scope("complex-fixture")
    assert complex_scope.bounds.window.resolved
    assert complex_scope.input.input_sha256 == (
        "383cdc77af981acf27f80c54d018060c126e6824f7bf29c2d6ec9a9a73fae650"
    )
    for scope in manifest.scopes[1:]:
        assert scope.input.external
        assert scope.input.repository_path is None
        assert not scope.bounds.window.resolved
        assert scope.bounds.window.id_set_slot
        assert scope.bounds.window.id_set_fingerprint_slot
    msd = [scope for scope in manifest.scopes if scope.id.startswith("msdenvers-")]
    assert len(msd) == 4
    assert {scope.bounds.window.parent_scope_id for scope in msd} == {
        "route_scope_13004aa8febf656c5f04"
    }
    assert all(scope.bounds.window.require_strict_subset for scope in msd)
    assert all(scope.bounds.window.max_evidence == 256 for scope in msd)


def test_manifest_schema_is_checked_in_and_forbids_extra_fields() -> None:
    schema = json.loads((FIXTURES / "evaluation-manifest.schema.json").read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert schema["properties"]["provider_policy"]["properties"]["model"]["const"] == (
        "gpt-5.6-luna"
    )
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    value["forbidden_extra_field"] = "rejected"
    with pytest.raises(ManifestError, match="strict schema"):
        EvaluationManifest.from_value(value)


def test_validated_resume_scores_every_rubric_dimension_and_is_accepted() -> None:
    manifest, baseline, candidate = _inputs()
    report = evaluate(manifest, "complex-fixture", baseline, candidate)
    assert report.decision is EvaluationDecision.ACCEPTED
    assert report.score == 1.0
    assert all(item.passed for item in report.guardrails)
    assert [item.id for item in report.criteria] == [
        "scene_boundaries",
        "meaningful_events",
        "concise_titles",
        "concise_summaries",
        "character_development",
        "route_meaning",
        "temporary_detours",
        "persistent_routes",
        "loops",
        "endings",
        "evidence_support",
        "ai_coverage",
        "technical_fallback",
        "resource_accounting",
        "cache_replay",
        "authority_preservation",
        "walkthrough_independence",
    ]
    assert report.comparison.accounting.cancelled_attempts == 1
    assert report.comparison.accounting.resumed_scopes == 1
    assert report.comparison.technical["window"] == baseline.window.to_dict()


def test_repeated_reports_have_identical_bytes_and_hashes() -> None:
    manifest = EvaluationManifest.load(MANIFEST)
    baseline = load_baseline(BASELINE)
    candidate = load_candidate(CANDIDATE)
    first = evaluate(manifest, "complex-fixture", baseline, candidate)
    second = evaluate(manifest, "complex-fixture", baseline, candidate)
    assert first.to_dict() == second.to_dict()
    assert first.digest == second.digest
    assert first.digest == "29c5b2895a6264efaca1ce325bd5b1525f1aaadb328f00289d2f37742a4dd906"
    assert json.dumps(first.to_dict(), sort_keys=True, separators=(",", ":")) == json.dumps(
        second.to_dict(), sort_keys=True, separators=(",", ":")
    )


@pytest.mark.parametrize(
    "invented_kind",
    [
        item["id"].removeprefix("invented_").replace("missing_evidence", "evidence")
        for item in INVALID_CASES["cases"][:4]
    ],
)
def test_invented_authority_and_missing_evidence_fail_closed(invented_kind: str) -> None:
    manifest = EvaluationManifest.load(MANIFEST)
    baseline = load_baseline(BASELINE)
    candidate = load_candidate(CANDIDATE)
    if invented_kind == "member":
        group = replace(candidate.groups[-1], member_ids=("invented-node",))
        candidate = replace(candidate, groups=(*candidate.groups[:-1], group))
    elif invented_kind == "edge":
        annotation = replace(candidate.annotations[0], edge_ids=("invented-edge",))
        candidate = replace(candidate, annotations=(annotation, *candidate.annotations[1:]))
    elif invented_kind == "fact":
        annotation = replace(candidate.annotations[0], fact_ids=("invented-fact",))
        candidate = replace(candidate, annotations=(annotation, *candidate.annotations[1:]))
    else:
        claim = InterpretationClaim("Unsupported claim.", ("invented-evidence",))
        group = replace(candidate.groups[0], claims=(claim,))
        candidate = replace(candidate, groups=(group, *candidate.groups[1:]))
    report = evaluate(manifest, "complex-fixture", baseline, candidate)
    assert report.decision is EvaluationDecision.REJECTED
    assert any(not item.passed for item in report.guardrails)


def test_changed_deterministic_authority_fails_closed() -> None:
    manifest = EvaluationManifest.load(MANIFEST)
    baseline = load_baseline(BASELINE)
    candidate = load_candidate(CANDIDATE)
    authority = AuthoritySnapshot(
        candidate.authority.element_ids,
        candidate.authority.edges,
        (*candidate.authority.fact_ids, "invented-fact"),
        (*candidate.authority.evidence, EvidenceReference("invented-ev", ("invented-fact",))),
    )
    report = evaluate(
        manifest, "complex-fixture", baseline, replace(candidate, authority=authority)
    )
    assert report.decision is EvaluationDecision.REJECTED
    assert not next(item for item in report.guardrails if item.id == "authority_unchanged").passed


def test_partial_cancelled_coverage_is_honest_but_not_accepted() -> None:
    manifest = EvaluationManifest.load(MANIFEST)
    baseline = load_baseline(BASELINE)
    candidate = load_candidate(CANDIDATE)
    groups = candidate.groups[:4]
    covered = tuple(member for group in groups for member in group.member_ids)
    partial = replace(
        candidate,
        run_id="mock-partial-cancelled",
        status=EvaluationStatus.CANCELLED,
        groups=groups,
        annotations=candidate.annotations[:4],
        coverage=CoverageSnapshot(candidate.coverage.eligible_ids, covered, ()),
        accounting=AccountingSnapshot(2, 2, 1800, 500, 650, 0, 2, 0, 1, False),
    )
    report = evaluate(manifest, "complex-fixture", baseline, partial)
    assert report.decision is EvaluationDecision.PARTIAL
    assert report.comparison.coverage.ai_ratio == pytest.approx(5 / 11)
    assert next(item for item in report.guardrails if item.id == "honest_completion").passed


def test_misleading_nominal_completion_is_rejected() -> None:
    manifest = EvaluationManifest.load(MANIFEST)
    baseline = load_baseline(BASELINE)
    candidate = load_candidate(CANDIDATE)
    groups = candidate.groups[:2]
    covered = tuple(member for group in groups for member in group.member_ids)
    dishonest = replace(
        candidate,
        groups=groups,
        annotations=(),
        coverage=CoverageSnapshot(candidate.coverage.eligible_ids, covered, ()),
    )
    report = evaluate(manifest, "complex-fixture", baseline, dishonest)
    assert report.decision is EvaluationDecision.REJECTED
    assert not next(item for item in report.guardrails if item.id == "honest_completion").passed


def test_zero_call_cache_replay_is_accepted_and_accounted() -> None:
    manifest = EvaluationManifest.load(MANIFEST)
    baseline = load_baseline(BASELINE)
    candidate = load_candidate(CANDIDATE)
    replay = replace(
        candidate,
        run_id="mock-zero-call-replay",
        accounting=AccountingSnapshot(0, 0, 0, 0, 41, 4, 0, 0, 0, True),
        provider=ProviderProfile(False, "gpt-5.6-luna", "high", False),
        provenance=Provenance("mocked_replay", False, False, False),
    )
    report = evaluate(manifest, "complex-fixture", baseline, replay)
    assert report.decision is EvaluationDecision.ACCEPTED
    assert report.comparison.accounting.calls == 0
    assert report.comparison.accounting.cache_hits == 4
    assert next(item for item in report.criteria if item.id == "cache_replay").score == 1.0


def test_walkthrough_dependency_is_rejected() -> None:
    manifest = EvaluationManifest.load(MANIFEST)
    baseline = load_baseline(BASELINE)
    candidate = load_candidate(CANDIDATE)
    provenance = replace(candidate.provenance, walkthrough_used_for_generation=True)
    report = evaluate(
        manifest, "complex-fixture", baseline, replace(candidate, provenance=provenance)
    )
    assert report.decision is EvaluationDecision.REJECTED
    guard = next(item for item in report.guardrails if item.id == "walkthrough_independence")
    assert not guard.passed


def test_global_parent_scope_disguised_as_window_is_rejected() -> None:
    manifest = EvaluationManifest.load(MANIFEST)
    scope = manifest.scope("complex-fixture")
    strict = replace(scope.bounds.window, require_strict_subset=True)
    strict_scope = replace(scope, bounds=replace(scope.bounds, window=strict))
    manifest = replace(manifest, scopes=(strict_scope, *manifest.scopes[1:]))
    baseline = load_baseline(BASELINE)
    candidate = load_candidate(CANDIDATE)
    report = evaluate(manifest, "complex-fixture", baseline, candidate)
    assert report.decision is EvaluationDecision.REJECTED
    assert not next(item for item in report.guardrails if item.id == "not_global_scope").passed


def test_unresolved_external_id_set_slots_cannot_be_evaluated() -> None:
    manifest = EvaluationManifest.load(MANIFEST)
    baseline = load_baseline(BASELINE)
    candidate = load_candidate(CANDIDATE)
    scope_id = "msdenvers-opening-window"
    scope = manifest.scope(scope_id)
    window = EvaluationWindowSnapshot(
        scope.bounds.window.window_id,
        scope.bounds.window.parent_scope_id,
        "bounded_window",
        baseline.window.node_ids,
        baseline.window.evidence_ids,
        ("boundary-before",),
        ("boundary-after",),
        500,
        13937,
    )
    baseline = replace(baseline, scope_id=scope_id, window=window)
    candidate = replace(candidate, scope_id=scope_id)
    report = evaluate(manifest, scope_id, baseline, candidate)
    assert report.decision is EvaluationDecision.REJECTED
    assert not next(item for item in report.guardrails if item.id == "exact_bounded_window").passed


def test_cli_writes_report_and_browser_contract_without_provider(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    comparison_path = tmp_path / "comparison.json"
    result = main(
        [
            "evaluate",
            "--manifest",
            str(MANIFEST),
            "--scope",
            "complex-fixture",
            "--baseline",
            str(BASELINE),
            "--candidate",
            str(CANDIDATE),
            "--output",
            str(report_path),
            "--comparison-output",
            str(comparison_path),
        ]
    )
    assert result == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    assert report["decision"] == "accepted"
    assert comparison["schema_version"] == 1
    assert comparison["accounting"]["calls"] == 4


def test_fixture_annotations_use_only_known_features() -> None:
    candidate = load_candidate(CANDIDATE)
    invalid = replace(
        candidate,
        annotations=(
            FeatureAnnotation("invented_feature", (), (), (), ("ev:start",)),
            *candidate.annotations,
        ),
    )
    manifest = EvaluationManifest.load(MANIFEST)
    report = evaluate(manifest, "complex-fixture", load_baseline(BASELINE), invalid)
    assert report.decision is EvaluationDecision.REJECTED
