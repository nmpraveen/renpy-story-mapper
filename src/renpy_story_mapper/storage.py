"""Versioned SQLite storage primitives for durable story-mapper projects.

Only inert, canonical JSON is stored here.  This module never reads game files,
parses Ren'Py, or executes creator code.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

APPLICATION_ID: Final = 0x52534D50  # "RSMP"
SCHEMA_VERSION: Final = 2

PAYLOAD_COLLECTIONS: Final = frozenset(
    {
        "m01_graph",
        "m02_semantic",
        "diagnostics",
        "unresolved",
        "gates",
        "effects",
        "import_manifest",
        "parsed_source",
        "source_dependencies",
        "state_registry",
    }
)


class ProjectStorageError(Exception):
    """Base class for safe, user-facing project storage failures."""


class ProjectCorruptError(ProjectStorageError):
    """The file is not a valid, internally consistent story-mapper project."""


class IncompatibleProjectVersionError(ProjectStorageError):
    """The project schema is newer than this application supports."""


class ProjectOperationCancelled(ProjectStorageError):
    """A project operation was cancelled and its transaction was rolled back."""


def utc_now() -> str:
    """Return a stable SQLite-friendly UTC timestamp."""

    return datetime.now(UTC).isoformat(timespec="microseconds")


def canonical_json(value: object) -> bytes:
    """Serialize JSON deterministically, rejecting non-portable numeric values."""

    _validate_json(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def decode_json(value: bytes | str) -> object:
    """Decode a stored canonical JSON value."""

    try:
        return json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectCorruptError("project contains invalid JSON payload data") from exc


def connect(path: Path) -> sqlite3.Connection:
    """Open a project connection with durability and integrity settings."""

    connection = sqlite3.connect(path, isolation_level=None, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = DELETE")
    connection.execute("PRAGMA synchronous = FULL")
    connection.execute("PRAGMA trusted_schema = OFF")
    return connection


def initialize_database(
    connection: sqlite3.Connection, *, target_version: int = SCHEMA_VERSION
) -> None:
    """Initialize or migrate a database up to ``target_version`` atomically."""

    if not 1 <= target_version <= SCHEMA_VERSION:
        raise ValueError(f"target schema version must be between 1 and {SCHEMA_VERSION}")
    current = _pragma_int(connection, "user_version")
    application_id = _pragma_int(connection, "application_id")
    if current > target_version:
        raise IncompatibleProjectVersionError(
            f"project schema version {current} is newer than supported version {target_version}"
        )
    if application_id not in {0, APPLICATION_ID}:
        raise ProjectCorruptError("SQLite file belongs to another application")

    while current < target_version:
        next_version = current + 1
        with transaction(connection):
            if next_version == 1:
                _migrate_to_v1(connection)
            elif next_version == 2:
                _migrate_to_v2(connection)
            connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version = {next_version}")
        current = next_version


def validate_database(connection: sqlite3.Connection) -> int:
    """Validate project identity, supported version, and SQLite integrity."""

    try:
        application_id = _pragma_int(connection, "application_id")
        version = _pragma_int(connection, "user_version")
        result = connection.execute("PRAGMA quick_check").fetchall()
    except sqlite3.DatabaseError as exc:
        raise ProjectCorruptError("project is not a readable SQLite database") from exc
    if version > SCHEMA_VERSION:
        raise IncompatibleProjectVersionError(
            f"project schema version {version} is newer than supported version {SCHEMA_VERSION}"
        )
    if application_id != APPLICATION_ID:
        raise ProjectCorruptError("file is not a Ren'Py Story Mapper project")
    if version < 1:
        raise ProjectCorruptError("project has no recognized schema version")
    failures = [str(row[0]) for row in result if str(row[0]).lower() != "ok"]
    if failures:
        raise ProjectCorruptError(f"project failed SQLite integrity check: {'; '.join(failures)}")
    return version


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[None]:
    """Run an immediate transaction with guaranteed exception rollback."""

    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


def payload_digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def check_collection(collection: str) -> None:
    if collection not in PAYLOAD_COLLECTIONS:
        allowed = ", ".join(sorted(PAYLOAD_COLLECTIONS))
        raise ValueError(f"unknown payload collection {collection!r}; expected one of: {allowed}")


def make_backup(source: Path, destination: Path) -> None:
    """Create a consistent SQLite backup and atomically publish it."""

    temporary = destination.with_name(f".{destination.name}.tmp")
    if temporary.exists():
        temporary.unlink()
    source_connection: sqlite3.Connection | None = None
    destination_connection: sqlite3.Connection | None = None
    try:
        source_connection = connect(source)
        validate_database(source_connection)
        destination_connection = connect(temporary)
        source_connection.backup(destination_connection)
        destination_connection.close()
        destination_connection = None
        backup_check = connect(temporary)
        try:
            validate_database(backup_check)
        finally:
            backup_check.close()
        temporary.replace(destination)
    except sqlite3.DatabaseError as exc:
        raise ProjectCorruptError("could not create a consistent project backup") from exc
    finally:
        if destination_connection is not None:
            destination_connection.close()
        if source_connection is not None:
            source_connection.close()
        if temporary.exists():
            temporary.unlink()


def _migrate_to_v1(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE project_metadata (
            key TEXT PRIMARY KEY NOT NULL,
            value_json BLOB NOT NULL,
            updated_utc TEXT NOT NULL
        ) STRICT
        """,
        """
        CREATE TABLE sources (
            path TEXT PRIMARY KEY NOT NULL,
            content_hash TEXT NOT NULL,
            size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
            modified_ns INTEGER,
            metadata_json BLOB NOT NULL,
            refreshed_utc TEXT NOT NULL
        ) STRICT
        """,
        """
        CREATE TABLE payloads (
            collection TEXT NOT NULL,
            record_key TEXT NOT NULL,
            payload_json BLOB NOT NULL,
            payload_hash TEXT NOT NULL,
            updated_utc TEXT NOT NULL,
            PRIMARY KEY (collection, record_key)
        ) STRICT
        """,
        """
        CREATE TABLE payload_dependencies (
            collection TEXT NOT NULL,
            record_key TEXT NOT NULL,
            source_path TEXT NOT NULL,
            PRIMARY KEY (collection, record_key, source_path),
            FOREIGN KEY (collection, record_key)
                REFERENCES payloads(collection, record_key) ON DELETE CASCADE,
            FOREIGN KEY (source_path) REFERENCES sources(path) ON DELETE CASCADE
        ) STRICT
        """,
        "CREATE INDEX payload_dependencies_source_idx ON payload_dependencies(source_path)",
    )
    for statement in statements:
        connection.execute(statement)


def _migrate_to_v2(connection: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(sources)")}
    if "fingerprint_kind" not in columns:
        connection.execute(
            "ALTER TABLE sources ADD COLUMN fingerprint_kind TEXT NOT NULL DEFAULT 'sha256'"
        )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY NOT NULL,
            applied_utc TEXT NOT NULL
        ) STRICT
        """
    )
    timestamp = utc_now()
    connection.executemany(
        "INSERT OR REPLACE INTO schema_migrations(version, applied_utc) VALUES (?, ?)",
        ((1, timestamp), (2, timestamp)),
    )


def _pragma_int(connection: sqlite3.Connection, name: str) -> int:
    try:
        row = connection.execute(f"PRAGMA {name}").fetchone()
    except sqlite3.DatabaseError as exc:
        raise ProjectCorruptError("project header could not be read") from exc
    if row is None or not isinstance(row[0], int):
        raise ProjectCorruptError(f"project has an invalid {name}")
    return row[0]


def _validate_json(value: object) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON values cannot contain NaN or infinity")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            _validate_json(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        raise TypeError("JSON arrays must be lists")
    raise TypeError(f"value of type {type(value).__name__} is not JSON-compatible")
