from __future__ import annotations

from m15_test_support import linear_authority
from renpy_story_mapper.m11_scene_model import AtomKind
from renpy_story_mapper.narrative_map import (
    NarrativeEdgeKind,
    NarrativeNodeKind,
    assemble_narrative_events,
    build_narrative_corridors,
    build_narrative_map,
)


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
