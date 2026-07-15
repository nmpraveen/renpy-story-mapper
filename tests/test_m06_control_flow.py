from __future__ import annotations

import json
import time
import tracemalloc
from pathlib import Path
from typing import Any

import pytest

from renpy_story_mapper.control_flow import (
    FlowEdgeRole,
    RouteClassification,
    analyze_control_flow,
    derive_story_quotient,
)
from renpy_story_mapper.graph import build_graph
from renpy_story_mapper.parser import parse_script
from renpy_story_mapper.project import Project, create_ingested_project
from renpy_story_mapper.semantic import build_semantic_story
from renpy_story_mapper.state import extract_state

FIXTURES = Path(__file__).parent / "fixtures" / "m06"


def analyze_fixture(name: str, *, entry: str = "start") -> tuple[dict[str, Any], Any]:
    with (FIXTURES / name).open(encoding="utf-8") as stream:
        graph = build_graph([parse_script(f"m06/{name}", stream)], entry_label=entry)
    return graph, analyze_control_flow(graph, build_semantic_story(graph))


def test_control_flow_is_persisted_and_reopens_canonically(tmp_path: Path) -> None:
    source_root = tmp_path / "game"
    source_root.mkdir()
    (source_root / "story.rpy").write_bytes((FIXTURES / "control_regions.rpy").read_bytes())
    project_path = tmp_path / "story.rsmproj"

    with create_ingested_project(project_path, source_root) as project:
        first = project.payload("m06_control_flow", "authoritative")
        assert isinstance(first, dict)
        assert first["schema_version"] == 1
        assert first["regions"]

    with Project.open(project_path) as reopened:
        assert reopened.payload("m06_control_flow", "authoritative") == first


def test_choice_arm_ordinals_preserve_source_order() -> None:
    source = """label start:
    menu:
        "First":
            "one"
        "Second":
            "two"
        "Third":
            "three"
    return
"""
    graph = build_graph([parse_script("ordered.rpy", source.splitlines(keepends=True))])
    analysis = analyze_control_flow(graph, build_semantic_story(graph))
    menu = next(item for item in analysis.nodes if item.kind == "menu")
    region = next(item for item in analysis.regions if item.split_node_id == menu.id)
    graph_nodes = {str(item["id"]): item for item in graph["nodes"]}
    arms = sorted(
        (item for item in analysis.arms if item.region_id == region.id),
        key=lambda item: item.ordinal,
    )

    assert [graph_nodes[item.entry_node_id]["metadata"]["caption"] for item in arms] == [
        "First",
        "Second",
        "Third",
    ]


def test_diamonds_bypass_long_routes_and_terminals_classify_exactly() -> None:
    _, analysis = analyze_fixture("control_regions.rpy")
    start_nodes = {node.id for node in analysis.nodes if node.label == "start"}
    classifications = [
        region.classification for region in analysis.regions if region.split_node_id in start_nodes
    ]
    assert sorted(classifications) == sorted(
        [
            RouteClassification.LOCAL_DETOUR,
            RouteClassification.OPTIONAL_DETOUR,
            RouteClassification.RECONVERGENT_ROUTE_SEGMENT,
        ]
    )
    start_regions = [region for region in analysis.regions if region.split_node_id in start_nodes]
    assert all(region.merge_node_id is not None for region in start_regions)
    assert all(
        region.merge_node_id != analysis.to_dict()["virtual_exit_id"] for region in analysis.regions
    )
    assert any(node.kind == "merge" and node.hidden for node in analysis.nodes)

    _, terminal = analyze_fixture("control_regions.rpy", entry="terminal_routes")
    split = next(
        region
        for region in terminal.regions
        if region.classification == RouteClassification.TERMINAL_SPLIT
    )
    assert split.merge_node_id is None
    assert len({arm.terminal_node_ids for arm in terminal.arms if arm.region_id == split.id}) == 2

    _, shared = analyze_fixture("control_regions.rpy", entry="shared_routes")
    shared_region = next(
        region
        for region in shared.regions
        if region.split_node_id
        in {node.id for node in shared.nodes if node.label == "shared_routes"}
    )
    assert shared_region.merge_node_id is not None
    assert shared_region.classification == RouteClassification.RECONVERGENT_ROUTE_SEGMENT


def test_calls_use_call_site_correct_return_sites_without_cross_product() -> None:
    graph, analysis = analyze_fixture("calls_loops.rpy")
    raw_returns = [edge for edge in graph["edges"] if edge["kind"] == "return"]
    helper_return_ids = {
        node["id"]
        for node in graph["nodes"]
        if node["kind"] == "return" and node["label"] == "helper"
    }
    helper_raw_returns = [edge for edge in raw_returns if edge["source"] in helper_return_ids]
    assert len(helper_raw_returns) == 4  # two returns multiplied by two helper continuations
    normalized_roles = [edge.role for edge in analysis.edges]
    assert normalized_roles.count(FlowEdgeRole.CALL_SUMMARY) == 2
    return_sites = [node for node in analysis.nodes if node.kind == "call_return_site"]
    assert len(return_sites) == 2
    for site in return_sites:
        incoming = [edge for edge in analysis.edges if edge.target == site.id]
        outgoing = [edge for edge in analysis.edges if edge.source == site.id]
        assert len(incoming) == len(outgoing) == 1
        assert incoming[0].call_site_id == outgoing[0].call_site_id
    assert not any(
        edge.source in {item["source"] for item in raw_returns}
        and edge.target in {item["target"] for item in raw_returns}
        for edge in analysis.edges
    )
    summaries = [edge for edge in analysis.edges if edge.role == FlowEdgeRole.CALL_SUMMARY]
    call_returns = [edge for edge in analysis.edges if edge.role == FlowEdgeRole.CALL_RETURN]
    assert all(
        [item["kind"] for item in edge.evidence] == ["call", "call_continuation"]
        for edge in summaries
    )
    assert all(
        [item["kind"] for item in edge.evidence] == ["call_continuation"]
        for edge in call_returns
        if edge.call_site_id is not None
    )
    assert not any(item["kind"] == "return" for edge in summaries for item in edge.evidence)
    helper = next(item for item in analysis.procedures if item.label == "helper")
    assert helper.may_return and not helper.recursive
    helper_region = next(
        region
        for region in analysis.regions
        if region.split_node_id in {node.id for node in analysis.nodes if node.label == "helper"}
    )
    assert helper_region.classification == RouteClassification.LOCAL_DETOUR


def test_loops_recursion_nonreturning_calls_and_dynamic_targets() -> None:
    _, looping = analyze_fixture("calls_loops.rpy", entry="loop_entry")
    assert looping.loops
    assert any(loop.back_edge_ids and loop.exit_edge_ids for loop in looping.loops)
    assert any(
        region.classification == RouteClassification.LOOP_CHOICE for region in looping.regions
    )
    assert any(edge.role == FlowEdgeRole.LOOP_BACK for edge in looping.edges)

    _, recursive = analyze_fixture("calls_loops.rpy", entry="recursive")
    recursive_summary = next(item for item in recursive.procedures if item.label == "recursive")
    assert recursive_summary.recursive and recursive_summary.looping

    _, nonreturning = analyze_fixture("calls_loops.rpy", entry="calls_never_returns")
    call = next(
        node
        for node in nonreturning.nodes
        if node.kind == "call" and node.label == "calls_never_returns"
    )
    assert not any(
        edge.role == FlowEdgeRole.CALL_SUMMARY and edge.source == call.id
        for edge in nonreturning.edges
    )
    assert (call.id, "non_returning_call") in nonreturning.terminals

    _, dynamic = analyze_fixture("calls_loops.rpy", entry="dynamic_arm")
    assert any(
        region.classification == RouteClassification.UNRESOLVED for region in dynamic.regions
    )


def _analyze_source(lines: list[str]) -> Any:
    graph = build_graph([parse_script("procedure-summary.rpy", lines)])
    return analyze_control_flow(graph, build_semantic_story(graph))


def test_procedure_termination_fixed_point_distinguishes_divergence() -> None:
    infinite = _analyze_source(
        [
            "label start:\n",
            "    call infinite\n",
            "    return\n",
            "label infinite:\n",
            "    jump infinite\n",
        ]
    )
    infinite_by_label = {item.label: item for item in infinite.procedures}
    assert not infinite_by_label["infinite"].may_return
    assert not infinite_by_label["infinite"].may_terminate
    assert not infinite_by_label["start"].may_return
    assert not infinite_by_label["start"].may_terminate

    terminating = _analyze_source(
        [
            "label start:\n",
            "    call terminator\n",
            "    return\n",
            "label terminator:\n",
            '    "Concrete ending."\n',
        ]
    )
    terminating_by_label = {item.label: item for item in terminating.procedures}
    assert terminating_by_label["terminator"].may_terminate
    assert not terminating_by_label["terminator"].may_return
    assert terminating_by_label["start"].may_terminate
    assert not terminating_by_label["start"].may_return

    terminating_tail_jump = _analyze_source(
        [
            "label start:\n",
            "    jump terminator\n",
            "label terminator:\n",
            '    "Tail ending."\n',
        ]
    )
    terminating_tail_by_label = {item.label: item for item in terminating_tail_jump.procedures}
    assert terminating_tail_by_label["start"].may_terminate
    assert not terminating_tail_by_label["start"].may_return

    returning_tail_jump = _analyze_source(
        [
            "label start:\n",
            "    jump helper\n",
            "label helper:\n",
            "    return\n",
        ]
    )
    returning_tail_by_label = {item.label: item for item in returning_tail_jump.procedures}
    assert returning_tail_by_label["start"].may_return
    assert not returning_tail_by_label["start"].may_terminate

    returning_then_terminal = _analyze_source(
        [
            "label helper:\n",
            "    return\n",
            "label start:\n",
            "    call helper\n",
            '    "Caller ending."\n',
        ]
    )
    returning_by_label = {item.label: item for item in returning_then_terminal.procedures}
    assert returning_by_label["helper"].may_return
    assert not returning_by_label["helper"].may_terminate
    assert returning_by_label["start"].may_terminate

    recursive = _analyze_source(
        [
            "label start:\n",
            "    call recurse\n",
            "    return\n",
            "label recurse:\n",
            "    call recurse\n",
            "    return\n",
        ]
    )
    recursive_by_label = {item.label: item for item in recursive.procedures}
    assert recursive_by_label["recurse"].recursive
    assert not recursive_by_label["recurse"].may_return
    assert not recursive_by_label["recurse"].may_terminate
    assert not recursive_by_label["start"].may_terminate


def test_unresolved_call_does_not_become_concrete_termination() -> None:
    analysis = _analyze_source(
        [
            "label start:\n",
            "    call expression destination\n",
            '    "Possible continuation."\n',
        ]
    )
    summary = next(item for item in analysis.procedures if item.label == "start")
    assert summary.unresolved
    assert not summary.may_return
    assert not summary.may_terminate


def test_nested_regions_have_stable_innermost_ownership_and_permutation_output() -> None:
    source = [
        "label start:\n",
        "    menu:\n",
        '        "Outer A":\n',
        "            menu:\n",
        '                "Inner A":\n',
        '                    "A."\n',
        '                "Inner B":\n',
        '                    "B."\n',
        '            "After nested."\n',
        '        "Outer B":\n',
        '            "C."\n',
        "    return\n",
    ]
    module = parse_script("nested.rpy", source)
    graph = build_graph([module])
    first = analyze_control_flow(graph, build_semantic_story(graph))
    permuted = dict(graph)
    permuted["nodes"] = list(reversed(graph["nodes"]))
    permuted["edges"] = list(reversed(graph["edges"]))
    second = analyze_control_flow(permuted, build_semantic_story(permuted))
    assert len(first.regions) == 2
    assert any(region.parent_region_id is not None for region in first.regions)
    outer_region = next(region for region in first.regions if region.parent_region_id is None)
    outer_first_arm = next(
        arm for arm in first.arms if arm.region_id == outer_region.id and arm.ordinal == 0
    )
    continuation_id = next(
        str(node["id"])
        for node in graph["nodes"]
        if node.get("source_text") == '"After nested."'
    )
    assert continuation_id in outer_first_arm.node_ids
    assert first.canonical_json() == second.canonical_json()
    assert (
        first.canonical_json()
        == json.dumps(
            first.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    )


def test_quotient_preserves_multiple_roles_and_ordered_evidence() -> None:
    _, analysis = analyze_fixture("calls_loops.rpy")
    mapping = {node.id: node.label for node in analysis.nodes}
    quotient = derive_story_quotient(analysis, mapping)
    assert quotient
    assert all(edge.semantic_roles and not hasattr(edge, "kind") for edge in quotient)
    assert all(edge.control_edge_ids == tuple(sorted(edge.control_edge_ids)) for edge in quotient)


def test_proven_state_lineage_preserves_detours_and_marks_dispatch() -> None:
    with (FIXTURES / "state_dispatch.rpy").open(encoding="utf-8") as stream:
        module = parse_script("m06/state_dispatch.rpy", stream)
    graph = build_graph([module])
    state = extract_state([module])
    analysis = analyze_control_flow(
        graph,
        build_semantic_story(graph),
        state.requirements,
        state.effects,
    )
    node_kind = {node.id: node.kind for node in analysis.nodes}
    menu_regions = [
        region for region in analysis.regions if node_kind[region.split_node_id] == "menu"
    ]
    dispatcher = next(
        region for region in analysis.regions if node_kind[region.split_node_id] == "if"
    )
    assert len(menu_regions) == 2
    assert all(
        region.merge_node_id is not None
        and region.classification == RouteClassification.LOCAL_DETOUR
        for region in menu_regions
    )
    menu_arms = [
        arm for arm in analysis.arms if arm.region_id in {item.id for item in menu_regions}
    ]
    assert not any(write.variable == "love" for arm in menu_arms for write in arm.state_writes)
    assert {write.value for arm in menu_arms for write in arm.state_writes} == {"red", "blue"}
    dispatch_arms = [arm for arm in analysis.arms if arm.region_id == dispatcher.id]
    assert any(read.variable == "route" for arm in dispatch_arms for read in arm.state_reads)
    assert dispatcher.merge_node_id is None
    assert dispatcher.classification == RouteClassification.TERMINAL_SPLIT
    assert "state_dispatch" in dispatcher.persistence_reasons
    assert "state_dispatch_variable:route" in dispatcher.persistence_reasons


def test_scc_records_self_loops_back_edges_exits_and_irreducibility() -> None:
    def node(node_id: str, kind: str) -> dict[str, object]:
        value: dict[str, object] = {
            "id": node_id,
            "kind": kind,
            "label": "start",
            "source": {
                "path": "scc.rpy",
                "start": {"line": 1, "column": 1},
                "end": {"line": 1, "column": 2},
            },
            "source_text": "pass",
        }
        if kind == "label":
            value["metadata"] = {"name": "start"}
        return value

    nodes = [
        node("entry", "label"),
        node("split", "if"),
        node("a", "statement"),
        node("b", "statement"),
        node("self", "statement"),
        node("end", "module_end"),
    ]
    edges = [
        {"source": "entry", "target": "split", "kind": "label_entry"},
        {"source": "split", "target": "a", "kind": "condition"},
        {"source": "split", "target": "b", "kind": "condition"},
        {"source": "split", "target": "self", "kind": "condition"},
        {"source": "a", "target": "b", "kind": "fallthrough"},
        {"source": "b", "target": "a", "kind": "jump"},
        {"source": "a", "target": "end", "kind": "fallthrough"},
        {"source": "self", "target": "self", "kind": "jump"},
    ]
    graph = {"schema_version": 1, "entry_label": "start", "nodes": nodes, "edges": edges}
    analysis = analyze_control_flow(graph, {"schema_version": 1, "transitions": []})
    irreducible = next(loop for loop in analysis.loops if loop.irreducible)
    assert irreducible.exit_edge_ids
    assert not irreducible.back_edge_ids
    assert any(
        diagnostic.kind == "irreducible_loop" and diagnostic.node_ids == irreducible.node_ids
        for diagnostic in analysis.diagnostics
    )
    self_loop = next(loop for loop in analysis.loops if loop.self_loop)
    assert self_loop.back_edge_ids


def _split_chain_graph(split_count: int) -> dict[str, object]:
    def source(line: int) -> dict[str, object]:
        return {
            "path": "split-chain.rpy",
            "start": {"line": line, "column": 1},
            "end": {"line": line, "column": 2},
        }

    nodes: list[dict[str, object]] = [
        {
            "id": "entry",
            "kind": "label",
            "label": "start",
            "source": source(1),
            "source_text": "label start:",
            "metadata": {"name": "start"},
        }
    ]
    nodes.extend(
        {
            "id": f"split_{index:04d}",
            "kind": "if",
            "label": "start",
            "source": source(index + 2),
            "source_text": "if branch:",
        }
        for index in range(split_count)
    )
    nodes.extend(
        {
            "id": f"terminal_{index:04d}",
            "kind": "module_end",
            "label": "start",
            "source": source(split_count + index + 2),
            "source_text": "return",
        }
        for index in range(split_count + 1)
    )
    edges: list[dict[str, object]] = [
        {"source": "entry", "target": "split_0000", "kind": "label_entry"}
    ]
    for index in range(split_count):
        split = f"split_{index:04d}"
        continuation = (
            f"split_{index + 1:04d}" if index + 1 < split_count else f"terminal_{split_count:04d}"
        )
        edges.extend(
            [
                {
                    "source": split,
                    "target": f"terminal_{index:04d}",
                    "kind": "condition",
                },
                {"source": split, "target": continuation, "kind": "condition"},
            ]
        )
    return {
        "schema_version": 1,
        "entry_label": "start",
        "nodes": nodes,
        "edges": edges,
    }


def test_persistent_split_chain_has_bounded_direct_membership() -> None:
    graph = _split_chain_graph(200)
    analysis = analyze_control_flow(graph, {"schema_version": 1, "transitions": []})
    assert len(analysis.regions) == 200
    assert sum(len(arm.node_ids) for arm in analysis.arms) <= len(analysis.nodes) * 8
    assert len(analysis.ownership) <= len(analysis.nodes)
    assert len({item.node_id for item in analysis.ownership}) == len(analysis.ownership)
    assert all(
        region.classification == RouteClassification.TERMINAL_SPLIT for region in analysis.regions
    )


@pytest.mark.hardware_sensitive
def test_2000_node_split_chain_runtime_and_memory_are_bounded() -> None:
    graph = _split_chain_graph(999)
    tracemalloc.start()
    before, _ = tracemalloc.get_traced_memory()
    started = time.perf_counter()
    analysis = analyze_control_flow(graph, {"schema_version": 1, "transitions": []})
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(analysis.nodes) == 2_000
    assert sum(len(arm.node_ids) for arm in analysis.arms) <= len(analysis.nodes) * 8
    assert elapsed < 2.0
    assert peak - before < 128 * 1024 * 1024


@pytest.mark.hardware_sensitive
def test_scale_harness_approximately_10k_nodes_15k_edges() -> None:
    # A direct inert M01-shaped fixture isolates the control algorithm from parser cost.
    count = 10_000
    nodes: list[dict[str, object]] = []
    for index in range(count):
        nodes.append(
            {
                "id": f"n{index:05d}",
                "kind": "label"
                if index == 0
                else ("module_end" if index == count - 1 else "statement"),
                "label": "start",
                "source": {
                    "path": "scale.rpy",
                    "start": {"line": index + 1, "column": 1},
                    "end": {"line": index + 1, "column": 2},
                },
                "source_text": "pass",
                "metadata": {"name": "start"} if index == 0 else {},
            }
        )
    edges = [
        {"source": f"n{index:05d}", "target": f"n{index + 1:05d}", "kind": "fallthrough"}
        for index in range(count - 1)
    ]
    edges.extend(
        {"source": f"n{index:05d}", "target": f"n{index + 2:05d}", "kind": "condition"}
        for index in range(0, count - 2, 2)
    )
    graph = {"schema_version": 1, "entry_label": "start", "nodes": nodes, "edges": edges}
    story = {"schema_version": 1, "transitions": []}
    tracemalloc.start()
    before, _ = tracemalloc.get_traced_memory()
    started = time.perf_counter()
    analysis = analyze_control_flow(graph, story)
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(analysis.nodes) == count
    assert len(analysis.edges) == 14_998
    assert elapsed < 2.0
    assert peak - before < 256 * 1024 * 1024
