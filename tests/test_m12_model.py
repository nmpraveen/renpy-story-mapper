from __future__ import annotations

from dataclasses import replace

import pytest

from renpy_story_mapper.m12_model import (
    DestinationKind,
    DeterministicLimitProfile,
    InitialStateValue,
    InitialValueKind,
    RequirementAttribution,
    RequirementSource,
    RouteDestination,
    RouteRequest,
    StateVariableIdentity,
)
from renpy_story_mapper.m12_solver import (
    LoopAccelerationSummary,
    identities_in_expression,
    identity_from_name,
    loop_acceleration_decision,
    threshold_equivalence,
)


def _request(*, limits: DeterministicLimitProfile | None = None) -> RouteRequest:
    return RouteRequest(
        source_generation="generation",
        canonical_schema="m10-canonical-graph-v1",
        canonical_hash="a" * 64,
        scene_schema="m11-scene-model-v1",
        scene_hash="b" * 64,
        start_node_id="node-entry",
        destination=RouteDestination(DestinationKind.GENERIC_SCENE, "scene-target"),
        limits=limits or DeterministicLimitProfile(),
    )


def test_state_identity_preserves_scope_name_and_persistent_status() -> None:
    store_a = identity_from_name("store_a.score")
    store_b = identity_from_name("store_b.score")
    persistent = identity_from_name("persistent.score")
    bare = identity_from_name("score")

    assert store_a == StateVariableIdentity("store_a", "score", None)
    assert store_b == StateVariableIdentity("store_b", "score", None)
    assert store_a.key != store_b.key
    assert persistent == StateVariableIdentity("persistent", "score", True)
    assert bare == StateVariableIdentity("store", "score", None)
    assert identities_in_expression("store_a.score > store_b.score") == (store_a, store_b)


def test_known_unknown_entry_and_persistent_values_remain_distinct() -> None:
    variable = StateVariableIdentity("store", "score", None)
    known = InitialStateValue(variable, InitialValueKind.KNOWN, 2, ("m10-init",))
    entry = InitialStateValue(variable, InitialValueKind.ENTRY_PRECONDITION, 2)
    unknown = InitialStateValue(variable, InitialValueKind.UNKNOWN)

    assert known.to_dict()["kind"] == "known_initial_value"
    assert entry.to_dict()["kind"] == "entry_precondition"
    assert unknown.to_dict()["value"] is None
    with pytest.raises(ValueError, match="cannot carry"):
        InitialStateValue(variable, InitialValueKind.UNKNOWN, False)
    with pytest.raises(ValueError, match="requires M10 evidence"):
        InitialStateValue(variable, InitialValueKind.KNOWN, 0)
    with pytest.raises(ValueError, match="requires M10 evidence"):
        InitialStateValue(
            StateVariableIdentity("persistent", "seen", True),
            InitialValueKind.KNOWN,
            False,
        )


def test_request_identity_includes_every_versioned_deterministic_budget() -> None:
    first = _request()
    second = _request(limits=replace(first.limits, expanded_states=19_999))

    assert first.identity != second.identity
    assert first.normalized_bytes() == _request().normalized_bytes()
    assert set(first.normalized_dict()["limits"]) == {
        "version",
        "expanded_states",
        "retained_states",
        "frontier_states",
        "prefix_records",
        "call_depth",
        "repetition_per_transition",
        "alternatives",
        "accounting_units",
    }
    assert b"duration" not in first.normalized_bytes()
    assert b"timestamp" not in first.normalized_bytes()
    assert b"wall" not in first.normalized_bytes()


def test_material_requirement_has_exactly_one_support_category() -> None:
    unknown = RequirementAttribution(
        "fact", "score > 1", RequirementSource.UNKNOWN
    )
    effect = RequirementAttribution(
        "fact",
        "score > 1",
        RequirementSource.PROVEN_EFFECT,
        satisfying_effect_id="effect",
        supporting_effect_ids=("effect",),
    )
    repeated = RequirementAttribution(
        "fact",
        "score > 1",
        RequirementSource.REPEATED_EVENT,
        repeated_effect_id="effect",
        supporting_effect_ids=("effect",),
        repeated_count=2,
    )
    entry_value = InitialStateValue(
        StateVariableIdentity("store", "score", None),
        InitialValueKind.ENTRY_PRECONDITION,
        2,
    )
    entry = RequirementAttribution(
        "fact",
        "score > 1",
        RequirementSource.ENTRY_PRECONDITION,
        entry_precondition=entry_value,
    )

    assert {item.source for item in (unknown, effect, repeated, entry)} == set(
        RequirementSource
    )
    assert entry.to_dict()["entry_precondition"] == entry_value.to_dict()
    with pytest.raises(ValueError, match="cannot carry"):
        RequirementAttribution(
            "fact",
            "score > 1",
            RequirementSource.UNKNOWN,
            satisfying_effect_id="effect",
        )


def test_threshold_equivalence_is_bounded_across_multiple_thresholds() -> None:
    thresholds = (1, 3, 5)

    assert [threshold_equivalence(value, thresholds) for value in range(8)] == [
        "<1",
        "=1",
        "<3",
        "=3",
        "<5",
        "=5",
        ">5",
        ">5",
    ]
    assert threshold_equivalence(100_000, thresholds) == ">5"


def test_one_shot_loop_effect_blocks_acceleration() -> None:
    safe = LoopAccelerationSummary(True, True, True, False, False, False, True, True)
    one_shot = replace(safe, relevant_one_shot_change=True)

    assert loop_acceleration_decision(safe).eligible is True
    decision = loop_acceleration_decision(one_shot)
    assert decision.eligible is False
    assert decision.reasons == ("relevant one-shot state changes",)
