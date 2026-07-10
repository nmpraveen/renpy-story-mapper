from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from renpy_story_mapper import semantic
from renpy_story_mapper.graph import build_graph
from renpy_story_mapper.parser import parse_script

FIXTURES = Path(__file__).parent / "fixtures" / "semantic"


def semantic_story(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    fixture = FIXTURES / name
    with fixture.open(encoding="utf-8") as stream:
        graph = build_graph([parse_script(f"semantic/{name}", stream)])
    return graph, semantic.build_semantic_story(graph)


def records(story: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = story[key]
    assert isinstance(value, list)
    assert all(isinstance(item, dict) for item in value)
    return value


def by_label(story: dict[str, Any], label: str) -> dict[str, Any]:
    return next(scene for scene in records(story, "scenes") if scene["label"] == label)


def scene_beats(story: dict[str, Any], label: str) -> list[dict[str, Any]]:
    scene = by_label(story, label)
    ids = set(scene["beat_ids"])
    return [beat for beat in records(story, "beats") if beat["id"] in ids]


def beat_of_kind(story: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [beat for beat in records(story, "beats") if beat["kind"] == kind]


def narrative_beat_with(story: dict[str, Any], text: str) -> dict[str, Any]:
    return next(
        beat
        for beat in beat_of_kind(story, "narrative")
        if any(item["text"] == text for item in beat["content"])
    )


def assert_source(source: dict[str, Any], path: str, start: int, end: int) -> None:
    assert source["path"] == path
    assert source["start"]["line"] == start
    assert source["end"]["line"] == end


def test_public_schema_is_explicit_and_source_linked() -> None:
    _, story = semantic_story("grouping.rpy")

    assert set(story) == {
        "schema_version",
        "entry_scene_id",
        "scenes",
        "beats",
        "transitions",
        "unresolved",
    }
    assert story["schema_version"] == 1
    assert isinstance(story["entry_scene_id"], str)

    scene_ids = {scene["id"] for scene in records(story, "scenes")}
    beat_ids = {beat["id"] for beat in records(story, "beats")}
    assert story["entry_scene_id"] in scene_ids
    for scene in records(story, "scenes"):
        assert set(scene) == {
            "id",
            "label",
            "classification",
            "reachable",
            "source",
            "beat_ids",
        }
        assert scene["classification"] in {"narrative", "utility", "unknown"}
        assert set(scene["beat_ids"]) <= beat_ids
    for beat in records(story, "beats"):
        assert {
            "id",
            "scene_id",
            "kind",
            "reachable",
            "source",
            "graph_node_ids",
        } <= set(beat)
        assert beat["scene_id"] in scene_ids
        assert beat["graph_node_ids"]


def test_adjacent_narration_and_dialogue_form_one_provenance_preserving_beat() -> None:
    _, story = semantic_story("grouping.rpy")
    narrative = beat_of_kind(story, "narrative")

    assert len(narrative) == 1
    beat = narrative[0]
    assert_source(beat["source"], "semantic/grouping.rpy", 3, 6)
    assert beat["content"] == [
        {
            "kind": "narration",
            "speaker": None,
            "text": "The room is quiet.",
            "source": beat["content"][0]["source"],
        },
        {
            "kind": "dialogue",
            "speaker": "eileen",
            "text": "We should go.",
            "source": beat["content"][1]["source"],
        },
        {
            "kind": "dialogue",
            "speaker": "eileen",
            "text": "Now.",
            "source": beat["content"][2]["source"],
        },
        {
            "kind": "narration",
            "speaker": None,
            "text": "Agreed.",
            "source": beat["content"][3]["source"],
        },
    ]
    for line, item in zip(range(3, 7), beat["content"], strict=True):
        assert_source(item["source"], "semantic/grouping.rpy", line, line)
    assert len(beat["graph_node_ids"]) == 4


def test_labels_and_control_flow_split_beats_and_preserve_typed_transitions() -> None:
    _, story = semantic_story("branching.rpy")

    assert {scene["label"] for scene in records(story, "scenes")} == {
        "start",
        "helper",
        "ending",
    }
    start_kinds = {beat["kind"] for beat in scene_beats(story, "start")}
    assert {"choice", "condition", "call", "jump"} <= start_kinds

    transitions = records(story, "transitions")
    choice_edges = [edge for edge in transitions if edge["kind"] == "choice"]
    assert {(edge["caption"], edge["condition"]) for edge in choice_edges} == {
        ("Take the lit path", "lantern"),
        ("Wait", None),
    }
    condition_edges = [edge for edge in transitions if edge["kind"] == "condition"]
    assert {edge["condition"] for edge in condition_edges} == {
        "courage > 5",
        "courage == 5",
        None,
    }
    assert {edge["kind"] for edge in transitions} >= {
        "call",
        "return",
        "jump",
        "fallthrough",
        "ending",
    }
    assert all(edge["resolved"] is True for edge in choice_edges + condition_edges)


def test_calls_returns_jumps_endings_and_label_fallthrough_remain_distinct() -> None:
    _, branching = semantic_story("branching.rpy")
    kinds = {beat["kind"] for beat in records(branching, "beats")}
    assert {"call", "return", "jump", "ending"} <= kinds

    _, falling = semantic_story("dynamic_and_fallthrough.rpy")
    fallthrough = [
        edge for edge in records(falling, "transitions") if edge["kind"] == "fallthrough"
    ]
    assert any(
        edge["source_label"] == "start" and edge["target_label"] == "continued"
        for edge in fallthrough
    )


def test_label_classification_and_reachability_are_conservative() -> None:
    _, story = semantic_story("classification.rpy")

    assert by_label(story, "start")["classification"] == "narrative"
    assert by_label(story, "utility")["classification"] == "utility"
    assert by_label(story, "chapter_two")["classification"] == "narrative"
    assert by_label(story, "unused_note")["classification"] == "unknown"
    assert by_label(story, "unused_note")["reachable"] is False
    assert all(beat["reachable"] is False for beat in scene_beats(story, "unused_note"))


def test_dynamic_transitions_are_unresolved_without_guessing_and_unreachable_is_retained() -> None:
    _, story = semantic_story("dynamic_and_fallthrough.rpy")

    unresolved = records(story, "unresolved")
    assert len(unresolved) == 1
    assert unresolved[0]["kind"] == "dynamic_jump_target"
    assert unresolved[0]["expression"] == "destination"
    assert unresolved[0]["resolved"] is False
    assert_source(unresolved[0]["source"], "semantic/dynamic_and_fallthrough.rpy", 6, 6)
    assert by_label(story, "unreachable_story")["reachable"] is False


def test_semantic_build_does_not_mutate_phase_one_graph() -> None:
    fixture = FIXTURES / "branching.rpy"
    with fixture.open(encoding="utf-8") as stream:
        graph = build_graph([parse_script("semantic/branching.rpy", stream)])
    original = copy.deepcopy(graph)

    semantic.build_semantic_story(graph)

    assert graph == original


def test_ids_and_canonical_json_are_byte_identical_across_builds() -> None:
    _, first = semantic_story("branching.rpy")
    _, second = semantic_story("branching.rpy")

    canonical_first = json.dumps(
        first, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    canonical_second = json.dumps(
        second, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()

    assert canonical_first == canonical_second
    assert [scene["id"] for scene in records(first, "scenes")] == [
        scene["id"] for scene in records(second, "scenes")
    ]
    assert [beat["id"] for beat in records(first, "beats")] == [
        beat["id"] for beat in records(second, "beats")
    ]
    assert [edge["id"] for edge in records(first, "transitions")] == [
        edge["id"] for edge in records(second, "transitions")
    ]


def test_nonempty_menu_and_condition_branches_rejoin_once_after_the_merge() -> None:
    _, story = semantic_story("merge_and_branch_call.rpy")
    transitions = records(story, "transitions")
    choice = beat_of_kind(story, "choice")[0]
    condition = beat_of_kind(story, "condition")[0]
    after_menu = narrative_beat_with(story, "After menu.")
    after_condition = narrative_beat_with(story, "After condition.")

    for branch_text in ("Menu branch A.", "Menu branch B."):
        branch = narrative_beat_with(story, branch_text)
        assert [
            edge
            for edge in transitions
            if edge["source_beat_id"] == branch["id"]
            and edge["target_beat_id"] == after_menu["id"]
            and edge["kind"] == "fallthrough"
        ]
        assert not any(
            edge["source_beat_id"] == branch["id"]
            and edge["target_beat_id"] == choice["id"]
            for edge in transitions
        )

    for branch_text in ("Condition branch B.", "Condition fallback."):
        branch = narrative_beat_with(story, branch_text)
        assert [
            edge
            for edge in transitions
            if edge["source_beat_id"] == branch["id"]
            and edge["target_beat_id"] == after_condition["id"]
            and edge["kind"] == "fallthrough"
        ]
        assert not any(
            edge["source_beat_id"] == branch["id"]
            and edge["target_beat_id"] == condition["id"]
            for edge in transitions
        )

    route_keys = [
        (
            edge["kind"],
            edge["source_beat_id"],
            edge["target_beat_id"],
            edge.get("caption"),
            edge.get("condition"),
        )
        for edge in transitions
    ]
    assert len(route_keys) == len(set(route_keys))


def test_call_and_return_inside_condition_reach_post_condition_continuation() -> None:
    _, story = semantic_story("merge_and_branch_call.rpy")
    transitions = records(story, "transitions")
    call = beat_of_kind(story, "call")[0]
    helper_return = next(
        beat for beat in scene_beats(story, "helper") if beat["kind"] == "return"
    )
    continuation = narrative_beat_with(story, "After condition.")

    assert any(
        edge["kind"] == "call_continuation"
        and edge["source_beat_id"] == call["id"]
        and edge["target_beat_id"] == continuation["id"]
        for edge in transitions
    )
    assert any(
        edge["kind"] == "return"
        and edge["source_beat_id"] == helper_return["id"]
        and edge["target_beat_id"] == continuation["id"]
        for edge in transitions
    )


def test_all_call_variants_retain_non_fallthrough_return_site_summaries() -> None:
    modules = []
    for name in ("call_variants.rpy", "external_call_target.rpy"):
        fixture = FIXTURES / name
        with fixture.open(encoding="utf-8") as stream:
            modules.append(parse_script(f"semantic/{name}", stream))
    graph = build_graph(modules, scope_paths={"semantic/call_variants.rpy"})
    story = semantic.build_semantic_story(graph)
    transitions = records(story, "transitions")

    expectations = {
        "call helper": "After static call.",
        "call expression dynamic_destination": "After dynamic call.",
        "call missing_helper": "After missing call.",
        "call external_helper": "After out-of-scope call.",
    }
    calls = {beat["source_text"]: beat for beat in beat_of_kind(story, "call")}
    for source_text, continuation_text in expectations.items():
        continuation = narrative_beat_with(story, continuation_text)
        summaries = [
            edge
            for edge in transitions
            if edge["kind"] == "call_continuation"
            and edge["source_beat_id"] == calls[source_text]["id"]
        ]
        assert len(summaries) == 1
        summary = summaries[0]
        assert summary["target_beat_id"] == continuation["id"]
        assert summary["resolved"] is True
        assert summary["graph_edge"]["kind"] == "call_continuation"
        assert summary["graph_edge"]["metadata"] == {
            "semantic": "return_site_not_immediate_fallthrough"
        }


def test_natural_module_end_has_explicit_targeted_ending() -> None:
    _, story = semantic_story("module_end.rpy")
    narrative = narrative_beat_with(story, "Natural ending.")
    endings = beat_of_kind(story, "ending")

    assert len(endings) == 1
    ending = endings[0]
    ending_edges = [
        edge
        for edge in records(story, "transitions")
        if edge["kind"] == "ending" and edge["source_beat_id"] == narrative["id"]
    ]
    assert len(ending_edges) == 1
    assert ending_edges[0]["target_scene_id"] == ending["scene_id"]
    assert ending_edges[0]["target_beat_id"] == ending["id"]
    assert ending_edges[0]["resolved"] is True


def test_multiline_narration_and_dialogue_preserve_literal_text_and_spans() -> None:
    _, story = semantic_story("multiline.rpy")
    narrative = beat_of_kind(story, "narrative")

    assert len(narrative) == 1
    beat = narrative[0]
    assert_source(beat["source"], "semantic/multiline.rpy", 2, 5)
    assert [(item["kind"], item["speaker"], item["text"]) for item in beat["content"]] == [
        ("narration", None, "First narration line.\nSecond narration line."),
        ("dialogue", "eileen", "First dialogue line.\nSecond dialogue line."),
    ]
    assert_source(beat["content"][0]["source"], "semantic/multiline.rpy", 2, 3)
    assert_source(beat["content"][1]["source"], "semantic/multiline.rpy", 4, 5)


def test_unsupported_graph_schema_version_is_rejected() -> None:
    graph, _ = semantic_story("grouping.rpy")
    graph["schema_version"] = 2

    with pytest.raises(ValueError, match="schema_version"):
        semantic.build_semantic_story(graph)


def test_unknown_graph_edge_kind_is_rejected() -> None:
    graph, _ = semantic_story("grouping.rpy")
    edges = records(graph, "edges")
    future_edge = copy.deepcopy(edges[0])
    future_edge["kind"] = "future_transfer"
    edges.append(future_edge)

    with pytest.raises(ValueError, match="future_transfer"):
        semantic.build_semantic_story(graph)
