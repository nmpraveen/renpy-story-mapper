from __future__ import annotations

from pathlib import Path

from renpy_story_mapper.canonical_graph import build_canonical_graph
from renpy_story_mapper.canonical_graph_contract import CanonicalGraph
from renpy_story_mapper.control_flow import analyze_control_flow
from renpy_story_mapper.graph import build_graph
from renpy_story_mapper.inspection_projection import (
    INSPECTION_PROJECTION_SCHEMA_VERSION,
    InspectionProjection,
    project_inspection_graph,
)
from renpy_story_mapper.parser import parse_script
from renpy_story_mapper.project import create_ingested_project
from renpy_story_mapper.route_map import RouteMap, project_route_map
from renpy_story_mapper.semantic import build_semantic_story
from renpy_story_mapper.state import extract_state

FIXTURE = Path(__file__).parent / "fixtures" / "m10" / "canonical_constructs.rpy"


def _models() -> tuple[CanonicalGraph, RouteMap, InspectionProjection]:
    module = parse_script(
        "m10/canonical_constructs.rpy",
        FIXTURE.read_text(encoding="utf-8").splitlines(keepends=True),
    )
    graph = build_graph([module])
    semantic = build_semantic_story(graph)
    state = extract_state([module])
    control = analyze_control_flow(graph, semantic, state.requirements, state.effects).to_dict()
    route = project_route_map(control, semantic, state.requirements, state.effects)
    canonical = build_canonical_graph(
        graph,
        semantic,
        control,
        route,
        state,
        source_generation="a" * 64,
    )
    return canonical, route, project_inspection_graph(canonical, route)


def test_projection_exposes_exact_choice_outcomes_and_proven_rejoins() -> None:
    canonical, _, projection = _models()
    canonical_before = canonical.normalized_bytes()
    outcomes = {item.title: item for item in projection.nodes if item.kind == "choice_outcome"}

    assert set(outcomes) == {"Help", "Leave", "Again", "Finish"}
    assert outcomes["Help"].attributes["condition"] == "ready"
    assert outcomes["Leave"].attributes["condition"] is None
    assert all(
        item.attributes["canonical_escape_id"] in item.canonical_node_ids
        for item in outcomes.values()
    )

    start_region = next(
        item
        for item in projection.regions
        if {outcomes["Help"].id, outcomes["Leave"].id} == set(item.outcome_node_ids)
    )
    assert start_region.kind == "loop_choice"
    assert start_region.split_node_id is not None
    assert start_region.merge_node_id is not None
    pairs = {(item.source_id, item.target_id) for item in projection.edges}
    assert (start_region.split_node_id, outcomes["Help"].id) in pairs
    assert (start_region.split_node_id, outcomes["Leave"].id) in pairs
    assert any(
        item.source_id == outcomes["Leave"].id and item.target_id == start_region.merge_node_id
        for item in projection.edges
    )
    assert canonical.normalized_bytes() == canonical_before


def test_projection_suppression_is_navigable_and_unresolved_behavior_stays_visible() -> None:
    canonical, _, projection = _models()
    canonical_ids = {item.id for item in canonical.nodes}
    projected_ids = {item.id for item in projection.nodes}

    assert any(item.reason == "routing_alias" for item in projection.suppressed)
    assert any(item.reason == "support_only_terminal" for item in projection.suppressed)
    assert all(set(item.canonical_node_ids) <= canonical_ids for item in projection.suppressed)
    assert all(
        item.represented_by_node_id is None or item.represented_by_node_id in projected_ids
        for item in projection.suppressed
    )
    assert any(
        bool(item.attributes.get("unresolved"))
        for item in projection.nodes
        if item.kind in {"terminal", "unresolved", "milestone"}
    )


def test_projection_bytes_are_stable_for_identical_structural_input() -> None:
    canonical, route, first = _models()
    second = project_inspection_graph(canonical, route)

    assert first.normalized_bytes() == second.normalized_bytes()
    assert first.authority_hash == second.authority_hash
    assert first.to_dict()["schema_version"] == INSPECTION_PROJECTION_SCHEMA_VERSION


def test_project_persists_generation_bound_inspection_projection(tmp_path: Path) -> None:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())

    with create_ingested_project(tmp_path / "story.rsmproj", source) as project:
        canonical = project.payload("m10_canonical_graph", "authoritative")
        projection = project.payload("m10_inspection_projection", "authoritative")
        state = project.payload("m10_analysis_state", "authoritative")

    assert isinstance(canonical, dict)
    assert isinstance(projection, dict)
    assert isinstance(state, dict)
    assert projection["source_generation"] == canonical["source_generation"]
    assert projection["canonical_graph_hash"] == state["canonical_hash"]
    phase = next(item for item in state["phases"] if item["phase"] == "simplified_projection")
    assert phase["source_generation"] == state["source_generation"]
