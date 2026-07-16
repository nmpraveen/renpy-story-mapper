from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from scripts.m13_provider_free_acceptance import run

from renpy_story_mapper.m12_service import M12RouteService
from renpy_story_mapper.project import create_ingested_project

FIXTURE = Path(__file__).parent / "fixtures" / "m12" / "route_targets.rpy"


def _fingerprint(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_size, stat.st_mtime_ns


def _mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping)
    return value


def _accepted_private_shape(tmp_path: Path) -> tuple[Path, Path, Path]:
    private_inputs = tmp_path / "private-inputs"
    source = private_inputs / "game"
    source.mkdir(parents=True)
    story = source / "private-story.rpy"
    story.write_bytes(FIXTURE.read_bytes())
    baseline = private_inputs / "private-accepted.rsmproj"
    with create_ingested_project(baseline, source) as project:
        service = M12RouteService(project)
        nodes = _mapping(service.destinations(limit=50))["nodes"]
        assert isinstance(nodes, list)
        destination = next(
            _mapping(item)
            for item in nodes
            if _mapping(item)["kind"] == "generic_scene"
        )
        kind = destination["kind"]
        target_id = destination["target_id"]
        assert isinstance(kind, str)
        assert isinstance(target_id, str)
        outcome = service.solve(service.prepare(kind, target_id))
        assert outcome.result is not None
    return baseline, story, tmp_path / "reports" / "m13-provider-free"


def test_provider_free_harness_exercises_complete_shape_without_private_leaks(
    tmp_path: Path,
) -> None:
    baseline, story, output = _accepted_private_shape(tmp_path)
    before = {path: _fingerprint(path) for path in (baseline, story)}

    report = run(
        baseline_path=baseline,
        source_path=story,
        output_path=output,
        minimum_scenes=1,
    )

    authority = _mapping(report["authority"])
    full_scale = _mapping(report["full_scale"])
    faults = _mapping(report["faults"])
    route_structure = _mapping(report["route_structure"])
    claims = _mapping(report["claims"])
    storage = _mapping(report["storage"])
    assert report["status"] == "passed"
    assert authority["m12_result_count"] == 1
    assert isinstance(full_scale["selected_scene_jobs"], int)
    assert full_scale["selected_scene_jobs"] >= 1
    assert isinstance(full_scale["initial_max_batch_items"], int)
    assert full_scale["initial_max_batch_items"] > 1
    assert full_scale["replay_simulated_calls"] == 0
    assert full_scale["replay_provider_calls"] == 0
    assert faults == {
        "batch_refusal_split": True,
        "cancellation_preserved_scene_artifacts": faults[
            "cancellation_preserved_scene_artifacts"
        ],
        "content_refusal_recovered": True,
        "malformed_item_retried": True,
        "partial_claim_artifact_published": True,
        "prior_identity_cache_survived": True,
        "provider_identity_invalidation_called": True,
        "transient_item_retried": True,
        "valid_prior_artifacts_preserved": True,
    }
    cancellation_count = faults["cancellation_preserved_scene_artifacts"]
    assert isinstance(cancellation_count, int)
    assert cancellation_count > 0
    assert route_structure["mutually_exclusive_routes_flattened"] is False
    assert claims["all_factual_claims_have_owned_evidence"] is True
    assert claims["unknown_or_out_of_scope_references"] == 0
    assert storage["approximately_linear_growth"] is True
    assert storage["raw_debug_payloads_persisted"] is False
    assert report["safety"] == {
        "creator_code_executions": 0,
        "network_requests": 0,
        "subprocess_executions": 0,
        "remote_provider_calls": 0,
        "renpy_or_game_executed": False,
        "runtime_tracing_executed": False,
        "private_paths_recorded": False,
        "working_project_retained": False,
    }
    assert {path.name for path in output.iterdir()} == {"acceptance.json"}
    encoded = (output / "acceptance.json").read_text(encoding="utf-8")
    assert json.loads(encoded) == report
    assert str(baseline) not in encoded
    assert str(story) not in encoded
    assert baseline.name not in encoded
    assert story.name not in encoded
    assert before == {path: _fingerprint(path) for path in (baseline, story)}


def test_provider_free_harness_rejects_output_beside_private_inputs(
    tmp_path: Path,
) -> None:
    baseline, story, _output = _accepted_private_shape(tmp_path)

    with pytest.raises(ValueError, match="isolated"):
        run(
            baseline_path=baseline,
            source_path=story,
            output_path=baseline.parent / "unsafe-output",
        )
