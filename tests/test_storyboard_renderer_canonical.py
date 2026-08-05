from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from jsonschema import Draft202012Validator

from renpy_story_mapper.storyboard.evidence import build_evidence_index_from_text
from renpy_story_mapper.storyboard.model import EvidenceIndex, EvidenceRecord, redact_public_value
from renpy_story_mapper.storyboard.pipeline import evidence_index_to_mapping
from renpy_story_mapper.storyboard.render import render_storyboard_html
from renpy_story_mapper.storyboard.validation import validate_phase01

SOURCE = """label opening:
    "Opening line"
    menu:
        "End the route":
            "Ending branch line"
        "Loop back":
            "Loop branch line"
        "Leave unresolved":
            "Unresolved branch line"
        "Continue":
            "Ordinary branch line"
    return

label ending:
    "Shared ending line"
    return
"""


def _record_for_line(index: EvidenceIndex, line_number: int) -> EvidenceRecord:
    for record in index.records:
        if (
            record.kind.value == "source_line"
            and record.metadata.get("line_number") == line_number
            and record.metadata.get("leaf") is True
        ):
            return record
    raise AssertionError(f"missing source line {line_number}")


def _schema_errors(document: Mapping[str, object], filename: str) -> list[str]:
    schema_path = Path(__file__).parents[1] / "src/renpy_story_mapper/storyboard/schemas" / filename
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    return [error.message for error in sorted(validator.iter_errors(document), key=str)]


def _assert_fixture_contract(
    index: EvidenceIndex,
    profile: Mapping[str, object],
    analysis: Mapping[str, object],
) -> None:
    assert _schema_errors(profile, "game-profile.schema.json") == []
    assert _schema_errors(analysis, "story-analysis.schema.json") == []
    report = validate_phase01(evidence_index_to_mapping(index), profile, analysis)
    assert report.publishable, [error.to_dict() for error in report.errors]


def _canonical_inputs() -> tuple[EvidenceIndex, dict[str, object], dict[str, object]]:
    index = build_evidence_index_from_text(SOURCE, path="game/canary.rpy")
    line_ids = {
        line_number: _record_for_line(index, line_number).id
        for line_number in range(1, 17)
        if line_number != 13
    }
    menu = next(record for record in index.records if record.kind.value == "menu")
    choice_arms = sorted(index.choice_arms, key=lambda record: record.source.span.start_line)
    arm_records = {
        "end": choice_arms[0],
        "loop": choice_arms[1],
        "unresolved": choice_arms[2],
        "none": choice_arms[3],
    }
    label_records = {
        str(record.metadata["name"]): record
        for record in index.labels
        if isinstance(record.metadata.get("name"), str)
    }
    all_ids = [record.id for record in index.records]

    profile: dict[str, object] = {
        "schema": "storyboard-game-profile-v1",
        "game_title": "Canonical Game",
        "story_title": "Canonical Reader Story",
        "source": {
            "evidence_index_hash": "fixture-evidence-hash",
            "scope_evidence_ids": all_ids,
        },
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

    def consequence(
        text: str,
        evidence_id: str,
        *,
        confidence: str,
        status: str,
        uncertainty: str | None,
        rationale: str,
    ) -> dict[str, object]:
        return {
            "text": text,
            "evidence_ids": [evidence_id],
            "confidence": confidence,
            "status": status,
            "uncertainty": uncertainty,
            "rationale": rationale,
        }

    def arm(
        identifier: str,
        caption: str,
        arm_record: EvidenceRecord,
        line_numbers: tuple[int, int],
        *,
        condition: str | None,
        condition_evidence_ids: list[str],
        consequence_value: dict[str, object],
        terminal: str,
        status: str,
        uncertainty: str | None,
        rationale: str,
        destination_scene_id: str | None = None,
        source_evidence_ids: list[str] | None = None,
        target_evidence_ids: list[str] | None = None,
    ) -> dict[str, object]:
        value: dict[str, object] = {
            "id": identifier,
            "caption": caption,
            "condition": condition,
            "condition_evidence_ids": condition_evidence_ids,
            "line_evidence_ids": [line_ids[line] for line in line_numbers],
            "consequence": consequence_value,
            "terminal": terminal,
            "evidence_ids": [arm_record.id],
            "confidence": "high" if status == "resolved" else "low",
            "status": status,
            "uncertainty": uncertainty,
            "rationale": rationale,
        }
        if destination_scene_id is not None:
            value["destination_scene_id"] = destination_scene_id
            value["source_evidence_ids"] = source_evidence_ids or []
            value["target_evidence_ids"] = target_evidence_ids or []
        return value

    analysis: dict[str, object] = {
        "schema": "storyboard-story-analysis-v1",
        "story_title": "Canonical Reader Story",
        "source": {
            "evidence_index_hash": "fixture-evidence-hash",
            "profile_hash": "fixture-profile-hash",
            "canary_evidence_ids": all_ids,
        },
        "scenes": [
            {
                "id": "scene-opening",
                "title": "Opening",
                "summary": "The shared opening presents four possible route outcomes.",
                "order": 0,
                "line_evidence_ids": [
                    line_ids[1],
                    line_ids[2],
                    line_ids[3],
                    line_ids[12],
                ],
                "choice_ids": ["choice-route"],
                "evidence_ids": [label_records["opening"].id, menu.id],
                "confidence": "high",
                "status": "uncertain",
                "uncertainty": "One route's terminal behavior depends on runtime state.",
                "rationale": "The shared lines and menu are directly cited in the source ledger.",
            },
            {
                "id": "scene-ending",
                "title": "Ending",
                "summary": "The shared ending line closes the selected section.",
                "order": 1,
                "line_evidence_ids": [line_ids[14], line_ids[15], line_ids[16]],
                "evidence_ids": [label_records["ending"].id],
                "confidence": "high",
                "status": "resolved",
                "uncertainty": None,
                "rationale": "The ending label and lines are explicit source evidence.",
            },
        ],
        "choices": [
            {
                "id": "choice-route",
                "scene_id": "scene-opening",
                "caption": "Choose a route",
                "condition": "menu_enabled",
                "condition_evidence_ids": [line_ids[3]],
                "menu_evidence_id": menu.id,
                "arms": [
                    arm(
                        "arm-end",
                        "End the route",
                        arm_records["end"],
                        (4, 5),
                        condition="ending_allowed",
                        condition_evidence_ids=[line_ids[4]],
                        consequence_value=consequence(
                            "The route reaches the ending.",
                            line_ids[5],
                            confidence="high",
                            status="resolved",
                            uncertainty=None,
                            rationale="The cited arm line names the ending route.",
                        ),
                        terminal="ending",
                        status="resolved",
                        uncertainty=None,
                        rationale="The ending arm is source-grounded.",
                    ),
                    arm(
                        "arm-loop",
                        "Loop back",
                        arm_records["loop"],
                        (6, 7),
                        condition=None,
                        condition_evidence_ids=[],
                        consequence_value=consequence(
                            "The route returns to the opening.",
                            line_ids[7],
                            confidence="high",
                            status="resolved",
                            uncertainty=None,
                            rationale="The arm is interpreted as a repeating route.",
                        ),
                        terminal="loop",
                        status="resolved",
                        uncertainty=None,
                        rationale="The destination scene is explicit in the analysis.",
                        destination_scene_id="scene-opening",
                        source_evidence_ids=[line_ids[6]],
                        target_evidence_ids=[line_ids[1]],
                    ),
                    arm(
                        "arm-unresolved",
                        "Leave unresolved",
                        arm_records["unresolved"],
                        (8, 9),
                        condition="runtime_choice",
                        condition_evidence_ids=[line_ids[8]],
                        consequence_value=consequence(
                            "The route's consequence cannot be established statically.",
                            line_ids[9],
                            confidence="low",
                            status="unresolved",
                            uncertainty="The runtime choice may select more than one destination.",
                            rationale="The cited line does not reveal a fixed target.",
                        ),
                        terminal="unresolved",
                        status="uncertain",
                        uncertainty="The runtime choice does not establish a terminal state.",
                        rationale="The source supports an unresolved outcome only.",
                    ),
                    arm(
                        "arm-none",
                        "Continue",
                        arm_records["none"],
                        (10, 11),
                        condition=None,
                        condition_evidence_ids=[],
                        consequence_value=consequence(
                            "The ordinary route continues.",
                            line_ids[11],
                            confidence="medium",
                            status="resolved",
                            uncertainty=None,
                            rationale="The branch line supports a normal continuation.",
                        ),
                        terminal="none",
                        status="resolved",
                        uncertainty=None,
                        rationale="No terminal state is declared for this arm.",
                    ),
                ],
                "evidence_ids": [menu.id],
                "confidence": "medium",
                "status": "uncertain",
                "uncertainty": "The menu condition is not guaranteed at runtime.",
                "rationale": "The menu and its condition are cited separately from its arms.",
            }
        ],
        "transitions": [
            {
                "id": "transition-opening-ending",
                "from_id": "scene-opening",
                "to_id": "scene-ending",
                "kind": "direct_jump",
                "source_evidence_ids": [line_ids[12]],
                "target_evidence_ids": [line_ids[14]],
                "evidence_ids": [line_ids[12], line_ids[14]],
                "confidence": "high",
                "status": "resolved",
                "uncertainty": None,
                "rationale": (
                    "The selected section reaches the ending label after the opening return."
                ),
            }
        ],
        "claims": [],
        "excluded_evidence_ids": [],
        "unresolved": [],
        "disagreements": [],
        "status": "uncertain",
        "uncertainty": "The menu condition and one terminal state remain runtime-dependent.",
    }
    _assert_fixture_contract(index, profile, analysis)
    return index, profile, analysis


def _details_body(html: str, summary: str) -> str:
    marker = f"<summary>{summary}</summary>"
    start = html.index(marker) + len(marker)
    return html[start : html.index("</details>", start)]


def test_canonical_fixture_is_schema_valid_and_deterministically_publishable() -> None:
    _canonical_inputs()


def test_canonical_renderer_preserves_local_metadata_and_terminal_semantics() -> None:
    index, profile, analysis = _canonical_inputs()

    html = render_storyboard_html(index.to_dict(), profile, analysis, {})

    assert "<title>Canonical Reader Story</title>" in html
    assert "<h1>Canonical Reader Story</h1>" in html
    opening = html.index('<article class="scene" id="scene-0">')
    ending = html.index('<article class="scene" id="scene-1">')
    assert opening < ending
    opening_html = html[opening:ending]

    assert "Opening line" in opening_html
    assert "Choose a route" in opening_html
    assert "menu_enabled" in opening_html
    assert "The menu and its condition are cited separately from its arms." in opening_html
    assert "The route reaches the ending." in opening_html
    assert "The route&#x27;s consequence cannot be established statically." in opening_html
    assert "The cited line does not reveal a fixed target." in opening_html
    assert "game/canary.rpy:1 (columns 1-15)" in html
    assert "game/canary.rpy:2 (columns 1-19)" in html

    choice_evidence = _details_body(html, "Choice evidence")
    condition_evidence = _details_body(html, "Condition evidence")
    consequence_evidence = _details_body(html, "Consequence evidence")
    arm_evidence = _details_body(html, "Arm evidence")
    assert str(analysis["choices"][0]["evidence_ids"][0]) in choice_evidence
    assert str(analysis["choices"][0]["condition_evidence_ids"][0]) in condition_evidence
    consequence_id = str(analysis["choices"][0]["arms"][0]["consequence"]["evidence_ids"][0])
    arm_id = str(analysis["choices"][0]["arms"][0]["evidence_ids"][0])
    assert consequence_id in consequence_evidence
    assert arm_id in arm_evidence
    assert consequence_id not in arm_evidence

    end_arm = html.index("End the route")
    loop_arm = html.index("Loop back")
    unresolved_arm = html.index("Leave unresolved")
    none_arm = html.index(">Continue</span>")
    assert "Terminal:</span>ending" in html[end_arm:loop_arm]
    assert "class=\"detail loop\"" in html[loop_arm:unresolved_arm]
    assert "Terminal:</span>loop" not in html[loop_arm:unresolved_arm]
    assert "Unresolved:</span>terminal behavior is unresolved." in html[unresolved_arm:none_arm]
    assert 'class="terminal"' not in html[unresolved_arm:none_arm]
    assert "Terminal:" not in html[none_arm:ending]

    assert "Destination:</span>Opening" in html[loop_arm:unresolved_arm]
    assert "Destination:</span>Ending" in opening_html
    assert '<summary>Source evidence</summary>' in html
    assert '<details class="technical-evidence"' in html


def test_canonical_projection_has_one_top_level_menu_and_no_legacy_nested_topology() -> None:
    index, profile, analysis = _canonical_inputs()

    html = render_storyboard_html(index.to_dict(), profile, analysis, {})

    assert html.count('<section class="menu"') == 1
    assert html.count('<ol class="arms">') == 1
    assert "Legacy nested menu" not in html
    assert "Legacy nested branch" not in html


def test_canonical_renderer_accepts_mapping_evidence_from_real_index() -> None:
    index, profile, analysis = _canonical_inputs()
    evidence = evidence_index_to_mapping(index)

    assert isinstance(evidence, Mapping)
    html = render_storyboard_html(evidence, profile, analysis, {})

    assert "Canonical Reader Story" in html
    assert "game/canary.rpy:8" in html


def test_canonical_game_title_is_used_when_story_title_is_absent() -> None:
    index, profile, analysis = _canonical_inputs()
    profile.pop("story_title")
    analysis.pop("story_title")

    html = render_storyboard_html(index.to_dict(), profile, analysis, {})

    assert "<h1>Canonical Game</h1>" in html


def test_public_redaction_handles_quoted_unc_and_nested_generic_text_without_leaks() -> None:
    drive_path = r"C:\Users\prave\Private Folder\drive source.rpy"
    unc_path = r"\\server\share\Private Folder\unc source.rpy"
    exact_source = r"say \"the source is intentionally exact\""
    payload = {
        "message": (
            f'quoted "{drive_path}" and unquoted {drive_path}; '
            f'quoted UNC "{unc_path}" and unquoted UNC {unc_path}.'
        ),
        "path": f'"{drive_path}"',
        "options": {"text": drive_path},
        "diagnostics": [{"text": unc_path}],
        "source_text": exact_source,
        "relative_path": r"..\relative\identity.rpy",
        "url": "https://example.test/story",
    }

    redacted = redact_public_value(payload, preserve_exact_text=True)
    assert isinstance(redacted, dict)
    serialized = json.dumps(redacted)
    message = redacted["message"]
    options = redacted["options"]
    diagnostics = redacted["diagnostics"]
    assert isinstance(message, str)
    assert isinstance(options, dict)
    assert isinstance(diagnostics, list)
    assert "C:/Users/prave" not in message
    assert "\\\\server\\share" not in message
    assert "Private Folder" not in message
    assert options["text"] == "source/drive source.rpy"
    assert diagnostics[0]["text"] == "source/unc source.rpy"
    assert redacted["path"] == "source/drive source.rpy"
    assert redacted["source_text"] == exact_source
    assert redacted["relative_path"] == "../relative/identity.rpy"
    assert redacted["url"] == "https://example.test/story"
    assert "https://example.test/story" in serialized
    assert "../relative/identity.rpy" in serialized

    html = render_storyboard_html(
        {
            "records": [
                {
                    "id": "path-evidence",
                    "source_text": "A safe exact line",
                    "source": {
                        "path": f'"{drive_path}"',
                        "start": {"line": 1},
                        "end": {"line": 1},
                    },
                }
            ]
        },
        {"title": "Path safety"},
        {"scenes": [{"title": "Start", "line_evidence_ids": ["path-evidence"]}]},
        {},
    )
    assert "Private Folder" not in html
    assert "source/drive source.rpy:1" in html
