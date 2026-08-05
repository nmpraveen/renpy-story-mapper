from __future__ import annotations

from collections.abc import Mapping

from renpy_story_mapper.storyboard.evidence import build_evidence_index_from_text
from renpy_story_mapper.storyboard.model import EvidenceIndex, EvidenceRecord
from renpy_story_mapper.storyboard.pipeline import evidence_index_to_mapping
from renpy_story_mapper.storyboard.render import render_storyboard_html

SOURCE = """label opening:
    "Opening line"
    jump branch

label branch:
    menu:
        "Continue":
            jump merge
        "Loop":
            jump branch

label merge:
    "Merged line"
    return

label ending:
    "Ending line"
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


def _canonical_inputs() -> tuple[EvidenceIndex, dict[str, object], dict[str, object]]:
    index = build_evidence_index_from_text(SOURCE, path="game/canary.rpy")
    line_ids = {
        line_number: _record_for_line(index, line_number).id
        for line_number in (1, 2, 3, 5, 6, 7, 8, 9, 10, 12, 13, 14, 16, 17, 18)
    }
    menu = next(record for record in index.records if record.kind.value == "menu")
    choice_arms = sorted(index.choice_arms, key=lambda record: record.source.span.start_line)
    continue_arm, loop_arm = choice_arms
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
    }

    def transition(
        identifier: str,
        source_scene_id: str,
        destination_scene_id: str | None,
        kind: str,
        source_evidence_id: str,
        target_evidence_id: str | None,
    ) -> dict[str, object]:
        return {
            "id": identifier,
            "from_id": source_scene_id,
            "to_id": destination_scene_id,
            "kind": kind,
            "source_evidence_ids": [source_evidence_id],
            "target_evidence_ids": [] if target_evidence_id is None else [target_evidence_id],
            "evidence_ids": [
                source_evidence_id,
                *([] if target_evidence_id is None else [target_evidence_id]),
            ],
            "confidence": "high",
        }

    analysis: dict[str, object] = {
        "schema": "storyboard-story-analysis-v1",
        "story_title": "Canonical Reader Story",
        "source": {
            "evidence_index_hash": "fixture-evidence-hash",
            "profile_hash": "fixture-profile-hash",
            "canary_evidence_ids": all_ids,
        },
        # Deliberately not in order: the renderer must use the canonical order field.
        "scenes": [
            {
                "id": "scene-merge",
                "title": "Shared merge",
                "summary": "The routes meet here.",
                "order": 2,
                "line_evidence_ids": [line_ids[13]],
                "evidence_ids": [line_ids[12], line_ids[13]],
                "confidence": "high",
            },
            {
                "id": "scene-opening",
                "title": "Opening",
                "summary": "The story begins.",
                "order": 0,
                "line_evidence_ids": [line_ids[2], line_ids[1]],
                "evidence_ids": [line_ids[2], line_ids[1]],
                "confidence": "high",
            },
            {
                "id": "scene-ending",
                "title": "Ending",
                "summary": "The story closes.",
                "order": 3,
                "line_evidence_ids": [line_ids[17]],
                "evidence_ids": [line_ids[16], line_ids[17]],
                "confidence": "high",
            },
            {
                "id": "scene-branch",
                "title": "Branch route",
                "summary": "A local choice changes the route.",
                "order": 1,
                "line_evidence_ids": [line_ids[9], line_ids[6]],
                "choice_ids": ["choice-branch"],
                "evidence_ids": [line_ids[5], str(menu.id)],
                "confidence": "high",
                # Canonical payloads must not fall back to these old nested shapes.
                "menus": [{"title": "Legacy nested menu must stay hidden"}],
                "branches": [{"title": "Legacy nested branch must stay hidden"}],
            },
        ],
        "choices": [
            {
                "id": "choice-branch",
                "scene_id": "scene-branch",
                "caption": "Pick a route",
                "condition": None,
                "arms": [
                    {
                        "id": "arm-continue",
                        "caption": "Continue to merge",
                        "condition": "route_is_open",
                        "line_evidence_ids": [line_ids[8]],
                        "source_evidence_ids": [line_ids[8]],
                        "target_evidence_ids": [line_ids[12]],
                        "consequence": "The route rejoins the shared merge.",
                        "destination_scene_id": "scene-merge",
                        "rejoin_scene_id": "scene-merge",
                        "rejoin_evidence_ids": [line_ids[12]],
                        "terminal": "none",
                        "evidence_ids": [str(continue_arm.id)],
                        "confidence": "high",
                    },
                    {
                        "id": "arm-loop",
                        "caption": "Loop back",
                        "line_evidence_ids": [line_ids[10]],
                        "source_evidence_ids": [line_ids[10]],
                        "target_evidence_ids": [line_ids[5]],
                        "consequence": "The route returns to the branch.",
                        "destination_scene_id": "scene-branch",
                        "rejoin_scene_id": None,
                        "terminal": "loop",
                        "evidence_ids": [str(loop_arm.id)],
                        "confidence": "high",
                    },
                ],
                "evidence_ids": [str(menu.id)],
                "confidence": "high",
            }
        ],
        "transitions": [
            transition(
                "transition-jump",
                "scene-opening",
                "scene-branch",
                "direct_jump",
                line_ids[3],
                line_ids[5],
            ),
            transition(
                "transition-rejoin",
                "scene-branch",
                "scene-merge",
                "rejoin",
                line_ids[8],
                line_ids[12],
            ),
            transition(
                "transition-loop",
                "scene-merge",
                "scene-merge",
                "loop",
                line_ids[14],
                line_ids[12],
            ),
            transition(
                "transition-custom",
                "scene-branch",
                "scene-ending",
                "custom_route",
                line_ids[10],
                line_ids[16],
            ),
            transition(
                "transition-terminal",
                "scene-ending",
                None,
                "terminal",
                line_ids[18],
                None,
            ),
        ],
        "claims": [],
        "excluded_evidence_ids": [],
        "unresolved": [],
        "disagreements": [],
    }
    return index, profile, analysis


def test_canonical_renderer_keeps_story_topology_and_technical_evidence_collapsed() -> None:
    index, profile, analysis = _canonical_inputs()

    html = render_storyboard_html(index.to_dict(), profile, analysis, {})

    assert "<title>Canonical Reader Story</title>" in html
    assert "<h1>Canonical Reader Story</h1>" in html
    assert "<h1>Storyboard</h1>" not in html

    opening = html.index('<article class="scene" id="scene-0">')
    branch = html.index('<article class="scene" id="scene-1">')
    merge = html.index('<article class="scene" id="scene-2">')
    ending = html.index('<article class="scene" id="scene-3">')
    assert opening < branch < merge < ending

    assert "Opening line" in html[opening:branch]
    assert "Pick a route" not in html[opening:branch]
    assert "Pick a route" in html[branch:merge]
    assert "The route rejoins the shared merge." in html[branch:merge]
    assert "Legacy nested menu must stay hidden" not in html
    assert "Legacy nested branch must stay hidden" not in html

    assert "Direct jump" in html[opening:branch]
    assert "Kind:</span>direct_jump" in html[opening:branch]
    assert "Destination:</span>Branch route" in html[opening:branch]
    assert "Rejoin" in html[branch:merge]
    assert "Destination:</span>Shared merge" in html[branch:merge]
    assert "Custom route" in html[branch:merge]
    assert "Loop" in html[merge:ending]
    assert "Destination:</span>Shared merge" in html[merge:ending]
    assert "Terminal" in html[ending:]

    assert "game/canary.rpy:1 (columns 1-15)" in html
    assert "game/canary.rpy:2 (columns 1-19)" in html
    opening_first_line = html[opening:branch].index('label opening:')
    opening_second_line = html[opening:branch].index("&quot;Opening line&quot;")
    assert opening_first_line < opening_second_line

    assert '<summary>Source evidence</summary>' in html
    assert '<summary>Target evidence</summary>' in html
    assert '<details class="technical-evidence"' in html
    for record in index.records:
        if record.id in {str(item) for item in analysis["transitions"][0]["evidence_ids"]}:
            identifier_position = html.index(record.id)
            assert html.rfind("<details", 0, identifier_position) > html.rfind(
                "</details>", 0, identifier_position
            )


def test_canonical_renderer_accepts_mapping_evidence_from_real_index() -> None:
    index, profile, analysis = _canonical_inputs()
    evidence = evidence_index_to_mapping(index)

    assert isinstance(evidence, Mapping)
    html = render_storyboard_html(evidence, profile, analysis, {})

    assert "Canonical Reader Story" in html
    assert "game/canary.rpy:8" in html


def test_canonical_renderer_ignores_legacy_topology_aliases() -> None:
    index, profile, analysis = _canonical_inputs()
    transitions = analysis["transitions"]
    choices = analysis["choices"]
    assert isinstance(transitions, list)
    assert isinstance(choices, list)
    assert isinstance(choices[0], dict)
    arms = choices[0]["arms"]
    assert isinstance(arms, list)
    assert isinstance(arms[0], dict)

    transitions[0]["source_scene_id"] = "scene-ending"
    transitions[0]["destination_scene_id"] = "scene-ending"
    arms[0]["destination_id"] = "scene-ending"
    arms[0]["rejoin_id"] = "scene-ending"

    html = render_storyboard_html(index.to_dict(), profile, analysis, {})

    opening = html.index('<article class="scene" id="scene-0">')
    branch = html.index('<article class="scene" id="scene-1">')
    assert "Destination:</span>Ending" not in html[opening:branch]
    assert "Shared merge" in html[branch:]


def test_canonical_game_title_is_used_when_story_title_is_absent() -> None:
    index, profile, analysis = _canonical_inputs()
    profile.pop("story_title")
    analysis.pop("story_title")

    html = render_storyboard_html(index.to_dict(), profile, analysis, {})

    assert "<h1>Canonical Game</h1>" in html
