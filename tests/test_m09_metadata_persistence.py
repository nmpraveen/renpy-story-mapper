from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from renpy_story_mapper.presentation import PresentationLevel, PresentationRequest
from renpy_story_mapper.project import (
    PayloadRecord,
    Project,
    SourceFingerprint,
    create_project,
    refresh_project,
)
from renpy_story_mapper.project_analysis import persist_story_metadata
from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.contracts import M07_API_ROUTES


def _project(tmp_path: Path) -> Path:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_text(
        '''label start:
    w "Hello."
    $ lust += 1
    return
''',
        encoding="utf-8",
    )
    path = tmp_path / "story.rsmproj"
    create_project(path, source).close()
    return path


def _metadata(*, lust_name: str = "Wanda LUST") -> dict[str, object]:
    def source(path: str) -> dict[str, object]:
        return {
            "path": path,
            "role": "canonical",
            "locator": path,
            "fingerprint": "a" * 64,
            "line_basis": "reconstructed_source",
            "span": {
                "start": {"line": 1, "column": 1},
                "end": {"line": 1, "column": 10},
            },
        }

    return {
        "schema_version": 1,
        "characters": [
            {"alias": "w", "display_name": "Wanda", "source": source("characters.rpy")}
        ],
        "state_hints": [
            {
                "name": "lust",
                "kind": "default",
                "default": 0,
                "source": source("wanda_attributes.rpy"),
            },
            {
                "name": "lust",
                "kind": "display_label",
                "display_name": lust_name,
                "source": source("character_screen.rpy"),
            },
            {
                "name": "gen",
                "kind": "default",
                "default": 0,
                "source": source("wanda_attributes.rpy"),
            },
            {
                "name": "gen",
                "kind": "display_label",
                "display_name": "Gene points",
                "source": source("character_screen.rpy"),
            },
        ],
        "scene_titles": [
            {
                "key": "start",
                "title": "Opening Memory",
                "collection": "memories",
                "source": source("extras_core.rpy"),
            }
        ],
        "sources": [
            {key: value for key, value in source(path).items() if key != "span"}
            for path in ("characters.rpy", "wanda_attributes.rpy", "extras_core.rpy")
        ],
        "diagnostics": [],
    }


def test_metadata_persists_without_changing_graph_authority_and_enriches_surfaces(
    tmp_path: Path,
) -> None:
    path = _project(tmp_path)
    with Project.open(path) as project:
        connection = project._require_open()
        authority_hashes = tuple(
            connection.execute(
                """SELECT collection,payload_hash FROM payloads
                   WHERE collection IN ('m01_graph','m02_semantic')
                   ORDER BY collection"""
            ).fetchall()
        )
        assert persist_story_metadata(project, _metadata(), source_paths=("story.rpy",))
        before_noop = tuple(
            connection.execute(
                """SELECT collection,record_key,payload_hash,updated_utc FROM payloads
                   WHERE collection IN ('story_metadata','state_registry')
                   ORDER BY collection,record_key"""
            ).fetchall()
        )
        generation = connection.execute(
            "SELECT generation FROM presentation_index_state WHERE singleton=1"
        ).fetchone()[0]
        assert not persist_story_metadata(project, _metadata(), source_paths=("story.rpy",))
        assert tuple(
            connection.execute(
                """SELECT collection,record_key,payload_hash,updated_utc FROM payloads
                   WHERE collection IN ('story_metadata','state_registry')
                   ORDER BY collection,record_key"""
            ).fetchall()
        ) == before_noop
        assert connection.execute(
            "SELECT generation FROM presentation_index_state WHERE singleton=1"
        ).fetchone()[0] == generation
        assert tuple(
            connection.execute(
                """SELECT collection,payload_hash FROM payloads
                   WHERE collection IN ('m01_graph','m02_semantic')
                   ORDER BY collection"""
            ).fetchall()
        ) == authority_hashes

    with Project.open(path) as reopened:
        assert reopened.payload("story_metadata", "authoritative") == _metadata()
        service = reopened.presentation_service()
        scenes = service.view(PresentationRequest(PresentationLevel.OVERVIEW)).nodes
        assert scenes[0].name == "Opening Memory"
        events = service.view(
            PresentationRequest(PresentationLevel.EVENT, parent_ids=(scenes[0].id,))
        ).nodes
        beats = service.view(
            PresentationRequest(PresentationLevel.EVIDENCE, parent_ids=(events[0].id,))
        ).nodes
        narrative = next(node for node in beats if node.kind == "narrative")
        assert narrative.payload["content"][0]["speaker_display_name"] == "Wanda"  # type: ignore[index]
        assert service.search("Wanda", fields=("character",)).items
        assert service.search("Wanda LUST", fields=("variable_display_name",)).items
        variables = {item.original_name: item for item in service.state_variables().items}  # type: ignore[attr-defined]
        assert variables["lust"].display_name == "Wanda LUST"
        assert variables["lust"].default_declared is True
        assert variables["lust"].default_value == 0
        assert variables["gen"].display_name == "Gene points"
        fact = service.facts(variable="lust").items[0]
        assert fact.variable_display_name == "Wanda LUST"  # type: ignore[attr-defined]


def test_user_override_wins_refresh_and_removed_metadata_is_reversible(tmp_path: Path) -> None:
    path = _project(tmp_path)
    with Project.open(path) as project:
        persist_story_metadata(project, _metadata(), source_paths=("story.rpy",))
        project.update_state_variable(
            "lust", display_name="My Lust", category="custom_relationship"
        )

    refresh_project(path, tmp_path / "game")
    changed = _metadata(lust_name="Replacement")
    changed["state_hints"] = changed["state_hints"][:2]  # type: ignore[index]
    with Project.open(path) as project:
        persist_story_metadata(project, changed, source_paths=("story.rpy",))
        state_page = project.presentation_service().state_variables()
        values = {
            item.original_name: item
            for item in state_page.items  # type: ignore[attr-defined]
        }
        assert values["lust"].display_name == "My Lust"
        assert values["lust"].category == "custom_relationship"
        assert values["lust"].user_override is True
        assert "gen" not in values


def test_opening_metadata_project_in_browser_is_provider_free(tmp_path: Path) -> None:
    path = _project(tmp_path)
    with Project.open(path) as project:
        persist_story_metadata(project, _metadata(), source_paths=("story.rpy",))
        route = project.payload("m07_route_map", "authoritative")
        effects = project.payload("effects", "story.rpy")
        assert isinstance(route, dict) and isinstance(effects, list) and effects
        assert isinstance(route["edges"], list) and route["edges"]
        route["edges"][0]["effect_ids"] = [effects[0]["id"]]
        project.write_payloads(
            (PayloadRecord("m07_route_map", "authoritative", route, ("story.rpy",)),)
        )
        authority_hash = project._require_open().execute(
            """SELECT payload_hash FROM payloads
               WHERE collection='m07_route_map' AND record_key='authoritative'"""
        ).fetchone()[0]

    provider_calls: list[object] = []

    def forbidden_provider(scope: object) -> Any:
        provider_calls.append(scope)
        raise AssertionError("project opening must not construct a provider")

    api = ProjectApi(_NoDialogs(), m07_provider_factory=forbidden_provider)
    api._project_path = path
    try:
        page = api.dispatch("POST", M07_API_ROUTES["route_map"], {"limit": 30})
        assert isinstance(page, dict)
        titled = next(item for item in page["nodes"] if item.get("scene_title_key") == "start")
        assert titled["title"] == "Opening Memory"

        details = [
            api.dispatch("POST", M07_API_ROUTES["detail"], {"element_id": item["id"]})
            for item in [*page["nodes"], *page["edges"]]
        ]
    finally:
        api.close()
    dialogue = [record for detail in details for record in detail.get("dialogue", [])]
    facts = [
        record
        for detail in details
        for collection in ("gates", "effects", "facts")
        for record in detail.get(collection, [])
    ]
    assert any(record["speaker_display_name"] == "Wanda" for record in dialogue)
    assert any(record["variable_display_name"] == "Wanda LUST" for record in facts)
    assert provider_calls == []
    with Project.open(path) as project:
        assert project._require_open().execute(
            """SELECT payload_hash FROM payloads
               WHERE collection='m07_route_map' AND record_key='authoritative'"""
        ).fetchone()[0] == authority_hash


def test_packaged_browser_consumes_metadata_display_fields() -> None:
    app = (
        Path(__file__).parents[1] / "src" / "renpy_story_mapper" / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")

    assert "item.speaker_display_name && item.text" in app
    assert "item.variable_display_name" in app
    assert 'addFactGroup(facts, "Dialogue", detail.dialogue, "dialogue")' in app


def test_browser_scene_title_is_fail_closed_for_duplicate_keys(tmp_path: Path) -> None:
    path = _project(tmp_path)
    metadata = _metadata()
    first = metadata["scene_titles"][0]  # type: ignore[index]
    metadata["scene_titles"] = [first, {**first, "title": "Second Memory"}]
    with Project.open(path) as project:
        project.write_payloads(
            (PayloadRecord("story_metadata", "authoritative", metadata, ("story.rpy",)),)
        )
        control = project.payload("m06_control_flow", "authoritative")
        route = project.payload("m07_route_map", "authoritative")
        assert isinstance(control, dict) and isinstance(route, dict)
        start_control_id = next(
            item["id"]
            for item in control["nodes"]
            if item.get("kind") == "label" and item.get("label") == "start"
        )
        expected = next(
            item["title"] for item in route["nodes"] if item["control_node_id"] == start_control_id
        )

    api = ProjectApi(_NoDialogs(), m07_provider_factory=lambda _scope: None)  # type: ignore[arg-type]
    api._project_path = path
    try:
        page = api.dispatch("POST", M07_API_ROUTES["route_map"], {"limit": 30})
    finally:
        api.close()
    node = next(item for item in page["nodes"] if item["control_node_id"] == start_control_id)
    assert node["title"] == expected
    assert "scene_title_key" not in node


def test_changed_metadata_dependency_invalidates_only_advisory_payload(tmp_path: Path) -> None:
    path = _project(tmp_path)
    with Project.open(path) as project:
        metadata_source = SourceFingerprint.from_bytes("metadata.bin", b"one")
        project.refresh_sources((*project.sources(), metadata_source))
        graph = project.payload("m01_graph", "authoritative")
        persist_story_metadata(project, _metadata(), source_paths=("metadata.bin",))
        project.update_state_variable("lust", display_name="My Lust")

        changed_source = SourceFingerprint.from_bytes("metadata.bin", b"two")
        retained = tuple(source for source in project.sources() if source.path != "metadata.bin")
        refresh = project.refresh_sources((*retained, changed_source))

        assert refresh.invalidated_payloads == 1
        assert project.payload("story_metadata", "authoritative") is None
        assert project.payload("m01_graph", "authoritative") == graph
        variables = project.payload("state_registry", "authoritative")
        assert isinstance(variables, list)
        lust = next(item for item in variables if item["original_name"] == "lust")
        assert lust["display_name"] == "My Lust"
        assert lust["user_override"] is True


def test_metadata_validation_is_narrow_and_fail_closed(tmp_path: Path) -> None:
    path = _project(tmp_path)
    invalid = _metadata()
    source = invalid["characters"][0]["source"]  # type: ignore[index]
    invalid["characters"] = [
        {"alias": "w", "display_name": "Wanda", "source": source},
        {"alias": "w", "display_name": "Other", "source": source},
    ]
    with Project.open(path) as project:
        with pytest.raises(ValueError, match="duplicate alias"):
            persist_story_metadata(project, invalid, source_paths=("story.rpy",))
        assert project.payload("story_metadata", "authoritative") is None


class _NoDialogs:
    def choose_source(self, _kind: str) -> None:
        return None

    def choose_open_project(self) -> None:
        return None

    def choose_save_project(self) -> None:
        return None
