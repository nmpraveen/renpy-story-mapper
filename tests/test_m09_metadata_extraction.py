from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ingestion_fixtures import make_modern_rpyc, make_rpa
from renpy_story_mapper import project_analysis, storage
from renpy_story_mapper.ingestion import IngestionOptions, ingest_input, inspect_input
from renpy_story_mapper.ingestion.contracts import (
    IngestionSource,
    SourceProvenance,
    SourceTier,
)
from renpy_story_mapper.ingestion.errors import IngestionError
from renpy_story_mapper.presentation import PresentationLevel, PresentationRequest
from renpy_story_mapper.project import Project
from renpy_story_mapper.project_analysis import create_input_project, refresh_input_project
from renpy_story_mapper.story_metadata import (
    StoryMetadataLimitError,
    StoryMetadataLimits,
    extract_story_metadata,
)


def _options(tmp_path: Path, **values: object) -> IngestionOptions:
    cache = tmp_path.parent / f"{tmp_path.name}-m09-cache"
    return IngestionOptions(cache_root=cache, **values)  # type: ignore[arg-type]


def _source(
    path: str, content: str, *, locator: str, reconstructed: bool = False
) -> IngestionSource:
    encoded = content.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return IngestionSource(
        path,
        encoded,
        SourceProvenance(
            source_kind="reconstructed" if reconstructed else "original",
            locator=locator,
            tier=(
                SourceTier.ARCHIVED_RECOVERED
                if reconstructed
                else SourceTier.ARCHIVED_ORIGINAL
            ),
            input_sha256=digest,
            output_sha256=digest,
            line_basis=(
                "reconstructed_unrpyc_output_v1"
                if reconstructed
                else "physical_original_source"
            ),
        ),
    )


def test_exact_extras_coexistence_quarantines_replay_and_recovers_separately(
    tmp_path: Path,
) -> None:
    game = tmp_path / "game"
    game.mkdir()
    make_rpa(
        game / "scripts.rpa",
        {"game/story.rpy": b"label start:\n    return\n"},
    )
    compiled_replay = make_modern_rpyc(label_name="primeira_memoria")
    make_rpa(
        game / "extras.rpa",
        {
            "extras/replay.rpyc": compiled_replay,
            "scripts/character_screen.rpy": b'text "Wanda LUST"\ntext "[lust]"\n',
        },
    )

    make_rpa(
        game / "images.rpa",
        {"accidental_story.rpy": b"label must_not_be_discovered:\n    return\n"},
    )
    (game / "loose_replay.rpy").write_text(
        "label loose_replay_must_not_be_discovered:\n    return\n", encoding="utf-8"
    )

    before = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in game.glob("*.rpa")
    }
    plan = inspect_input(game, _options(tmp_path))
    assert [candidate.logical_path for candidate in plan.selected] == ["game/story.rpy"]
    assert all("images.rpa" not in candidate.locator for candidate in plan.candidates)
    assert all("loose_replay" not in candidate.logical_path for candidate in plan.candidates)
    assert {candidate.logical_path for candidate in plan.secondary_candidates} == {
        "game/extras/replay.rpyc",
        "game/scripts/character_screen.rpy",
    }

    result = ingest_input(game, _options(tmp_path))
    assert [source.path for source in result.sources] == ["game/story.rpy"]
    assert b"primeira_memoria" not in b"".join(source.content for source in result.sources)
    assert b"loose_replay" not in b"".join(source.content for source in result.sources)
    secondary = {source.path: source for source in result.secondary_sources}
    assert set(secondary) == {
        "game/extras/replay.rpy",
        "game/scripts/character_screen.rpy",
    }
    replay = secondary["game/extras/replay.rpy"]
    assert b"label primeira_memoria:" in replay.content
    assert replay.provenance.source_kind == "reconstructed"
    assert replay.provenance.locator.endswith("extras.rpa!/extras/replay.rpyc")
    assert replay.provenance.line_basis == "reconstructed_unrpyc_output_v1"
    assert before == {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in game.glob("*.rpa")
    }


def test_quarantine_rule_does_not_change_direct_or_noncoexisting_archive_behavior(
    tmp_path: Path,
) -> None:
    direct = make_rpa(
        tmp_path / "extras.rpa", {"extras/replay.rpy": b"label replay:\n    return\n"}
    )
    direct_result = ingest_input(direct, _options(tmp_path))
    assert [source.path for source in direct_result.sources] == ["game/extras/replay.rpy"]
    assert direct_result.secondary_sources == ()

    game = tmp_path / "only-extras" / "game"
    game.mkdir(parents=True)
    make_rpa(game / "extras.rpa", {"extras/replay.rpy": b"label replay:\n"})
    folder_result = ingest_input(game, _options(tmp_path / "only-extras"))
    assert [source.path for source in folder_result.sources] == ["game/extras/replay.rpy"]
    assert folder_result.secondary_sources == ()

    loose_game = tmp_path / "only-loose" / "game"
    loose_game.mkdir(parents=True)
    (loose_game / "story.rpy").write_text("label loose_start:\n", encoding="utf-8")
    loose_result = ingest_input(loose_game, _options(tmp_path / "only-loose"))
    assert [source.path for source in loose_result.sources] == ["game/story.rpy"]


def test_game_folder_metadata_is_persisted_without_entering_story_graph(tmp_path: Path) -> None:
    game = tmp_path / "game"
    game.mkdir()
    (game / "loose_replay.rpy").write_text(
        "label loose_replay_memory:\n    return\n", encoding="utf-8"
    )
    make_rpa(
        game / "scripts.rpa",
        {
            "story.rpy": (
                b'define w = Character("Wanda")\n'
                b"default lust = 0\n"
                b'label start:\n    w "Hello."\n    $ lust += 1\n    return\n'
            )
        },
    )
    make_rpa(
        game / "extras.rpa",
        {
            "extras/replay.rpy": b"label replay_memory:\n    return\n",
            "scripts/character_screen.rpy": (
                b'text "Wanda LUST"\ntext "[lust]"\n'
                b'memories.append(Memory("Opening Memory", "thumb.jpg", key="start"))\n'
            ),
        },
    )
    project_path = tmp_path / "story.rsmproj"
    create_input_project(project_path, game, options=_options(tmp_path)).close()

    with Project.open(project_path) as project:
        assert {source.path for source in project.sources()} == {
            "game/story.rpy",
            "game/extras/replay.rpy",
            "game/scripts/character_screen.rpy",
        }
        graph = storage.canonical_json(project.payload("m01_graph", "authoritative"))
        assert b"replay_memory" not in graph
        assert b"loose_replay_memory" not in graph
        metadata = project.payload("story_metadata", "authoritative")
        assert isinstance(metadata, dict)
        assert {item["alias"] for item in metadata["characters"]} == {"w"}
        assert metadata["scene_titles"][0]["key"] == "start"
        scenes = project.presentation_service().view(
            PresentationRequest(PresentationLevel.OVERVIEW)
        ).nodes
        assert scenes[0].name == "Opening Memory"
        variables = {
            item.original_name: item
            for item in project.presentation_service().state_variables().items
        }
        assert variables["lust"].display_name == "Wanda LUST"
        assert variables["lust"].default_declared

    refresh = refresh_input_project(
        project_path,
        game,
        options=_options(tmp_path),
    )
    assert refresh.parsed_sources == ()


def test_metadata_limit_falls_back_without_blocking_story_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    story = tmp_path / "story.rpy"
    story.write_text("label start:\n    return\n", encoding="utf-8")

    def limited(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise StoryMetadataLimitError("bounded metadata limit")

    monkeypatch.setattr(project_analysis, "extract_story_metadata", limited)
    path = tmp_path / "story.rsmproj"
    create_input_project(path, story, options=_options(tmp_path)).close()
    with Project.open(path) as project:
        assert project.payload("m01_graph", "authoritative") is not None
        metadata = project.payload("story_metadata", "authoritative")
        assert metadata["diagnostics"][0]["code"] == "metadata_limits_exceeded"


def test_secondary_inventory_obeys_source_limit(tmp_path: Path) -> None:
    game = tmp_path / "game"
    game.mkdir()
    make_rpa(game / "scripts.rpa", {"story.rpy": b"label start:\n"})
    make_rpa(game / "extras.rpa", {"metadata.rpy": b"default points = 0\n"})
    with pytest.raises(IngestionError, match="source-count limit"):
        inspect_input(game, _options(tmp_path, max_sources=1))


def test_literal_metadata_has_deterministic_provenance_and_exact_spans(tmp_path: Path) -> None:
    del tmp_path
    canonical = _source(
        "game/characters.rpy",
        "define w = Character(_(\"Wanda\"), color=dynamic_color)\n"
        "default lust = 0\n"
        "default route_open = False\n",
        locator="scripts.rpa!/characters.rpyc",
        reconstructed=True,
    )
    secondary = _source(
        "game/scripts/character_screen.rpy",
        'text "Wanda LUST"\n'
        "# adjacent screen statements may have a comment\n"
        'text "[lust]"\n'
        'text "Gene points"\n'
        'text "[gen]"\n'
        'memories.append(Memory(_("First Memory"), "thumb.webp"))\n',
        locator="extras.rpa!/scripts/character_screen.rpy",
    )

    first = extract_story_metadata([canonical], [secondary])
    second = extract_story_metadata(tuple(reversed([canonical])), tuple(reversed([secondary])))
    assert first == second
    assert first["schema_version"] == 1
    assert first["characters"] == [
        {
            "alias": "w",
            "display_name": "Wanda",
            "source": {
                "path": "game/characters.rpy",
                "role": "canonical",
                "locator": "scripts.rpa!/characters.rpyc",
                "fingerprint": canonical.provenance.output_sha256,
                "line_basis": "reconstructed_unrpyc_output_v1",
                "span": {
                    "start": {"line": 1, "column": 1},
                    "end": {"line": 1, "column": 54},
                },
            },
        }
    ]
    default = next(hint for hint in first["state_hints"] if hint["kind"] == "default")  # type: ignore[index]
    assert default["name"] == "lust"
    assert default["default"] == 0
    assert default["source"]["role"] == "canonical"  # type: ignore[index]
    display = next(
        hint
        for hint in first["state_hints"]  # type: ignore[union-attr]
        if hint["kind"] == "display_label" and hint["name"] == "lust"
    )
    assert display["display_name"] == "Wanda LUST"
    assert display["source"]["span"] == {  # type: ignore[index]
        "start": {"line": 1, "column": 1},
        "end": {"line": 3, "column": 14},
    }
    display_variables = {
        hint["name"]
        for hint in first["state_hints"]  # type: ignore[union-attr]
        if hint["kind"] == "display_label"
    }
    assert display_variables == {"lust", "gen"}
    assert first["scene_titles"] == [
        {
            "title": "First Memory",
            "thumbnail": "thumb.webp",
            "collection": "memories",
            "source": {
                "path": "game/scripts/character_screen.rpy",
                "role": "secondary_metadata",
                "locator": "extras.rpa!/scripts/character_screen.rpy",
                "fingerprint": secondary.provenance.output_sha256,
                "line_basis": "physical_original_source",
                "span": {
                    "start": {"line": 6, "column": 1},
                    "end": {"line": 6, "column": 57},
                },
            },
        }
    ]
    assert {item["role"] for item in first["sources"]} == {  # type: ignore[index]
        "canonical",
        "secondary_metadata",
    }


def test_screen_properties_and_literal_memorias_constructor_are_supported() -> None:
    payload = extract_story_metadata(
        [
            _source(
                "game/character_screen.rpy",
                'text "Domination" xpos 150 ypos 210\n'
                'text "[wanda_dom]" xpos 360 ypos 210\n'
                '("gene", MsDenversCharacter("GENE", "profile", points=gen, '
                'trait=gene_char_trait))\n'
                'lista_memorias.append(memorias("First Memory", "thumb.jpg", "no", True))\n',
                locator="extras.rpa!/scripts/character_screen.rpyc",
            )
        ]
    )
    display = next(
        item for item in payload["state_hints"] if item["kind"] == "display_label"
    )
    assert (display["name"], display["display_name"]) == ("wanda_dom", "Domination")
    semantic = {
        item["name"]: (item["display_name"], item["category"])
        for item in payload["state_hints"]
        if item["kind"] == "semantic_label"
    }
    assert semantic == {
        "gen": ("Gene points", "relationship"),
        "gene_char_trait": ("Gene trait", "skill"),
    }
    assert payload["scene_titles"][0]["title"] == "First Memory"
    assert "key" not in payload["scene_titles"][0]


def test_scene_title_key_requires_one_nonempty_literal_keyword() -> None:
    payload = extract_story_metadata(
        [
            _source(
                "game/extras_core.rpy",
                'memories.append(Memory("Applied", "one.jpg", key="start"))\n'
                'memories.append(Memory("Dynamic", "two.jpg", key=get_key()))\n'
                'memories.append(Memory("Blank", "three.jpg", key=""))\n'
                'memories.append(Memory("Unkeyed", "four.jpg"))\n',
                locator="extras.rpa!/extras/extras_core.rpyc",
            )
        ]
    )
    titles = {item["title"]: item for item in payload["scene_titles"]}
    assert titles["Applied"]["key"] == "start"
    assert all("key" not in titles[title] for title in {"Dynamic", "Blank", "Unkeyed"})


def test_dynamic_and_malformed_constructs_are_skipped_without_execution(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    content = (
        "define unsafe = Character(get_name())\n"
        'define empty = Character("")\n'
        f'default danger = __import__("pathlib").Path({str(marker)!r}).write_text("bad")\n'
        "text make_label()\n"
        'text "[computed + 1]"\n'
        'memories.append(Memory(get_title(), "thumb.webp"))\n'
        'define broken = Character("unterminated"\n'
    )
    payload = extract_story_metadata(
        [_source("game/dynamic.rpy", content, locator="scripts.rpa!/dynamic.rpy")]
    )
    assert payload["characters"] == []
    assert payload["state_hints"] == []
    assert payload["scene_titles"] == []
    assert not marker.exists()
    codes = {item["code"] for item in payload["diagnostics"]}  # type: ignore[index]
    assert {"dynamic_character_name", "dynamic_default", "dynamic_screen_text"} <= codes
    assert "dynamic_scene_title" in codes
    assert "unsupported_character_definition" in codes


def test_repeated_metadata_is_deduplicated_and_conflicts_fail_closed() -> None:
    payload = extract_story_metadata(
        [
            _source(
                "game/characters.rpy",
                'define w = Character("Wanda")\ndefine x = Character("One")\n',
                locator="scripts.rpa!/characters.rpy",
            ),
            _source(
                "game/more_characters.rpy",
                'define w = Character("Wanda")\ndefine x = Character("Two")\n',
                locator="scripts.rpa!/more_characters.rpy",
            ),
        ]
    )
    assert [(item["alias"], item["display_name"]) for item in payload["characters"]] == [
        ("w", "Wanda")
    ]
    assert any(
        item["code"] == "ambiguous_character_alias" for item in payload["diagnostics"]
    )


def test_extractor_limits_cancellation_invalid_utf8_and_bounded_diagnostics() -> None:
    noisy = _source(
        "game/noisy.rpy",
        "\n".join(f"default value_{index} = dynamic()" for index in range(10)),
        locator="scripts.rpa!/noisy.rpy",
    )
    bounded = extract_story_metadata(
        [noisy], limits=StoryMetadataLimits(max_diagnostics=2)
    )
    diagnostics = bounded["diagnostics"]
    assert len(diagnostics) == 2  # type: ignore[arg-type]
    assert any(item["code"] == "diagnostics_truncated" for item in diagnostics)  # type: ignore[union-attr]

    literal = _source(
        "game/literals.rpy",
        "default one = 1\ndefault two = 2\n",
        locator="scripts.rpa!/literals.rpy",
    )
    with pytest.raises(StoryMetadataLimitError, match="record count"):
        extract_story_metadata([literal], limits=StoryMetadataLimits(max_records=1))
    with pytest.raises(StoryMetadataLimitError, match="byte limit"):
        extract_story_metadata([literal], limits=StoryMetadataLimits(max_source_bytes=4))

    invalid = IngestionSource(
        "game/invalid.rpy",
        b"\xff",
        literal.provenance,
    )
    invalid_payload = extract_story_metadata([invalid])
    assert invalid_payload["diagnostics"][0]["code"] == "invalid_utf8"  # type: ignore[index]

    with pytest.raises(storage.ProjectOperationCancelled):
        extract_story_metadata([literal], cancel_check=lambda: True)
