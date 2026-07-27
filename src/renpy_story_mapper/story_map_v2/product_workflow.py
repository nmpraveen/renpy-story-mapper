"""Production preparation bridge for the Phase 04 full-game workflow.

This module is deliberately provider-free.  It turns current M10/M11 authority into the exact
StoryPlan, StoryChunkPlan, provider-request identities, workflow jobs, and finite approval
ceilings used by the durable runner.  Preparing this object never constructs a provider and the
returned raw request bytes are ephemeral; only their identities and the privacy-safe frozen plans
may be persisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn, cast

from renpy_story_mapper.canonical_graph_contract import CanonicalGraph
from renpy_story_mapper.m11_scene_model import SceneModel
from renpy_story_mapper.m12_service import canonical_graph_from_mapping, load_m12_authority
from renpy_story_mapper.project import Project
from renpy_story_mapper.story_map_v2.frozen_plans import FrozenPlanBundle
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
from renpy_story_mapper.story_map_v2.phase04_sections import build_derived_semantic_plan
from renpy_story_mapper.story_map_v2.phase04_semantics import (
    PHASE04_MAPPER_RESPONSE_SCHEMA,
    FrozenMapperJobBinding,
    Phase04MapperResponseValidator,
)
from renpy_story_mapper.story_map_v2.source_adapter import adapt_story_scope
from renpy_story_mapper.story_map_v2.story_plan import build_story_plan
from renpy_story_mapper.story_map_v2.workflow_contracts import (
    CLOUD_FAST_MODE,
    CLOUD_MODEL,
    CLOUD_PROVIDER,
    CLOUD_REASONING,
    AuthorityIdentity,
    ProviderMode,
    ProviderSettings,
    SerializedRequestIdentity,
    ValidatedWorkflowResult,
    WorkflowCorridorDescriptor,
    WorkflowDerivedSemanticPlanDescriptor,
    WorkflowExecutableJobDescriptor,
    WorkflowJobDescriptor,
    WorkflowPlanDescriptor,
    WorkflowPolicy,
    WorkflowPreview,
    WorkflowResourceCeilings,
    WorkflowRouteMembership,
)
from renpy_story_mapper.story_map_v2.workflow_repository_adapter import (
    DurableWorkflowRepositoryAdapter,
)
from renpy_story_mapper.story_map_v2.workflow_service import StoryMapWorkflowService

MAPPING_ADAPTER_VERSION = "story-map-v2-phase04-mapper-adapter-v1"
DERIVED_INPUT_TOKEN_ALLOWANCE = 10_700
OUTPUT_TOKEN_ALLOWANCE_PER_CALL = 8_000
ELAPSED_ALLOWANCE_MS_PER_CALL = 300_000
_CRITICAL_FLAGS = frozenset({"persistent_lane", "loop", "terminal", "unresolved"})


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
        if not isinstance(job, WorkflowJobDescriptor):
            raise ValueError("derived semantic validation is not available in the mapper adapter")
        binding = FrozenMapperJobBinding(
            plan_id=job.plan_id,
            scope_id=job.scope_id,
            chunk_id=job.chunk_id,
            request_sha256=job.serialized_request_identity.sha256,
            request_byte_count=job.serialized_request_identity.byte_count,
        )
        result = self._validator.validate(binding, payload, cached=cached)
        return ValidatedWorkflowResult(
            result.result_identity,
            result.normalized_payload,
            result.flagged_for_review,
        )


def persist_product_workflow_preview(
    project: Project,
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


def prepare_product_workflow(
    project: Project,
    *,
    run_id: str,
    loopback: ProviderSettings | None = None,
) -> PreparedProductWorkflow:
    """Prepare the current opened project without constructing or calling a provider."""

    graph, scene_model = _current_full_authority(project)
    return prepare_product_workflow_from_authority(
        graph,
        scene_model,
        run_id=run_id,
        loopback=loopback,
    )


def prepare_product_workflow_from_authority(
    graph: CanonicalGraph,
    scene_model: SceneModel,
    *,
    run_id: str,
    loopback: ProviderSettings | None = None,
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
    policy = _workflow_policy(loopback)

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
    ceilings = _resource_ceilings(provider_chunks, derived_descriptor, loopback is not None)
    return PreparedProductWorkflow(
        run_id,
        frozen_plans,
        projection,
        plan,
        policy,
        ceilings,
        tuple(requests),
    )


def _current_full_authority(project: Project) -> tuple[CanonicalGraph, SceneModel]:
    current = load_m12_authority(project)
    value = project.payload("m10_canonical_graph", "authoritative")
    if not isinstance(value, dict):
        raise ValueError("Phase 04 requires current complete M10 authority")
    graph = canonical_graph_from_mapping(cast(dict[str, object], value))
    if (
        graph.source_generation != current.graph.source_generation
        or graph.authority_hash != current.canonical_hash
        or current.scene_model.binding.canonical_hash != graph.authority_hash
    ):
        raise ValueError("Phase 04 authority changed while preparing the Story Map")
    return graph, current.scene_model


def _workflow_policy(loopback: ProviderSettings | None) -> WorkflowPolicy:
    if loopback is not None and loopback.mode is not ProviderMode.LOOPBACK:
        raise ValueError("the optional fallback must use loopback mode")
    return WorkflowPolicy(
        prompt_version=PHASE04_MAPPER_PROMPT_VERSION,
        schema_version=PHASE04_MAPPER_RESPONSE_SCHEMA,
        cloud=ProviderSettings(
            provider=CLOUD_PROVIDER,
            model=CLOUD_MODEL,
            reasoning=CLOUD_REASONING,
            fast_mode=CLOUD_FAST_MODE,
            mode=ProviderMode.CLOUD,
            adapter_version=MAPPING_ADAPTER_VERSION,
        ),
        loopback=loopback,
        allow_refusal_fallback=loopback is not None,
    )


def _critical_chunk(chunk: StoryChunkDescriptor) -> bool:
    return bool(chunk.choice_segments or _CRITICAL_FLAGS.intersection(chunk.structural_flags))


def _resource_ceilings(
    chunks: tuple[StoryChunkDescriptor, ...],
    derived: WorkflowDerivedSemanticPlanDescriptor,
    has_loopback: bool,
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
        indeterminate_retry_calls=mapping_calls + derived_calls,
        section_synthesis_calls=derived.section_synthesis_calls,
        route_reduction_calls=derived.route_reduction_calls,
        route_summary_calls=derived.route_summary_calls,
        whole_game_reduction_calls=derived.whole_game_reduction_calls,
        final_overview_calls=derived.final_overview_calls,
        rollup_synthesis_calls=derived.rollup_synthesis_calls,
    )
