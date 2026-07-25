from __future__ import annotations

import pytest

from renpy_story_mapper.story_map_v2.assembly import assemble_core
from renpy_story_mapper.story_map_v2.contracts import (
    ArmLineageStep,
    BranchSummary,
    ChunkStatus,
    CoreChunk,
    MapperEvent,
    MapperResponse,
    ProviderOrigin,
    Reachability,
)
from renpy_story_mapper.story_map_v2.overlay import MapperValidationError, validate_and_overlay
from renpy_story_mapper.story_map_v2.planner import ChunkPlanningError, plan_chunks
from story_map_v2_fixtures import choice, scope, span

CHOICE_KEY = "scripts/day.rpy:10"


def test_planner_keeps_menu_arms_and_local_rejoin_together_below_ceiling() -> None:
    fixture = choice()
    spans = (
        span("menu", 10, 10, 1_000, choice_keys=(CHOICE_KEY,)),
        span(
            "arm-1",
            11,
            19,
            3_000,
            lineage=(ArmLineageStep(CHOICE_KEY, 1),),
            choice_keys=(CHOICE_KEY,),
        ),
        span(
            "arm-2",
            20,
            29,
            3_000,
            lineage=(ArmLineageStep(CHOICE_KEY, 2),),
            choice_keys=(CHOICE_KEY,),
        ),
        span("rejoin", 40, 45, 3_000, choice_keys=(CHOICE_KEY,), shared=True, boundary=True),
    )
    chunks = plan_chunks(scope(spans, choices=(fixture,)))
    assert len(chunks) == 1
    assert chunks[0].raw_tokens == 10_000
    assert chunks[0].choice_keys == (CHOICE_KEY,)


def test_planner_prefers_natural_boundary_and_branch_heavy_target() -> None:
    spans = (
        span("a", 1, 9, 3_000, boundary=True),
        span("b", 10, 19, 3_000, boundary=True),
        span("c", 20, 29, 3_000, boundary=True),
    )
    chunks = plan_chunks(scope(spans))
    assert [chunk.span_keys for chunk in chunks] == [("a", "b"), ("c",)]


def test_planner_fails_an_indivisible_cluster_above_validated_ceiling() -> None:
    fixture = choice()
    spans = (
        span("menu", 10, 10, 1_000, choice_keys=(CHOICE_KEY,)),
        span(
            "arm-1",
            11,
            19,
            5_000,
            lineage=(ArmLineageStep(CHOICE_KEY, 1),),
            choice_keys=(CHOICE_KEY,),
        ),
        span(
            "arm-2",
            20,
            29,
            5_000,
            lineage=(ArmLineageStep(CHOICE_KEY, 2),),
            choice_keys=(CHOICE_KEY,),
        ),
        span("rejoin", 40, 45, 1_000, choice_keys=(CHOICE_KEY,), shared=True),
    )
    with pytest.raises(ChunkPlanningError, match="ceiling"):
        plan_chunks(scope(spans, choices=(fixture,)))


def test_overlay_rejects_invented_choice_keys() -> None:
    fixture = scope((span("story", 1, 20, 100),), choices=(choice(),))
    chunk = plan_chunks(fixture)[0]
    response = MapperResponse(None, None, (), (BranchSummary("invented", 1, "Outcome"),))
    with pytest.raises(MapperValidationError, match="choice"):
        validate_and_overlay(fixture, chunk, response, origin=ProviderOrigin.CLOUD)


def test_overlay_uses_common_lineage_for_cross_arm_event_and_python_caption() -> None:
    fixture = choice()
    spans = (
        span(
            "arm-1",
            11,
            19,
            100,
            lineage=(ArmLineageStep(CHOICE_KEY, 1),),
            choice_keys=(CHOICE_KEY,),
        ),
        span(
            "arm-2",
            20,
            29,
            100,
            lineage=(ArmLineageStep(CHOICE_KEY, 2),),
            choice_keys=(CHOICE_KEY,),
        ),
    )
    mapped = MapperResponse(
        None,
        None,
        (MapperEvent("Both paths", "Crosses siblings", "scripts/day.rpy", 11, 29),),
        (BranchSummary(CHOICE_KEY, 1, 'The mapper writes "Take the ridge".'),),
    )
    planned = plan_chunks(scope(spans, choices=(fixture,)))[0]
    core = validate_and_overlay(
        scope(spans, choices=(fixture,)), planned, mapped, origin=ProviderOrigin.CLOUD
    )

    assert core.events[0].anchor.arm_lineage == ()
    assert core.events[0].reachability is Reachability.UNRESOLVED
    assert core.branch_outcomes[0].caption == "Take the ridge"


def test_nested_branch_event_anchor_comes_only_from_python_lineage() -> None:
    outer = ArmLineageStep("scripts/day.rpy:5", 2)
    nested_choice = choice(parent=(outer,))
    lineage = (outer, ArmLineageStep(CHOICE_KEY, 1))
    fixture = scope(
        (span("nested", 11, 19, 100, lineage=lineage, choice_keys=(CHOICE_KEY,)),),
        choices=(nested_choice,),
    )
    chunk = plan_chunks(fixture)[0]
    mapped = MapperResponse(
        None,
        None,
        (MapperEvent("Ridge", "They climb", "scripts/day.rpy", 11, 19),),
        (BranchSummary(CHOICE_KEY, 1, "They climb"),),
    )
    core = validate_and_overlay(fixture, chunk, mapped, origin=ProviderOrigin.CLOUD)
    assert core.events[0].anchor.arm_lineage == lineage
    assert core.choices[0].arms[0].caption == "Take the ridge"


def test_partial_assembly_preserves_complete_chunk_and_missing_mechanics() -> None:
    fixture = scope(
        (
            span("a", 1, 9, 6_000, boundary=True),
            span("b", 10, 19, 6_000, boundary=True),
        )
    )
    planned = plan_chunks(fixture)
    assert len(planned) == 2
    assert planned[0].identity != planned[-1].identity
    chunks = (
        CoreChunk(planned[0].identity, ChunkStatus.COMPLETE, ProviderOrigin.CLOUD, (), ()),
        CoreChunk(planned[-1].identity, ChunkStatus.MISSING, ProviderOrigin.MISSING, (), ()),
    )
    core = assemble_core(fixture, chunks)
    assert core.status is ChunkStatus.PARTIAL
    assert core.chunks == chunks
