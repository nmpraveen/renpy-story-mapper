"""Versioned, provider-independent contracts for the optional M13 narrative layer.

The records in this module separate deterministic logical work from provider transport.  A
logical job cannot contain a provider or batch identity.  Cache identity adds those runtime
bindings only after an exact logical input revision exists.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from enum import StrEnum

from renpy_story_mapper.storage import canonical_json

M13_CONTRACT_VERSION = "m13-narrative-contract-v1"
M13_PARTITION_VERSION = "m13-summary-partition-v1"
M13_CACHE_VERSION = "m13-narrative-cache-v1"

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class LogicalJobKind(StrEnum):
    """Logical artifact kinds; transport packing is deliberately absent."""

    SCENE = "scene"
    AUTHORITY_FACT = "authority_fact"
    SUMMARY_SEGMENT = "summary_segment"
    CHAPTER = "chapter"
    ROUTE = "route"
    ENDING = "ending"
    PLOT = "plot"
    CHARACTER = "character"
    WEAK_BOUNDARY = "weak_boundary"


class LogicalJobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    REFUSED = "refused"
    CANCELLED = "cancelled"
    STALE = "stale"


class ClaimClass(StrEnum):
    FACTUAL = "factual"
    INTERPRETIVE = "interpretive"
    REVIEW_SUGGESTION = "review_suggestion"


class ClaimPolarity(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class SupportKind(StrEnum):
    DIRECT_EVIDENCE = "direct_evidence"
    CHILD_CLAIMS = "child_claims"


class ArtifactPublication(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    REJECTED = "rejected"


class PrivacyMode(StrEnum):
    FACT_ONLY = "fact_only"
    STORY_TEXT = "story_text"


class AuthoritySystem(StrEnum):
    M10 = "m10"
    M11 = "m11"
    M12 = "m12"


class AttemptOutcome(StrEnum):
    ACCEPTED = "accepted"
    PARTIAL = "partial"
    MALFORMED = "malformed"
    TRANSIENT_FAILURE = "transient_failure"
    PROVIDER_REFUSAL = "provider_refusal"
    CONTENT_REFUSAL = "content_refusal"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    HARD_LIMIT = "hard_limit"


class CostConfidence(StrEnum):
    RELIABLE = "reliable"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


def canonical_hash(value: object) -> str:
    """Return the canonical SHA-256 digest used by all M13 identities."""

    return hashlib.sha256(canonical_json(value)).hexdigest()


def _require_text(value: str, label: str, *, maximum: int | None = None) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{label} must be a non-empty trimmed string")
    if maximum is not None and len(value) > maximum:
        raise ValueError(f"{label} must be at most {maximum} characters")


def _require_unique_text(values: tuple[str, ...], label: str) -> None:
    for value in values:
        _require_text(value, label)
    if len(values) != len(set(values)):
        raise ValueError(f"{label} values must be unique")


@dataclass(frozen=True)
class StructuralContext:
    """Exact M11/M12 context that owns a logical artifact.

    Optional fields stay distinct because a lane, temporary arm, call occurrence, loop, and
    temporal anchor carry different chronology semantics.
    """

    chapter_id: str | None = None
    lane_id: str | None = None
    route_id: str | None = None
    temporary_container_id: str | None = None
    temporary_arm_id: str | None = None
    occurrence_id: str | None = None
    call_site_id: str | None = None
    loop_id: str | None = None
    temporal_anchor: str | None = None
    structural_fingerprint: str | None = None

    def __post_init__(self) -> None:
        for name, value in self.to_dict().items():
            if value is not None:
                if not isinstance(value, str):
                    raise TypeError(f"{name} must be a string or None")
                _require_text(value, name)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "chapter_id": self.chapter_id,
            "lane_id": self.lane_id,
            "route_id": self.route_id,
            "temporary_container_id": self.temporary_container_id,
            "temporary_arm_id": self.temporary_arm_id,
            "occurrence_id": self.occurrence_id,
            "call_site_id": self.call_site_id,
            "loop_id": self.loop_id,
            "temporal_anchor": self.temporal_anchor,
            "structural_fingerprint": self.structural_fingerprint,
        }


@dataclass(frozen=True)
class AuthorityBinding:
    """Exact immutable authority revision consumed by one normalized M13 input."""

    source_generation: str
    source_archive_hash: str
    canonical_schema: str
    canonical_hash: str
    scene_schema: str
    scene_hash: str
    correction_hash: str
    m12_result_identities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "source_generation",
            "source_archive_hash",
            "canonical_schema",
            "canonical_hash",
            "scene_schema",
            "scene_hash",
            "correction_hash",
        ):
            _require_text(str(getattr(self, name)), name)
        _require_unique_text(self.m12_result_identities, "M12 result identity")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "source_generation": self.source_generation,
            "source_archive_hash": self.source_archive_hash,
            "canonical_schema": self.canonical_schema,
            "canonical_hash": self.canonical_hash,
            "scene_schema": self.scene_schema,
            "scene_hash": self.scene_hash,
            "correction_hash": self.correction_hash,
            "m12_result_identities": list(sorted(self.m12_result_identities)),
        }

    @property
    def identity(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class InputRevision:
    """Exact deterministic input revision, independent of provider transport."""

    authority: AuthorityBinding
    projection_schema: str
    normalized_input_hash: str

    def __post_init__(self) -> None:
        _require_text(self.projection_schema, "projection schema")
        _require_text(self.normalized_input_hash, "normalized input hash")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "authority": self.authority.to_dict(),
            "projection_schema": self.projection_schema,
            "normalized_input_hash": self.normalized_input_hash,
        }

    @property
    def identity(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class LogicalJobSpec:
    """Provider-independent logical identity for one independently durable job."""

    kind: LogicalJobKind
    owner_id: str
    context: StructuralContext
    ordered_child_artifact_ids: tuple[str, ...] = ()
    locale: str = "und"
    perspective: str = "default"
    contract_version: str = M13_CONTRACT_VERSION
    partition_version: str = M13_PARTITION_VERSION

    def __post_init__(self) -> None:
        for value, label in (
            (self.owner_id, "logical job owner"),
            (self.locale, "locale"),
            (self.perspective, "perspective"),
            (self.contract_version, "contract version"),
            (self.partition_version, "partition version"),
        ):
            _require_text(value, label)
        _require_unique_text(self.ordered_child_artifact_ids, "child artifact ID")
        hierarchy_kinds = {
            LogicalJobKind.SUMMARY_SEGMENT,
            LogicalJobKind.CHAPTER,
            LogicalJobKind.ROUTE,
            LogicalJobKind.ENDING,
            LogicalJobKind.PLOT,
            LogicalJobKind.CHARACTER,
        }
        if self.kind in hierarchy_kinds and not self.ordered_child_artifact_ids:
            raise ValueError(f"{self.kind.value} jobs require ordered child artifact IDs")
        if self.kind not in hierarchy_kinds and self.ordered_child_artifact_ids:
            raise ValueError(f"{self.kind.value} jobs cannot own child artifact IDs")

    def identity_dict(self) -> dict[str, JsonValue]:
        return {
            "contract_version": self.contract_version,
            "partition_version": self.partition_version,
            "kind": self.kind.value,
            "owner_id": self.owner_id,
            "context": self.context.to_dict(),
            "ordered_child_artifact_ids": list(self.ordered_child_artifact_ids),
            "locale": self.locale,
            "perspective": self.perspective,
        }

    @property
    def job_id(self) -> str:
        return f"m13_job_{canonical_hash(self.identity_dict())[:24]}"


@dataclass(frozen=True)
class LogicalJob:
    spec: LogicalJobSpec
    input_revision: InputRevision
    state: LogicalJobState = LogicalJobState.QUEUED

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "job_id": self.spec.job_id,
            "spec": self.spec.identity_dict(),
            "input_revision": self.input_revision.to_dict(),
            "input_revision_id": self.input_revision.identity,
            "state": self.state.value,
        }


@dataclass(frozen=True, order=True)
class AuthorityReference:
    """Bounded direct reference to one exact, owned authority record."""

    authority: AuthoritySystem
    record_kind: str
    record_id: str
    owner_id: str

    def __post_init__(self) -> None:
        _require_text(self.record_kind, "authority record kind")
        _require_text(self.record_id, "authority record ID")
        _require_text(self.owner_id, "authority owner ID")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "authority": self.authority.value,
            "record_kind": self.record_kind,
            "record_id": self.record_id,
            "owner_id": self.owner_id,
        }


@dataclass(frozen=True)
class ProviderSettings:
    """Canonical non-secret runtime settings included in cache identity."""

    values: tuple[tuple[str, JsonScalar], ...] = ()

    def __post_init__(self) -> None:
        keys = tuple(key for key, _value in self.values)
        _require_unique_text(keys, "provider setting key")
        forbidden = {
            "api_key",
            "authorization",
            "credential",
            "password",
            "secret",
            "token",
        }
        for key, value in self.values:
            if key.casefold() in forbidden:
                raise ValueError("provider settings identity cannot contain credentials")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("provider setting floats must be finite")

    def to_dict(self) -> dict[str, JsonValue]:
        return {key: value for key, value in sorted(self.values)}


@dataclass(frozen=True)
class ProviderIdentity:
    """Requested and actually resolved runtime provider identity."""

    provider: str
    adapter: str
    adapter_version: str
    requested_model: str
    resolved_model: str
    settings: ProviderSettings

    def __post_init__(self) -> None:
        for value, label in (
            (self.provider, "provider"),
            (self.adapter, "provider adapter"),
            (self.adapter_version, "provider adapter version"),
            (self.requested_model, "requested model"),
            (self.resolved_model, "resolved model"),
        ):
            _require_text(value, label)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "provider": self.provider,
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
            "requested_model": self.requested_model,
            "resolved_model": self.resolved_model,
            "settings": self.settings.to_dict(),
        }


@dataclass(frozen=True)
class CacheIdentity:
    """Exact accepted-artifact cache key; never a transport-batch key."""

    logical_job_id: str
    input_revision_id: str
    normalized_input_hash: str
    prompt_template_version: str
    response_schema_version: str
    provider: ProviderIdentity
    cache_version: str = M13_CACHE_VERSION

    def __post_init__(self) -> None:
        for value, label in (
            (self.logical_job_id, "logical job ID"),
            (self.input_revision_id, "input revision ID"),
            (self.normalized_input_hash, "normalized input hash"),
            (self.prompt_template_version, "prompt template version"),
            (self.response_schema_version, "response schema version"),
            (self.cache_version, "cache version"),
        ):
            _require_text(value, label)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "cache_version": self.cache_version,
            "logical_job_id": self.logical_job_id,
            "input_revision_id": self.input_revision_id,
            "normalized_input_hash": self.normalized_input_hash,
            "prompt_template_version": self.prompt_template_version,
            "response_schema_version": self.response_schema_version,
            "provider": self.provider.to_dict(),
        }

    @property
    def key(self) -> str:
        return f"m13_cache_{canonical_hash(self.to_dict())}"


@dataclass(frozen=True)
class ClaimSupport:
    kind: SupportKind
    direct_evidence: tuple[AuthorityReference, ...] = ()
    child_claim_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.direct_evidence) != len(set(self.direct_evidence)):
            raise ValueError("direct evidence references must be unique")
        _require_unique_text(self.child_claim_ids, "child claim ID")
        if self.kind is SupportKind.DIRECT_EVIDENCE:
            if not self.direct_evidence or self.child_claim_ids:
                raise ValueError("direct support requires only direct evidence references")
        elif not self.child_claim_ids or self.direct_evidence:
            raise ValueError("ancestor support requires only child claim IDs")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "kind": self.kind.value,
            "direct_evidence": [item.to_dict() for item in self.direct_evidence],
            "child_claim_ids": list(self.child_claim_ids),
        }


@dataclass(frozen=True)
class ClaimSemantics:
    """Normalized provider assertion fields used only for contextual review checks."""

    subject: str
    predicate: str
    polarity: ClaimPolarity
    normalized_value: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.subject, "claim subject"),
            (self.predicate, "claim predicate"),
            (self.normalized_value, "claim normalized value"),
        ):
            _require_text(value, label, maximum=320)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "polarity": self.polarity.value,
            "normalized_value": self.normalized_value,
        }


@dataclass(frozen=True)
class NarrativeClaim:
    logical_job_id: str
    job_kind: LogicalJobKind
    ordinal: int
    claim_class: ClaimClass
    text: str
    support: ClaimSupport
    semantics: ClaimSemantics | None = None

    def __post_init__(self) -> None:
        _require_text(self.logical_job_id, "claim logical job ID")
        _require_text(self.text, "claim text", maximum=1_000)
        if self.ordinal < 0:
            raise ValueError("claim ordinal must be non-negative")
        direct_kinds = {
            LogicalJobKind.SCENE,
            LogicalJobKind.AUTHORITY_FACT,
            LogicalJobKind.WEAK_BOUNDARY,
        }
        if self.job_kind in direct_kinds:
            if self.support.kind is not SupportKind.DIRECT_EVIDENCE:
                raise ValueError(f"{self.job_kind.value} claims require direct evidence")
        elif self.support.kind is not SupportKind.CHILD_CLAIMS:
            raise ValueError(f"{self.job_kind.value} claims require child claim references")

    @property
    def claim_id(self) -> str:
        identity = {
            "contract_version": M13_CONTRACT_VERSION,
            "logical_job_id": self.logical_job_id,
            "ordinal": self.ordinal,
        }
        return f"m13_claim_{canonical_hash(identity)[:24]}"

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "claim_id": self.claim_id,
            "logical_job_id": self.logical_job_id,
            "job_kind": self.job_kind.value,
            "ordinal": self.ordinal,
            "claim_class": self.claim_class.value,
            "text": self.text,
            "support": self.support.to_dict(),
            "semantics": None if self.semantics is None else self.semantics.to_dict(),
        }


@dataclass(frozen=True)
class Coverage:
    """Deterministic child and claim coverage for complete or partial artifacts."""

    expected_child_ids: tuple[str, ...] = ()
    available_child_ids: tuple[str, ...] = ()
    missing_child_ids: tuple[str, ...] = ()
    valid_claim_count: int = 0
    invalid_claim_count: int = 0

    def __post_init__(self) -> None:
        for values, label in (
            (self.expected_child_ids, "expected child ID"),
            (self.available_child_ids, "available child ID"),
            (self.missing_child_ids, "missing child ID"),
        ):
            _require_unique_text(values, label)
        expected = set(self.expected_child_ids)
        available = set(self.available_child_ids)
        missing = set(self.missing_child_ids)
        if available & missing:
            raise ValueError("available and missing child IDs cannot overlap")
        if available | missing != expected:
            raise ValueError("available and missing child IDs must partition expected children")
        if self.valid_claim_count < 0 or self.invalid_claim_count < 0:
            raise ValueError("claim coverage counts must be non-negative")

    @property
    def child_coverage_basis_points(self) -> int:
        if not self.expected_child_ids:
            return 10_000
        return len(self.available_child_ids) * 10_000 // len(self.expected_child_ids)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "expected_child_ids": list(self.expected_child_ids),
            "available_child_ids": list(self.available_child_ids),
            "missing_child_ids": list(self.missing_child_ids),
            "child_coverage_basis_points": self.child_coverage_basis_points,
            "valid_claim_count": self.valid_claim_count,
            "invalid_claim_count": self.invalid_claim_count,
        }


@dataclass(frozen=True)
class NarrativeArtifact:
    logical_job_id: str
    input_revision_id: str
    job_kind: LogicalJobKind
    publication: ArtifactPublication
    title: str
    summary: str
    claims: tuple[NarrativeClaim, ...]
    coverage: Coverage
    warnings: tuple[str, ...] = ()
    used_deterministic_title: bool = False

    def __post_init__(self) -> None:
        _require_text(self.logical_job_id, "artifact logical job ID")
        _require_text(self.input_revision_id, "artifact input revision ID")
        _require_unique_text(self.warnings, "artifact warning")
        if self.title:
            _require_text(self.title, "artifact title", maximum=200)
        if self.summary:
            _require_text(self.summary, "artifact summary", maximum=4_000)
        claim_ids = tuple(claim.claim_id for claim in self.claims)
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("artifact claim IDs must be unique")
        if any(
            claim.logical_job_id != self.logical_job_id or claim.job_kind is not self.job_kind
            for claim in self.claims
        ):
            raise ValueError("artifact claims must be owned by the artifact logical job")
        if self.coverage.valid_claim_count != len(self.claims):
            raise ValueError("coverage valid-claim count must equal persisted claims")
        if self.publication is ArtifactPublication.COMPLETE:
            if self.coverage.missing_child_ids or self.coverage.invalid_claim_count:
                raise ValueError(
                    "complete artifacts cannot have missing children or invalid claims"
                )
            if not self.title or not self.summary:
                raise ValueError("complete artifacts require a title and summary")
        elif self.publication is ArtifactPublication.PARTIAL:
            if not self.warnings:
                raise ValueError("partial artifacts require a coverage warning")
            if not self.title or not self.summary:
                raise ValueError("partial artifacts require a usable title and summary")
        elif self.claims:
            raise ValueError("rejected artifacts cannot publish claims")

    def normalized_dict(self) -> dict[str, JsonValue]:
        return {
            "contract_version": M13_CONTRACT_VERSION,
            "logical_job_id": self.logical_job_id,
            "input_revision_id": self.input_revision_id,
            "job_kind": self.job_kind.value,
            "publication": self.publication.value,
            "title": self.title,
            "summary": self.summary,
            "claims": [claim.to_dict() for claim in self.claims],
            "coverage": self.coverage.to_dict(),
            "warnings": list(self.warnings),
            "used_deterministic_title": self.used_deterministic_title,
        }

    @property
    def artifact_id(self) -> str:
        return f"m13_artifact_{canonical_hash(self.normalized_dict())}"


@dataclass(frozen=True)
class BudgetLimits:
    max_provider_calls: int
    max_input_tokens: int
    max_output_tokens: int
    max_total_tokens: int
    timeout_seconds: int
    max_concurrency: int
    max_cost_micros: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "max_provider_calls",
            "max_input_tokens",
            "max_output_tokens",
            "max_total_tokens",
            "timeout_seconds",
            "max_concurrency",
        ):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_cost_micros is not None and self.max_cost_micros < 0:
            raise ValueError("max_cost_micros must be non-negative when supplied")
        if self.max_total_tokens < max(self.max_input_tokens, self.max_output_tokens):
            raise ValueError("total token limit cannot be below an input or output token limit")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "max_provider_calls": self.max_provider_calls,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_total_tokens": self.max_total_tokens,
            "timeout_seconds": self.timeout_seconds,
            "max_concurrency": self.max_concurrency,
            "max_cost_micros": self.max_cost_micros,
        }


@dataclass(frozen=True)
class RunEstimate:
    logical_job_count: int
    provider_call_count: int
    input_tokens: int
    output_tokens: int
    estimated_cost_micros: int | None
    cost_confidence: CostConfidence

    def __post_init__(self) -> None:
        for name in (
            "logical_job_count",
            "provider_call_count",
            "input_tokens",
            "output_tokens",
        ):
            if int(getattr(self, name)) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.logical_job_count and not self.provider_call_count:
            raise ValueError("a non-empty cloud run requires an estimated provider call")
        if self.cost_confidence is CostConfidence.UNAVAILABLE:
            if self.estimated_cost_micros is not None:
                raise ValueError("unavailable cost must not carry an estimate")
        elif self.estimated_cost_micros is None or self.estimated_cost_micros < 0:
            raise ValueError("known cost confidence requires a non-negative estimate")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "logical_job_count": self.logical_job_count,
            "provider_call_count": self.provider_call_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_micros": self.estimated_cost_micros,
            "cost_confidence": self.cost_confidence.value,
        }


@dataclass(frozen=True)
class ConsentManifest:
    """One exact, scope-bound cloud consent; false by default means no transmission."""

    run_id: str
    provider: ProviderIdentity
    selected_scope_ids: tuple[str, ...]
    privacy_mode: PrivacyMode
    includes_m12_material: bool
    estimate: RunEstimate
    limits: BudgetLimits
    consent_granted: bool = False

    def __post_init__(self) -> None:
        _require_text(self.run_id, "run ID")
        _require_unique_text(self.selected_scope_ids, "selected scope ID")
        if not self.selected_scope_ids:
            raise ValueError("consent requires a non-empty selected scope")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "contract_version": M13_CONTRACT_VERSION,
            "run_id": self.run_id,
            "provider": self.provider.to_dict(),
            "selected_scope_ids": list(self.selected_scope_ids),
            "privacy_mode": self.privacy_mode.value,
            "includes_m12_material": self.includes_m12_material,
            "estimate": self.estimate.to_dict(),
            "limits": self.limits.to_dict(),
            "consent_granted": self.consent_granted,
        }

    @property
    def manifest_id(self) -> str:
        return f"m13_consent_{canonical_hash(self.to_dict())}"


@dataclass(frozen=True)
class AttemptMetrics:
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_ms: int = 0
    cost_micros: int | None = None

    def __post_init__(self) -> None:
        for name in ("input_tokens", "output_tokens", "elapsed_ms"):
            if int(getattr(self, name)) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.cost_micros is not None and self.cost_micros < 0:
            raise ValueError("cost_micros cannot be negative")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "elapsed_ms": self.elapsed_ms,
            "cost_micros": self.cost_micros,
        }


@dataclass(frozen=True)
class JobAttempt:
    logical_job_id: str
    attempt_number: int
    outcome: AttemptOutcome
    provider: ProviderIdentity
    metrics: AttemptMetrics
    batch_id: str | None = None
    sanitized_error_code: str | None = None
    validated_claim_count: int = 0
    invalid_claim_count: int = 0

    def __post_init__(self) -> None:
        _require_text(self.logical_job_id, "attempt logical job ID")
        if self.attempt_number < 1:
            raise ValueError("attempt number must be positive")
        if self.batch_id is not None:
            _require_text(self.batch_id, "transport batch ID")
        if self.sanitized_error_code is not None:
            _require_text(self.sanitized_error_code, "sanitized error code", maximum=80)
        if self.validated_claim_count < 0 or self.invalid_claim_count < 0:
            raise ValueError("attempt claim counts cannot be negative")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "logical_job_id": self.logical_job_id,
            "attempt_number": self.attempt_number,
            "outcome": self.outcome.value,
            "provider": self.provider.to_dict(),
            "metrics": self.metrics.to_dict(),
            "batch_id": self.batch_id,
            "sanitized_error_code": self.sanitized_error_code,
            "validated_claim_count": self.validated_claim_count,
            "invalid_claim_count": self.invalid_claim_count,
        }


@dataclass(frozen=True)
class TransportBatchPlan:
    """Operational packing identity, intentionally separate from every logical job ID."""

    transport_version: str
    provider: ProviderIdentity
    items: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        _require_text(self.transport_version, "transport version")
        job_ids = tuple(job_id for job_id, _revision_id in self.items)
        _require_unique_text(job_ids, "batched logical job ID")
        for _job_id, revision_id in self.items:
            _require_text(revision_id, "batched input revision ID")
        if not self.items:
            raise ValueError("transport batches require at least one logical item")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "transport_version": self.transport_version,
            "provider": self.provider.to_dict(),
            "items": [
                {"logical_job_id": job_id, "input_revision_id": revision_id}
                for job_id, revision_id in self.items
            ],
        }

    @property
    def batch_id(self) -> str:
        return f"m13_batch_{canonical_hash(self.to_dict())[:24]}"
