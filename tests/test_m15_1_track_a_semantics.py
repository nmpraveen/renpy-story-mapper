from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from m15_test_support import linear_authority
from renpy_story_mapper.canonical_graph_contract import (
    CANONICAL_GRAPH_SCHEMA,
    CanonicalEdge,
    CanonicalGraph,
    CanonicalNodeKind,
    CanonicalRegion,
    DerivedProof,
    OriginReference,
    ReachabilityStatus,
)
from renpy_story_mapper.m11_scene_model import (
    AtomKind,
    CallSiteOccurrence,
    OccurrenceKind,
)
from renpy_story_mapper.m11_scene_model import (
    Provenance as M11Provenance,
)
from renpy_story_mapper.narrative_map import (
    AuthorityBinding,
    ChoiceComposition,
    FineNarrativeUnit,
    LiveSemanticProvenance,
    Provenance,
    SemanticBoundaryDecision,
    SemanticBoundaryKind,
    SourceLocator,
    assemble_semantic_outline,
    build_all_eligible_gap_candidates,
    build_boundary_windows,
    build_choice_compositions,
    build_fine_narrative_units,
    build_semantic_quotient_topology,
    semantic_membership_hash,
    semantic_outline_to_dict,
    stable_m15_id,
)
from renpy_story_mapper.narrative_map.semantic_contracts import SemanticOutline

ROOT = Path(__file__).resolve().parents[1]


def _authority() -> AuthorityBinding:
    return AuthorityBinding("synthetic", "m10-v1", "m10-hash", "m11-v1", "m11-hash")


def _unit(
    key: str,
    sequence_id: str,
    ordinal: int,
    line: int,
    parent_choice_id: str | None = None,
    parent_arm_id: str | None = None,
) -> FineNarrativeUnit:
    node_id = f"node-{key}"
    evidence_id = f"evidence-{key}"
    locator = SourceLocator("game/generalized.rpy", line, line, "physical_source")
    return FineNarrativeUnit(
        authority=_authority(),
        sequence_id=sequence_id,
        ordinal=ordinal,
        story_atom_id=f"atom-{key}",
        story_locator=locator,
        technical_context_atom_ids=(),
        node_ids=(node_id,),
        evidence_ids=(evidence_id,),
        speaker_ids=(),
        context_ids=(),
        lane_id="lane_story_spine",
        call_occurrence_id=None,
        loop_id=None,
        parent_choice_id=parent_choice_id,
        parent_arm_id=parent_arm_id,
        entry_node_id=node_id,
        exit_node_id=node_id,
        incident_edge_ids=(),
        provenance=Provenance(
            atom_ids=(f"atom-{key}",),
            node_ids=(node_id,),
            evidence_ids=(evidence_id,),
            locators=(locator,),
        ),
    )


def _generalized_outline() -> tuple[
    tuple[FineNarrativeUnit, ...],
    tuple[SemanticBoundaryDecision, ...],
    tuple[ChoiceComposition, ...],
    SemanticOutline,
]:
    fixture = json.loads((ROOT / "tests/fixtures/m15_1/track_a_semantics_v2.json").read_text())
    units = tuple(
        _unit(
            str(item[0]),
            str(item[1]),
            int(item[2]),
            line,
            str(item[3]) if len(item) > 3 else None,
            str(item[4]) if len(item) > 4 else None,
        )
        for line, item in enumerate(fixture["spine"], start=1)
    )
    candidates = build_all_eligible_gap_candidates(units)
    assert len(candidates) == len(fixture["coarse_decisions"])
    decisions = tuple(
        SemanticBoundaryDecision(
            candidate.candidate_id,
            SemanticBoundaryKind(raw_kind),
            f"Generalized decision {index}",
            0.9,
        )
        for index, (candidate, raw_kind) in enumerate(
            zip(candidates, fixture["coarse_decisions"], strict=True)
        )
    )
    provisional = assemble_semantic_outline(units, candidates, decisions)
    assert isinstance(provisional, SemanticOutline)
    unit_by_key = {str(item[0]): unit for item, unit in zip(fixture["spine"], units, strict=True)}
    cluster_by_unit = {
        unit_id: beat.parent_cluster_id
        for beat in provisional.beats
        for unit_id in beat.ordered_unit_ids
    }
    parent_cluster = cluster_by_unit[unit_by_key["outer_question"].unit_id]
    continuation_id = unit_by_key[str(fixture["post_rejoin_continuation_key"])].unit_id
    raw_choices = fixture["choices"]
    assert isinstance(raw_choices, list)
    outer_raw = _mapping(raw_choices[0])
    inner_raw = _mapping(raw_choices[1])
    choices = (
        ChoiceComposition(
            choice_id=str(outer_raw["choice_id"]),
            parent_cluster_id=parent_cluster,
            parent_choice_id=None,
            parent_arm_id=None,
            ordered_arm_ids=_strings(outer_raw["ordered_arm_ids"]),
            ordered_arm_captions=_strings(outer_raw["ordered_arm_captions"]),
            child_choice_ids=_strings(outer_raw["child_choice_ids"]),
            rejoin_relationship_ids=("rejoin-outer-stop", "rejoin-outer-continue"),
            shared_target_id=str(fixture["shared_target_id"]),
            post_rejoin_continuation_id=continuation_id,
        ),
        ChoiceComposition(
            choice_id=str(inner_raw["choice_id"]),
            parent_cluster_id=parent_cluster,
            parent_choice_id=str(inner_raw["parent_choice_id"]),
            parent_arm_id=str(inner_raw["parent_arm_id"]),
            ordered_arm_ids=_strings(inner_raw["ordered_arm_ids"]),
            ordered_arm_captions=_strings(inner_raw["ordered_arm_captions"]),
            child_choice_ids=(),
            rejoin_relationship_ids=("rejoin-inner-stop", "rejoin-inner-continue"),
            shared_target_id=str(fixture["shared_target_id"]),
            post_rejoin_continuation_id=continuation_id,
        ),
    )
    outline = assemble_semantic_outline(
        units,
        candidates,
        decisions,
        choices=choices,
    )
    assert isinstance(outline, SemanticOutline)
    return units, decisions, choices, outline


def _mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping)
    return value


def _strings(value: object) -> tuple[str, ...]:
    assert isinstance(value, list)
    assert all(isinstance(item, str) for item in value)
    return tuple(str(item) for item in value)


def test_fine_units_attach_technical_context_once_and_enumerate_every_gap() -> None:
    canonical, model = linear_authority(
        (
            AtomKind.NARRATION,
            AtomKind.TECHNICAL,
            AtomKind.DIALOGUE,
            AtomKind.NARRATION,
        )
    )

    units = build_fine_narrative_units(canonical, model)
    candidates = build_all_eligible_gap_candidates(units)

    assert [item.story_atom_id for item in units] == ["atom-0", "atom-2", "atom-3"]
    assert [item for unit in units for item in unit.technical_context_atom_ids] == ["atom-1"]
    assert len(candidates) == len(units) - 1
    assert [(item.left_unit_id, item.right_unit_id) for item in candidates] == [
        (units[0].unit_id, units[1].unit_id),
        (units[1].unit_id, units[2].unit_id),
    ]


def test_split_call_loop_terminal_and_unresolved_locks_never_emit_crossing_gaps() -> None:
    canonical, model = linear_authority(
        (
            AtomKind.NARRATION,
            AtomKind.CHOICE,
            AtomKind.NARRATION,
            AtomKind.CALL,
            AtomKind.NARRATION,
            AtomKind.LOOP,
            AtomKind.NARRATION,
            AtomKind.UNRESOLVED,
            AtomKind.NARRATION,
            AtomKind.TERMINAL,
        )
    )

    units = build_fine_narrative_units(canonical, model)

    assert build_all_eligible_gap_candidates(units) == ()
    assert len({item.sequence_id for item in units}) == len(units)


def test_four_state_hierarchy_splits_coarse_story_and_resumes_once_after_nested_rejoin() -> None:
    units, decisions, choices, outline = _generalized_outline()

    coarse_ids = {item.unit_id for item in units if item.sequence_id == "coarse"}
    coarse_beats = [
        beat for beat in outline.beats if coarse_ids.intersection(beat.ordered_unit_ids)
    ]
    assert {item.decision for item in decisions} == set(SemanticBoundaryKind)
    assert len(coarse_beats) == 4
    assert len({item.parent_cluster_id for item in coarse_beats}) == 2
    assert choices[1].parent_choice_id == choices[0].choice_id
    assert choices[1].parent_arm_id == "outer_continue"
    assert choices[0].ordered_arm_captions == ("Stop here", "Keep going")
    assert (
        len(
            {
                item.post_rejoin_continuation_id
                for item in choices
                if item.post_rejoin_continuation_id is not None
            }
        )
        == 1
    )
    continuation_id = choices[0].post_rejoin_continuation_id
    assert sum(continuation_id in beat.ordered_unit_ids for beat in outline.beats) == 1
    continuation_beat = next(
        beat for beat in outline.beats if continuation_id in beat.ordered_unit_ids
    )
    assert continuation_beat.parent_choice_id is None
    assert [item for beat in outline.beats for item in beat.ordered_unit_ids] == list(
        outline.ordered_unit_ids
    )


def test_missing_duplicate_and_foreign_semantic_decisions_fail_closed() -> None:
    units, decisions, _choices, _outline = _generalized_outline()
    candidates = build_all_eligible_gap_candidates(units)
    with pytest.raises(ValueError, match="missing or incomplete"):
        assemble_semantic_outline(units, candidates, decisions[:-1])
    with pytest.raises(ValueError, match="duplicate"):
        assemble_semantic_outline(units, candidates, (*decisions, decisions[0]))
    foreign = SemanticBoundaryDecision(
        "foreign-gap", SemanticBoundaryKind.SAME_BEAT, "Foreign", 1.0
    )
    with pytest.raises(ValueError, match="foreign or stale"):
        assemble_semantic_outline(units, candidates, (*decisions[:-1], foreign))


def test_boundary_provenance_binds_by_exact_candidate_and_window_identity() -> None:
    units, decisions, choices, _outline = _generalized_outline()
    candidates = build_all_eligible_gap_candidates(units)
    windows = build_boundary_windows(
        units,
        candidates,
        maximum_owned_candidates=2,
        context_halo_units=1,
    )
    window_by_candidate = {
        candidate_id: window.window_id
        for window in windows
        for candidate_id in window.owned_candidate_ids
    }
    provenance = tuple(
        LiveSemanticProvenance(
            "boundaries",
            f"job-{index}",
            f"input-{index}",
            "manifest-generalized",
            "provider-identity",
            f"cache-{index}",
            candidate_id=candidate.candidate_id,
            window_id=window_by_candidate[candidate.candidate_id],
        )
        for index, candidate in enumerate(candidates)
    )

    outline = assemble_semantic_outline(
        units,
        candidates,
        decisions,
        choices=choices,
        boundary_windows=windows,
        boundary_provenance=tuple(reversed(provenance)),
    )

    assert isinstance(outline, SemanticOutline)
    assert [item.candidate_id for item in outline.boundary_provenance] == [
        item.candidate_id for item in candidates
    ]
    serialized = semantic_outline_to_dict(outline)
    serialized_provenance = serialized["boundary_provenance"]
    assert isinstance(serialized_provenance, list)
    assert [item["candidate_id"] for item in serialized_provenance] == [
        item.candidate_id for item in candidates
    ]
    duplicated = (provenance[0], provenance[0], *provenance[2:])
    with pytest.raises(ValueError, match="requires its exact boundary windows"):
        assemble_semantic_outline(
            units,
            candidates,
            decisions,
            choices=choices,
            boundary_provenance=provenance,
        )
    with pytest.raises(ValueError, match="duplicates one candidate"):
        assemble_semantic_outline(
            units,
            candidates,
            decisions,
            choices=choices,
            boundary_windows=windows,
            boundary_provenance=duplicated,
        )
    foreign_window = replace(provenance[0], window_id="foreign-window")
    with pytest.raises(ValueError, match="foreign candidate/window ownership"):
        assemble_semantic_outline(
            units,
            candidates,
            decisions,
            choices=choices,
            boundary_windows=windows,
            boundary_provenance=(foreign_window, *provenance[1:]),
        )


def test_canonical_edge_tuple_order_cannot_change_fine_units_or_candidates() -> None:
    canonical, model = linear_authority((AtomKind.NARRATION, AtomKind.DIALOGUE, AtomKind.NARRATION))
    reversed_authority = replace(canonical, edges=tuple(reversed(canonical.edges)))
    reversed_authority.validate()

    assert reversed_authority.authority_hash == canonical.authority_hash
    expected_units = build_fine_narrative_units(canonical, model)
    actual_units = build_fine_narrative_units(reversed_authority, model)
    assert actual_units == expected_units
    assert build_all_eligible_gap_candidates(actual_units) == (
        build_all_eligible_gap_candidates(expected_units)
    )


def test_m11_call_occurrences_duplicate_shared_callee_units_without_cross_locking() -> None:
    canonical, model = linear_authority((AtomKind.CALL, AtomKind.NARRATION, AtomKind.DIALOGUE))
    occurrence_provenance = M11Provenance(
        node_ids=tuple(item.id for item in canonical.nodes),
        edge_ids=tuple(item.id for item in canonical.edges),
        evidence_ids=tuple(item.id for item in canonical.evidence),
    )
    occurrences = tuple(
        CallSiteOccurrence(
            id=f"occurrence-{suffix}",
            call_atom_id="atom-0",
            callee_entry_node_id="node-1",
            kind=OccurrenceKind.NARRATIVE,
            scene_id=model.scenes[0].id,
            lane_id=model.scenes[0].lane_id,
            referenced_atom_ids=("atom-1", "atom-2"),
            guard_fact_ids=(),
            collapsed=False,
            repeatable=False,
            provenance=occurrence_provenance,
        )
        for suffix in ("a", "b")
    )
    occurrence_model = replace(model, occurrences=occurrences)
    occurrence_model.validate()

    units = build_fine_narrative_units(canonical, occurrence_model)
    candidates = build_all_eligible_gap_candidates(units)

    assert [item.story_atom_id for item in units] == [
        "atom-0",
        "atom-1",
        "atom-2",
        "atom-0",
        "atom-1",
        "atom-2",
    ]
    assert [item.call_occurrence_id for item in units] == [
        "occurrence-a",
        "occurrence-a",
        "occurrence-a",
        "occurrence-b",
        "occurrence-b",
        "occurrence-b",
    ]
    assert len(candidates) == 2
    assert [item.call_occurrence_id for item in candidates] == [
        "occurrence-a",
        "occurrence-b",
    ]
    decisions = tuple(
        SemanticBoundaryDecision(
            item.candidate_id,
            SemanticBoundaryKind.NEW_BEAT_SAME_CLUSTER,
            "Keep occurrence-local turns distinct.",
            1.0,
        )
        for item in candidates
    )
    outline = assemble_semantic_outline(units, candidates, decisions)
    assert isinstance(outline, SemanticOutline)
    topology = build_semantic_quotient_topology(canonical, units, outline)
    assert sum("edge-0" in item.authority_edge_ids for item in topology.edges) == 2
    assert sum("edge-1" in item.authority_edge_ids for item in topology.edges) == 2


def test_nested_occurrence_instances_are_qualified_by_their_outer_call_path() -> None:
    canonical, model = linear_authority(
        (
            AtomKind.CALL,
            AtomKind.CALL,
            AtomKind.NARRATION,
            AtomKind.CALL,
            AtomKind.NARRATION,
            AtomKind.DIALOGUE,
        )
    )
    occurrence_provenance = M11Provenance(
        node_ids=tuple(item.id for item in canonical.nodes),
        edge_ids=tuple(item.id for item in canonical.edges),
        evidence_ids=tuple(item.id for item in canonical.evidence),
    )
    occurrences = (
        CallSiteOccurrence(
            "outer-a",
            "atom-0",
            "node-2",
            OccurrenceKind.NARRATIVE,
            model.scenes[0].id,
            model.scenes[0].lane_id,
            ("atom-2", "atom-3"),
            (),
            False,
            False,
            occurrence_provenance,
        ),
        CallSiteOccurrence(
            "outer-b",
            "atom-1",
            "node-2",
            OccurrenceKind.NARRATIVE,
            model.scenes[0].id,
            model.scenes[0].lane_id,
            ("atom-2", "atom-3"),
            (),
            False,
            False,
            occurrence_provenance,
        ),
        CallSiteOccurrence(
            "nested-static",
            "atom-3",
            "node-4",
            OccurrenceKind.NARRATIVE,
            model.scenes[0].id,
            model.scenes[0].lane_id,
            ("atom-4", "atom-5"),
            (),
            False,
            False,
            occurrence_provenance,
        ),
    )
    occurrence_model = replace(model, occurrences=occurrences)
    occurrence_model.validate()

    units = build_fine_narrative_units(canonical, occurrence_model)
    nested_units = [item for item in units if item.story_atom_id == "atom-3"]

    assert len(nested_units) == 2
    assert len({item.call_occurrence_id for item in nested_units}) == 2
    assert {item.call_occurrence_path for item in nested_units} == {
        ("outer-a", "nested-static"),
        ("outer-b", "nested-static"),
    }
    candidates = build_all_eligible_gap_candidates(units)
    decisions = tuple(
        SemanticBoundaryDecision(
            item.candidate_id,
            SemanticBoundaryKind.NEW_BEAT_SAME_CLUSTER,
            "Keep nested occurrence-local turns distinct.",
            1.0,
        )
        for item in candidates
    )
    outline = assemble_semantic_outline(units, candidates, decisions)
    assert isinstance(outline, SemanticOutline)
    topology = build_semantic_quotient_topology(canonical, units, outline)
    assert topology.edges


def test_shared_call_anchors_cannot_bridge_sibling_occurrence_paths() -> None:
    base, _model = linear_authority((AtomKind.NARRATION,) * 8)
    edge_specs = (
        ("alpha-enter", "node-0", "node-2", "call_enter", "site-alpha"),
        ("beta-enter", "node-1", "node-2", "call_enter", "site-beta"),
        ("shared-body", "node-2", "node-3", "continuation", None),
        ("shared-return", "node-3", "node-4", "continuation", None),
        ("alpha-return", "node-4", "node-5", "call_return", "site-alpha"),
        ("beta-return", "node-4", "node-6", "call_return", "site-beta"),
        ("direct-enter", "node-7", "node-2", "jump", None),
    )
    edges = tuple(
        CanonicalEdge(
            edge_id,
            source_id,
            target_id,
            kind,
            ReachabilityStatus.PROVEN_REACHABLE,
            True,
            ("evidence-0",),
            (),
            (OriginReference("synthetic", edge_id),),
            {
                "gate_ids": [],
                "effect_ids": [],
                "call_site_id": call_site_id,
            },
        )
        for edge_id, source_id, target_id, kind, call_site_id in edge_specs
    )
    canonical = replace(base, edges=edges)
    canonical.validate()
    authority = AuthorityBinding(
        canonical.source_generation,
        CANONICAL_GRAPH_SCHEMA,
        canonical.authority_hash,
        "m11-shared-anchors-v1",
        "m11-shared-anchors-hash",
    )
    unit_specs = (
        ("alpha-call", "node-0", ("occ-alpha",), ("site-alpha",)),
        ("beta-call", "node-1", ("occ-beta",), ("site-beta",)),
        ("direct-jump", "node-7", (), ()),
        ("alpha-dialogue", "node-3", ("occ-alpha",), ("site-alpha",)),
        ("beta-dialogue", "node-3", ("occ-beta",), ("site-beta",)),
        ("direct-dialogue", "node-3", (), ()),
        ("alpha-after", "node-5", (), ()),
        ("beta-after", "node-6", (), ()),
    )
    units = tuple(
        replace(
            (base_unit := _unit(key, key, 0, index + 1)),
            authority=authority,
            node_ids=(node_id,),
            call_occurrence_id=(occurrence_path[-1] if occurrence_path else None),
            call_occurrence_path=occurrence_path,
            call_site_path=call_site_path,
            entry_node_id=node_id,
            exit_node_id=node_id,
            provenance=replace(base_unit.provenance, node_ids=(node_id,)),
        )
        for index, (key, node_id, occurrence_path, call_site_path) in enumerate(unit_specs)
    )
    outline = assemble_semantic_outline(units, (), ())
    assert isinstance(outline, SemanticOutline)
    topology = build_semantic_quotient_topology(canonical, units, outline)
    beat_by_unit = {
        unit_id: beat.beat_id for beat in outline.beats for unit_id in beat.ordered_unit_ids
    }
    start = beat_by_unit[units[0].unit_id]
    forbidden = beat_by_unit[units[4].unit_id]
    outgoing: dict[str, set[str]] = {}
    for edge in topology.edges:
        outgoing.setdefault(edge.source_subject_id, set()).add(edge.target_subject_id)
    pending = [start]
    reached: set[str] = set()
    while pending:
        subject_id = pending.pop()
        if subject_id in reached:
            continue
        reached.add(subject_id)
        pending.extend(outgoing.get(subject_id, ()))

    assert beat_by_unit[units[3].unit_id] in reached
    assert forbidden not in reached
    direct_pending = [beat_by_unit[units[2].unit_id]]
    direct_reached: set[str] = set()
    while direct_pending:
        subject_id = direct_pending.pop()
        if subject_id in direct_reached:
            continue
        direct_reached.add(subject_id)
        direct_pending.extend(outgoing.get(subject_id, ()))
    assert beat_by_unit[units[5].unit_id] in direct_reached
    assert beat_by_unit[units[3].unit_id] not in direct_reached
    assert beat_by_unit[units[4].unit_id] not in direct_reached


def test_boundary_windows_own_every_candidate_once_with_bounded_same_sequence_halos() -> None:
    units, _decisions, _choices, _outline = _generalized_outline()
    candidates = build_all_eligible_gap_candidates(units)

    windows = build_boundary_windows(
        units,
        candidates,
        maximum_owned_candidates=2,
        context_halo_units=1,
    )

    assert [item for window in windows for item in window.owned_candidate_ids] == [
        item.candidate_id for item in candidates
    ]
    assert all(len(item.owned_candidate_ids) <= 2 for item in windows)
    assert all(len(item.context_unit_ids) <= item.maximum_context_units for item in windows)
    assert all(
        len(
            {
                next(unit.sequence_id for unit in units if unit.unit_id == context_id)
                for context_id in window.context_unit_ids
            }
        )
        == 1
        for window in windows
    )
    with pytest.raises(ValueError, match="exact exhaustive"):
        build_boundary_windows(units, candidates[:-1])


def test_semantic_quotient_copies_only_m10_edges_gates_effects_and_evidence() -> None:
    canonical, model = linear_authority(
        (AtomKind.NARRATION, AtomKind.UNRESOLVED, AtomKind.TERMINAL),
        edge_attributes=(
            {"gate_ids": ["gate-1"], "effect_ids": ["effect-1"]},
            {"gate_ids": [], "effect_ids": []},
        ),
    )
    units = build_fine_narrative_units(canonical, model)
    outline = assemble_semantic_outline(units, (), ())
    assert isinstance(outline, SemanticOutline)

    topology = build_semantic_quotient_topology(canonical, units, outline)

    assert {item for edge in topology.edges for item in edge.authority_edge_ids} == {
        "edge-0",
        "edge-1",
    }
    gated = next(item for item in topology.edges if "edge-0" in item.authority_edge_ids)
    assert gated.requirement_ids == ("gate-1",)
    assert gated.effect_ids == ("effect-1",)
    assert gated.evidence_ids == ("evidence-0",)
    assert topology.to_dict()["canonical_hash"] == canonical.authority_hash
    assert (
        stable_m15_id(
            "semantic_topology_edge",
            {
                "canonical_hash": canonical.authority_hash,
                "source": gated.source_subject_id,
                "target": gated.target_subject_id,
                "kind": gated.kind.value,
                "authority_edge_ids": list(gated.authority_edge_ids),
            },
        )
        == gated.edge_id
    )
    serialized = semantic_outline_to_dict(outline)
    assert serialized["membership_hash"] == semantic_membership_hash(outline)
    assert serialized["ordered_unit_ids"] == [item.unit_id for item in units]


def test_m10_regions_own_exact_arm_order_captions_nesting_and_shared_rejoin() -> None:
    canonical = _nested_choice_canonical()
    authority = AuthorityBinding(
        canonical.source_generation,
        CANONICAL_GRAPH_SCHEMA,
        canonical.authority_hash,
        "m11-synthetic-v1",
        "m11-synthetic-hash",
    )
    specs = (
        ("opening", "node-0", None, None),
        ("outer-question", "node-1", None, None),
        ("outer-stop", "node-2", "choice-outer", "outer-stop"),
        ("outer-continue", "node-3", "choice-outer", "outer-continue"),
        ("inner-question", "node-4", "choice-outer", "outer-continue"),
        ("inner-stop", "node-5", "choice-inner", "inner-stop"),
        ("inner-continue", "node-6", "choice-inner", "inner-continue"),
        ("resume", "node-8", None, None),
    )
    units = tuple(
        replace(
            _unit(key, key, 0, index + 1, parent_choice, parent_arm),
            authority=authority,
            node_ids=(node_id,),
            entry_node_id=node_id,
            exit_node_id=node_id,
            provenance=replace(
                _unit(key, key, 0, index + 1, parent_choice, parent_arm).provenance,
                node_ids=(node_id,),
            ),
        )
        for index, (key, node_id, parent_choice, parent_arm) in enumerate(specs)
    )
    provisional = assemble_semantic_outline(units, (), ())
    assert isinstance(provisional, SemanticOutline)

    choices = build_choice_compositions(canonical, units, provisional)

    assert [item.choice_id for item in choices] == ["choice-outer", "choice-inner"]
    assert choices[0].ordered_arm_ids == ("outer-stop", "outer-continue")
    assert choices[0].ordered_arm_captions == ("Stop now", "Continue onward")
    assert choices[1].parent_choice_id == "choice-outer"
    assert choices[1].parent_arm_id == "outer-continue"
    assert choices[1].ordered_arm_captions == ("Turn back", "Go deeper")
    assert choices[0].shared_target_id == choices[1].shared_target_id == "node-7"
    assert len(set(choices[0].rejoin_relationship_ids)) == 2
    assert set(choices[0].rejoin_relationship_ids).isdisjoint(choices[1].rejoin_relationship_ids)
    assert {item.post_rejoin_continuation_id for item in choices} == {units[-1].unit_id}

    reversed_authority = replace(canonical, regions=tuple(reversed(canonical.regions)))
    reversed_authority.validate()
    assert reversed_authority.authority_hash == canonical.authority_hash
    reversed_choices = build_choice_compositions(reversed_authority, units, provisional)
    assert reversed_choices == choices
    reversed_outline = assemble_semantic_outline(
        units,
        (),
        (),
        choices=reversed_choices,
    )
    expected_outline = assemble_semantic_outline(units, (), (), choices=choices)
    assert isinstance(reversed_outline, SemanticOutline)
    assert isinstance(expected_outline, SemanticOutline)
    assert semantic_membership_hash(reversed_outline) == semantic_membership_hash(expected_outline)


def test_shared_callee_choices_and_topology_remain_occurrence_local() -> None:
    canonical = _nested_choice_canonical()
    authority = AuthorityBinding(
        canonical.source_generation,
        CANONICAL_GRAPH_SCHEMA,
        canonical.authority_hash,
        "m11-shared-callee-v1",
        "m11-shared-callee-hash",
    )
    specs = (
        ("opening", "node-0", None, None),
        ("outer-question", "node-1", None, None),
        ("outer-stop", "node-2", "choice-outer", "outer-stop"),
        ("outer-continue", "node-3", "choice-outer", "outer-continue"),
        ("inner-question", "node-4", "choice-outer", "outer-continue"),
        ("inner-stop", "node-5", "choice-inner", "inner-stop"),
        ("inner-continue", "node-6", "choice-inner", "inner-continue"),
        ("resume", "node-8", None, None),
    )
    units_list: list[FineNarrativeUnit] = []
    for occurrence_index, occurrence_id in enumerate(("call-alpha", "call-beta", None)):
        occurrence_path = (occurrence_id,) if occurrence_id is not None else ()
        instance_label = occurrence_id or "direct"
        for index, (key, node_id, parent_choice, parent_arm) in enumerate(specs):
            qualified_parent = (
                stable_m15_id(
                    "choice_occurrence",
                    {
                        "authority": authority.to_dict(),
                        "canonical_region_id": parent_choice,
                        "call_occurrence_path": list(occurrence_path),
                    },
                )
                if parent_choice is not None and occurrence_path
                else parent_choice
                if parent_choice is not None
                else None
            )
            base = _unit(
                f"{key}-{instance_label}",
                f"{key}-{instance_label}",
                0,
                occurrence_index * len(specs) + index + 1,
                qualified_parent,
                parent_arm,
            )
            units_list.append(
                replace(
                    base,
                    authority=authority,
                    node_ids=(node_id,),
                    context_ids=occurrence_path,
                    call_occurrence_id=occurrence_id,
                    call_occurrence_path=occurrence_path,
                    call_site_path=occurrence_path,
                    entry_node_id=node_id,
                    exit_node_id=node_id,
                    provenance=replace(base.provenance, node_ids=(node_id,)),
                )
            )
    units = tuple(units_list)
    provisional = assemble_semantic_outline(units, (), ())
    assert isinstance(provisional, SemanticOutline)

    choices = build_choice_compositions(canonical, units, provisional)

    assert len(choices) == 6
    assert {item.canonical_region_id for item in choices} == {
        "choice-outer",
        "choice-inner",
    }
    assert {item.call_occurrence_path for item in choices} == {
        ("call-alpha",),
        ("call-beta",),
        (),
    }
    assert all(
        item.choice_id != item.canonical_region_id for item in choices if item.call_occurrence_path
    )
    for outer in (item for item in choices if item.canonical_region_id == "choice-outer"):
        assert len(outer.child_choice_ids) == 1
        child = next(item for item in choices if item.choice_id == outer.child_choice_ids[0])
        assert child.call_occurrence_path == outer.call_occurrence_path
        assert child.parent_choice_id == outer.choice_id

    outline = assemble_semantic_outline(units, (), (), choices=choices)
    assert isinstance(outline, SemanticOutline)
    topology = build_semantic_quotient_topology(canonical, units, outline)
    beat_by_unit = {
        unit_id: beat.beat_id for beat in outline.beats for unit_id in beat.ordered_unit_ids
    }
    alpha_subjects = {
        beat_by_unit[item.unit_id] for item in units if item.call_occurrence_path == ("call-alpha",)
    }
    beta_subjects = {
        beat_by_unit[item.unit_id] for item in units if item.call_occurrence_path == ("call-beta",)
    }
    alpha_subjects.update(
        item.choice_id for item in choices if item.call_occurrence_path == ("call-alpha",)
    )
    beta_subjects.update(
        item.choice_id for item in choices if item.call_occurrence_path == ("call-beta",)
    )
    for node in canonical.nodes:
        for occurrence_id, subjects in (
            ("call-alpha", alpha_subjects),
            ("call-beta", beta_subjects),
        ):
            subjects.add(
                stable_m15_id(
                    "semantic_structural_anchor",
                    {
                        "canonical_hash": canonical.authority_hash,
                        "canonical_node_id": node.id,
                        "call_occurrence_path": [occurrence_id],
                    },
                )
            )
            subjects.add(
                stable_m15_id(
                    "semantic_rejoin",
                    {
                        "canonical_hash": canonical.authority_hash,
                        "canonical_node_id": node.id,
                        "call_occurrence_path": [occurrence_id],
                    },
                )
            )
    assert not any(
        (edge.source_subject_id in alpha_subjects and edge.target_subject_id in beta_subjects)
        or (edge.source_subject_id in beta_subjects and edge.target_subject_id in alpha_subjects)
        for edge in topology.edges
    )


def test_choice_arm_edge_must_be_exact_and_reach_declared_rejoin() -> None:
    canonical = _nested_choice_canonical()
    outer = canonical.regions[0]
    attributes = dict(outer.attributes)
    arms = attributes["arms"]
    assert isinstance(arms, list)
    first_arm = _mapping(arms[0])
    attributes["arms"] = [{**first_arm, "edge_id": "edge-open"}, *arms[1:]]
    invalid_outer = replace(outer, attributes=attributes)
    invalid_authority = replace(canonical, regions=(invalid_outer, *canonical.regions[1:]))
    invalid_authority.validate()
    authority = AuthorityBinding(
        invalid_authority.source_generation,
        CANONICAL_GRAPH_SCHEMA,
        invalid_authority.authority_hash,
        "m11-synthetic-v1",
        "m11-synthetic-hash",
    )
    specs = (
        ("opening", "node-0"),
        ("outer-question", "node-1"),
        ("outer-stop", "node-2"),
        ("outer-continue", "node-3"),
        ("inner-question", "node-4"),
        ("inner-stop", "node-5"),
        ("inner-continue", "node-6"),
        ("resume", "node-8"),
    )
    units = tuple(
        replace(
            _unit(key, key, 0, index + 1),
            authority=authority,
            node_ids=(node_id,),
            entry_node_id=node_id,
            exit_node_id=node_id,
            provenance=replace(
                _unit(key, key, 0, index + 1).provenance,
                node_ids=(node_id,),
            ),
        )
        for index, (key, node_id) in enumerate(specs)
    )
    provisional = assemble_semantic_outline(units, (), ())
    assert isinstance(provisional, SemanticOutline)

    with pytest.raises(ValueError, match="entry edge is not exact M10 authority"):
        build_choice_compositions(invalid_authority, units, provisional)


def _nested_choice_canonical() -> CanonicalGraph:
    base, _model = linear_authority((AtomKind.NARRATION,) * 9)
    nodes = tuple(
        replace(
            node,
            kind=(
                CanonicalNodeKind.CHOICE
                if index in {1, 4}
                else CanonicalNodeKind.MERGE
                if index == 7
                else CanonicalNodeKind.SCRIPT_UNIT
            ),
            attributes={
                **node.attributes,
                "source_kind": "menu" if index in {1, 4} else "statement",
                "source_text": {
                    2: "Stop now",
                    3: "Continue onward",
                    5: "Turn back",
                    6: "Go deeper",
                }.get(index, f"Synthetic story {index}"),
            },
        )
        for index, node in enumerate(base.nodes)
    )
    origins = tuple(OriginReference("synthetic", f"edge-{index}") for index in range(9))
    edge_specs = (
        ("edge-open", 0, 1),
        ("edge-outer-stop", 1, 2),
        ("edge-outer-continue", 1, 3),
        ("edge-stop-rejoin", 2, 7),
        ("edge-to-inner", 3, 4),
        ("edge-inner-stop", 4, 5),
        ("edge-inner-continue", 4, 6),
        ("edge-inner-stop-rejoin", 5, 7),
        ("edge-inner-continue-rejoin", 6, 7),
        ("edge-resume", 7, 8),
    )
    edges = tuple(
        CanonicalEdge(
            edge_id,
            f"node-{source}",
            f"node-{target}",
            "choice" if source in {1, 4} else "continuation",
            ReachabilityStatus.PROVEN_REACHABLE,
            True,
            (f"evidence-{min(source, 8)}",),
            (),
            (origins[index % len(origins)],),
            {"gate_ids": [], "effect_ids": []},
        )
        for index, (edge_id, source, target) in enumerate(edge_specs)
    )
    proof_outer = DerivedProof(
        "proof-outer",
        "immediate_post_dominator_merge",
        (OriginReference("synthetic", "choice-outer"),),
        ("node-1", "node-7"),
        "Synthetic outer choice rejoins at node 7.",
    )
    proof_inner = DerivedProof(
        "proof-inner",
        "immediate_post_dominator_merge",
        (OriginReference("synthetic", "choice-inner"),),
        ("node-4", "node-7"),
        "Synthetic nested choice shares node 7.",
    )
    outer = CanonicalRegion(
        "choice-outer",
        "local_detour",
        "node-1",
        "node-7",
        ("node-2", "node-3", "node-4", "node-5", "node-6"),
        (OriginReference("synthetic", "choice-outer"),),
        (proof_outer.id,),
        {
            "arms": [
                {
                    "id": "outer-stop",
                    "ordinal": 0,
                    "entry_node_id": "node-2",
                    "edge_id": "edge-outer-stop",
                    "member_node_ids": ["node-2"],
                },
                {
                    "id": "outer-continue",
                    "ordinal": 1,
                    "entry_node_id": "node-3",
                    "edge_id": "edge-outer-continue",
                    "member_node_ids": ["node-3", "node-4", "node-5", "node-6"],
                },
            ]
        },
    )
    inner = CanonicalRegion(
        "choice-inner",
        "local_detour",
        "node-4",
        "node-7",
        ("node-5", "node-6"),
        (OriginReference("synthetic", "choice-inner"),),
        (proof_inner.id,),
        {
            "arms": [
                {
                    "id": "inner-stop",
                    "ordinal": 0,
                    "entry_node_id": "node-5",
                    "edge_id": "edge-inner-stop",
                    "member_node_ids": ["node-5"],
                },
                {
                    "id": "inner-continue",
                    "ordinal": 1,
                    "entry_node_id": "node-6",
                    "edge_id": "edge-inner-continue",
                    "member_node_ids": ["node-6"],
                },
            ]
        },
    )
    canonical = CanonicalGraph(
        base.source_generation,
        base.origin_generations,
        nodes,
        edges,
        (outer, inner),
        (),
        base.evidence,
        (proof_outer, proof_inner),
    )
    canonical.validate()
    return canonical
