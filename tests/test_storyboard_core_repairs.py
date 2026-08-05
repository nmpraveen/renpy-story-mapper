from __future__ import annotations

import ast
import json
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
                "leaf_evidence_ids": [lines[number] for number in (1, 2, 3, 8)],
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
                "leaf_evidence_ids": lines,
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
    scene["leaf_evidence_ids"] = [
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
                "leaf_evidence_ids": [
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
    scene["leaf_evidence_ids"] = [
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

    records = _records(evidence)
    analysis["scenes"].append(
        {
            "id": "scene-next",
            "title": "Next",
            "summary": "The continuation.",
            "order": 1,
            "leaf_evidence_ids": [],
            "evidence_ids": [str(records[0]["id"])],
            "confidence": "high",
            "status": "resolved",
            "uncertainty": None,
        }
    )
    first_arm.pop("destination_id")
    first_arm["destination_scene_id"] = "scene-next"
    first_arm["source_evidence_ids"] = [str(records[0]["id"])]
    first_arm["target_evidence_ids"] = [str(records[-1]["id"])]
    analysis["transitions"] = [
        {
            "id": "transition-main",
            "from_id": "scene-start",
            "to_id": "scene-next",
            "kind": "jump",
            "evidence_ids": [str(records[0]["id"])],
            "source_evidence_ids": [str(records[0]["id"])],
            "target_evidence_ids": [str(records[-1]["id"])],
            "confidence": "high",
            "status": "resolved",
            "uncertainty": None,
        }
    ]
    report = validate_phase01(evidence, profile, analysis)
    assert report.publishable
    schema_path = (
        Path(__file__).parents[1]
        / "src/renpy_story_mapper/storyboard/schemas/story-analysis.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(analysis)) == []


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
