"""Public-synthetic C1 coverage for Phase 04 semantic assembly and publication."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

import pytest

from renpy_story_mapper.story_map_v2.contracts import canonical_json
from renpy_story_mapper.story_map_v2.phase04_chunk_plan import (
    ChoiceArmBoundary,
    ChunkPlanningChoice,
    ChunkPlanningPlacement,
    ChunkPlanningProjection,
    ChunkPlanningScope,
    StoryChunkDescriptor,
    StoryChunkPlan,
    plan_story_chunks,
)
from renpy_story_mapper.story_map_v2.phase04_publication import (
    AtomicGenerationPublisher,
    GenerationArtifact,
    GenerationBuildState,
    GenerationDescriptor,
    GenerationFreshness,
    GenerationKind,
    GenerationPointers,
    PathFact,
    PathFactKind,
    PathFactSnapshot,
    PublicationConflictError,
    derive_new_path_facts,
    generation_freshness,
    project_phase03_read_only,
)
from renpy_story_mapper.story_map_v2.phase04_sections import (
    DERIVED_SEMANTIC_FAN_IN,
    ROLLUP_SYNTHESIS_SCHEMA_VERSION,
    SECTION_SYNTHESIS_SCHEMA_VERSION,
    DerivedCallKind,
    DerivedSemanticJob,
    MeaningfulSection,
    RollupNodeRole,
    assemble_derived_semantics,
    build_derived_semantic_plan,
)
from renpy_story_mapper.story_map_v2.phase04_semantics import (
    MAX_REPLACEMENT_REVIEW_CALLS_PER_CHUNK,
    PHASE04_MAPPER_RESPONSE_SCHEMA,
    FrozenMapperJobBinding,
    Phase04MapperResponseValidator,
    SemanticAssemblyError,
    SemanticOrigin,
    SemanticValidationError,
    assemble_semantic_corridors,
    deserialize_semantic_chunk,
    replacement_review_allowed,
)

FAULT_BEFORE_GENERATION_PUBLICATION = "generation_publication.before"
FAULT_AFTER_GENERATION_PUBLICATION = "generation_publication.after"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _placement(
    scope_id: str,
    ordinal: int,
    *,
    arms: tuple[ChoiceArmBoundary, ...] = (),
    flags: tuple[str, ...] = (),
    raw_tokens: int = 12,
) -> ChunkPlanningPlacement:
    return ChunkPlanningPlacement(
        placement_id=f"{scope_id}:placement:{ordinal}",
        scope_id=scope_id,
        scene_id=f"{scope_id}:scene:{ordinal}",
        relative_path="game/public_synthetic.rpy",
        start_line=ordinal * 10,
        end_line=ordinal * 10 + 4,
        raw_text=f"Synthetic public story event {scope_id} {ordinal}.\n",
        raw_tokens=raw_tokens,
        atomic_group_id=f"{scope_id}:atomic:{ordinal}",
        choice_arms=arms,
        structural_flags=flags,
    )


def _choice() -> ChunkPlanningChoice:
    mechanics = {
        "choice_key": "choice:public",
        "caption": "Choose a public route",
        "arms": [
            {"order": 1, "caption": "First", "destination": "event:first"},
            {"order": 2, "caption": "Second", "destination": "event:second"},
        ],
    }
    return ChunkPlanningChoice(
        choice_key="choice:public",
        canonical_mechanics=json.dumps(mechanics, sort_keys=True, separators=(",", ":")),
        arm_orders=(1, 2),
    )


def _plan(
    *,
    route_events: int = 4,
    common_events: int = 4,
    route_raw_tokens: int = 12,
) -> StoryChunkPlan:
    common_placements = tuple(
        _placement(
            "scope:common",
            ordinal,
            arms=(
                ChoiceArmBoundary(
                    "choice:public",
                    1 if ordinal <= max(1, common_events // 2) else 2,
                    "local",
                    0,
                ),
            ),
            flags=("choice",) if ordinal == 1 else (),
        )
        for ordinal in range(1, common_events + 1)
    )
    scopes = [
        ChunkPlanningScope(
            scope_id="scope:common",
            ordinal=1,
            parent_scope_id=None,
            persistent_lane=False,
            branch_heavy=True,
            chapter_ordinal=0,
            lane_id="lane:spine",
            lane_kind="spine",
            placements=common_placements,
        )
    ]
    if route_events:
        route_placements = tuple(
            _placement(
                "scope:route",
                ordinal,
                flags=("route",),
                raw_tokens=route_raw_tokens,
            )
            for ordinal in range(1, route_events + 1)
        )
        scopes.append(
            ChunkPlanningScope(
                scope_id="scope:route",
                ordinal=2,
                parent_scope_id="scope:common",
                persistent_lane=True,
                branch_heavy=False,
                chapter_ordinal=0,
                lane_id="route:public",
                lane_kind="persistent",
                placements=route_placements,
            )
        )
    projection = ChunkPlanningProjection(
        story_plan_identity="story-plan-public-c1",
        source_identity="source-public-c1",
        scopes=tuple(scopes),
        choices=(_choice(),),
    )
    return plan_story_chunks(projection)


def _job(plan: StoryChunkPlan, chunk: StoryChunkDescriptor) -> FrozenMapperJobBinding:
    return FrozenMapperJobBinding(
        plan_id=plan.identity,
        scope_id=chunk.scope_id,
        chunk_id=chunk.chunk_id,
        request_sha256=cast(str, chunk.request_hash),
        request_byte_count=chunk.serialized_request_bytes,
    )


def _mapper_payload(
    plan: StoryChunkPlan,
    chunk: StoryChunkDescriptor,
    *,
    groups: tuple[tuple[str, ...], ...] | None = None,
    review: bool = False,
) -> bytes:
    memberships = (chunk.placement_ids,) if groups is None else groups
    branches = [
        {
            "choice_key": segment.choice_key,
            "arm_orders": list(segment.arm_orders),
            "summary": "The exact supplied arms lead to different story material.",
        }
        for segment in chunk.choice_segments
    ]
    return canonical_json(
        {
            "schema": PHASE04_MAPPER_RESPONSE_SCHEMA,
            "story_chunk_plan_identity": plan.identity,
            "chunk_id": chunk.chunk_id,
            "request_hash": chunk.request_hash,
            "scope_id": chunk.scope_id,
            "title": "A public story chunk",
            "overview": "The synthetic characters move through this exact corridor.",
            "review_requested": review,
            "events": [
                {
                    "key": f"proposed-{index}",
                    "placement_ids": list(membership),
                    "title": f"Public event {index}",
                    "summary": "A bounded synthetic event occurs.",
                    "characters": ["Avery"],
                }
                for index, membership in enumerate(memberships, start=1)
            ],
            "branch_summaries": branches,
        }
    )


def _accepted_assembly(
    plan: StoryChunkPlan,
    *,
    singleton_events: bool = False,
) -> tuple[bytes, ...]:
    validator = Phase04MapperResponseValidator(plan)
    results = []
    for chunk in plan.chunks:
        if chunk.structural_fallback_only:
            continue
        groups = (
            tuple((placement_id,) for placement_id in chunk.placement_ids)
            if singleton_events
            else None
        )
        results.append(
            validator.validate(
                _job(plan, chunk),
                _mapper_payload(plan, chunk, groups=groups),
                cached=False,
            ).normalized_payload
        )
    return tuple(results)


def test_mapper_validation_overlays_exact_python_mechanics() -> None:
    plan = _plan()
    chunk = plan.chunks[0]
    validated = Phase04MapperResponseValidator(plan).validate(
        _job(plan, chunk), _mapper_payload(plan, chunk), cached=False
    )
    normalized = deserialize_semantic_chunk(validated.normalized_payload)

    assert normalized.origin is SemanticOrigin.AI
    assert tuple(item for event in normalized.events for item in event.placement_ids) == (
        chunk.placement_ids
    )
    assert normalized.route_owner == "lane:spine"
    assert normalized.choices[0].canonical_mechanics == plan.choice_parents[0].canonical_mechanics
    assert normalized.choices[0].mechanics_hash == plan.choice_parents[0].mechanics_hash


@pytest.mark.parametrize("mutation", ["empty", "reordered", "foreign", "missing", "duplicate"])
def test_mapper_rejects_invalid_empty_reordered_hallucinated_and_incomplete_membership(
    mutation: str,
) -> None:
    plan = _plan()
    chunk = plan.chunks[0]
    placements = chunk.placement_ids
    groups: tuple[tuple[str, ...], ...]
    if mutation == "empty":
        groups = ()
    elif mutation == "reordered":
        groups = ((placements[1], placements[0], *placements[2:]),)
    elif mutation == "foreign":
        groups = ((placements[0], "placement:hallucinated", *placements[1:]),)
    elif mutation == "missing":
        groups = (placements[:-1],)
    else:
        groups = ((placements[0], placements[0], *placements[1:]),)

    with pytest.raises(SemanticValidationError):
        Phase04MapperResponseValidator(plan).validate(
            _job(plan, chunk),
            _mapper_payload(plan, chunk, groups=groups),
            cached=False,
        )


def test_mapper_rejects_wrong_branch_mechanics_and_cached_mutation() -> None:
    plan = _plan()
    chunk = plan.chunks[0]
    payload = json.loads(_mapper_payload(plan, chunk))
    payload["branch_summaries"][0]["arm_orders"] = [2, 1]
    validator = Phase04MapperResponseValidator(plan)
    with pytest.raises(SemanticValidationError):
        validator.validate(_job(plan, chunk), canonical_json(payload), cached=False)

    normalized = validator.validate(
        _job(plan, chunk), _mapper_payload(plan, chunk), cached=False
    ).normalized_payload
    mutated = json.loads(normalized)
    mutated["route_owner"] = "route:foreign"
    with pytest.raises(SemanticValidationError):
        validator.validate(_job(plan, chunk), canonical_json(mutated), cached=True)


def test_selective_replacement_review_pass_fail_and_one_call_ceiling() -> None:
    plan = _plan(route_events=0)
    chunk = plan.chunks[0]
    validator = Phase04MapperResponseValidator(plan)
    first = validator.validate(
        _job(plan, chunk), _mapper_payload(plan, chunk, review=True), cached=False
    )
    replacement = validator.validate(
        _job(plan, chunk), _mapper_payload(plan, chunk, review=False), cached=False
    )
    assert first.flagged_for_review is True
    assert replacement.flagged_for_review is False
    with pytest.raises(SemanticValidationError):
        validator.validate(_job(plan, chunk), b"{}", cached=False)
    assert MAX_REPLACEMENT_REVIEW_CALLS_PER_CHUNK == 1
    assert replacement_review_allowed(first, 0) is True
    assert replacement_review_allowed(first, 1) is False
    assert replacement_review_allowed(replacement, 0) is False


def test_frozen_corridor_assembly_uses_structural_fallback_without_replanning() -> None:
    plan = _plan()
    assembly = assemble_semantic_corridors(plan, ())
    assert tuple(
        placement for event in assembly.events for placement in event.placement_ids
    ) == plan.covered_placement_ids
    assert all(chunk.origin is SemanticOrigin.STRUCTURAL for chunk in assembly.chunks)

    accepted = _accepted_assembly(plan)
    with pytest.raises(SemanticAssemblyError, match="duplicate"):
        assemble_semantic_corridors(plan, (accepted[0], accepted[0]))


def test_derived_plan_freezes_dependency_aware_v2_ceilings_and_identity() -> None:
    plan = _plan()
    derived = build_derived_semantic_plan(plan, _digest("authority-public-c1"))
    assert derived.fan_in == DERIVED_SEMANTIC_FAN_IN
    assert derived.ceilings.section_synthesis_calls == 2
    assert derived.ceilings.route_reduction_calls == 0
    assert derived.ceilings.route_summary_calls == 1
    assert derived.ceilings.whole_game_reduction_calls == 0
    assert derived.ceilings.final_overview_calls == 1
    assert derived.ceilings.rollup_synthesis_calls == 2
    assert derived.semantic_plan_identity == build_derived_semantic_plan(
        plan, _digest("authority-public-c1")
    ).semantic_plan_identity


def test_persistent_route_spans_bounded_corridors_in_exact_order_and_ownership() -> None:
    plan = _plan(common_events=1, route_events=4, route_raw_tokens=3_000)
    route_chunks = tuple(chunk for chunk in plan.chunks if chunk.scope_id == "scope:route")
    assert len(route_chunks) >= 2
    derived = build_derived_semantic_plan(plan, _digest("authority-public-c1"))
    route = derived.persistent_routes[0]
    assert route.route_owner == "route:public"
    assert route.corridor_ids == tuple(chunk.chunk_id for chunk in route_chunks)
    corridor_by_id = {corridor.corridor_id: corridor for corridor in derived.corridors}
    assert [corridor_by_id[item].ordinal for item in route.corridor_ids] == sorted(
        corridor_by_id[item].ordinal for item in route.corridor_ids
    )
    assert [corridor_by_id[item].event_slot_upper_bound for item in route.corridor_ids] == [
        len(chunk.placement_ids) for chunk in route_chunks
    ]
    assert all(corridor_by_id[item].route_owner == "route:public" for item in route.corridor_ids)

    semantic = assemble_semantic_corridors(plan, _accepted_assembly(plan, singleton_events=True))
    fallback = assemble_derived_semantics(derived, semantic, _digest("candidate-corridors"))
    semantic_chunks = {chunk.chunk_id: chunk for chunk in semantic.chunks}
    jobs = {job.corridor_id: job for job in fallback.section_jobs}
    for corridor_id in route.corridor_ids:
        job = jobs[corridor_id]
        assert job.route_owner == "route:public"
        assert job.child_ids == tuple(
            event.event_id for event in semantic_chunks[corridor_id].events
        )
        assert len(job.child_ids) <= corridor_by_id[corridor_id].event_slot_upper_bound
    assert derived.ceilings.section_synthesis_calls == len(plan.chunks)
    assert derived.ceilings.route_reduction_calls == 0
    assert derived.ceilings.route_summary_calls == 1
    assert derived.ceilings.whole_game_reduction_calls == 0
    assert derived.ceilings.final_overview_calls == 1
    assert derived.ceilings.rollup_synthesis_calls == 2
    assert all(section.origin is SemanticOrigin.STRUCTURAL for section in fallback.sections)


def _section_payload(job: DerivedSemanticJob, *, incomplete: bool = False) -> bytes:
    child_ids = job.child_ids
    selected = child_ids[:-1] if incomplete else child_ids
    sections = []
    if selected:
        sections = [
            {
                "first_event_id": selected[0],
                "last_event_id": selected[-1],
                "title": "A meaningful public section",
                "summary": "The public events remain in exact order.",
            }
        ]
    return canonical_json(
        {
            "schema": SECTION_SYNTHESIS_SCHEMA_VERSION,
            "semantic_plan_identity": job.semantic_plan_identity,
            "candidate_generation_identity": job.candidate_generation_identity,
            "job_id": job.job_id,
            "corridor_id": job.corridor_id,
            "ordered_child_ids": list(child_ids),
            "title": "A meaningful synthetic corridor",
            "summary": "The public events form one contiguous section.",
            "sections": sections,
        }
    )


def _rollup_payload(job: DerivedSemanticJob, *, reordered: bool = False) -> bytes:
    child_ids = job.child_ids
    returned = tuple(reversed(child_ids)) if reordered else child_ids
    role = cast(RollupNodeRole, job.node_role)
    return canonical_json(
        {
            "schema": ROLLUP_SYNTHESIS_SCHEMA_VERSION,
            "semantic_plan_identity": job.semantic_plan_identity,
            "candidate_generation_identity": job.candidate_generation_identity,
            "job_id": job.job_id,
            "node_role": role.value,
            "route_owner": job.route_owner,
            "ordered_child_ids": list(returned),
            "title": "A bounded public rollup",
            "summary": "Verified child summaries are combined without changing membership.",
        }
    )


def test_section_and_rollup_results_reject_to_deterministic_zero_call_fallback() -> None:
    plan = _plan()
    semantic = assemble_semantic_corridors(plan, _accepted_assembly(plan))
    derived_plan = build_derived_semantic_plan(plan, _digest("authority-public-c1"))
    initial = assemble_derived_semantics(derived_plan, semantic, _digest("candidate-public"))
    section_payloads = {
        job.job_id: _section_payload(job, incomplete=index == 0)
        for index, job in enumerate(initial.section_jobs)
    }
    with_sections = assemble_derived_semantics(
        derived_plan,
        semantic,
        _digest("candidate-public"),
        section_payloads=section_payloads,
    )
    assert with_sections.corridor_results[0].origin is SemanticOrigin.STRUCTURAL
    assert with_sections.corridor_results[0].rejection_reason == "invalid_section_result"
    assert with_sections.corridor_results[1].origin is SemanticOrigin.AI

    overview_job = next(
        job
        for job in with_sections.rollup_jobs
        if job.node_role is RollupNodeRole.FINAL_OVERVIEW
    )
    invalid_rollup = {overview_job.job_id: _rollup_payload(overview_job, reordered=True)}
    rejected = assemble_derived_semantics(
        derived_plan,
        semantic,
        _digest("candidate-public"),
        section_payloads=section_payloads,
        rollup_payloads=invalid_rollup,
    )
    assert rejected.overview is not None
    assert rejected.overview.origin is SemanticOrigin.STRUCTURAL
    assert rejected.overview.rejection_reason == "invalid_rollup_result"


def test_dependency_created_rollups_bind_published_child_prose_and_accept_valid_results() -> None:
    plan = _plan()
    semantic = assemble_semantic_corridors(plan, _accepted_assembly(plan))
    derived_plan = build_derived_semantic_plan(plan, _digest("authority-public-c1"))
    first = assemble_derived_semantics(derived_plan, semantic, _digest("candidate-public"))
    section_payloads = {job.job_id: _section_payload(job) for job in first.section_jobs}
    sectioned = assemble_derived_semantics(
        derived_plan,
        semantic,
        _digest("candidate-public"),
        section_payloads=section_payloads,
    )
    route_job = next(
        job
        for job in sectioned.rollup_jobs
        if job.node_role is RollupNodeRole.ROUTE_SUMMARY
    )
    route_payloads = {route_job.job_id: _rollup_payload(route_job)}
    routed = assemble_derived_semantics(
        derived_plan,
        semantic,
        _digest("candidate-public"),
        section_payloads=section_payloads,
        rollup_payloads=route_payloads,
    )
    old_overview_job = next(
        job
        for job in sectioned.rollup_jobs
        if job.node_role is RollupNodeRole.FINAL_OVERVIEW
    )
    new_overview_job = next(
        job
        for job in routed.rollup_jobs
        if job.node_role is RollupNodeRole.FINAL_OVERVIEW
    )
    assert new_overview_job.job_id != old_overview_job.job_id
    assert new_overview_job.child_ids == old_overview_job.child_ids
    assert new_overview_job.child_prose_hashes != old_overview_job.child_prose_hashes

    payloads = {
        route_job.job_id: _rollup_payload(route_job),
        new_overview_job.job_id: _rollup_payload(new_overview_job),
    }
    complete = assemble_derived_semantics(
        derived_plan,
        semantic,
        _digest("candidate-public"),
        section_payloads=section_payloads,
        rollup_payloads=payloads,
    )
    assert all(result.origin is SemanticOrigin.AI for result in complete.corridor_results)
    assert complete.overview is not None
    assert complete.overview.origin is SemanticOrigin.AI


def test_all_ai_failure_still_builds_complete_structural_sections_and_overview() -> None:
    plan = _plan()
    semantic = assemble_semantic_corridors(plan, ())
    derived_plan = build_derived_semantic_plan(plan, _digest("authority-public-c1"))
    result = assemble_derived_semantics(derived_plan, semantic, _digest("candidate-public"))
    assert result.sections
    assert all(section.origin is SemanticOrigin.STRUCTURAL for section in result.sections)
    assert result.overview is not None
    assert result.overview.origin is SemanticOrigin.STRUCTURAL
    assert all(job.call_kind is DerivedCallKind.SECTION_SYNTHESIS for job in result.section_jobs)
    assert all(job.call_kind is DerivedCallKind.ROLLUP_SYNTHESIS for job in result.rollup_jobs)


def test_fixed_membership_rollup_upper_bound_is_finite_for_large_route() -> None:
    plan = _plan(route_events=30, common_events=1)
    derived = build_derived_semantic_plan(plan, _digest("authority-public-c1"))
    assert derived.ceilings.route_reduction_calls == 2
    assert derived.ceilings.route_summary_calls == 1
    assert derived.ceilings.final_overview_calls == 1
    assert derived.ceilings.rollup_synthesis_calls == 4


def _section(section_id: str = "section:public") -> MeaningfulSection:
    return MeaningfulSection(
        section_id=section_id,
        corridor_id="scope:common",
        route_owner=None,
        event_ids=("event:public",),
        title="Public section",
        summary="A public synthetic section.",
        origin=SemanticOrigin.STRUCTURAL,
    )


def _artifact(
    generation_id: str,
    kind: GenerationKind,
    *,
    baseline: str | None = None,
) -> GenerationArtifact:
    section = _section()
    fact = PathFact(PathFactKind.ARM, "arm:public", ("section:public",))
    new_facts = ()
    if baseline is not None:
        new_facts = derive_new_path_facts((fact,), PathFactSnapshot(baseline, ()))
    return GenerationArtifact(
        generation_id=generation_id,
        run_id="run-public",
        plan_id="plan-public",
        authority_identity=_digest("authority-publication"),
        story_chunk_plan_identity=_digest("chunk-plan-publication"),
        source_identity=_digest("source-publication"),
        coverage_hash=_digest("coverage-publication"),
        kind=kind,
        state=(
            GenerationBuildState.COMPLETE
            if kind is GenerationKind.COMPLETE
            else GenerationBuildState.STRUCTURAL
            if kind is GenerationKind.STRUCTURAL
            else GenerationBuildState.BUILDING
        ),
        title="Public story",
        overview="A public synthetic overview.",
        sections=(section,),
        path_facts=(fact,),
        baseline_generation_id=baseline,
        new_path_facts=new_facts,
    )


class _MemoryGenerationRepository:
    """C1-local generation primitive fake; Track B supplies the durable adapter."""

    def __init__(self) -> None:
        self._generations: dict[str, GenerationDescriptor] = {}
        self._pointers = GenerationPointers(None, None, 0)

    def create_generation(self, generation: GenerationDescriptor) -> None:
        existing = self._generations.get(generation.generation_id)
        if existing is not None and existing != generation:
            raise ValueError("generation identity is immutable")
        self._generations[generation.generation_id] = generation

    def set_active_generation(
        self,
        generation_id: str,
        *,
        expected_active_generation_id: str | None,
    ) -> GenerationPointers:
        if generation_id not in self._generations:
            raise ValueError("generation must exist before activation")
        if self._pointers.active_build_generation != expected_active_generation_id:
            raise PublicationConflictError("active generation pointer changed")
        self._pointers = GenerationPointers(
            self._pointers.current_complete_generation,
            generation_id,
            self._pointers.map_revision,
        )
        return self._pointers

    def generation_pointers(self) -> GenerationPointers:
        return self._pointers

    def publish_generation(
        self,
        generation_id: str,
        *,
        expected_active_generation_id: str,
        fault: Callable[[str], None] | None = None,
    ) -> GenerationPointers:
        if fault is not None:
            fault(FAULT_BEFORE_GENERATION_PUBLICATION)
        if self._pointers.active_build_generation != expected_active_generation_id:
            raise PublicationConflictError("active generation pointer changed")
        if generation_id != expected_active_generation_id:
            raise PublicationConflictError("published generation must be active")
        descriptor = self._generations[generation_id]
        if descriptor.kind is not GenerationKind.COMPLETE:
            raise ValueError("only complete generations may publish")
        self._pointers = GenerationPointers(
            generation_id,
            None,
            self._pointers.map_revision + 1,
        )
        if fault is not None:
            fault(FAULT_AFTER_GENERATION_PUBLICATION)
        return self._pointers


def _publication_repository() -> _MemoryGenerationRepository:
    return _MemoryGenerationRepository()


def test_atomic_publication_protects_previous_complete_and_rejects_stale_candidate(
) -> None:
    repository = _publication_repository()
    publisher = AtomicGenerationPublisher(repository)
    publisher.activate_progressive(
        _artifact("generation:build:1", GenerationKind.STRUCTURAL),
        expected_active_generation_id=None,
    )
    publisher.publish_complete(
        _artifact("generation:complete:1", GenerationKind.COMPLETE),
        expected_active_generation_id="generation:build:1",
    )
    publisher.activate_progressive(
        _artifact("generation:build:2", GenerationKind.CANDIDATE),
        expected_active_generation_id=None,
    )
    pointers = repository.generation_pointers()
    assert pointers.current_complete_generation == "generation:complete:1"
    assert generation_freshness("generation:complete:1", pointers) is GenerationFreshness.STALE
    with pytest.raises(PublicationConflictError, match="immediately prior accepted"):
        publisher.publish_complete(
            _artifact("generation:complete:wrong-baseline", GenerationKind.COMPLETE),
            expected_active_generation_id="generation:build:2",
        )
    with pytest.raises(PublicationConflictError, match="stale candidate"):
        publisher.publish_complete(
            _artifact(
                "generation:complete:stale",
                GenerationKind.COMPLETE,
                baseline="generation:complete:1",
            ),
            expected_active_generation_id="generation:build:wrong",
        )
    assert repository.generation_pointers().current_complete_generation == (
        "generation:complete:1"
    )
    published = publisher.publish_complete(
        _artifact(
            "generation:complete:2",
            GenerationKind.COMPLETE,
            baseline="generation:complete:1",
        ),
        expected_active_generation_id="generation:build:2",
    )
    assert published.current_complete_generation == "generation:complete:2"
    assert published.map_revision == 2


@pytest.mark.parametrize(
    ("fault_point", "pointer_advances"),
    [
        (FAULT_BEFORE_GENERATION_PUBLICATION, False),
        (FAULT_AFTER_GENERATION_PUBLICATION, True),
    ],
)
def test_atomic_publication_is_crash_safe_and_idempotently_resumable(
    fault_point: str,
    pointer_advances: bool,
) -> None:
    repository = _publication_repository()
    publisher = AtomicGenerationPublisher(repository)
    publisher.activate_progressive(
        _artifact("generation:build", GenerationKind.STRUCTURAL),
        expected_active_generation_id=None,
    )

    def inject(point: str) -> None:
        if point == fault_point:
            raise RuntimeError(point)

    complete = _artifact("generation:complete", GenerationKind.COMPLETE)
    with pytest.raises(RuntimeError, match=fault_point):
        publisher.publish_complete(
            complete,
            expected_active_generation_id="generation:build",
            fault=inject,
        )
    pointers = repository.generation_pointers()
    assert (pointers.current_complete_generation == "generation:complete") is pointer_advances
    resumed = publisher.publish_complete(
        complete,
        expected_active_generation_id="generation:build",
    )
    assert resumed.current_complete_generation == "generation:complete"
    assert resumed.active_build_generation is None
    assert resumed.map_revision == 1


def test_new_derivation_uses_path_facts_only_and_ignores_prose_changes() -> None:
    old = PathFactSnapshot(
        "generation:old",
        (PathFact(PathFactKind.ROUTE, "route:a", ("section:a",)),),
    )
    same_facts = (PathFact(PathFactKind.ROUTE, "route:a", ("section:a",)),)
    assert derive_new_path_facts(same_facts, old) == ()
    current = (
        *same_facts,
        PathFact(PathFactKind.ENDING, "ending:new", ("section:ending",)),
    )
    new_facts = derive_new_path_facts(current, old)
    assert len(new_facts) == 1
    assert new_facts[0].kind is PathFactKind.ENDING
    assert new_facts[0].fact_id == "ending:new"
    assert new_facts[0].section_ids == ("section:ending",)


def test_phase03_compatibility_projection_is_read_only_and_preserves_records() -> None:
    @dataclass(frozen=True)
    class Phase03Event:
        selection_id: str
        title: str
        summary: str

    @dataclass(frozen=True)
    class Phase03Section:
        id: str
        title: str
        summary: str
        events: tuple[Phase03Event, ...]

    @dataclass(frozen=True)
    class Phase03Page:
        status: str
        title: str
        overview: str
        sections: tuple[Phase03Section, ...]

    page = Phase03Page(
        status="complete",
        title="Phase 03 public story",
        overview="The accepted old record remains readable.",
        sections=(
            Phase03Section(
                id="section:phase03",
                title="Old section",
                summary="Old summary",
                events=(
                    Phase03Event(
                        selection_id="event:phase03",
                        title="Old event",
                        summary="Old event summary",
                    ),
                ),
            ),
        ),
    )
    projection = project_phase03_read_only(page)
    assert projection.read_only is True
    assert projection.sections[0].events[0].selection_id == "event:phase03"
    assert projection.title == page.title
