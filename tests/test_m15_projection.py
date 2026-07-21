from __future__ import annotations

from dataclasses import replace

from m15_test_support import linear_authority
from renpy_story_mapper.canonical_graph_contract import CanonicalNodeKind
from renpy_story_mapper.m11_scene_model import AtomKind
from renpy_story_mapper.narrative_map import (
    NarrativeEdgeKind,
    NarrativeNodeKind,
    Provenance,
    SourceLocator,
    assemble_narrative_events,
    build_narrative_corridors,
    build_narrative_map,
)
from renpy_story_mapper.narrative_map.projection import _edge_kind


def test_quotient_edges_copy_only_authoritative_provenance_requirements_and_effects() -> None:
    canonical, model = linear_authority(
        (AtomKind.NARRATION, AtomKind.UNRESOLVED, AtomKind.TERMINAL),
        edge_attributes=(
            {"gate_ids": ["requirement-1"], "effect_ids": ["effect-1"], "semantic_roles": []},
            {"gate_ids": [], "effect_ids": [], "semantic_roles": []},
        ),
    )
    corridors = build_narrative_corridors(canonical, model)
    events = assemble_narrative_events(corridors)

    result = build_narrative_map(canonical, events, corridors=corridors)

    assert {item for edge in result.edges for item in edge.authority_edge_ids} == {
        item.id for item in canonical.edges
    }
    first = next(item for item in result.edges if "edge-0" in item.authority_edge_ids)
    assert first.requirement_ids == ("requirement-1",)
    assert first.effect_ids == ("effect-1",)
    assert first.kind is NarrativeEdgeKind.UNRESOLVED
    assert any(item.kind is NarrativeNodeKind.TERMINAL for item in result.nodes)
    assert any(item.kind is NarrativeNodeKind.UNRESOLVED for item in result.nodes)


def test_loop_back_edge_is_never_linearized_or_invented() -> None:
    canonical, model = linear_authority((AtomKind.NARRATION, AtomKind.LOOP))
    loop_edge = canonical.edges[0]
    loop_edge = type(loop_edge)(
        **{
            **loop_edge.__dict__,
            "kind": "loop_back",
            "source_id": "node-1",
            "target_id": "node-0",
        }
    )
    canonical = type(canonical)(
        canonical.source_generation,
        canonical.origin_generations,
        canonical.nodes,
        (loop_edge,),
        canonical.regions,
        canonical.facts,
        canonical.evidence,
        canonical.proofs,
    )
    # Rebind the synthetic M11 model to the changed exact M10 hash.
    model = type(model)(
        type(model.binding)(
            model.binding.source_generation,
            model.binding.canonical_schema,
            canonical.authority_hash,
        ),
        model.atoms,
        model.boundaries,
        model.scenes,
        model.temporary_branches,
        model.occurrences,
        model.lanes,
        model.chapters,
        model.loop_hubs,
        model.coverage,
    )
    corridors = build_narrative_corridors(canonical, model)
    events = assemble_narrative_events(corridors)
    result = build_narrative_map(canonical, events, corridors=corridors)

    assert len(result.edges) == 1
    assert result.edges[0].kind is NarrativeEdgeKind.LOOP
    assert result.edges[0].authority_edge_ids == ("edge-0",)


def test_hidden_technical_coverage_is_attached_without_equal_weight_story_promotion() -> None:
    canonical, model = linear_authority(
        (AtomKind.NARRATION, AtomKind.VISUAL_CHANGE, AtomKind.NARRATION),
        labels=("Begin", "Scene office pose", "Continue"),
        source_kinds=("statement", "scene", "statement"),
    )
    corridors = build_narrative_corridors(canonical, model)
    events = assemble_narrative_events(corridors)
    result = build_narrative_map(canonical, events, corridors=corridors)

    assert result.hidden_technical_atom_ids == ("atom-1",)
    assert all(item.title.casefold() not in {"start", "clean"} for item in result.nodes)


def test_hidden_technical_event_retains_authoritative_story_continuity() -> None:
    canonical, model = linear_authority(
        (AtomKind.NARRATION, AtomKind.TECHNICAL, AtomKind.NARRATION),
        labels=("Story before", "Sanitized technical transition", "Story after"),
    )
    combined = build_narrative_corridors(canonical, model)[0]
    corridors = tuple(
        replace(
            combined,
            ordered_atom_ids=(f"atom-{index}",),
            entry_node_id=f"node-{index}",
            exit_node_id=f"node-{index}",
            incident_edge_ids=(
                ("edge-0",)
                if index == 0
                else ("edge-1",)
                if index == 2
                else ("edge-0", "edge-1")
            ),
            hard_boundary_before=index > 0,
            hard_boundary_after=index < 2,
            technical_atom_ids=(("atom-1",) if index == 1 else ()),
            provenance=Provenance(
                atom_ids=(f"atom-{index}",),
                node_ids=(f"node-{index}",),
                edge_ids=(
                    ("edge-0",)
                    if index == 0
                    else ("edge-1",)
                    if index == 2
                    else ("edge-0", "edge-1")
                ),
                evidence_ids=(f"evidence-{index}",),
                locators=(
                    SourceLocator(
                        "game/synthetic.rpy", index + 1, index + 1, "physical_source"
                    ),
                ),
            ),
        )
        for index in range(3)
    )
    events = assemble_narrative_events(corridors)

    result = build_narrative_map(canonical, events, corridors=corridors)

    event_nodes = {
        item.event_id: item
        for item in result.nodes
        if item.event_id is not None
    }
    before = event_nodes[events[0].event_id]
    technical = event_nodes[events[1].event_id]
    after = event_nodes[events[2].event_id]
    assert technical.kind is NarrativeNodeKind.TECHNICAL_COVERAGE
    continuity = next(
        item
        for item in result.edges
        if item.source_node_id == before.node_id and item.target_node_id == after.node_id
    )
    assert continuity.kind is NarrativeEdgeKind.CONTINUATION
    assert continuity.authority_edge_ids == ("edge-0", "edge-1")


def test_call_return_and_persistent_region_edge_precedence() -> None:
    canonical, _model = linear_authority((AtomKind.CALL, AtomKind.NARRATION))
    edge = canonical.edges[0]
    node_kinds = {item.id: item.kind for item in canonical.nodes}

    call_return = type(edge)(**{**edge.__dict__, "kind": "call_return"})
    assert _edge_kind(call_return, node_kinds, {}, set(), set()) is NarrativeEdgeKind.RETURN

    persistent_merge = type(edge)(
        **{
            **edge.__dict__,
            "attributes": {"semantic_roles": ["merge"]},
        }
    )
    assert (
        _edge_kind(
            persistent_merge,
            node_kinds,
            {edge.target_id: "map-rejoin"},
            set(),
            {edge.target_id},
        )
        is NarrativeEdgeKind.PERSISTENT_MERGE
    )

    persistent_split = type(edge)(
        **{
            **edge.__dict__,
            "source_id": edge.source_id,
            "target_id": edge.target_id,
        }
    )
    assert (
        _edge_kind(
            persistent_split,
            {**node_kinds, edge.source_id: CanonicalNodeKind.CONDITION},
            {},
            {edge.source_id},
            set(),
        )
        is NarrativeEdgeKind.PERSISTENT_SPLIT
    )
