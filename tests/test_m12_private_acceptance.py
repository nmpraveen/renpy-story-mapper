from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from scripts.m12_private_acceptance import MANIFEST_SCHEMA, run

from renpy_story_mapper.m12_service import M12RouteService
from renpy_story_mapper.project import Project, create_ingested_project

FIXTURE = Path(__file__).parent / "fixtures" / "m12" / "route_targets.rpy"


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
        hidden = next(
            item
            for item in service.destinations(query="Courtyard", limit=50)["nodes"]
            if item["kind"] == "generic_scene"
        )
        catalog: list[dict[str, object]] = []
        offset = 0
        while True:
            page = service.destinations(offset=offset, limit=50)
            catalog.extend(page["nodes"])
            if page["next_offset"] is None:
                break
            offset = int(page["next_offset"])
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
                    {
                        "role": "hidden_or_gated",
                        "kind": hidden["kind"],
                        "target_id": hidden["target_id"],
                    },
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
    assert report["coverage"]["hidden_or_gated_targets"] == 1
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


def test_private_harness_fails_conservatively_without_hidden_target(tmp_path: Path) -> None:
    baseline, archive, manifest, walkthrough, output = _private_inputs(tmp_path)
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    raw["targets"] = [item for item in raw["targets"] if item["role"] != "hidden_or_gated"]
    manifest.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="hidden or gated"):
        run(
            baseline_path=baseline,
            archive_path=archive,
            targets_path=manifest,
            output_path=output,
            walkthrough_path=walkthrough,
        )
