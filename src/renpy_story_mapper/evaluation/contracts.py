"""Narrow, serializable contracts shared with the M08 browser comparison surface."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

EVALUATION_SCHEMA_VERSION = 1
BROWSER_COMPARISON_SCHEMA_VERSION = 1


def canonical_json(value: object) -> bytes:
    """Serialize a value for reproducible hashing and checked-in artifacts."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


class EvaluationStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


class EvaluationDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PARTIAL = "partial"


@dataclass(frozen=True)
class EvidenceReference:
    id: str
    subject_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "subject_ids": list(self.subject_ids)}


@dataclass(frozen=True)
class AuthoritySnapshot:
    """All factual identifiers that AI organization is forbidden to change."""

    element_ids: tuple[str, ...]
    edges: tuple[tuple[str, str, str], ...]
    fact_ids: tuple[str, ...]
    evidence: tuple[EvidenceReference, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "element_ids": list(self.element_ids),
            "edges": [
                {"id": edge_id, "source_id": source_id, "target_id": target_id}
                for edge_id, source_id, target_id in self.edges
            ],
            "fact_ids": list(self.fact_ids),
            "evidence": [item.to_dict() for item in self.evidence],
        }

    @property
    def digest(self) -> str:
        return sha256_json(self.to_dict())


@dataclass(frozen=True)
class EvaluationWindowSnapshot:
    """Exact deterministic slice selected from a potentially very large route scope."""

    window_id: str
    parent_scope_id: str
    selection_mode: str
    node_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    boundary_before_node_ids: tuple[str, ...]
    boundary_after_node_ids: tuple[str, ...]
    parent_scope_node_count: int
    parent_scope_evidence_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "window_id": self.window_id,
            "parent_scope_id": self.parent_scope_id,
            "selection_mode": self.selection_mode,
            "node_ids": list(self.node_ids),
            "evidence_ids": list(self.evidence_ids),
            "boundary_before_node_ids": list(self.boundary_before_node_ids),
            "boundary_after_node_ids": list(self.boundary_after_node_ids),
            "parent_scope_node_count": self.parent_scope_node_count,
            "parent_scope_evidence_count": self.parent_scope_evidence_count,
        }


@dataclass(frozen=True)
class TechnicalBaseline:
    scope_id: str
    window: EvaluationWindowSnapshot
    authority: AuthoritySnapshot

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": EVALUATION_SCHEMA_VERSION,
            "scope_id": self.scope_id,
            "window": self.window.to_dict(),
            "authority": self.authority.to_dict(),
        }


@dataclass(frozen=True)
class InterpretationClaim:
    text: str
    evidence_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"text": self.text, "evidence_ids": list(self.evidence_ids)}


@dataclass(frozen=True)
class EvaluationGroup:
    id: str
    title: str
    summary: str
    member_ids: tuple[str, ...]
    claims: tuple[InterpretationClaim, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "member_ids": list(self.member_ids),
            "claims": [claim.to_dict() for claim in self.claims],
        }


@dataclass(frozen=True)
class FeatureAnnotation:
    feature: str
    subject_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    fact_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "feature": self.feature,
            "subject_ids": list(self.subject_ids),
            "edge_ids": list(self.edge_ids),
            "fact_ids": list(self.fact_ids),
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True)
class CoverageSnapshot:
    eligible_ids: tuple[str, ...]
    covered_ids: tuple[str, ...]
    fallback_ids: tuple[str, ...]

    @property
    def ai_ratio(self) -> float:
        return 1.0 if not self.eligible_ids else len(self.covered_ids) / len(self.eligible_ids)

    @property
    def technical_ratio(self) -> float:
        if not self.eligible_ids:
            return 1.0
        return (len(self.covered_ids) + len(self.fallback_ids)) / len(self.eligible_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "eligible_ids": list(self.eligible_ids),
            "covered_ids": list(self.covered_ids),
            "fallback_ids": list(self.fallback_ids),
            "ai_ratio": self.ai_ratio,
            "technical_ratio": self.technical_ratio,
        }


@dataclass(frozen=True)
class AccountingSnapshot:
    attempts: int
    calls: int
    input_tokens: int
    output_tokens: int
    elapsed_ms: int
    cache_hits: int
    cache_misses: int
    resumed_scopes: int
    cancelled_attempts: int
    replay: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "attempts": self.attempts,
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "elapsed_ms": self.elapsed_ms,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "resumed_scopes": self.resumed_scopes,
            "cancelled_attempts": self.cancelled_attempts,
            "replay": self.replay,
        }


@dataclass(frozen=True)
class ProviderProfile:
    invoked: bool
    model: str
    reasoning: str
    fast_mode: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "invoked": self.invoked,
            "model": self.model,
            "reasoning": self.reasoning,
            "fast_mode": self.fast_mode,
        }


@dataclass(frozen=True)
class Provenance:
    artifact_kind: str
    walkthrough_used_for_generation: bool
    walkthrough_text_embedded: bool
    external_story_text_embedded: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_kind": self.artifact_kind,
            "walkthrough_used_for_generation": self.walkthrough_used_for_generation,
            "walkthrough_text_embedded": self.walkthrough_text_embedded,
            "external_story_text_embedded": self.external_story_text_embedded,
        }


@dataclass(frozen=True)
class EvaluationCandidate:
    scope_id: str
    run_id: str
    status: EvaluationStatus
    authority: AuthoritySnapshot
    groups: tuple[EvaluationGroup, ...]
    annotations: tuple[FeatureAnnotation, ...]
    coverage: CoverageSnapshot
    accounting: AccountingSnapshot
    provider: ProviderProfile
    provenance: Provenance

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": EVALUATION_SCHEMA_VERSION,
            "scope_id": self.scope_id,
            "run_id": self.run_id,
            "status": self.status.value,
            "authority": self.authority.to_dict(),
            "groups": [group.to_dict() for group in self.groups],
            "annotations": [item.to_dict() for item in self.annotations],
            "coverage": self.coverage.to_dict(),
            "accounting": self.accounting.to_dict(),
            "provider": self.provider.to_dict(),
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True)
class GuardrailResult:
    id: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class CriterionScore:
    id: str
    label: str
    weight: int
    score: float
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "weight": self.weight,
            "score": round(self.score, 6),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class BrowserComparison:
    """Stable payload for the later browser Technical/AI comparison UI."""

    scope_id: str
    decision: EvaluationDecision
    technical: Mapping[str, object]
    ai: Mapping[str, object]
    criteria: tuple[CriterionScore, ...]
    guardrails: tuple[GuardrailResult, ...]
    coverage: CoverageSnapshot
    accounting: AccountingSnapshot

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": BROWSER_COMPARISON_SCHEMA_VERSION,
            "scope_id": self.scope_id,
            "decision": self.decision.value,
            "technical": dict(self.technical),
            "ai": dict(self.ai),
            "criteria": [item.to_dict() for item in self.criteria],
            "guardrails": [item.to_dict() for item in self.guardrails],
            "coverage": self.coverage.to_dict(),
            "accounting": self.accounting.to_dict(),
        }


@dataclass(frozen=True)
class EvaluationReport:
    manifest_id: str
    scope_id: str
    decision: EvaluationDecision
    score: float
    pass_score: float
    baseline_sha256: str
    candidate_sha256: str
    criteria: tuple[CriterionScore, ...]
    guardrails: tuple[GuardrailResult, ...]
    comparison: BrowserComparison

    def body_dict(self) -> dict[str, object]:
        return {
            "schema_version": EVALUATION_SCHEMA_VERSION,
            "manifest_id": self.manifest_id,
            "scope_id": self.scope_id,
            "decision": self.decision.value,
            "score": round(self.score, 6),
            "pass_score": self.pass_score,
            "baseline_sha256": self.baseline_sha256,
            "candidate_sha256": self.candidate_sha256,
            "criteria": [item.to_dict() for item in self.criteria],
            "guardrails": [item.to_dict() for item in self.guardrails],
            "comparison": self.comparison.to_dict(),
        }

    @property
    def digest(self) -> str:
        return sha256_json(self.body_dict())

    def to_dict(self) -> dict[str, object]:
        value = self.body_dict()
        value["report_sha256"] = self.digest
        return value


def ratio[T: Hashable](
    found: Sequence[T] | set[T],
    expected: Sequence[T] | set[T],
) -> float:
    expected_set = set(expected)
    if not expected_set:
        return 1.0
    return len(set(found) & expected_set) / len(expected_set)
