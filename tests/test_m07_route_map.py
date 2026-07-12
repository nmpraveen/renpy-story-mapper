from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any

from renpy_story_mapper.control_flow import analyze_control_flow
from renpy_story_mapper.graph import build_graph
from renpy_story_mapper.parser import parse_script
from renpy_story_mapper.project import create_ingested_project
from renpy_story_mapper.route_map import RouteLaneKind, RouteNodeKind, project_route_map
from renpy_story_mapper.semantic import build_semantic_story

FIXTURES = Path(__file__).parent / "fixtures" / "m06"


def _fixture(name: str, *, entry: str = "start") -> tuple[dict[str, Any], dict[str, Any]]:
    with (FIXTURES / name).open(encoding="utf-8") as stream:
        graph = build_graph([parse_script(f"m06/{name}", stream)], entry_label=entry)
    semantic = build_semantic_story(graph)
    return semantic, analyze_control_flow(graph, semantic).to_dict()


def test_exactly_two_levels_diamonds_reconvergence_and_nested_detours() -> None:
    semantic, control = _fixture("control_regions.rpy")
    route_map = project_route_map(control, semantic)

    assert route_map.to_dict()["presentation_levels"] == ["route_map", "detail_evidence"]
    assert len(route_map.nodes) <= 30
    assert any(node.kind is RouteNodeKind.CHOICE for node in route_map.nodes)
    assert any(node.kind is RouteNodeKind.MERGE for node in route_map.nodes)
    assert any(edge.proven_merge for edge in route_map.edges)
    assert any(node.lane_kind is RouteLaneKind.DETOUR for node in route_map.nodes)
    assert route_map.coverage.technical_nodes > 0
    assert route_map.coverage.corridor_count > 0

    choice = next(node for node in route_map.nodes if node.kind is RouteNodeKind.CHOICE)
    detail = route_map.detail(choice.id)
    assert detail["level"] == "detail_evidence"
    assert detail["back_target"] == "route_map"
    assert "successor_ids" in detail
    assert detail["evidence"]


def test_persistent_routes_terminals_loops_calls_and_unresolved_are_visible() -> None:
    semantic, control = _fixture("control_regions.rpy", entry="terminal_routes")
    terminal_map = project_route_map(control, semantic)
    assert any(node.lane_kind is RouteLaneKind.PERSISTENT for node in terminal_map.nodes)
    assert any(node.kind is RouteNodeKind.TERMINAL for node in terminal_map.nodes)

    semantic, control = _fixture("calls_loops.rpy", entry="loop_entry")
    loop_map = project_route_map(control, semantic)
    assert any(node.kind is RouteNodeKind.LOOP for node in loop_map.nodes)
    assert any(role in edge.role for edge in loop_map.edges for role in ("loop", "corridor"))

    semantic, control = _fixture("calls_loops.rpy", entry="dynamic_arm")
    unresolved_map = project_route_map(control, semantic)
    assert any(node.unresolved for node in unresolved_map.nodes)

    semantic, control = _fixture("calls_loops.rpy")
    call_map = project_route_map(control, semantic)
    assert any(
        "call" in control_edge_id or any("call" in role for role in (edge.role,))
        for edge in call_map.edges
        for control_edge_id in edge.control_edge_ids
    )


def test_edge_gates_effects_and_direct_evidence_contract() -> None:
    semantic, control = _fixture("control_regions.rpy")
    first_edge = control["edges"][0]
    assert isinstance(first_edge, dict)
    target = str(first_edge["target"])
    requirements = [{"id": "gate_wits", "evidence": {"graph_node_id": target}}]
    effects = [{"id": "effect_love", "evidence": {"graph_node_id": target}}]
    route_map = project_route_map(control, semantic, requirements, effects)

    edge = next(item for item in route_map.edges if item.gate_ids or item.effect_ids)
    assert edge.gate_ids == ("gate_wits",)
    assert edge.effect_ids == ("effect_love",)
    detail = route_map.detail(edge.id)
    assert detail["gate_ids"] == ["gate_wits"]
    assert detail["effect_ids"] == ["effect_love"]
    assert detail["evidence_ids"]
    assert detail["evidence"]


def test_stable_ids_order_hash_and_permuted_authority() -> None:
    semantic, control = _fixture("control_regions.rpy")
    first = project_route_map(control, semantic)
    permuted = copy.deepcopy(control)
    for key in ("nodes", "edges", "regions", "arms", "loops", "terminals"):
        permuted[key] = list(reversed(permuted[key]))
    second = project_route_map(permuted, semantic)

    assert second.canonical_json() == first.canonical_json()
    assert second.authority_hash == first.authority_hash
    assert hashlib.sha256(first.canonical_json()).hexdigest() == first.authority_hash
    assert [node.order for node in first.nodes] == list(range(len(first.nodes)))
    assert [scope.ordinal for scope in first.scopes] == list(range(len(first.scopes)))


def test_initial_projection_is_bounded_at_scale() -> None:
    count = 2_000
    nodes = [
        {
            "id": f"n{i:04d}",
            "kind": "statement",
            "label": "start",
            "hidden": False,
            "synthetic": False,
            "source": {
                "path": "scale.rpy",
                "start": {"line": i + 1, "column": 0},
                "end": {"line": i + 1, "column": 1},
            },
        }
        for i in range(count)
    ]
    edges = [
        {
            "id": f"e{i:04d}",
            "source": f"n{i:04d}",
            "target": f"n{i + 1:04d}",
            "role": "flow",
            "semantic_roles": ["fallthrough"],
            "evidence": [],
            "resolved": True,
        }
        for i in range(count - 1)
    ]
    beats = [
        {
            "id": f"beat{i:04d}",
            "kind": "narrative",
            "graph_node_ids": [f"n{i:04d}"],
            "content": [{"text": f"Moment {i}"}],
        }
        for i in range(count)
    ]
    control = {
        "schema_version": 1,
        "nodes": nodes,
        "edges": edges,
        "regions": [],
        "arms": [],
        "loops": [],
        "terminals": [{"node_id": f"n{count - 1:04d}", "kind": "game_end"}],
    }
    semantic = {"schema_version": 1, "beats": beats}
    route_map = project_route_map(control, semantic)
    assert len(route_map.nodes) == 30
    assert route_map.coverage.control_nodes == count
    assert route_map.coverage.technical_nodes == count - 30
    assert route_map.nodes[-1].kind is RouteNodeKind.TERMINAL


def test_project_analysis_persists_route_map_and_pre_ai_scopes(tmp_path: Path) -> None:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes((FIXTURES / "control_regions.rpy").read_bytes())
    with create_ingested_project(tmp_path / "story.rsmproj", source) as project:
        payload = project.payload("m07_route_map", "authoritative")
        assert isinstance(payload, dict)
        assert payload["presentation_levels"] == ["route_map", "detail_evidence"]
        checkpoints = project.m07_model_service().checkpoints()
        assert checkpoints
        assert [item.ordinal for item in checkpoints] == list(range(len(checkpoints)))
