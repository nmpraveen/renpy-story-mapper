from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from renpy_story_mapper.m12_model import DestinationKind
from renpy_story_mapper.m12_persistence import RouteCacheState
from renpy_story_mapper.m12_service import M12RouteService, load_m12_authority
from renpy_story_mapper.project import Project, create_ingested_project, refresh_ingested_project

FIXTURE = Path(__file__).parent / "fixtures" / "m12" / "route_targets.rpy"


def _project(tmp_path: Path) -> tuple[Project, Path]:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    return create_ingested_project(tmp_path / "routes.rsmproj", source), source


def _reachable_scene_target(service: M12RouteService) -> tuple[str, str]:
    page = service.destinations(query="Foyer", limit=50)
    target = next(item for item in page["nodes"] if item["kind"] == "generic_scene")
    return str(target["kind"]), str(target["target_id"])


def test_destination_catalog_uses_current_m10_m11_authority_and_is_searchable(
    tmp_path: Path,
) -> None:
    fixture_hash = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    project, _source = _project(tmp_path)
    with project:
        service = M12RouteService(project)
        authority = load_m12_authority(project)
        page = service.destinations(limit=50)

        assert page["canonical_hash"] == authority.graph.authority_hash
        assert page["scene_model_hash"] == authority.scene_model.structural_hash
        kinds = {item["kind"] for item in page["nodes"]}
        assert {
            DestinationKind.GENERIC_SCENE.value,
            DestinationKind.EXACT_OCCURRENCE.value,
            DestinationKind.TEMPORARY_OUTCOME.value,
            DestinationKind.PERSISTENT_LANE.value,
            DestinationKind.TERMINAL.value,
            DestinationKind.REPEATABLE_EVENT.value,
        } <= kinds
        selected = page["nodes"][0]
        searched = service.destinations(query=str(selected["target_id"]), limit=50)
        assert [item["target_id"] for item in searched["nodes"]] == [selected["target_id"]]

    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == fixture_hash


def test_real_project_solve_publishes_once_and_reuses_exact_cache(tmp_path: Path) -> None:
    project, _source = _project(tmp_path)
    with project:
        service = M12RouteService(project)
        kind, target_id = _reachable_scene_target(service)
        prepared = service.prepare(kind, target_id)
        first = service.solve(prepared)
        second = service.solve(prepared)

        assert first.result is not None
        assert first.publication is not None
        assert not first.cached
        assert second.cached
        assert second.result == first.result
        assert second.result["request_identity"] == prepared.request.identity
        assert second.result["status"] == "confirmed"
        assert second.result["complete"] is True
        assert second.result["budget_usage"]["limiting_dimension"] is None
        assert service.lookup_identity(prepared.identity).state is RouteCacheState.HIT
        recommended = second.result["recommended"]
        assert isinstance(recommended, dict)
        assert recommended["scene_ids"]
        assert recommended["instructions"]
        assert recommended["provenance"]["node_ids"]


def test_cancel_and_emergency_abort_publish_no_result_or_cache_entry(tmp_path: Path) -> None:
    project, _source = _project(tmp_path)
    with project:
        service = M12RouteService(project)
        page = service.destinations(limit=50)
        targets = [item for item in page["nodes"] if item["kind"] == "generic_scene"]
        assert len(targets) >= 2
        cancelled = service.prepare(str(targets[0]["kind"]), str(targets[0]["target_id"]))
        aborted = service.prepare(str(targets[1]["kind"]), str(targets[1]["target_id"]))

        cancelled_outcome = service.solve(cancelled, cancelled=lambda: True)
        aborted_outcome = service.solve(aborted, emergency_seconds=1e-12)

        assert cancelled_outcome.result is None
        assert cancelled_outcome.diagnostic is not None
        assert cancelled_outcome.diagnostic.status.value == "cancelled"
        assert aborted_outcome.result is None
        assert aborted_outcome.diagnostic is not None
        assert aborted_outcome.diagnostic.status.value == "emergency_abort"
        assert service.lookup(cancelled).state is RouteCacheState.MISS
        assert service.lookup(aborted).state is RouteCacheState.MISS


def test_real_project_route_uses_visible_literal_choice_caption(tmp_path: Path) -> None:
    project, _source = _project(tmp_path)
    with project:
        service = M12RouteService(project)
        page = service.destinations(query="Courtyard", limit=50)
        destination = next(item for item in page["nodes"] if item["kind"] == "generic_scene")
        outcome = service.solve(
            service.prepare(str(destination["kind"]), str(destination["target_id"]))
        )

        assert outcome.result is not None
        recommended = outcome.result["recommended"]
        assert isinstance(recommended, dict)
        assert recommended["visible_choices"] == ["Practice first"]
        choice_instructions = [
            item["text"] for item in recommended["instructions"] if item["kind"] == "choice"
        ]
        assert choice_instructions == ['Choose "Practice first".']


def test_old_identity_is_rejected_after_current_authority_changes(tmp_path: Path) -> None:
    project, source = _project(tmp_path)
    project_path = project.path
    with project:
        service = M12RouteService(project)
        kind, target_id = _reachable_scene_target(service)
        prepared = service.prepare(kind, target_id)

    story = source / "story.rpy"
    story.write_text(story.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    refresh_ingested_project(project_path, source)
    with Project.open(project_path) as reopened, pytest.raises(ValueError, match="stale"):
        M12RouteService(reopened).lookup_identity(prepared.identity)
