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
LOOPBACK_REASONING = "none"
GLOBAL_SUBMISSION_SLOTS = 6
DERIVED_SEMANTIC_WORKFLOW_VERSION = "story-map-v2-derived-semantic-workflow-v2"
DERIVED_SEMANTIC_FAN_IN = 24

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
    SECTION_SYNTHESIS = "section_synthesis"
    ROLLUP_SYNTHESIS = "rollup_synthesis"


class DerivedSemanticNodeRole(StrEnum):
    ROUTE_REDUCTION = "route_reduction"
    ROUTE_SUMMARY = "route_summary"
    WHOLE_GAME_REDUCTION = "whole_game_reduction"
    FINAL_OVERVIEW = "final_overview"


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
class WorkflowCorridorDescriptor:
    corridor_id: str
    route_owner: str | None
    event_slot_upper_bound: int
    ordinal: int

    def __post_init__(self) -> None:
        _text(self.corridor_id, "corridor ID")
        if self.route_owner is not None:
            _text(self.route_owner, "route owner")
        if type(self.event_slot_upper_bound) is not int or self.event_slot_upper_bound < 1:
            raise ValueError("event-slot upper bound must be a positive integer")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("corridor ordinal must be a non-negative integer")


@dataclass(frozen=True)
class WorkflowRouteMembership:
    route_id: str
    ordered_corridor_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.route_id, "route ID")
        if not self.ordered_corridor_ids:
            raise ValueError("persistent route membership cannot be empty")
        if len(set(self.ordered_corridor_ids)) != len(self.ordered_corridor_ids):
            raise ValueError("persistent route corridor IDs must be unique")
        for corridor_id in self.ordered_corridor_ids:
            _text(corridor_id, "route corridor ID")


def derived_reduce_calls(count: int, *, fan_in: int = DERIVED_SEMANTIC_FAN_IN) -> int:
    """Return the frozen consecutive fan-in reduction-call upper bound."""

    if type(count) is not int or count < 0:
        raise ValueError("derived reduction count must be a non-negative integer")
    if fan_in != DERIVED_SEMANTIC_FAN_IN:
        raise ValueError("derived semantic fan-in must be 24")
    calls = 0
    while count > fan_in:
        count = (count + fan_in - 1) // fan_in
        calls += count
    return calls


@dataclass(frozen=True)
class WorkflowDerivedSemanticPlanDescriptor:
    semantic_plan_identity: str
    story_chunk_plan_identity: str
    authority_identity: AuthorityIdentity
    corridors: tuple[WorkflowCorridorDescriptor, ...]
    route_memberships: tuple[WorkflowRouteMembership, ...]
    section_synthesis_calls: int
    route_reduction_calls: int
    route_summary_calls: int
    whole_game_reduction_calls: int
    final_overview_calls: int
    rollup_synthesis_calls: int
    fan_in: int = DERIVED_SEMANTIC_FAN_IN
    version: str = DERIVED_SEMANTIC_WORKFLOW_VERSION

    def __post_init__(self) -> None:
        _digest(self.semantic_plan_identity, "semantic plan identity")
        _digest(self.story_chunk_plan_identity, "story chunk plan identity")
        if self.version != DERIVED_SEMANTIC_WORKFLOW_VERSION:
            raise ValueError("unsupported derived semantic workflow version")
        if self.fan_in != DERIVED_SEMANTIC_FAN_IN:
            raise ValueError("derived semantic fan-in must be 24")
        if tuple(item.ordinal for item in self.corridors) != tuple(range(len(self.corridors))):
            raise ValueError("corridor ordinals must be consecutive")
        corridor_ids = tuple(item.corridor_id for item in self.corridors)
        if len(set(corridor_ids)) != len(corridor_ids):
            raise ValueError("corridor IDs must be unique")
        route_ids = tuple(item.route_id for item in self.route_memberships)
        if len(set(route_ids)) != len(route_ids):
            raise ValueError("persistent route IDs must be unique")
        by_id = {item.corridor_id: item for item in self.corridors}
        referenced: list[str] = []
        route_upper_bounds: list[int] = []
        for membership in self.route_memberships:
            route_upper_bound = 0
            for corridor_id in membership.ordered_corridor_ids:
                corridor = by_id.get(corridor_id)
                if corridor is None:
                    raise ValueError("route membership references an unknown corridor")
                if corridor.route_owner != membership.route_id:
                    raise ValueError("route membership must match the persistent lane owner")
                referenced.append(corridor_id)
                route_upper_bound += corridor.event_slot_upper_bound
            route_upper_bounds.append(route_upper_bound)
        owned = tuple(item.corridor_id for item in self.corridors if item.route_owner is not None)
        if len(set(referenced)) != len(referenced) or set(referenced) != set(owned):
            raise ValueError("every persistent corridor requires exactly one route membership")
        common = sum(
            item.event_slot_upper_bound for item in self.corridors if item.route_owner is None
        )
        expected = (
            len(self.corridors),
            sum(derived_reduce_calls(value) for value in route_upper_bounds),
            len(self.route_memberships),
            derived_reduce_calls(common + len(self.route_memberships)),
            int(common + len(self.route_memberships) > 0),
        )
        actual = (
            self.section_synthesis_calls,
            self.route_reduction_calls,
            self.route_summary_calls,
            self.whole_game_reduction_calls,
            self.final_overview_calls,
        )
        if actual != expected or self.rollup_synthesis_calls != sum(expected[1:]):
            raise ValueError("derived semantic component ceilings do not match the frozen formula")


@dataclass(frozen=True)
class WorkflowDerivedSemanticJobDescriptor:
    plan_id: str
    semantic_plan_identity: str
    story_chunk_plan_identity: str
    candidate_generation_identity: str
    authority_identity: AuthorityIdentity
    job_id: str
    call_kind: ProviderCallKind
    node_role: DerivedSemanticNodeRole | None
    corridor_id: str | None
    route_owner: str | None
    child_ids: tuple[str, ...]
    child_prose_hashes: tuple[str, ...]
    ordinal: int
    serialized_request_identity: SerializedRequestIdentity
    provider_input_identity: ProviderInputIdentity
    cache_identity: CacheIdentity

    def __post_init__(self) -> None:
        for value, label in (
            (self.plan_id, "plan ID"),
            (self.job_id, "derived job ID"),
        ):
            _text(value, label)
        for value, label in (
            (self.semantic_plan_identity, "semantic plan identity"),
            (self.story_chunk_plan_identity, "story chunk plan identity"),
            (self.candidate_generation_identity, "candidate generation identity"),
        ):
            _digest(value, label)
        if self.call_kind is ProviderCallKind.SECTION_SYNTHESIS:
            if self.node_role is not None or self.corridor_id is None:
                raise ValueError("section synthesis requires a corridor and no rollup role")
        elif self.call_kind is ProviderCallKind.ROLLUP_SYNTHESIS:
            if self.node_role is None:
                raise ValueError("rollup synthesis requires an exact node role")
        else:
            raise ValueError("derived semantic jobs use only the two synthesis call kinds")
        if self.corridor_id is not None:
            _text(self.corridor_id, "derived corridor ID")
        if self.route_owner is not None:
            _text(self.route_owner, "derived route owner")
        if not self.child_ids or len(self.child_ids) != len(self.child_prose_hashes):
            raise ValueError("derived jobs require exact ordered child IDs and prose hashes")
        if len(set(self.child_ids)) != len(self.child_ids):
            raise ValueError("derived child IDs must be unique")
        for child_id in self.child_ids:
            _text(child_id, "derived child ID")
        for prose_hash in self.child_prose_hashes:
            _digest(prose_hash, "derived child prose hash")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("derived job ordinal must be a non-negative integer")
        if self.provider_input_identity.serialized_request_identity != (
            self.serialized_request_identity
        ):
            raise ValueError("derived provider input must bind the serialized request identity")
        if self.provider_input_identity.cache_identity != self.cache_identity:
            raise ValueError("derived cache identity must bind the exact provider input")
        if self.provider_input_identity.mode is ProviderMode.CLOUD and (
            self.provider_input_identity.provider != CLOUD_PROVIDER
            or self.provider_input_identity.model != CLOUD_MODEL
            or self.provider_input_identity.reasoning != CLOUD_REASONING
            or self.provider_input_identity.fast_mode is not CLOUD_FAST_MODE
        ):
            raise ValueError("cloud derived synthesis requires exact Terra, High, fast-off input")


WorkflowExecutableJobDescriptor = WorkflowJobDescriptor | WorkflowDerivedSemanticJobDescriptor


@dataclass(frozen=True)
class WorkflowPlanDescriptor:
    plan_id: str
    authority_identity: AuthorityIdentity
    jobs: tuple[WorkflowJobDescriptor, ...]
    derived_semantic_plan: WorkflowDerivedSemanticPlanDescriptor | None = None

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
        if (
            self.derived_semantic_plan is not None
            and self.derived_semantic_plan.authority_identity != self.authority_identity
        ):
            raise ValueError("derived semantic plan must bind the frozen authority identity")


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
    indeterminate_retry_calls: int = 0
    section_synthesis_calls: int = 0
    route_reduction_calls: int = 0
    route_summary_calls: int = 0
    whole_game_reduction_calls: int = 0
    final_overview_calls: int = 0
    rollup_synthesis_calls: int = 0

    def __post_init__(self) -> None:
        values = (
            self.mapping_calls,
            self.review_calls,
            self.fallback_calls,
            self.input_tokens,
            self.output_tokens,
            self.elapsed_ms,
            self.indeterminate_retry_calls,
            self.section_synthesis_calls,
            self.route_reduction_calls,
            self.route_summary_calls,
            self.whole_game_reduction_calls,
            self.final_overview_calls,
            self.rollup_synthesis_calls,
        )
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("workflow resource ceilings must be finite non-negative integers")
        if self.mapping_calls < 1 or self.input_tokens < 1 or self.elapsed_ms < 1:
            raise ValueError("mapping, input-token, and elapsed ceilings must be positive")
        if self.submission_slots not in {1, GLOBAL_SUBMISSION_SLOTS}:
            raise ValueError("Phase 04 requires one or six independent submission slots")


@dataclass(frozen=True)
class WorkflowPrivacyScope:
    cloud_story_content: bool
    loopback_story_content: bool
    durable_raw_requests: bool = False
    durable_raw_responses: bool = False
    durable_provider_diagnostics: bool = False
    durable_absolute_paths: bool = False

    def __post_init__(self) -> None:
        if not self.cloud_story_content and not self.loopback_story_content:
            raise ValueError("Phase 04 preview must disclose one story transmission boundary")
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
        if self.cloud.mode is ProviderMode.CLOUD and self.cloud != ProviderSettings(
            provider=CLOUD_PROVIDER,
            model=CLOUD_MODEL,
            reasoning=CLOUD_REASONING,
            fast_mode=CLOUD_FAST_MODE,
            mode=ProviderMode.CLOUD,
            adapter_version=self.cloud.adapter_version,
        ):
            raise ValueError("cloud policy requires exact Terra, High, fast-off settings")
        if self.cloud.mode is ProviderMode.LOOPBACK and (
            self.cloud.provider == CLOUD_PROVIDER
            or self.cloud.reasoning not in {None, LOOPBACK_REASONING}
            or self.cloud.fast_mode is not None
        ):
            raise ValueError(
                "provider policy requires exact Terra cloud settings or explicit loopback settings"
            )
        if self.cloud.mode is ProviderMode.LOOPBACK and self.loopback is not None:
            raise ValueError("local-primary policy cannot also configure refusal fallback")
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
        mode: ProviderMode | None = None,
    ) -> ProviderInputIdentity:
        settings = self.cloud if mode is None or self.cloud.mode is mode else self.loopback
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
        expected_cloud = self.policy.cloud.mode is ProviderMode.CLOUD
        expected_loopback = (
            self.policy.cloud.mode is ProviderMode.LOOPBACK
            or self.policy.allow_refusal_fallback
        )
        if (
            self.privacy.cloud_story_content != expected_cloud
            or self.privacy.loopback_story_content != expected_loopback
        ):
            raise ValueError("privacy scope must match the disclosed provider boundaries")
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
    job: WorkflowExecutableJobDescriptor
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
    retry_of_attempt_id: str | None = None
    uses_supplemental_retry_capacity: bool = False

    def __post_init__(self) -> None:
        _text(self.attempt_id, "attempt ID")
        if self.ordinal < 1:
            raise ValueError("attempt ordinals must be positive and never reused")
        if self.retry_of_attempt_id is not None:
            _text(self.retry_of_attempt_id, "approved indeterminate retry attempt ID")
            if self.retry_of_attempt_id == self.attempt_id:
                raise ValueError("an attempt cannot retry itself")
        if type(self.uses_supplemental_retry_capacity) is not bool:
            raise ValueError("supplemental retry capacity marker must be a boolean")
        if self.uses_supplemental_retry_capacity and self.retry_of_attempt_id is None:
            raise ValueError("supplemental retry capacity requires an exact approved attempt")


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
    indeterminate_retries: tuple[IndeterminateRetryStatus, ...] = ()


@dataclass(frozen=True)
class IndeterminateRetryStatus:
    job_id: str
    attempt_id: str
    call_kind: ProviderCallKind
    retry_approval_identity: str | None
    can_approve_retry: bool

    def __post_init__(self) -> None:
        _text(self.job_id, "indeterminate job ID")
        _text(self.attempt_id, "indeterminate attempt ID")
        if self.retry_approval_identity is not None:
            _digest(self.retry_approval_identity, "retry approval identity")
        if self.can_approve_retry != (self.retry_approval_identity is None):
            raise ValueError("retry approval action must match its durable identity")


@dataclass(frozen=True)
class RecoveryReport:
    not_transmitted_jobs: tuple[str, ...]
    indeterminate_jobs: tuple[str, ...]
    finalized_jobs: tuple[str, ...]
    published_jobs: tuple[str, ...]
    policy_resume_jobs: tuple[str, ...] = ()
