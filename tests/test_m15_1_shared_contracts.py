from __future__ import annotations

import json
from pathlib import Path

import pytest

from renpy_story_mapper.narrative_map.contracts import AuthorityBinding, Provenance, SourceLocator
from renpy_story_mapper.narrative_map.semantic_contracts import (
    BoundaryWindow,
    ChoiceComposition,
    FineNarrativeUnit,
    NarrativeGapCandidate,
    SemanticBoundaryKind,
    SemanticBuildRecord,
    SemanticBuildState,
)

ROOT = Path(__file__).resolve().parents[1]


def _authority() -> AuthorityBinding:
    return AuthorityBinding("generation", "m10-v1", "m10-hash", "m11-v1", "m11-hash")


def _unit(ordinal: int, atom_id: str) -> FineNarrativeUnit:
    return FineNarrativeUnit(
        authority=_authority(),
        sequence_id="sequence",
        ordinal=ordinal,
        story_atom_id=atom_id,
        story_locator=SourceLocator("game/story.rpy", ordinal + 1, ordinal + 1, "reconstructed"),
        technical_context_atom_ids=(f"technical-{ordinal}",),
        node_ids=(f"node-{ordinal}",),
        evidence_ids=(f"evidence-{ordinal}",),
        speaker_ids=(),
        context_ids=(f"context-{ordinal}",),
        lane_id="main",
        call_occurrence_id=None,
        loop_id=None,
        parent_choice_id=None,
        parent_arm_id=None,
        entry_node_id=f"node-{ordinal}",
        exit_node_id=f"node-{ordinal}",
        incident_edge_ids=(),
        provenance=Provenance(atom_ids=(atom_id,), node_ids=(f"node-{ordinal}",)),
    )


def test_fine_units_are_one_story_atom_and_have_stable_identity() -> None:
    unit = _unit(0, "story-atom")
    assert unit.unit_id == _unit(0, "story-atom").unit_id
    assert unit.to_dict()["schema"] == "m15-fine-narrative-unit-v2"
    with pytest.raises(ValueError, match="cannot be technical"):
        FineNarrativeUnit(
            **{**unit.__dict__, "technical_context_atom_ids": ("story-atom",)}
        )


def test_gap_and_window_contracts_expose_exhaustive_owned_adjacency() -> None:
    left, right = _unit(0, "a"), _unit(1, "b")
    gap = NarrativeGapCandidate(
        authority=_authority(), sequence_id="sequence", ordinal=0,
        left_unit_id=left.unit_id, right_unit_id=right.unit_id, lane_id="main",
        call_occurrence_id=None, loop_id=None, parent_choice_id=None, parent_arm_id=None,
        evidence_ids=("evidence-0", "evidence-1"),
    )
    window = BoundaryWindow(_authority(), 0, (gap.candidate_id,), (left.unit_id, right.unit_id), 2)
    assert window.to_dict()["owned_candidate_ids"] == [gap.candidate_id]
    with pytest.raises(ValueError, match="context exceeds"):
        BoundaryWindow(_authority(), 0, (gap.candidate_id,), (left.unit_id, right.unit_id), 1)


def test_choice_composition_requires_explicit_nested_ownership() -> None:
    with pytest.raises(ValueError, match="both parent choice and arm"):
        ChoiceComposition(
            "inner", "cluster", "outer", None, ("a", "b"), ("A", "B"), (),
            ("rejoin-inner",), "shared-target", "continuation",
        )


def test_boundary_vocabulary_and_build_states_are_frozen() -> None:
    assert {item.value for item in SemanticBoundaryKind} == {
        "same_beat", "new_beat_same_cluster", "new_major_cluster", "uncertain"
    }
    fixture = json.loads((ROOT / "tests/fixtures/m15_1/status_transitions_v2.json").read_text())
    assert fixture["primary"] + fixture["terminal_noncomplete"] == [
        item.value for item in SemanticBuildState
    ]
    with pytest.raises(ValueError, match="complete semantic build"):
        SemanticBuildRecord(
            _authority(), SemanticBuildState.COMPLETE, None, None, None, None, (), ()
        )


def test_provider_schemas_exclude_membership_topology_and_coordinates() -> None:
    root = ROOT / "src/renpy_story_mapper/narrative_map/schemas"
    boundary = json.loads((root / "boundary_window_v2.schema.json").read_text())
    summary = json.loads((root / "semantic_summary_v2.schema.json").read_text())
    property_names: set[str] = set()

    def collect_properties(value: object) -> None:
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict):
                property_names.update(properties)
            for child in value.values():
                collect_properties(child)
        elif isinstance(value, list):
            for child in value:
                collect_properties(child)

    collect_properties([boundary, summary])
    for forbidden in (
        "ordered_unit_ids",
        "members",
        "edges",
        "coordinates",
        "requirements",
        "effects",
        "locators",
    ):
        assert forbidden not in property_names
