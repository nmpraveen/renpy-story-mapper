from __future__ import annotations

from dataclasses import replace

import pytest

from renpy_story_mapper.narrative_map import (
    AuthorityBinding,
    ChoiceComposition,
    FineNarrativeUnit,
    HierarchyHardLock,
    HierarchyHardLockKind,
    NarrativeGapCandidate,
    ProposedBeatGroup,
    ProposedMajorCluster,
    Provenance,
    SemanticBoundaryKind,
    SourceLocator,
    WholeScopeHierarchyProposal,
    assemble_semantic_outline,
    build_all_eligible_gap_candidates,
    compile_hierarchy_to_gap_decisions,
    derive_stable_hierarchy_ids,
    validate_whole_scope_hierarchy,
)
from renpy_story_mapper.narrative_map.semantic_contracts import SemanticOutline
from renpy_story_mapper.narrative_map.semantic_hierarchy import HierarchyAuthorityError
from renpy_story_mapper.narrative_map.semantic_lifecycle import (
    whole_scope_hierarchy_input_payload,
)
from renpy_story_mapper.narrative_map.semantic_projection import SemanticEvidenceRecord


def _authority() -> AuthorityBinding:
    return AuthorityBinding("synthetic", "m10-v1", "m10-hash", "m11-v1", "m11-hash")


def _unit(
    key: str,
    sequence_id: str,
    ordinal: int,
    *,
    lane_id: str = "lane-main",
    call_occurrence_id: str | None = None,
    loop_id: str | None = None,
    parent_choice_id: str | None = None,
    parent_arm_id: str | None = None,
) -> FineNarrativeUnit:
    locator = SourceLocator("game/synthetic.rpy", ordinal + 1, ordinal + 1, "physical_source")
    return FineNarrativeUnit(
        authority=_authority(),
        sequence_id=sequence_id,
        ordinal=ordinal,
        story_atom_id=f"atom-{key}",
        story_locator=locator,
        technical_context_atom_ids=(),
        node_ids=(f"node-{key}",),
        evidence_ids=(f"evidence-{key}",),
        speaker_ids=(),
        context_ids=(),
        lane_id=lane_id,
        call_occurrence_id=call_occurrence_id,
        loop_id=loop_id,
        parent_choice_id=parent_choice_id,
        parent_arm_id=parent_arm_id,
        entry_node_id=f"node-{key}",
        exit_node_id=f"node-{key}",
        incident_edge_ids=(),
        provenance=Provenance(
            atom_ids=(f"atom-{key}",),
            node_ids=(f"node-{key}",),
            evidence_ids=(f"evidence-{key}",),
            locators=(locator,),
        ),
        call_occurrence_path=(call_occurrence_id,) if call_occurrence_id else (),
        call_site_path=(f"site-{call_occurrence_id}",) if call_occurrence_id else (),
    )


def _beat(key: str, units: tuple[FineNarrativeUnit, ...]) -> ProposedBeatGroup:
    return ProposedBeatGroup(
        key,
        tuple(item.unit_id for item in units),
        0.9,
        "Synthetic whole-scope grouping.",
    )


def _proposal(
    units: tuple[FineNarrativeUnit, ...],
    *,
    beat_keys: tuple[str, str, str] = ("proposal-a", "proposal-b", "proposal-c"),
    cluster_keys: tuple[str, str] = ("proposal-cluster-a", "proposal-cluster-b"),
) -> WholeScopeHierarchyProposal:
    return WholeScopeHierarchyProposal(
        "scope-synthetic",
        (
            _beat(beat_keys[0], units[:2]),
            _beat(beat_keys[1], units[2:3]),
            _beat(beat_keys[2], units[3:]),
        ),
        (
            ProposedMajorCluster(
                cluster_keys[0], beat_keys[:2], 0.9, "Synthetic first section."
            ),
            ProposedMajorCluster(
                cluster_keys[1], beat_keys[2:], 0.9, "Synthetic second section."
            ),
        ),
    )


def _linear_authority() -> tuple[tuple[FineNarrativeUnit, ...], tuple[NarrativeGapCandidate, ...]]:
    units = tuple(_unit(str(index), "main", index) for index in range(6))
    return units, build_all_eligible_gap_candidates(units)


def _assert_exact_assembler_round_trip(
    proposal: WholeScopeHierarchyProposal,
    units: tuple[FineNarrativeUnit, ...],
    candidates: tuple[NarrativeGapCandidate, ...],
    *,
    choices: tuple[ChoiceComposition, ...] = (),
) -> None:
    validated = validate_whole_scope_hierarchy(
        proposal,
        units,
        candidates,
        choices,
    )
    decisions = compile_hierarchy_to_gap_decisions(validated)
    outline = assemble_semantic_outline(units, candidates, decisions, choices=choices)
    assert isinstance(outline, SemanticOutline)
    derived = derive_stable_hierarchy_ids(validated)

    assert tuple(item.ordered_unit_ids for item in outline.beats) == tuple(
        item.ordered_unit_ids for item in proposal.beat_groups
    )
    beat_by_id = {item.beat_id: item for item in outline.beats}
    assert tuple(
        tuple(beat_by_id[beat_id].ordered_unit_ids for beat_id in cluster.ordered_beat_ids)
        for cluster in outline.clusters
    ) == tuple(
        tuple(
            next(
                beat.ordered_unit_ids
                for beat in proposal.beat_groups
                if beat.proposal_key == beat_key
            )
            for beat_key in cluster.ordered_beat_keys
        )
        for cluster in proposal.major_clusters
    )
    assert tuple(stable_id for _, stable_id in derived.beat_ids) == tuple(
        item.beat_id for item in outline.beats
    )
    assert tuple(stable_id for _, stable_id in derived.cluster_ids) == tuple(
        item.cluster_id for item in outline.clusters
    )


def test_valid_hierarchy_compiles_exhaustively_and_derives_authority_ids() -> None:
    units, candidates = _linear_authority()
    validated = validate_whole_scope_hierarchy(
        _proposal(units),
        units,
        candidates,
        scope_id="scope-synthetic",
        authority=_authority(),
    )

    decisions = compile_hierarchy_to_gap_decisions(validated)
    derived = derive_stable_hierarchy_ids(validated)

    assert [item.candidate_id for item in decisions] == [item.candidate_id for item in candidates]
    assert [item.decision for item in decisions] == [
        SemanticBoundaryKind.SAME_BEAT,
        SemanticBoundaryKind.NEW_BEAT_SAME_CLUSTER,
        SemanticBoundaryKind.NEW_MAJOR_CLUSTER,
        SemanticBoundaryKind.SAME_BEAT,
        SemanticBoundaryKind.SAME_BEAT,
    ]
    assert all(value.startswith("semantic_beat_") for _, value in derived.beat_ids)
    assert all(value.startswith("semantic_cluster_") for _, value in derived.cluster_ids)


def test_linear_hierarchy_round_trips_exact_membership_and_published_ids() -> None:
    units, candidates = _linear_authority()

    _assert_exact_assembler_round_trip(_proposal(units), units, candidates)


def test_zero_candidate_multi_sequence_cluster_split_is_rejected_as_unrepresentable() -> None:
    units = (
        _unit("first", "sequence-first", 0),
        _unit("second", "sequence-second", 0),
    )
    proposal = WholeScopeHierarchyProposal(
        "scope-synthetic",
        (_beat("proposal-first", units[:1]), _beat("proposal-second", units[1:])),
        (
            ProposedMajorCluster(
                "cluster-first", ("proposal-first",), 0.9, "First synthetic section."
            ),
            ProposedMajorCluster(
                "cluster-second", ("proposal-second",), 0.9, "Second synthetic section."
            ),
        ),
    )

    with pytest.raises(ValueError, match="not representable by the existing assembler"):
        validate_whole_scope_hierarchy(proposal, units, ())


def test_choice_arm_and_rejoin_boundaries_round_trip_through_existing_assembler() -> None:
    units = (
        _unit("question", "question", 0),
        _unit(
            "arm-a",
            "arm-a",
            0,
            lane_id="lane-arm-a",
            parent_choice_id="choice-one",
            parent_arm_id="arm-a",
        ),
        _unit(
            "arm-b",
            "arm-b",
            0,
            lane_id="lane-arm-b",
            parent_choice_id="choice-one",
            parent_arm_id="arm-b",
        ),
        _unit("rejoin", "rejoin", 0, lane_id="lane-rejoin"),
    )
    provisional = assemble_semantic_outline(units, (), ())
    assert isinstance(provisional, SemanticOutline)
    choice = ChoiceComposition(
        "choice-one",
        provisional.clusters[0].cluster_id,
        None,
        None,
        ("arm-a", "arm-b"),
        ("Take A", "Take B"),
        (),
        ("rejoin-a", "rejoin-b"),
        "node-rejoin",
        units[-1].unit_id,
    )
    beat_keys = ("proposal-question", "proposal-arm-a", "proposal-arm-b", "proposal-rejoin")
    proposal = WholeScopeHierarchyProposal(
        "scope-synthetic",
        tuple(_beat(key, units[index : index + 1]) for index, key in enumerate(beat_keys)),
        (
            ProposedMajorCluster(
                "cluster-choice",
                beat_keys,
                0.9,
                "Question, alternatives, and shared continuation.",
            ),
        ),
    )

    choice_lock = HierarchyHardLock(
        "choice-cluster-lock",
        HierarchyHardLockKind.CHOICE_OWNERSHIP,
        unit_ids=(units[0].unit_id, units[-1].unit_id),
        choice_id="choice-one",
        arm_ids=("arm-a", "arm-b"),
    )
    evidence_by_unit = {
        unit.unit_id: (
            SemanticEvidenceRecord(
                unit.unit_id,
                unit.story_atom_id,
                unit.evidence_ids[0],
                unit.ordinal,
                "narration",
                "Synthetic choice evidence.",
                None,
                unit.story_locator,
            ),
        )
        for unit in units
    }
    serialized = whole_scope_hierarchy_input_payload(
        _authority(),
        "scope-synthetic",
        units,
        evidence_by_unit,
        (choice_lock,),
    )
    serialized_units = serialized["units"]
    serialized_locks = serialized["hard_locks"]
    assert isinstance(serialized_units, list)
    assert isinstance(serialized_locks, list)
    assert {item["lane_id"] for item in serialized_units} == {
        "lane-main",
        "lane-arm-a",
        "lane-arm-b",
        "lane-rejoin",
    }
    serialized_evidence = serialized["evidence"]
    assert isinstance(serialized_evidence, list)
    assert {item["unit_id"] for item in serialized_evidence} == {
        unit.unit_id for unit in units
    }
    assert serialized_locks[0]["unit_ids"] == [units[0].unit_id, units[-1].unit_id]
    missing_evidence = dict(evidence_by_unit)
    missing_evidence.pop(units[0].unit_id)
    with pytest.raises(ValueError, match="each Stage H unit requires exact transient evidence"):
        whole_scope_hierarchy_input_payload(
            _authority(),
            "scope-synthetic",
            units,
            missing_evidence,
            (choice_lock,),
        )
    validate_whole_scope_hierarchy(
        proposal,
        units,
        (),
        (choice,),
        (choice_lock,),
    )
    _assert_exact_assembler_round_trip(proposal, units, (), choices=(choice,))

    context_split = WholeScopeHierarchyProposal(
        "scope-synthetic",
        proposal.beat_groups,
        tuple(
            ProposedMajorCluster(
                f"cluster-context-{index}",
                (beat_key,),
                0.9,
                "Incorrectly split choice context.",
            )
            for index, beat_key in enumerate(beat_keys)
        ),
    )
    with pytest.raises(
        HierarchyAuthorityError, match="splits a required choice cluster"
    ) as captured:
        validate_whole_scope_hierarchy(
            context_split,
            units,
            (),
            (choice,),
            (choice_lock,),
        )
    assert captured.value.code == "choice_cluster_split"


def test_stable_ids_ignore_temporary_proposal_keys() -> None:
    units, candidates = _linear_authority()
    first = validate_whole_scope_hierarchy(_proposal(units), units, candidates)
    renamed = validate_whole_scope_hierarchy(
        _proposal(
            units,
            beat_keys=("temporary-x", "temporary-y", "temporary-z"),
            cluster_keys=("temporary-section-x", "temporary-section-y"),
        ),
        units,
        candidates,
    )

    assert [item[1] for item in derive_stable_hierarchy_ids(first).beat_ids] == [
        item[1] for item in derive_stable_hierarchy_ids(renamed).beat_ids
    ]
    assert [item[1] for item in derive_stable_hierarchy_ids(first).cluster_ids] == [
        item[1] for item in derive_stable_hierarchy_ids(renamed).cluster_ids
    ]


def test_published_beat_ids_change_when_validated_membership_changes() -> None:
    units, candidates = _linear_authority()
    base = validate_whole_scope_hierarchy(_proposal(units), units, candidates)
    changed_proposal = WholeScopeHierarchyProposal(
        "scope-synthetic",
        (
            _beat("proposal-a", units[:1]),
            _beat("proposal-b", units[1:3]),
            _beat("proposal-c", units[3:]),
        ),
        _proposal(units).major_clusters,
    )
    changed = validate_whole_scope_hierarchy(changed_proposal, units, candidates)

    base_ids = derive_stable_hierarchy_ids(base)
    changed_ids = derive_stable_hierarchy_ids(changed)
    assert base_ids.beat_ids != changed_ids.beat_ids


@pytest.mark.parametrize("malformation", ["missing", "duplicate", "foreign", "reordered"])
def test_inexact_unit_coverage_fails_closed(malformation: str) -> None:
    units, candidates = _linear_authority()
    base = _proposal(units)
    groups = list(base.beat_groups)
    if malformation == "missing":
        groups[2] = replace(groups[2], ordered_unit_ids=groups[2].ordered_unit_ids[:-1])
        match = "missing"
    elif malformation == "duplicate":
        groups[1] = replace(groups[1], ordered_unit_ids=(units[1].unit_id,))
        match = "duplicates"
    elif malformation == "foreign":
        groups[1] = replace(groups[1], ordered_unit_ids=("foreign-unit",))
        match = "foreign"
    else:
        groups[0] = replace(
            groups[0], ordered_unit_ids=(units[1].unit_id, units[0].unit_id)
        )
        match = "reordered"
    malformed = replace(base, beat_groups=tuple(groups))

    with pytest.raises(ValueError, match=match):
        validate_whole_scope_hierarchy(malformed, units, candidates)


def test_noncontiguous_same_sequence_membership_fails_before_compilation() -> None:
    units, candidates = _linear_authority()
    base = _proposal(units)
    malformed = replace(
        base,
        beat_groups=(
            replace(
                base.beat_groups[0],
                ordered_unit_ids=(units[0].unit_id, units[2].unit_id),
            ),
            replace(base.beat_groups[1], ordered_unit_ids=(units[1].unit_id,)),
            base.beat_groups[2],
        ),
    )

    with pytest.raises(ValueError, match="noncontiguous"):
        validate_whole_scope_hierarchy(malformed, units, candidates)


def test_reordered_missing_or_foreign_gap_authority_fails_closed() -> None:
    units, candidates = _linear_authority()
    proposal = _proposal(units)

    with pytest.raises(ValueError, match="exact exhaustive"):
        validate_whole_scope_hierarchy(proposal, units, tuple(reversed(candidates)))
    with pytest.raises(ValueError, match="exact exhaustive"):
        validate_whole_scope_hierarchy(proposal, units, candidates[:-1])
    foreign = replace(candidates[-1], evidence_ids=("foreign-evidence",))
    with pytest.raises(ValueError, match="exact exhaustive"):
        validate_whole_scope_hierarchy(proposal, units, (*candidates[:-1], foreign))


def test_scope_authority_and_hard_lock_identities_are_exact() -> None:
    units, candidates = _linear_authority()
    proposal = _proposal(units)

    with pytest.raises(ValueError, match="scope identity"):
        validate_whole_scope_hierarchy(
            proposal, units, candidates, scope_id="scope-foreign"
        )
    with pytest.raises(ValueError, match="foreign or stale authority"):
        validate_whole_scope_hierarchy(
            proposal,
            units,
            candidates,
            authority=AuthorityBinding(
                "foreign", "m10-v1", "m10-hash", "m11-v1", "m11-hash"
            ),
        )

    lock = HierarchyHardLock(
        "lock-duplicate",
        HierarchyHardLockKind.SEPARATE_BEAT,
        left_unit_id=units[1].unit_id,
        right_unit_id=units[2].unit_id,
    )
    with pytest.raises(ValueError, match="duplicate hard-lock identity"):
        validate_whole_scope_hierarchy(
            proposal, units, candidates, hard_locks=(lock, lock)
        )


def test_generalized_boundary_hard_lock_mapping_is_fail_closed() -> None:
    units, candidates = _linear_authority()
    raw_lock: dict[str, object] = {
        "lock_id": "lock-rejoin",
        "kind": "proven_rejoin",
        "left_unit_id": units[0].unit_id,
        "right_unit_id": units[1].unit_id,
    }

    with pytest.raises(ValueError, match="required beat hard lock"):
        validate_whole_scope_hierarchy(
            _proposal(units), units, candidates, hard_locks=(raw_lock,)
        )


def test_cross_sequence_lane_call_loop_and_choice_owners_are_rejected() -> None:
    units = (
        _unit("main", "main", 0),
        _unit(
            "arm",
            "arm-a",
            0,
            lane_id="lane-arm",
            call_occurrence_id="call-one",
            loop_id="loop-one",
            parent_choice_id="choice-one",
            parent_arm_id="arm-a",
        ),
    )
    choice = ChoiceComposition(
        "choice-one",
        "cluster-owner",
        None,
        None,
        ("arm-a", "arm-b"),
        ("Take A", "Take B"),
        (),
        ("rejoin-a", "rejoin-b"),
        "node-rejoin",
        None,
    )
    proposal = WholeScopeHierarchyProposal(
        "scope-synthetic",
        (_beat("proposal-cross-owner", units),),
        (
            ProposedMajorCluster(
                "proposal-cluster", ("proposal-cross-owner",), 0.9, "Invalid crossing."
            ),
        ),
    )

    with pytest.raises(ValueError, match="crosses sequence or deterministic ownership"):
        validate_whole_scope_hierarchy(proposal, units, (), (choice,))


def test_uncertainty_and_authoritative_looking_temporary_keys_fail_closed() -> None:
    units, candidates = _linear_authority()
    uncertain = replace(_proposal(units), uncertain_unit_ids=(units[0].unit_id,))
    with pytest.raises(ValueError, match="uncertainty fails closed"):
        validate_whole_scope_hierarchy(uncertain, units, candidates)

    base = _proposal(units)
    authoritative_key = replace(
        base,
        beat_groups=(
            replace(base.beat_groups[0], proposal_key=units[0].unit_id),
            *base.beat_groups[1:],
        ),
        major_clusters=(
            replace(
                base.major_clusters[0],
                ordered_beat_keys=(units[0].unit_id, base.beat_groups[1].proposal_key),
            ),
            base.major_clusters[1],
        ),
    )
    with pytest.raises(ValueError, match="collides with authoritative"):
        validate_whole_scope_hierarchy(authoritative_key, units, candidates)


def test_scope_marker_and_required_boundary_hard_locks_are_enforced() -> None:
    units, candidates = _linear_authority()
    base = _proposal(units)
    marker_lock = HierarchyHardLock(
        "lock-marker", HierarchyHardLockKind.SCOPE_MARKER, unit_ids=(units[5].unit_id,)
    )
    with pytest.raises(ValueError, match="isolating hard lock"):
        validate_whole_scope_hierarchy(base, units, candidates, hard_locks=(marker_lock,))

    boundary_lock = HierarchyHardLock(
        "lock-section",
        HierarchyHardLockKind.SEPARATE_MAJOR_CLUSTER,
        left_unit_id=units[1].unit_id,
        right_unit_id=units[2].unit_id,
    )
    with pytest.raises(ValueError, match="major-cluster hard lock"):
        validate_whole_scope_hierarchy(base, units, candidates, hard_locks=(boundary_lock,))


def test_choice_ownership_hard_lock_requires_exact_ordered_arms() -> None:
    units = (
        _unit(
            "arm-a",
            "arm-a-sequence",
            0,
            parent_choice_id="choice-one",
            parent_arm_id="arm-a",
        ),
        _unit(
            "arm-b",
            "arm-b-sequence",
            0,
            parent_choice_id="choice-one",
            parent_arm_id="arm-b",
        ),
    )
    choice = ChoiceComposition(
        "choice-one",
        "cluster-owner",
        None,
        None,
        ("arm-a", "arm-b"),
        ("Take A", "Take B"),
        (),
        ("rejoin-a", "rejoin-b"),
        "node-rejoin",
        None,
    )
    proposal = WholeScopeHierarchyProposal(
        "scope-synthetic",
        (_beat("proposal-a", units[:1]), _beat("proposal-b", units[1:])),
        (
            ProposedMajorCluster(
                "proposal-choice", ("proposal-a", "proposal-b"), 0.9, "Choice alternatives."
            ),
        ),
    )
    invalid_lock = HierarchyHardLock(
        "lock-choice",
        HierarchyHardLockKind.CHOICE_OWNERSHIP,
        choice_id="choice-one",
        arm_ids=("arm-b", "arm-a"),
    )

    with pytest.raises(ValueError, match="choice-ownership hard lock"):
        validate_whole_scope_hierarchy(
            proposal, units, (), (choice,), hard_locks=(invalid_lock,)
        )
