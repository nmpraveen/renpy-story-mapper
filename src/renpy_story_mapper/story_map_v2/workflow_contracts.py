"""Frozen provider-neutral contracts for the Phase 04 Story Map V2 workflow.

These records deliberately depend only on scalar identities and provider-neutral bytes.  Track A
may construct them, and Track B1 may persist them, without either implementation becoming a
runtime dependency of this module.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum

WORKFLOW_SCHEMA = "story-map-v2-workflow-v1"
WORKFLOW_POLICY_VERSION = "story-map-v2-phase04-policy-v1"
CLOUD_PROVIDER = "codex-cli"
CLOUD_MODEL = "gpt-5.6-terra"
CLOUD_REASONING = "high"
CLOUD_FAST_MODE = False
GLOBAL_SUBMISSION_SLOTS = 6

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


def canonical_workflow_bytes(value: object) -> bytes:
    """Return the stable JSON encoding used by persisted adapter records and identities."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def workflow_digest(value: object) -> str:
    """Hash a workflow dataclass/scalar through its canonical persistence encoding."""

    return hashlib.sha256(canonical_workflow_bytes(value)).hexdigest()


def _text(value: str, label: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{label} must be a non-empty trimmed string")


def _digest(value: str, label: str) -> None:
    if _HEX_64.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


class ProviderMode(StrEnum):
    CLOUD = "cloud"
    LOOPBACK = "loopback"


class ProviderCallKind(StrEnum):
    MAPPING = "mapping"
    REPLACEMENT_REVIEW = "replacement_review"
    REFUSAL_FALLBACK = "refusal_fallback"


class WorkflowFailure(StrEnum):
    CONTENT_REFUSAL = "content_refusal"
    NOT_TRANSMITTED = "not_transmitted"
    INDETERMINATE = "indeterminate"
    INVALID_RESPONSE = "invalid_response"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    IDENTITY_MISMATCH = "identity_mismatch"
    RESOURCE_LIMIT = "resource_limit"
    CANCELLED = "cancelled"


class TransmissionDisposition(StrEnum):
    NOT_TRANSMITTED = "not_transmitted"
    TRANSMITTED = "transmitted"
    INDETERMINATE = "indeterminate"


class JobResolution(StrEnum):
    ACCEPTED = "accepted"
    STRUCTURAL_FALLBACK = "structural_fallback"
    RESUMABLE = "resumable"
    INDETERMINATE = "indeterminate"
    CANCELLED = "cancelled"


class AttemptStage(StrEnum):
    RESERVED = "reserved"
    SUBMITTING = "submitting"
    RETURNED = "returned"
    VALIDATED = "validated"
    FINALIZED = "finalized"
    PUBLISHED = "published"
    NOT_TRANSMITTED = "not_transmitted"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class AuthorityIdentity:
    value: str

    def __post_init__(self) -> None:
        _text(self.value, "authority identity")


@dataclass(frozen=True)
class SerializedRequestIdentity:
    value: str
    sha256: str
    byte_count: int

    def __post_init__(self) -> None:
        _text(self.value, "serialized request identity")
        _digest(self.sha256, "serialized request hash")
        if self.byte_count < 1:
            raise ValueError("serialized request byte count must be positive")

    def verify(self, request: bytes) -> None:
        if len(request) != self.byte_count or hashlib.sha256(request).hexdigest() != self.sha256:
            raise ValueError("materialized request bytes do not match their frozen identity")


@dataclass(frozen=True)
class CacheIdentity:
    value: str

    def __post_init__(self) -> None:
        _digest(self.value, "cache identity")


@dataclass(frozen=True)
class ProviderInputIdentity:
    """Every field that may change the exact provider input or interpretation contract."""

    serialized_request_identity: SerializedRequestIdentity
    prompt_version: str
    schema_version: str
    adapter_version: str
    provider: str
    model: str
    reasoning: str | None
    fast_mode: bool | None
    mode: ProviderMode

    def __post_init__(self) -> None:
        for value, label in (
            (self.prompt_version, "prompt version"),
            (self.schema_version, "schema version"),
            (self.adapter_version, "adapter version"),
            (self.provider, "provider"),
            (self.model, "model"),
        ):
            _text(value, label)
        if self.reasoning is not None:
            _text(self.reasoning, "reasoning")
        if type(self.mode) is not ProviderMode:
            raise ValueError("provider mode must use the frozen ProviderMode contract")

    @property
    def cache_identity(self) -> CacheIdentity:
        return CacheIdentity(workflow_digest(asdict(self)))


@dataclass(frozen=True)
class WorkflowJobDescriptor:
    plan_id: str
    scope_id: str
    job_id: str
    chunk_id: str
    authority_identity: AuthorityIdentity
    serialized_request_identity: SerializedRequestIdentity
    cache_identity: CacheIdentity
    critical: bool = False

    def __post_init__(self) -> None:
        for value, label in (
            (self.plan_id, "plan ID"),
            (self.scope_id, "scope ID"),
            (self.job_id, "job ID"),
            (self.chunk_id, "chunk ID"),
        ):
            _text(value, label)
        if type(self.critical) is not bool:
            raise ValueError("critical must be a boolean")


@dataclass(frozen=True)
class WorkflowPlanDescriptor:
    plan_id: str
    authority_identity: AuthorityIdentity
    jobs: tuple[WorkflowJobDescriptor, ...]

    def __post_init__(self) -> None:
        _text(self.plan_id, "plan ID")
        if not self.jobs:
            raise ValueError("a workflow plan requires at least one job")
        if len({job.job_id for job in self.jobs}) != len(self.jobs):
            raise ValueError("workflow job IDs must be unique")
        if len({job.chunk_id for job in self.jobs}) != len(self.jobs):
            raise ValueError("workflow chunk IDs must be unique")
        for job in self.jobs:
            if job.plan_id != self.plan_id:
                raise ValueError("workflow jobs must bind the frozen plan ID")
            if job.authority_identity != self.authority_identity:
                raise ValueError("workflow jobs must bind the frozen authority identity")


@dataclass(frozen=True)
class ProviderSettings:
    provider: str
    model: str
    reasoning: str | None
    fast_mode: bool | None
    mode: ProviderMode
    adapter_version: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.provider, "provider"),
            (self.model, "model"),
            (self.adapter_version, "adapter version"),
        ):
            _text(value, label)
        if self.reasoning is not None:
            _text(self.reasoning, "reasoning")


@dataclass(frozen=True)
class WorkflowResourceCeilings:
    mapping_calls: int
    review_calls: int
    fallback_calls: int
    input_tokens: int
    output_tokens: int
    elapsed_ms: int
    submission_slots: int = GLOBAL_SUBMISSION_SLOTS

    def __post_init__(self) -> None:
        values = (
            self.mapping_calls,
            self.review_calls,
            self.fallback_calls,
            self.input_tokens,
            self.output_tokens,
            self.elapsed_ms,
        )
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("workflow resource ceilings must be finite non-negative integers")
        if self.mapping_calls < 1 or self.input_tokens < 1 or self.elapsed_ms < 1:
            raise ValueError("mapping, input-token, and elapsed ceilings must be positive")
        if self.submission_slots != GLOBAL_SUBMISSION_SLOTS:
            raise ValueError("Phase 04 requires exactly six independent submission slots")


@dataclass(frozen=True)
class WorkflowPrivacyScope:
    cloud_story_content: bool
    loopback_story_content: bool
    durable_raw_requests: bool = False
    durable_raw_responses: bool = False
    durable_provider_diagnostics: bool = False
    durable_absolute_paths: bool = False

    def __post_init__(self) -> None:
        if self.cloud_story_content is not True:
            raise ValueError("Phase 04 preview must disclose cloud story transmission")
        if any(
            (
                self.durable_raw_requests,
                self.durable_raw_responses,
                self.durable_provider_diagnostics,
                self.durable_absolute_paths,
            )
        ):
            raise ValueError("Phase 04 privacy scope cannot retain sensitive provider material")


@dataclass(frozen=True)
class WorkflowPolicy:
    prompt_version: str
    schema_version: str
    cloud: ProviderSettings
    loopback: ProviderSettings | None
    allow_refusal_fallback: bool
    policy_version: str = WORKFLOW_POLICY_VERSION

    def __post_init__(self) -> None:
        _text(self.prompt_version, "prompt version")
        _text(self.schema_version, "schema version")
        if self.cloud != ProviderSettings(
            provider=CLOUD_PROVIDER,
            model=CLOUD_MODEL,
            reasoning=CLOUD_REASONING,
            fast_mode=CLOUD_FAST_MODE,
            mode=ProviderMode.CLOUD,
            adapter_version=self.cloud.adapter_version,
        ):
            raise ValueError("cloud policy requires exact Terra, High, fast-off settings")
        if self.allow_refusal_fallback != (self.loopback is not None):
            raise ValueError("loopback settings must exactly match disclosed fallback permission")
        if self.loopback is not None and self.loopback.mode is not ProviderMode.LOOPBACK:
            raise ValueError("fallback settings must identify a loopback provider")
        if self.policy_version != WORKFLOW_POLICY_VERSION:
            raise ValueError("unsupported Phase 04 provider policy")

    def input_identity(
        self,
        request: SerializedRequestIdentity,
        *,
        mode: ProviderMode = ProviderMode.CLOUD,
    ) -> ProviderInputIdentity:
        settings = self.cloud if mode is ProviderMode.CLOUD else self.loopback
        if settings is None:
            raise ValueError("the frozen preview does not disclose a loopback provider")
        return ProviderInputIdentity(
            serialized_request_identity=request,
            prompt_version=self.prompt_version,
            schema_version=self.schema_version,
            adapter_version=settings.adapter_version,
            provider=settings.provider,
            model=settings.model,
            reasoning=settings.reasoning,
            fast_mode=settings.fast_mode,
            mode=settings.mode,
        )


@dataclass(frozen=True)
class WorkflowPreview:
    run_id: str
    plan: WorkflowPlanDescriptor
    policy: WorkflowPolicy
    ceilings: WorkflowResourceCeilings
    privacy: WorkflowPrivacyScope
    cache_hit_job_ids: tuple[str, ...]
    loopback_cache_hit_job_ids: tuple[str, ...] = ()
    schema: str = WORKFLOW_SCHEMA

    def __post_init__(self) -> None:
        _text(self.run_id, "run ID")
        if self.schema != WORKFLOW_SCHEMA:
            raise ValueError("unsupported workflow preview schema")
        if self.privacy.loopback_story_content != self.policy.allow_refusal_fallback:
            raise ValueError("privacy scope must match disclosed loopback fallback permission")
        known_jobs = {job.job_id for job in self.plan.jobs}
        if len(set(self.cache_hit_job_ids)) != len(self.cache_hit_job_ids):
            raise ValueError("cache-hit job IDs must be unique")
        if not set(self.cache_hit_job_ids).issubset(known_jobs):
            raise ValueError("cache-hit jobs must belong to the frozen plan")
        if len(set(self.loopback_cache_hit_job_ids)) != len(
            self.loopback_cache_hit_job_ids
        ):
            raise ValueError("loopback cache-hit job IDs must be unique")
        if not set(self.loopback_cache_hit_job_ids).issubset(known_jobs):
            raise ValueError("loopback cache-hit jobs must belong to the frozen plan")
        if self.loopback_cache_hit_job_ids and not self.policy.allow_refusal_fallback:
            raise ValueError("loopback cache hits require a disclosed loopback provider")
        if set(self.cache_hit_job_ids) & set(self.loopback_cache_hit_job_ids):
            raise ValueError("cloud and loopback cache hits must be disjoint")

    @property
    def identity(self) -> str:
        # Run routing is intentionally excluded from approval/cache semantics.
        value = asdict(self)
        del value["run_id"]
        return workflow_digest(value)


@dataclass(frozen=True)
class WorkflowApproval:
    preview_identity: str
    plan_id: str
    authority_identity: AuthorityIdentity

    def __post_init__(self) -> None:
        _digest(self.preview_identity, "preview identity")
        _text(self.plan_id, "plan ID")

    @property
    def identity(self) -> str:
        return workflow_digest(asdict(self))


@dataclass(frozen=True)
class JobRetryApproval:
    preview_identity: str
    job_id: str
    indeterminate_attempt_id: str

    def __post_init__(self) -> None:
        _digest(self.preview_identity, "preview identity")
        _text(self.job_id, "job ID")
        _text(self.indeterminate_attempt_id, "indeterminate attempt ID")

    @property
    def identity(self) -> str:
        return workflow_digest(asdict(self))


@dataclass(frozen=True)
class JobClaim:
    run_id: str
    execution_id: str
    claim_id: str
    worker_id: str
    job: WorkflowJobDescriptor
    resume_call_kind: ProviderCallKind | None = None

    def __post_init__(self) -> None:
        if (
            self.resume_call_kind is not None
            and type(self.resume_call_kind) is not ProviderCallKind
        ):
            raise ValueError("resume call kind must use the frozen provider-call contract")


@dataclass(frozen=True)
class AttemptReservation:
    attempt_id: str
    ordinal: int
    call_kind: ProviderCallKind
    provider_input: ProviderInputIdentity

    def __post_init__(self) -> None:
        _text(self.attempt_id, "attempt ID")
        if self.ordinal < 1:
            raise ValueError("attempt ordinals must be positive and never reused")


@dataclass(frozen=True)
class AttemptAccounting:
    calls: int
    input_tokens: int
    output_tokens: int
    elapsed_ms: int

    def __post_init__(self) -> None:
        if type(self.calls) is not int or self.calls not in {0, 1}:
            raise ValueError("one attempt may account for zero or one provider call")
        if any(
            type(value) is not int or value < 0
            for value in (self.input_tokens, self.output_tokens, self.elapsed_ms)
        ):
            raise ValueError("attempt accounting must use finite non-negative integers")

    @classmethod
    def zero(cls) -> AttemptAccounting:
        return cls(calls=0, input_tokens=0, output_tokens=0, elapsed_ms=0)


def validate_transmission_accounting(
    transmission: TransmissionDisposition,
    accounting: AttemptAccounting,
) -> None:
    """Reject provider-boundary accounting that contradicts transmission certainty."""

    if (
        transmission is TransmissionDisposition.NOT_TRANSMITTED
        and accounting.calls != 0
    ) or (
        transmission is TransmissionDisposition.TRANSMITTED and accounting.calls != 1
    ):
        raise ValueError("transmission disposition and accounting conflict")


@dataclass(frozen=True)
class WorkflowAccounting:
    calls: int
    input_tokens: int
    output_tokens: int
    elapsed_ms: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (self.calls, self.input_tokens, self.output_tokens, self.elapsed_ms)
        ):
            raise ValueError("workflow accounting must use finite non-negative integers")

    @classmethod
    def zero(cls) -> WorkflowAccounting:
        return cls(calls=0, input_tokens=0, output_tokens=0, elapsed_ms=0)


@dataclass(frozen=True)
class ProviderCallResult:
    payload: bytes
    accounting: AttemptAccounting
    resolved_provider: str
    resolved_model: str
    resolved_reasoning: str | None
    resolved_fast_mode: bool | None
    transmission: TransmissionDisposition = TransmissionDisposition.TRANSMITTED

    def __post_init__(self) -> None:
        if not self.payload:
            raise ValueError("a successful provider result requires response bytes")
        if self.accounting.calls != 1:
            raise ValueError("a successful provider result accounts for exactly one call")
        if self.transmission is not TransmissionDisposition.TRANSMITTED:
            raise ValueError("a successful provider result must be definitely transmitted")


@dataclass(frozen=True)
class ValidatedWorkflowResult:
    result_identity: str
    normalized_payload: bytes
    flagged_for_review: bool = False

    def __post_init__(self) -> None:
        _digest(self.result_identity, "validated result identity")
        if not self.normalized_payload:
            raise ValueError("validated workflow prose cannot be empty")
        if hashlib.sha256(self.normalized_payload).hexdigest() != self.result_identity:
            raise ValueError("validated result identity must bind normalized result bytes")


@dataclass(frozen=True)
class AttemptCompletion:
    stage: AttemptStage
    transmission: TransmissionDisposition
    accounting: AttemptAccounting
    response_identity: str | None
    failure: WorkflowFailure | None
    sanitized_reason: str | None

    def __post_init__(self) -> None:
        validate_transmission_accounting(self.transmission, self.accounting)
        if self.response_identity is not None:
            _digest(self.response_identity, "response identity")
        if self.sanitized_reason is not None:
            _text(self.sanitized_reason, "sanitized reason")


@dataclass(frozen=True)
class WorkflowStatus:
    run_id: str
    preview_identity: str
    approved: bool
    cancelled: bool
    pending_jobs: int
    active_jobs: int
    accepted_jobs: int
    structural_fallback_jobs: int
    resumable_jobs: int
    indeterminate_jobs: int
    accounting: WorkflowAccounting


@dataclass(frozen=True)
class RecoveryReport:
    not_transmitted_jobs: tuple[str, ...]
    indeterminate_jobs: tuple[str, ...]
    finalized_jobs: tuple[str, ...]
    published_jobs: tuple[str, ...]
    policy_resume_jobs: tuple[str, ...] = ()
