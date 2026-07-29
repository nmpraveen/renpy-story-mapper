from __future__ import annotations

from renpy_story_mapper.story_map_v2.whole_game_reader import (
    WHOLE_GAME_READER_MARKER,
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


def _fixture() -> tuple[dict[str, object], ...]:
    nodes = [
        _node("label", "label", 1, "label start:"),
        _node("opening", "statement", 2, '"Opening"'),
        _node("menu", "menu", 3, "menu:"),
        _node("yes", "menu_choice", 4, '"Yes":', metadata={"caption": "Yes"}),
        _node("no", "menu_choice", 5, '"No":', metadata={"caption": "No"}),
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
                "arm_ids": ["menu_yes", "menu_no"],
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
    }
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
    menu = event["choices"][0]
    yes, no = menu["arms"]
    assert [arm["caption"] for arm in menu["arms"]] == ["Yes", "No"]
    assert no["outcome_kind"] == "ends"
    assert len(yes["nested_choices"]) == 1
    gate = yes["nested_choices"][0]
    assert gate["control_kind"] == "condition"
    assert [arm["caption"] for arm in gate["arms"]] == ["Requires: trust", "Otherwise"]
    assert {arm["outcome_kind"] for arm in gate["arms"]} == {"rejoins"}
    assert "Detail 3." in yes["detail_summary"]

    details = [event["detail_summary"]]
    pending = [menu]
    while pending:
        choice = pending.pop()
        for arm in choice["arms"]:
            details.append(arm["detail_summary"])
            pending.extend(arm["nested_choices"])
    combined = "\n".join(details)
    assert combined.count("Detail ") == 594
    assert "Detail 0." not in combined
    assert "Detail 1." not in combined
    assert "Detail 2." not in combined
