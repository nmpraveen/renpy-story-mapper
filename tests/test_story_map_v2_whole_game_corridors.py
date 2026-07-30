from __future__ import annotations

from copy import deepcopy

import pytest

from renpy_story_mapper.story_map_v2.whole_game_corridors import (
    build_whole_game_corridor_packets,
)


def _source(line: int, *, column: int = 1) -> dict[str, object]:
    return {
        "path": "game/story.rpy",
        "start": {"line": line, "column": column},
        "end": {"line": line, "column": column + 10},
    }


def _node(
    node_id: str,
    kind: str,
    line: int,
    text: str,
    *,
    metadata: dict[str, object] | None = None,
    label: str = "start",
) -> dict[str, object]:
    return {
        "id": node_id,
        "kind": kind,
        "label": label,
        "reachable_from_entry": True,
        "source": _source(line),
        "source_text": text,
        **({} if metadata is None else {"metadata": metadata}),
    }


def _edge(source: str, target: str, kind: str, **metadata: object) -> dict[str, object]:
    return {
        "source": source,
        "target": target,
        "kind": kind,
        **({} if not metadata else {"metadata": metadata}),
    }


def _parsed(statements: list[tuple[int, str]]) -> list[dict[str, object]]:
    body = [
        {
            "type": "simple",
            "kind": "statement",
            "text": text,
            "source": {
                "path": "game/story.rpy",
                "start_line": line,
                "start_column": 1,
                "end_line": line,
                "end_column": 11,
            },
        }
        for line, text in statements
    ]
    return [
        {
            "schema_version": 1,
            "path": "game/story.rpy",
            "diagnostics": [],
            "top_level": [
                {
                    "type": "label",
                    "name": "start",
                    "body": body,
                    "source": body[0]["source"],
                }
            ],
        }
    ]


def _fixture() -> tuple[list[dict[str, object]], dict[str, object], dict[str, object]]:
    nodes = [
        _node("label", "label", 1, "label start:", metadata={"name": "start"}),
        _node("opening", "statement", 2, 'narrator "Opening."'),
        _node(
            "spoken_settings",
            "statement",
            3,
            'Wanda "Turn off hints in the settings menu."',
        ),
        _node(
            "helper",
            "statement",
            4,
            '"{i}If you want to turn off hints, use the settings menu.{/i}"',
        ),
        _node("menu", "menu", 5, "menu:", metadata={"captions": []}),
        _node(
            "end_arm",
            "menu_choice",
            6,
            '"End the massage":',
            metadata={"caption": "End the massage", "condition": None},
        ),
        _node("end_story", "statement", 7, 'narrator "The massage ends."'),
        _node(
            "keep_arm",
            "menu_choice",
            8,
            '"Keep going":',
            metadata={"caption": "Keep going", "condition": None},
        ),
        _node("nested_menu", "menu", 9, "menu:", metadata={"captions": []}),
        _node(
            "stop_arm",
            "menu_choice",
            10,
            '"Stop Faye":',
            metadata={"caption": "Stop Faye", "condition": None},
        ),
        _node("stop_story", "statement", 11, 'narrator "Faye stops."'),
        _node(
            "continue_arm",
            "menu_choice",
            12,
            '"Do nothing":',
            metadata={"caption": "Do nothing", "condition": None},
        ),
        _node("continue_story", "statement", 13, 'narrator "Faye continues."'),
        _node("nested_merge", "merge", 14, "menu:", metadata={"control": "menu"}),
        _node("outer_merge", "merge", 15, "menu:", metadata={"control": "menu"}),
        _node("scene", "scene", 16, "scene pool_day"),
        _node("shared", "statement", 17, 'narrator "The shared day begins."'),
        _node("condition", "if", 18, "if trust:", metadata={}),
        _node(
            "branch",
            "if_branch",
            19,
            "if trust:",
            metadata={"condition": "trust"},
        ),
        _node("effect", "opaque", 20, "$ trust += 1"),
        _node("jump", "jump", 21, "jump destination"),
        _node("call", "call", 22, "call helper"),
        _node("return", "return", 23, "return", metadata={"expression": None}),
        _node(
            "unresolved",
            "unresolved",
            24,
            "jump expression",
            metadata={"reason": "dynamic_target"},
        ),
    ]
    edges = [
        _edge("label", "opening", "label_entry"),
        _edge("opening", "spoken_settings", "fallthrough"),
        _edge("spoken_settings", "helper", "fallthrough"),
        _edge("helper", "menu", "fallthrough"),
        _edge("menu", "end_arm", "menu_choice", choice_index=0, condition=None),
        _edge("end_arm", "end_story", "choice_body"),
        _edge("end_story", "outer_merge", "fallthrough"),
        _edge("menu", "keep_arm", "menu_choice", choice_index=1, condition=None),
        _edge("keep_arm", "nested_menu", "choice_body"),
        _edge("nested_menu", "stop_arm", "menu_choice", choice_index=0, condition=None),
        _edge("stop_arm", "stop_story", "choice_body"),
        _edge("stop_story", "nested_merge", "fallthrough"),
        _edge("nested_menu", "continue_arm", "menu_choice", choice_index=1, condition=None),
        _edge("continue_arm", "continue_story", "choice_body"),
        _edge("continue_story", "nested_merge", "fallthrough"),
        _edge("nested_merge", "outer_merge", "fallthrough"),
        _edge("outer_merge", "scene", "fallthrough"),
        _edge("scene", "shared", "fallthrough"),
        _edge("shared", "condition", "fallthrough"),
        _edge("condition", "branch", "condition", branch_index=0, condition="trust"),
        _edge("branch", "effect", "branch_body"),
        _edge("effect", "jump", "fallthrough"),
        _edge("jump", "call", "jump"),
        _edge("call", "return", "call"),
        _edge("return", "unresolved", "return"),
    ]
    graph = {
        "entry_label": "start",
        "nodes": nodes,
        "edges": edges,
        "reachable_labels": ["start"],
    }

    def arm(arm_id: str, entry: str) -> dict[str, object]:
        return {
            "id": arm_id,
            "edge_id": f"edge:{arm_id}",
            "entry_node_id": entry,
            "node_ids": [],
            "ordinal": 1,
            "region_id": "region",
            "state_reads": [{"variable": "trust", "expression": "trust", "node_id": entry}],
            "state_writes": [],
            "terminal_node_ids": [],
            "terminal_summary": {},
            "unresolved": False,
        }

    control_flow = {
        "arms": [
            arm("arm_end", "end_arm"),
            arm("arm_keep", "keep_arm"),
            arm("arm_stop", "stop_arm"),
            arm("arm_continue", "continue_arm"),
        ],
        "regions": [
            {
                "id": "outer_region",
                "arm_ids": ["arm_end", "arm_keep"],
                "classification": "rejoining",
                "merge_node_id": "outer_merge",
                "node_ids": [],
                "parent_region_id": None,
                "persistence_reasons": [],
                "single_entry": True,
                "single_exit": True,
                "split_node_id": "menu",
            },
            {
                "id": "nested_region",
                "arm_ids": ["arm_stop", "arm_continue"],
                "classification": "rejoining",
                "merge_node_id": "nested_merge",
                "node_ids": [],
                "parent_region_id": "outer_region",
                "persistence_reasons": [],
                "single_entry": True,
                "single_exit": True,
                "split_node_id": "nested_menu",
            },
        ],
        "ownership": [
            {"arm_id": None, "node_id": "nested_menu", "region_id": "nested_region"},
            {"arm_id": "arm_keep", "node_id": "nested_merge", "region_id": "outer_region"},
        ],
    }
    parsed = _parsed(
        [
            (2, 'narrator "Opening."'),
            (3, 'Wanda "Turn off hints in the settings menu."'),
            (4, '"{i}If you want to turn off hints, use the settings menu.{/i}"'),
            (7, 'narrator "The massage ends."'),
            (11, 'narrator "Faye stops."'),
            (13, 'narrator "Faye continues."'),
            (17, 'narrator "The shared day begins."'),
        ]
    )
    return parsed, graph, control_flow


def test_packets_preserve_all_rejoin_origins_next_control_and_exact_accounting() -> None:
    parsed, graph, control_flow = _fixture()

    result = build_whole_game_corridor_packets(parsed, graph, control_flow)

    assert result["coverage_grade"] == "PASS"
    assert result["counts"]["reachable_statement_nodes"] == 7  # type: ignore[index]
    assert result["counts"]["included_narrative_statements"] == 6  # type: ignore[index]
    assert result["counts"]["excluded_non_story_statements"] == 1  # type: ignore[index]
    assert result["counts"]["accounted_statement_nodes"] == 7  # type: ignore[index]
    opening = next(packet for packet in result["packets"] if "Opening." in packet["story_text"])
    assert "Wanda: Turn off hints in the settings menu." in opening["story_text"]
    assert "If you want to turn off hints" not in opening["story_text"]
    assert opening["source"]["end_line"] == 4

    shared = next(
        packet for packet in result["packets"] if "The shared day begins." in packet["story_text"]
    )
    origins = shared["incoming_rejoins"][0]["route_origins"]
    assert {origin["origin"]["metadata"].get("caption") for origin in origins} == {
        "End the massage",
        "Stop Faye",
        "Do nothing",
    }
    assert all(isinstance(origin["state_reads"][0], dict) for origin in origins)
    assert shared["next_control_points"][0]["kind"] == "if"
    assert shared["next_control_points"][0]["arms"][0]["metadata"]["condition"] == "trust"
    assert shared["presentation_children"] == []
    assert result["presentation_contract"]["packet_array_order"] == "processing_order_only"
    assert "place every branch before" in result["presentation_contract"]["reader_order_rule"]

    mechanics = {item["kind"] for item in result["mechanics"]}
    assert {"menu", "if", "effect", "jump", "call", "return", "unresolved"} <= mechanics

    reordered_graph = deepcopy(graph)
    reordered_graph["nodes"] = list(reversed(reordered_graph["nodes"]))
    reordered_graph["edges"] = list(reversed(reordered_graph["edges"]))
    reordered_flow = deepcopy(control_flow)
    for key in ("arms", "regions", "ownership"):
        reordered_flow[key] = list(reversed(reordered_flow[key]))
    assert build_whole_game_corridor_packets(parsed, reordered_graph, reordered_flow) == result


def test_long_python_corridor_is_not_split_by_size_or_count() -> None:
    statement_count = 150
    nodes = [_node("label", "label", 1, "label start:")]
    edges: list[dict[str, object]] = []
    parsed_lines: list[tuple[int, str]] = []
    previous = "label"
    for index in range(statement_count):
        node_id = f"story_{index:03d}"
        line = index + 2
        text = f'narrator "Story line {index}."'
        nodes.append(_node(node_id, "statement", line, text))
        edges.append(_edge(previous, node_id, "label_entry" if index == 0 else "fallthrough"))
        parsed_lines.append((line, text))
        previous = node_id
    nodes.append(_node("return", "return", statement_count + 2, "return"))
    edges.append(_edge(previous, "return", "fallthrough"))

    result = build_whole_game_corridor_packets(
        _parsed(parsed_lines),
        {"entry_label": "start", "nodes": nodes, "edges": edges},
        {"arms": [], "regions": [], "ownership": []},
    )

    assert result["counts"]["packets"] == 1  # type: ignore[index]
    assert result["packets"][0]["python_corridor"]["narrative_statement_count"] == 150


def test_missing_parsed_statement_binding_fails_instead_of_silently_dropping_story() -> None:
    parsed, graph, control_flow = _fixture()
    parsed[0]["top_level"][0]["body"] = parsed[0]["top_level"][0]["body"][:-1]

    with pytest.raises(ValueError, match="lack parsed_source bindings"):
        build_whole_game_corridor_packets(parsed, graph, control_flow)


def test_setup_save_and_credits_exclusions_are_exact_and_reasoned() -> None:
    nodes = [
        _node("label", "label", 1, "label start:"),
        _node("adult_prompt", "statement", 2, '"Are you 18 years or older?"'),
        _node("adult_refusal", "statement", 3, '"Sorry! You cannot play this game."'),
        _node("save_prompt", "statement", 4, 'narrator "You should save now"'),
        _node("real_dialogue", "statement", 5, 'Wanda "You should save now"'),
        _node("jump", "jump", 6, "jump credits"),
        _node("credits_label", "label", 7, "label credits:", label="credits"),
        _node(
            "credits_thanks",
            "statement",
            8,
            (
                'centered "{size=+15}A special thank you to our treasured patrons, without whom '
                'this game would not be possible. Here are some of them.....{/size}"'
            ),
            label="credits",
        ),
        _node("return", "return", 9, "return", label="credits"),
    ]
    edges = [
        _edge("label", "adult_prompt", "label_entry"),
        _edge("adult_prompt", "adult_refusal", "fallthrough"),
        _edge("adult_refusal", "save_prompt", "fallthrough"),
        _edge("save_prompt", "real_dialogue", "fallthrough"),
        _edge("real_dialogue", "jump", "fallthrough"),
        _edge("jump", "credits_label", "jump"),
        _edge("credits_label", "credits_thanks", "label_entry"),
        _edge("credits_thanks", "return", "fallthrough"),
    ]
    parsed = _parsed(
        [
            (2, '"Are you 18 years or older?"'),
            (3, '"Sorry! You cannot play this game."'),
            (4, 'narrator "You should save now"'),
            (5, 'Wanda "You should save now"'),
            (
                8,
                (
                    'centered "{size=+15}A special thank you to our treasured patrons, without '
                    'whom this game would not be possible. Here are some of them.....{/size}"'
                ),
            ),
        ]
    )

    result = build_whole_game_corridor_packets(
        parsed,
        {
            "entry_label": "start",
            "nodes": nodes,
            "edges": edges,
            "reachable_labels": ["start", "credits"],
        },
        {"arms": [], "regions": [], "ownership": []},
    )

    assert result["counts"]["reachable_statement_nodes"] == 5  # type: ignore[index]
    assert result["counts"]["included_narrative_statements"] == 1  # type: ignore[index]
    assert result["counts"]["excluded_non_story_statements"] == 4  # type: ignore[index]
    assert result["counts"]["filtered_statement_reasons"] == {  # type: ignore[index]
        "adult_entry_prompt": 1,
        "adult_entry_refusal": 1,
        "checkpoint_save_prompt": 1,
        "credits_patron_thank_you": 1,
    }
    assert result["packets"][0]["story_text"] == "Wanda: You should save now"
