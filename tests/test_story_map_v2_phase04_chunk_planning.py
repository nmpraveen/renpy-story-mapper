"""Failing-first public-synthetic coverage for Phase 04 frozen chunk planning."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Never, cast

import pytest

from renpy_story_mapper.story_map_v2.phase04_assembly import (
    ChunkProseResult,
    FrozenAssemblyError,
    assemble_frozen_chunk_plan,
)
from renpy_story_mapper.story_map_v2.phase04_chunk_plan import (
    ChoiceArmBoundary,
    ChunkPlanningChoice,
    ChunkPlanningPlacement,
    ChunkPlanningProjection,
    ChunkPlanningScope,
    ChunkProfileKind,
    FrozenPlanMismatch,
    StoryChunkPlan,
    deserialize_story_chunk_plan,
    plan_story_chunks,
    serialize_chunk_request,
    serialize_story_chunk_plan,
)

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "story_map_v2" / "phase04_chunk_planning.json"
)


def _fixture_cases() -> dict[str, dict[str, object]]:
    payload = cast(dict[str, object], json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))
    assert payload["schema"] == "story-map-v2-phase04-public-chunk-fixture-v1"
    return cast(dict[str, dict[str, object]], payload["cases"])


def _story_text(index: int, raw_tokens: int) -> str:
    return f"{index}: synthetic scene {index} " + ("x" * (raw_tokens * 4)) + "\n"


def _placement(
    scope_id: str,
    index: int,
    raw_tokens: int,
    *,
    arms: tuple[ChoiceArmBoundary, ...] = (),
    flags: tuple[str, ...] = (),
) -> ChunkPlanningPlacement:
    return ChunkPlanningPlacement(
        placement_id=f"{scope_id}:placement:{index:02d}",
        scope_id=scope_id,
        scene_id=f"scene:{scope_id}:{index:02d}",
        relative_path="scripts/public_synthetic.rpy",
        start_line=index * 10,
        end_line=index * 10 + 9,
        raw_text=_story_text(index, raw_tokens),
        raw_tokens=raw_tokens,
        choice_arms=arms,
        structural_flags=flags,
    )


def _scope(
    case: dict[str, object],
    ordinal: int,
    *,
    placements: tuple[ChunkPlanningPlacement, ...] | None = None,
) -> ChunkPlanningScope:
    scope_id = cast(str, case["scope_id"])
    token_counts = cast(list[int], case["raw_tokens"])
    return ChunkPlanningScope(
        scope_id=scope_id,
        ordinal=ordinal,
        parent_scope_id=cast(str | None, case["parent_scope_id"]),
        persistent_lane=cast(bool, case["persistent_lane"]),
        branch_heavy=cast(bool, case["branch_heavy"]),
        placements=placements
        if placements is not None
        else tuple(
            _placement(scope_id, index, raw_tokens)
            for index, raw_tokens in enumerate(token_counts, start=1)
        ),
    )


def _choice(choice_key: str, *, nested_under: str | None = None) -> ChunkPlanningChoice:
    mechanics = {
        "choice_key": choice_key,
        "caption": f"Synthetic {choice_key}",
        "parent_choice_key": nested_under,
        "arms": [
            {"order": 1, "caption": "First", "destination": f"{choice_key}:first"},
            {"order": 2, "caption": "Second", "destination": f"{choice_key}:second"},
        ],
    }
    return ChunkPlanningChoice(
        choice_key=choice_key,
        canonical_mechanics=json.dumps(
            mechanics, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
        arm_orders=(1, 2),
    )


def _projection(
    scopes: tuple[ChunkPlanningScope, ...],
    *,
    choices: tuple[ChunkPlanningChoice, ...] = (),
) -> ChunkPlanningProjection:
    return ChunkPlanningProjection(
        story_plan_identity="story-plan-public-synthetic-v1",
        source_identity="source-public-synthetic-v1",
        scopes=scopes,
        choices=choices,
    )


def test_long_persistent_lane_chunks_independently_at_normal_target() -> None:
    cases = _fixture_cases()
    spine_case = {
        "scope_id": "scope:spine",
        "parent_scope_id": None,
        "persistent_lane": False,
        "branch_heavy": False,
        "raw_tokens": [4000, 4000],
    }
    projection = _projection(
        (_scope(spine_case, 1), _scope(cases["long_persistent_lane"], 2))
    )

    plan = plan_story_chunks(projection)

    assert plan.scope_ids == ("scope:spine", "scope:persistent:ridge")
    assert [chunk.scope_id for chunk in plan.chunks] == [
        "scope:spine",
        "scope:persistent:ridge",
        "scope:persistent:ridge",
    ]
    assert [chunk.raw_tokens for chunk in plan.chunks] == [8000, 8000, 6500]
    assert all(chunk.profile is ChunkProfileKind.NORMAL for chunk in plan.chunks)
    assert plan.covered_placement_ids == tuple(
        placement.placement_id for scope in projection.scopes for placement in scope.placements
    )


def test_local_and_nested_choices_segment_at_exact_scene_boundaries() -> None:
    case = _fixture_cases()["local_nested_choices"]
    scope_id = cast(str, case["scope_id"])
    tokens = cast(list[int], case["raw_tokens"])
    root_arm_1 = ChoiceArmBoundary("choice:root", 1, "local", 0)
    root_arm_2 = ChoiceArmBoundary("choice:root", 2, "local", 0)
    nested_arm_1 = ChoiceArmBoundary("choice:nested", 1, "nested", 1)
    nested_arm_2 = ChoiceArmBoundary("choice:nested", 2, "nested", 1)
    placements = (
        _placement(scope_id, 1, tokens[0], arms=(root_arm_1,)),
        _placement(scope_id, 2, tokens[1], arms=(root_arm_1, nested_arm_1)),
        _placement(scope_id, 3, tokens[2], arms=(root_arm_1, nested_arm_2)),
        _placement(scope_id, 4, tokens[3], arms=(root_arm_2,)),
    )
    projection = _projection(
        (_scope(case, 1, placements=placements),),
        choices=(
            _choice("choice:root"),
            _choice("choice:nested", nested_under="choice:root"),
        ),
    )

    plan = plan_story_chunks(projection)

    assert [chunk.raw_tokens for chunk in plan.chunks] == [5000, 5000]
    assert all(chunk.profile is ChunkProfileKind.BRANCH_HEAVY for chunk in plan.chunks)
    assert [parent.choice_key for parent in plan.choice_parents] == [
        "choice:root",
        "choice:nested",
    ]
    root_segments = [
        segment
        for chunk in plan.chunks
        for segment in chunk.choice_segments
        if segment.choice_key == "choice:root"
    ]
    nested_segments = [
        segment
        for chunk in plan.chunks
        for segment in chunk.choice_segments
        if segment.choice_key == "choice:nested"
    ]
    assert [(item.segment_ordinal, item.segment_count) for item in root_segments] == [
        (1, 2),
        (2, 2),
    ]
    assert [item.arm_orders for item in root_segments] == [(1,), (1, 2)]
    assert [(item.segment_ordinal, item.segment_count) for item in nested_segments] == [
        (1, 2),
        (2, 2),
    ]
    assert [item.arm_orders for item in nested_segments] == [(1,), (2,)]
    assert [placement for chunk in plan.chunks for placement in chunk.placement_ids] == [
        item.placement_id for item in placements
    ]


def test_oversized_persistent_choice_segments_by_exact_arm_scene_boundaries() -> None:
    case = _fixture_cases()["persistent_choice"]
    scope_id = cast(str, case["scope_id"])
    tokens = cast(list[int], case["raw_tokens"])
    placements = tuple(
        _placement(
            scope_id,
            index,
            raw_tokens,
            arms=(
                ChoiceArmBoundary(
                    "choice:persistent",
                    1 if index <= 3 else 2,
                    "persistent",
                    0,
                ),
            ),
        )
        for index, raw_tokens in enumerate(tokens, start=1)
    )
    projection = _projection(
        (_scope(case, 1, placements=placements),),
        choices=(_choice("choice:persistent"),),
    )

    plan = plan_story_chunks(projection)

    assert [chunk.raw_tokens for chunk in plan.chunks] == [5000, 5000, 5000]
    assert [
        segment.arm_orders
        for chunk in plan.chunks
        for segment in chunk.choice_segments
    ] == [(1,), (1, 2), (2,)]
    assert [
        segment.segment_ordinal
        for chunk in plan.chunks
        for segment in chunk.choice_segments
    ] == [1, 2, 3]
    assert all(
        segment.boundary_kinds == ("persistent",)
        for chunk in plan.chunks
        for segment in chunk.choice_segments
    )
    assert len(plan.choice_parents) == 1
    assert all(
        chunk.complete_request_tokens is not None
        and chunk.complete_request_tokens <= 10_700
        for chunk in plan.chunks
    )


def test_complete_serialized_requests_stay_under_hard_ceiling_without_omission() -> None:
    case = _fixture_cases()["oversized_material"]
    projection = _projection((_scope(case, 1),))

    plan = plan_story_chunks(projection)

    assert sum(chunk.raw_tokens for chunk in plan.chunks) == 18_000
    assert len(plan.chunks) >= 3
    assert all(not chunk.structural_fallback_only for chunk in plan.chunks)
    assert all(
        chunk.complete_request_tokens is not None
        and chunk.complete_request_tokens <= plan.maximum_request_tokens == 10_700
        for chunk in plan.chunks
    )
    for chunk in plan.chunks:
        request = serialize_chunk_request(plan, chunk.chunk_id, projection)
        assert len(request) == chunk.serialized_request_bytes

    assert len(plan.covered_placement_ids) == len(set(plan.covered_placement_ids))
    changed = replace(
        projection.scopes[0].placements[0],
        raw_text=projection.scopes[0].placements[0].raw_text + "1: changed\n",
    )
    mutated_scope = replace(
        projection.scopes[0],
        placements=(changed, *projection.scopes[0].placements[1:]),
    )
    with pytest.raises(FrozenPlanMismatch, match="rendered input"):
        serialize_chunk_request(
            plan,
            plan.chunks[0].chunk_id,
            replace(projection, scopes=(mutated_scope,)),
        )


def test_atomic_request_over_ceiling_is_provider_free_structural_fallback() -> None:
    case = _fixture_cases()["atomic_oversized"]
    projection = _projection((_scope(case, 1),))

    plan = plan_story_chunks(projection)

    assert len(plan.chunks) == 1
    chunk = plan.chunks[0]
    assert chunk.structural_fallback_only
    assert chunk.request_hash is None
    assert chunk.complete_request_tokens is None
    assert chunk.structural_fallback_reason == "atomic_scene_request_exceeds_hard_ceiling"
    with pytest.raises(FrozenPlanMismatch, match="structural-fallback-only"):
        serialize_chunk_request(plan, chunk.chunk_id, projection)


def test_structural_fallback_preserves_loops_endings_and_unresolved_arms() -> None:
    case = _fixture_cases()["structural_edges"]
    scope_id = cast(str, case["scope_id"])
    tokens = cast(list[int], case["raw_tokens"])
    flags = cast(list[str], case["flags"])
    placements = tuple(
        _placement(
            scope_id,
            index,
            raw_tokens,
            arms=(ChoiceArmBoundary("choice:unresolved", index if index < 3 else 2, "local", 0),),
            flags=(flags[index - 1],),
        )
        for index, raw_tokens in enumerate(tokens, start=1)
    )
    projection = _projection(
        (_scope(case, 1, placements=placements),),
        choices=(_choice("choice:unresolved"),),
    )
    plan = plan_story_chunks(projection)

    assembled = assemble_frozen_chunk_plan(plan, ())

    assert len(assembled.slots) == len(plan.chunks)
    assert all(slot.prose is None and slot.fallback is not None for slot in assembled.slots)
    fallbacks = tuple(slot.fallback for slot in assembled.slots)
    assert all(fallback is not None for fallback in fallbacks)
    retained_fallbacks = tuple(fallback for fallback in fallbacks if fallback is not None)
    assert {
        flag for fallback in retained_fallbacks for flag in fallback.structural_flags
    } == {"loop", "ending", "unresolved_arm"}
    assert [
        placement_id
        for fallback in retained_fallbacks
        for placement_id in fallback.placement_ids
    ] == list(plan.covered_placement_ids)


def test_round_trip_and_assembly_consume_exact_plan_without_replanning() -> None:
    projection = _projection((_scope(_fixture_cases()["oversized_material"], 1),))
    plan = plan_story_chunks(projection)
    frozen_bytes = serialize_story_chunk_plan(plan)
    reopened = deserialize_story_chunk_plan(frozen_bytes)
    assert reopened == plan
    assert serialize_story_chunk_plan(reopened) == frozen_bytes

    first = plan.chunks[0]
    assert first.request_hash is not None
    result = ChunkProseResult(
        story_chunk_plan_identity=plan.identity,
        chunk_id=first.chunk_id,
        request_hash=first.request_hash,
        title="Synthetic opening",
        overview="The public-synthetic story begins.",
    )
    trap_calls = 0

    def replanning_trap() -> Never:
        nonlocal trap_calls
        trap_calls += 1
        raise AssertionError("assembly attempted forbidden replanning")

    assembled = assemble_frozen_chunk_plan(
        reopened,
        (result,),
        replanning_trap=replanning_trap,
    )

    assert trap_calls == 0
    assert assembled.story_chunk_plan_identity == plan.identity
    assert assembled.slots[0].prose == result
    assert all(slot.fallback is not None for slot in assembled.slots[1:])

    tampered = json.loads(frozen_bytes)
    tampered["unexpected"] = "not part of the frozen contract"
    tampered_bytes = json.dumps(
        tampered, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    with pytest.raises(ValueError, match="unexpected fields"):
        deserialize_story_chunk_plan(tampered_bytes)


def test_plan_and_assembly_reject_duplicate_or_foreign_chunk_results() -> None:
    plan = plan_story_chunks(
        _projection((_scope(_fixture_cases()["oversized_material"], 1),))
    )
    first = plan.chunks[0]
    assert first.request_hash is not None
    result = ChunkProseResult(
        story_chunk_plan_identity=plan.identity,
        chunk_id=first.chunk_id,
        request_hash=first.request_hash,
        title="Synthetic",
        overview="Synthetic.",
    )
    with pytest.raises(FrozenAssemblyError, match="duplicate"):
        assemble_frozen_chunk_plan(plan, (result, result))
    with pytest.raises(FrozenAssemblyError, match="plan identity"):
        assemble_frozen_chunk_plan(
            plan,
            (replace(result, story_chunk_plan_identity="foreign-plan"),),
        )

    duplicate_coverage = replace(
        plan.chunks[1],
        placement_ids=(plan.chunks[0].placement_ids[0], *plan.chunks[1].placement_ids),
    )
    with pytest.raises(ValueError, match="exactly once"):
        replace(plan, chunks=(plan.chunks[0], duplicate_coverage, *plan.chunks[2:]))


def test_fixture_is_public_synthetic_and_contains_all_required_shapes() -> None:
    text = FIXTURE_PATH.read_text(encoding="utf-8")
    assert "MsDenvers" not in text
    assert set(_fixture_cases()) == {
        "long_persistent_lane",
        "local_nested_choices",
        "persistent_choice",
        "oversized_material",
        "structural_edges",
        "atomic_oversized",
    }
    assert StoryChunkPlan.__module__.endswith("phase04_chunk_plan")
