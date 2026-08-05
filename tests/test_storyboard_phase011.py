from __future__ import annotations

import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

from renpy_story_mapper.storyboard.evidence import build_evidence_index_from_text
from renpy_story_mapper.storyboard.pipeline import evidence_index_to_mapping
from renpy_story_mapper.storyboard.render import render_storyboard_html
from renpy_story_mapper.storyboard.validation import validate_phase01

BRANCH_SOURCE = """label start:
    "Intro"
    menu:
        "Left":
            "Left line"
        "Right" if gate:
            "Right line"
    return
"""


def _branch_inputs() -> tuple[dict[str, object], dict[str, object], dict[str, str]]:
    index = build_evidence_index_from_text(BRANCH_SOURCE, label="start")
    evidence = evidence_index_to_mapping(index)
    records = [item for item in evidence["records"] if isinstance(item, dict)]
    lines = {
        str(item["facts"]["line_number"]): str(item["id"])
        for item in records
        if item["kind"] == "source_line" and isinstance(item.get("facts"), dict)
    }
    annotations = {
        str(item["kind"]): str(item["id"])
        for item in records
        if item["kind"] in {"label", "menu"}
    }
    arms = [item for item in records if item["kind"] == "choice_arm"]
    arms.sort(key=lambda item: int(item["facts"]["ordinal"]))
    arm_ids = {"left": str(arms[0]["id"]), "right": str(arms[1]["id"])}
    menu = next(item for item in evidence["menus"] if isinstance(item, dict))
    scene = {
        "id": "scene-start",
        "title": "Start",
        "summary": "The shared opening divides into two arms.",
        "order": 0,
        "line_evidence_ids": [lines[str(line)] for line in (1, 2, 3, 8)],
        "choice_ids": ["choice-main"],
        "evidence_ids": [annotations["label"], annotations["menu"]],
        "confidence": "high",
        "status": "resolved",
        "uncertainty": None,
    }
    choices = [
        {
            "id": "choice-main",
            "scene_id": "scene-start",
            "caption": "Choose a route",
            "condition": None,
            "menu_evidence_id": str(menu["id"]),
            "arms": [
                {
                    "id": "arm-left",
                    "caption": "Left",
                    "condition": None,
                    "line_evidence_ids": [lines["4"], lines["5"]],
                    "consequence": {
                        "text": "The left line follows.",
                        "evidence_ids": [arm_ids["left"]],
                        "confidence": "high",
                        "status": "resolved",
                        "uncertainty": None,
                    },
                    "destination_scene_id": None,
                    "rejoin_scene_id": None,
                    "terminal": "none",
                    "evidence_ids": [arm_ids["left"]],
                    "confidence": "high",
                    "status": "resolved",
                    "uncertainty": None,
                },
                {
                    "id": "arm-right",
                    "caption": "Right",
                    "condition": "gate",
                    "line_evidence_ids": [lines["6"], lines["7"]],
                    "consequence": {
                        "text": "The right line follows when gate is true.",
                        "evidence_ids": [arm_ids["right"]],
                        "confidence": "high",
                        "status": "resolved",
                        "uncertainty": None,
                    },
                    "destination_scene_id": None,
                    "rejoin_scene_id": None,
                    "terminal": "none",
                    "evidence_ids": [arm_ids["right"]],
                    "confidence": "high",
                    "status": "resolved",
                    "uncertainty": None,
                },
            ],
            "evidence_ids": [str(menu["id"])],
            "confidence": "high",
            "status": "resolved",
            "uncertainty": None,
        }
    ]
    analysis: dict[str, object] = {
        "schema": "storyboard-story-analysis-v1",
        "scenes": [scene],
        "choices": choices,
        "transitions": [],
        "claims": [],
        "excluded_evidence_ids": [],
        "unresolved": [],
        "disagreements": [],
        "status": "resolved",
        "uncertainty": None,
    }
    return evidence, analysis, lines


def test_parser_failure_keeps_raw_source_ledger() -> None:
    index = build_evidence_index_from_text('label start:\n\t"Tab-safe line"\n', label="start")

    assert any(item.code == "parse_failed" for item in index.diagnostics)
    artifact = index.to_dict()
    assert artifact["ledger"]
    assert any('"Tab-safe line"' in str(item["text"]) for item in artifact["ledger"])
    assert artifact["annotations"] == []


def test_line_window_closes_nested_parser_parents_and_keeps_actual_lines() -> None:
    source = """label start:
    if gate:
        "Nested line"
    return
"""
    index = build_evidence_index_from_text(source, label="start", start_line=3, end_line=3)
    records = {record.id: record for record in index.records}
    nested = [
        record
        for record in index.records
        if record.text.strip() == '"Nested line"' and record.kind.value != "source_line"
    ]

    assert nested
    parent_id = nested[0].metadata["parent_id"]
    assert parent_id in records
    assert any(record.kind.value == "label" for record in records.values())
    assert nested[0].source.span.start_line == 3


def test_branch_body_leaf_ownership_is_exact_once_and_reported_per_arm() -> None:
    evidence, analysis, _lines = _branch_inputs()

    profile = {"claims": [], "status": "resolved", "uncertainty": None}
    report = validate_phase01(evidence, profile, analysis)

    assert report.publishable
    coverage = report.to_dict()["coverage"]
    assert coverage["unaccounted"] == 0
    assert coverage["duplicate_memberships"] == 0
    assert {item["arm_id"] for item in coverage["per_arm"]} == {"arm-left", "arm-right"}
    assert all(item["covered"] == 2 for item in coverage["per_arm"])
    html = render_storyboard_html(evidence, {"title": "Branch"}, analysis, {})
    assert "Left line" in html
    assert "Right line" in html
    assert "The left line follows." in html
    assert "The right line follows when gate is true." in html

    scene = analysis["scenes"][0]
    assert isinstance(scene, dict)
    scene["line_evidence_ids"].append(analysis["choices"][0]["arms"][0]["line_evidence_ids"][0])
    rejected = validate_phase01(evidence, profile, analysis)
    assert not rejected.publishable
    assert any(item.code == "duplicate_membership" for item in rejected.errors)


def test_resolved_choice_consequence_and_custom_rationale_are_allowed_but_python_is_not() -> None:
    evidence = {
        "records": [
            {"id": "custom", "kind": "custom", "accountable": True, "source": {}},
            {"id": "python", "kind": "python", "accountable": True, "source": {}},
        ],
        "accountable_evidence_ids": ["custom", "python"],
    }
    profile = {
        "claims": [
            {
                "text": "The custom statement opens the route.",
                "evidence_ids": ["custom"],
                "confidence": "medium",
                "status": "resolved",
                "rationale": "The same source block is followed by the cited route line.",
            }
        ],
        "status": "resolved",
        "uncertainty": None,
    }
    analysis = {
        "scenes": [
            {
                "id": "scene",
                "evidence_ids": ["custom", "python"],
                "line_evidence_ids": ["custom", "python"],
                "confidence": "medium",
                "status": "unresolved",
                "uncertainty": "The embedded Python behavior is not statically closed.",
            }
        ],
        "claims": [
            {
                "id": "python-claim",
                "text": "The embedded block always sets the route.",
                "evidence_ids": ["python"],
                "confidence": "high",
                "status": "resolved",
                "uncertainty": None,
            }
        ],
        "status": "unresolved",
        "uncertainty": "The embedded Python behavior is not statically closed.",
    }

    report = validate_phase01(evidence, profile, analysis)

    assert any(item.code == "dynamic_behavior_as_fact" for item in report.errors)
    assert not any(item.code == "custom_interpretation_without_rationale" for item in report.errors)


def test_scene_order_and_semantic_destination_require_source_target_evidence() -> None:
    evidence, analysis, lines = _branch_inputs()
    scenes = analysis["scenes"]
    assert isinstance(scenes, list)
    scenes.append({
        "id": "scene-next",
        "title": "Next",
        "summary": "Continuation",
        "order": 0,
                "line_evidence_ids": [],
        "choice_ids": [],
        "evidence_ids": [lines["8"]],
        "confidence": "high",
        "status": "resolved",
        "uncertainty": None,
    })
    choice = analysis["choices"][0]
    assert isinstance(choice, dict)
    arm = choice["arms"][0]
    arm["destination_scene_id"] = "scene-next"
    arm["status"] = "resolved"

    report = validate_phase01(
        evidence,
        {"claims": [], "status": "resolved", "uncertainty": None},
        analysis,
    )

    codes = {item.code for item in report.errors}
    assert "duplicate_scene_order" in codes
    assert "missing_source_target_evidence" in codes


def test_public_artifacts_redact_absolute_paths_and_renderer_collapses_technical_evidence() -> None:
    index = build_evidence_index_from_text(
        "label start:\n    \"Exact line\"\n",
        path=r"C:\Users\prave\private\game.rpy",
        label="start",
    )
    artifact = evidence_index_to_mapping(index)
    serialized = json.dumps(artifact)
    assert "C:/Users" not in serialized
    assert "Users\\prave" not in serialized
    assert "source/game.rpy" in serialized

    html = render_storyboard_html(
        artifact,
        {"title": "Game"},
        {"scenes": [{"title": "Start", "line_evidence_ids": [artifact["leaf_evidence_ids"][0]]}]},
        {},
    )
    assert "<details" in html
    assert "Source evidence" in html


def test_storyboard_runtime_scan_has_no_known_game_or_fixed_count_constants() -> None:
    root = Path(__file__).parents[1] / "src" / "renpy_story_mapper" / "storyboard"
    text = "\n".join(path.read_text(encoding="utf-8").casefold() for path in root.rglob("*.py"))
    for forbidden in ("msdenvers", "resort", "sadie", "terrance", "v0.07", "_6_2_wg_clean"):
        assert forbidden not in text
    assert not re.search(r"range\(\s*(?:1[0-9]{2,}|[2-9][0-9]{2,})\s*\)", text)


def test_canonical_analysis_schema_accepts_empty_lines_and_semantic_destinations() -> None:
    schema = json.loads(
        (
            Path(__file__).parents[1]
            / "src/renpy_story_mapper/storyboard/schemas/story-analysis.schema.json"
        )
        .read_text(encoding="utf-8")
    )
    analysis = {
        "schema": "storyboard-story-analysis-v1",
        "source": {
            "evidence_index_hash": "evidence-hash",
            "profile_hash": "profile-hash",
            "canary_evidence_ids": ["line-1"],
        },
        "scenes": [
            {
                "id": "scene-start",
                "title": "Start",
                "summary": "The opening.",
                "order": 0,
                "confidence": "high",
                "status": "resolved",
                "uncertainty": None,
                "line_evidence_ids": [],
                "evidence_ids": ["line-1"],
            },
            {
                "id": "scene-next",
                "title": "Next",
                "summary": "The continuation.",
                "order": 1,
                "confidence": "medium",
                "status": "uncertain",
                "uncertainty": "The runtime condition is not statically closed.",
                "line_evidence_ids": [],
                "evidence_ids": ["line-1"],
            },
        ],
        "choices": [
            {
                "id": "choice-main",
                "scene_id": "scene-start",
                "caption": "Continue",
                "condition": None,
                "arms": [
                    {
                        "id": "arm-main",
                        "caption": "Continue",
                        "condition": "gate",
                        "condition_evidence_ids": [],
                        "line_evidence_ids": [],
                        "destination_scene_id": "scene-next",
                        "source_evidence_ids": ["line-1"],
                        "target_evidence_ids": ["line-1"],
                        "evidence_ids": ["line-1"],
                        "consequence": {
                            "text": "The next scene may follow.",
                            "evidence_ids": ["line-1"],
                            "confidence": "medium",
                            "status": "uncertain",
                            "uncertainty": "The gate is runtime-computed.",
                        },
                        "confidence": "medium",
                        "status": "uncertain",
                        "uncertainty": "The gate is runtime-computed.",
                    }
                ],
                "confidence": "medium",
                "status": "uncertain",
                "uncertainty": "The choice depends on runtime state.",
                "evidence_ids": ["line-1"],
            }
        ],
        "transitions": [],
        "claims": [],
        "excluded_evidence_ids": [],
        "unresolved": [],
        "disagreements": [],
        "status": "uncertain",
        "uncertainty": "The choice depends on runtime state.",
    }
    errors = list(Draft202012Validator(schema).iter_errors(analysis))
    assert errors == []
