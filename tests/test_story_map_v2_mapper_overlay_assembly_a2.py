from __future__ import annotations

import json
from dataclasses import replace

import pytest

from renpy_story_mapper.story_map_v2.assembly import CoreAssemblyError, assemble_core
from renpy_story_mapper.story_map_v2.contracts import (
    ArmLineageStep,
    ArmMechanic,
    BranchSummary,
    ChunkExecutionResult,
    ChunkStatus,
    CoreChunk,
    MapperEvent,
    MapperResponse,
    ProviderOrigin,
    Reachability,
    StoryChunk,
)
from renpy_story_mapper.story_map_v2.mapper_io import (
    MapperResponseValidationError,
    MapperSerializationError,
    deserialize_mapper_response,
    serialize_mapper_request,
)
from renpy_story_mapper.story_map_v2.overlay import MapperValidationError, validate_and_overlay
from renpy_story_mapper.story_map_v2.planner import plan_chunks
from story_map_v2_fixtures import arm, choice, scope, span

CHOICE_KEY = "scripts/day.rpy:10"


def _choice_scope():  # type: ignore[no-untyped-def]
    mechanic = choice()
    spans = (
        span("menu", 10, 10, 100, choice_keys=(CHOICE_KEY,)),
        span(
            "ridge",
            11,
            19,
            100,
            lineage=(ArmLineageStep(CHOICE_KEY, 1),),
            choice_keys=(CHOICE_KEY,),
        ),
        span(
            "valley",
            20,
            29,
            100,
            lineage=(ArmLineageStep(CHOICE_KEY, 2),),
            choice_keys=(CHOICE_KEY,),
        ),
        span("rejoin", 40, 45, 100, choice_keys=(CHOICE_KEY,), shared=True),
    )
    return scope(spans, choices=(mechanic,))


def _execution(
    chunk: StoryChunk,
    response: MapperResponse,
    *,
    origin: ProviderOrigin = ProviderOrigin.CLOUD,
    status: ChunkStatus = ChunkStatus.COMPLETE,
) -> ChunkExecutionResult:
    return ChunkExecutionResult(
        chunk_identity=chunk.identity,
        origin=origin,
        status=status,
        response=response,
        failure_kind=None,
        elapsed_ms=25,
        response_hash="e" * 64,
        sanitized_reason=None,
        input_tokens=120,
        output_tokens=30,
        requested_model="gpt-5.6-luna",
        resolved_model="gpt-5.6-luna",
        reasoning="high",
        fast_mode=False,
    )


def _event_response(
    *,
    title: str = "Arrival",
    start: int = 1,
    end: int = 5,
    path: str = "scripts/day.rpy",
) -> MapperResponse:
    return MapperResponse(
        "Opening",
        "The travelers arrive.",
        (MapperEvent(title, "They arrive together.", path, start, end, ("Ari",)),),
        (),
    )


def test_mapper_request_serializes_exact_line_numbered_story_and_canonical_mechanics() -> None:
    fixture = _choice_scope()
    chunk = plan_chunks(fixture)[0]

    first = serialize_mapper_request(chunk)
    second = serialize_mapper_request(chunk)
    payload = json.loads(first)

    assert first == second
    assert payload["chunk_identity"] == chunk.identity
    assert payload["packet_hash"] == chunk.packet_hash
    assert payload["raw_text"] == chunk.raw_text
    assert payload["mechanics"] == json.loads(chunk.mechanics)
    assert payload["mechanics"]["choices"][0]["arms"][0]["caption"] == "Take the ridge"


def test_mapper_request_rejects_non_numbered_text_and_mismatched_mechanics_keys() -> None:
    fixture = _choice_scope()
    chunk = plan_chunks(fixture)[0]

    with pytest.raises(MapperSerializationError, match="line-numbered"):
        serialize_mapper_request(replace(chunk, raw_text="not numbered"))
    with pytest.raises(MapperSerializationError, match="choice keys"):
        serialize_mapper_request(replace(chunk, mechanics='{"choices":[]}'))


def test_mapper_response_json_round_trips_strict_frozen_shape() -> None:
    payload = json.dumps(
        {
            "branch_summaries": [
                {
                    "outcome_summary": "They take the difficult route.",
                    "arm_order": 1,
                    "choice_key": CHOICE_KEY,
                }
            ],
            "events": [
                {
                    "warning": None,
                    "characters": ["Ari"],
                    "end_line": 19,
                    "start_line": 11,
                    "relative_path": "scripts/day.rpy",
                    "summary": "They climb.",
                    "title": "The ridge",
                }
            ],
            "scope_overview": "A route is chosen.",
            "scope_title": "The crossing",
        }
    )

    response = deserialize_mapper_response(payload)

    assert response.scope_title == "The crossing"
    assert response.events[0].characters == ("Ari",)
    assert response.branch_summaries[0] == BranchSummary(
        CHOICE_KEY, 1, "They take the difficult route."
    )


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        ('{"events":[],"branch_summaries":[],"extra":1}', "unsupported"),
        ('{"events":[],"branch_summaries":[],"events":[]}', "duplicate"),
        (
            '{"events":[{"title":"T","summary":"S","relative_path":"p",'
            '"start_line":true,"end_line":1,"characters":[],"warning":null}],'
            '"branch_summaries":[]}',
            "integer",
        ),
        (
            '{"events":[{"title":"T","summary":"S","relative_path":"p",'
            '"start_line":2,"end_line":1,"characters":[],"warning":null}],'
            '"branch_summaries":[]}',
            "inverted",
        ),
        (
            '{"events":[{"title":"T","summary":"S","relative_path":"p",'
            '"start_line":1,"end_line":1,"characters":[]}],"branch_summaries":[]}',
            "missing",
        ),
    ),
)
def test_mapper_response_json_rejects_unknown_duplicate_type_range_and_missing_keys(
    payload: str, message: str
) -> None:
    with pytest.raises(MapperResponseValidationError, match=message):
        deserialize_mapper_response(payload)


def test_linear_overlay_retains_scope_text_exact_reachability_and_stable_title_free_anchor() -> None:
    fixture = scope((span("arrival", 1, 5, 100),))
    chunk = plan_chunks(fixture)[0]
    first_response = _event_response(title="Arrival")
    execution = _execution(chunk, first_response)

    first = validate_and_overlay(
        fixture,
        chunk,
        first_response,
        origin=ProviderOrigin.CLOUD,
        execution=execution,
    )
    second = validate_and_overlay(
        fixture,
        chunk,
        _event_response(title="A different generated title"),
        origin=ProviderOrigin.CLOUD,
    )

    assert first.scope_title == "Opening"
    assert first.scope_overview == "The travelers arrive."
    assert first.events[0].reachability is Reachability.REACHABLE
    assert first.events[0].anchor.id == second.events[0].anchor.id
    assert first.events[0].anchor.canonical_node_id == "node:arrival"
    assert first.execution is execution


@pytest.mark.parametrize(
    ("change", "message"),
    (
        ({"chunk_identity": "wrong"}, "identity"),
        ({"origin": ProviderOrigin.LOCAL_ONLY}, "origin"),
        ({"status": ChunkStatus.PARTIAL}, "status"),
    ),
)
def test_overlay_rejects_mismatched_execution_provenance(
    change: dict[str, object], message: str
) -> None:
    fixture = scope((span("arrival", 1, 5, 100),))
    chunk = plan_chunks(fixture)[0]
    response = _event_response()
    execution = replace(_execution(chunk, response), **change)

    with pytest.raises(MapperValidationError, match=message):
        validate_and_overlay(
            fixture,
            chunk,
            response,
            origin=ProviderOrigin.CLOUD,
            execution=execution,
        )


def test_overlay_rejects_unknown_path_range_gap_and_out_of_order_events() -> None:
    fixture = scope((span("first", 1, 5, 100), span("second", 10, 15, 100)))
    chunk = plan_chunks(fixture)[0]
    cases = (
        MapperResponse(None, None, (MapperEvent("X", "X", "other.rpy", 1, 1),), ()),
        MapperResponse(
            None,
            None,
            (MapperEvent("Gap", "Crosses omitted lines", "scripts/day.rpy", 1, 10),),
            (),
        ),
        MapperResponse(
            None,
            None,
            (
                MapperEvent("Later", "Later", "scripts/day.rpy", 10, 15),
                MapperEvent("Earlier", "Earlier", "scripts/day.rpy", 1, 5),
            ),
            (),
        ),
    )

    for response in cases:
        with pytest.raises(MapperValidationError):
            validate_and_overlay(fixture, chunk, response, origin=ProviderOrigin.CLOUD)


def test_overlay_rejects_cross_sibling_and_arm_to_post_rejoin_ranges() -> None:
    fixture = _choice_scope()
    chunk = plan_chunks(fixture)[0]
    cross_siblings = MapperResponse(
        None,
        None,
        (MapperEvent("Both", "Both routes", "scripts/day.rpy", 11, 29),),
        (),
    )
    with pytest.raises(MapperValidationError, match="lineage"):
        validate_and_overlay(fixture, chunk, cross_siblings, origin=ProviderOrigin.CLOUD)

    base = choice()
    arms = (
        replace(base.arms[0], rejoin_line=20),
        replace(base.arms[1], start_line=50, end_line=59, rejoin_line=20),
    )
    local_choice = replace(base, arms=arms)
    local_scope = scope(
        (
            span("menu", 10, 10, 100, choice_keys=(CHOICE_KEY,)),
            span(
                "ridge",
                11,
                19,
                100,
                lineage=(ArmLineageStep(CHOICE_KEY, 1),),
                choice_keys=(CHOICE_KEY,),
            ),
            span("rejoin", 20, 35, 100, choice_keys=(CHOICE_KEY,), shared=True),
        ),
        choices=(local_choice,),
    )
    local_chunk = plan_chunks(local_scope)[0]
    arm_to_rejoin = MapperResponse(
        None,
        None,
        (MapperEvent("Ambiguous", "Arm and rejoin", "scripts/day.rpy", 11, 35),),
        (),
    )
    with pytest.raises(MapperValidationError, match="lineage"):
        validate_and_overlay(
            local_scope, local_chunk, arm_to_rejoin, origin=ProviderOrigin.CLOUD
        )


def test_proven_shared_rejoin_is_a_spine_event_with_python_span_status() -> None:
    fixture = _choice_scope()
    chunk = plan_chunks(fixture)[0]
    response = MapperResponse(
        None,
        None,
        (MapperEvent("Together", "The routes reunite.", "scripts/day.rpy", 40, 45),),
        (),
    )

    core = validate_and_overlay(fixture, chunk, response, origin=ProviderOrigin.CLOUD)

    assert core.events[0].anchor.arm_lineage == ()
    assert core.events[0].anchor.destination_id is None
    assert core.events[0].reachability is Reachability.REACHABLE


def test_nested_branch_outcome_uses_full_python_lineage_caption_and_destination() -> None:
    outer = ArmLineageStep("scripts/day.rpy:5", 2)
    nested_choice = choice(parent=(outer,))
    lineage = (outer, ArmLineageStep(CHOICE_KEY, 1))
    fixture = scope(
        (
            span(
                "nested",
                11,
                19,
                100,
                lineage=lineage,
                choice_keys=(CHOICE_KEY,),
            ),
        ),
        choices=(nested_choice,),
    )
    chunk = plan_chunks(fixture)[0]
    response = MapperResponse(
        None,
        None,
        (MapperEvent("Ridge", "They climb.", "scripts/day.rpy", 11, 19),),
        (BranchSummary(CHOICE_KEY, 1, 'The mapper calls it "the wrong caption".'),),
    )

    core = validate_and_overlay(fixture, chunk, response, origin=ProviderOrigin.CLOUD)

    assert core.events[0].anchor.arm_lineage == lineage
    assert core.branch_outcomes[0].caption == "Take the ridge"
    assert core.branch_outcomes[0].anchor.arm_lineage == lineage
    assert core.branch_outcomes[0].anchor.destination_id == "node:ridge"


def test_conditional_persistent_unresolved_branch_keeps_exact_python_mechanics() -> None:
    unresolved_arm = ArmMechanic(
        order=1,
        caption="Enter the ruins",
        start_line=11,
        end_line=15,
        condition="courage >= 2",
        effects=("relic_found = True",),
        destination_id="node:ruins",
        rejoin_node_id=None,
        rejoin_line=None,
        reachability=Reachability.UNRESOLVED,
        unresolved_warnings=("dynamic chamber target",),
    )
    safe_arm = arm(
        2,
        "Stay outside",
        16,
        20,
        destination="node:camp",
        rejoin=None,
        rejoin_line=None,
    )
    mechanic = replace(choice(), arms=(unresolved_arm, safe_arm))
    fixture = scope(
        (
            span("menu", 10, 10, 100, choice_keys=(CHOICE_KEY,)),
            span(
                "ruins",
                11,
                15,
                100,
                lineage=(ArmLineageStep(CHOICE_KEY, 1),),
                choice_keys=(CHOICE_KEY,),
                reachability=Reachability.UNRESOLVED,
                warnings=("canonical dynamic target",),
            ),
            span(
                "camp",
                16,
                20,
                100,
                lineage=(ArmLineageStep(CHOICE_KEY, 2),),
                choice_keys=(CHOICE_KEY,),
            ),
        ),
        choices=(mechanic,),
    )
    chunk = plan_chunks(fixture)[0]
    response = MapperResponse(
        None,
        None,
        (),
        (BranchSummary(CHOICE_KEY, 1, "They investigate the ruins."),),
    )

    core = validate_and_overlay(fixture, chunk, response, origin=ProviderOrigin.CLOUD)

    assert core.choices[0].arms[0].condition == "courage >= 2"
    assert core.choices[0].arms[0].effects == ("relic_found = True",)
    assert core.choices[0].arms[0].rejoin_node_id is None
    assert core.branch_outcomes[0].reachability is Reachability.UNRESOLVED
    assert core.branch_outcomes[0].warnings == ("dynamic chamber target",)


def test_overlay_rejects_invented_choice_arm_and_reverse_branch_order() -> None:
    fixture = _choice_scope()
    chunk = plan_chunks(fixture)[0]
    cases = (
        MapperResponse(None, None, (), (BranchSummary("invented", 1, "X"),)),
        MapperResponse(None, None, (), (BranchSummary(CHOICE_KEY, 3, "X"),)),
        MapperResponse(
            None,
            None,
            (),
            (
                BranchSummary(CHOICE_KEY, 2, "Valley"),
                BranchSummary(CHOICE_KEY, 1, "Ridge"),
            ),
        ),
    )

    for response in cases:
        with pytest.raises(MapperValidationError):
            validate_and_overlay(fixture, chunk, response, origin=ProviderOrigin.CLOUD)


def test_mixed_span_reachability_becomes_honestly_unresolved_with_warning() -> None:
    fixture = scope(
        (
            span("known", 1, 5, 100),
            span("blocked", 6, 10, 100, reachability=Reachability.UNREACHABLE),
        )
    )
    chunk = plan_chunks(fixture)[0]
    response = MapperResponse(
        None,
        None,
        (MapperEvent("Mixed", "Mixed authority", "scripts/day.rpy", 1, 10),),
        (),
    )

    core = validate_and_overlay(fixture, chunk, response, origin=ProviderOrigin.CLOUD)

    assert core.events[0].reachability is Reachability.UNRESOLVED
    assert "mixed reachability" in core.events[0].warnings[0]


def _two_chunk_scope():  # type: ignore[no-untyped-def]
    return scope(
        (
            span("first", 1, 5, 5_000, boundary=True),
            span("second", 6, 10, 5_000, boundary=True),
        )
    )


def test_assembly_fills_missing_chunk_preserves_complete_provenance_and_scope_text() -> None:
    fixture = _two_chunk_scope()
    planned = plan_chunks(fixture)
    response = _event_response(end=5)
    execution = _execution(planned[0], response)
    first = validate_and_overlay(
        fixture,
        planned[0],
        response,
        origin=ProviderOrigin.CLOUD,
        execution=execution,
    )

    core = assemble_core(fixture, (first,))

    assert core.status is ChunkStatus.PARTIAL
    assert core.chunks[0] is first
    assert core.chunks[0].execution is execution
    assert core.chunks[1].status is ChunkStatus.MISSING
    assert core.chunks[1].origin is ProviderOrigin.MISSING
    assert core.title == "Opening"
    assert core.overview == "The travelers arrive."


def test_assembly_combines_scope_text_in_chunk_order_when_all_chunks_complete() -> None:
    fixture = _two_chunk_scope()
    planned = plan_chunks(fixture)
    first = CoreChunk(
        planned[0].identity,
        ChunkStatus.COMPLETE,
        ProviderOrigin.CLOUD,
        (),
        (),
        scope_title="First",
        scope_overview="First overview.",
    )
    second = CoreChunk(
        planned[1].identity,
        ChunkStatus.COMPLETE,
        ProviderOrigin.LOCAL_FALLBACK,
        (),
        (),
        scope_title="Second",
        scope_overview="Second overview.",
    )

    core = assemble_core(fixture, (first, second))

    assert core.status is ChunkStatus.COMPLETE
    assert core.title == "First\n\nSecond"
    assert core.overview == "First overview.\n\nSecond overview."


def test_assembly_rejects_unknown_duplicate_and_out_of_order_chunks() -> None:
    fixture = _two_chunk_scope()
    planned = plan_chunks(fixture)
    first = CoreChunk(planned[0].identity, ChunkStatus.COMPLETE, ProviderOrigin.CLOUD, (), ())
    second = CoreChunk(planned[1].identity, ChunkStatus.COMPLETE, ProviderOrigin.CLOUD, (), ())
    unknown = replace(first, chunk_identity="unknown")

    with pytest.raises(CoreAssemblyError, match="unknown"):
        assemble_core(fixture, (unknown,))
    with pytest.raises(CoreAssemblyError, match="duplicate"):
        assemble_core(fixture, (first, first))
    with pytest.raises(CoreAssemblyError, match="chronological"):
        assemble_core(fixture, (second, first))


@pytest.mark.parametrize(
    ("change", "message"),
    (
        ({"chunk_identity": "wrong"}, "identity"),
        ({"origin": ProviderOrigin.LOCAL_ONLY}, "origin"),
        ({"status": ChunkStatus.PARTIAL}, "status"),
    ),
)
def test_assembly_rejects_mismatched_execution_provenance(
    change: dict[str, object], message: str
) -> None:
    fixture = scope((span("only", 1, 5, 100),))
    planned = plan_chunks(fixture)[0]
    response = _event_response()
    execution = replace(_execution(planned, response), **change)
    chunk = CoreChunk(
        planned.identity,
        ChunkStatus.COMPLETE,
        ProviderOrigin.CLOUD,
        (),
        (),
        execution=execution,
    )

    with pytest.raises(CoreAssemblyError, match=message):
        assemble_core(fixture, (chunk,))


def test_missing_assembly_chunk_retains_authoritative_choice_mechanics() -> None:
    fixture = _choice_scope()

    core = assemble_core(fixture, ())

    assert core.status is ChunkStatus.PARTIAL
    assert core.chunks[0].status is ChunkStatus.MISSING
    assert core.chunks[0].choices[0].arms[0].caption == "Take the ridge"
