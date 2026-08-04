from __future__ import annotations

from copy import deepcopy
from typing import Any

from renpy_story_mapper.storyboard.validation import validate_phase01


def _span(line: int) -> dict[str, object]:
    return {
        "path": "game/canary.rpy",
        "start": {"line": line, "column": 5},
        "end": {"line": line, "column": 42},
    }


def _base_objects() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    records = [
        {"id": "label-start", "kind": "label", "accountable": True, "source": _span(1)},
        {"id": "line-intro", "kind": "dialogue", "accountable": True, "source": _span(2)},
        {"id": "menu-main", "kind": "menu", "accountable": True, "source": _span(3)},
        {"id": "arm-left", "kind": "choice_arm", "accountable": True, "source": _span(4)},
        {"id": "arm-right", "kind": "choice_arm", "accountable": True, "source": _span(6)},
        {"id": "label-left", "kind": "label", "accountable": True, "source": _span(8)},
        {"id": "line-left", "kind": "dialogue", "accountable": True, "source": _span(9)},
        {"id": "label-right", "kind": "label", "accountable": True, "source": _span(11)},
        {"id": "line-right", "kind": "dialogue", "accountable": True, "source": _span(12)},
    ]
    evidence: dict[str, object] = {
        "schema_version": "storyboard-evidence-v1",
        "revision": "idx-canary-1",
        "records": records,
        "menus": [{"id": "menu-main", "arm_ids": ["arm-left", "arm-right"]}],
    }
    profile: dict[str, object] = {
        "schema_version": "storyboard-profile-v1",
        "source_revision": "idx-canary-1",
        "claims": [
            {
                "text": "The canary has a named start label.",
                "evidence_ids": ["label-start"],
                "confidence": "high",
                "unresolved": False,
            }
        ],
    }
    analysis: dict[str, object] = {
        "schema_version": "storyboard-analysis-v1",
        "source_revision": "idx-canary-1",
        "scenes": [
            {
                "id": "scene-start",
                "member_evidence_ids": [
                    "label-start",
                    "line-intro",
                    "menu-main",
                    "arm-left",
                    "arm-right",
                    "label-left",
                    "line-left",
                    "label-right",
                    "line-right",
                ],
                "lines": [{"evidence_id": "line-intro"}],
                "choices": [
                    {
                        "menu_evidence_id": "menu-main",
                        "arm_evidence_id": "arm-left",
                        "consequence": {
                            "text": "The left route continues.",
                            "evidence_ids": ["arm-left", "label-left"],
                            "confidence": "medium",
                            "unresolved": False,
                        },
                        "destination": {
                            "kind": "label",
                            "target_evidence_id": "label-left",
                            "evidence_ids": ["arm-left", "label-left"],
                            "confidence": "high",
                            "unresolved": False,
                        },
                    },
                    {
                        "menu_evidence_id": "menu-main",
                        "arm_evidence_id": "arm-right",
                        "consequence": {
                            "text": "The right route continues.",
                            "evidence_ids": ["arm-right", "label-right"],
                            "confidence": "medium",
                            "unresolved": False,
                        },
                        "destination": {
                            "kind": "label",
                            "target_evidence_id": "label-right",
                            "evidence_ids": ["arm-right", "label-right"],
                            "confidence": "high",
                            "unresolved": False,
                        },
                    },
                ],
            }
        ],
    }
    return evidence, profile, analysis


def _error(report: Any, code: str) -> dict[str, object]:
    return next(item for item in report.to_dict()["errors"] if item["code"] == code)


def test_fake_evidence_citation_is_rejected() -> None:
    evidence, profile, analysis = _base_objects()
    profile["claims"] = [
        {
            "text": "This citation is not in the index.",
            "evidence_ids": ["ev-fake"],
            "confidence": "low",
            "unresolved": False,
        }
    ]

    report = validate_phase01(evidence, profile, analysis)

    assert not report.publishable
    assert _error(report, "unknown_evidence_id")["evidence_ids"] == ["ev-fake"]
    assert report.to_dict()["coverage"] == {
        "expected": 9,
        "covered": 9,
        "excluded": 0,
        "unaccounted": 0,
        "duplicate_memberships": 0,
        "complete": True,
    }


def test_omitted_choice_arm_is_reported_with_exact_id_and_source_span() -> None:
    evidence, profile, analysis = _base_objects()
    reduced = deepcopy(analysis)
    scene = reduced["scenes"][0]
    assert isinstance(scene, dict)
    scene["member_evidence_ids"] = [
        item for item in scene["member_evidence_ids"] if item != "arm-right"
    ]
    scene["choices"] = [scene["choices"][0]]

    report = validate_phase01(evidence, profile, reduced)

    assert not report.publishable
    missing = _error(report, "missing_menu_arm")
    assert missing["evidence_ids"] == ["menu-main", "arm-right"]
    assert missing["source"] == _span(6)


def test_duplicate_membership_and_coverage_totals_are_reported() -> None:
    evidence, profile, analysis = _base_objects()
    scene = analysis["scenes"][0]
    assert isinstance(scene, dict)
    scene["member_evidence_ids"].append("line-intro")
    analysis["exclusions"] = [{
        "evidence_id": "line-intro",
        "reason": "incorrectly excluded",
        "unresolved": True,
        "uncertainty": "The line is still present in the scene.",
        "evidence_ids": ["line-intro"],
        "confidence": "low",
    }]

    report = validate_phase01(evidence, profile, analysis)
    result: Any = report.to_dict()

    assert not report.publishable
    assert any(item["code"] == "duplicate_membership" for item in result["errors"])
    assert result["coverage"]["covered"] == 9
    assert result["coverage"]["excluded"] == 1
    assert result["coverage"]["duplicate_memberships"] >= 1


def test_dynamic_behavior_and_missing_uncertainty_are_not_publishable() -> None:
    evidence, profile, analysis = _base_objects()
    evidence["records"].append(
        {
            "id": "jump-dynamic",
            "kind": "jump",
            "accountable": True,
            "source": _span(14),
            "facts": {"target": None, "expression": "route_selector"},
        }
    )
    scene = analysis["scenes"][0]
    assert isinstance(scene, dict)
    scene["member_evidence_ids"].append("jump-dynamic")
    scene["choices"][0]["destination"] = {
        "kind": "label",
        "target_evidence_id": "jump-dynamic",
        "evidence_ids": ["jump-dynamic"],
        "confidence": "high",
        "unresolved": False,
    }
    analysis["unresolved"] = [
        {
            "evidence_ids": ["jump-dynamic"],
            "confidence": "low",
            "unresolved": True,
        }
    ]

    report = validate_phase01(evidence, profile, analysis)
    result: Any = report.to_dict()
    codes = {item["code"] for item in result["errors"]}

    assert not report.publishable
    assert "dynamic_behavior_as_fact" in codes
    assert "missing_uncertainty" in codes


def test_parser_ai_disagreements_remain_visible_as_warnings() -> None:
    evidence, profile, analysis = _base_objects()
    analysis["disagreements"] = [
        {
            "id": "disagreement-1",
            "evidence_ids": ["arm-left"],
            "parser": "static jump to label-left",
            "ai": "The route may be dynamic.",
            "resolution": "unresolved",
            "confidence": "low",
            "unresolved": True,
            "uncertainty": "The custom helper may alter the target.",
        }
    ]

    report = validate_phase01(evidence, profile, analysis)
    result: Any = report.to_dict()

    assert report.publishable
    assert result["disagreements"][0]["id"] == "disagreement-1"
    assert any(
        item["code"] == "parser_ai_disagreement" for item in result["warnings"]
    )


def test_empty_inputs_are_never_publishable() -> None:
    report = validate_phase01({}, {}, {})
    codes = {item.code for item in report.errors}

    assert not report.publishable
    assert not report.coverage["complete"]
    assert {"empty_evidence_index", "empty_game_profile", "empty_story_analysis"} <= codes


def test_dynamic_evidence_in_any_inference_object_is_not_a_resolved_fact() -> None:
    evidence, profile, analysis = _base_objects()
    records = evidence["records"]
    assert isinstance(records, list)
    records.append(
        {
            "id": "custom-dynamic",
            "kind": "custom",
            "accountable": False,
            "source": _span(15),
            "facts": {"opaque_reason": "creator_defined_statement"},
        }
    )
    profile["custom_constructs"] = [
        {
            "id": "custom-meaning",
            "meaning": "This construct always redirects the route.",
            "evidence_ids": ["custom-dynamic"],
            "confidence": "high",
            "unresolved": False,
        }
    ]

    report = validate_phase01(evidence, profile, analysis)

    assert not report.publishable
    assert any(item.code == "dynamic_behavior_as_fact" for item in report.errors)
