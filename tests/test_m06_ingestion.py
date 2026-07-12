from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ingestion_fixtures import make_modern_rpyc, make_rpa
from renpy_story_mapper import storage
from renpy_story_mapper.ingestion import (
    IngestionOptions,
    InputKind,
    ingest_input,
    inspect_input,
)
from renpy_story_mapper.ingestion.errors import (
    AmbiguousSourceError,
    IngestionError,
    RecoveryError,
    RecoveryTimeoutError,
    UnsafeExportError,
)
from renpy_story_mapper.ingestion.export import export_recovered_sources
from renpy_story_mapper.ingestion.runtime import (
    UNRPYC_BUNDLE_FILES,
    UNRPYC_BUNDLE_SHA256,
    verify_runtime_bundle,
)
from renpy_story_mapper.project import Project
from renpy_story_mapper.project_analysis import create_input_project


def options(tmp_path: Path, **values: object) -> IngestionOptions:
    cache = tmp_path.parents[2] / "m06-recovery-caches" / hashlib.sha256(
        str(tmp_path).encode()
    ).hexdigest()
    return IngestionOptions(cache_root=cache, **values)  # type: ignore[arg-type]


def test_discovery_accepts_parent_game_folder_direct_source_archive_and_project(
    tmp_path: Path,
) -> None:
    game = tmp_path / "release" / "game"
    game.mkdir(parents=True)
    source = game / "script.rpy"
    source.write_text("label start:\n    return\n", encoding="utf-8")
    folder = inspect_input(game.parent, options(tmp_path))
    assert folder.input_kind is InputKind.GAME_FOLDER
    assert folder.source_root == game
    assert folder.selected[0].logical_path == "game/script.rpy"
    assert inspect_input(source, options(tmp_path)).input_kind is InputKind.SOURCE_FILE

    archive = make_rpa(tmp_path / "scripts.rpa", {"game/archived.rpy": b"label a:\n"})
    assert inspect_input(archive, options(tmp_path)).input_kind is InputKind.ARCHIVE

    project_path = tmp_path / "existing.rsmproj"
    with Project.create(project_path):
        pass
    project = inspect_input(project_path, options(tmp_path))
    assert project.input_kind is InputKind.PROJECT
    assert project.existing_project == project_path
    assert ingest_input(project_path, options(tmp_path)).sources == ()


def test_four_tier_precedence_mixed_sources_and_identical_dedupe(tmp_path: Path) -> None:
    game = tmp_path / "game"
    game.mkdir()
    loose_original = b"label loose:\n    return\n"
    (game / "route.rpy").write_bytes(loose_original)
    (game / "loose_compiled.rpyc").write_bytes(make_modern_rpyc(label_name="loose_compiled"))
    archived_compiled = make_modern_rpyc(label_name="archived_compiled")
    make_rpa(
        game / "one.rpa",
        {
            "game/route.rpy": b"label lower_priority:\n",
            "game/route.rpyc": make_modern_rpyc(),
            "game/archived_original.rpy": b"label archived_original:\n    return\n",
            "game/archived_compiled.rpyc": archived_compiled,
            "game/deduped.rpy": b"label deduped:\n",
        },
    )
    make_rpa(game / "two.rpa", {"game/deduped.rpy": b"label deduped:\n"})
    plan = inspect_input(game, options(tmp_path))
    selected = {item.logical_path: item.tier.value for item in plan.selected}
    assert selected == {
        "game/archived_compiled.rpyc": "archived_recovered_rpyc",
        "game/archived_original.rpy": "archived_original_rpy",
        "game/deduped.rpy": "archived_original_rpy",
        "game/loose_compiled.rpyc": "loose_recovered_rpyc",
        "game/route.rpy": "loose_original_rpy",
    }
    result = ingest_input(game, options(tmp_path))
    contents = result.content_by_path
    assert contents["game/route.rpy"] == loose_original
    assert b"label loose_compiled:" in contents["game/loose_compiled.rpy"]
    assert b"label archived_compiled:" in contents["game/archived_compiled.rpy"]


def test_conflicting_same_tier_fails_as_ambiguous(tmp_path: Path) -> None:
    game = tmp_path / "game"
    game.mkdir()
    make_rpa(game / "one.rpa", {"game/route.rpy": b"label one:\n"})
    make_rpa(game / "two.rpa", {"game/route.rpy": b"label two:\n"})
    with pytest.raises(AmbiguousSourceError, match="conflicting same-tier"):
        inspect_input(game, options(tmp_path))


def test_recovery_cache_provenance_bounds_and_input_immutability(tmp_path: Path) -> None:
    compiled = tmp_path / "script.rpyc"
    compiled.write_bytes(make_modern_rpyc())
    before = (compiled.read_bytes(), compiled.stat().st_mtime_ns)
    first = ingest_input(compiled, options(tmp_path))
    second = ingest_input(compiled, options(tmp_path))
    provenance = first.sources[0].provenance
    assert provenance.source_kind == "reconstructed"
    assert provenance.line_basis == "reconstructed_unrpyc_output_v1"
    assert provenance.input_sha256 == hashlib.sha256(before[0]).hexdigest()
    assert provenance.output_sha256 == hashlib.sha256(first.sources[0].content).hexdigest()
    assert provenance.tool_bundle_sha256 == UNRPYC_BUNDLE_SHA256
    assert not provenance.cache_hit
    assert second.sources[0].provenance.cache_hit
    assert (compiled.read_bytes(), compiled.stat().st_mtime_ns) == before

    with pytest.raises(RecoveryError, match="output"):
        ingest_input(compiled, options(tmp_path / "small", max_output_bytes=8))


def test_unsupported_malformed_timeout_cancellation_and_partial_coverage(tmp_path: Path) -> None:
    ancient = tmp_path / "ancient.rpyc"
    ancient.write_bytes(b"not-modern")
    with pytest.raises(RecoveryError, match="only modern RENPY RPC2"):
        ingest_input(ancient, options(tmp_path))

    modern = tmp_path / "modern.rpyc"
    modern.write_bytes(make_modern_rpyc())
    with pytest.raises(IngestionError, match="cache must be outside"):
        ingest_input(modern, IngestionOptions(cache_root=tmp_path / "unsafe-cache"))
    with pytest.raises(RecoveryTimeoutError):
        ingest_input(modern, options(tmp_path / "timeout", recovery_timeout_seconds=0.0))
    with pytest.raises(storage.ProjectOperationCancelled):
        ingest_input(modern, options(tmp_path), lambda: True)

    game = tmp_path / "partial" / "game"
    game.mkdir(parents=True)
    (game / "good.rpyc").write_bytes(make_modern_rpyc())
    (game / "bad.rpyc").write_bytes(b"bad")
    partial = ingest_input(game, options(tmp_path / "partial-cache", allow_partial_recovery=True))
    assert not partial.complete
    assert partial.ai_transmission_blocked
    assert [source.path for source in partial.sources] == ["game/good.rpy"]
    assert partial.recovery_failures[0].logical_path == "game/bad.rpyc"
    assert any("incomplete" in warning.lower() for warning in partial.warnings)

    partial_project_path = tmp_path / "partial.rsmproj"
    with create_input_project(
        partial_project_path,
        game,
        options=options(tmp_path / "partial-project", allow_partial_recovery=True),
    ) as project:
        assert {item["status"] for item in project.recovery_results()} == {
            "failed",
            "recovered",
        }
        assert project.source_coverage()["ai_transmission_blocked"] is True
        project.acknowledge_incomplete_source_coverage()
        coverage = project.source_coverage()
        assert coverage["acknowledged"] is True
        assert coverage["ai_transmission_blocked"] is False
        assert coverage["warning"]


def test_export_requires_new_destination_outside_source_and_writes_manifest(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "input"
    source_root.mkdir()
    compiled = source_root / "script.rpyc"
    compiled.write_bytes(make_modern_rpyc())
    result = ingest_input(compiled, options(tmp_path))
    with pytest.raises(UnsafeExportError, match="outside"):
        export_recovered_sources(result, source_root / "export")
    destination = tmp_path / "safe-export"
    exported = export_recovered_sources(result, destination)
    manifest = json.loads((exported / "RECOVERY_PROVENANCE.json").read_text(encoding="utf-8"))
    assert "not original author source" in manifest["warning"]
    assert manifest["sources"][0]["provenance"]["line_basis"].startswith("reconstructed")
    assert (exported / "game" / "script.rpy").is_file()
    with pytest.raises(UnsafeExportError, match="must not already exist"):
        export_recovered_sources(result, destination)


def test_schema_v5_migration_and_project_provenance_contract(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.rsmproj"
    connection = storage.connect(legacy)
    storage.initialize_database(connection, target_version=4)
    connection.close()
    with Project.open(legacy) as migrated:
        assert migrated.schema_version == 5
        assert migrated.source_coverage() == {}
    assert (tmp_path / "legacy.rsmproj.pre-migrate-v4.bak").is_file()

    compiled = tmp_path / "script.rpyc"
    compiled.write_bytes(make_modern_rpyc())
    project_path = tmp_path / "story.rsmproj"
    with create_input_project(project_path, compiled, options=options(tmp_path)) as project:
        assert project.schema_version == 5
        derivation = project.source_derivations()[0]
        assert derivation["source_kind"] == "reconstructed"
        assert derivation["line_basis"] == "reconstructed_unrpyc_output_v1"
        assert project.source_coverage()["complete"] is True
        assert project.snapshot()["source_derivations"] == [derivation]


def test_runtime_pin_covers_every_shipped_vendor_file_except_pin(tmp_path: Path) -> None:
    del tmp_path
    verify_runtime_bundle()
    root = Path(__file__).parents[1] / "src/renpy_story_mapper/ingestion/_vendor/unrpyc"
    shipped = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "PIN.json" and "__pycache__" not in path.parts
    }
    assert shipped == set(UNRPYC_BUNDLE_FILES)
    pin = json.loads((root / "PIN.json").read_text(encoding="utf-8"))
    assert pin["bundle_files"] == list(UNRPYC_BUNDLE_FILES)
    assert pin["bundle_sha256"] == UNRPYC_BUNDLE_SHA256
    assert not {"translate.py", "testcasedecompiler.py", "astdump.py"} & {
        Path(item).name for item in shipped
    }
