from __future__ import annotations

import json
from pathlib import Path

import pytest

from renpy_story_mapper.narrative_map.contracts import (
    AuthorityBinding,
    BoundaryCandidate,
    BoundaryDecision,
    BoundaryDecisionKind,
    BoundarySignal,
    CoverageState,
    EvidenceNavigation,
    NarrativeCorridor,
    NarrativeEdgeKind,
    NarrativeEvent,
    NarrativeMap,
    NarrativeMapEdge,
    NarrativeMapNode,
    NarrativeNodeKind,
    Provenance,
    SourceLocator,
)

ROOT = Path(__file__).resolve().parents[1]


def _authority() -> AuthorityBinding:
    return AuthorityBinding(
        source_generation="generation-1",
        canonical_schema="m10-canonical-graph-v1",
        canonical_hash="canonical-hash",
        atom_schema="m11-story-atoms-v1",
        atom_hash="atom-hash",
    )


def _provenance(*atoms: str) -> Provenance:
    return Provenance(
        atom_ids=atoms,
        node_ids=("node-1", "node-2"),
        edge_ids=("edge-1",),
        evidence_ids=("evidence-1",),
        locators=(SourceLocator("game/story.rpy", 10, 12, "reconstructed"),),
    )


def test_corridor_identity_is_ordered_bound_and_technical_coverage_is_attached() -> None:
    corridor = NarrativeCorridor(
        authority=_authority(),
        lane_id="lane-spine",
        chapter_id="day-1",
        call_occurrence_id=None,
        loop_id=None,
        temporary_container_id=None,
        temporary_arm_id=None,
        ordered_atom_ids=("atom-dialogue", "atom-pose", "atom-narration"),
        entry_node_id="node-1",
        exit_node_id="node-2",
        incident_edge_ids=("edge-1",),
        soft_boundary_signals=(BoundarySignal.CAST,),
        technical_atom_ids=("atom-pose",),
        provenance=_provenance("atom-dialogue", "atom-pose", "atom-narration"),
    )

    assert corridor.corridor_id == NarrativeCorridor(**corridor.__dict__).corridor_id
    assert corridor.to_dict()["ordered_atom_ids"] == [
        "atom-dialogue",
        "atom-pose",
        "atom-narration",
    ]

    with pytest.raises(ValueError, match="technical coverage"):
        NarrativeCorridor(
            **{**corridor.__dict__, "technical_atom_ids": ("foreign-atom",)}
        )


def test_boundary_contract_cannot_create_a_provider_free_merge() -> None:
    candidate = BoundaryCandidate(
        authority=_authority(),
        left_corridor_id="corridor-left",
        right_corridor_id="corridor-right",
        signals=(BoundarySignal.NARRATIVE_OBJECTIVE,),
        evidence_ids=("evidence-1",),
    )
    fallback = BoundaryDecision(
        candidate=candidate,
        decision=BoundaryDecisionKind.UNCERTAIN,
        reason="Provider unavailable; retain the conservative boundary.",
        confidence=0.0,
        provider_identity=None,
    )
    assert fallback.to_dict()["decision"] == "uncertain"

    with pytest.raises(ValueError, match="must remain uncertain"):
        BoundaryDecision(
            candidate=candidate,
            decision=BoundaryDecisionKind.MERGE,
            reason="Unsafe fallback merge.",
            confidence=0.0,
            provider_identity=None,
        )


def test_event_identity_excludes_optional_ai_prose() -> None:
    common = {
        "authority": _authority(),
        "ordered_corridor_ids": ("corridor-1",),
        "ordered_atom_ids": ("atom-1", "atom-2"),
        "chapter_id": "day-1",
        "lane_id": "lane-spine",
        "call_occurrence_id": None,
        "temporary_container_id": None,
        "temporary_arm_id": None,
        "loop_id": None,
        "entry_node_id": "node-1",
        "exit_node_id": "node-2",
        "nested_choice_ids": (),
        "rejoin_node_ids": (),
        "deterministic_title": "Event at line 10",
        "coverage_state": CoverageState.COMPLETE,
        "provenance": _provenance("atom-1", "atom-2"),
    }
    first = NarrativeEvent(**common)
    enriched = NarrativeEvent(
        **common,
        ai_title="A readable title",
        ai_summary="A concise evidence-grounded summary.",
        ai_claim_ids=("claim-1",),
    )

    assert first.event_id == enriched.event_id


def test_map_requires_known_nodes_and_authoritative_edges() -> None:
    navigation = EvidenceNavigation("event", "event-1")
    first = NarrativeMapNode(
        node_id="map-node-1",
        kind=NarrativeNodeKind.EVENT_CLUSTER,
        title="Opening event",
        ordinal=0,
        navigation=navigation,
        event_id="event-1",
    )
    second = NarrativeMapNode(
        node_id="map-node-2",
        kind=NarrativeNodeKind.EVENT_CLUSTER,
        title="Next event",
        ordinal=1,
        navigation=EvidenceNavigation("event", "event-2"),
        event_id="event-2",
    )
    edge = NarrativeMapEdge(
        source_node_id=first.node_id,
        target_node_id=second.node_id,
        kind=NarrativeEdgeKind.CONTINUATION,
        authority_edge_ids=("m10-edge-1",),
    )
    result = NarrativeMap(
        authority=_authority(),
        event_ids=("event-1", "event-2"),
        nodes=(first, second),
        edges=(edge,),
        initial_node_ids=(first.node_id,),
    )
    assert result.to_dict()["edges"][0]["authority_edge_ids"] == ["m10-edge-1"]

    with pytest.raises(ValueError, match="known map nodes"):
        NarrativeMap(
            authority=_authority(),
            event_ids=("event-1",),
            nodes=(first,),
            edges=(edge,),
            initial_node_ids=(first.node_id,),
        )


def test_source_locators_are_relative_and_detail_evidence_is_the_only_mode() -> None:
    with pytest.raises(ValueError, match="safe relative path"):
        SourceLocator("../private/story.rpy", 1, 1, "physical")
    with pytest.raises(ValueError, match="safe relative path"):
        SourceLocator("C:/private/story.rpy", 1, 1, "physical")
    with pytest.raises(ValueError, match="Detail/Evidence"):
        EvidenceNavigation("event", "event-1", mode="third_level")


def test_provider_response_schemas_exclude_membership_and_edges() -> None:
    schema_root = ROOT / "src" / "renpy_story_mapper" / "narrative_map" / "schemas"
    boundary = json.loads((schema_root / "boundary_decision_v1.schema.json").read_text())
    summary = json.loads((schema_root / "event_summary_v1.schema.json").read_text())

    assert boundary["additionalProperties"] is False
    assert summary["additionalProperties"] is False
    boundary_fields = boundary["properties"]["decisions"]["items"]["properties"]
    summary_fields = summary["properties"]
    for forbidden in ("edges", "members", "corridor_ids", "atom_ids", "requirements", "effects"):
        assert forbidden not in boundary_fields
        assert forbidden not in summary_fields


def test_synthetic_acceptance_manifest_covers_required_topologies() -> None:
    manifest = json.loads(
        (ROOT / "tests" / "fixtures" / "m15" / "acceptance_cases.json").read_text()
    )
    case_ids = {item["id"] for item in manifest["cases"]}
    assert case_ids == {
        "linear-dialogue",
        "frequent-pose-changes",
        "local-detour",
        "nested-local-detour",
        "persistent-branches",
        "call-occurrences",
        "loop",
        "terminal",
        "unresolved-transfer",
    }
