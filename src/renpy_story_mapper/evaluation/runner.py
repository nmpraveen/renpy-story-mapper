"""Deterministic, provider-free M08 evaluation and browser comparison projection."""

from __future__ import annotations

from collections.abc import Callable

from renpy_story_mapper.evaluation.contracts import (
    BrowserComparison,
    CriterionScore,
    EvaluationCandidate,
    EvaluationDecision,
    EvaluationReport,
    EvaluationStatus,
    GuardrailResult,
    TechnicalBaseline,
    ratio,
    sha256_json,
)
from renpy_story_mapper.evaluation.manifest import (
    FEATURE_IDS,
    EvaluationManifest,
    EvaluationScope,
)

_CRITERIA: tuple[tuple[str, str, int], ...] = (
    ("scene_boundaries", "Scene boundaries", 8),
    ("meaningful_events", "Meaningful events", 8),
    ("concise_titles", "Concise titles", 4),
    ("concise_summaries", "Concise summaries", 4),
    ("character_development", "Character development", 6),
    ("route_meaning", "Route meaning", 8),
    ("temporary_detours", "Temporary detours", 5),
    ("persistent_routes", "Persistent routes", 8),
    ("loops", "Loops", 6),
    ("endings", "Endings", 8),
    ("evidence_support", "Evidence support", 10),
    ("ai_coverage", "AI coverage", 8),
    ("technical_fallback", "Technical fallback", 5),
    ("resource_accounting", "Calls, tokens, and time", 4),
    ("cache_replay", "Cache and zero-call replay", 4),
    ("authority_preservation", "Deterministic authority", 10),
    ("walkthrough_independence", "Walkthrough independence", 4),
)


class EvaluationRejectedError(ValueError):
    """Raised by callers that require an accepted, fail-closed evaluation."""

    def __init__(self, report: EvaluationReport) -> None:
        super().__init__(f"evaluation was not accepted: {report.decision.value}")
        self.report = report


def evaluate(
    manifest: EvaluationManifest,
    scope_id: str,
    baseline: TechnicalBaseline,
    candidate: EvaluationCandidate,
) -> EvaluationReport:
    """Compare a validated organization with deterministic authority without a provider call."""

    scope = manifest.scope(scope_id)
    guardrails = _guardrails(manifest, scope, baseline, candidate)
    guardrail_by_id = {item.id: item.passed for item in guardrails}
    criteria = _score(scope, manifest, candidate, guardrail_by_id)
    total_weight = sum(item.weight for item in criteria)
    score = sum(item.weight * item.score for item in criteria) / total_weight
    guardrails_pass = all(item.passed for item in guardrails)
    if not guardrails_pass:
        decision = EvaluationDecision.REJECTED
    elif candidate.status is not EvaluationStatus.COMPLETE:
        decision = EvaluationDecision.PARTIAL
    elif score >= manifest.rubric.pass_score:
        decision = EvaluationDecision.ACCEPTED
    else:
        decision = EvaluationDecision.REJECTED

    technical = {
        "authority_sha256": baseline.authority.digest,
        "window": baseline.window.to_dict(),
        "element_count": len(baseline.authority.element_ids),
        "edge_count": len(baseline.authority.edges),
        "fact_count": len(baseline.authority.fact_ids),
        "evidence_count": len(baseline.authority.evidence),
    }
    ai = {
        "run_id": candidate.run_id,
        "status": candidate.status.value,
        "provider": candidate.provider.to_dict(),
        "groups": [item.to_dict() for item in candidate.groups],
        "annotations": [item.to_dict() for item in candidate.annotations],
    }
    comparison = BrowserComparison(
        scope_id=scope_id,
        decision=decision,
        technical=technical,
        ai=ai,
        criteria=criteria,
        guardrails=guardrails,
        coverage=candidate.coverage,
        accounting=candidate.accounting,
    )
    return EvaluationReport(
        manifest_id=manifest.id,
        scope_id=scope_id,
        decision=decision,
        score=score,
        pass_score=manifest.rubric.pass_score,
        baseline_sha256=sha256_json(baseline.to_dict()),
        candidate_sha256=sha256_json(candidate.to_dict()),
        criteria=criteria,
        guardrails=guardrails,
        comparison=comparison,
    )


def require_accepted(report: EvaluationReport) -> None:
    if report.decision is not EvaluationDecision.ACCEPTED:
        raise EvaluationRejectedError(report)


def _guardrails(
    manifest: EvaluationManifest,
    scope: EvaluationScope,
    baseline: TechnicalBaseline,
    candidate: EvaluationCandidate,
) -> tuple[GuardrailResult, ...]:
    authority = baseline.authority
    elements = set(authority.element_ids)
    edge_ids = {edge[0] for edge in authority.edges}
    facts = set(authority.fact_ids)
    evidence = {item.id: set(item.subject_ids) for item in authority.evidence}
    members = [member for group in candidate.groups for member in group.member_ids]
    annotations = candidate.annotations
    covered = set(candidate.coverage.covered_ids)
    fallback = set(candidate.coverage.fallback_ids)
    eligible = set(candidate.coverage.eligible_ids)

    known_annotations = all(
        item.feature in FEATURE_IDS
        and set(item.subject_ids) <= elements
        and set(item.edge_ids) <= edge_ids
        and set(item.fact_ids) <= facts
        for item in annotations
    )
    evidence_linked = True
    for group in candidate.groups:
        subjects = set(group.member_ids)
        supported_subjects: set[str] = set()
        if not group.claims:
            evidence_linked = False
        for claim in group.claims:
            if any(evidence_id not in evidence for evidence_id in claim.evidence_ids):
                evidence_linked = False
                continue
            if not any(evidence[evidence_id] & subjects for evidence_id in claim.evidence_ids):
                evidence_linked = False
            for evidence_id in claim.evidence_ids:
                supported_subjects.update(evidence[evidence_id] & subjects)
        if supported_subjects != subjects:
            evidence_linked = False
    for annotation in annotations:
        subjects = (
            set(annotation.subject_ids) | set(annotation.edge_ids) | set(annotation.fact_ids)
        )
        if any(identifier not in evidence for identifier in annotation.evidence_ids):
            evidence_linked = False
            continue
        if not any(
            evidence[identifier] & subjects for identifier in annotation.evidence_ids
        ):
            evidence_linked = False

    positions = {item: index for index, item in enumerate(authority.element_ids)}
    ordered = all(
        [positions[member] for member in group.member_ids]
        == sorted(positions[member] for member in group.member_ids)
        for group in candidate.groups
        if set(group.member_ids) <= elements
    )
    noncrossing = True
    prior = -1
    for group in candidate.groups:
        if not set(group.member_ids) <= elements:
            continue
        group_positions = [positions[member] for member in group.member_ids]
        if group_positions[0] <= prior:
            noncrossing = False
        prior = group_positions[-1]

    coverage_consistent = (
        tuple(candidate.coverage.eligible_ids) == scope.expectations.eligible_ids
        and covered == set(members)
        and not (covered & fallback)
        and (covered | fallback) <= eligible
    )
    nominal_complete = candidate.status is not EvaluationStatus.COMPLETE or (
        covered | fallback == eligible
    )
    accounting = candidate.accounting
    accounting_consistent = (
        accounting.calls <= accounting.attempts
        and accounting.cancelled_attempts <= accounting.attempts
        and (accounting.calls > 0) == candidate.provider.invoked
        and (
            accounting.calls > 0
            or (accounting.input_tokens == 0 and accounting.output_tokens == 0)
        )
        and (
            not accounting.replay
            or (
                accounting.calls == 0
                and accounting.input_tokens == 0
                and accounting.output_tokens == 0
                and accounting.cache_hits > 0
                and not candidate.provider.invoked
            )
        )
        and (
            accounting.cancelled_attempts == 0
            or candidate.status is EvaluationStatus.CANCELLED
            or accounting.resumed_scopes > 0
        )
    )
    profile = candidate.provider
    provider_policy = not profile.invoked or (
        profile.model == manifest.provider_policy.model
        and profile.reasoning == manifest.provider_policy.reasoning
        and profile.fast_mode == manifest.provider_policy.fast_mode
    )
    provenance = candidate.provenance
    budget = scope.budget
    resource_budget = (
        accounting.calls <= budget.max_calls
        and accounting.input_tokens + accounting.output_tokens <= budget.max_tokens
        and accounting.elapsed_ms <= budget.max_elapsed_ms
    )
    window_contract = scope.bounds.window
    window = baseline.window
    authority_evidence_ids = tuple(item.id for item in authority.evidence)
    window_exact = (
        window_contract.resolved
        and window.window_id == window_contract.window_id
        and window.parent_scope_id == window_contract.parent_scope_id
        and window.selection_mode == window_contract.selection_mode
        and window.node_ids == window_contract.expected_node_ids
        and window.evidence_ids == window_contract.expected_evidence_ids
        and window.boundary_before_node_ids == window_contract.boundary_before_node_ids
        and window.boundary_after_node_ids == window_contract.boundary_after_node_ids
        and window.node_ids == authority.element_ids
        and window.evidence_ids == authority_evidence_ids
        and scope.expectations.eligible_ids == window.node_ids
    )
    bounded_window = (
        len(window.node_ids) <= window_contract.max_nodes
        and len(window.evidence_ids) <= window_contract.max_evidence
        and not (set(window.boundary_before_node_ids) & set(window.node_ids))
        and not (set(window.boundary_after_node_ids) & set(window.node_ids))
    )
    strict_subscope = not window_contract.require_strict_subset or (
        window.parent_scope_node_count > len(window.node_ids)
        and window.parent_scope_evidence_count > len(window.evidence_ids)
        and bool(window.boundary_before_node_ids or window.boundary_after_node_ids)
    )
    results = (
        _guardrail(
            "exact_bounded_window",
            window_exact and bounded_window,
            "The baseline exactly matches resolved node/evidence IDs and boundary context.",
        ),
        _guardrail(
            "not_global_scope",
            strict_subscope,
            "Strict windows remain smaller than their parent route scope and retain context.",
        ),
        _guardrail(
            "scope_identity",
            baseline.scope_id == scope.id == candidate.scope_id,
            "Baseline, candidate, and manifest name the same bounded scope.",
        ),
        _guardrail(
            "authority_unchanged",
            authority == candidate.authority,
            "Candidate authority is byte-equivalent to the technical snapshot.",
        ),
        _guardrail(
            "known_ids_edges_facts",
            set(members) <= elements
            and len(members) == len(set(members))
            and len({group.id for group in candidate.groups}) == len(candidate.groups)
            and known_annotations,
            "All organization memberships and annotations use existing authority IDs.",
        ),
        _guardrail(
            "deterministic_order",
            ordered and noncrossing,
            "Organization membership preserves deterministic order without crossings.",
        ),
        _guardrail(
            "evidence_linkage",
            evidence_linked,
            "Every interpretation has existing evidence linked to its claimed subject.",
        ),
        _guardrail(
            "coverage_accounting",
            coverage_consistent,
            "Covered and fallback IDs exactly account for reported organization membership.",
        ),
        _guardrail(
            "honest_completion",
            nominal_complete,
            "Complete status is allowed only when every eligible ID is covered or fallback.",
        ),
        _guardrail(
            "attempt_accounting",
            accounting_consistent,
            "Calls, tokens, cancellation/resume, and replay counters are internally consistent.",
        ),
        _guardrail(
            "resource_budget",
            resource_budget,
            "Calls, total tokens, and elapsed time remain inside the manifest hard limits.",
        ),
        _guardrail(
            "provider_policy",
            provider_policy,
            "Invoked runs record Luna, High reasoning, and fast mode disabled.",
        ),
        _guardrail(
            "walkthrough_independence",
            not provenance.walkthrough_used_for_generation
            and not provenance.walkthrough_text_embedded,
            "Walkthroughs are evaluation references only and never organization inputs.",
        ),
        _guardrail(
            "no_external_text",
            not provenance.external_story_text_embedded,
            "The evaluation artifact embeds no external story text.",
        ),
    )
    return results


def _guardrail(identifier: str, passed: bool, success_detail: str) -> GuardrailResult:
    detail = success_detail if passed else f"REJECTED: {success_detail}"
    return GuardrailResult(identifier, passed, detail)


def _score(
    scope: EvaluationScope,
    manifest: EvaluationManifest,
    candidate: EvaluationCandidate,
    guardrails: dict[str, bool],
) -> tuple[CriterionScore, ...]:
    groups = candidate.groups
    boundaries = {group.member_ids for group in groups}
    expected_boundaries = set(scope.expectations.scene_boundaries)
    members = {member for group in groups for member in group.member_ids}
    annotated: dict[str, set[str]] = {feature: set() for feature in FEATURE_IDS}
    for item in candidate.annotations:
        if item.feature in annotated:
            annotated[item.feature].update(item.subject_ids)
    budget = scope.budget
    accounting = candidate.accounting
    tokens = accounting.input_tokens + accounting.output_tokens

    scores: dict[str, tuple[float, str]] = {
        "scene_boundaries": (
            ratio(boundaries, expected_boundaries),
            f"{len(boundaries & expected_boundaries)}/{len(expected_boundaries)} "
            "expected boundaries",
        ),
        "meaningful_events": (
            ratio(members, scope.expectations.meaningful_event_ids),
            "Expected meaningful deterministic elements are represented by AI events.",
        ),
        "concise_titles": (
            _fraction(groups, lambda group: len(group.title) <= manifest.rubric.max_title_chars),
            f"Titles are non-empty and at most {manifest.rubric.max_title_chars} characters.",
        ),
        "concise_summaries": (
            _fraction(
                groups, lambda group: len(group.summary) <= manifest.rubric.max_summary_chars
            ),
            f"Summaries are non-empty and at most {manifest.rubric.max_summary_chars} characters.",
        ),
        "evidence_support": (
            float(guardrails["evidence_linkage"]),
            "Interpretations are linked to deterministic evidence.",
        ),
        "ai_coverage": (
            candidate.coverage.ai_ratio,
            f"{len(candidate.coverage.covered_ids)}/"
            f"{len(candidate.coverage.eligible_ids)} eligible IDs",
        ),
        "technical_fallback": (
            candidate.coverage.technical_ratio,
            "Every evaluated ID remains available through AI organization or technical fallback.",
        ),
        "resource_accounting": (
            float(
                accounting.calls <= budget.max_calls
                and tokens <= budget.max_tokens
                and accounting.elapsed_ms <= budget.max_elapsed_ms
            ),
            f"calls={accounting.calls}, tokens={tokens}, elapsed_ms={accounting.elapsed_ms}",
        ),
        "cache_replay": (
            float(
                not accounting.replay
                or (
                    accounting.calls == 0
                    and accounting.cache_hits > 0
                    and guardrails["attempt_accounting"]
                )
            ),
            "Replay is zero-call with persisted cache accounting when replay is requested.",
        ),
        "authority_preservation": (
            float(guardrails["authority_unchanged"]),
            "AI organization does not modify deterministic elements, edges, facts, or evidence.",
        ),
        "walkthrough_independence": (
            float(guardrails["walkthrough_independence"]),
            "Walkthrough expectations are comparison-only.",
        ),
    }
    for feature in FEATURE_IDS:
        expected = scope.expectations.feature_subjects[feature]
        scores[feature] = (
            ratio(annotated[feature], expected),
            f"{len(annotated[feature] & set(expected))}/{len(expected)} expected subjects",
        )
    return tuple(
        CriterionScore(identifier, label, weight, scores[identifier][0], scores[identifier][1])
        for identifier, label, weight in _CRITERIA
    )


def _fraction[T](values: tuple[T, ...], predicate: Callable[[T], bool]) -> float:
    if not values:
        return 0.0
    return sum(1 for value in values if predicate(value)) / len(values)
