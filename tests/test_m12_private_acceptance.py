from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import scripts.m12_private_acceptance as private_acceptance
from scripts.m12_private_acceptance import (
    MANIFEST_SCHEMA,
    _authority_requirement_facts,
    run,
)

from renpy_story_mapper.canonical_graph_contract import CanonicalFact
from renpy_story_mapper.m12_service import M12RouteService, load_m12_authority
from renpy_story_mapper.project import Project, create_ingested_project

FIXTURE = Path(__file__).parent / "fixtures" / "m12" / "private_gated_targets.rpy"


def _private_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    inputs = tmp_path / "private-inputs"
    inputs.mkdir()
    source = inputs / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    baseline = inputs / "accepted.rsmproj"
    create_ingested_project(baseline, source).close()
    archive = inputs / "story.rpa"
    archive.write_bytes(b"synthetic inert archive bytes")
    walkthrough = inputs / "walkthrough.txt"
    walkthrough.write_text("Optional diagnostic only.\n", encoding="utf-8")

    with Project.open(baseline) as project:
        service = M12RouteService(project)
        authority = load_m12_authority(project)
        catalog: list[dict[str, object]] = []
        offset = 0
        while True:
            page = service.destinations(offset=offset, limit=50)
            catalog.extend(page["nodes"])
            if page["next_offset"] is None:
                break
            offset = int(page["next_offset"])
        guarded_ids = {
            item.id for item in authority.scene_model.occurrences if item.guard_fact_ids
        }
        hidden = [
            item
            for item in catalog
            if item["kind"] == "exact_occurrence" and item["target_id"] in guarded_ids
        ][:3]
        assert len(hidden) == 3
        commitment = next(
            item
            for preferred in ("persistent_lane", "terminal")
            for item in catalog
            if item["kind"] == preferred
        )
    role = "persistent_lane" if commitment["kind"] == "persistent_lane" else "ending"
    manifest = inputs / "targets.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": MANIFEST_SCHEMA,
                "targets": [
                    *(
                        {
                            "role": "hidden_or_gated",
                            "kind": item["kind"],
                            "target_id": item["target_id"],
                        }
                        for item in hidden
                    ),
                    {
                        "role": role,
                        "kind": commitment["kind"],
                        "target_id": commitment["target_id"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    reports = tmp_path / "reports"
    reports.mkdir()
    return baseline, archive, manifest, walkthrough, reports / "m12-private"


def _fingerprint(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_size, stat.st_mtime_ns


def test_private_harness_emits_only_redacted_aggregate_and_preserves_inputs(
    tmp_path: Path,
) -> None:
    baseline, archive, manifest, walkthrough, output = _private_inputs(tmp_path)
    accepted_inputs = (baseline, archive, manifest, walkthrough)
    before = {path: _fingerprint(path) for path in accepted_inputs}

    report = run(
        baseline_path=baseline,
        archive_path=archive,
        targets_path=manifest,
        output_path=output,
        walkthrough_path=walkthrough,
    )

    assert report["status"] == "passed"
    assert report["coverage"]["hidden_or_gated_targets"] == 3
    hidden_results = [
        item for item in report["results"] if item["role"] == "hidden_or_gated"
    ]
    assert all(item["authority_hidden_or_gated"] is True for item in hidden_results)
    assert all(
        item["authority_classification"]["basis"] == "m11_occurrence_guard"
        for item in hidden_results
    )
    assert report["coverage"]["ending_targets"] + report["coverage"]["persistent_lane_targets"] == 1
    assert report["determinism"] == {
        "all_exact_replays_hit_cache": True,
        "all_normalized_replays_equal": True,
    }
    assert report["safety"] == {
        "provider_constructions": 0,
        "network_requests": 0,
        "subprocess_executions": 0,
        "creator_code_executions": 0,
        "renpy_or_game_executed": False,
        "private_paths_recorded": False,
    }
    assert {item.name for item in output.iterdir()} == {"acceptance.json"}
    report_text = (output / "acceptance.json").read_text(encoding="utf-8")
    for private_path in accepted_inputs:
        assert str(private_path) not in report_text
        assert private_path.name not in report_text
    assert before == {path: _fingerprint(path) for path in accepted_inputs}


def test_private_harness_rejects_output_beside_private_inputs(tmp_path: Path) -> None:
    baseline, archive, manifest, walkthrough, _output = _private_inputs(tmp_path)
    with pytest.raises(ValueError, match="isolated"):
        run(
            baseline_path=baseline,
            archive_path=archive,
            targets_path=manifest,
            output_path=baseline.parent / "unsafe-output",
            walkthrough_path=walkthrough,
        )


def test_private_harness_rejects_changed_normalized_replay_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline, archive, manifest, walkthrough, output = _private_inputs(tmp_path)
    original = private_acceptance._normalized_result_bytes
    calls = 0

    def unstable(result: dict[str, object]) -> bytes:
        nonlocal calls
        calls += 1
        payload = original(result)
        return payload + (b"changed" if calls == 2 else b"")

    monkeypatch.setattr(private_acceptance, "_normalized_result_bytes", unstable)

    with pytest.raises(AssertionError, match="changed normalized route bytes"):
        run(
            baseline_path=baseline,
            archive_path=archive,
            targets_path=manifest,
            output_path=output,
            walkthrough_path=walkthrough,
        )


def test_private_harness_rejects_fewer_than_three_hidden_or_gated_targets(
    tmp_path: Path,
) -> None:
    baseline, archive, manifest, walkthrough, output = _private_inputs(tmp_path)
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    hidden_seen = 0
    retained = []
    for item in raw["targets"]:
        if item["role"] == "hidden_or_gated":
            hidden_seen += 1
            if hidden_seen > 2:
                continue
        retained.append(item)
    raw["targets"] = retained
    manifest.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="at least 3 selected hidden or gated"):
        run(
            baseline_path=baseline,
            archive_path=archive,
            targets_path=manifest,
            output_path=output,
            walkthrough_path=walkthrough,
        )


def test_private_harness_rejects_role_kind_mismatch(tmp_path: Path) -> None:
    baseline, archive, manifest, walkthrough, output = _private_inputs(tmp_path)
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    commitment = next(item for item in raw["targets"] if item["role"] != "hidden_or_gated")
    commitment["role"] = (
        "ending" if commitment["kind"] == "persistent_lane" else "persistent_lane"
    )
    manifest.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="role does not match"):
        run(
            baseline_path=baseline,
            archive_path=archive,
            targets_path=manifest,
            output_path=output,
            walkthrough_path=walkthrough,
        )


def test_private_harness_rejects_caller_label_for_ungated_occurrence(
    tmp_path: Path,
) -> None:
    baseline, archive, manifest, walkthrough, output = _private_inputs(tmp_path)
    with Project.open(baseline) as project:
        authority = load_m12_authority(project)
        ungated_id = next(
            item.id for item in authority.scene_model.occurrences if not item.guard_fact_ids
        )
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    hidden = next(item for item in raw["targets"] if item["role"] == "hidden_or_gated")
    hidden["target_id"] = ungated_id
    manifest.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(AssertionError, match="lacks M10/M11 guard"):
        run(
            baseline_path=baseline,
            archive_path=archive,
            targets_path=manifest,
            output_path=output,
            walkthrough_path=walkthrough,
        )


def test_private_gate_classification_preserves_honest_unresolved_authority() -> None:
    facts = {
        "proven": CanonicalFact("proven", "requirement", "proven", ("e1",), (), {}),
        "unresolved": CanonicalFact(
            "unresolved", "requirement", "unresolved", ("e2",), (), {}
        ),
        "possible": CanonicalFact(
            "possible", "requirement", "possible", ("e3",), (), {}
        ),
        "effect": CanonicalFact("effect", "effect", "proven", ("e4",), (), {}),
        "no-evidence": CanonicalFact(
            "no-evidence", "requirement", "proven", (), (), {}
        ),
    }

    classified = _authority_requirement_facts(tuple(facts), facts)

    assert tuple(item.id for item in classified) == ("proven", "unresolved")
