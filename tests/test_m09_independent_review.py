from __future__ import annotations

from pathlib import Path

from ingestion_fixtures import make_rpa
from renpy_story_mapper import storage
from renpy_story_mapper.ingestion import IngestionOptions
from renpy_story_mapper.project import Project, create_project
from renpy_story_mapper.project_analysis import create_input_project, persist_story_metadata


def _metadata_source(path: str) -> dict[str, object]:
    return {
        "path": path,
        "role": "secondary_metadata",
        "locator": f"extras.rpa!/{path}",
        "fingerprint": "a" * 64,
        "line_basis": "physical_original_source",
        "span": {
            "start": {"line": 1, "column": 1},
            "end": {"line": 1, "column": 20},
        },
    }


def _state_metadata() -> dict[str, object]:
    source = _metadata_source("scripts/character_screen.rpy")
    return {
        "schema_version": 1,
        "characters": [],
        "state_hints": [
            {
                "name": "lust",
                "kind": "display_label",
                "display_name": "Wanda LUST",
                "source": source,
            }
        ],
        "scene_titles": [],
        "sources": [{key: value for key, value in source.items() if key != "span"}],
        "diagnostics": [],
    }


def test_scripts_archive_remains_exact_story_authority_when_loose_replay_exists(
    tmp_path: Path,
) -> None:
    game = tmp_path / "game"
    game.mkdir()
    make_rpa(game / "scripts.rpa", {"story.rpy": b"label start:\n    return\n"})
    (game / "loose_replay.rpy").write_text(
        "label primeira_memoria:\n    return\n", encoding="utf-8"
    )

    project_path = tmp_path / "story.rsmproj"
    options = IngestionOptions(cache_root=tmp_path / "recovery-cache")
    create_input_project(project_path, game, options=options).close()

    with Project.open(project_path) as project:
        graph = storage.canonical_json(project.payload("m01_graph", "authoritative"))
        assert b"primeira_memoria" not in graph
        assert {source.path for source in project.sources()} == {"game/story.rpy"}


def test_user_state_override_immediately_replaces_metadata_in_facts_and_search(
    tmp_path: Path,
) -> None:
    game = tmp_path / "game"
    game.mkdir()
    (game / "story.rpy").write_text(
        "label start:\n    $ lust += 1\n    return\n", encoding="utf-8"
    )
    project_path = tmp_path / "story.rsmproj"
    create_project(project_path, game).close()

    with Project.open(project_path) as project:
        persist_story_metadata(project, _state_metadata(), source_paths=("story.rpy",))
        assert project.presentation_service().search(
            "Wanda LUST", fields=("variable_display_name",)
        ).items

        project.update_state_variable(
            "lust", display_name="My Lust", category="custom_relationship"
        )

        facts = project.presentation_service().facts(variable="lust").items
        assert facts and facts[0].variable_display_name == "My Lust"
        assert project.presentation_service().search(
            "My Lust", fields=("variable_display_name",)
        ).items
        assert not project.presentation_service().search(
            "Wanda LUST", fields=("variable_display_name",)
        ).items
