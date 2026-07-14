from __future__ import annotations

import copy
from pathlib import Path

import pytest

from renpy_story_mapper.canonical_graph import build_canonical_graph
from renpy_story_mapper.canonical_graph_contract import (
    CANONICAL_GRAPH_SCHEMA_VERSION,
    ReachabilityStatus,
    assign_reachability,
    source_generation,
)
from renpy_story_mapper.control_flow import analyze_control_flow
from renpy_story_mapper.graph import build_graph
from renpy_story_mapper.parser import parse_script
from renpy_story_mapper.project import Project, create_ingested_project
from renpy_story_mapper.route_map import project_route_map
from renpy_story_mapper.semantic import build_semantic_story
from renpy_story_mapper.state import extract_state

FIXTURE = Path(__file__).parent / "fixtures" / "m10" / "canonical_constructs.rpy"


@pytest.mark.parametrize(
    ("inputs", "expected"),
    [
        ({"static_reachable": True}, ReachabilityStatus.PROVEN_REACHABLE),
        (
            {"static_reachable": True, "proven_requirement": True},
            ReachabilityStatus.CONDITIONALLY_REACHABLE,
        ),
        (
            {"static_reachable": True, "inferred_requirement": True},
            ReachabilityStatus.REACHABLE_UNDER_INFERRED_REQUIREMENTS,
        ),
        (
            {"static_reachable": True, "unresolved_requirement": True},
            ReachabilityStatus.UNRESOLVED_DYNAMIC_BEHAVIOR,
        ),
        (
            {"static_reachable": False, "unresolved_item": True},
            ReachabilityStatus.UNRESOLVED_DYNAMIC_BEHAVIOR,
        ),
        (
            {"static_reachable": False, "unresolved_transfer_could_reach": True},
            ReachabilityStatus.POSSIBLY_DEAD,
        ),
        (
            {"static_reachable": False, "closed_world": False},
            ReachabilityStatus.UNREACHABLE_IN_RESOLVED_STATIC_GRAPH,
        ),
        (
            {"static_reachable": False, "closed_world": True},
            ReachabilityStatus.PROVEN_UNREACHABLE,
        ),
    ],
)
def test_reachability_decision_table(
    inputs: dict[str, bool], expected: ReachabilityStatus
) -> None:
    assert assign_reachability(**inputs) is expected  # type: ignore[arg-type]


def test_canonical_graph_composes_existing_authority_and_is_permutation_stable() -> None:
    module = parse_script(
        "m10/canonical_constructs.rpy",
        FIXTURE.read_text(encoding="utf-8").splitlines(keepends=True),
    )
    graph = build_graph([module])
    semantic = build_semantic_story(graph)
    state = extract_state([module])
    control = analyze_control_flow(
        graph, semantic, state.requirements, state.effects
    ).to_dict()
    route = project_route_map(control, semantic, state.requirements, state.effects)
    generation = source_generation(((module.path, "a" * 64),))
    first = build_canonical_graph(
        graph, semantic, control, route, state, source_generation=generation
    )

    assert first.to_dict()["schema_version"] == CANONICAL_GRAPH_SCHEMA_VERSION
    assert first.regions
    assert {item.kind for item in first.facts} == {"requirement", "effect"}
    assert any(item.kind == "loop_choice" for item in first.regions)
    assert any(item.kind == "unresolved" for item in first.nodes)
    assert all(item.evidence_ids or item.proof_ids for item in (*first.nodes, *first.edges))
    assert all(item.origins for item in (*first.nodes, *first.edges, *first.regions))

    permuted_graph = copy.deepcopy(graph)
    permuted_semantic = copy.deepcopy(semantic)
    permuted_control = copy.deepcopy(control)
    for value in (permuted_graph, permuted_semantic, permuted_control):
        for key, rows in tuple(value.items()):
            if isinstance(rows, list):
                value[key] = list(reversed(rows))
    second = build_canonical_graph(
        permuted_graph,
        permuted_semantic,
        permuted_control,
        route,
        state,
        source_generation=generation,
    )
    assert second.normalized_bytes() == first.normalized_bytes()
    assert second.authority_hash == first.authority_hash


def test_project_persists_canonical_graph_with_matching_fact_origins(tmp_path: Path) -> None:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    project_path = tmp_path / "story.rsmproj"

    with create_ingested_project(project_path, source) as project:
        payload = project.payload("m10_canonical_graph", "authoritative")
        assert isinstance(payload, dict)
        assert payload["schema_version"] == CANONICAL_GRAPH_SCHEMA_VERSION
        source_rows = project._require_open().execute(
            "SELECT path,content_hash FROM sources ORDER BY path"
        )
        expected_generation = source_generation(
            tuple((str(row["path"]), str(row["content_hash"])) for row in source_rows)
        )
        assert payload["source_generation"] == expected_generation
        origins = {
            str(origin["record_id"])
            for fact in payload["facts"]
            for origin in fact["origins"]
        }
        persisted = {
            str(item["id"])
            for collection in ("gates", "effects", "unresolved")
            for key in project.payload_keys(collection)
            for item in (project.payload(collection, key) or [])
            if isinstance(item, dict) and "id" in item
        }
        assert origins <= persisted
        normalized = payload

    with Project.open(project_path) as project:
        assert project.payload("m10_canonical_graph", "authoritative") == normalized
