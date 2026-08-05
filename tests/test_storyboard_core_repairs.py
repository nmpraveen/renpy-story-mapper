from __future__ import annotations

import ast
import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

from renpy_story_mapper.ingestion.contracts import IngestionSource, SourceProvenance, SourceTier
from renpy_story_mapper.storyboard.evidence import (
    build_evidence_index_from_source,
    build_evidence_index_from_text,
)
from renpy_story_mapper.storyboard.model import redact_public_value
from renpy_story_mapper.storyboard.pipeline import evidence_index_to_mapping
from renpy_story_mapper.storyboard.validation import validate_phase01

BRANCH_SOURCE = """label start:
    \"Intro\"
    menu:
        \"Left\":
            \"Left line\"
        \"Right\" if gate:
            \"Right line\"
    return
"""


def _evidence(source: str = BRANCH_SOURCE, *, label: str | None = "start") -> dict[str, object]:
    return evidence_index_to_mapping(build_evidence_index_from_text(source, label=label))


def _records(evidence: dict[str, object]) -> list[dict[str, object]]:
    return [item for item in evidence["records"] if isinstance(item, dict)]


def _canonical_profile(evidence: dict[str, object]) -> dict[str, object]:
    ids = [str(item["id"]) for item in _records(evidence)]
    return {
        "schema": "storyboard-game-profile-v1",
        "source": {"evidence_index_hash": "evidence", "scope_evidence_ids": ids},
        "entry_points": [],
        "characters": [],
        "variables": [],
        "custom_constructs": [],
        "conventions": [],
        "ending_patterns": [],
        "unresolved": [],
        "status": "resolved",
        "uncertainty": None,
    }


def _branch_analysis(evidence: dict[str, object]) -> dict[str, object]:
    records = _records(evidence)
    lines = {
        int(item["facts"]["line_number"]): str(item["id"])
        for item in records
        if item["kind"] == "source_line" and isinstance(item.get("facts"), dict)
    }

    arms = sorted(
        (item for item in records if item["kind"] == "choice_arm"),
        key=lambda item: int(item["facts"]["ordinal"]),
    )
    menu = next(item for item in evidence["menus"] if isinstance(item, dict))
    label = next(item for item in records if item["kind"] == "label")

    def arm(
        story_id: str, caption: str, arm_record: dict[str, object], leaf_lines: list[int]
    ) -> dict[str, object]:
        return {
            "id": story_id,
            "caption": caption,
            "condition": arm_record["facts"].get("condition"),
            "line_evidence_ids": [lines[number] for number in leaf_lines],
            "consequence": {
                "text": f"The {caption.lower()} route continues.",
                "evidence_ids": [str(arm_record["id"])],
                "confidence": "high",
                "status": "resolved",
                "uncertainty": None,
            },
            "destination_scene_id": None,
            "rejoin_scene_id": None,
            "evidence_ids": [str(arm_record["id"])],
            "confidence": "high",
            "status": "resolved",
            "uncertainty": None,
        }

    return {
        "schema": "storyboard-story-analysis-v1",
        "source": {
            "evidence_index_hash": "evidence",
            "profile_hash": "profile",
            "canary_evidence_ids": [str(item["id"]) for item in records],
        },
        "scenes": [
            {
                "id": "scene-start",
                "title": "Start",
                "summary": "The shared opening divides into two routes.",
                "order": 0,
                "line_evidence_ids": [lines[number] for number in (1, 2, 3, 8)],
                "choice_ids": ["choice-main"],
                "evidence_ids": [str(label["id"]), str(menu["id"])],
                "confidence": "high",
                "status": "resolved",
                "uncertainty": None,
            }
        ],
        "choices": [
            {
                "id": "choice-main",
                "scene_id": "scene-start",
                "caption": "Choose a route",
                "condition": None,
                "menu_evidence_id": str(menu["id"]),
                "arms": [
                    arm("arm-left", "Left", arms[0], [4, 5]),
                    arm("arm-right", "Right", arms[1], [6, 7]),
                ],
                "evidence_ids": [str(menu["id"])],
                "confidence": "high",
                "status": "resolved",
                "uncertainty": None,
            }
        ],
        "transitions": [],
        "claims": [],
        "excluded_evidence_ids": [],
        "unresolved": [],
        "disagreements": [],
        "status": "resolved",
        "uncertainty": None,
    }


def _empty_analysis(evidence: dict[str, object]) -> dict[str, object]:
    records = _records(evidence)
    lines = [str(item["id"]) for item in records if item["kind"] == "source_line"]
    return {
        "schema": "storyboard-story-analysis-v1",
        "source": {
            "evidence_index_hash": "evidence",
            "profile_hash": "profile",
            "canary_evidence_ids": [str(item["id"]) for item in records],
        },
        "scenes": [
            {
                "id": "scene-selected",
                "title": "Selected source",
                "summary": "The bounded source selection remains unresolved.",
                "order": 0,
                "line_evidence_ids": lines,
                "evidence_ids": [str(records[0]["id"])],
                "confidence": "low",
                "status": "unresolved",
                "uncertainty": "The requested label was not found.",
            }
        ],
        "choices": [],
        "transitions": [],
        "claims": [],
        "excluded_evidence_ids": [],
        "unresolved": [],
        "disagreements": [],
        "status": "unresolved",
        "uncertainty": "The requested label was not found.",
    }


def _nested_branch_analysis(evidence: dict[str, object]) -> dict[str, object]:
    records = _records(evidence)
    lines = {
        int(item["facts"]["line_number"]): str(item["id"])
        for item in records
        if item["kind"] == "source_line" and isinstance(item.get("facts"), dict)
    }
    menu = next(item for item in records if item["kind"] == "menu")
    menu_arms = sorted(
        (item for item in records if item["kind"] == "choice_arm"),
        key=lambda item: int(item["facts"]["ordinal"]),
    )
    conditions = {
        str(item["facts"]["condition_type"]): item
        for item in records
        if item["kind"] == "condition"
        and isinstance(item.get("facts"), dict)
        and item["facts"].get("condition_type") in {"if_branch", "else_branch"}
    }
    label = next(item for item in records if item["kind"] == "label")

    def arm(
        story_id: str,
        caption: str,
        evidence_id: str,
        line_numbers: tuple[int, ...],
        *,
        condition: str | None = None,
        condition_id: str | None = None,
    ) -> dict[str, object]:
        return {
            "id": story_id,
            "caption": caption,
            "condition": condition,
            "condition_evidence_ids": [] if condition_id is None else [condition_id],
            "line_evidence_ids": [lines[number] for number in line_numbers],
            "evidence_ids": [evidence_id],
            "consequence": {
                "text": f"The {caption.lower()} branch continues.",
                "evidence_ids": [evidence_id],
                "confidence": "high",
                "status": "resolved",
                "uncertainty": None,
            },
            "terminal": "none",
            "confidence": "high",
            "status": "resolved",
            "uncertainty": None,
        }

    outer_choice = {
        "id": "choice-menu",
        "scene_id": "scene-start",
        "caption": "Choose a route",
        "condition": None,
        "menu_evidence_id": str(menu["id"]),
        "arms": [
            arm("arm-nested-route", "Nested route", str(menu_arms[0]["id"]), (3,)),
            arm("arm-other-route", "Other route", str(menu_arms[1]["id"]), (8, 9)),
        ],
        "evidence_ids": [str(menu["id"])],
        "confidence": "high",
        "status": "resolved",
        "uncertainty": None,
    }
    inner_if = conditions["if_branch"]
    inner_else = conditions["else_branch"]
    conditional_choice = {
        "id": "choice-inner-condition",
        "scene_id": "scene-start",
        "caption": "Inner gate",
        "condition": None,
        "arms": [
            arm(
                "arm-inner-if",
                "Inner if",
                str(inner_if["id"]),
                (4, 5),
                condition="inner_gate",
                condition_id=str(inner_if["id"]),
            ),
            arm(
                "arm-inner-else",
                "Inner else",
                str(inner_else["id"]),
                (6, 7),
                condition_id=str(inner_else["id"]),
            ),
        ],
        "evidence_ids": [str(inner_if["id"]), str(inner_else["id"])],
        "confidence": "high",
        "status": "resolved",
        "uncertainty": None,
    }
    return {
        "schema": "storyboard-story-analysis-v1",
        "source": {
            "evidence_index_hash": "evidence",
            "profile_hash": "profile",
            "canary_evidence_ids": [str(item["id"]) for item in records],
        },
        "scenes": [
            {
                "id": "scene-start",
                "title": "Start",
                "summary": "A menu arm contains a nested conditional.",
                "order": 0,
                "line_evidence_ids": [lines[number] for number in (1, 2, 10)],
                "choice_ids": ["choice-menu", "choice-inner-condition"],
                "evidence_ids": [str(label["id"]), str(menu["id"])],
                "confidence": "high",
                "status": "resolved",
                "uncertainty": None,
            }
        ],
        "choices": [outer_choice, conditional_choice],
        "transitions": [],
        "claims": [],
        "excluded_evidence_ids": [],
        "unresolved": [],
        "disagreements": [],
        "status": "resolved",
        "uncertainty": None,
    }


def _two_scene_transition_inputs(
    *, empty_destination: bool = False, unrelated_target: bool = False
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    source = (
        Path(__file__).parent / "fixtures" / "storyboard_two_scene_targets.rpy"
    ).read_text(encoding="utf-8")
    evidence = evidence_index_to_mapping(
        build_evidence_index_from_text(source, path="game/storyboard_two_scene_targets.rpy")
    )
    records = _records(evidence)
    lines = {
        int(item["facts"]["line_number"]): str(item["id"])
        for item in records
        if item["kind"] == "source_line" and isinstance(item.get("facts"), dict)
    }
    labels = {
        str(item["facts"]["name"]): str(item["id"])
        for item in records
        if item["kind"] == "label" and isinstance(item.get("facts"), dict)
    }
    jump = next(item for item in records if item["kind"] == "jump")
    destination_line = next(
        item
        for item in records
        if item["kind"] == "narration"
        and isinstance(item.get("facts"), dict)
        and item["facts"].get("dialogue_text") == "Destination line"
    )
    profile = _canonical_profile(evidence)
    start_lines = [lines[number] for number in (1, 2, 3, 4)]
    destination_lines = [] if empty_destination else [lines[number] for number in (5, 6, 7)]
    if empty_destination:
        start_lines = list(lines.values())
    target_id = lines[4] if unrelated_target else str(destination_line["id"])
    analysis = {
        "schema": "storyboard-story-analysis-v1",
        "source": {
            "evidence_index_hash": "evidence",
            "profile_hash": "profile",
            "canary_evidence_ids": [str(item["id"]) for item in records],
        },
        "scenes": [
            {
                "id": "scene-start",
                "title": "Start",
                "summary": "The opening jumps to a destination.",
                "order": 0,
                "line_evidence_ids": start_lines,
                "evidence_ids": [labels["start"]],
                "confidence": "high",
                "status": "resolved",
                "uncertainty": None,
            },
            {
                "id": "scene-destination",
                "title": "Destination",
                "summary": "The destination scene contains its own line.",
                "order": 1,
                "line_evidence_ids": destination_lines,
                "evidence_ids": [labels["destination"]],
                "confidence": "high",
                "status": "resolved",
                "uncertainty": None,
            },
        ],
        "choices": [],
        "transitions": [
            {
                "id": "transition-destination",
                "from_id": "scene-start",
                "to_id": "scene-destination",
                "kind": "jump",
                "evidence_ids": [str(jump["id"])],
                "source_evidence_ids": [str(jump["id"])],
                "target_evidence_ids": [target_id],
                "confidence": "high",
                "status": "resolved",
                "uncertainty": None,
            }
        ],
        "claims": [],
        "excluded_evidence_ids": [],
        "unresolved": [],
        "disagreements": [],
        "status": "resolved",
        "uncertainty": None,
    }
    return evidence, profile, analysis


def _menu_arm_destination_inputs() -> tuple[dict[str, object], dict[str, object]]:
    source = (
        Path(__file__).parent / "fixtures" / "storyboard_menu_arm_target.rpy"
    ).read_text(encoding="utf-8")
    evidence = evidence_index_to_mapping(
        build_evidence_index_from_text(source, path="game/storyboard_menu_arm_target.rpy")
    )
    records = _records(evidence)
    lines = {
        int(item["facts"]["line_number"]): str(item["id"])
        for item in records
        if item["kind"] == "source_line" and isinstance(item.get("facts"), dict)
    }
    menu = next(item for item in records if item["kind"] == "menu")
    menu_arms = sorted(
        (item for item in records if item["kind"] == "choice_arm"),
        key=lambda item: int(item["facts"]["ordinal"]),
    )
    jump = next(item for item in records if item["kind"] == "jump")
    destination_line = next(
        item
        for item in records
        if item["kind"] == "narration"
        and isinstance(item.get("facts"), dict)
        and item["facts"].get("dialogue_text") == "Destination line"
    )
    labels = {
        str(item["facts"]["name"]): str(item["id"])
        for item in records
        if item["kind"] == "label" and isinstance(item.get("facts"), dict)
    }
    def make_arm(
        story_id: str,
        caption: str,
        evidence_id: str,
        line_numbers: tuple[int, ...],
    ) -> dict[str, object]:
        value: dict[str, object] = {
            "id": story_id,
            "caption": caption,
            "line_evidence_ids": [lines[number] for number in line_numbers],
            "evidence_ids": [evidence_id],
            "consequence": {
                "text": f"The {caption.lower()} route continues.",
                "evidence_ids": [evidence_id],
                "confidence": "high",
                "status": "resolved",
                "uncertainty": None,
            },
            "terminal": "none",
            "confidence": "high",
            "status": "resolved",
            "uncertainty": None,
        }
        return value

    go = make_arm("arm-go", "Go to destination", str(menu_arms[0]["id"]), (3, 4))
    go["destination_scene_id"] = "scene-destination"
    go["source_evidence_ids"] = [str(jump["id"])]
    go["target_evidence_ids"] = [str(destination_line["id"])]
    stay = make_arm("arm-stay", "Stay here", str(menu_arms[1]["id"]), (5, 6))
    analysis = {
        "schema": "storyboard-story-analysis-v1",
        "source": {
            "evidence_index_hash": "evidence",
            "profile_hash": "profile",
            "canary_evidence_ids": [str(item["id"]) for item in records],
        },
        "scenes": [
            {
                "id": "scene-start",
                "title": "Start",
                "summary": "The menu offers a destination or a local line.",
                "order": 0,
                "line_evidence_ids": [lines[number] for number in (1, 2)],
                "choice_ids": ["choice-main"],
                "evidence_ids": [labels["start"], str(menu["id"])],
                "confidence": "high",
                "status": "resolved",
                "uncertainty": None,
            },
            {
                "id": "scene-destination",
                "title": "Destination",
                "summary": "The destination line is shown.",
                "order": 1,
                "line_evidence_ids": [lines[number] for number in (8, 9, 10)],
                "evidence_ids": [labels["destination"]],
                "confidence": "high",
                "status": "resolved",
                "uncertainty": None,
            },
        ],
        "choices": [
            {
                "id": "choice-main",
                "scene_id": "scene-start",
                "caption": "Choose a route",
                "condition": None,
                "menu_evidence_id": str(menu["id"]),
                "arms": [go, stay],
                "evidence_ids": [str(menu["id"])],
                "confidence": "high",
                "status": "resolved",
                "uncertainty": None,
            }
        ],
        "transitions": [],
        "claims": [],
        "excluded_evidence_ids": [],
        "unresolved": [],
        "disagreements": [],
        "status": "resolved",
        "uncertainty": None,
    }
    return evidence, analysis


def test_wrong_arm_swap_and_zero_arm_giant_scene_fail_parser_derived_ownership() -> None:
    evidence = _evidence()
    profile = _canonical_profile(evidence)
    analysis = _branch_analysis(evidence)
    choices = analysis["choices"]
    assert isinstance(choices, list)
    choice = choices[0]
    assert isinstance(choice, dict)
    arms = choice["arms"]
    assert isinstance(arms, list)
    left = arms[0]
    right = arms[1]
    assert isinstance(left, dict) and isinstance(right, dict)
    left_lines = left["line_evidence_ids"]
    right_lines = right["line_evidence_ids"]
    assert isinstance(left_lines, list) and isinstance(right_lines, list)
    left["line_evidence_ids"], right["line_evidence_ids"] = right_lines, left_lines

    swapped = validate_phase01(evidence, profile, analysis)
    assert not swapped.publishable
    assert {issue.code for issue in swapped.errors} >= {
        "cross_arm_ownership",
        "incomplete_arm_coverage",
    }
    per_arm = swapped.coverage["per_arm"]
    assert isinstance(per_arm, list)
    assert all(item["complete"] is False for item in per_arm if isinstance(item, dict))

    giant = _branch_analysis(evidence)
    giant_choice = giant["choices"]
    assert isinstance(giant_choice, list)
    giant_choice.clear()
    giant_scene = giant["scenes"]
    assert isinstance(giant_scene, list)
    scene = giant_scene[0]
    assert isinstance(scene, dict)
    records = _records(evidence)
    scene["line_evidence_ids"] = [
        str(item["id"]) for item in records if item["kind"] == "source_line"
    ]
    scene["choice_ids"] = []
    giant_result = validate_phase01(evidence, profile, giant)
    assert not giant_result.publishable
    assert {issue.code for issue in giant_result.errors} >= {
        "scene_contains_branch_leaves",
        "missing_menu_arm",
    }


def test_real_python_leaf_classification_requires_unresolved_status() -> None:
    source = """label start:
    python:
        route = compute_route()
    \"Visible line\"
"""
    evidence = _evidence(source)
    records = _records(evidence)
    python_lines = [
        str(item["id"])
        for item in records
        if item["kind"] == "source_line"
        and isinstance(item.get("facts"), dict)
        and "python" in item["facts"].get("semantic_kinds", [])
    ]
    assert python_lines
    profile = _canonical_profile(evidence)
    profile["variables"] = [
        {
            "id": "route",
            "names": ["route"],
            "meaning": "The route selected by the embedded block.",
            "roles": ["state"],
            "evidence_ids": [python_lines[0]],
            "confidence": "medium",
            "status": "resolved",
            "uncertainty": None,
        }
    ]
    analysis = {
        "scenes": [
            {
                "id": "scene-start",
                "title": "Start",
                "summary": "A block precedes visible text.",
                "order": 0,
                "line_evidence_ids": [
                    str(item["id"]) for item in records if item["kind"] == "source_line"
                ],
                "evidence_ids": [str(records[0]["id"])],
                "confidence": "medium",
                "status": "unresolved",
                "uncertainty": "The embedded Python behavior is not statically closed.",
            }
        ],
        "choices": [],
        "transitions": [],
        "claims": [],
        "excluded_evidence_ids": [],
        "unresolved": [],
        "disagreements": [],
        "status": "unresolved",
        "uncertainty": "The embedded Python behavior is not statically closed.",
    }
    resolved = validate_phase01(evidence, profile, analysis)
    assert not resolved.publishable
    assert any(issue.code == "dynamic_behavior_as_fact" for issue in resolved.errors)
    variable = profile["variables"][0]
    assert isinstance(variable, dict)
    variable["status"] = "unresolved"
    variable["uncertainty"] = "The embedded Python behavior is not statically closed."
    unresolved = validate_phase01(evidence, profile, analysis)
    assert unresolved.publishable


def test_real_custom_and_unknown_leaf_classifications_require_rationale() -> None:
    source = """label start:
    renpy.notify("custom")
    custom_statement whatever
"""
    evidence = _evidence(source)
    records = _records(evidence)
    custom_line = next(
        item
        for item in records
        if item["kind"] == "source_line"
        and isinstance(item.get("facts"), dict)
        and item["facts"].get("semantic_kinds") == ["custom"]
    )
    unknown_line = next(
        item
        for item in records
        if item["kind"] == "source_line"
        and isinstance(item.get("facts"), dict)
        and item["facts"].get("semantic_kinds") == ["unknown"]
    )
    profile = _canonical_profile(evidence)
    profile["custom_constructs"] = [
        {
            "id": "custom-meaning",
            "syntax": "renpy.notify/custom_statement",
            "meaning": "The statements affect route state.",
            "behavior": "They are interpreted as route-affecting operations.",
            "evidence_ids": [str(custom_line["id"]), str(unknown_line["id"])],
            "confidence": "medium",
            "status": "resolved",
            "uncertainty": None,
        }
    ]
    analysis = _empty_analysis(evidence)
    scene = analysis["scenes"][0]
    assert isinstance(scene, dict)
    scene["line_evidence_ids"] = [
        str(item["id"]) for item in records if item["kind"] == "source_line"
    ]
    scene["evidence_ids"] = [str(records[0]["id"])]
    scene["status"] = "resolved"
    scene["uncertainty"] = None
    scene["rationale"] = "The source lines are parser-marked custom syntax."
    analysis["status"] = "resolved"
    analysis["uncertainty"] = None
    rejected = validate_phase01(evidence, profile, analysis)
    assert any(issue.code == "custom_interpretation_without_rationale" for issue in rejected.errors)

    profile["custom_constructs"][0]["rationale"] = (
        "Both cited lines are parser-marked custom syntax."
    )
    accepted = validate_phase01(evidence, profile, analysis)
    assert accepted.publishable


def test_missing_status_and_unmatched_label_preserve_evidence_but_block_publication() -> None:
    evidence = _evidence()
    profile = _canonical_profile(evidence)
    variables = profile["variables"]
    assert isinstance(variables, list)
    variables.append(
        {
            "id": "gate",
            "names": ["gate"],
            "meaning": "A gate.",
            "roles": ["condition"],
            "evidence_ids": [str(_records(evidence)[0]["id"])],
            "confidence": "low",
            "uncertainty": None,
        }
    )
    missing_status = validate_phase01(evidence, profile, _branch_analysis(evidence))
    assert any(issue.code == "missing_status" for issue in missing_status.errors)

    unmatched_index = build_evidence_index_from_text(BRANCH_SOURCE, label="missing")
    unmatched = evidence_index_to_mapping(unmatched_index)
    assert unmatched["records"]
    selection = unmatched["selection"]
    assert isinstance(selection, dict)
    assert selection["status"] == "unresolved"
    assert any(
        isinstance(item, dict) and item.get("code") == "label_not_found"
        for item in unmatched["diagnostics"]
    )
    blocked = validate_phase01(unmatched, _canonical_profile(unmatched), _empty_analysis(unmatched))
    assert not blocked.publishable
    assert any(issue.code == "unresolved_selection" for issue in blocked.errors)


def test_parser_failure_preserves_tabbed_two_arm_ledger_but_blocks_flattened_publication() -> None:
    source = (
        Path(__file__).parent / "fixtures" / "storyboard_tab_menu.rpy"
    ).read_text(encoding="utf-8")
    evidence = evidence_index_to_mapping(
        build_evidence_index_from_text(source, path="game/storyboard_tab_menu.rpy", label="start")
    )
    diagnostics = evidence["diagnostics"]
    assert any(
        isinstance(item, dict) and item.get("code") == "parse_failed" for item in diagnostics
    )
    assert any(
        isinstance(item, dict)
        and item.get("code") == "parser_annotations_unavailable"
        for item in diagnostics
    )
    ledger = evidence["ledger"]
    assert any(
        isinstance(item, dict) and "First tab arm" in str(item.get("text")) for item in ledger
    )
    assert any(
        isinstance(item, dict) and "Second tab arm" in str(item.get("text")) for item in ledger
    )
    report = validate_phase01(evidence, _canonical_profile(evidence), _empty_analysis(evidence))
    assert not report.publishable
    assert {issue.code for issue in report.errors} >= {
        "parse_failed",
        "parser_annotations_unavailable",
    }


def test_nested_menu_condition_ownership_uses_deepest_evaluated_branch() -> None:
    source = (
        Path(__file__).parent / "fixtures" / "storyboard_nested_menu_if.rpy"
    ).read_text(encoding="utf-8")
    evidence = evidence_index_to_mapping(
        build_evidence_index_from_text(
            source, path="game/storyboard_nested_menu_if.rpy", label="start"
        )
    )
    profile = _canonical_profile(evidence)
    analysis = _nested_branch_analysis(evidence)

    accepted = validate_phase01(evidence, profile, analysis)
    assert accepted.publishable
    per_arm = accepted.coverage["per_arm"]
    assert isinstance(per_arm, list)
    by_id = {item["arm_id"]: item for item in per_arm if isinstance(item, dict)}
    assert by_id["arm-inner-if"]["covered"] == 2
    assert by_id["arm-inner-else"]["covered"] == 2

    wrong = deepcopy(analysis)
    choices = wrong["choices"]
    assert isinstance(choices, list)
    conditional = choices[1]
    assert isinstance(conditional, dict)
    nested_arms = conditional["arms"]
    assert isinstance(nested_arms, list)
    first_lines = nested_arms[0]["line_evidence_ids"]
    second_lines = nested_arms[1]["line_evidence_ids"]
    nested_arms[0]["line_evidence_ids"] = second_lines
    nested_arms[1]["line_evidence_ids"] = first_lines
    rejected = validate_phase01(evidence, profile, wrong)
    assert not rejected.publishable
    assert {issue.code for issue in rejected.errors} >= {
        "cross_arm_ownership",
        "incomplete_arm_coverage",
    }

    shared = deepcopy(analysis)
    shared_scene = shared["scenes"][0]
    assert isinstance(shared_scene, dict)
    shared_scene["line_evidence_ids"].append(
        analysis["choices"][1]["arms"][0]["line_evidence_ids"][0]
    )
    shared_report = validate_phase01(evidence, profile, shared)
    assert not shared_report.publishable
    assert any(issue.code == "arm_leaf_in_shared_scene" for issue in shared_report.errors)


def test_scene_and_edge_completeness_bind_origin_and_destination_evidence() -> None:
    evidence, profile, valid = _two_scene_transition_inputs()
    assert validate_phase01(evidence, profile, valid).publishable

    records = _records(evidence)
    line_ids = {
        int(item["facts"]["line_number"]): str(item["id"])
        for item in records
        if item["kind"] == "source_line" and isinstance(item.get("facts"), dict)
    }
    wrong_target = deepcopy(valid)
    transition = wrong_target["transitions"][0]
    assert isinstance(transition, dict)
    transition["target_evidence_ids"] = [line_ids[4]]
    target_report = validate_phase01(evidence, profile, wrong_target)
    assert not target_report.publishable
    assert any(
        issue.code == "target_evidence_not_in_destination_scene"
        for issue in target_report.errors
    )

    wrong_source = deepcopy(valid)
    transition = wrong_source["transitions"][0]
    assert isinstance(transition, dict)
    transition["source_evidence_ids"] = [line_ids[6]]
    source_report = validate_phase01(evidence, profile, wrong_source)
    assert not source_report.publishable
    assert any(
        issue.code == "source_evidence_not_in_origin_scene" for issue in source_report.errors
    )

    semantic_target = deepcopy(valid)
    destination_scene = semantic_target["scenes"][1]
    assert isinstance(destination_scene, dict)
    destination_citations = destination_scene["evidence_ids"]
    assert isinstance(destination_citations, list)
    destination_citations.append(line_ids[4])
    assert validate_phase01(evidence, profile, semantic_target).publishable
    semantic_target_transition = semantic_target["transitions"][0]
    assert isinstance(semantic_target_transition, dict)
    semantic_target_transition["target_evidence_ids"] = [line_ids[4]]
    semantic_target_report = validate_phase01(evidence, profile, semantic_target)
    assert not semantic_target_report.publishable
    assert any(
        issue.code == "target_evidence_not_in_destination_scene"
        for issue in semantic_target_report.errors
    )

    semantic_source = deepcopy(valid)
    origin_scene = semantic_source["scenes"][0]
    assert isinstance(origin_scene, dict)
    origin_citations = origin_scene["evidence_ids"]
    assert isinstance(origin_citations, list)
    origin_citations.append(line_ids[6])
    assert validate_phase01(evidence, profile, semantic_source).publishable
    semantic_source_transition = semantic_source["transitions"][0]
    assert isinstance(semantic_source_transition, dict)
    semantic_source_transition["source_evidence_ids"] = [line_ids[6]]
    semantic_source_report = validate_phase01(evidence, profile, semantic_source)
    assert not semantic_source_report.publishable
    assert any(
        issue.code == "source_evidence_not_in_origin_scene"
        for issue in semantic_source_report.errors
    )

    empty, empty_profile, empty_destination = _two_scene_transition_inputs(
        empty_destination=True, unrelated_target=True
    )
    empty_report = validate_phase01(empty, empty_profile, empty_destination)
    assert not empty_report.publishable
    assert {issue.code for issue in empty_report.errors} >= {
        "incomplete_scene_coverage",
        "target_evidence_not_in_destination_scene",
    }
    per_scene = empty_report.coverage["per_scene"]
    assert isinstance(per_scene, list)
    destination = next(item for item in per_scene if item["scene_id"] == "scene-destination")
    assert destination["complete"] is False


def test_choice_arm_origin_and_destination_evidence_are_bound_to_the_arm_and_scene() -> None:
    evidence, analysis = _menu_arm_destination_inputs()
    profile = _canonical_profile(evidence)
    assert validate_phase01(evidence, profile, analysis).publishable
    records = _records(evidence)
    line_ids = {
        int(item["facts"]["line_number"]): str(item["id"])
        for item in records
        if item["kind"] == "source_line" and isinstance(item.get("facts"), dict)
    }
    choice = analysis["choices"][0]
    assert isinstance(choice, dict)
    go = choice["arms"][0]
    assert isinstance(go, dict)

    wrong_source = deepcopy(analysis)
    wrong_go = wrong_source["choices"][0]["arms"][0]
    assert isinstance(wrong_go, dict)
    wrong_go["source_evidence_ids"] = [line_ids[9]]
    source_report = validate_phase01(evidence, profile, wrong_source)
    assert not source_report.publishable
    assert any(issue.code == "source_evidence_not_in_origin_arm" for issue in source_report.errors)

    wrong_target = deepcopy(analysis)
    wrong_go = wrong_target["choices"][0]["arms"][0]
    assert isinstance(wrong_go, dict)
    wrong_go["target_evidence_ids"] = [line_ids[6]]
    target_report = validate_phase01(evidence, profile, wrong_target)
    assert not target_report.publishable
    assert any(
        issue.code == "target_evidence_not_in_destination_scene" for issue in target_report.errors
    )

    semantic_source = deepcopy(analysis)
    semantic_go = semantic_source["choices"][0]["arms"][0]
    assert isinstance(semantic_go, dict)
    arm_citations = semantic_go["evidence_ids"]
    assert isinstance(arm_citations, list)
    arm_citations.append(line_ids[6])
    assert validate_phase01(evidence, profile, semantic_source).publishable
    semantic_go["source_evidence_ids"] = [line_ids[6]]
    semantic_source_report = validate_phase01(evidence, profile, semantic_source)
    assert not semantic_source_report.publishable
    assert any(
        issue.code == "source_evidence_not_in_origin_arm"
        for issue in semantic_source_report.errors
    )

    semantic_target = deepcopy(analysis)
    semantic_destination = semantic_target["scenes"][1]
    assert isinstance(semantic_destination, dict)
    destination_citations = semantic_destination["evidence_ids"]
    assert isinstance(destination_citations, list)
    destination_citations.append(line_ids[6])
    assert validate_phase01(evidence, profile, semantic_target).publishable
    semantic_target_go = semantic_target["choices"][0]["arms"][0]
    assert isinstance(semantic_target_go, dict)
    semantic_target_go["target_evidence_ids"] = [line_ids[6]]
    semantic_target_report = validate_phase01(evidence, profile, semantic_target)
    assert not semantic_target_report.publishable
    assert any(
        issue.code == "target_evidence_not_in_destination_scene"
        for issue in semantic_target_report.errors
    )

    rejoin = deepcopy(analysis)
    rejoin_go = rejoin["choices"][0]["arms"][0]
    assert isinstance(rejoin_go, dict)
    rejoin_go.pop("destination_scene_id")
    rejoin_go["rejoin_scene_id"] = "scene-destination"
    assert validate_phase01(evidence, profile, rejoin).publishable

    semantic_rejoin = deepcopy(rejoin)
    semantic_rejoin_destination = semantic_rejoin["scenes"][1]
    assert isinstance(semantic_rejoin_destination, dict)
    rejoin_citations = semantic_rejoin_destination["evidence_ids"]
    assert isinstance(rejoin_citations, list)
    rejoin_citations.append(line_ids[6])
    assert validate_phase01(evidence, profile, semantic_rejoin).publishable
    semantic_rejoin_go = semantic_rejoin["choices"][0]["arms"][0]
    assert isinstance(semantic_rejoin_go, dict)
    semantic_rejoin_go["target_evidence_ids"] = [line_ids[6]]
    semantic_rejoin_report = validate_phase01(evidence, profile, semantic_rejoin)
    assert not semantic_rejoin_report.publishable
    assert any(
        issue.code == "target_evidence_not_in_destination_scene"
        for issue in semantic_rejoin_report.errors
    )


def test_canonical_line_membership_is_sole_scene_and_arm_membership_field() -> None:
    evidence = _evidence()
    profile = _canonical_profile(evidence)
    analysis = _branch_analysis(evidence)
    scene = analysis["scenes"][0]
    assert isinstance(scene, dict)
    scene["leaf_evidence_ids"] = list(scene["line_evidence_ids"])
    rejected = validate_phase01(evidence, profile, analysis)
    assert any(issue.code == "legacy_membership_field" for issue in rejected.errors)

    missing = deepcopy(_branch_analysis(evidence))
    missing_scene = missing["scenes"][0]
    assert isinstance(missing_scene, dict)
    missing_scene.pop("line_evidence_ids")
    missing_report = validate_phase01(evidence, profile, missing)
    assert any(issue.code == "missing_membership_field" for issue in missing_report.errors)

    schema_path = (
        Path(__file__).parents[1]
        / "src"
        / "renpy_story_mapper"
        / "storyboard"
        / "schemas"
        / "story-analysis.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(analysis))


def test_continuation_line_membership_is_required_but_explicit_empty_is_valid() -> None:
    evidence = _evidence()
    profile = _canonical_profile(evidence)
    valid = _branch_analysis(evidence)
    records = _records(evidence)
    label = next(item for item in records if item["kind"] == "label")
    continuation = {
        "id": "continuation-empty",
        "title": "Shared continuation",
        "evidence_ids": [str(label["id"])],
        "confidence": "high",
        "status": "resolved",
        "uncertainty": None,
        "line_evidence_ids": [],
    }
    with_empty_membership = deepcopy(valid)
    with_empty_membership["continuations"] = [continuation]
    schema_path = (
        Path(__file__).parents[1]
        / "src"
        / "renpy_story_mapper"
        / "storyboard"
        / "schemas"
        / "story-analysis.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(with_empty_membership)) == []
    assert validate_phase01(evidence, profile, with_empty_membership).publishable

    without_membership = deepcopy(with_empty_membership)
    missing_continuation = without_membership["continuations"][0]
    assert isinstance(missing_continuation, dict)
    missing_continuation.pop("line_evidence_ids")
    assert list(Draft202012Validator(schema).iter_errors(without_membership))
    report = validate_phase01(evidence, profile, without_membership)
    assert not report.publishable
    assert any(issue.code == "missing_membership_field" for issue in report.errors)


def test_recursive_path_redaction_preserves_relative_identity_and_exact_source_text() -> None:
    source_path = r"C:\Users\prave\private\scene.rpy"
    source = 'label start:\n    "C:\\Users\\prave\\private\\exact.rpy"\n'
    digest = "a" * 64
    provenance = SourceProvenance(
        source_kind="original",
        locator=source_path,
        tier=SourceTier.LOOSE_ORIGINAL,
        input_sha256=digest,
        output_sha256=digest,
        line_basis="physical_original_source",
        options={
            "nested": {
                "paths": [r"C:\Users\prave\secret\one.rpy", "../relative/identity.rpy"],
                "diagnostics": [{"message": r"failed at C:\Users\prave\secret\two.rpy"}],
            }
        },
        warnings=(r"warning at C:\Users\prave\secret\three.rpy",),
    )
    custom = IngestionSource(source_path, source.encode("utf-8"), provenance)
    custom_index = evidence_index_to_mapping(
        build_evidence_index_from_source(custom, label="start")
    )
    # Exercise the public recursive helper directly for nested AI/public payloads.
    redacted = redact_public_value(
        {
            "options": provenance.options,
            "warnings": list(provenance.warnings),
            "diagnostics": [{"message": r"C:\Users\prave\secret\four.rpy"}],
            "relative_path": "../relative/identity.rpy",
            "url": "https://example.test/story",
            "text": source,
        },
        preserve_exact_text=False,
    )
    serialized = json.dumps(redacted)
    assert "C:/Users/prave" not in serialized
    assert "source/one.rpy" in serialized
    assert "source/four.rpy" in serialized
    assert "../relative/identity.rpy" in serialized
    assert "https://example.test/story" in serialized
    source_artifact = custom_index["source"]
    assert isinstance(source_artifact, dict)
    assert "C:/Users/prave" not in json.dumps(source_artifact)
    assert source_artifact["path"] == "source/scene.rpy"
    records = _records(custom_index)
    assert any("C:\\Users\\prave\\private\\exact.rpy" in str(item["text"]) for item in records)


def test_destination_alias_is_rejected_and_canonical_transition_is_schema_valid() -> None:
    evidence = _evidence()
    profile = _canonical_profile(evidence)
    analysis = _branch_analysis(evidence)
    choices = analysis["choices"]
    assert isinstance(choices, list)
    arms = choices[0]["arms"]
    assert isinstance(arms, list)
    first_arm = arms[0]
    assert isinstance(first_arm, dict)
    first_arm["destination_id"] = "scene-next"
    alias_report = validate_phase01(evidence, profile, analysis)
    assert any(issue.code == "legacy_destination_shape" for issue in alias_report.errors)

    _valid_evidence, _valid_profile, valid_analysis = _two_scene_transition_inputs()
    report = validate_phase01(_valid_evidence, _valid_profile, valid_analysis)
    assert report.publishable
    schema_path = (
        Path(__file__).parents[1]
        / "src/renpy_story_mapper/storyboard/schemas/story-analysis.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(valid_analysis)) == []


def test_dangling_parent_is_rejected_after_real_evidence_is_modified() -> None:
    evidence = _evidence()
    records = _records(evidence)
    child = next(item for item in records if item["kind"] == "narration")
    facts = child["facts"]
    assert isinstance(facts, dict)
    facts["parent_id"] = "missing-parent"
    report = validate_phase01(evidence, _canonical_profile(evidence), _branch_analysis(evidence))
    assert any(issue.code == "dangling_parent_id" for issue in report.errors)


def test_genericity_scan_uses_forbidden_corpus_and_ast_count_checks() -> None:
    root = Path(__file__).parents[1] / "src" / "renpy_story_mapper" / "storyboard"
    corpus = json.loads(
        (Path(__file__).parent / "fixtures" / "storyboard_forbidden_genericity.json").read_text(
            encoding="utf-8"
        )
    )
    tokens = [str(item).casefold() for item in corpus["forbidden_tokens"]]
    for path in (*root.rglob("*.py"), *root.rglob("*.json")):
        text = path.read_text(encoding="utf-8").casefold()
        assert not any(token in text for token in tokens), path
    forbidden_counts = {int(value) for value in corpus["forbidden_count_literals"]}
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "range"
            ):
                for argument in node.args:
                    if isinstance(argument, ast.Constant) and argument.value in forbidden_counts:
                        raise AssertionError(f"fixed count range in {path}:{node.lineno}")
            if (
                isinstance(node, ast.Compare)
                and isinstance(node.left, ast.Call)
                and isinstance(node.left.func, ast.Name)
                and node.left.func.id == "len"
                and any(
                    isinstance(value, ast.Constant) and value.value in forbidden_counts
                    for value in node.comparators
                )
            ):
                raise AssertionError(f"fixed count comparison in {path}:{node.lineno}")
