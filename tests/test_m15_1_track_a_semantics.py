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
from renpy_story_mapper.m11_scene_model import AtomKind
from renpy_story_mapper.narrative_map import (
    AuthorityBinding,
    ChoiceComposition,
    FineNarrativeUnit,
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
