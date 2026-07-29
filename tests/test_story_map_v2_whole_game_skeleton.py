from __future__ import annotations

from copy import deepcopy

from renpy_story_mapper.story_map_v2.whole_game_skeleton import build_whole_game_skeleton


def _source(line: int) -> dict[str, object]:
    return {
        "path": "game/story.rpy",
        "start": {"line": line, "column": 1},
        "end": {"line": line, "column": 10},
    }


def _graph() -> dict[str, object]:
    nodes = [
        {
            "id": "label-start",
            "kind": "label",
            "label": "start",
            "reachable_from_entry": True,
            "source": _source(1),
            "source_text": "label start:",
        },
        {
            "id": "menu",
            "kind": "menu",
            "label": "start",
            "reachable_from_entry": True,
            "source": _source(2),
            "source_text": "menu:",
        },
        {
            "id": "arm",
            "kind": "menu_choice",
            "label": "start",
            "reachable_from_entry": True,
            "source": _source(3),
            "source_text": '"Continue":',
        },
        {
            "id": "jump",
            "kind": "jump",
            "label": "start",
            "reachable_from_entry": True,
            "source": _source(4),
            "source_text": "jump ending",
            "metadata": {"target_label": "ending"},
        },
        {
            "id": "effect",
            "kind": "opaque",
            "label": "start",
            "reachable_from_entry": True,
            "source": _source(5),
            "source_text": "$ score += 1",
        },
        {
            "id": "unresolved",
            "kind": "unresolved",
            "label": "start",
            "reachable_from_entry": True,
            "source": _source(6),
            "source_text": "jump missing",
            "metadata": {"reason": "missing_label", "target_label": "missing"},
        },
        {
            "id": "label-ending",
            "kind": "label",
            "label": "ending",
            "reachable_from_entry": True,
            "source": _source(10),
            "source_text": "label ending:",
        },
        {
            "id": "return",
            "kind": "return",
            "label": "ending",
            "reachable_from_entry": True,
            "source": _source(11),
            "source_text": "return",
        },
        {
            "id": "label-unused",
            "kind": "label",
            "label": "unused",
            "reachable_from_entry": False,
            "source": _source(20),
            "source_text": "label unused:",
        },
    ]
    edges = [
        {"source": "label-start", "target": "menu", "kind": "label_entry"},
        {"source": "menu", "target": "arm", "kind": "menu_choice"},
        {"source": "arm", "target": "jump", "kind": "choice_body"},
        {"source": "jump", "target": "label-ending", "kind": "jump"},
        {"source": "jump", "target": "unresolved", "kind": "unresolved_behavior"},
        {"source": "label-ending", "target": "return", "kind": "label_entry"},
    ]
    return {
        "entry_label": "start",
        "counts": {
            "nodes": len(nodes),
            "edges": len(edges),
            "labels_in_scope": 3,
            "reachable_labels": 2,
            "unresolved": 1,
        },
        "nodes": nodes,
        "edges": edges,
        "reachable_labels": ["ending", "start"],
    }


def _control_flow() -> dict[str, object]:
    return {
        "arms": [{"id": "arm-1"}],
        "loops": [
            {
                "id": "loop-1",
                "node_ids": ["menu", "arm"],
                "entry_node_ids": ["menu"],
                "back_edge_ids": ["back-1"],
                "exit_edge_ids": ["exit-1"],
                "irreducible": False,
                "self_loop": False,
            }
        ],
        "terminals": [
            {"node_id": "return", "kind": "procedure_return_boundary"},
            {"node_id": "unresolved", "kind": "unresolved"},
        ],
        "diagnostics": [],
    }


def _parser_coverage() -> dict[str, object]:
    return {
        "deterministic": {
            "grade": "PASS",
            "python_labels": 3,
            "renpy_labels": 4,
            "matched_python_labels": 3,
            "compiler_internal_labels": 1,
            "canonical_substantive_labels_missing_from_python": [],
            "missing_python_node_count": 0,
        }
    }


def test_whole_game_projection_is_compact_deterministic_and_exact() -> None:
    graph = _graph()
    result = build_whole_game_skeleton(
        graph,
        control_flow=_control_flow(),
        parser_coverage=_parser_coverage(),
        authority_bindings={
            "m01_graph/authoritative": "graph-hash",
            "m06_control_flow/authoritative": "flow-hash",
        },
    )

    assert result["parser_extraction_grade"] == "PASS"
    assert result["label_accounting_grade"] == "PASS"
    assert result["story_coverage_grade"] == "PASS"
    assert result["resolution_state"] == "partial"
    assert result["coverage"]["counts"] == {  # type: ignore[index]
        "total_parser_labels": 3,
        "reached_labels": 2,
        "unreachable_labels": 1,
        "accounted_labels": 3,
        "unresolved_mechanics": 1,
    }
    assert result["coverage"]["unreachable_labels"][0]["label"] == "unused"  # type: ignore[index]
    assert result["coverage"]["unresolved_facts"][0]["metadata"]["reason"] == (  # type: ignore[index]
        "missing_label"
    )
    assert result["skeleton"]["label_transitions"] == [  # type: ignore[index]
        {
            "source_label": "start",
            "target_label": "ending",
            "transfer_kind": "jump",
        }
    ]
    assert result["counts"]["direct_state_changes"] == 1  # type: ignore[index]
    assert result["counts"]["route_arms"] == 1  # type: ignore[index]
    assert result["counts"]["loop_components"] == 1  # type: ignore[index]
    assert result["counts"]["terminals"] == 2  # type: ignore[index]
    assert "controls" not in result["skeleton"]  # type: ignore[operator]
    assert result["authority_bindings"] == {
        "m01_graph/authoritative": "graph-hash",
        "m06_control_flow/authoritative": "flow-hash",
    }

    reordered = deepcopy(graph)
    reordered["nodes"] = list(reversed(reordered["nodes"]))  # type: ignore[index,assignment]
    reordered["edges"] = list(reversed(reordered["edges"]))  # type: ignore[index,assignment]
    assert build_whole_game_skeleton(
        reordered,
        control_flow=_control_flow(),
        parser_coverage=_parser_coverage(),
        authority_bindings={
            "m06_control_flow/authoritative": "flow-hash",
            "m01_graph/authoritative": "graph-hash",
        },
    ) == result


def test_whole_game_projection_fails_inconsistent_reachable_label_accounting() -> None:
    graph = _graph()
    graph["reachable_labels"] = ["start"]

    result = build_whole_game_skeleton(graph, parser_coverage=_parser_coverage())

    assert result["label_accounting_grade"] == "FAIL"
    assert result["story_coverage_grade"] == "FAIL"
    assert result["coverage"]["checks"]["reachable_label_set_matches"] is False  # type: ignore[index]
