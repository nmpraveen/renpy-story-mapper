from __future__ import annotations

from dataclasses import replace

import pytest

from renpy_story_mapper.narrative_map import (
    AuthorityBinding,
    BoundaryDecision,
    BoundaryDecisionKind,
    BoundaryProviderIdentity,
    BoundarySignal,
    NarrativeCorridor,
    Provenance,
    SourceLocator,
    assemble_narrative_events,
    build_boundary_candidates,
)


def _authority() -> AuthorityBinding:
    return AuthorityBinding("generation", "m10", "hash", "m11", "atom-hash")


def _corridor(
    ordinal: int,
    *,
    lane: str = "lane",
    occurrence: str | None = None,
    container: str | None = None,
    arm: str | None = None,
    hard_before: bool = False,
    hard_after: bool = False,
    soft: tuple[BoundarySignal, ...] = (),
) -> NarrativeCorridor:
    atom = f"atom-{ordinal}"
    node = f"node-{ordinal}"
    return NarrativeCorridor(
        authority=_authority(),
        lane_id=lane,
        chapter_id="chapter",
        call_occurrence_id=occurrence,
        loop_id=None,
        temporary_container_id=container,
        temporary_arm_id=arm,
        ordered_atom_ids=(atom,),
        entry_node_id=node,
        exit_node_id=node,
        incident_edge_ids=(f"edge-{ordinal}",),
        hard_boundary_before=hard_before,
        hard_boundary_after=hard_after,
        soft_boundary_signals=soft,
        provenance=Provenance(
            atom_ids=(atom,),
            node_ids=(node,),
            edge_ids=(f"edge-{ordinal}",),
            locators=(SourceLocator("game/story.rpy", ordinal, ordinal, "physical"),),
        ),
    )


def _merge_decision(left: NarrativeCorridor, right: NarrativeCorridor) -> BoundaryDecision:
    candidate = build_boundary_candidates((left, right))[0]
    return BoundaryDecision(
        candidate,
        BoundaryDecisionKind.MERGE,
        "Synthetic adjacent material remains one event.",
        1.0,
        BoundaryProviderIdentity("fake", "v1", "fake", "fake", "settings", "p1", "s1", "i1"),
    )


def test_linear_soft_boundary_merges_only_with_an_exact_decision() -> None:
    first = _corridor(1)
    second = _corridor(2, soft=(BoundarySignal.NARRATIVE_OBJECTIVE,))

    assert len(assemble_narrative_events((first, second))) == 2
    merged = assemble_narrative_events((first, second), (_merge_decision(first, second),))
    assert len(merged) == 1
    assert merged[0].ordered_atom_ids == ("atom-1", "atom-2")


def test_local_and_nested_arms_never_escape_context_or_duplicate_continuation() -> None:
    split = _corridor(1, hard_after=True)
    outer = _corridor(2, container="choice", arm="arm-0", hard_before=True, hard_after=True)
    nested = _corridor(
        3,
        container="nested-choice",
        arm="nested-arm-0",
        hard_before=True,
        hard_after=True,
    )
    sibling = _corridor(4, container="choice", arm="arm-1", hard_before=True, hard_after=True)
    continuation = _corridor(5, hard_before=True)

    events = assemble_narrative_events(
        (split, outer, nested, sibling, continuation),
        expected_atom_ids=("atom-1", "atom-2", "atom-3", "atom-4", "atom-5"),
    )

    assert len(events) == 5
    assert sum("atom-5" in item.ordered_atom_ids for item in events) == 1
    assert {item.temporary_arm_id for item in events if item.temporary_arm_id} == {
        "arm-0",
        "nested-arm-0",
        "arm-1",
    }


@pytest.mark.parametrize(
    "changed, message",
    (
        (("duplicate",), "overlaps"),
        (("missing",), "missing or out of scope"),
        (("out-of-order",), "out of source/control order"),
    ),
)
def test_duplicate_missing_and_out_of_order_membership_fail_closed(
    changed: tuple[str, ...], message: str
) -> None:
    first = _corridor(1)
    second = _corridor(2)
    corridors = (first, second)
    expected: tuple[str, ...] = ("atom-1", "atom-2")
    if changed == ("duplicate",):
        second = replace(
            second,
            ordered_atom_ids=("atom-1",),
            provenance=replace(second.provenance, atom_ids=("atom-1",)),
        )
        corridors = (first, second)
    elif changed == ("missing",):
        expected = ("atom-1", "atom-2", "atom-3")
    else:
        corridors = (second, first)
    with pytest.raises(ValueError, match=message):
        assemble_narrative_events(corridors, expected_atom_ids=expected)


def test_persistent_lanes_and_call_occurrences_never_merge() -> None:
    corridors = (
        _corridor(1, lane="lane-a"),
        _corridor(2, lane="lane-b"),
        _corridor(3, occurrence="call-1"),
        _corridor(4, occurrence="call-2"),
    )
    events = assemble_narrative_events(corridors)
    assert len(events) == 4
    assert len({(item.lane_id, item.call_occurrence_id) for item in events}) == 4


def test_decision_across_a_hard_boundary_is_rejected() -> None:
    first = _corridor(1, hard_after=True)
    second = _corridor(
        2,
        hard_before=True,
        soft=(BoundarySignal.NARRATIVE_OBJECTIVE,),
    )
    candidate = replace(
        build_boundary_candidates((_corridor(1), _corridor(2, soft=(BoundarySignal.CAST,))))[0],
        left_corridor_id=first.corridor_id,
        right_corridor_id=second.corridor_id,
    )
    decision = BoundaryDecision(
        candidate,
        BoundaryDecisionKind.MERGE,
        "Invalid hard-boundary merge.",
        1.0,
        BoundaryProviderIdentity("fake", "v1", "fake", "fake", "settings", "p1", "s1", "i1"),
    )
    with pytest.raises(ValueError, match="exact adjacent soft candidate"):
        assemble_narrative_events((first, second), (decision,))
