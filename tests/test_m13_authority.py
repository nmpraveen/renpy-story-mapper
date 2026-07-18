from __future__ import annotations

import hashlib
from pathlib import Path

from renpy_story_mapper.m12_service import M12RouteService
from renpy_story_mapper.narrative.authority import load_narrative_authority
from renpy_story_mapper.project import PayloadRecord, Project, create_ingested_project
from renpy_story_mapper.storage import canonical_json

FIXTURE = Path(__file__).parent / "fixtures" / "m12" / "route_targets.rpy"


def _project(tmp_path: Path) -> Project:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    return create_ingested_project(tmp_path / "m13-authority.rsmproj", source)


def test_current_authority_load_is_read_only_and_m12_is_explicit(tmp_path: Path) -> None:
    with _project(tmp_path) as project:
        m10_before = canonical_json(project.payload("m10_canonical_graph", "authoritative"))
        m11_before = canonical_json(project.payload("m11_analysis_state", "authoritative"))
        without_routes = load_narrative_authority(project, include_m12=False)

        assert without_routes.m12_results == ()
        assert without_routes.m12_coverage.selected == 0
        assert without_routes.binding.canonical_hash == hashlib.sha256(m10_before).hexdigest()
        assert without_routes.binding.scene_hash
        assert without_routes.binding.source_archive_hash
        assert canonical_json(project.payload("m10_canonical_graph", "authoritative")) == m10_before
        assert canonical_json(project.payload("m11_analysis_state", "authoritative")) == m11_before

        route_service = M12RouteService(project)
        nodes = route_service.destinations(limit=50)["nodes"]
        assert isinstance(nodes, list)
        destination = next(
            item
            for item in nodes
            if isinstance(item, dict)
            if item["kind"] == "generic_scene"
        )
        outcome = route_service.solve(
            route_service.prepare(str(destination["kind"]), str(destination["target_id"]))
        )
        assert outcome.result is not None
        m12_before = canonical_json(outcome.result)

        with_routes = load_narrative_authority(project, include_m12=True)

        assert with_routes.m12_coverage.selected == 1
        assert with_routes.m12_coverage.invalid == 0
        assert with_routes.m12_results[0]["status"] == outcome.result["status"]
        assert canonical_json(with_routes.m12_results[0]) == m12_before
        assert (
            with_routes.binding.source_archive_hash
            == without_routes.binding.source_archive_hash
        )
        assert canonical_json(project.payload("m10_canonical_graph", "authoritative")) == m10_before
        assert canonical_json(project.payload("m11_analysis_state", "authoritative")) == m11_before


def test_invalid_m12_entry_is_coverage_not_published_authority(tmp_path: Path) -> None:
    with _project(tmp_path) as project:
        project.write_payloads(
            (
                PayloadRecord(
                    "m12_route_results",
                    "route:invalid",
                    {"schema": "invalid-m12-envelope"},
                ),
            )
        )

        authority = load_narrative_authority(project, include_m12=True)

        assert authority.m12_results == ()
        assert authority.m12_coverage.selected == 0
        assert authority.m12_coverage.invalid == 1
        assert authority.m12_coverage.complete is False
