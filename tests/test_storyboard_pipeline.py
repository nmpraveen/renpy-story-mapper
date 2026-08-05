from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import renpy_story_mapper.storyboard.pipeline as storyboard_pipeline
from renpy_story_mapper.cli import main
from renpy_story_mapper.storyboard.ai_client import (
    CanonicalValidationIssue,
    ProviderCanonicalValidationError,
)
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


def _source_and_evidence(
    tmp_path: Path,
) -> tuple[Path, dict[str, object], dict[str, object]]:
    game = tmp_path / "input-game"
    game.mkdir()
    (game / "canary.rpy").write_text(SOURCE, encoding="utf-8")
    index = build_evidence_index(game, source_path="canary.rpy", label="unfamiliar_entry")
    raw_evidence = index.to_dict()
    evidence = evidence_index_to_mapping(index)
    assert raw_evidence["menus"]
    assert isinstance(evidence["menus"], list)
    return game, raw_evidence, evidence


def _artifact_hash(value: object) -> str:
    return hashlib.sha256(_artifact_text(value).encode("utf-8")).hexdigest()


def _artifact_text(value: object) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def _schema_replays(
    raw_evidence: dict[str, object], evidence: dict[str, object]
) -> tuple[dict[str, object], dict[str, object]]:
    records = [item for item in evidence["records"] if isinstance(item, dict)]
    ids = [item["id"] for item in records]
    menu = next(item for item in evidence["menus"] if isinstance(item, dict))
    arm_ids = menu["arm_ids"]
    profile: dict[str, object] = {
        "schema": "storyboard-game-profile-v1",
        "source": {
            "evidence_index_hash": _artifact_hash(raw_evidence),
            "scope_evidence_ids": ids,
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
    source_lines = {
        int(item["facts"]["line_number"]): item["id"]
        for item in records
        if item["kind"] == "source_line" and isinstance(item.get("facts"), dict)
    }
    condition = next(
        item
        for item in records
        if item["kind"] == "condition"
        and isinstance(item.get("facts"), dict)
        and item["facts"].get("condition_type") == "if_branch"
    )
    condition_id = str(condition["id"])
    analysis: dict[str, object] = {
        "schema": "storyboard-story-analysis-v1",
        "source": {
            "evidence_index_hash": _artifact_hash(raw_evidence),
            "profile_hash": _artifact_hash(profile),
            "canary_evidence_ids": ids,
        },
        "scenes": [
            {
                "id": "scene-unfamiliar-entry",
                "title": "An unfamiliar entry",
                "summary": "The static analysis preserves exact source and both arms.",
                "order": 0,
                "line_evidence_ids": [
                    source_lines[line]
                    for line in (1, 2, 3, 6)
                    if line in source_lines
                ],
                "choice_ids": ["choice-main", "choice-condition"],
                "evidence_ids": [ids[0]],
                "confidence": "medium",
                "status": "unresolved",
                "uncertainty": "The assignment and runtime condition are not statically closed.",
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
                        "line_evidence_ids": [
                            source_lines[line]
                            for line in ((7, 8) if ordinal == 0 else (9, 10))
                            if line in source_lines
                        ],
                        "consequence": {
                            "text": f"Arm {ordinal + 1} continues.",
                            "evidence_ids": [arm_id],
                            "confidence": "low",
                            "status": "uncertain",
                            "uncertainty": "The target is not established by this canary.",
                        },
                        "destination_scene_id": None,
                        "rejoin_scene_id": None,
                        "terminal": "unresolved",
                        "evidence_ids": [arm_id],
                        "confidence": "low",
                        "status": "uncertain",
                        "uncertainty": "The target is not established by this canary.",
                    }
                    for ordinal, arm_id in enumerate(arm_ids)
                ],
                "evidence_ids": [menu["id"]],
                "confidence": "medium",
                "status": "resolved",
                "uncertainty": None,
            },
            {
                "id": "choice-condition",
                "scene_id": "scene-unfamiliar-entry",
                "caption": "Conditional line",
                "condition": "strange_counter > 0",
                "arms": [
                    {
                        "id": "arm-condition",
                        "caption": "Condition holds",
                        "condition": "strange_counter > 0",
                        "line_evidence_ids": [source_lines[4], source_lines[5]],
                        "consequence": {
                            "text": "The conditional line is shown.",
                            "evidence_ids": [condition_id],
                            "confidence": "medium",
                            "status": "resolved",
                            "uncertainty": None,
                        },
                        "evidence_ids": [condition_id],
                        "confidence": "medium",
                        "status": "resolved",
                        "uncertainty": None,
                    }
                ],
                "evidence_ids": [condition_id],
                "confidence": "medium",
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
    return profile, analysis


def test_evidence_adapter_makes_menu_ownership_and_facts_explicit(tmp_path: Path) -> None:
    _game, _raw_evidence, evidence = _source_and_evidence(tmp_path)

    records = {item["id"]: item for item in evidence["records"] if isinstance(item, dict)}
    menu = evidence["menus"][0]
    assert menu["arm_ids"]
    assert all(records[item]["kind"] == "choice_arm" for item in menu["arm_ids"])
    assignment = next(item for item in records.values() if item["kind"] == "assignment")
    assert assignment["facts"]["target"] == "strange_counter"
    assert assignment["source_text"].strip().startswith("$")


def test_pipeline_writes_exactly_five_artifacts_and_keeps_input_unchanged(tmp_path: Path) -> None:
    game, raw_evidence, evidence = _source_and_evidence(tmp_path)
    profile, analysis = _schema_replays(raw_evidence, evidence)
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
    assert "Arm 1" in (output / "index.html").read_text(encoding="utf-8")
    assert json.loads((output / "evidence-index.json").read_text(encoding="utf-8")) == raw_evidence


def test_schema_shaped_replay_is_validated_and_rendered_without_mutating_artifact(
    tmp_path: Path,
) -> None:
    game, raw_evidence, evidence = _source_and_evidence(tmp_path)
    profile, analysis = _schema_replays(raw_evidence, evidence)
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


def test_empty_evidence_profile_and_analysis_are_rejected(tmp_path: Path) -> None:
    empty_game = tmp_path / "empty-game"
    empty_game.mkdir()
    (empty_game / "empty.rpy").write_text("", encoding="utf-8")
    with pytest.raises(StoryboardPipelineError, match="canary evidence is empty"):
        run_storyboard_pipeline(
            empty_game,
            tmp_path / "empty-evidence-artifacts",
            profile_replay={},
            analysis_replay={},
        )

    game, raw_evidence, evidence = _source_and_evidence(tmp_path)
    profile, analysis = _schema_replays(raw_evidence, evidence)
    with pytest.raises(StoryboardPipelineError, match="game-profile response is empty"):
        run_storyboard_pipeline(
            game,
            tmp_path / "empty-profile-artifacts",
            source_path="canary.rpy",
            label="unfamiliar_entry",
            profile_replay={},
            analysis_replay=analysis,
        )
    with pytest.raises(StoryboardPipelineError, match="story-analysis response is empty"):
        run_storyboard_pipeline(
            game,
            tmp_path / "empty-analysis-artifacts",
            source_path="canary.rpy",
            label="unfamiliar_entry",
            profile_replay=profile,
            analysis_replay={},
        )


def test_replays_must_match_bundled_schemas(tmp_path: Path) -> None:
    game, raw_evidence, evidence = _source_and_evidence(tmp_path)
    profile, analysis = _schema_replays(raw_evidence, evidence)

    invalid_profile = dict(profile)
    invalid_profile.pop("source")
    with pytest.raises(StoryboardPipelineError, match=r"game-profile.*bundled schema"):
        run_storyboard_pipeline(
            game,
            tmp_path / "invalid-profile-artifacts",
            source_path="canary.rpy",
            label="unfamiliar_entry",
            profile_replay=invalid_profile,
            analysis_replay=analysis,
        )

    invalid_analysis = dict(analysis)
    invalid_analysis.pop("choices")
    with pytest.raises(StoryboardPipelineError, match=r"story-analysis.*bundled schema"):
        run_storyboard_pipeline(
            game,
            tmp_path / "invalid-analysis-artifacts",
            source_path="canary.rpy",
            label="unfamiliar_entry",
            profile_replay=profile,
            analysis_replay=invalid_analysis,
        )


def test_legacy_replay_envelopes_are_rejected_instead_of_unwrapped(tmp_path: Path) -> None:
    game, raw_evidence, evidence = _source_and_evidence(tmp_path)
    profile, analysis = _schema_replays(raw_evidence, evidence)

    with pytest.raises(StoryboardPipelineError, match="legacy envelope"):
        run_storyboard_pipeline(
            game,
            tmp_path / "profile-envelope",
            source_path="canary.rpy",
            label="unfamiliar_entry",
            profile_replay={"profile": profile},
            analysis_replay=analysis,
        )
    with pytest.raises(StoryboardPipelineError, match="legacy envelope"):
        run_storyboard_pipeline(
            game,
            tmp_path / "game-profile-envelope",
            source_path="canary.rpy",
            label="unfamiliar_entry",
            profile_replay={"game_profile": profile},
            analysis_replay=analysis,
        )
    with pytest.raises(StoryboardPipelineError, match="legacy envelope"):
        run_storyboard_pipeline(
            game,
            tmp_path / "analysis-envelope",
            source_path="canary.rpy",
            label="unfamiliar_entry",
            profile_replay=profile,
            analysis_replay={"analysis": analysis},
        )
    with pytest.raises(StoryboardPipelineError, match="legacy envelope"):
        run_storyboard_pipeline(
            game,
            tmp_path / "story-analysis-envelope",
            source_path="canary.rpy",
            label="unfamiliar_entry",
            profile_replay=profile,
            analysis_replay={"story_analysis": analysis},
        )


def test_replay_provenance_binds_raw_evidence_and_exact_profile_json(tmp_path: Path) -> None:
    game, raw_evidence, evidence = _source_and_evidence(tmp_path)
    profile, analysis = _schema_replays(raw_evidence, evidence)
    output = tmp_path / "provenance-artifacts"

    run_storyboard_pipeline(
        game,
        output,
        source_path="canary.rpy",
        label="unfamiliar_entry",
        profile_replay=profile,
        analysis_replay=analysis,
    )

    expected_evidence_hash = _artifact_hash(raw_evidence)
    expected_profile_hash = _artifact_hash(profile)
    expected_analysis_hash = _artifact_hash(analysis)
    written_evidence = json.loads((output / "evidence-index.json").read_text(encoding="utf-8"))
    written_profile = json.loads((output / "game-profile.json").read_text(encoding="utf-8"))
    written_analysis = json.loads((output / "story-analysis.json").read_text(encoding="utf-8"))
    report = json.loads((output / "validation-report.json").read_text(encoding="utf-8"))
    html = (output / "index.html").read_text(encoding="utf-8")

    assert written_evidence == raw_evidence
    assert written_profile == profile
    assert written_analysis == analysis
    assert hashlib.sha256((output / "evidence-index.json").read_bytes()).hexdigest() == (
        expected_evidence_hash
    )
    assert hashlib.sha256((output / "game-profile.json").read_bytes()).hexdigest() == (
        expected_profile_hash
    )
    assert hashlib.sha256((output / "story-analysis.json").read_bytes()).hexdigest() == (
        expected_analysis_hash
    )
    assert written_profile["source"]["evidence_index_hash"] == expected_evidence_hash
    assert written_analysis["source"]["evidence_index_hash"] == expected_evidence_hash
    assert written_analysis["source"]["profile_hash"] == expected_profile_hash
    assert report["provenance"] == {
        "hash_algorithm": "sha256",
        "hash_basis": "serialized artifact bytes",
        "serialization": "UTF-8 JSON with sorted keys, two-space indentation, and trailing newline",
        "evidence_index_hash": expected_evidence_hash,
        "game_profile_hash": expected_profile_hash,
        "story_analysis_hash": expected_analysis_hash,
    }
    assert f'name="storyboard-evidence-index-hash" content="{expected_evidence_hash}"' in html
    assert (
        f'name="storyboard-validation-report-hash" '
        f'content="{_artifact_hash(report)}"'
    ) in html


def test_replay_provenance_mismatch_is_rejected(tmp_path: Path) -> None:
    game, raw_evidence, evidence = _source_and_evidence(tmp_path)
    profile, analysis = _schema_replays(raw_evidence, evidence)

    bad_profile = dict(profile)
    bad_profile["source"] = {**profile["source"], "evidence_index_hash": "0" * 64}
    with pytest.raises(
        StoryboardPipelineError, match=r"game profile source\.evidence_index_hash"
    ):
        run_storyboard_pipeline(
            game,
            tmp_path / "bad-profile-provenance",
            source_path="canary.rpy",
            label="unfamiliar_entry",
            profile_replay=bad_profile,
            analysis_replay=analysis,
        )

    bad_analysis = dict(analysis)
    bad_analysis["source"] = {**analysis["source"], "profile_hash": "0" * 64}
    with pytest.raises(StoryboardPipelineError, match=r"story analysis source\.profile_hash"):
        run_storyboard_pipeline(
            game,
            tmp_path / "bad-analysis-provenance",
            source_path="canary.rpy",
            label="unfamiliar_entry",
            profile_replay=profile,
            analysis_replay=bad_analysis,
        )


def test_output_inside_game_is_rejected_before_artifacts_are_written(tmp_path: Path) -> None:
    game, _raw_evidence, _evidence = _source_and_evidence(tmp_path)

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


def test_file_input_protects_its_source_directory_from_output(tmp_path: Path) -> None:
    game, _raw_evidence, _evidence = _source_and_evidence(tmp_path)
    source = game / "canary.rpy"

    with pytest.raises(StoryboardPipelineError, match="outside"):
        run_storyboard_pipeline(
            source,
            game / "generated-from-file",
            label="unfamiliar_entry",
            profile_replay={},
            analysis_replay={},
        )

    assert not (game / "generated-from-file").exists()


def test_source_scope_echoes_must_cover_every_canary_evidence_id(tmp_path: Path) -> None:
    game, raw_evidence, evidence = _source_and_evidence(tmp_path)
    profile, analysis = _schema_replays(raw_evidence, evidence)
    profile_source = profile["source"]
    assert isinstance(profile_source, dict)
    profile_source["scope_evidence_ids"] = profile_source["scope_evidence_ids"][:-1]

    with pytest.raises(StoryboardPipelineError, match="scope_evidence_ids"):
        run_storyboard_pipeline(
            game,
            tmp_path / "profile-subset",
            source_path="canary.rpy",
            label="unfamiliar_entry",
            profile_replay=profile,
            analysis_replay=analysis,
        )

    profile, analysis = _schema_replays(raw_evidence, evidence)
    analysis_source = analysis["source"]
    assert isinstance(analysis_source, dict)
    analysis_source["canary_evidence_ids"] = analysis_source["canary_evidence_ids"][:-1]

    with pytest.raises(StoryboardPipelineError, match="canary_evidence_ids"):
        run_storyboard_pipeline(
            game,
            tmp_path / "analysis-subset",
            source_path="canary.rpy",
            label="unfamiliar_entry",
            profile_replay=profile,
            analysis_replay=analysis,
        )


def test_schema_valid_dangling_story_references_reject_publication(tmp_path: Path) -> None:
    game, raw_evidence, evidence = _source_and_evidence(tmp_path)
    profile, analysis = _schema_replays(raw_evidence, evidence)
    evidence_ids = profile["source"]["scope_evidence_ids"]
    assert isinstance(evidence_ids, list)
    choices = analysis["choices"]
    assert isinstance(choices, list)
    arms = choices[0]["arms"]
    assert isinstance(arms, list)
    arms[0]["destination_scene_id"] = "scene-missing-destination"
    arms[0]["source_evidence_ids"] = [evidence_ids[0]]
    arms[0]["target_evidence_ids"] = [evidence_ids[-1]]
    analysis["transitions"] = [
        {
            "id": "transition-missing-target",
            "from_id": "scene-unfamiliar-entry",
            "to_id": "scene-missing-transition",
            "kind": "jump",
            "evidence_ids": [evidence_ids[0]],
            "source_evidence_ids": [evidence_ids[0]],
            "target_evidence_ids": [evidence_ids[-1]],
            "confidence": "low",
            "status": "uncertain",
            "uncertainty": "The named destination is not in the scene set.",
        }
    ]

    result = run_storyboard_pipeline(
        game,
        tmp_path / "dangling-references",
        source_path="canary.rpy",
        label="unfamiliar_entry",
        profile_replay=profile,
        analysis_replay=analysis,
    )

    assert not result.validation_report.publishable
    errors = result.validation_report.to_dict()["errors"]
    assert isinstance(errors, list)
    assert sum(item["code"] == "invalid_story_reference" for item in errors) >= 2
    html = result.artifacts["index.html"].read_text(encoding="utf-8")
    assert "invalid_story_reference" in html


def test_output_publication_is_fresh_and_transactional(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    game, raw_evidence, evidence = _source_and_evidence(tmp_path)
    profile, analysis = _schema_replays(raw_evidence, evidence)
    existing = tmp_path / "existing-output"
    existing.mkdir()
    with pytest.raises(StoryboardPipelineError, match="already exists"):
        run_storyboard_pipeline(
            game,
            existing,
            source_path="canary.rpy",
            label="unfamiliar_entry",
            profile_replay=profile,
            analysis_replay=analysis,
        )

    real_write_text = storyboard_pipeline._write_text
    calls = 0

    def fail_on_final_artifact(path: Path, content: str) -> None:
        nonlocal calls
        calls += 1
        if calls == len(ARTIFACT_FILENAMES):
            raise StoryboardPipelineError("synthetic late write failure")
        real_write_text(path, content)

    monkeypatch.setattr(storyboard_pipeline, "_write_text", fail_on_final_artifact)
    output = tmp_path / "late-output"
    with pytest.raises(StoryboardPipelineError, match="synthetic late write failure"):
        run_storyboard_pipeline(
            game,
            output,
            source_path="canary.rpy",
            label="unfamiliar_entry",
            profile_replay=profile,
            analysis_replay=analysis,
        )

    assert not output.exists()
    assert not list(tmp_path.glob(".late-output-*"))


def test_cli_supports_json_replay_inputs_and_bounded_label(tmp_path: Path, capsys: Any) -> None:
    game, raw_evidence, evidence = _source_and_evidence(tmp_path)
    profile, analysis = _schema_replays(raw_evidence, evidence)
    replay = tmp_path / "replay"
    replay.mkdir()
    (replay / "profile.json").write_text(_artifact_text(profile), encoding="utf-8")
    (replay / "analysis.json").write_text(_artifact_text(analysis), encoding="utf-8")
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
    game, raw_evidence, evidence = _source_and_evidence(tmp_path)
    profile, analysis = _schema_replays(raw_evidence, evidence)
    scenes = analysis["scenes"]
    assert isinstance(scenes, list)
    scene = scenes[0]
    assert isinstance(scene, dict)
    evidence_ids = scene["evidence_ids"]
    assert isinstance(evidence_ids, list)
    scene["evidence_ids"] = [*evidence_ids, "fake-evidence-id"]

    replay = tmp_path / "rejected-replay"
    replay.mkdir()
    (replay / "profile.json").write_text(_artifact_text(profile), encoding="utf-8")
    (replay / "analysis.json").write_text(_artifact_text(analysis), encoding="utf-8")
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
    game, raw_evidence, evidence = _source_and_evidence(tmp_path)

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
            ai_evidence = request_input["evidence_index"]
            assert isinstance(ai_evidence, dict)
            assert not {
                "annotations",
                "ledger",
                "leaf_evidence_ids",
                "annotation_evidence_ids",
                "accountable_evidence_ids",
            } & ai_evidence.keys()
            assert ai_evidence["source"] == raw_evidence["source"]
            ai_records = ai_evidence["records"]
            canonical_records = raw_evidence["records"]
            assert isinstance(ai_records, list)
            assert isinstance(canonical_records, list)
            assert [item["id"] for item in ai_records] == [
                item["id"] for item in canonical_records
            ]
            for compact, canonical in zip(ai_records, canonical_records, strict=True):
                assert compact["source_text"] == canonical["source_text"]
                assert compact["facts"] == canonical["facts"]
                assert compact["metadata"] == canonical["metadata"]
                assert compact["role"] == canonical["role"]
                assert "text" not in compact
                assert compact["source"]["path"] == canonical["source"]["path"]
                assert compact["source"]["span"] == canonical["source"]["span"]
                assert "provenance" not in compact["source"]
            required_provenance = payload["required_provenance"]
            assert isinstance(required_provenance, dict)
            assert required_provenance["evidence_index_hash"] == _artifact_hash(raw_evidence)
            profile, analysis = _schema_replays(raw_evidence, evidence)
            if schema_path.name.startswith("story-analysis"):
                assert required_provenance["profile_hash"] == _artifact_hash(profile)
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
    assert result.evidence_index == raw_evidence


def test_pipeline_binds_complete_source_receipts_to_provider_results(tmp_path: Path) -> None:
    game, raw_evidence, evidence = _source_and_evidence(tmp_path)
    expected_ids = [
        item["id"] for item in evidence["records"] if isinstance(item, dict)
    ]
    semantic_marker = "AI-owned semantic content is preserved."

    class IncompleteReceiptClient:
        def complete(self, **request: object) -> dict[str, object]:
            schema_path = request["schema_path"]
            payload = request["payload"]
            assert isinstance(schema_path, Path)
            assert isinstance(payload, dict)
            request_input = payload["input"]
            assert isinstance(request_input, dict)
            current_profile = request_input.get("game_profile")
            profile, analysis = _schema_replays(raw_evidence, evidence)
            if schema_path.name.startswith("game-profile"):
                profile["conventions"] = [
                    {
                        "id": "semantic-marker",
                        "kind": "test-convention",
                        "description": semantic_marker,
                        "evidence_ids": [expected_ids[0]],
                        "confidence": "high",
                        "status": "resolved",
                        "uncertainty": None,
                    }
                ]
                profile_source = profile["source"]
                assert isinstance(profile_source, dict)
                profile_source["scope_evidence_ids"] = [expected_ids[0]]
                return profile
            assert isinstance(current_profile, dict)
            analysis_source = analysis["source"]
            assert isinstance(analysis_source, dict)
            analysis_source["profile_hash"] = _artifact_hash(current_profile)
            analysis_source["canary_evidence_ids"] = [expected_ids[0]]
            return analysis

        def cancel(self) -> None:
            return None

    result = run_storyboard_pipeline(
        game,
        tmp_path / "bound-source-artifacts",
        source_path="canary.rpy",
        label="unfamiliar_entry",
        ai_client=IncompleteReceiptClient(),  # type: ignore[arg-type]
    )

    assert result.game_profile["source"] == {
        "evidence_index_hash": _artifact_hash(raw_evidence),
        "scope_evidence_ids": expected_ids,
    }
    assert result.story_analysis["source"] == {
        "evidence_index_hash": _artifact_hash(raw_evidence),
        "profile_hash": _artifact_hash(result.game_profile),
        "canary_evidence_ids": expected_ids,
    }
    conventions = result.game_profile["conventions"]
    assert isinstance(conventions, list)
    assert conventions[0]["description"] == semantic_marker
    assert result.validation_report.publishable


def test_pipeline_allows_exactly_one_targeted_canonical_repair(tmp_path: Path) -> None:
    game, raw_evidence, evidence = _source_and_evidence(tmp_path)
    profile, analysis = _schema_replays(raw_evidence, evidence)
    invalid_profile = dict(profile)
    invalid_profile["uncertainty"] = "A resolved response cannot retain uncertainty text."

    class RepairClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def complete(self, **request: object) -> dict[str, object]:
            payload = request["payload"]
            assert isinstance(payload, dict)
            self.calls.append(payload)
            if len(self.calls) == 1:
                raise ProviderCanonicalValidationError(
                    invalid_profile,
                    (
                        CanonicalValidationIssue(
                            ("uncertainty",),
                            "value is not of type 'null'",
                        ),
                    ),
                )
            if len(self.calls) == 2:
                assert payload["prompt_version"] == "storyboard-canonical-repair-prompt-v1"
                repair_input = payload["input"]
                assert isinstance(repair_input, dict)
                assert repair_input["prior_response"] == invalid_profile
                issues = repair_input["validator_issues"]
                assert isinstance(issues, list)
                assert issues[0]["path"] == ["uncertainty"]
                assert "not of type 'null'" in issues[0]["message"]
                assert payload["required_provenance"] == self.calls[0]["required_provenance"]
                return profile
            return analysis

        def cancel(self) -> None:
            return None

    client = RepairClient()
    output = tmp_path / "repair-artifacts"
    result = run_storyboard_pipeline(
        game,
        output,
        source_path="canary.rpy",
        label="unfamiliar_entry",
        ai_client=client,  # type: ignore[arg-type]
    )

    assert len(client.calls) == 3
    assert invalid_profile["uncertainty"] == (
        "A resolved response cannot retain uncertainty text."
    )
    written_profile = json.loads((output / "game-profile.json").read_text(encoding="utf-8"))
    assert written_profile["uncertainty"] is None
    assert result.validation_report.publishable


def test_pipeline_fails_after_the_single_repair_attempt(tmp_path: Path) -> None:
    game, raw_evidence, evidence = _source_and_evidence(tmp_path)
    profile, _analysis = _schema_replays(raw_evidence, evidence)
    invalid_profile = dict(profile)
    invalid_profile["uncertainty"] = "Still invalid for resolved status."

    class InvalidRepairClient:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, **request: object) -> dict[str, object]:
            del request
            self.calls += 1
            return invalid_profile

        def cancel(self) -> None:
            return None

    client = InvalidRepairClient()
    output = tmp_path / "failed-repair-artifacts"
    with pytest.raises(
        StoryboardPipelineError,
        match="after one targeted repair",
    ):
        run_storyboard_pipeline(
            game,
            output,
            source_path="canary.rpy",
            label="unfamiliar_entry",
            ai_client=client,  # type: ignore[arg-type]
        )

    assert client.calls == 2
    assert not output.exists()
