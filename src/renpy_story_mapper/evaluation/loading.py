"""Strict JSON loading for technical baselines and validated organization candidates."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from renpy_story_mapper.evaluation.contracts import (
    EVALUATION_SCHEMA_VERSION,
    AccountingSnapshot,
    AuthoritySnapshot,
    CoverageSnapshot,
    EvaluationCandidate,
    EvaluationGroup,
    EvaluationStatus,
    EvaluationWindowSnapshot,
    EvidenceReference,
    FeatureAnnotation,
    InterpretationClaim,
    Provenance,
    ProviderProfile,
    TechnicalBaseline,
)


class ArtifactError(ValueError):
    """Raised when an evaluation input violates its strict data contract."""


def load_baseline(path: str | Path) -> TechnicalBaseline:
    return baseline_from_value(_load(path, "technical baseline"))


def load_candidate(path: str | Path) -> EvaluationCandidate:
    return candidate_from_value(_load(path, "evaluation candidate"))


def baseline_from_value(value: object) -> TechnicalBaseline:
    root = _mapping(value, "technical baseline")
    _keys(root, {"schema_version", "scope_id", "window", "authority"}, "technical baseline")
    _version(root["schema_version"])
    return TechnicalBaseline(
        scope_id=_text(root["scope_id"], "scope_id"),
        window=_window(root["window"]),
        authority=_authority(root["authority"]),
    )


def candidate_from_value(value: object) -> EvaluationCandidate:
    root = _mapping(value, "evaluation candidate")
    _keys(
        root,
        {
            "schema_version",
            "scope_id",
            "run_id",
            "status",
            "authority",
            "groups",
            "annotations",
            "coverage",
            "accounting",
            "provider",
            "provenance",
        },
        "evaluation candidate",
    )
    _version(root["schema_version"])
    try:
        status = EvaluationStatus(_text(root["status"], "status"))
    except ValueError as error:
        raise ArtifactError("status is not an allowed evaluation state") from error

    groups = tuple(_group(value) for value in _objects(root["groups"], "groups"))
    annotations = tuple(
        _annotation(value) for value in _objects(root["annotations"], "annotations")
    )
    coverage_value = _mapping(root["coverage"], "coverage")
    _keys(
        coverage_value,
        {"eligible_ids", "covered_ids", "fallback_ids", "ai_ratio", "technical_ratio"},
        "coverage",
    )
    coverage = CoverageSnapshot(
        eligible_ids=_strings(coverage_value["eligible_ids"], "coverage.eligible_ids"),
        covered_ids=_strings(coverage_value["covered_ids"], "coverage.covered_ids"),
        fallback_ids=_strings(coverage_value["fallback_ids"], "coverage.fallback_ids"),
    )
    if abs(_number(coverage_value["ai_ratio"], "coverage.ai_ratio") - coverage.ai_ratio) > 1e-9:
        raise ArtifactError("coverage.ai_ratio does not match the identifier accounting")
    if (
        abs(
            _number(coverage_value["technical_ratio"], "coverage.technical_ratio")
            - coverage.technical_ratio
        )
        > 1e-9
    ):
        raise ArtifactError("coverage.technical_ratio does not match identifier accounting")

    accounting_value = _mapping(root["accounting"], "accounting")
    _keys(
        accounting_value,
        {
            "attempts",
            "calls",
            "input_tokens",
            "output_tokens",
            "elapsed_ms",
            "cache_hits",
            "cache_misses",
            "resumed_scopes",
            "cancelled_attempts",
            "replay",
        },
        "accounting",
    )
    accounting = AccountingSnapshot(
        attempts=_nonnegative(accounting_value["attempts"], "accounting.attempts"),
        calls=_nonnegative(accounting_value["calls"], "accounting.calls"),
        input_tokens=_nonnegative(
            accounting_value["input_tokens"], "accounting.input_tokens"
        ),
        output_tokens=_nonnegative(
            accounting_value["output_tokens"], "accounting.output_tokens"
        ),
        elapsed_ms=_nonnegative(accounting_value["elapsed_ms"], "accounting.elapsed_ms"),
        cache_hits=_nonnegative(accounting_value["cache_hits"], "accounting.cache_hits"),
        cache_misses=_nonnegative(
            accounting_value["cache_misses"], "accounting.cache_misses"
        ),
        resumed_scopes=_nonnegative(
            accounting_value["resumed_scopes"], "accounting.resumed_scopes"
        ),
        cancelled_attempts=_nonnegative(
            accounting_value["cancelled_attempts"], "accounting.cancelled_attempts"
        ),
        replay=_boolean(accounting_value["replay"], "accounting.replay"),
    )
    provider_value = _mapping(root["provider"], "provider")
    _keys(provider_value, {"invoked", "model", "reasoning", "fast_mode"}, "provider")
    provider = ProviderProfile(
        invoked=_boolean(provider_value["invoked"], "provider.invoked"),
        model=_text(provider_value["model"], "provider.model"),
        reasoning=_text(provider_value["reasoning"], "provider.reasoning"),
        fast_mode=_boolean(provider_value["fast_mode"], "provider.fast_mode"),
    )
    provenance_value = _mapping(root["provenance"], "provenance")
    _keys(
        provenance_value,
        {
            "artifact_kind",
            "walkthrough_used_for_generation",
            "walkthrough_text_embedded",
            "external_story_text_embedded",
        },
        "provenance",
    )
    provenance = Provenance(
        artifact_kind=_text(provenance_value["artifact_kind"], "provenance.artifact_kind"),
        walkthrough_used_for_generation=_boolean(
            provenance_value["walkthrough_used_for_generation"],
            "provenance.walkthrough_used_for_generation",
        ),
        walkthrough_text_embedded=_boolean(
            provenance_value["walkthrough_text_embedded"],
            "provenance.walkthrough_text_embedded",
        ),
        external_story_text_embedded=_boolean(
            provenance_value["external_story_text_embedded"],
            "provenance.external_story_text_embedded",
        ),
    )
    return EvaluationCandidate(
        scope_id=_text(root["scope_id"], "scope_id"),
        run_id=_text(root["run_id"], "run_id"),
        status=status,
        authority=_authority(root["authority"]),
        groups=groups,
        annotations=annotations,
        coverage=coverage,
        accounting=accounting,
        provider=provider,
        provenance=provenance,
    )


def _authority(value: object) -> AuthoritySnapshot:
    root = _mapping(value, "authority")
    _keys(root, {"element_ids", "edges", "fact_ids", "evidence"}, "authority")
    elements = _strings(root["element_ids"], "authority.element_ids")
    facts = _strings(root["fact_ids"], "authority.fact_ids")
    edges: list[tuple[str, str, str]] = []
    for value in _objects(root["edges"], "authority.edges"):
        _keys(value, {"id", "source_id", "target_id"}, "authority.edge")
        edges.append(
            (
                _text(value["id"], "authority.edge.id"),
                _text(value["source_id"], "authority.edge.source_id"),
                _text(value["target_id"], "authority.edge.target_id"),
            )
        )
    if len({edge[0] for edge in edges}) != len(edges):
        raise ArtifactError("authority edge IDs must be unique")
    endpoints = {endpoint for _, source, target in edges for endpoint in (source, target)}
    if endpoints - set(elements):
        raise ArtifactError("authority edges reference invented element IDs")
    evidence: list[EvidenceReference] = []
    for value in _objects(root["evidence"], "authority.evidence"):
        _keys(value, {"id", "subject_ids"}, "authority.evidence[]")
        evidence.append(
            EvidenceReference(
                id=_text(value["id"], "authority.evidence.id"),
                subject_ids=_strings(
                    value["subject_ids"], "authority.evidence.subject_ids", empty=False
                ),
            )
        )
    if len({item.id for item in evidence}) != len(evidence):
        raise ArtifactError("authority evidence IDs must be unique")
    subjects = set(elements) | {edge[0] for edge in edges} | set(facts)
    if any(set(item.subject_ids) - subjects for item in evidence):
        raise ArtifactError("authority evidence references invented subject IDs")
    if not elements or not evidence:
        raise ArtifactError("technical authority requires elements and evidence")
    return AuthoritySnapshot(elements, tuple(edges), facts, tuple(evidence))


def _window(value: object) -> EvaluationWindowSnapshot:
    root = _mapping(value, "window")
    _keys(
        root,
        {
            "window_id",
            "parent_scope_id",
            "selection_mode",
            "node_ids",
            "evidence_ids",
            "boundary_before_node_ids",
            "boundary_after_node_ids",
            "parent_scope_node_count",
            "parent_scope_evidence_count",
        },
        "window",
    )
    result = EvaluationWindowSnapshot(
        window_id=_text(root["window_id"], "window.window_id"),
        parent_scope_id=_text(root["parent_scope_id"], "window.parent_scope_id"),
        selection_mode=_text(root["selection_mode"], "window.selection_mode"),
        node_ids=_strings(root["node_ids"], "window.node_ids", empty=False),
        evidence_ids=_strings(root["evidence_ids"], "window.evidence_ids", empty=False),
        boundary_before_node_ids=_strings(
            root["boundary_before_node_ids"], "window.boundary_before_node_ids"
        ),
        boundary_after_node_ids=_strings(
            root["boundary_after_node_ids"], "window.boundary_after_node_ids"
        ),
        parent_scope_node_count=_nonnegative(
            root["parent_scope_node_count"], "window.parent_scope_node_count"
        ),
        parent_scope_evidence_count=_nonnegative(
            root["parent_scope_evidence_count"], "window.parent_scope_evidence_count"
        ),
    )
    if result.selection_mode != "bounded_window":
        raise ArtifactError("technical baseline selection_mode must be bounded_window")
    if result.parent_scope_node_count < len(result.node_ids):
        raise ArtifactError("window node count exceeds its parent scope")
    if result.parent_scope_evidence_count < len(result.evidence_ids):
        raise ArtifactError("window evidence count exceeds its parent scope")
    return result


def _group(value: Mapping[str, object]) -> EvaluationGroup:
    _keys(value, {"id", "title", "summary", "member_ids", "claims"}, "group")
    claims: list[InterpretationClaim] = []
    for claim in _objects(value["claims"], "group.claims"):
        _keys(claim, {"text", "evidence_ids"}, "group.claim")
        claims.append(
            InterpretationClaim(
                text=_text(claim["text"], "group.claim.text"),
                evidence_ids=_strings(
                    claim["evidence_ids"], "group.claim.evidence_ids", empty=False
                ),
            )
        )
    return EvaluationGroup(
        id=_text(value["id"], "group.id"),
        title=_text(value["title"], "group.title"),
        summary=_text(value["summary"], "group.summary"),
        member_ids=_strings(value["member_ids"], "group.member_ids", empty=False),
        claims=tuple(claims),
    )


def _annotation(value: Mapping[str, object]) -> FeatureAnnotation:
    _keys(
        value,
        {"feature", "subject_ids", "edge_ids", "fact_ids", "evidence_ids"},
        "annotation",
    )
    return FeatureAnnotation(
        feature=_text(value["feature"], "annotation.feature"),
        subject_ids=_strings(value["subject_ids"], "annotation.subject_ids"),
        edge_ids=_strings(value["edge_ids"], "annotation.edge_ids"),
        fact_ids=_strings(value["fact_ids"], "annotation.fact_ids"),
        evidence_ids=_strings(value["evidence_ids"], "annotation.evidence_ids", empty=False),
    )


def _load(path: str | Path, name: str) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ArtifactError(f"{name} is not valid JSON") from error


def _version(value: object) -> None:
    if _integer(value, "schema_version") != EVALUATION_SCHEMA_VERSION:
        raise ArtifactError("unsupported evaluation artifact schema version")


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ArtifactError(f"{name} must be an object")
    return cast(Mapping[str, object], value)


def _keys(value: Mapping[str, object], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise ArtifactError(f"{name} fields do not match the strict contract")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactError(f"{name} must be non-empty text")
    return value


def _integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ArtifactError(f"{name} must be an integer")
    return value


def _nonnegative(value: object, name: str) -> int:
    result = _integer(value, name)
    if result < 0:
        raise ArtifactError(f"{name} must not be negative")
    return result


def _number(value: object, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ArtifactError(f"{name} must be a number")
    return float(value)


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ArtifactError(f"{name} must be a boolean")
    return value


def _array(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ArtifactError(f"{name} must be an array")
    return cast(list[object], value)


def _objects(value: object, name: str) -> list[Mapping[str, object]]:
    return [_mapping(item, f"{name}[]") for item in _array(value, name)]


def _strings(value: object, name: str, *, empty: bool = True) -> tuple[str, ...]:
    result = tuple(_text(item, f"{name}[]") for item in _array(value, name))
    if not empty and not result:
        raise ArtifactError(f"{name} must not be empty")
    if len(set(result)) != len(result):
        raise ArtifactError(f"{name} contains duplicates")
    return result
