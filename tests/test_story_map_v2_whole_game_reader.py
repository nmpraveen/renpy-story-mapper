from __future__ import annotations

import json
from collections import Counter

from scripts.m15_phase05_whole_game_reader import _reader_counts

from renpy_story_mapper.story_map_v2.whole_game_reader import (
    WHOLE_GAME_READER_MARKER,
    _label_route_plan,
    build_whole_game_reader_page,
)


def _source(line: int) -> dict[str, object]:
    return {
        "path": "game/story.rpy",
        "start": {"line": line, "column": 1},
        "end": {"line": line, "column": 20},
    }


def _node(identity: str, kind: str, line: int, text: str, **values: object) -> dict[str, object]:
    return {
        "id": identity,
        "kind": kind,
        "label": "start",
        "reachable_from_entry": True,
        "source": _source(line),
        "source_text": text,
        **values,
    }


def _edge(source: str, target: str) -> dict[str, object]:
    return {"source": source, "target": target, "kind": "flow", "metadata": {}}


def _transfer(source: str, target: str, kind: str) -> dict[str, object]:
    return {"source": source, "target": target, "kind": kind, "metadata": {}}


def _fixture() -> tuple[dict[str, object], ...]:
    nodes = [
        _node("label", "label", 1, "label start:"),
        _node("opening", "statement", 2, '"Opening"'),
        _node("menu", "menu", 3, "menu:"),
        _node("yes", "menu_choice", 4, '"Yes":', metadata={"caption": "Yes"}),
        _node("no", "menu_choice", 5, '"No":', metadata={"caption": "No"}),
        _node("maybe", "menu_choice", 5, '"Maybe":', metadata={"caption": "Maybe"}),
        _node("mystery", "unresolved", 6, "unresolved dynamic jump"),
        _node("branch_story", "statement", 6, '"Branch"'),
        _node("gate", "if", 7, "if trust:"),
        _node("true", "if_branch", 8, "if trust:", metadata={"condition": "trust"}),
        _node("false", "merge", 7, "if trust:", metadata={"control": "if"}),
        _node("rejoin", "merge", 9, "if trust:", metadata={"control": "if"}),
        _node("end", "return", 10, "return"),
    ]
    graph = {
        "entry_label": "start",
        "nodes": nodes,
        "edges": [
            _edge("label", "opening"),
            _edge("opening", "menu"),
            _edge("menu", "yes"),
            _edge("menu", "no"),
            _edge("menu", "maybe"),
            _edge("maybe", "mystery"),
            _edge("yes", "branch_story"),
            _edge("branch_story", "gate"),
            _edge("gate", "true"),
            _edge("gate", "false"),
            _edge("true", "rejoin"),
            _edge("false", "rejoin"),
            _edge("no", "end"),
        ],
    }
    arms = [
        {
            "id": "menu_yes",
            "entry_node_id": "yes",
            "node_ids": ["yes", "branch_story", "gate", "true", "false", "rejoin"],
            "ordinal": 0,
            "state_reads": [],
            "state_writes": [],
            "terminal_node_ids": [],
        },
        {
            "id": "menu_no",
            "entry_node_id": "no",
            "node_ids": ["no", "end"],
            "ordinal": 1,
            "state_reads": [],
            "state_writes": [],
            "terminal_node_ids": ["end"],
        },
        {
            "id": "menu_maybe",
            "entry_node_id": "maybe",
            "node_ids": ["maybe", "mystery"],
            "ordinal": 2,
            "state_reads": [],
            "state_writes": [],
            "terminal_node_ids": [],
        },
        {
            "id": "gate_true",
            "entry_node_id": "true",
            "node_ids": ["true"],
            "ordinal": 0,
            "state_reads": [{"variable": "trust", "expression": "trust"}],
            "state_writes": [],
            "terminal_node_ids": [],
        },
        {
            "id": "gate_false",
            "entry_node_id": "false",
            "node_ids": ["false"],
            "ordinal": 1,
            "state_reads": [],
            "state_writes": [],
            "terminal_node_ids": [],
        },
    ]
    control_flow = {
        "arms": arms,
        "regions": [
            {
                "id": "menu_region",
                "split_node_id": "menu",
                "arm_ids": ["menu_yes", "menu_no", "menu_maybe"],
                "merge_node_id": None,
                "parent_region_id": None,
            },
            {
                "id": "gate_region",
                "split_node_id": "gate",
                "arm_ids": ["gate_true", "gate_false"],
                "merge_node_id": "rejoin",
                "parent_region_id": "menu_region",
            },
        ],
        "ownership": [
            {"node_id": "branch_story", "region_id": "menu_region", "arm_id": "menu_yes"}
        ],
    }
    packets = []
    results = []
    for index in range(597):
        corridor_id = f"corridor:{index}"
        story_node = "opening" if index == 0 else "branch_story"
        packets.append(
            {
                "corridor_id": corridor_id,
                "owning_label": "start",
                "python_corridor": {"narrative_statement_node_ids": [story_node]},
                "incoming_control_points": [],
            }
        )
        grade = "FAIL" if index < 3 else "LOW" if index < 29 else "PASS"
        results.append(
            {
                "corridor_id": corridor_id,
                "title": f"Beat {index}",
                "summary": f"Summary {index}.",
                "detail": f"Detail {index}.",
                "presentation_children": [],
                "packet_shape_grade": grade,
                "fidelity_grade": "PASS",
            }
        )
    corridors = {
        "entry_label": "start",
        "coverage_grade": "PASS",
        "counts": {
            "included_narrative_statements": 597,
            "mechanics": 6,
            "state_effects": 0,
            "mechanic_kinds": {"unresolved": 0},
        },
        "mechanics": [],
        "packets": packets,
    }
    summaries = {
        "results": results,
        "reader_excluded": [{"corridor_id": f"corridor:{index}"} for index in range(3)],
    }
    skeleton = {
        "entry_label": "start",
        "parser_extraction_grade": "PASS",
        "story_coverage_grade": "PASS",
        "skeleton": {"label_transitions": [], "loops": []},
    }
    return graph, control_flow, skeleton, corridors, summaries


def _fitting_room_fixture() -> tuple[dict[str, object], ...]:
    graph, control_flow, skeleton, corridors, summaries = _fixture()

    def node(
        identity: str, kind: str, line: int, text: str, label: str, **values: object
    ) -> dict[str, object]:
        value = _node(identity, kind, line, text, **values)
        value["label"] = label
        return value

    graph["nodes"] = [
        node("start_label", "label", 1, "label fitting_room:", "fitting_room"),
        node("opening", "statement", 2, '"They enter the fitting room."', "fitting_room"),
        node("menu", "menu", 3, "menu:", "fitting_room"),
        node(
            "push",
            "menu_choice",
            4,
            '"Push her out":',
            "fitting_room",
            metadata={"caption": "Push her out"},
        ),
        node("push_story", "statement", 5, '"Wanda changes alone."', "fitting_room"),
        node(
            "keep",
            "menu_choice",
            6,
            '"Keep arguing with her":',
            "fitting_room",
            metadata={"caption": "Keep arguing with her"},
        ),
        node(
            "call_argument",
            "call",
            7,
            "call kept_arguing from return_here",
            "fitting_room",
        ),
        node("shared_merge", "merge", 8, "menu:", "fitting_room"),
        node(
            "shared_story",
            "statement",
            9,
            '"They check out and leave the mall."',
            "fitting_room",
        ),
        node("jump_next", "jump", 10, "jump photo_studio", "fitting_room"),
        node("argument_label", "label", 20, "label kept_arguing:", "kept_arguing"),
        node(
            "argument_story",
            "statement",
            21,
            '"The fitting-room argument turns intimate."',
            "kept_arguing",
        ),
        node("argument_return", "return", 22, "return", "kept_arguing"),
        node("next_label", "label", 30, "label photo_studio:", "photo_studio"),
        node("next_story", "statement", 31, '"Wanda reaches the studio."', "photo_studio"),
        node("next_return", "return", 32, "return", "photo_studio"),
    ]
    graph["entry_label"] = "fitting_room"
    graph["edges"] = [
        _transfer("start_label", "opening", "fallthrough"),
        _transfer("opening", "menu", "fallthrough"),
        _transfer("menu", "push", "choice_body"),
        _transfer("menu", "keep", "choice_body"),
        _transfer("push", "push_story", "fallthrough"),
        _transfer("push_story", "shared_merge", "fallthrough"),
        _transfer("keep", "call_argument", "fallthrough"),
        _transfer("call_argument", "argument_label", "call"),
        _transfer("argument_label", "argument_story", "fallthrough"),
        _transfer("argument_story", "argument_return", "fallthrough"),
        _transfer("argument_return", "shared_merge", "return"),
        _transfer("shared_merge", "shared_story", "fallthrough"),
        _transfer("shared_story", "jump_next", "fallthrough"),
        _transfer("jump_next", "next_label", "jump"),
        _transfer("next_label", "next_story", "fallthrough"),
        _transfer("next_story", "next_return", "fallthrough"),
    ]
    control_flow["arms"] = [
        {
            "id": "push_arm",
            "entry_node_id": "push",
            "node_ids": ["push", "push_story"],
            "ordinal": 0,
            "state_reads": [],
            "state_writes": [],
            "terminal_node_ids": [],
        },
        {
            "id": "keep_arm",
            "entry_node_id": "keep",
            "node_ids": ["keep", "call_argument", "return_here"],
            "ordinal": 1,
            "state_reads": [],
            "state_writes": [],
            "terminal_node_ids": [],
        },
    ]
    control_flow["regions"] = [
        {
            "id": "fitting_menu",
            "split_node_id": "menu",
            "arm_ids": ["push_arm", "keep_arm"],
            "merge_node_id": "shared_merge",
            "parent_region_id": None,
        }
    ]
    control_flow["ownership"] = [
        {"node_id": "push_story", "region_id": "fitting_menu", "arm_id": "push_arm"},
        {
            "node_id": "call_argument",
            "region_id": "fitting_menu",
            "arm_id": "keep_arm",
        },
    ]
    skeleton.update(
        {
            "entry_label": "fitting_room",
            "skeleton": {
                "label_transitions": [
                    {
                        "source_label": "fitting_room",
                        "target_label": "kept_arguing",
                        "transfer_kind": "call",
                    },
                    {
                        "source_label": "kept_arguing",
                        "target_label": "fitting_room",
                        "transfer_kind": "return",
                    },
                    {
                        "source_label": "fitting_room",
                        "target_label": "photo_studio",
                        "transfer_kind": "jump",
                    },
                ],
                "loops": [],
            },
            "counts": {
                "route_arms": 2,
                "demonstrated_rejoins": 1,
                "loop_components": 0,
                "terminals": 1,
            },
            "coverage": {"counts": {"reached_labels": 3}},
        }
    )
    corridors["entry_label"] = "fitting_room"
    packets = corridors["packets"]
    for index, packet in enumerate(packets):
        packet["owning_label"] = "fitting_room"
        packet["python_corridor"]["narrative_statement_node_ids"] = ["opening"]
        if index == 3:
            packet["owning_label"] = "kept_arguing"
            packet["python_corridor"]["narrative_statement_node_ids"] = ["argument_story"]
        elif index == 4:
            packet["python_corridor"]["narrative_statement_node_ids"] = ["shared_story"]
        elif index == 5:
            packet["owning_label"] = "photo_studio"
            packet["python_corridor"]["narrative_statement_node_ids"] = ["next_story"]
        elif index == 6:
            packet["python_corridor"]["narrative_statement_node_ids"] = ["push_story"]
    summaries["results"][3].update(
        {
            "title": "The Fitting-Room Argument Turns Intimate",
            "summary": "Nicole stays and the argument becomes intimate.",
            "detail": "Only the arguing route enters this scene.",
        }
    )
    summaries["results"][4].update(
        {
            "title": "They Leave the Mall Together",
            "summary": "Both routes continue after the fitting room.",
            "detail": "The shared continuation appears once after the routes meet.",
        }
    )
    summaries["results"][5].update(
        {
            "title": "Wanda Heads to the Studio",
            "summary": "Wanda reaches Faye's studio.",
            "detail": "The next story begins.",
        }
    )
    return graph, control_flow, skeleton, corridors, summaries


def test_whole_game_reader_stitches_corridors_under_python_owned_routes() -> None:
    page = build_whole_game_reader_page(*_fixture())

    assert page["analysis_notes"][0] == WHOLE_GAME_READER_MARKER
    assert set(page) == {
        "schema",
        "status",
        "reason",
        "title",
        "overview",
        "analysis_notes",
        "sections",
    }
    event = page["sections"][0]["events"][0]
    assert event["title"] == "Routes: Yes / No / Maybe"
    assert event["summary"] == ""
    assert event["detail_summary"] == ""
    menu = event["choices"][0]
    yes, no, maybe = menu["arms"]
    assert [arm["caption"] for arm in menu["arms"]] == ["Yes", "No", "Maybe"]
    assert no["outcome_kind"] == "ends"
    assert maybe["outcome_kind"] == "unresolved"
    assert maybe["outline_summary"] == "Unresolved at start."
    assert len(yes["nested_choices"]) == 1
    gate = yes["nested_choices"][0]
    assert gate["control_kind"] == "condition"
    assert [arm["caption"] for arm in gate["arms"]] == ["Requires: trust", "Otherwise"]
    assert {arm["outcome_kind"] for arm in gate["arms"]} == {"rejoins"}
    assert "Detail 3." in yes["detail_summary"]
    assert "Detail 3." not in event["detail_summary"]

    details = [event["detail_summary"]]
    pending = [menu]
    controls = 0
    arms = 0
    outcomes: Counter[str] = Counter()
    while pending:
        choice = pending.pop()
        controls += 1
        for arm in choice["arms"]:
            arms += 1
            outcomes[arm["outcome_kind"]] += 1
            details.append(arm["detail_summary"])
            pending.extend(arm["nested_choices"])
    combined = "\n".join(details)
    assert combined.count("Detail ") == 594
    assert "Detail 0." not in combined
    assert "Detail 1." not in combined
    assert "Detail 2." not in combined
    assert controls == 2
    assert arms == 5
    assert outcomes == {"continues": 1, "rejoins": 2, "ends": 1, "unresolved": 1}
    assert "Continue through this Python-owned story point" not in json.dumps(page)


def test_label_route_plan_keeps_shared_loop_and_interleaved_entries_non_recursive() -> None:
    nodes = {
        item["id"]: item
        for item in [
            _node("start_label", "label", 1, "label start:"),
            _node("arm_a_jump", "jump", 2, "jump shared"),
            _node("arm_b_fallthrough", "statement", 3, '"Shared"'),
            _node("arm_a_loop", "jump", 4, "jump looped"),
            _node("arm_a_call", "call", 5, "call interleaved"),
            {
                **_node("shared_label", "label", 10, "label shared:"),
                "label": "shared",
            },
            {
                **_node("looped_label", "label", 20, "label looped:"),
                "label": "looped",
            },
            {
                **_node("interleaved_label", "label", 30, "label interleaved:"),
                "label": "interleaved",
            },
        ]
    }
    edges = [
        _transfer("arm_a_jump", "shared_label", "jump"),
        _transfer("arm_b_fallthrough", "shared_label", "fallthrough"),
        _transfer("arm_a_loop", "looped_label", "jump"),
        _transfer("arm_a_call", "interleaved_label", "call"),
    ]
    skeleton = {
        "skeleton": {
            "label_transitions": [
                {
                    "source_label": "start",
                    "target_label": "shared",
                    "transfer_kind": "jump",
                },
                {
                    "source_label": "start",
                    "target_label": "shared",
                    "transfer_kind": "fallthrough",
                },
                {
                    "source_label": "start",
                    "target_label": "looped",
                    "transfer_kind": "jump",
                },
                {
                    "source_label": "start",
                    "target_label": "interleaved",
                    "transfer_kind": "call",
                },
            ],
            "loops": [{"labels": ["looped"]}],
        }
    }
    owners = {
        "arm_a_jump": "arm_a",
        "arm_b_fallthrough": "arm_b",
        "arm_a_loop": "arm_a",
        "arm_a_call": "arm_a",
    }
    plan = _label_route_plan(
        graph={"entry_label": "start"},
        skeleton=skeleton,
        nodes=nodes,
        edges=edges,
        visible_labels={"shared", "looped", "interleaved"},
        arm_labels={"arm_a": "start", "arm_b": "start"},
        interleaved_arms={"arm_a"},
        owning_arm=lambda node_id, _label: owners.get(node_id),
    )

    assert plan["placements"] == {}
    references = {
        (item["arm_id"], item["target_label"], item["entry_kind"])
        for item in plan["references"]
    }
    assert references == {
        ("arm_a", "looped", "loop"),
        ("arm_a", "interleaved", "unresolved"),
    }
    assert plan["counts"]["shared"] == 1
    assert plan["counts"]["loop"] == 1
    assert plan["counts"]["unresolved"] == 1


def test_whole_game_reader_keeps_called_fitting_room_event_under_its_only_arm() -> None:
    fixture = _fitting_room_fixture()
    page = build_whole_game_reader_page(*fixture)

    root_events = page["sections"][0]["events"]
    assert [event["selection_id"] for event in root_events] == [
        "whole-game:label:fitting_room",
        "whole-game:label:photo_studio",
    ]
    fitting_room = root_events[0]
    push, keep = fitting_room["choices"][0]["arms"]
    assert push["caption"] == "Push her out"
    assert push["route_flow"] == []
    assert keep["caption"] == "Keep arguing with her"
    assert len(keep["route_flow"]) == 1
    called = keep["route_flow"][0]
    assert called["kind"] == "event"
    assert called["transfer_kind"] == "call"
    assert called["entry_kind"] == "unique"
    assert called["event"]["selection_id"] == "whole-game:label:kept_arguing"
    assert called["event"]["title"] == "The Fitting-Room Argument Turns Intimate"
    assert "shared continuation appears once" not in called["event"]["detail_summary"]
    assert fitting_room["detail_summary"].count("shared continuation appears once") == 1
    assert sum(
        event["selection_id"] == "whole-game:label:kept_arguing"
        for event in root_events
    ) == 0
    assert any(
        "1 calls, and 1 returns" in note and "1 unique entries" in note
        for note in page["analysis_notes"]
    )
    counts = _reader_counts(page, *fixture[:3], *fixture[3:])
    assert counts["label_events"] == 3
    assert counts["visible_controls"] == 1
    assert counts["visible_route_arms"] == 2
    assert counts["reader_corridors"] == 594
