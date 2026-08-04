from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from renpy_story_mapper.cli import main
from renpy_story_mapper.storyboard.evidence import build_evidence_index
from renpy_story_mapper.storyboard.pipeline import (
    ARTIFACT_FILENAMES,
    StoryboardPipelineError,
    evidence_index_to_mapping,
    run_storyboard_pipeline,
)

SOURCE = """label unfamiliar_entry:
    "An exact line from an unfamiliar speaker."
    $ strange_counter = 1
    if strange_counter > 0:
        "A conditional line."
    menu:
        "First branch":
            jump unfamiliar_left
        "Second branch" if strange_counter > 0:
            jump unfamiliar_right

label unfamiliar_left:
    custom_statement with_unknown_behavior
    return

label unfamiliar_right:
    python:
        never_run = True
    return
"""


def _source_and_evidence(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    game = tmp_path / "input-game"
    game.mkdir()
    (game / "canary.rpy").write_text(SOURCE, encoding="utf-8")
    index = build_evidence_index(game, source_path="canary.rpy", label="unfamiliar_entry")
    evidence = evidence_index_to_mapping(index)
    assert index.to_dict()["menus"]
    assert isinstance(evidence["menus"], list)
    return game, evidence


def _legacy_replays(evidence: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    records = [item for item in evidence["records"] if isinstance(item, dict)]
    record_ids = [item["id"] for item in records]
    menu = next(item for item in evidence["menus"] if isinstance(item, dict))
    menu_id = menu["id"]
    arms = menu["arm_ids"]
    profile: dict[str, object] = {
        "schema_version": "storyboard-profile-v1",
        "source_revision": evidence["revision"],
        "claims": [
            {
                "text": "The selected label is a bounded entry point.",
                "evidence_ids": [next(item["id"] for item in records if item["kind"] == "label")],
                "confidence": "high",
                "unresolved": False,
            }
        ],
    }
    choices = [
        {
            "menu_evidence_id": menu_id,
            "arm_evidence_id": arm_id,
            "consequence": {
                "text": f"Arm {ordinal + 1} continues to a separate route.",
                "evidence_ids": [arm_id],
                "confidence": "medium",
                "unresolved": False,
            },
            "destination": {
                "kind": "unresolved",
                "evidence_ids": [arm_id],
                "confidence": "low",
                "unresolved": True,
                "uncertainty": "The selected canary does not establish the target label body.",
            },
        }
        for ordinal, arm_id in enumerate(arms)
    ]
    analysis: dict[str, object] = {
        "schema_version": "storyboard-analysis-v1",
        "source_revision": evidence["revision"],
        "scenes": [
            {
                "id": "scene-unfamiliar-entry",
                "member_evidence_ids": record_ids,
                "line_evidence_ids": [
                    item["id"]
                    for item in records
                    if item["kind"] in {"dialogue", "narration"}
                ],
                "choices": choices,
            }
        ],
        "unresolved": [],
        "disagreements": [],
    }
    return profile, analysis


def _schema_replays(evidence: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    records = [item for item in evidence["records"] if isinstance(item, dict)]
    ids = [item["id"] for item in records]
    menu = next(item for item in evidence["menus"] if isinstance(item, dict))
    arm_ids = menu["arm_ids"]
    profile: dict[str, object] = {
        "schema": "storyboard-game-profile-v1",
        "source": {
            "evidence_index_hash": evidence["revision"],
            "scope_evidence_ids": ids,
        },
        "entry_points": [],
        "characters": [],
        "variables": [],
        "custom_constructs": [],
        "conventions": [],
        "ending_patterns": [],
        "unresolved": [],
    }
    analysis: dict[str, object] = {
        "schema": "storyboard-story-analysis-v1",
        "source": {
            "evidence_index_hash": evidence["revision"],
            "profile_hash": "replay-profile",
            "canary_evidence_ids": ids,
        },
        "scenes": [
            {
                "id": "scene-unfamiliar-entry",
                "title": "An unfamiliar entry",
                "summary": "The static analysis preserves exact source and both arms.",
                "order": 0,
                "line_evidence_ids": [
                    item["id"]
                    for item in records
                    if item["kind"] in {"dialogue", "narration"}
                ],
                "choice_ids": ["choice-main"],
                "evidence_ids": ids,
                "confidence": "medium",
                "unresolved": "none",
            }
        ],
        "choices": [
            {
                "id": "choice-main",
                "scene_id": "scene-unfamiliar-entry",
                "caption": "What happens next?",
                "condition": None,
                "arms": [
                    {
                        "id": f"arm-{ordinal}",
                        "caption": f"Arm {ordinal + 1}",
                        "line_evidence_ids": [arm_id],
                        "consequence": f"Arm {ordinal + 1} continues.",
                        "destination_id": None,
                        "rejoin_id": None,
                        "terminal": "unresolved",
                        "evidence_ids": [arm_id],
                        "confidence": "low",
                        "unresolved": "The target is not established by this canary.",
                    }
                    for ordinal, arm_id in enumerate(arm_ids)
                ],
                "evidence_ids": [menu["id"]],
                "confidence": "medium",
                "unresolved": "none",
            }
        ],
        "transitions": [],
        "claims": [],
        "excluded_evidence_ids": [],
        "unresolved": [],
        "disagreements": [],
    }
    return profile, analysis


def test_evidence_adapter_makes_menu_ownership_and_facts_explicit(tmp_path: Path) -> None:
    _game, evidence = _source_and_evidence(tmp_path)

    records = {item["id"]: item for item in evidence["records"] if isinstance(item, dict)}
    menu = evidence["menus"][0]
    assert menu["arm_ids"]
    assert all(records[item]["kind"] == "choice_arm" for item in menu["arm_ids"])
    assignment = next(item for item in records.values() if item["kind"] == "assignment")
    assert assignment["facts"]["target"] == "strange_counter"
    assert assignment["source_text"].strip().startswith("$")


def test_pipeline_writes_exactly_five_artifacts_and_keeps_input_unchanged(tmp_path: Path) -> None:
    game, evidence = _source_and_evidence(tmp_path)
    profile, analysis = _legacy_replays(evidence)
    before = (game / "canary.rpy").read_bytes()
    output = tmp_path / "artifacts"

    result = run_storyboard_pipeline(
        game,
        output,
        source_path="canary.rpy",
        label="unfamiliar_entry",
        profile_replay=profile,
        analysis_replay=analysis,
    )

    assert tuple(path.name for path in result.artifacts.values()) == ARTIFACT_FILENAMES
    assert {item.name for item in output.iterdir()} == set(ARTIFACT_FILENAMES)
    assert (game / "canary.rpy").read_bytes() == before
    assert result.validation_report.publishable
    assert "An exact line from an unfamiliar speaker." in (output / "index.html").read_text(
        encoding="utf-8"
    )
    assert "First branch" in (output / "index.html").read_text(encoding="utf-8")


def test_schema_shaped_replay_is_validated_and_rendered_without_mutating_artifact(
    tmp_path: Path,
) -> None:
    game, evidence = _source_and_evidence(tmp_path)
    profile, analysis = _schema_replays(evidence)
    output = tmp_path / "schema-artifacts"

    result = run_storyboard_pipeline(
        game,
        output,
        source_path="canary.rpy",
        label="unfamiliar_entry",
        profile_replay=profile,
        analysis_replay=analysis,
    )

    assert result.validation_report.publishable
    written_analysis = json.loads((output / "story-analysis.json").read_text(encoding="utf-8"))
    assert written_analysis == analysis
    html = (output / "index.html").read_text(encoding="utf-8")
    assert "What happens next?" in html
    assert "Arm 1" in html
    assert "Arm 2" in html


def test_output_inside_game_is_rejected_before_artifacts_are_written(tmp_path: Path) -> None:
    game, _evidence = _source_and_evidence(tmp_path)

    with pytest.raises(StoryboardPipelineError, match="outside"):
        run_storyboard_pipeline(
            game,
            game / "generated",
            source_path="canary.rpy",
            label="unfamiliar_entry",
            profile_replay={},
            analysis_replay={},
        )
    assert not (game / "generated").exists()


def test_cli_supports_json_replay_inputs_and_bounded_label(tmp_path: Path, capsys: Any) -> None:
    game, evidence = _source_and_evidence(tmp_path)
    profile, analysis = _legacy_replays(evidence)
    replay = tmp_path / "replay"
    replay.mkdir()
    (replay / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
    (replay / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")
    output = tmp_path / "cli-artifacts"

    code = main(
        [
            "storyboard",
            str(game),
            "--output",
            str(output),
            "--source-path",
            "canary.rpy",
            "--canary-label",
            "unfamiliar_entry",
            "--profile-json",
            str(replay / "profile.json"),
            "--analysis-json",
            str(replay / "analysis.json"),
        ]
    )

    assert code == 0
    assert "Storyboard output:" in capsys.readouterr().out
    assert set(item.name for item in output.iterdir()) == set(ARTIFACT_FILENAMES)


def test_cli_returns_two_for_rejected_validation_and_keeps_artifacts(
    tmp_path: Path, capsys: Any
) -> None:
    game, evidence = _source_and_evidence(tmp_path)
    profile, analysis = _legacy_replays(evidence)
    scenes = analysis["scenes"]
    assert isinstance(scenes, list)
    scene = scenes[0]
    assert isinstance(scene, dict)
    member_evidence_ids = scene["member_evidence_ids"]
    assert isinstance(member_evidence_ids, list)
    member_evidence_ids.append("fake-evidence-id")

    replay = tmp_path / "rejected-replay"
    replay.mkdir()
    (replay / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
    (replay / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")
    output = tmp_path / "rejected-artifacts"

    code = main(
        [
            "storyboard",
            str(game),
            "--output",
            str(output),
            "--source-path",
            "canary.rpy",
            "--canary-label",
            "unfamiliar_entry",
            "--profile-json",
            str(replay / "profile.json"),
            "--analysis-json",
            str(replay / "analysis.json"),
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "Validation: rejected" in captured.out
    assert set(item.name for item in output.iterdir()) == set(ARTIFACT_FILENAMES)


def test_pipeline_makes_one_profile_and_one_analysis_provider_call(tmp_path: Path) -> None:
    game, _evidence = _source_and_evidence(tmp_path)

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def complete(self, **request: object) -> dict[str, object]:
            schema_path = request["schema_path"]
            assert isinstance(schema_path, Path)
            self.calls.append(schema_path.name)
            payload = request["payload"]
            assert isinstance(payload, dict)
            request_input = payload["input"]
            assert isinstance(request_input, dict)
            evidence = request_input["evidence_index"]
            assert isinstance(evidence, dict)
            profile, analysis = _legacy_replays(evidence)
            return profile if schema_path.name.startswith("game-profile") else analysis

        def cancel(self) -> None:
            return None

    client = FakeClient()
    result = run_storyboard_pipeline(
        game,
        tmp_path / "provider-artifacts",
        source_path="canary.rpy",
        label="unfamiliar_entry",
        ai_client=client,  # type: ignore[arg-type]
    )

    assert client.calls == ["game-profile.schema.json", "story-analysis.schema.json"]
    assert result.validation_report.publishable
