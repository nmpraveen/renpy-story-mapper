from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ingestion_fixtures import make_modern_rpyc, make_rpa
from renpy_story_mapper import storage
from renpy_story_mapper.ingestion import IngestionOptions, ingest_input, inspect_input
from renpy_story_mapper.ingestion.contracts import (
    IngestionSource,
    SourceProvenance,
    SourceTier,
)
from renpy_story_mapper.ingestion.errors import IngestionError
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

    before = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in game.glob("*.rpa")
    }
    plan = inspect_input(game, _options(tmp_path))
    assert [candidate.logical_path for candidate in plan.selected] == ["game/story.rpy"]
    assert {candidate.logical_path for candidate in plan.secondary_candidates} == {
        "game/extras/replay.rpyc",
        "game/scripts/character_screen.rpy",
    }

    result = ingest_input(game, _options(tmp_path))
    assert [source.path for source in result.sources] == ["game/story.rpy"]
    assert b"primeira_memoria" not in b"".join(source.content for source in result.sources)
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


def test_dynamic_and_malformed_constructs_are_skipped_without_execution(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    content = (
        "define unsafe = Character(get_name())\n"
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
    assert "scene_titles" not in payload
    assert not marker.exists()
    codes = {item["code"] for item in payload["diagnostics"]}  # type: ignore[index]
    assert {"dynamic_character_name", "dynamic_default", "dynamic_screen_text"} <= codes
    assert "dynamic_scene_title" in codes
    assert "unsupported_character_definition" in codes


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
