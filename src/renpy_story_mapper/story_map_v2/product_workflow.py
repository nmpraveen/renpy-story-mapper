"""Production preparation bridge for the Phase 04 full-game workflow.

This module is deliberately provider-free.  It turns current M10/M11 authority into the exact
StoryPlan, StoryChunkPlan, provider-request identities, workflow jobs, and finite approval
ceilings used by the durable runner.  Preparing this object never constructs a provider and the
returned raw request bytes are ephemeral; only their identities and the privacy-safe frozen plans
may be persisted.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import NoReturn, Protocol

from renpy_story_mapper.canonical_graph_contract import CanonicalGraph
from renpy_story_mapper.m11_scene_model import SceneModel
from renpy_story_mapper.story_map_v2.contracts import canonical_json
from renpy_story_mapper.story_map_v2.durable_repository import SqliteStoryMapV2Repository
from renpy_story_mapper.story_map_v2.frozen_plans import FrozenPlanBundle
from renpy_story_mapper.story_map_v2.loopback_transport import LoopbackLmStudioTransport
from renpy_story_mapper.story_map_v2.phase04_chunk_adapter import (
    adapt_chunk_planning_projection,
)
from renpy_story_mapper.story_map_v2.phase04_chunk_plan import (
    PHASE04_MAPPER_PROMPT_VERSION,
    ChunkPlanningProjection,
    StoryChunkDescriptor,
    plan_story_chunks,
    serialize_chunk_request,
)
from renpy_story_mapper.story_map_v2.phase04_sections import (
    ROLLUP_SYNTHESIS_ADAPTER_VERSION,
    ROLLUP_SYNTHESIS_PROMPT_VERSION,
    ROLLUP_SYNTHESIS_SCHEMA_VERSION,
    SECTION_SYNTHESIS_ADAPTER_VERSION,
    SECTION_SYNTHESIS_PROMPT_VERSION,
    SECTION_SYNTHESIS_SCHEMA_VERSION,
    DerivedCallKind,
    DerivedSemanticJob,
    build_derived_semantic_plan,
)
from renpy_story_mapper.story_map_v2.phase04_semantics import (
    PHASE04_MAPPER_RESPONSE_SCHEMA,
    FrozenMapperJobBinding,
    Phase04MapperResponseValidator,
)
from renpy_story_mapper.story_map_v2.provider_policy import LOCAL_MAPPER_MODEL
from renpy_story_mapper.story_map_v2.source_adapter import adapt_story_scope
from renpy_story_mapper.story_map_v2.story_plan import build_story_plan
from renpy_story_mapper.story_map_v2.workflow_cloud_provider import (
    CodexCliWorkflowProvider,
)
from renpy_story_mapper.story_map_v2.workflow_contracts import (
    CLOUD_FAST_MODE,
    CLOUD_MODEL,
    CLOUD_PROVIDER,
    CLOUD_REASONING,
    GLOBAL_SUBMISSION_SLOTS,
    LOOPBACK_REASONING,
    AuthorityIdentity,
    DerivedSemanticNodeRole,
    ProviderCallKind,
    ProviderInputIdentity,
    ProviderMode,
    ProviderSettings,
    SerializedRequestIdentity,
    ValidatedWorkflowResult,
    WorkflowCorridorDescriptor,
    WorkflowDerivedSemanticJobDescriptor,
    WorkflowDerivedSemanticPlanDescriptor,
    WorkflowExecutableJobDescriptor,
    WorkflowJobDescriptor,
    WorkflowPlanDescriptor,
    WorkflowPolicy,
    WorkflowPreview,
    WorkflowResourceCeilings,
    WorkflowRouteMembership,
)
from renpy_story_mapper.story_map_v2.workflow_protocols import ProviderFactory
from renpy_story_mapper.story_map_v2.workflow_repository_adapter import (
    DurableWorkflowRepositoryAdapter,
)
from renpy_story_mapper.story_map_v2.workflow_service import StoryMapWorkflowService


class ProductWorkflowProject(Protocol):
    """Small opened-project surface needed by the Phase 04 workflow."""

    def story_map_v2_repository(self) -> SqliteStoryMapV2Repository: ...

MAPPING_ADAPTER_VERSION = "story-map-v2-phase04-mapper-adapter-v1"
LOOPBACK_WORKFLOW_ADAPTER_VERSION = "story-map-v2-phase04-loopback-workflow-v1"
DERIVED_INPUT_TOKEN_ALLOWANCE = 10_700
OUTPUT_TOKEN_ALLOWANCE_PER_CALL = 8_000
ELAPSED_ALLOWANCE_MS_PER_CALL = 300_000
_CRITICAL_FLAGS = frozenset({"persistent_lane", "loop", "terminal", "unresolved"})


def local_lm_studio_workflow_settings() -> ProviderSettings:
    """Return the installed-model identity used by the supported local website workflow."""

    return ProviderSettings(
        provider="lm-studio-loopback",
        model=LOCAL_MAPPER_MODEL,
        reasoning=LOOPBACK_REASONING,
        fast_mode=None,
        mode=ProviderMode.LOOPBACK,
        adapter_version=LOOPBACK_WORKFLOW_ADAPTER_VERSION,
    )


@dataclass(frozen=True)
class PreparedProductWorkflow:
    """One exact zero-submit product preparation and its ephemeral request material."""

    run_id: str
    frozen_plans: FrozenPlanBundle
    projection: ChunkPlanningProjection
    plan: WorkflowPlanDescriptor
    policy: WorkflowPolicy
    ceilings: WorkflowResourceCeilings
    requests: tuple[tuple[SerializedRequestIdentity, bytes], ...]

    def __post_init__(self) -> None:
        if not self.run_id or self.run_id != self.run_id.strip():
            raise ValueError("run ID must be non-empty and trimmed")
        if self.plan.plan_id != self.frozen_plans.story_chunk_plan.identity:
            raise ValueError("workflow plan does not bind the frozen StoryChunkPlan")
        known = {identity.value for identity, _request in self.requests}
        if known != {job.serialized_request_identity.value for job in self.plan.jobs}:
            raise ValueError("workflow request material does not match the frozen jobs")
        for identity, request in self.requests:
            identity.verify(request)

    def materialized_requests(self) -> dict[str, bytes]:
        """Return a fresh execution-only lookup without making it durable."""

        return {identity.value: request for identity, request in self.requests}


class FrozenProductRequestMaterializer:
    """Execution-only request lookup that verifies every returned byte string."""

    def __init__(self, prepared: PreparedProductWorkflow) -> None:
        self._requests = prepared.materialized_requests()

    def materialize(self, identity: SerializedRequestIdentity) -> bytes:
        try:
            request = self._requests[identity.value]
        except KeyError as exc:
            raise ValueError("the frozen workflow request is unavailable") from exc
        identity.verify(request)
        return request

    def register(self, identity: SerializedRequestIdentity, request: bytes) -> None:
        """Add one dependency-created exact request without replacing frozen material."""

        identity.verify(request)
        existing = self._requests.setdefault(identity.value, request)
        if existing != request:
            raise ValueError("a workflow request identity cannot be reused for new bytes")


class ProductWorkflowValidator:
    """Adapt the scalar durable mapping job to the authority-owning semantic validator."""

    def __init__(self, prepared: PreparedProductWorkflow) -> None:
        self._validator = Phase04MapperResponseValidator(
            prepared.frozen_plans.story_chunk_plan
        )

    def validate(
        self,
        job: WorkflowExecutableJobDescriptor,
        payload: bytes,
        *,
        cached: bool,
    ) -> ValidatedWorkflowResult:
        if isinstance(job, WorkflowDerivedSemanticJobDescriptor):
            return _validate_derived_provider_prose(job, payload, cached=cached)
        if not isinstance(job, WorkflowJobDescriptor):
            raise TypeError("unsupported workflow job descriptor")
        binding = FrozenMapperJobBinding(
            plan_id=job.plan_id,
            scope_id=job.scope_id,
            chunk_id=job.chunk_id,
            request_sha256=job.serialized_request_identity.sha256,
            request_byte_count=job.serialized_request_identity.byte_count,
        )
        bound_payload = payload if cached else _bind_provider_prose(job, payload)
        result = self._validator.validate(binding, bound_payload, cached=cached)
        return ValidatedWorkflowResult(
            result.result_identity,
            result.normalized_payload,
            result.flagged_for_review,
        )


def _bind_provider_prose(job: WorkflowJobDescriptor, payload: bytes) -> bytes:
    """Overlay Python-owned request and authority identities onto provider prose."""

    try:
        value: object = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return payload
    if not isinstance(value, dict):
        return payload
    expected = {"title", "overview", "review_requested", "events", "branch_summaries"}
    if set(value) != expected:
        return payload
    return canonical_json(
        {
            "schema": PHASE04_MAPPER_RESPONSE_SCHEMA,
            "story_chunk_plan_identity": job.plan_id,
            "chunk_id": job.chunk_id,
            "request_hash": job.serialized_request_identity.sha256,
            "scope_id": job.scope_id,
            **value,
        }
    )


def _validate_derived_provider_prose(
    job: WorkflowDerivedSemanticJobDescriptor,
    payload: bytes,
    *,
    cached: bool,
) -> ValidatedWorkflowResult:
    """Bind section/overview prose to Python-owned membership and job identities."""

    try:
        value: object = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("derived provider prose is not JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("derived provider prose must be an object")
    if job.call_kind is ProviderCallKind.SECTION_SYNTHESIS:
        prose = _section_prose(job, value, cached=cached)
        bound: dict[str, object] = {
            "schema": job.provider_input_identity.schema_version,
            "semantic_plan_identity": job.semantic_plan_identity,
            "candidate_generation_identity": job.candidate_generation_identity,
            "job_id": job.job_id,
            "corridor_id": job.corridor_id,
            "ordered_child_ids": list(job.child_ids),
            **prose,
        }
    elif job.call_kind is ProviderCallKind.ROLLUP_SYNTHESIS:
        prose = _rollup_prose(job, value, cached=cached)
        if job.node_role is None:
            raise ValueError("rollup job is missing its Python-owned role")
        bound = {
            "schema": job.provider_input_identity.schema_version,
            "semantic_plan_identity": job.semantic_plan_identity,
            "candidate_generation_identity": job.candidate_generation_identity,
            "job_id": job.job_id,
            "node_role": job.node_role.value,
            "route_owner": job.route_owner,
            "ordered_child_ids": list(job.child_ids),
            **prose,
        }
    else:
        raise ValueError("unsupported derived semantic call kind")
    normalized = canonical_json(bound)
    return ValidatedWorkflowResult(hashlib.sha256(normalized).hexdigest(), normalized)


def _section_prose(
    job: WorkflowDerivedSemanticJobDescriptor,
    value: dict[object, object],
    *,
    cached: bool,
) -> dict[str, object]:
    prose_keys = {"title", "summary", "sections"}
    bound_keys = prose_keys | {
        "schema",
        "semantic_plan_identity",
        "candidate_generation_identity",
        "job_id",
        "corridor_id",
        "ordered_child_ids",
    }
    if set(value) != (bound_keys if cached else prose_keys):
        raise ValueError("section prose fields do not match the frozen schema")
    if cached:
        _verify_derived_binding(job, value, section=True)
    title = _derived_text(value["title"], "section title", 80)
    summary = _derived_text(value["summary"], "section summary", 600)
    raw_sections = value["sections"]
    if not isinstance(raw_sections, list) or not raw_sections:
        raise ValueError("section prose requires at least one section")
    indexes = {child_id: index for index, child_id in enumerate(job.child_ids)}
    cursor = 0
    sections: list[dict[str, object]] = []
    for raw in raw_sections:
        if not isinstance(raw, dict) or set(raw) != {
            "first_event_id",
            "last_event_id",
            "title",
            "summary",
        }:
            raise ValueError("section proposal fields are invalid")
        first = _derived_text(raw["first_event_id"], "first event ID", 2_000)
        last = _derived_text(raw["last_event_id"], "last event ID", 2_000)
        if first not in indexes or last not in indexes:
            raise ValueError("section proposal references a foreign child")
        first_index = indexes[first]
        last_index = indexes[last]
        if first_index != cursor or last_index < first_index:
            raise ValueError("section proposal is not contiguous and ordered")
        cursor = last_index + 1
        sections.append(
            {
                "first_event_id": first,
                "last_event_id": last,
                "title": _derived_text(raw["title"], "proposed section title", 80),
                "summary": _derived_text(
                    raw["summary"], "proposed section summary", 600
                ),
            }
        )
    if cursor != len(job.child_ids):
        raise ValueError("section proposal does not cover every child exactly once")
    return {"title": title, "summary": summary, "sections": sections}


def _rollup_prose(
    job: WorkflowDerivedSemanticJobDescriptor,
    value: dict[object, object],
    *,
    cached: bool,
) -> dict[str, object]:
    prose_keys = {"title", "summary"}
    bound_keys = prose_keys | {
        "schema",
        "semantic_plan_identity",
        "candidate_generation_identity",
        "job_id",
        "node_role",
        "route_owner",
        "ordered_child_ids",
    }
    if set(value) != (bound_keys if cached else prose_keys):
        raise ValueError("rollup prose fields do not match the frozen schema")
    if cached:
        _verify_derived_binding(job, value, section=False)
    return {
        "title": _derived_text(value["title"], "rollup title", 80),
        "summary": _derived_text(value["summary"], "rollup summary", 800),
    }


def _verify_derived_binding(
    job: WorkflowDerivedSemanticJobDescriptor,
    value: dict[object, object],
    *,
    section: bool,
) -> None:
    expected: dict[str, object] = {
        "schema": job.provider_input_identity.schema_version,
        "semantic_plan_identity": job.semantic_plan_identity,
        "candidate_generation_identity": job.candidate_generation_identity,
        "job_id": job.job_id,
        "ordered_child_ids": list(job.child_ids),
    }
    if section:
        expected["corridor_id"] = job.corridor_id
    else:
        expected["node_role"] = None if job.node_role is None else job.node_role.value
        expected["route_owner"] = job.route_owner
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise ValueError("cached derived prose has stale or foreign membership")


def _derived_text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must be non-empty, trimmed, and bounded")
    return value


def persist_product_workflow_preview(
    project: ProductWorkflowProject,
    prepared: PreparedProductWorkflow,
) -> WorkflowPreview:
    """Persist one zero-submit preview and its privacy-safe plans.

    The provider factory is an explicit trap.  A later execution composer must replace it with
    the real approved transport; this preparation function cannot construct a provider even by
    accident.
    """

    def provider_construction_forbidden() -> NoReturn:
        raise AssertionError("Prepare must not construct a provider")

    repository = DurableWorkflowRepositoryAdapter.from_project(project)
    service = StoryMapWorkflowService(
        repository,
        FrozenProductRequestMaterializer(prepared),
        ProductWorkflowValidator(prepared),
        cloud_factory=provider_construction_forbidden,
    )
    return service.prepare(
        prepared.run_id,
        prepared.plan,
        prepared.policy,
        prepared.ceilings,
        frozen_plans=prepared.frozen_plans,
    )


def create_product_workflow_service(
    project: ProductWorkflowProject,
    prepared: PreparedProductWorkflow,
    *,
    cloud_factory: ProviderFactory | None = None,
    loopback_factory: ProviderFactory | None = None,
    request_materializer: FrozenProductRequestMaterializer | None = None,
) -> StoryMapWorkflowService:
    """Compose the durable runner without constructing a provider before execution."""

    materializer = request_materializer or FrozenProductRequestMaterializer(prepared)
    if prepared.policy.cloud.mode is ProviderMode.LOOPBACK:
        if cloud_factory is not None:
            raise ValueError("local-only workflow cannot accept a cloud provider factory")
        primary_factory = loopback_factory or LoopbackLmStudioTransport
    else:
        primary_factory = cloud_factory or CodexCliWorkflowProvider
    return StoryMapWorkflowService(
        DurableWorkflowRepositoryAdapter.from_project(project),
        materializer,
        ProductWorkflowValidator(prepared),
        cloud_factory=primary_factory,
        loopback_factory=loopback_factory,
    )


def adapt_derived_semantic_job(
    prepared: PreparedProductWorkflow,
    job: DerivedSemanticJob,
) -> WorkflowDerivedSemanticJobDescriptor:
    """Adapt one dependency-ready C job into the durable B workflow contract."""

    semantic = prepared.plan.derived_semantic_plan
    if semantic is None or job.semantic_plan_identity != semantic.semantic_plan_identity:
        raise ValueError("derived job does not bind the prepared semantic plan")
    request_identity = SerializedRequestIdentity(
        job.request_identity.value,
        job.request_identity.sha256,
        job.request_identity.byte_count,
    )
    if job.call_kind is DerivedCallKind.SECTION_SYNTHESIS:
        prompt_version = SECTION_SYNTHESIS_PROMPT_VERSION
        schema_version = SECTION_SYNTHESIS_SCHEMA_VERSION
        adapter_version = SECTION_SYNTHESIS_ADAPTER_VERSION
    else:
        prompt_version = ROLLUP_SYNTHESIS_PROMPT_VERSION
        schema_version = ROLLUP_SYNTHESIS_SCHEMA_VERSION
        adapter_version = ROLLUP_SYNTHESIS_ADAPTER_VERSION
    primary = prepared.policy.cloud
    provider_input = ProviderInputIdentity(
        serialized_request_identity=request_identity,
        prompt_version=prompt_version,
        schema_version=schema_version,
        adapter_version=adapter_version,
        provider=primary.provider,
        model=primary.model,
        reasoning=primary.reasoning,
        fast_mode=primary.fast_mode,
        mode=primary.mode,
    )
    node_role = (
        None
        if job.node_role is None
        else DerivedSemanticNodeRole(job.node_role.value)
    )
    return WorkflowDerivedSemanticJobDescriptor(
        plan_id=prepared.plan.plan_id,
        semantic_plan_identity=job.semantic_plan_identity,
        story_chunk_plan_identity=semantic.story_chunk_plan_identity,
        candidate_generation_identity=job.candidate_generation_identity,
        authority_identity=prepared.plan.authority_identity,
        job_id=job.job_id,
        call_kind=ProviderCallKind(job.call_kind.value),
        node_role=node_role,
        corridor_id=job.corridor_id,
        route_owner=job.route_owner,
        child_ids=job.child_ids,
        child_prose_hashes=job.child_prose_hashes,
        ordinal=job.ordinal,
        serialized_request_identity=request_identity,
        provider_input_identity=provider_input,
        cache_identity=provider_input.cache_identity,
    )


def prepare_product_workflow_from_authority(
    graph: CanonicalGraph,
    scene_model: SceneModel,
    *,
    run_id: str,
    loopback: ProviderSettings | None = None,
    primary: ProviderSettings | None = None,
) -> PreparedProductWorkflow:
    """Pure authority-to-preview bridge used by the website and public fixtures."""

    graph.validate()
    scene_model.validate()
    source = adapt_story_scope(graph, scene_model=scene_model)
    story_plan = build_story_plan(graph, scene_model=scene_model, source_scope=source)
    projection = adapt_chunk_planning_projection(story_plan, source)
    chunk_plan = plan_story_chunks(projection)
    frozen_plans = FrozenPlanBundle(story_plan, chunk_plan)
    authority = AuthorityIdentity(graph.authority_hash)
    policy = _workflow_policy(loopback, primary=primary)

    jobs: list[WorkflowJobDescriptor] = []
    requests: list[tuple[SerializedRequestIdentity, bytes]] = []
    provider_chunks = tuple(
        chunk for chunk in chunk_plan.chunks if not chunk.structural_fallback_only
    )
    if not provider_chunks:
        raise ValueError("the current story plan contains no provider-eligible story chunks")
    for chunk in provider_chunks:
        request = serialize_chunk_request(chunk_plan, chunk.chunk_id, projection)
        identity = SerializedRequestIdentity(
            value=f"chunk-request:{chunk.chunk_id}",
            sha256=chunk.request_hash or "",
            byte_count=chunk.serialized_request_bytes,
        )
        identity.verify(request)
        jobs.append(
            WorkflowJobDescriptor(
                plan_id=chunk_plan.identity,
                scope_id=chunk.scope_id,
                job_id=f"mapping:{chunk.chunk_id}",
                chunk_id=chunk.chunk_id,
                authority_identity=authority,
                serialized_request_identity=identity,
                cache_identity=policy.input_identity(identity).cache_identity,
                critical=_critical_chunk(chunk),
            )
        )
        requests.append((identity, request))

    derived = build_derived_semantic_plan(chunk_plan, authority.value)
    derived_descriptor = WorkflowDerivedSemanticPlanDescriptor(
        semantic_plan_identity=derived.semantic_plan_identity,
        story_chunk_plan_identity=derived.story_chunk_plan_identity,
        authority_identity=authority,
        corridors=tuple(
            WorkflowCorridorDescriptor(
                item.corridor_id,
                item.route_owner,
                item.event_slot_upper_bound,
                item.ordinal,
            )
            for item in derived.corridors
        ),
        route_memberships=tuple(
            WorkflowRouteMembership(item.route_owner, item.corridor_ids)
            for item in derived.persistent_routes
        ),
        section_synthesis_calls=derived.ceilings.section_synthesis_calls,
        route_reduction_calls=derived.ceilings.route_reduction_calls,
        route_summary_calls=derived.ceilings.route_summary_calls,
        whole_game_reduction_calls=derived.ceilings.whole_game_reduction_calls,
        final_overview_calls=derived.ceilings.final_overview_calls,
        rollup_synthesis_calls=derived.ceilings.rollup_synthesis_calls,
    )
    plan = WorkflowPlanDescriptor(
        chunk_plan.identity,
        authority,
        tuple(jobs),
        derived_descriptor,
    )
    ceilings = _resource_ceilings(
        provider_chunks,
        derived_descriptor,
        loopback is not None,
        local_primary=policy.cloud.mode is ProviderMode.LOOPBACK,
    )
    return PreparedProductWorkflow(
        run_id,
        frozen_plans,
        projection,
        plan,
        policy,
        ceilings,
        tuple(requests),
    )


def _workflow_policy(
    loopback: ProviderSettings | None,
    *,
    primary: ProviderSettings | None = None,
) -> WorkflowPolicy:
    if loopback is not None and loopback.mode is not ProviderMode.LOOPBACK:
        raise ValueError("the optional fallback must use loopback mode")
    selected_primary = primary or ProviderSettings(
        provider=CLOUD_PROVIDER,
        model=CLOUD_MODEL,
        reasoning=CLOUD_REASONING,
        fast_mode=CLOUD_FAST_MODE,
        mode=ProviderMode.CLOUD,
        adapter_version=MAPPING_ADAPTER_VERSION,
    )
    if selected_primary.mode is ProviderMode.LOOPBACK and loopback is not None:
        raise ValueError("local-only primary cannot also configure refusal fallback")
    return WorkflowPolicy(
        prompt_version=PHASE04_MAPPER_PROMPT_VERSION,
        schema_version=PHASE04_MAPPER_RESPONSE_SCHEMA,
        cloud=selected_primary,
        loopback=loopback,
        allow_refusal_fallback=loopback is not None,
    )


def _critical_chunk(chunk: StoryChunkDescriptor) -> bool:
    return bool(chunk.choice_segments or _CRITICAL_FLAGS.intersection(chunk.structural_flags))


def _resource_ceilings(
    chunks: tuple[StoryChunkDescriptor, ...],
    derived: WorkflowDerivedSemanticPlanDescriptor,
    has_loopback: bool,
    *,
    local_primary: bool = False,
) -> WorkflowResourceCeilings:
    mapping_calls = len(chunks)
    derived_calls = derived.section_synthesis_calls + derived.rollup_synthesis_calls
    maximum_calls = mapping_calls * (2 + int(has_loopback)) + derived_calls
    mapping_input = sum(chunk.complete_request_tokens or 0 for chunk in chunks)
    return WorkflowResourceCeilings(
        mapping_calls=mapping_calls,
        review_calls=mapping_calls,
        fallback_calls=mapping_calls if has_loopback else 0,
        input_tokens=max(
            1,
            mapping_input * (2 + int(has_loopback))
            + derived_calls * DERIVED_INPUT_TOKEN_ALLOWANCE,
        ),
        output_tokens=max(1, maximum_calls * OUTPUT_TOKEN_ALLOWANCE_PER_CALL),
        elapsed_ms=max(1, maximum_calls * ELAPSED_ALLOWANCE_MS_PER_CALL),
        submission_slots=1 if local_primary else GLOBAL_SUBMISSION_SLOTS,
        indeterminate_retry_calls=mapping_calls + derived_calls,
        section_synthesis_calls=derived.section_synthesis_calls,
        route_reduction_calls=derived.route_reduction_calls,
        route_summary_calls=derived.route_summary_calls,
        whole_game_reduction_calls=derived.whole_game_reduction_calls,
        final_overview_calls=derived.final_overview_calls,
        rollup_synthesis_calls=derived.rollup_synthesis_calls,
    )
