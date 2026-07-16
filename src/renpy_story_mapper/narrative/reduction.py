"""Bounded execution primitives for M13 segment and hierarchy reductions.

Only immediate validated child artifacts enter a hierarchy request.  Their claim IDs are replaced
with prompt-local C handles, while the durable result stores only direct child-claim edges.  This
keeps prompts bounded and provenance growth linear instead of flattening transitive M10 evidence.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from renpy_story_mapper.narrative.authority import NarrativeAuthority, load_narrative_authority
from renpy_story_mapper.narrative.contracts import (
    CacheIdentity,
    ClaimClass,
    ClaimContextScope,
    ClaimPolarity,
    ClaimSemantics,
    ClaimSupport,
    ConsentManifest,
    InputRevision,
    JsonValue,
    LogicalJob,
    LogicalJobKind,
    NarrativeClaim,
    ProviderIdentity,
    StructuralContext,
    SupportKind,
    canonical_hash,
)
from renpy_story_mapper.narrative.evidence import PromptHandleTable
from renpy_story_mapper.narrative.hierarchy import (
    MAX_MANDATORY_CLAIMS_PER_HIERARCHY_JOB,
    ChronologyPolicy,
    HierarchyJobDescriptor,
    HierarchyPathContext,
    M12AuthorityLeaf,
)
from renpy_story_mapper.narrative.persistence import LookupState, RecordKind
from renpy_story_mapper.narrative.preparation import ProviderPricing
from renpy_story_mapper.narrative.provider import (
    PROMPT_TEMPLATE_VERSION,
    RESPONSE_SCHEMA_VERSION,
    NarrativeProvider,
)
from renpy_story_mapper.narrative.scheduler import (
    NarrativeScheduler,
    ScheduledSceneJob,
    SchedulerPolicy,
    SchedulerRunResult,
    SchedulerUsage,
    ValidatedLogicalOutput,
)
from renpy_story_mapper.narrative.validation import ValidationContext, validate_and_salvage
from renpy_story_mapper.narrative.workflow import M13SchedulerPersistenceSink
from renpy_story_mapper.project import Project
from renpy_story_mapper.storage import canonical_json

HIERARCHY_PROVIDER_INPUT_SCHEMA = "m13-hierarchy-provider-input-v3"
MAX_DIRECT_CHILD_CLAIMS = 1_024
MAX_PROPAGATED_CLAIMS_PER_ARTIFACT = 32
MAX_PERSISTED_CLAIM_CONTEXTS = 256
CHARS_PER_ESTIMATED_TOKEN = 4
DEFAULT_HIERARCHY_OUTPUT_TOKENS = 1_000

CancelledCallback = Callable[[], bool]


@dataclass(frozen=True)
class RuntimeNarrativeArtifact:
    """One current validated artifact plus only its immediate hierarchy metadata."""

    artifact_id: str
    logical_job_id: str
    payload: Mapping[str, object]
    claim_ids: tuple[str, ...]
    estimated_tokens: int
    path: HierarchyPathContext
    chronology_index: int
    temporal_anchor: str
    mandatory_claim_ids: tuple[str, ...] = ()
    chapter_id: str | None = None
    chapter_ordinal: int | None = None
    occurrence_id: str | None = None
    call_site_id: str | None = None
    loop_id: str | None = None
    expected_leaf_count: int = 1
    covered_leaf_count: int = 1
    contains_structured_alternatives: bool = False
    structure_manifest_id: str | None = None

    def __post_init__(self) -> None:
        if not self.artifact_id or not self.logical_job_id:
            raise ValueError("runtime artifacts require stable artifact and job identities")
        if len(self.claim_ids) != len(set(self.claim_ids)):
            raise ValueError("runtime artifacts cannot repeat immediate claims")
        if len(self.mandatory_claim_ids) != len(set(self.mandatory_claim_ids)):
            raise ValueError("runtime artifacts cannot repeat mandatory claims")
        if not set(self.mandatory_claim_ids) <= set(self.claim_ids):
            raise ValueError("runtime mandatory claims must be immediate claims")
        if self.estimated_tokens < 1:
            raise ValueError("runtime artifact token estimate must be positive")
        if not 0 <= self.covered_leaf_count <= self.expected_leaf_count:
            raise ValueError("runtime artifact leaf coverage is invalid")

    @property
    def title(self) -> str:
        return _required_text(self.payload, "title")

    @property
    def summary(self) -> str:
        return _required_text(self.payload, "summary")

    def claims(self) -> dict[str, Mapping[str, object]]:
        raw = self.payload.get("claims")
        if not isinstance(raw, list):
            raise ValueError("runtime artifact claims are malformed")
        result: dict[str, Mapping[str, object]] = {}
        for value in raw:
            if not isinstance(value, Mapping):
                raise ValueError("runtime artifact claim is malformed")
            claim_id = value.get("claim_id")
            if not isinstance(claim_id, str) or claim_id in result:
                raise ValueError("runtime artifact claim identity is malformed")
            result[claim_id] = dict(value)
        if not set(self.claim_ids) <= set(result):
            raise ValueError("runtime artifact immediate claim index changed")
        return {claim_id: result[claim_id] for claim_id in self.claim_ids}


@dataclass(frozen=True)
class PreparedHierarchyJob:
    """One bounded hierarchy job and its deterministic validation context."""

    descriptor: HierarchyJobDescriptor
    job: LogicalJob
    handles: PromptHandleTable
    payload: dict[str, JsonValue]
    deterministic_title: str
    deterministic_summary: str
    scope_id: str
    ordinal: int
    estimated_input_tokens: int
    estimated_output_tokens: int = DEFAULT_HIERARCHY_OUTPUT_TOKENS
    authority_claims: tuple[NarrativeClaim, ...] = ()
    claim_contexts: tuple[tuple[str, StructuralContext], ...] = ()
    claim_context_scopes: tuple[tuple[str, ClaimContextScope], ...] = ()

    def __post_init__(self) -> None:
        if self.job.spec != self.descriptor.spec:
            raise ValueError("prepared hierarchy job changed its deterministic specification")
        if self.handles.scope_id != self.job.spec.job_id:
            raise ValueError("hierarchy handles belong to another logical job")
        if canonical_hash(self.payload) != self.job.input_revision.normalized_input_hash:
            raise ValueError("hierarchy payload differs from its normalized input revision")
        if self.ordinal < 0 or self.estimated_input_tokens < 1:
            raise ValueError("hierarchy scheduling estimates are invalid")
        authority_ids = tuple(claim.claim_id for claim in self.authority_claims)
        if len(authority_ids) != len(set(authority_ids)):
            raise ValueError("prepared hierarchy authority claims must be unique")
        required_allowlist = {
            *self.descriptor.authority_leaf_claim_ids,
            *self.descriptor.mandatory_child_claim_ids,
        }
        if not set(authority_ids) <= required_allowlist:
            raise ValueError("prepared authority claims exceed the descriptor allowlist")
        contextual_ids = tuple(claim_id for claim_id, _context in self.claim_contexts)
        if len(contextual_ids) != len(set(contextual_ids)):
            raise ValueError("prepared hierarchy claim contexts must be unique")
        if not set(contextual_ids) <= set(self.descriptor.child_claim_ids):
            raise ValueError("prepared claim contexts exceed immediate artifact claims")
        scoped_ids = tuple(claim_id for claim_id, _scope in self.claim_context_scopes)
        if len(scoped_ids) != len(set(scoped_ids)):
            raise ValueError("prepared hierarchy claim context scopes must be unique")
        if not set(scoped_ids) <= set(self.descriptor.child_claim_ids):
            raise ValueError("prepared claim context scopes exceed immediate artifact claims")

    def scheduled(
        self,
        provider: ProviderIdentity,
        pricing: ProviderPricing | None = None,
    ) -> ScheduledSceneJob:
        revision = self.job.input_revision
        cache = CacheIdentity(
            logical_job_id=self.job.spec.job_id,
            input_revision_id=revision.identity,
            normalized_input_hash=revision.normalized_input_hash,
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            response_schema_version=RESPONSE_SCHEMA_VERSION,
            provider=provider,
        )
        cost = None
        if pricing is not None:
            cost = math.ceil(
                (
                    self.estimated_input_tokens
                    * pricing.input_micros_per_million_tokens
                    + self.estimated_output_tokens
                    * pricing.output_micros_per_million_tokens
                )
                / 1_000_000
            )
        return ScheduledSceneJob(
            logical_job=self.job,
            cache_identity=cache,
            scope_id=self.scope_id,
            provider_input=self.payload,
            ordinal=self.ordinal,
            estimated_input_tokens=self.estimated_input_tokens,
            estimated_output_tokens=self.estimated_output_tokens,
            estimated_cost_micros=cost,
        )


@dataclass(frozen=True)
class HierarchyExecutionResult:
    scheduler: SchedulerRunResult
    artifacts: tuple[RuntimeNarrativeArtifact, ...]


def prepare_hierarchy_job(
    descriptor: HierarchyJobDescriptor,
    children: Mapping[str, RuntimeNarrativeArtifact],
    authority: NarrativeAuthority,
    *,
    scope_id: str,
    ordinal: int,
    deterministic_title: str,
    deterministic_summary: str,
    authority_claims: Mapping[str, NarrativeClaim] | None = None,
) -> PreparedHierarchyJob:
    """Project immediate children and C handles into one bounded provider input."""

    if not deterministic_title.strip() or not deterministic_summary.strip():
        raise ValueError("hierarchy deterministic fallbacks must be non-empty")
    direct_authority_claims = {} if authority_claims is None else authority_claims
    available = tuple(
        child_id
        for child_id in descriptor.child_artifact_ids
        if child_id in children
    )
    if available != descriptor.available_child_artifact_ids:
        raise ValueError("runtime hierarchy children differ from deterministic availability")
    claim_records: dict[str, Mapping[str, object]] = {}
    claim_contexts: dict[str, StructuralContext] = {}
    claim_context_scopes: dict[str, ClaimContextScope] = {}
    for child_id in available:
        available_child = children[child_id]
        child_contexts = _runtime_claim_contexts(available_child)
        for claim_id, artifact_claim in available_child.claims().items():
            if claim_id in claim_records:
                raise ValueError("two child artifacts expose the same immediate claim")
            claim_records[claim_id] = artifact_claim
            claim_contexts[claim_id] = child_contexts[claim_id]
            claim_context_scopes[claim_id] = ClaimContextScope(
                _required_text(artifact_claim, "context_scope")
            )
    required_claims: dict[str, NarrativeClaim] = {}
    for claim_id in descriptor.mandatory_child_claim_ids:
        required_claims[claim_id] = _runtime_narrative_claim(claim_records[claim_id])
    for claim_id, authority_claim in direct_authority_claims.items():
        if claim_id in claim_records:
            raise ValueError("authority and artifact claims cannot overlap")
        claim_records[claim_id] = authority_claim.to_dict()
        required_claims[claim_id] = authority_claim
    if set(claim_records) != set(descriptor.allowed_support_claim_ids):
        raise ValueError("hierarchy claim records differ from the descriptor allowlist")
    if len(claim_records) > MAX_DIRECT_CHILD_CLAIMS:
        raise ValueError("hierarchy job exceeds the direct child-claim bound")

    handles = PromptHandleTable.build(
        scope_id=descriptor.job_id,
        allowed_owner_ids=(),
        child_claim_ids=descriptor.allowed_support_claim_ids,
    )
    handle_by_claim = {
        item.claim_id: item.handle for item in handles.child_claim_handles
    }
    child_records: list[JsonValue] = []
    for entry in descriptor.section_entries:
        record: dict[str, JsonValue] = {
            "artifact_id": entry.artifact_id,
            "job_kind": entry.job_kind.value,
            "path": cast(JsonValue, entry.path.to_dict()),
            "chapter_id": entry.chapter_id,
            "chapter_ordinal": entry.chapter_ordinal,
            "chronology_index": entry.chronology_index,
            "temporal_anchor": entry.temporal_anchor,
            "available": entry.available,
            "contains_structured_alternatives": entry.contains_structured_alternatives,
            "structure_manifest_id": entry.structure_manifest_id,
        }
        runtime_child = children.get(entry.artifact_id)
        if runtime_child is not None:
            record["title"] = runtime_child.title
            record["summary"] = runtime_child.summary
            record["claims"] = [
                _prompt_claim(
                    handle_by_claim[claim_id],
                    runtime_child.claims()[claim_id],
                    claim_contexts[claim_id],
                )
                for claim_id in runtime_child.claim_ids
            ]
        else:
            record["missing"] = True
        child_records.append(record)
    exact_authority_claims = [
        _prompt_claim(handle_by_claim[claim_id], claim.to_dict())
        for claim_id, claim in sorted(required_claims.items())
    ]
    payload: dict[str, JsonValue] = {
        "schema": HIERARCHY_PROVIDER_INPUT_SCHEMA,
        "job_kind": descriptor.spec.kind.value,
        "logical_job_id": descriptor.job_id,
        "owner_handle": descriptor.spec.owner_id,
        "locale": descriptor.spec.locale,
        "perspective": descriptor.spec.perspective,
        "chronology_policy": descriptor.chronology_policy.value,
        "path": cast(JsonValue, descriptor.path.to_dict()),
        "structure_manifest_id": descriptor.structure_manifest_id,
        "child_artifacts": child_records,
        "exact_m12_authority_claims": exact_authority_claims,
        "missing_child_artifact_ids": list(descriptor.missing_child_artifact_ids),
        "coverage_percentage": descriptor.coverage_percentage,
        "response_contract": {
            "support_class": "child_claim_handles_only",
            "interpretation_label_required": True,
            "route_chronology_must_remain_separate": True,
            "m12_status_and_prerequisite_wording_must_not_change": True,
        },
    }
    revision = InputRevision(
        authority.binding,
        HIERARCHY_PROVIDER_INPUT_SCHEMA,
        canonical_hash(payload),
    )
    encoded = canonical_json(payload)
    return PreparedHierarchyJob(
        descriptor=descriptor,
        job=LogicalJob(descriptor.spec, revision),
        handles=handles,
        payload=payload,
        deterministic_title=deterministic_title,
        deterministic_summary=deterministic_summary,
        scope_id=scope_id,
        ordinal=ordinal,
        estimated_input_tokens=max(1, math.ceil(len(encoded) / CHARS_PER_ESTIMATED_TOKEN)),
        authority_claims=tuple(
            required_claims[claim_id] for claim_id in sorted(required_claims)
        ),
        claim_contexts=tuple(
            (claim_id, claim_contexts[claim_id]) for claim_id in sorted(claim_contexts)
        ),
        claim_context_scopes=tuple(
            (claim_id, claim_context_scopes[claim_id])
            for claim_id in sorted(claim_context_scopes)
        ),
    )


def execute_hierarchy_jobs(
    project: Project,
    provider: NarrativeProvider,
    prepared: Sequence[PreparedHierarchyJob],
    consent: ConsentManifest,
    *,
    policy: SchedulerPolicy,
    initial_usage: SchedulerUsage | None = None,
    pricing: ProviderPricing | None = None,
    cancelled: CancelledCallback = lambda: False,
) -> HierarchyExecutionResult:
    """Execute one dependency-ready hierarchy level with independent durable commits."""

    if not prepared:
        raise ValueError("a hierarchy execution level requires at least one logical job")
    current = load_narrative_authority(project, include_m12=True)
    scheduled = tuple(item.scheduled(consent.provider, pricing) for item in prepared)
    sink = M13SchedulerPersistenceSink(
        project.m13_persistence(),
        scheduled,
        authority_binding=current.binding.to_dict(),
        cancelled=cancelled,
    )
    contexts = {
        item.job.spec.job_id: ValidationContext(
            job=item.job.spec,
            input_revision_id=item.job.input_revision.identity,
            handles=item.handles,
            deterministic_title=item.deterministic_title,
            deterministic_summary=item.deterministic_summary,
            expected_child_ids=item.descriptor.child_artifact_ids,
            available_child_ids=item.descriptor.available_child_artifact_ids,
            authority_claims=item.authority_claims,
            claim_contexts=item.claim_contexts,
            claim_context_scopes=item.claim_context_scopes,
        )
        for item in prepared
    }
    prepared_by_job = {item.job.spec.job_id: item for item in prepared}

    def validate(
        job: ScheduledSceneJob,
        raw: Mapping[str, JsonValue],
    ) -> ValidatedLogicalOutput:
        result = validate_and_salvage(raw, contexts[job.logical_job_id])
        if result.artifact is None:
            raise ValueError(result.rejected_reason or "hierarchy output is not publishable")
        artifact = result.artifact
        item = prepared_by_job[job.logical_job_id]
        payload = artifact.normalized_dict()
        validation_context = contexts[job.logical_job_id]
        payload["claim_contexts"] = cast(
            JsonValue,
            [
                {
                    "claim_id": claim.claim_id,
                    "context": (
                        validation_context.context_for_claim(claim) or job.logical_job.spec.context
                    ).to_dict(),
                }
                for claim in artifact.claims
            ],
        )
        payload["hierarchy"] = cast(
            JsonValue,
            {
                "chronology_policy": item.descriptor.chronology_policy.value,
                "path": item.descriptor.path.to_dict(),
                "structure_manifest_id": item.descriptor.structure_manifest_id,
                "section_entries": [
                    entry.to_dict() for entry in item.descriptor.section_entries
                ],
            },
        )
        payload["m12_authority"] = cast(
            JsonValue,
            [record.to_dict() for record in item.descriptor.m12_authority],
        )
        return ValidatedLogicalOutput(
            logical_job_id=job.logical_job_id,
            artifact_id=f"m13_artifact_{canonical_hash(payload)}",
            publication=artifact.publication,
            payload=payload,
            validated_claim_count=len(artifact.claims),
            invalid_claim_count=artifact.coverage.invalid_claim_count,
        )

    run = NarrativeScheduler(provider, sink, policy).run(
        scheduled,
        consent,
        validate,
        cancelled=cancelled,
        initial_usage=initial_usage,
    )
    artifacts: list[RuntimeNarrativeArtifact] = []
    by_job = {item.job.spec.job_id: item for item in prepared}
    for record in run.jobs:
        if record.artifact_id is None:
            continue
        item = by_job[record.logical_job_id]
        lookup = project.m13_persistence().lookup(
            RecordKind.ARTIFACT,
            record.artifact_id,
            authority_binding=current.binding.to_dict(),
        )
        if lookup.state is not LookupState.HIT or lookup.payload is None:
            raise ValueError("published hierarchy artifact is not durably readable")
        artifacts.append(_runtime_from_prepared(item, record.artifact_id, lookup.payload))
    return HierarchyExecutionResult(run, tuple(artifacts))


def persist_m12_authority_leaf(
    project: Project,
    authority: NarrativeAuthority,
    leaf: M12AuthorityLeaf,
) -> None:
    """Persist exact deterministic M12 leaf claims without a provider call."""

    current = load_narrative_authority(project, include_m12=True)
    if current.binding != authority.binding:
        raise ValueError("M12 authority changed before deterministic leaf publication")
    store = project.m13_persistence()
    for claim in leaf.claims:
        store.put_claim(
            claim.claim_id,
            claim.to_dict(),
            authority_binding=current.binding.to_dict(),
        )
    store.put_job(
        leaf.job.job_id,
        {
            "job_id": leaf.job.job_id,
            "spec": leaf.job.identity_dict(),
            "input_revision_id": canonical_hash(
                {"m12_authority": leaf.authority.to_dict()}
            ),
            "state": "succeeded",
            "status": "succeeded",
            "claim_ids": list(leaf.claim_ids),
        },
        authority_binding=current.binding.to_dict(),
    )


def _runtime_from_prepared(
    prepared: PreparedHierarchyJob,
    artifact_id: str,
    payload: Mapping[str, object],
) -> RuntimeNarrativeArtifact:
    claims = payload.get("claims")
    if not isinstance(claims, list):
        raise ValueError("published hierarchy artifact claims are malformed")
    claim_records = _mappings(claims)
    authority_ids = {claim.claim_id for claim in prepared.authority_claims}
    mandatory: list[str] = []
    optional: list[str] = []
    represented_authority: set[str] = set()
    for item in claim_records:
        claim_id = _required_text(item, "claim_id")
        support = item.get("support")
        children = (
            support.get("child_claim_ids", [])
            if isinstance(support, Mapping)
            else []
        )
        cited = {
            child_id
            for child_id in children
            if isinstance(child_id, str) and child_id in authority_ids
        }
        if cited and item.get("claim_class") == "factual":
            mandatory.append(claim_id)
            represented_authority.update(cited)
        else:
            optional.append(claim_id)
    if represented_authority != authority_ids:
        raise ValueError("published hierarchy artifact lost exact M12 authority claims")
    if len(mandatory) > MAX_MANDATORY_CLAIMS_PER_HIERARCHY_JOB:
        raise ValueError("exact M12 authority claims exceed propagation capacity")
    optional_capacity = max(0, MAX_PROPAGATED_CLAIMS_PER_ARTIFACT - len(mandatory))
    claim_ids = tuple(
        (*mandatory, *optional[:optional_capacity])
    )
    descriptor = prepared.descriptor
    return RuntimeNarrativeArtifact(
        artifact_id=artifact_id,
        logical_job_id=prepared.job.spec.job_id,
        payload=dict(payload),
        claim_ids=claim_ids,
        estimated_tokens=max(1, math.ceil(len(canonical_json(dict(payload))) / 4)),
        path=descriptor.path,
        chronology_index=descriptor.chronology_index,
        temporal_anchor=prepared.job.spec.context.temporal_anchor or descriptor.spec.owner_id,
        mandatory_claim_ids=tuple(mandatory),
        chapter_id=prepared.job.spec.context.chapter_id,
        chapter_ordinal=descriptor.chapter_ordinal,
        occurrence_id=prepared.job.spec.context.occurrence_id,
        call_site_id=prepared.job.spec.context.call_site_id,
        loop_id=prepared.job.spec.context.loop_id,
        expected_leaf_count=descriptor.expected_leaf_count,
        covered_leaf_count=descriptor.covered_leaf_count,
        contains_structured_alternatives=(
            descriptor.chronology_policy is not ChronologyPolicy.LINEAR
            or any(entry.contains_structured_alternatives for entry in descriptor.section_entries)
        ),
        structure_manifest_id=descriptor.structure_manifest_id,
    )


def _runtime_narrative_claim(payload: Mapping[str, object]) -> NarrativeClaim:
    """Rehydrate one validated immediate claim selected for exact M12 passthrough."""

    support_raw = payload.get("support")
    semantics_raw = payload.get("semantics")
    ordinal = payload.get("ordinal")
    if (
        not isinstance(support_raw, Mapping)
        or support_raw.get("kind") != SupportKind.CHILD_CLAIMS.value
        or not isinstance(semantics_raw, Mapping)
        or not isinstance(ordinal, int)
        or isinstance(ordinal, bool)
    ):
        raise ValueError("mandatory runtime claim is malformed")
    child_ids = support_raw.get("child_claim_ids")
    if not isinstance(child_ids, list) or any(not isinstance(item, str) for item in child_ids):
        raise ValueError("mandatory runtime claim support is malformed")
    return NarrativeClaim(
        logical_job_id=_required_text(payload, "logical_job_id"),
        job_kind=LogicalJobKind(_required_text(payload, "job_kind")),
        ordinal=ordinal,
        claim_class=ClaimClass(_required_text(payload, "claim_class")),
        context_scope=ClaimContextScope(_required_text(payload, "context_scope")),
        text=_required_text(payload, "text"),
        support=ClaimSupport(
            SupportKind.CHILD_CLAIMS,
            child_claim_ids=tuple(cast(list[str], child_ids)),
        ),
        semantics=ClaimSemantics(
            subject=_required_text(semantics_raw, "subject"),
            predicate=_required_text(semantics_raw, "predicate"),
            polarity=ClaimPolarity(_required_text(semantics_raw, "polarity")),
            normalized_value=_required_text(semantics_raw, "normalized_value"),
        ),
    )


def _prompt_claim(
    handle: str,
    claim: Mapping[str, object],
    context: StructuralContext | None = None,
) -> JsonValue:
    semantics = claim.get("semantics")
    result: dict[str, JsonValue] = {
        "handle": handle,
        "claim_class": _required_text(claim, "claim_class"),
        "context_scope": _required_text(claim, "context_scope"),
        "text": _required_text(claim, "text"),
        "semantics": cast(JsonValue, dict(semantics)) if isinstance(semantics, Mapping) else None,
    }
    if context is not None:
        result["structural_context"] = cast(JsonValue, context.to_dict())
    return result


def _runtime_claim_contexts(
    artifact: RuntimeNarrativeArtifact,
) -> dict[str, StructuralContext]:
    fallback = StructuralContext(
        chapter_id=artifact.chapter_id,
        lane_id=artifact.path.persistent_lane_id,
        route_id=artifact.path.route_id,
        temporary_container_id=artifact.path.temporary_container_id,
        temporary_arm_id=artifact.path.temporary_arm_id,
        occurrence_id=artifact.occurrence_id,
        call_site_id=artifact.call_site_id,
        loop_id=artifact.loop_id,
        temporal_anchor=artifact.temporal_anchor,
        structural_fingerprint=canonical_hash(
            {
                "artifact_id": artifact.artifact_id,
                "path": artifact.path.to_dict(),
                "structure_manifest_id": artifact.structure_manifest_id,
            }
        ),
    )
    raw = artifact.payload.get("claim_contexts")
    if raw is None:
        return {claim_id: fallback for claim_id in artifact.claim_ids}
    if not isinstance(raw, list) or len(raw) > MAX_PERSISTED_CLAIM_CONTEXTS:
        raise ValueError("runtime artifact claim contexts are malformed or unbounded")
    parsed: dict[str, StructuralContext] = {}
    expected_fields = set(StructuralContext().to_dict())
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != {"claim_id", "context"}:
            raise ValueError("runtime artifact claim context record is malformed")
        claim_id = item.get("claim_id")
        context_raw = item.get("context")
        if (
            not isinstance(claim_id, str)
            or claim_id in parsed
            or not isinstance(context_raw, Mapping)
            or set(context_raw) != expected_fields
        ):
            raise ValueError("runtime artifact claim context binding is malformed")
        values: dict[str, str | None] = {}
        for key in expected_fields:
            value = context_raw.get(key)
            if value is not None and not isinstance(value, str):
                raise ValueError("runtime artifact claim context value is malformed")
            values[key] = value
        parsed[claim_id] = StructuralContext(
            chapter_id=values["chapter_id"],
            lane_id=values["lane_id"],
            route_id=values["route_id"],
            temporary_container_id=values["temporary_container_id"],
            temporary_arm_id=values["temporary_arm_id"],
            occurrence_id=values["occurrence_id"],
            call_site_id=values["call_site_id"],
            loop_id=values["loop_id"],
            temporal_anchor=values["temporal_anchor"],
            structural_fingerprint=values["structural_fingerprint"],
        )
    if not set(artifact.claim_ids) <= set(parsed):
        raise ValueError("runtime artifact is missing propagated claim contexts")
    return {claim_id: parsed[claim_id] for claim_id in artifact.claim_ids}


def _required_text(value: Mapping[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"{key} must be a non-empty string")
    return result


def _mappings(values: Sequence[object]) -> tuple[Mapping[str, object], ...]:
    if any(not isinstance(item, Mapping) for item in values):
        raise ValueError("expected an array of objects")
    return tuple(cast(Mapping[str, object], item) for item in values)
