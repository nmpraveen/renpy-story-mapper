from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from renpy_story_mapper import storage
from renpy_story_mapper.project import PayloadRecord, Project, SourceFingerprint


def source(path: str, text: str) -> SourceFingerprint:
    return SourceFingerprint.from_bytes(path, text.encode("utf-8"))


def test_create_reopen_and_canonical_round_trip_all_authoritative_payloads(tmp_path: Path) -> None:
    path = tmp_path / "story.rsmp"
    first = source("game/start.rpy", "label start:\n    return\n")
    second = source("game/routes.rpy", "label route:\n    return\n")
    payloads = {
        "m01_graph": {"schema_version": 1, "nodes": [{"id": "node-a"}], "edges": []},
        "m02_semantic": {"schema_version": 1, "scenes": [{"id": "scene-a"}]},
        "diagnostics": [{"severity": "warning", "message": "example"}],
        "unresolved": [{"id": "u1", "reason": "dynamic_expression"}],
        "gates": [{"expression": "wits > 0", "status": "proven", "line": 4}],
        "effects": [{"expression": "love += 1", "status": "proven", "line": 5}],
        "state_registry": [{"name": "love", "display_name": "Love", "category": "affection"}],
    }

    with Project.create(path, metadata={"title": "Test Story"}) as project:
        refresh = project.refresh_sources([first, second])
        assert refresh.changed == ("game/routes.rpy", "game/start.rpy")
        project.write_payloads(
            [
                PayloadRecord(collection, "authoritative", value, (first.path, second.path))
                for collection, value in payloads.items()
            ]
        )
        before = project.canonical_export()
        assert project.metadata()["title"] == "Test Story"

    with Project.open(path) as reopened:
        assert reopened.canonical_export() == before
        for collection, value in payloads.items():
            assert reopened.payload(collection, "authoritative") == value


def test_incremental_refresh_skips_unchanged_and_invalidates_only_dependents(
    tmp_path: Path,
) -> None:
    path = tmp_path / "incremental.rsmp"
    a1 = source("a.rpy", "label a:\n")
    b1 = source("b.rpy", "label b:\n")
    with Project.create(path) as project:
        project.refresh_sources([a1, b1])
        project.write_payloads(
            [
                PayloadRecord("m01_graph", "a", {"node": "a"}, ("a.rpy",)),
                PayloadRecord("m01_graph", "b", {"node": "b"}, ("b.rpy",)),
                PayloadRecord("m02_semantic", "shared", {"scene": "ab"}, ("a.rpy", "b.rpy")),
                PayloadRecord("state_registry", "global", {"name": "manual"}),
            ]
        )

        unchanged = project.refresh_sources([a1, b1])
        assert unchanged.changed == ()
        assert unchanged.unchanged == ("a.rpy", "b.rpy")
        assert unchanged.invalidated_payloads == 0

        a2 = source("a.rpy", "label a:\n    return\n")
        changed = project.refresh_sources([a2, b1])
        assert changed.changed == ("a.rpy",)
        assert changed.unchanged == ("b.rpy",)
        assert changed.invalidated_payloads == 2
        assert project.payload("m01_graph", "a") is None
        assert project.payload("m02_semantic", "shared") is None
        assert project.payload("m01_graph", "b") == {"node": "b"}
        assert project.payload("state_registry", "global") == {"name": "manual"}


def test_refresh_removes_missing_sources_and_rolls_back_on_cancellation(tmp_path: Path) -> None:
    path = tmp_path / "cancel.rsmp"
    old = source("old.rpy", "old")
    keep = source("keep.rpy", "keep")
    with Project.create(path) as project:
        project.refresh_sources([old, keep])
        project.write_payloads([PayloadRecord("diagnostics", "old", ["warning"], ("old.rpy",))])
        removed = project.refresh_sources([keep])
        assert removed.removed == ("old.rpy",)
        assert project.payload("diagnostics", "old") is None

        calls = 0

        def cancel_during_write() -> bool:
            nonlocal calls
            calls += 1
            return calls >= 3

        records = [
            PayloadRecord("effects", "one", {"value": 1}, ("keep.rpy",)),
            PayloadRecord("effects", "two", {"value": 2}, ("keep.rpy",)),
        ]
        with pytest.raises(storage.ProjectOperationCancelled):
            project.write_payloads(records, cancelled=cancel_during_write)
        assert project.payload_keys("effects") == ()


def test_schema_v1_is_backed_up_and_migrated_to_current_version(tmp_path: Path) -> None:
    path = tmp_path / "legacy.rsmp"
    connection = storage.connect(path)
    storage.initialize_database(connection, target_version=1)
    connection.close()

    with Project.open(path) as project:
        assert project.schema_version == storage.SCHEMA_VERSION
        columns = {
            str(row[1]) for row in project._require_open().execute("PRAGMA table_info(sources)")
        }
        assert "fingerprint_kind" in columns

    backup = path.with_name(f"{path.name}.pre-migrate-v1.bak")
    assert backup.is_file()
    backup_connection = storage.connect(backup)
    try:
        assert storage.validate_database(backup_connection) == 1
    finally:
        backup_connection.close()


def test_corruption_foreign_sqlite_and_future_versions_fail_safely(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.rsmp"
    corrupt.write_bytes(b"not sqlite")
    with pytest.raises(storage.ProjectCorruptError):
        Project.open(corrupt)

    foreign = tmp_path / "foreign.sqlite"
    connection = sqlite3.connect(foreign)
    connection.execute("CREATE TABLE unrelated(value TEXT)")
    connection.close()
    with pytest.raises(storage.ProjectCorruptError):
        Project.open(foreign)

    future = tmp_path / "future.rsmp"
    with Project.create(future) as project:
        project._require_open().execute(f"PRAGMA user_version = {storage.SCHEMA_VERSION + 1}")
    with pytest.raises(storage.IncompatibleProjectVersionError):
        Project.open(future)


def test_matching_header_with_missing_schema_fails_as_corrupt(tmp_path: Path) -> None:
    malformed = tmp_path / "missing-schema.rsmp"
    connection = sqlite3.connect(malformed)
    connection.execute(f"PRAGMA application_id = {storage.APPLICATION_ID}")
    connection.execute(f"PRAGMA user_version = {storage.SCHEMA_VERSION}")
    connection.close()

    with pytest.raises(storage.ProjectCorruptError, match="missing required table"):
        Project.open(malformed)


def test_matching_names_without_required_constraints_fail_as_corrupt(tmp_path: Path) -> None:
    malformed = tmp_path / "missing-constraints.rsmp"
    connection = sqlite3.connect(malformed)
    connection.executescript(
        """
        CREATE TABLE project_metadata (
            key TEXT NOT NULL, value_json BLOB NOT NULL, updated_utc TEXT NOT NULL
        ) STRICT;
        CREATE TABLE sources (
            path TEXT NOT NULL, content_hash TEXT NOT NULL, size_bytes INTEGER NOT NULL,
            modified_ns INTEGER, metadata_json BLOB NOT NULL, refreshed_utc TEXT NOT NULL,
            fingerprint_kind TEXT NOT NULL
        ) STRICT;
        CREATE TABLE payloads (
            collection TEXT NOT NULL, record_key TEXT NOT NULL, payload_json BLOB NOT NULL,
            payload_hash TEXT NOT NULL, updated_utc TEXT NOT NULL
        ) STRICT;
        CREATE TABLE payload_dependencies (
            collection TEXT NOT NULL, record_key TEXT NOT NULL, source_path TEXT NOT NULL
        ) STRICT;
        CREATE TABLE schema_migrations (
            version INTEGER NOT NULL, applied_utc TEXT NOT NULL
        ) STRICT;
        CREATE INDEX payload_dependencies_source_idx
            ON payload_dependencies(source_path);
        """
    )
    connection.execute(f"PRAGMA application_id = {storage.APPLICATION_ID}")
    connection.execute(f"PRAGMA user_version = {storage.SCHEMA_VERSION}")
    connection.close()

    with pytest.raises(storage.ProjectCorruptError, match="invalid primary key"):
        Project.open(malformed)


def test_backup_restore_delete_and_failed_create_temp_file_discipline(tmp_path: Path) -> None:
    path = tmp_path / "lifecycle.rsmp"
    backup = tmp_path / "backups" / "story.bak"
    restored = tmp_path / "restored.rsmp"
    project = Project.create(path, metadata={"title": "Lifecycle"})
    project.refresh_sources([source("story.rpy", "label start:\n")])
    expected = project.canonical_export()
    project.backup(backup)
    project.close()

    with Project.restore_backup(backup, restored) as recovered:
        assert recovered.canonical_export() == expected
        recovered.delete()
    assert not restored.exists()

    reopened = Project.open(path)
    reopened.delete()
    assert not path.exists()

    occupied = tmp_path / "occupied.rsmp"
    occupied.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        Project.create(occupied)
    assert occupied.read_text(encoding="utf-8") == "keep"
    assert not list(tmp_path.glob(".*.tmp"))


def test_rejects_unknown_sources_noncanonical_json_and_unsafe_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="safe relative"):
        source("../outside.rpy", "bad")
    with pytest.raises(ValueError, match="NaN"):
        PayloadRecord("effects", "bad", {"value": float("nan")})

    with Project.create(tmp_path / "validation.rsmp") as project:
        with pytest.raises(ValueError, match="unknown source"):
            project.write_payloads(
                [PayloadRecord("gates", "gate", {"expression": "wits > 0"}, ("missing.rpy",))]
            )
        assert project.payload_keys("gates") == ()
