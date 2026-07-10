from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from renpy_story_mapper.graph import build_graph
from renpy_story_mapper.parser import parse_script

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_graph(name: str) -> dict[str, Any]:
    path = FIXTURES / name
    with path.open(encoding="utf-8") as stream:
        module = parse_script(name, stream)
    return build_graph([module])


def nodes(graph: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [node for node in graph["nodes"] if node["kind"] == kind]


def edge_kinds(graph: dict[str, Any]) -> list[str]:
    return [edge["kind"] for edge in graph["edges"]]


def test_linear_script_has_exact_source_spans_and_fallthrough() -> None:
    graph = fixture_graph("linear.rpy")
    assert graph["counts"]["unresolved"] == 0
    label = nodes(graph, "label")[0]
    scene = nodes(graph, "scene")[0]
    assert label["source"]["start"] == {"line": 1, "column": 1}
    assert scene["source"]["start"] == {"line": 2, "column": 5}
    assert "label_entry" in edge_kinds(graph)
    assert "fallthrough" in edge_kinds(graph)


def test_menu_branches_reunite_at_a_directed_merge() -> None:
    graph = fixture_graph("menu_reunion.rpy")
    assert len(nodes(graph, "menu_choice")) == 2
    assert nodes(graph, "menu")[0]["metadata"]["captions"][0]["text"] == "Pick a route."
    merge = nodes(graph, "merge")[0]
    incoming = [edge for edge in graph["edges"] if edge["target"] == merge["id"]]
    assert {edge["kind"] for edge in incoming} >= {"fallthrough", "menu_no_choice"}
    right = next(node for node in nodes(graph, "menu_choice") if "right" in node["source_text"])
    assert right["metadata"]["condition"] == "right_is_open"


def test_conditional_has_ordered_branches_and_no_false_edge_with_else() -> None:
    graph = fixture_graph("conditional.rpy")
    branches = sorted(
        nodes(graph, "if_branch"), key=lambda node: node["source"]["start"]["line"]
    )
    assert len(branches) == 3
    assert [node["metadata"]["condition"] for node in branches] == [
        "score > 5",
        "score == 5",
        None,
    ]
    assert "condition_false" not in edge_kinds(graph)


def test_static_call_preserves_target_continuation_and_return() -> None:
    graph = fixture_graph("call_return.rpy")
    assert set(graph["reachable_labels"]) == {"helper", "start"}
    assert {"call", "call_continuation", "return"} <= set(edge_kinds(graph))
    call_node = nodes(graph, "call")[0]
    call_edges = [edge for edge in graph["edges"] if edge["source"] == call_node["id"]]
    assert {edge["kind"] for edge in call_edges} == {"call", "call_continuation"}


@pytest.mark.parametrize(
    ("fixture", "reason", "edge_kind"),
    [
        ("missing_target.rpy", "missing_label", "missing_jump"),
        ("dynamic_target.rpy", "dynamic_jump_target", "dynamic_jump"),
    ],
)
def test_unresolved_transfers_are_explicit(
    fixture: str, reason: str, edge_kind: str
) -> None:
    graph = fixture_graph(fixture)
    unresolved = nodes(graph, "unresolved")
    assert len(unresolved) == 1
    assert unresolved[0]["metadata"]["reason"] == reason
    assert edge_kind in edge_kinds(graph)


def test_graph_is_deterministic() -> None:
    assert fixture_graph("menu_reunion.rpy") == fixture_graph("menu_reunion.rpy")


def test_local_label_target_is_resolved_in_global_namespace() -> None:
    source = [
        "label start:\n",
        "    jump .later\n",
        "label .later:\n",
        "    return\n",
    ]
    module = parse_script("local.rpy", source)
    graph = build_graph([module])
    assert set(graph["reachable_labels"]) == {"start", "start.later"}
    assert graph["counts"]["unresolved"] == 0


def test_embedded_python_is_never_interpreted_as_control_flow() -> None:
    source = [
        "label start:\n",
        "    python:\n",
        "        jump = 'malicious'\n",
        "    return\n",
    ]
    module = parse_script("python.rpy", source)
    graph = build_graph([module])
    opaque = nodes(graph, "opaque")
    assert len(opaque) == 1
    assert opaque[0]["metadata"] == {
        "executed": False,
        "reason": "embedded_python_not_executed",
    }
    assert not nodes(graph, "jump")


def test_label_anchor_inside_menu_preserves_following_choice_statements() -> None:
    source = [
        "label start:\n",
        "    menu:\n",
        "        \"Replay\":\n",
        "            label replay_anchor:\n",
        "                scene black\n",
        "            \"After anchor.\"\n",
        "    return\n",
    ]
    module = parse_script("anchor.rpy", source)
    assert {label.name for label in module.labels} == {"start", "replay_anchor"}
    graph = build_graph([module])
    assert graph["counts"]["unresolved"] == 0
    assert len(nodes(graph, "label")) == 2
    assert any(node["source_text"] == '"After anchor."' for node in graph["nodes"])


def test_named_menu_is_a_static_jump_target() -> None:
    source = [
        "label start:\n",
        "    jump choose_route\n",
        "    menu choose_route:\n",
        "        \"Continue\":\n",
        "            return\n",
    ]
    module = parse_script("named-menu.rpy", source)
    graph = build_graph([module])
    assert {label.name for label in module.labels} == {"start", "choose_route"}
    assert graph["counts"]["unresolved"] == 0
    assert "jump" in edge_kinds(graph)


def test_root_label_falls_through_to_next_source_label() -> None:
    source = [
        "label start:\n",
        "    \"First.\"\n",
        "label next_label:\n",
        "    return\n",
    ]
    graph = build_graph([parse_script("root-fallthrough.rpy", source)])
    label = next(node for node in nodes(graph, "label") if node["metadata"]["name"] == "next_label")
    assert label["reachable_from_entry"] is True


def test_source_end_column_is_exclusive_and_includes_indentation() -> None:
    module = parse_script("span.rpy", ["label start:\n", "    pause 1\n"])
    graph = build_graph([module])
    pause = nodes(graph, "pause")[0]
    assert pause["source"]["start"] == {"line": 2, "column": 5}
    assert pause["source"]["end"] == {"line": 2, "column": 12}


def test_call_screen_is_unresolved_interactive_behavior_not_dynamic_label_call() -> None:
    module = parse_script(
        "screen-call.rpy", ["label start:\n", "    call screen chooser\n", "    return\n"]
    )
    graph = build_graph([module])
    assert not nodes(graph, "call")
    unresolved = nodes(graph, "unresolved")
    assert unresolved[0]["metadata"]["reason"] == "interactive_screen_call"
