"""Public-synthetic C1 coverage for Phase 04 semantic assembly and publication."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
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
    build_generation_artifact,
    derive_new_path_facts,
    generation_freshness,
    project_phase03_read_only,
)
from renpy_story_mapper.story_map_v2.phase04_sections import (
    DERIVED_SEMANTIC_FAN_IN,
    ROLLUP_SYNTHESIS_SCHEMA_VERSION,
    SECTION_SYNTHESIS_SCHEMA_VERSION,
    DerivedCallKind,
    DerivedSemanticError,
    DerivedSemanticJob,
    MeaningfulSection,
    RollupNodeRole,
    assemble_derived_semantics,
    build_derived_semantic_plan,
    build_editorial_timeline_request,
    build_editorial_timeline_rollup_request,
    combine_editorial_timeline_batches,
    partition_editorial_timeline_sections,
    validate_editorial_timeline_response,
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
_POINTER_EXPECTATION_UNSET = object()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _editorial_sections(count: int) -> tuple[MeaningfulSection, ...]:
    return tuple(
        MeaningfulSection(
            section_id=f"section:public-{index:03d}",
            corridor_id=f"corridor:public-{index:03d}",
            route_owner=None,
            event_ids=(f"event:public-{index:03d}",),
            title=f"Public section {index + 1}",
            summary=f"Public synthetic story summary {index + 1}.",
            origin=SemanticOrigin.AI,
        )
        for index in range(count)
    )


def _editorial_payload(
    sections: tuple[MeaningfulSection, ...], ranges: tuple[tuple[int, int], ...]
) -> bytes:
    return canonical_json(
        {
            "title": "Whole public story",
            "summary": "The public story advances chronologically across every source section.",
            "sections": [
                {
                    "first_event_id": sections[first].section_id,
                    "last_event_id": sections[last].section_id,
                    "title": f"Major event {index + 1}",
                    "summary": "A concise public synthetic major event.",
                }
                for index, (first, last) in enumerate(ranges)
            ],
        }
    )


def _editorial_batch_payload(
    sections: tuple[MeaningfulSection, ...], ranges: tuple[tuple[int, int], ...]
) -> bytes:
    payload = json.loads(_editorial_payload(sections, ranges))
    proposals = payload["sections"]
    assert isinstance(proposals, list)
    for proposal, (first, last) in zip(proposals, ranges, strict=True):
        proposal["first_event_id"] = f"source:{first:03d}"
        proposal["last_event_id"] = f"source:{last:03d}"
    return canonical_json(payload)


def test_editorial_timeline_reuses_section_shape_and_preserves_exact_coverage() -> None:
    sections = _editorial_sections(12)
    authority = _digest("public-editorial-authority")

    request = json.loads(build_editorial_timeline_request(sections, authority))
    timeline = validate_editorial_timeline_response(
        sections,
        authority,
        _editorial_payload(sections, tuple((index, index) for index in range(12))),
    )

    assert request["call_kind"] == "section_synthesis"
    assert request["schema_version"] == SECTION_SYNTHESIS_SCHEMA_VERSION
    assert request["ordered_child_ids"] == [section.section_id for section in sections]
    assert "complete sentences" in request["task"]
    assert "sentence boundary" in request["task"]
    assert len(timeline.groups) == 12
    assert tuple(
        source_id for group in timeline.groups for source_id in group.source_section_ids
    ) == tuple(section.section_id for section in sections)
    assert tuple(event_id for group in timeline.groups for event_id in group.event_ids) == tuple(
        event_id for section in sections for event_id in section.event_ids
    )
    assert timeline.sections[0].section_id.startswith("story-group:")


@pytest.mark.parametrize("mutation", ["too_few", "foreign", "duplicate", "extra_fact"])
def test_editorial_timeline_rejects_invalid_membership_or_fact_fields(mutation: str) -> None:
    sections = _editorial_sections(12)
    ranges = [(index, index) for index in range(12)]
    payload = json.loads(_editorial_payload(sections, tuple(ranges)))
    proposals = payload["sections"]
    assert isinstance(proposals, list)
    if mutation == "too_few":
        proposals[-2]["last_event_id"] = sections[-1].section_id
        proposals.pop()
    elif mutation == "foreign":
        proposals[0]["first_event_id"] = "section:foreign"
    elif mutation == "duplicate":
        proposals[1]["first_event_id"] = sections[0].section_id
    else:
        proposals[0]["effects"] = ["invented_flag = True"]

    with pytest.raises(DerivedSemanticError):
        validate_editorial_timeline_response(
            sections, _digest("authority"), canonical_json(payload)
        )


def test_editorial_timeline_rejects_more_than_thirty_groups() -> None:
    sections = _editorial_sections(31)
    with pytest.raises(DerivedSemanticError, match="bounded group count"):
        validate_editorial_timeline_response(
            sections,
            _digest("authority"),
            _editorial_payload(sections, tuple((index, index) for index in range(31))),
        )


def test_editorial_timeline_rejects_group_over_current_reader_bound() -> None:
    sections = _editorial_sections(52)
    ranges = ((0, 40), *((index, index) for index in range(41, 52)))
    with pytest.raises(DerivedSemanticError, match="source-section limit"):
        validate_editorial_timeline_response(
            sections,
            _digest("reader-bound-authority"),
            _editorial_payload(sections, ranges),
        )


@pytest.mark.parametrize("group_count", [12, 30])
def test_editorial_timeline_accepts_real_scale_group_bounds(group_count: int) -> None:
    sections = _editorial_sections(425)
    ranges = tuple(
        (
            index * len(sections) // group_count,
            ((index + 1) * len(sections) // group_count) - 1,
        )
        for index in range(group_count)
    )

    timeline = validate_editorial_timeline_response(
        sections,
        _digest("real-scale-public-authority"),
        _editorial_payload(sections, ranges),
    )

    assert len(timeline.groups) == group_count
    assert sum(len(group.source_section_ids) for group in timeline.groups) == 425


def test_editorial_timeline_batches_real_scale_into_bounded_exact_slices() -> None:
    sections = _editorial_sections(425)
    authority = _digest("batched-real-scale-authority")

    batches = partition_editorial_timeline_sections(sections)
    group_counts = (3, 4, 5, 3, 4, 5)
    timelines = tuple(
        validate_editorial_timeline_response(
            batch,
            authority,
            _editorial_batch_payload(
                batch,
                tuple(
                    (
                        index * len(batch) // group_count,
                        ((index + 1) * len(batch) // group_count) - 1,
                    )
                    for index in range(group_count)
                ),
            ),
            group_count_bounds=(3, 5),
        )
        for batch, group_count in zip(batches, group_counts, strict=True)
    )
    groups = tuple(group for timeline in timelines for group in timeline.groups)
    batch_request = json.loads(
        build_editorial_timeline_request(
            batches[0],
            authority,
            group_count_bounds=(3, 5),
        )
    )
    rollup_request = json.loads(
        build_editorial_timeline_rollup_request(groups, authority)
    )
    timeline = combine_editorial_timeline_batches(
        sections,
        authority,
        timelines,
        canonical_json(
            {
                "title": "Whole public story",
                "summary": "A coherent overview of every chronological public story group.",
            }
        ),
    )

    assert len(batches) == 6
    assert {len(batch) for batch in batches} == {70, 71}
    assert len(timeline.groups) == 24
    assert batch_request["minimum_group_count"] == 3
    assert batch_request["maximum_group_count"] == 5
    assert batch_request["ordered_child_ids"] == [
        f"source:{index:03d}" for index in range(len(batches[0]))
    ]
    assert [child["id"] for child in batch_request["children"]] == batch_request[
        "ordered_child_ids"
    ]
    assert batches[0][0].section_id not in batch_request["ordered_child_ids"]
    assert "Prefer four groups" in batch_request["task"]
    assert "Never return fewer than three or more than five groups" in batch_request["task"]
    assert "Copy the supplied short child IDs exactly" in batch_request["task"]
    assert "more than 40 children" in batch_request["task"]
    assert "family roles" in batch_request["task"]
    assert "alternatives rather than one resolved chronology" in batch_request["task"]
    assert rollup_request["call_kind"] == "rollup_synthesis"
    assert rollup_request["schema_version"] == ROLLUP_SYNTHESIS_SCHEMA_VERSION
    assert "about 450-650 characters" in rollup_request["task"]
    assert "complete sentences" in rollup_request["task"]
    assert "sentence boundary" in rollup_request["task"]
    assert "family roles" in rollup_request["task"]
    assert "not as one resolved chronology" in rollup_request["task"]
    assert rollup_request["ordered_child_ids"] == [group.group_id for group in groups]
    assert tuple(
        source_id for group in timeline.groups for source_id in group.source_section_ids
    ) == tuple(section.section_id for section in sections)


def test_editorial_timeline_batch_maps_local_prose_spans_to_exact_membership() -> None:
    sections = _editorial_sections(71)
    ranges = ((0, 16), (17, 34), (35, 52), (53, 70))
    payload = json.loads(_editorial_batch_payload(sections, ranges))
    proposals = payload["sections"]
    assert isinstance(proposals, list)
    for index, (proposal, (first, last)) in enumerate(
        zip(proposals, ranges, strict=True), start=1
    ):
        proposal["title"] = f"Exact span {index}"
        proposal["summary"] = f"This prose describes only source children {first} through {last}."

    timeline = validate_editorial_timeline_response(
        sections,
        _digest("local-prose-membership-authority"),
        canonical_json(payload),
        group_count_bounds=(3, 5),
    )

    for index, (group, (first, last)) in enumerate(
        zip(timeline.groups, ranges, strict=True), start=1
    ):
        assert group.source_section_ids == tuple(
            section.section_id for section in sections[first : last + 1]
        )
        assert group.title == f"Exact span {index}"
        assert group.summary == f"This prose describes only source children {first} through {last}."


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("overlap", "contiguous and ordered"),
        ("gap", "contiguous and ordered"),
        ("foreign", "foreign source section"),
        ("oversized", "source-section limit"),
    ],
)
def test_editorial_timeline_batch_rejects_invalid_local_membership(
    mutation: str, message: str
) -> None:
    sections = _editorial_sections(71)
    ranges = (
        ((0, 40), (41, 50), (51, 60), (61, 70))
        if mutation == "oversized"
        else ((0, 16), (17, 34), (35, 52), (53, 70))
    )
    payload = json.loads(_editorial_batch_payload(sections, ranges))
    proposals = payload["sections"]
    assert isinstance(proposals, list)
    if mutation == "overlap":
        proposals[1]["first_event_id"] = "source:016"
    elif mutation == "gap":
        proposals[1]["first_event_id"] = "source:018"
    elif mutation == "foreign":
        proposals[0]["last_event_id"] = "source:999"

    with pytest.raises(DerivedSemanticError, match=message):
        validate_editorial_timeline_response(
            sections,
            _digest(f"invalid-local-membership-{mutation}"),
            canonical_json(payload),
            group_count_bounds=(3, 5),
        )


def test_editorial_batch_drops_only_a_600_character_incomplete_summary_suffix() -> None:
    sections = _editorial_sections(2)
    authority = _digest("clipped-editorial-summary-authority")
    complete = "Avery follows the known route and reaches the shared outcome."
    clipped = (complete + " The next description breaks mid" + ("w" * 600))[:600]
    payload = json.loads(_editorial_batch_payload(sections, ((0, 0), (1, 1))))
    payload["sections"][0]["summary"] = clipped
    packet = json.loads(
        build_editorial_timeline_request(
            sections,
            authority,
            group_count_bounds=(1, 2),
        )
    )

    timeline = validate_editorial_timeline_response(
        sections,
        authority,
        canonical_json(payload),
        group_count_bounds=(1, 2),
    )

    assert len(clipped) == 600
    assert timeline.groups[0].summary == complete
    assert "complete sentences" in packet["task"]
    assert "sentence boundary" in packet["task"]
    assert "600-character schema maximum" in packet["task"]


def test_editorial_batch_preserves_a_normal_complete_group_summary() -> None:
    sections = _editorial_sections(2)
    summary = "The route branches, develops through two outcomes, and rejoins at a shared scene."
    payload = json.loads(_editorial_batch_payload(sections, ((0, 0), (1, 1))))
    payload["sections"][0]["summary"] = summary

    timeline = validate_editorial_timeline_response(
        sections,
        _digest("complete-editorial-summary-authority"),
        canonical_json(payload),
        group_count_bounds=(1, 2),
    )

    assert timeline.groups[0].summary == summary


def test_editorial_batch_derives_its_discarded_overview_from_validated_groups() -> None:
    sections = _editorial_sections(2)
    payload = json.loads(_editorial_batch_payload(sections, ((0, 0), (1, 1))))
    wrapper = ("A discarded batch wrapper. " + ("w" * 600))[:599] + " "
    payload["summary"] = wrapper

    timeline = validate_editorial_timeline_response(
        sections,
        _digest("discarded-editorial-wrapper-authority"),
        canonical_json(payload),
        group_count_bounds=(1, 2),
    )

    assert len(wrapper) == 600
    assert timeline.overview == timeline.groups[0].summary


def test_unbatched_editorial_overview_remains_strict() -> None:
    sections = _editorial_sections(12)
    payload = json.loads(
        _editorial_payload(sections, tuple((index, index) for index in range(12)))
    )
    payload["summary"] = str(payload["summary"]) + " "

    with pytest.raises(DerivedSemanticError, match="editorial timeline overview"):
        validate_editorial_timeline_response(
            sections,
            _digest("strict-editorial-overview-authority"),
            canonical_json(payload),
        )


def test_editorial_batch_rejects_a_group_without_one_complete_sentence() -> None:
    sections = _editorial_sections(2)
    payload = json.loads(_editorial_batch_payload(sections, ((0, 0), (1, 1))))
    payload["sections"][0]["summary"] = "A clipped fragment without any complete sentence"

    with pytest.raises(DerivedSemanticError, match="complete sentence"):
        validate_editorial_timeline_response(
            sections,
            _digest("fragment-only-editorial-summary-authority"),
            canonical_json(payload),
            group_count_bounds=(1, 2),
        )


def test_editorial_timeline_batches_reject_global_reordering() -> None:
    sections = _editorial_sections(425)
    authority = _digest("reordered-batch-authority")
    batches = partition_editorial_timeline_sections(sections)
    timelines = [
        validate_editorial_timeline_response(
            batch,
            authority,
            _editorial_batch_payload(
                batch,
                tuple(
                    (
                        index * len(batch) // 3,
                        ((index + 1) * len(batch) // 3) - 1,
                    )
                    for index in range(3)
                ),
            ),
            group_count_bounds=(3, 5),
        )
        for batch in batches
    ]
    timelines[0], timelines[1] = timelines[1], timelines[0]

    with pytest.raises(DerivedSemanticError, match="coverage or chronology"):
        combine_editorial_timeline_batches(
            sections,
            authority,
            timelines,
            canonical_json({"title": "Story", "summary": "Overview"}),
        )


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
    assert result.sections[0].title.startswith(semantic.events[0].title)
    assert semantic.events[0].summary in result.sections[0].summary
    assert result.overview is not None
    assert result.overview.origin is SemanticOrigin.STRUCTURAL
    assert semantic.events[0].summary in result.overview.summary
    assert all(job.call_kind is DerivedCallKind.SECTION_SYNTHESIS for job in result.section_jobs)
    assert all(job.call_kind is DerivedCallKind.ROLLUP_SYNTHESIS for job in result.rollup_jobs)


def test_fixed_membership_rollup_upper_bound_is_finite_for_large_route() -> None:
    plan = _plan(route_events=30, common_events=1)
    derived = build_derived_semantic_plan(plan, _digest("authority-public-c1"))
    assert derived.ceilings.route_reduction_calls == 2
    assert derived.ceilings.route_summary_calls == 1
    assert derived.ceilings.final_overview_calls == 1
    assert derived.ceilings.rollup_synthesis_calls == 4


def _generation_inputs(
    generation_id: str,
) -> tuple[StoryChunkPlan, object, object, str]:
    plan = _plan()
    semantic = assemble_semantic_corridors(
        plan,
        _accepted_assembly(plan, singleton_events=True),
    )
    authority_identity = _digest("authority-generation-binding")
    semantic_plan = build_derived_semantic_plan(plan, authority_identity)
    derived = assemble_derived_semantics(semantic_plan, semantic, generation_id)
    return plan, semantic, derived, authority_identity


def test_generation_build_rejects_cross_plan_authority_and_candidate_binding() -> None:
    generation_id = "generation:bound-public"
    plan, semantic, derived, authority_identity = _generation_inputs(generation_id)
    artifact = build_generation_artifact(
        generation_id=generation_id,
        run_id="run-bound-public",
        plan_id="workflow-plan-bound-public",
        authority_identity=authority_identity,
        semantic_assembly=semantic,
        derived=derived,
        kind=GenerationKind.COMPLETE,
    )
    assert artifact.story_chunk_plan_identity == plan.identity

    with pytest.raises(ValueError, match="candidate generation"):
        build_generation_artifact(
            generation_id="generation:foreign-candidate",
            run_id="run-bound-public",
            plan_id="workflow-plan-bound-public",
            authority_identity=authority_identity,
            semantic_assembly=semantic,
            derived=derived,
            kind=GenerationKind.COMPLETE,
        )
    with pytest.raises(ValueError, match="foreign semantic-plan authority"):
        build_generation_artifact(
            generation_id=generation_id,
            run_id="run-bound-public",
            plan_id="workflow-plan-bound-public",
            authority_identity=_digest("foreign-authority"),
            semantic_assembly=semantic,
            derived=derived,
            kind=GenerationKind.COMPLETE,
        )
    foreign_plan = replace(
        derived.semantic_plan,
        story_chunk_plan_identity=_digest("foreign-story-chunk-plan"),
    )
    cross_plan = replace(
        derived,
        semantic_plan=foreign_plan,
        semantic_plan_identity=foreign_plan.semantic_plan_identity,
    )
    with pytest.raises(ValueError, match="foreign semantic-plan authority"):
        build_generation_artifact(
            generation_id=generation_id,
            run_id="run-bound-public",
            plan_id="workflow-plan-bound-public",
            authority_identity=authority_identity,
            semantic_assembly=semantic,
            derived=cross_plan,
            kind=GenerationKind.COMPLETE,
        )


@pytest.mark.parametrize("mutation", ["missing", "foreign", "duplicate", "reordered"])
def test_generation_build_rejects_invalid_derived_event_coverage(mutation: str) -> None:
    generation_id = "generation:coverage-public"
    _, semantic, derived, authority_identity = _generation_inputs(generation_id)
    result = derived.corridor_results[0]
    section = result.sections[0]
    event_ids = section.event_ids
    if mutation == "missing":
        mutated_sections = (replace(section, event_ids=event_ids[:-1]),)
    elif mutation == "foreign":
        mutated_sections = (replace(section, event_ids=("event:foreign", *event_ids[1:])),)
    elif mutation == "duplicate":
        mutated_sections = (
            replace(section, section_id="section:duplicate:a", event_ids=(event_ids[0],)),
            replace(section, section_id="section:duplicate:b", event_ids=event_ids),
        )
    else:
        mutated_sections = (replace(section, event_ids=tuple(reversed(event_ids))),)
    invalid_result = replace(result, sections=mutated_sections)
    invalid = replace(
        derived,
        corridor_results=(invalid_result, *derived.corridor_results[1:]),
    )
    with pytest.raises(ValueError, match="exact existing corridor events"):
        build_generation_artifact(
            generation_id=generation_id,
            run_id="run-coverage-public",
            plan_id="workflow-plan-coverage-public",
            authority_identity=authority_identity,
            semantic_assembly=semantic,
            derived=invalid,
            kind=GenerationKind.COMPLETE,
        )


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
    trust_empty_baseline: bool = False,
    run_id: str = "run-public",
    plan_id: str = "plan-public",
    authority_identity: str | None = None,
    source_identity: str | None = None,
) -> GenerationArtifact:
    section = _section()
    fact = PathFact(PathFactKind.ARM, "arm:public", ("section:public",))
    new_facts = ()
    baseline_facts: tuple[PathFact, ...] | None = None
    if baseline is not None:
        baseline_facts = () if trust_empty_baseline else (fact,)
        new_facts = derive_new_path_facts(
            (fact,), PathFactSnapshot(baseline, baseline_facts)
        )
    artifact_values: dict[str, object] = {
        "generation_id": generation_id,
        "run_id": run_id,
        "plan_id": plan_id,
        "authority_identity": (
            _digest("authority-publication")
            if authority_identity is None
            else authority_identity
        ),
        "story_chunk_plan_identity": _digest("chunk-plan-publication"),
        "source_identity": (
            _digest("source-publication") if source_identity is None else source_identity
        ),
        "coverage_hash": _digest("coverage-publication"),
        "kind": kind,
        "state": (
            GenerationBuildState.COMPLETE
            if kind is GenerationKind.COMPLETE
            else GenerationBuildState.STRUCTURAL
            if kind is GenerationKind.STRUCTURAL
            else GenerationBuildState.BUILDING
        ),
        "title": "Public story",
        "overview": "A public synthetic overview.",
        "sections": (section,),
        "path_facts": (fact,),
        "baseline_generation_id": baseline,
        "new_path_facts": new_facts,
    }
    if "baseline_path_facts" in GenerationArtifact.__dataclass_fields__:
        artifact_values["baseline_path_facts"] = baseline_facts
    return GenerationArtifact(**artifact_values)


class _MemoryGenerationRepository:
    """C1-local generation primitive fake; Track B supplies the durable adapter."""

    def __init__(self) -> None:
        self._generations: dict[str, GenerationDescriptor] = {}
        self._pointers = GenerationPointers(None, None, 0)
        self._run_authorities: dict[str, tuple[str, str]] = {}
        self._cancelled_runs: set[str] = set()
        self.before_activate_cas: Callable[[], None] | None = None
        self.before_publish_cas: Callable[[], None] | None = None

    def create_generation(self, generation: GenerationDescriptor) -> None:
        run_authority = (generation.plan_id, generation.authority_identity)
        existing_run = self._run_authorities.setdefault(generation.run_id, run_authority)
        if existing_run != run_authority:
            raise ValueError("generation run plan and authority are immutable")
        existing = self._generations.get(generation.generation_id)
        if existing is not None and existing != generation:
            raise ValueError("generation identity is immutable")
        self._generations[generation.generation_id] = generation

    def load_generation(self, generation_id: str) -> GenerationDescriptor | None:
        return self._generations.get(generation_id)

    def is_run_publishable(
        self,
        run_id: str,
        plan_id: str,
        authority_identity: str,
    ) -> bool:
        expected = self._run_authorities.get(run_id)
        return run_id not in self._cancelled_runs and (
            expected is None or expected == (plan_id, authority_identity)
        )

    def cancel_run(self, run_id: str) -> None:
        self._cancelled_runs.add(run_id)

    def _require_publishable_generation(self, generation_id: str) -> GenerationDescriptor:
        generation = self._generations[generation_id]
        if not self.is_run_publishable(
            generation.run_id,
            generation.plan_id,
            generation.authority_identity,
        ):
            raise PublicationConflictError("generation run is not publishable")
        return generation

    @staticmethod
    def _lineage(generation: GenerationDescriptor) -> tuple[object, ...]:
        descriptor = cast(dict[str, object], generation.descriptor)
        return (
            generation.run_id,
            generation.plan_id,
            generation.authority_identity,
            descriptor["story_chunk_plan_identity"],
            descriptor["source_identity"],
            descriptor["coverage_hash"],
            descriptor["baseline_generation_id"],
        )

    def set_active_generation(
        self,
        generation_id: str,
        *,
        expected_active_generation_id: str | None,
        expected_complete_generation_id: str | object | None = _POINTER_EXPECTATION_UNSET,
    ) -> GenerationPointers:
        if self.before_activate_cas is not None:
            hook, self.before_activate_cas = self.before_activate_cas, None
            hook()
        generation = self._require_publishable_generation(generation_id)
        if (
            generation.kind is GenerationKind.COMPLETE
            and expected_complete_generation_id is not _POINTER_EXPECTATION_UNSET
        ):
            raise PublicationConflictError("complete generation cannot activate progressively")
        if (
            expected_complete_generation_id is not _POINTER_EXPECTATION_UNSET
            and self._pointers.current_complete_generation
            != expected_complete_generation_id
        ):
            raise PublicationConflictError("complete generation pointer changed")
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
        expected_complete_generation_id: str | object | None = _POINTER_EXPECTATION_UNSET,
        fault: Callable[[str], None] | None = None,
    ) -> GenerationPointers:
        if fault is not None:
            fault(FAULT_BEFORE_GENERATION_PUBLICATION)
        if self.before_publish_cas is not None:
            hook, self.before_publish_cas = self.before_publish_cas, None
            hook()
        descriptor = self._require_publishable_generation(generation_id)
        if (
            expected_complete_generation_id is not _POINTER_EXPECTATION_UNSET
            and self._pointers.current_complete_generation
            != expected_complete_generation_id
        ):
            raise PublicationConflictError("complete generation pointer changed")
        if self._pointers.active_build_generation != expected_active_generation_id:
            raise PublicationConflictError("active generation pointer changed")
        if descriptor.kind is not GenerationKind.COMPLETE:
            raise ValueError("only complete generations may publish")
        active = self._require_publishable_generation(expected_active_generation_id)
        if self._lineage(active) != self._lineage(descriptor):
            raise PublicationConflictError("active and complete generation lineage differ")
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
        _artifact(
            "generation:build:2",
            GenerationKind.CANDIDATE,
            baseline="generation:complete:1",
        ),
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
    with pytest.raises(PublicationConflictError, match="changed active run"):
        publisher.publish_complete(
            _artifact(
                "generation:complete:foreign-source",
                GenerationKind.COMPLETE,
                baseline="generation:complete:1",
                source_identity=_digest("source-publication-foreign"),
            ),
            expected_active_generation_id="generation:build:2",
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


def test_publication_rejects_same_id_empty_substitute_baseline_facts() -> None:
    repository = _publication_repository()
    publisher = AtomicGenerationPublisher(repository)
    publisher.activate_progressive(
        _artifact("generation:baseline-build:1", GenerationKind.STRUCTURAL),
        expected_active_generation_id=None,
    )
    publisher.publish_complete(
        _artifact("generation:baseline-complete:1", GenerationKind.COMPLETE),
        expected_active_generation_id="generation:baseline-build:1",
    )
    publisher.activate_progressive(
        _artifact(
            "generation:baseline-build:2",
            GenerationKind.CANDIDATE,
            baseline="generation:baseline-complete:1",
        ),
        expected_active_generation_id=None,
    )
    substituted = _artifact(
        "generation:baseline-complete:2",
        GenerationKind.COMPLETE,
        baseline="generation:baseline-complete:1",
        trust_empty_baseline=True,
    )
    assert substituted.new_path_facts[0].fact_id == "arm:public"
    with pytest.raises(PublicationConflictError, match="baseline path facts differ"):
        publisher.publish_complete(
            substituted,
            expected_active_generation_id="generation:baseline-build:2",
        )
    pointers = repository.generation_pointers()
    assert pointers.current_complete_generation == "generation:baseline-complete:1"
    assert pointers.active_build_generation == "generation:baseline-build:2"
    assert repository.load_generation("generation:baseline-complete:2") is None


def test_stale_and_cancelled_activation_cannot_advance_dual_pointers() -> None:
    repository = _publication_repository()
    publisher = AtomicGenerationPublisher(repository)
    stale = _artifact(
        "generation:stale-build",
        GenerationKind.CANDIDATE,
        run_id="run-stale",
        authority_identity=_digest("authority-stale"),
        source_identity=_digest("source-stale"),
    )
    publisher.activate_progressive(
        _artifact("generation:new-build", GenerationKind.STRUCTURAL),
        expected_active_generation_id=None,
    )
    publisher.publish_complete(
        _artifact("generation:new-complete", GenerationKind.COMPLETE),
        expected_active_generation_id="generation:new-build",
    )
    accepted = repository.generation_pointers()
    with pytest.raises(PublicationConflictError, match="immediately prior accepted"):
        publisher.activate_progressive(stale, expected_active_generation_id=None)
    assert repository.generation_pointers() == accepted

    cancelled = _artifact(
        "generation:cancel-race-build",
        GenerationKind.CANDIDATE,
        baseline="generation:new-complete",
        run_id="run-cancel-race",
        plan_id="plan-cancel-race",
        authority_identity=_digest("authority-cancel-race"),
        source_identity=_digest("source-cancel-race"),
    )
    repository.before_activate_cas = lambda: repository.cancel_run("run-cancel-race")
    with pytest.raises(PublicationConflictError, match="not publishable"):
        publisher.activate_progressive(cancelled, expected_active_generation_id=None)
    assert repository.generation_pointers() == accepted


def test_publish_cas_rechecks_cancellation_without_pointer_mutation() -> None:
    repository = _publication_repository()
    publisher = AtomicGenerationPublisher(repository)
    publisher.activate_progressive(
        _artifact("generation:publish-build:1", GenerationKind.STRUCTURAL),
        expected_active_generation_id=None,
    )
    publisher.publish_complete(
        _artifact("generation:publish-complete:1", GenerationKind.COMPLETE),
        expected_active_generation_id="generation:publish-build:1",
    )
    build = _artifact(
        "generation:publish-build:2",
        GenerationKind.CANDIDATE,
        baseline="generation:publish-complete:1",
        run_id="run-publish-race",
        plan_id="plan-publish-race",
        authority_identity=_digest("authority-publish-race"),
        source_identity=_digest("source-publish-race"),
    )
    publisher.activate_progressive(build, expected_active_generation_id=None)
    before = repository.generation_pointers()
    complete = _artifact(
        "generation:publish-complete:2",
        GenerationKind.COMPLETE,
        baseline="generation:publish-complete:1",
        run_id="run-publish-race",
        plan_id="plan-publish-race",
        authority_identity=_digest("authority-publish-race"),
        source_identity=_digest("source-publish-race"),
    )
    repository.before_publish_cas = lambda: repository.cancel_run("run-publish-race")
    with pytest.raises(PublicationConflictError, match="not publishable"):
        publisher.publish_complete(
            complete,
            expected_active_generation_id="generation:publish-build:2",
        )
    assert repository.generation_pointers() == before


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
