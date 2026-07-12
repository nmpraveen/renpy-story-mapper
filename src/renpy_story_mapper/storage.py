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
SCHEMA_VERSION: Final = 4

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
            elif next_version == 3:
                _migrate_to_v3(connection)
            elif next_version == 4:
                _migrate_to_v4(connection)
            connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version = {next_version}")
        current = next_version
    if current == 4 and needs_v4_enrichment_extension(connection):
        with transaction(connection):
            _migrate_v4_enrichment_extension(connection)


def validate_database(
    connection: sqlite3.Connection, *, allow_legacy_v4: bool = False
) -> int:
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
    _validate_schema_shape(connection, version, allow_legacy_v4=allow_legacy_v4)
    failures = [str(row[0]) for row in result if str(row[0]).lower() != "ok"]
    if failures:
        raise ProjectCorruptError(f"project failed SQLite integrity check: {'; '.join(failures)}")
    return version


def _validate_schema_shape(
    connection: sqlite3.Connection, version: int, *, allow_legacy_v4: bool = False
) -> None:
    required: dict[str, set[str]] = {
        "project_metadata": {"key", "value_json", "updated_utc"},
        "sources": {
            "path",
            "content_hash",
            "size_bytes",
            "modified_ns",
            "metadata_json",
            "refreshed_utc",
        },
        "payloads": {
            "collection",
            "record_key",
            "payload_json",
            "payload_hash",
            "updated_utc",
        },
        "payload_dependencies": {"collection", "record_key", "source_path"},
    }
    if version >= 2:
        required["sources"].add("fingerprint_kind")
        required["schema_migrations"] = {"version", "applied_utc"}
    if version >= 3:
        required["presentation_nodes"] = {
            "node_id",
            "level",
            "parent_id",
            "sort_key",
            "kind",
            "label",
            "source_path",
            "start_line",
            "end_line",
            "technical",
            "payload_json",
        }
        required["presentation_edges"] = {
            "edge_id",
            "level",
            "source_id",
            "target_id",
            "sort_key",
            "kind",
            "payload_json",
        }
        required["presentation_evidence"] = {
            "evidence_id",
            "node_id",
            "sort_key",
            "kind",
            "source_path",
            "start_line",
            "end_line",
            "text",
            "payload_json",
        }
        required["presentation_search"] = {
            "search_id",
            "node_id",
            "field",
            "text",
            "normalized",
        }
        required["presentation_facts"] = {
            "fact_id",
            "node_id",
            "fact_kind",
            "variable",
            "category",
            "status",
            "expression",
            "source_path",
            "start_line",
            "end_line",
            "sort_key",
            "payload_json",
        }
        required["presentation_index_state"] = {"singleton", "generation"}
        required["presentation_overrides"] = {
            "node_id",
            "display_name",
            "hidden",
            "updated_utc",
        }
    if version >= 4:
        required.update(
            {
                "organization_runs": {
                    "run_id",
                    "provider_mode",
                    "model_profile",
                    "model_fingerprint",
                    "prompt_version",
                    "output_schema_version",
                    "generation",
                    "status",
                    "started_utc",
                    "completed_utc",
                    "elapsed_ms",
                    "usage_json",
                    "sanitized_failure",
                },
                "organization_cache": {
                    "cache_key",
                    "provider_mode",
                    "model_profile",
                    "model_fingerprint",
                    "prompt_version",
                    "output_schema_version",
                    "input_hash",
                    "ordered_ids_hash",
                    "result_json",
                    "result_hash",
                    "created_utc",
                    "last_used_utc",
                    "hit_count",
                },
                "organization_chunks": {
                    "chunk_id",
                    "run_id",
                    "scope_id",
                    "reconciliation_scope",
                    "ordinal",
                    "input_hash",
                    "ordered_ids_hash",
                    "cache_key",
                    "cache_state",
                    "status",
                    "result_json",
                    "result_hash",
                },
                "organization_drafts": {
                    "draft_id",
                    "run_id",
                    "generation",
                    "status",
                    "candidate_json",
                    "candidate_hash",
                    "created_utc",
                    "resolved_utc",
                },
                "organization_draft_reviews": {
                    "draft_id",
                    "target_kind",
                    "target_id",
                    "decision",
                    "reviewed_utc",
                },
                "story_arcs": {
                    "arc_id",
                    "title",
                    "summary",
                    "sort_order",
                    "origin",
                    "pinned",
                    "hidden",
                    "approval_state",
                    "needs_review",
                    "generation",
                    "updated_utc",
                },
                "story_events": {
                    "event_id",
                    "title",
                    "summary",
                    "sort_order",
                    "origin",
                    "pinned",
                    "hidden",
                    "approval_state",
                    "needs_review",
                    "generation",
                    "updated_utc",
                },
                "story_event_members": {"event_id", "beat_id", "ordinal"},
                "story_arc_members": {"arc_id", "event_id", "ordinal"},
                "story_event_edges": {
                    "edge_id",
                    "source_event_id",
                    "target_event_id",
                    "kind",
                    "provenance",
                    "transition_ids_json",
                },
                "story_claims": {
                    "claim_id",
                    "event_id",
                    "arc_id",
                    "text",
                    "claim_kind",
                    "status",
                    "sort_order",
                },
                "story_claim_evidence": {"claim_id", "evidence_id"},
                "story_group_enrichment": {
                    "target_kind",
                    "target_id",
                    "characters_json",
                    "importance",
                    "outcomes_json",
                    "promoted_fact_ids_json",
                    "warnings_json",
                },
                "story_edits": {
                    "edit_id",
                    "operation",
                    "target_kind",
                    "target_id",
                    "payload_json",
                    "status",
                    "created_utc",
                },
            }
        )
        if allow_legacy_v4 and needs_v4_enrichment_extension(connection):
            required.pop("story_group_enrichment")
    try:
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
        }
        strict_tables = {
            str(row[1]): int(row[5])
            for row in connection.execute("PRAGMA table_list")
            if str(row[2]) == "table"
        }
        primary_keys = {
            "project_metadata": ("key",),
            "sources": ("path",),
            "payloads": ("collection", "record_key"),
            "payload_dependencies": ("collection", "record_key", "source_path"),
            "schema_migrations": ("version",),
            "presentation_nodes": ("node_id",),
            "presentation_edges": ("edge_id",),
            "presentation_evidence": ("evidence_id",),
            "presentation_search": ("search_id",),
            "presentation_facts": ("fact_id",),
            "presentation_index_state": ("singleton",),
            "presentation_overrides": ("node_id",),
            "organization_runs": ("run_id",),
            "organization_cache": ("cache_key",),
            "organization_chunks": ("chunk_id",),
            "organization_drafts": ("draft_id",),
            "organization_draft_reviews": ("draft_id", "target_kind", "target_id"),
            "story_arcs": ("arc_id",),
            "story_events": ("event_id",),
            "story_event_members": ("event_id", "beat_id"),
            "story_arc_members": ("arc_id", "event_id"),
            "story_event_edges": ("edge_id",),
            "story_claims": ("claim_id",),
            "story_claim_evidence": ("claim_id", "evidence_id"),
            "story_group_enrichment": ("target_kind", "target_id"),
            "story_edits": ("edit_id",),
        }
        declared_types: dict[str, dict[str, str]] = {
            "project_metadata": {
                "key": "TEXT",
                "value_json": "BLOB",
                "updated_utc": "TEXT",
            },
            "sources": {
                "path": "TEXT",
                "content_hash": "TEXT",
                "size_bytes": "INTEGER",
                "modified_ns": "INTEGER",
                "metadata_json": "BLOB",
                "refreshed_utc": "TEXT",
                "fingerprint_kind": "TEXT",
            },
            "payloads": {
                "collection": "TEXT",
                "record_key": "TEXT",
                "payload_json": "BLOB",
                "payload_hash": "TEXT",
                "updated_utc": "TEXT",
            },
            "payload_dependencies": {
                "collection": "TEXT",
                "record_key": "TEXT",
                "source_path": "TEXT",
            },
            "schema_migrations": {"version": "INTEGER", "applied_utc": "TEXT"},
            "presentation_nodes": {
                "node_id": "TEXT",
                "level": "INTEGER",
                "parent_id": "TEXT",
                "sort_key": "TEXT",
                "kind": "TEXT",
                "label": "TEXT",
                "source_path": "TEXT",
                "start_line": "INTEGER",
                "end_line": "INTEGER",
                "technical": "INTEGER",
                "payload_json": "BLOB",
            },
            "presentation_edges": {
                "edge_id": "TEXT",
                "level": "INTEGER",
                "source_id": "TEXT",
                "target_id": "TEXT",
                "sort_key": "TEXT",
                "kind": "TEXT",
                "payload_json": "BLOB",
            },
            "presentation_evidence": {
                "evidence_id": "TEXT",
                "node_id": "TEXT",
                "sort_key": "TEXT",
                "kind": "TEXT",
                "source_path": "TEXT",
                "start_line": "INTEGER",
                "end_line": "INTEGER",
                "text": "TEXT",
                "payload_json": "BLOB",
            },
            "presentation_search": {
                "search_id": "INTEGER",
                "node_id": "TEXT",
                "field": "TEXT",
                "text": "TEXT",
                "normalized": "TEXT",
            },
            "presentation_overrides": {
                "node_id": "TEXT",
                "display_name": "TEXT",
                "hidden": "INTEGER",
                "updated_utc": "TEXT",
            },
            "presentation_facts": {
                "fact_id": "TEXT",
                "node_id": "TEXT",
                "fact_kind": "TEXT",
                "variable": "TEXT",
                "category": "TEXT",
                "status": "TEXT",
                "expression": "TEXT",
                "source_path": "TEXT",
                "start_line": "INTEGER",
                "end_line": "INTEGER",
                "sort_key": "TEXT",
                "payload_json": "BLOB",
            },
            "presentation_index_state": {
                "singleton": "INTEGER",
                "generation": "TEXT",
            },
            "organization_runs": {
                "run_id": "TEXT",
                "provider_mode": "TEXT",
                "model_profile": "TEXT",
                "model_fingerprint": "TEXT",
                "prompt_version": "TEXT",
                "output_schema_version": "TEXT",
                "generation": "TEXT",
                "status": "TEXT",
                "started_utc": "TEXT",
                "completed_utc": "TEXT",
                "elapsed_ms": "INTEGER",
                "usage_json": "BLOB",
                "sanitized_failure": "TEXT",
            },
            "organization_cache": {
                "cache_key": "TEXT",
                "provider_mode": "TEXT",
                "model_profile": "TEXT",
                "model_fingerprint": "TEXT",
                "prompt_version": "TEXT",
                "output_schema_version": "TEXT",
                "input_hash": "TEXT",
                "ordered_ids_hash": "TEXT",
                "result_json": "BLOB",
                "result_hash": "TEXT",
                "created_utc": "TEXT",
                "last_used_utc": "TEXT",
                "hit_count": "INTEGER",
            },
            "organization_chunks": {
                "chunk_id": "TEXT",
                "run_id": "TEXT",
                "scope_id": "TEXT",
                "reconciliation_scope": "TEXT",
                "ordinal": "INTEGER",
                "input_hash": "TEXT",
                "ordered_ids_hash": "TEXT",
                "cache_key": "TEXT",
                "cache_state": "TEXT",
                "status": "TEXT",
                "result_json": "BLOB",
                "result_hash": "TEXT",
            },
            "organization_drafts": {
                "draft_id": "TEXT",
                "run_id": "TEXT",
                "generation": "TEXT",
                "status": "TEXT",
                "candidate_json": "BLOB",
                "candidate_hash": "TEXT",
                "created_utc": "TEXT",
                "resolved_utc": "TEXT",
            },
            "organization_draft_reviews": {
                "draft_id": "TEXT",
                "target_kind": "TEXT",
                "target_id": "TEXT",
                "decision": "TEXT",
                "reviewed_utc": "TEXT",
            },
            "story_arcs": {
                "arc_id": "TEXT",
                "title": "TEXT",
                "summary": "TEXT",
                "sort_order": "INTEGER",
                "origin": "TEXT",
                "pinned": "INTEGER",
                "hidden": "INTEGER",
                "approval_state": "TEXT",
                "needs_review": "INTEGER",
                "generation": "TEXT",
                "updated_utc": "TEXT",
            },
            "story_events": {
                "event_id": "TEXT",
                "title": "TEXT",
                "summary": "TEXT",
                "sort_order": "INTEGER",
                "origin": "TEXT",
                "pinned": "INTEGER",
                "hidden": "INTEGER",
                "approval_state": "TEXT",
                "needs_review": "INTEGER",
                "generation": "TEXT",
                "updated_utc": "TEXT",
            },
            "story_event_members": {"event_id": "TEXT", "beat_id": "TEXT", "ordinal": "INTEGER"},
            "story_arc_members": {"arc_id": "TEXT", "event_id": "TEXT", "ordinal": "INTEGER"},
            "story_event_edges": {
                "edge_id": "TEXT",
                "source_event_id": "TEXT",
                "target_event_id": "TEXT",
                "kind": "TEXT",
                "provenance": "TEXT",
                "transition_ids_json": "BLOB",
            },
            "story_claims": {
                "claim_id": "TEXT",
                "event_id": "TEXT",
                "arc_id": "TEXT",
                "text": "TEXT",
                "claim_kind": "TEXT",
                "status": "TEXT",
                "sort_order": "INTEGER",
            },
            "story_claim_evidence": {"claim_id": "TEXT", "evidence_id": "TEXT"},
            "story_group_enrichment": {
                "target_kind": "TEXT",
                "target_id": "TEXT",
                "characters_json": "BLOB",
                "importance": "TEXT",
                "outcomes_json": "BLOB",
                "promoted_fact_ids_json": "BLOB",
                "warnings_json": "BLOB",
            },
            "story_edits": {
                "edit_id": "TEXT",
                "operation": "TEXT",
                "target_kind": "TEXT",
                "target_id": "TEXT",
                "payload_json": "BLOB",
                "status": "TEXT",
                "created_utc": "TEXT",
            },
        }
        nullable = {
            ("sources", "modified_ns"),
            ("presentation_nodes", "parent_id"),
            ("presentation_nodes", "source_path"),
            ("presentation_nodes", "start_line"),
            ("presentation_nodes", "end_line"),
            ("presentation_overrides", "display_name"),
            ("presentation_facts", "node_id"),
            ("presentation_facts", "variable"),
            ("presentation_facts", "category"),
            ("organization_runs", "model_fingerprint"),
            ("organization_runs", "completed_utc"),
            ("organization_runs", "elapsed_ms"),
            ("organization_runs", "sanitized_failure"),
            ("organization_chunks", "cache_key"),
            ("organization_chunks", "result_json"),
            ("organization_chunks", "result_hash"),
            ("organization_drafts", "resolved_utc"),
            ("story_claims", "event_id"),
            ("story_claims", "arc_id"),
        }
        for table, expected_columns in required.items():
            if table not in tables:
                raise ProjectCorruptError(f"project is missing required table {table!r}")
            column_rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            columns = {str(row[1]) for row in column_rows}
            missing = expected_columns - columns
            if missing:
                names = ", ".join(sorted(missing))
                raise ProjectCorruptError(
                    f"project table {table!r} is missing required columns: {names}"
                )
            allowed_columns = set(declared_types[table])
            unexpected = columns - allowed_columns
            if unexpected:
                names = ", ".join(sorted(unexpected))
                raise ProjectCorruptError(
                    f"project table {table!r} has unexpected columns: {names}"
                )
            if strict_tables.get(table) != 1:
                raise ProjectCorruptError(f"project table {table!r} must be STRICT")
            actual_key = tuple(
                str(row[1])
                for row in sorted(column_rows, key=lambda item: int(item[5]))
                if int(row[5]) > 0
            )
            if actual_key != primary_keys[table]:
                raise ProjectCorruptError(f"project table {table!r} has an invalid primary key")
            for row in column_rows:
                column = str(row[1])
                expected_type = declared_types[table][column]
                if str(row[2]).upper() != expected_type:
                    raise ProjectCorruptError(
                        f"project column {table}.{column} must use type {expected_type}"
                    )
                if (
                    column in expected_columns
                    and (table, column) not in nullable
                    and int(row[3]) != 1
                    and int(row[5]) == 0
                ):
                    raise ProjectCorruptError(f"project column {table}.{column} must be NOT NULL")
        indexes = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_schema WHERE type = 'index'")
        }
    except sqlite3.DatabaseError as exc:
        raise ProjectCorruptError("project schema could not be validated") from exc
    if "payload_dependencies_source_idx" not in indexes:
        raise ProjectCorruptError("project is missing its dependency lookup index")
    index_columns = tuple(
        str(row[2])
        for row in connection.execute('PRAGMA index_info("payload_dependencies_source_idx")')
    )
    if index_columns != ("source_path",):
        raise ProjectCorruptError("project dependency lookup index has invalid columns")
    foreign_keys = {
        (str(row[2]), str(row[3]), str(row[4]), str(row[6]).upper())
        for row in connection.execute('PRAGMA foreign_key_list("payload_dependencies")')
    }
    expected_foreign_keys = {
        ("payloads", "collection", "collection", "CASCADE"),
        ("payloads", "record_key", "record_key", "CASCADE"),
        ("sources", "source_path", "path", "CASCADE"),
    }
    if foreign_keys != expected_foreign_keys:
        raise ProjectCorruptError("project dependency foreign keys are invalid")
    source_sql_row = connection.execute(
        "SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = 'sources'"
    ).fetchone()
    source_sql = "" if source_sql_row is None else str(source_sql_row[0])
    normalized_source_sql = " ".join(source_sql.lower().split())
    if "check (size_bytes >= 0)" not in normalized_source_sql:
        raise ProjectCorruptError("project sources table is missing its size constraint")
    if version >= 3:
        expected_indexes = {
            "presentation_nodes_parent_idx",
            "presentation_edges_level_idx",
            "presentation_evidence_node_idx",
            "presentation_search_normalized_idx",
            "presentation_facts_filter_idx",
        }
        missing_indexes = expected_indexes - indexes
        if missing_indexes:
            names = ", ".join(sorted(missing_indexes))
            raise ProjectCorruptError(f"project is missing presentation indexes: {names}")
    if version >= 4:
        expected_indexes = {
            "organization_runs_status_idx",
            "organization_chunks_run_idx",
            "organization_chunks_invalidation_idx",
            "organization_cache_lookup_idx",
            "organization_drafts_status_idx",
            "organization_draft_reviews_decision_idx",
            "story_arcs_order_idx",
            "story_events_order_idx",
            "story_event_members_beat_idx",
            "story_arc_members_order_idx",
            "story_event_edges_source_idx",
            "story_event_edges_target_idx",
            "story_claims_event_idx",
            "story_claim_evidence_evidence_idx",
            "story_group_enrichment_target_idx",
            "story_edits_target_idx",
        }
        if allow_legacy_v4 and needs_v4_enrichment_extension(connection):
            expected_indexes.remove("story_group_enrichment_target_idx")
        missing_indexes = expected_indexes - indexes
        if missing_indexes:
            names = ", ".join(sorted(missing_indexes))
            raise ProjectCorruptError(f"project is missing organization indexes: {names}")
        index_shapes = {
            "organization_runs_status_idx": ("status", "started_utc"),
            "organization_chunks_run_idx": ("run_id", "ordinal"),
            "organization_chunks_invalidation_idx": ("reconciliation_scope", "input_hash"),
            "organization_cache_lookup_idx": (
                "provider_mode",
                "model_profile",
                "model_fingerprint",
                "prompt_version",
                "output_schema_version",
                "input_hash",
                "ordered_ids_hash",
            ),
            "story_event_members_beat_idx": ("beat_id", "event_id"),
            "story_arc_members_order_idx": ("arc_id", "ordinal", "event_id"),
            "story_event_edges_source_idx": ("source_event_id", "kind", "target_event_id"),
            "story_group_enrichment_target_idx": ("target_kind", "target_id"),
        }
        if allow_legacy_v4 and needs_v4_enrichment_extension(connection):
            index_shapes.pop("story_group_enrichment_target_idx")
        for name, expected in index_shapes.items():
            actual = tuple(
                str(row[2]) for row in connection.execute(f'PRAGMA index_info("{name}")')
            )
            if actual != expected:
                raise ProjectCorruptError(
                    f"project organization index {name!r} has invalid columns"
                )
        foreign_key_shapes = {
            "organization_chunks": {
                ("organization_runs", "run_id", "run_id", "CASCADE"),
                ("organization_cache", "cache_key", "cache_key", "SET NULL"),
            },
            "organization_drafts": {
                ("organization_runs", "run_id", "run_id", "CASCADE"),
            },
            "organization_draft_reviews": {
                ("organization_drafts", "draft_id", "draft_id", "CASCADE"),
            },
            "story_event_members": {("story_events", "event_id", "event_id", "CASCADE")},
            "story_arc_members": {
                ("story_arcs", "arc_id", "arc_id", "CASCADE"),
                ("story_events", "event_id", "event_id", "CASCADE"),
            },
            "story_event_edges": {
                ("story_events", "source_event_id", "event_id", "CASCADE"),
                ("story_events", "target_event_id", "event_id", "CASCADE"),
            },
            "story_claims": {
                ("story_events", "event_id", "event_id", "CASCADE"),
                ("story_arcs", "arc_id", "arc_id", "CASCADE"),
            },
            "story_claim_evidence": {
                ("story_claims", "claim_id", "claim_id", "CASCADE"),
            },
        }
        for table, expected_foreign_key_shape in foreign_key_shapes.items():
            actual_foreign_key_shape = {
                (str(row[2]), str(row[3]), str(row[4]), str(row[6]).upper())
                for row in connection.execute(f'PRAGMA foreign_key_list("{table}")')
            }
            if actual_foreign_key_shape != expected_foreign_key_shape:
                raise ProjectCorruptError(
                    f"project organization table {table!r} has invalid foreign keys"
                )
        constraint_fragments = {
            "organization_cache": (
                "model_profile text not null",
                "check (length(trim(model_profile)) > 0)",
                "check (hit_count >= 0)",
            ),
            "organization_draft_reviews": (
                "primary key (draft_id, target_kind, target_id)",
                "check (target_kind in ('arc','event'))",
                "check (decision in ('approved','rejected'))",
            ),
            "story_arcs": (
                "check (length(trim(title)) between 1 and 80)",
                "check (length(trim(summary)) between 1 and 320)",
                "check (origin in ('ai','deterministic','user'))",
            ),
            "story_events": (
                "check (length(trim(title)) between 1 and 80)",
                "check (length(trim(summary)) between 1 and 320)",
                "check (origin in ('ai','deterministic','user'))",
            ),
            "story_event_members": (
                "unique (event_id, ordinal)",
                "unique (beat_id)",
            ),
            "story_arc_members": (
                "unique (arc_id, ordinal)",
                "unique (event_id)",
            ),
            "story_event_edges": ("unique (source_event_id, target_event_id, kind)",),
            "story_group_enrichment": (
                "primary key (target_kind, target_id)",
                "check (target_kind in ('arc','event'))",
                "check (importance in ('supporting','major','turning point'))",
            ),
            "story_edits": (
                "check (operation in "
                "('rename','split','merge','move','hide','pin','approve','reject'))",
            ),
        }
        if allow_legacy_v4 and needs_v4_enrichment_extension(connection):
            constraint_fragments.pop("story_group_enrichment")
        for table, fragments in constraint_fragments.items():
            row = connection.execute(
                "SELECT sql FROM sqlite_schema WHERE type='table' AND name=?", (table,)
            ).fetchone()
            normalized = "" if row is None else " ".join(str(row[0]).lower().split())
            normalized = normalized.replace(", ", ",").replace("( ", "(").replace(" )", ")")
            if any(
                fragment.replace(", ", ",").replace("( ", "(").replace(" )", ")") not in normalized
                for fragment in fragments
            ):
                raise ProjectCorruptError(
                    f"project organization table {table!r} has invalid constraints"
                )


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


def make_backup(
    source: Path, destination: Path, *, allow_legacy_v4: bool = False
) -> None:
    """Create a consistent SQLite backup and atomically publish it."""

    temporary = destination.with_name(f".{destination.name}.tmp")
    if temporary.exists():
        temporary.unlink()
    source_connection: sqlite3.Connection | None = None
    destination_connection: sqlite3.Connection | None = None
    try:
        source_connection = connect(source)
        validate_database(source_connection, allow_legacy_v4=allow_legacy_v4)
        destination_connection = connect(temporary)
        source_connection.backup(destination_connection)
        destination_connection.close()
        destination_connection = None
        backup_check = connect(temporary)
        try:
            validate_database(backup_check, allow_legacy_v4=allow_legacy_v4)
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


def _migrate_to_v3(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE IF NOT EXISTS presentation_nodes (
            node_id TEXT PRIMARY KEY NOT NULL,
            level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 3),
            parent_id TEXT,
            sort_key TEXT NOT NULL,
            kind TEXT NOT NULL,
            label TEXT NOT NULL,
            source_path TEXT,
            start_line INTEGER,
            end_line INTEGER,
            technical INTEGER NOT NULL CHECK (technical IN (0, 1)),
            payload_json BLOB NOT NULL
        ) STRICT
        """,
        """
        CREATE TABLE IF NOT EXISTS presentation_edges (
            edge_id TEXT PRIMARY KEY NOT NULL,
            level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 3),
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            sort_key TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload_json BLOB NOT NULL
        ) STRICT
        """,
        """
        CREATE TABLE IF NOT EXISTS presentation_evidence (
            evidence_id TEXT PRIMARY KEY NOT NULL,
            node_id TEXT NOT NULL,
            sort_key TEXT NOT NULL,
            kind TEXT NOT NULL,
            source_path TEXT NOT NULL,
            start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            text TEXT NOT NULL,
            payload_json BLOB NOT NULL
        ) STRICT
        """,
        """
        CREATE TABLE IF NOT EXISTS presentation_search (
            search_id INTEGER PRIMARY KEY NOT NULL,
            node_id TEXT NOT NULL,
            field TEXT NOT NULL,
            text TEXT NOT NULL,
            normalized TEXT NOT NULL
        ) STRICT
        """,
        """
        CREATE TABLE IF NOT EXISTS presentation_overrides (
            node_id TEXT PRIMARY KEY NOT NULL,
            display_name TEXT,
            hidden INTEGER NOT NULL CHECK (hidden IN (0, 1)),
            updated_utc TEXT NOT NULL
        ) STRICT
        """,
        """
        CREATE TABLE IF NOT EXISTS presentation_facts (
            fact_id TEXT PRIMARY KEY NOT NULL,
            node_id TEXT,
            fact_kind TEXT NOT NULL CHECK (fact_kind IN ('gate', 'effect')),
            variable TEXT,
            category TEXT,
            status TEXT NOT NULL,
            expression TEXT NOT NULL,
            source_path TEXT NOT NULL,
            start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            sort_key TEXT NOT NULL,
            payload_json BLOB NOT NULL
        ) STRICT
        """,
        """
        CREATE TABLE IF NOT EXISTS presentation_index_state (
            singleton INTEGER PRIMARY KEY NOT NULL CHECK (singleton = 1),
            generation TEXT NOT NULL
        ) STRICT
        """,
        "CREATE INDEX IF NOT EXISTS presentation_nodes_parent_idx "
        "ON presentation_nodes(level, parent_id, sort_key, node_id)",
        "CREATE INDEX IF NOT EXISTS presentation_nodes_parent_lookup_idx "
        "ON presentation_nodes(parent_id, node_id)",
        "CREATE INDEX IF NOT EXISTS presentation_nodes_source_idx "
        "ON presentation_nodes(level, source_path, start_line, end_line, sort_key)",
        "CREATE INDEX IF NOT EXISTS presentation_edges_level_idx "
        "ON presentation_edges(level, sort_key, edge_id)",
        "CREATE INDEX IF NOT EXISTS presentation_edges_source_idx "
        "ON presentation_edges(level, source_id, target_id, edge_id)",
        "CREATE INDEX IF NOT EXISTS presentation_evidence_node_idx "
        "ON presentation_evidence(node_id, sort_key, evidence_id)",
        "CREATE INDEX IF NOT EXISTS presentation_search_normalized_idx "
        "ON presentation_search(field, normalized, search_id)",
        "CREATE INDEX IF NOT EXISTS presentation_facts_filter_idx "
        "ON presentation_facts(fact_kind, variable, category, sort_key, fact_id)",
        "CREATE INDEX IF NOT EXISTS presentation_facts_node_idx "
        "ON presentation_facts(node_id, sort_key, fact_id)",
    )
    for statement in statements:
        connection.execute(statement)
    connection.execute(
        "INSERT OR REPLACE INTO schema_migrations(version, applied_utc) VALUES (?, ?)",
        (3, utc_now()),
    )


def needs_v4_enrichment_extension(connection: sqlite3.Connection) -> bool:
    """Return whether a pre-enrichment schema-v4 project needs the additive extension."""

    if _pragma_int(connection, "user_version") != 4:
        return False
    names = {
        str(row[0])
        for row in connection.execute(
            """SELECT name FROM sqlite_schema
               WHERE name IN ('story_group_enrichment','story_group_enrichment_target_idx')"""
        )
    }
    return names != {"story_group_enrichment", "story_group_enrichment_target_idx"}


def _migrate_v4_enrichment_extension(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS story_group_enrichment (
            target_kind TEXT NOT NULL CHECK (target_kind IN ('arc','event')),
            target_id TEXT NOT NULL,
            characters_json BLOB NOT NULL,
            importance TEXT NOT NULL
                CHECK (importance IN ('supporting','major','turning point')),
            outcomes_json BLOB NOT NULL,
            promoted_fact_ids_json BLOB NOT NULL,
            warnings_json BLOB NOT NULL,
            PRIMARY KEY (target_kind, target_id)
        ) STRICT"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS story_group_enrichment_target_idx
           ON story_group_enrichment(target_kind, target_id)"""
    )
    connection.execute(
        "INSERT OR REPLACE INTO schema_migrations(version, applied_utc) VALUES (4, ?)",
        (utc_now(),),
    )


def _migrate_to_v4(connection: sqlite3.Connection) -> None:
    statements = (
        """CREATE TABLE IF NOT EXISTS organization_runs (
            run_id TEXT PRIMARY KEY NOT NULL, provider_mode TEXT NOT NULL,
            model_profile TEXT NOT NULL, model_fingerprint TEXT, prompt_version TEXT NOT NULL,
            output_schema_version TEXT NOT NULL, generation TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('running','completed','failed','cancelled')),
            started_utc TEXT NOT NULL, completed_utc TEXT, elapsed_ms INTEGER,
            usage_json BLOB NOT NULL, sanitized_failure TEXT,
            CHECK (elapsed_ms IS NULL OR elapsed_ms >= 0)
        ) STRICT""",
        """CREATE TABLE IF NOT EXISTS organization_cache (
            cache_key TEXT PRIMARY KEY NOT NULL, provider_mode TEXT NOT NULL,
            model_profile TEXT NOT NULL CHECK (length(trim(model_profile)) > 0),
            model_fingerprint TEXT NOT NULL, prompt_version TEXT NOT NULL,
            output_schema_version TEXT NOT NULL, input_hash TEXT NOT NULL,
            ordered_ids_hash TEXT NOT NULL, result_json BLOB NOT NULL, result_hash TEXT NOT NULL,
            created_utc TEXT NOT NULL, last_used_utc TEXT NOT NULL,
            hit_count INTEGER NOT NULL CHECK (hit_count >= 0)
        ) STRICT""",
        """CREATE TABLE IF NOT EXISTS organization_chunks (
            chunk_id TEXT PRIMARY KEY NOT NULL, run_id TEXT NOT NULL, scope_id TEXT NOT NULL,
            reconciliation_scope TEXT NOT NULL, ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
            input_hash TEXT NOT NULL, ordered_ids_hash TEXT NOT NULL, cache_key TEXT,
            cache_state TEXT NOT NULL CHECK (cache_state IN ('miss','hit','stored','bypassed')),
            status TEXT NOT NULL
                CHECK (status IN ('pending','validated','rejected','failed','cancelled')),
            result_json BLOB, result_hash TEXT,
            FOREIGN KEY (run_id) REFERENCES organization_runs(run_id) ON DELETE CASCADE,
            FOREIGN KEY (cache_key) REFERENCES organization_cache(cache_key) ON DELETE SET NULL,
            UNIQUE (run_id, ordinal)
        ) STRICT""",
        """CREATE TABLE IF NOT EXISTS organization_drafts (
            draft_id TEXT PRIMARY KEY NOT NULL, run_id TEXT NOT NULL UNIQUE,
            generation TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('pending','applied','discarded')),
            candidate_json BLOB NOT NULL, candidate_hash TEXT NOT NULL, created_utc TEXT NOT NULL,
            resolved_utc TEXT,
            FOREIGN KEY (run_id) REFERENCES organization_runs(run_id) ON DELETE CASCADE
        ) STRICT""",
        """CREATE TABLE IF NOT EXISTS organization_draft_reviews (
            draft_id TEXT NOT NULL,
            target_kind TEXT NOT NULL CHECK (target_kind IN ('arc','event')),
            target_id TEXT NOT NULL,
            decision TEXT NOT NULL CHECK (decision IN ('approved','rejected')),
            reviewed_utc TEXT NOT NULL,
            PRIMARY KEY (draft_id, target_kind, target_id),
            FOREIGN KEY (draft_id) REFERENCES organization_drafts(draft_id) ON DELETE CASCADE
        ) STRICT""",
        """CREATE TABLE IF NOT EXISTS story_arcs (
            arc_id TEXT PRIMARY KEY NOT NULL,
            title TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 80),
            summary TEXT NOT NULL CHECK (length(trim(summary)) BETWEEN 1 AND 320),
            sort_order INTEGER NOT NULL CHECK (sort_order >= 0),
            origin TEXT NOT NULL CHECK (origin IN ('ai','deterministic','user')),
            pinned INTEGER NOT NULL CHECK (pinned IN (0,1)),
            hidden INTEGER NOT NULL CHECK (hidden IN (0,1)),
            approval_state TEXT NOT NULL
                CHECK (approval_state IN ('pending','approved','rejected')),
            needs_review INTEGER NOT NULL CHECK (needs_review IN (0,1)),
            generation TEXT NOT NULL, updated_utc TEXT NOT NULL
        ) STRICT""",
        """CREATE TABLE IF NOT EXISTS story_events (
            event_id TEXT PRIMARY KEY NOT NULL,
            title TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 80),
            summary TEXT NOT NULL CHECK (length(trim(summary)) BETWEEN 1 AND 320),
            sort_order INTEGER NOT NULL CHECK (sort_order >= 0),
            origin TEXT NOT NULL CHECK (origin IN ('ai','deterministic','user')),
            pinned INTEGER NOT NULL CHECK (pinned IN (0,1)),
            hidden INTEGER NOT NULL CHECK (hidden IN (0,1)),
            approval_state TEXT NOT NULL
                CHECK (approval_state IN ('pending','approved','rejected')),
            needs_review INTEGER NOT NULL CHECK (needs_review IN (0,1)),
            generation TEXT NOT NULL, updated_utc TEXT NOT NULL
        ) STRICT""",
        """CREATE TABLE IF NOT EXISTS story_event_members (
            event_id TEXT NOT NULL, beat_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
            PRIMARY KEY (event_id, beat_id),
            FOREIGN KEY (event_id) REFERENCES story_events(event_id) ON DELETE CASCADE,
            UNIQUE (event_id, ordinal), UNIQUE (beat_id)
        ) STRICT""",
        """CREATE TABLE IF NOT EXISTS story_arc_members (
            arc_id TEXT NOT NULL, event_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
            PRIMARY KEY (arc_id, event_id),
            FOREIGN KEY (arc_id) REFERENCES story_arcs(arc_id) ON DELETE CASCADE,
            FOREIGN KEY (event_id) REFERENCES story_events(event_id) ON DELETE CASCADE,
            UNIQUE (arc_id, ordinal), UNIQUE (event_id)
        ) STRICT""",
        """CREATE TABLE IF NOT EXISTS story_event_edges (
            edge_id TEXT PRIMARY KEY NOT NULL, source_event_id TEXT NOT NULL,
            target_event_id TEXT NOT NULL, kind TEXT NOT NULL,
            provenance TEXT NOT NULL CHECK (provenance = 'deterministic_quotient'),
            transition_ids_json BLOB NOT NULL,
            FOREIGN KEY (source_event_id) REFERENCES story_events(event_id) ON DELETE CASCADE,
            FOREIGN KEY (target_event_id) REFERENCES story_events(event_id) ON DELETE CASCADE,
            UNIQUE (source_event_id, target_event_id, kind)
        ) STRICT""",
        """CREATE TABLE IF NOT EXISTS story_claims (
            claim_id TEXT PRIMARY KEY NOT NULL, event_id TEXT, arc_id TEXT, text TEXT NOT NULL,
            claim_kind TEXT NOT NULL CHECK (claim_kind IN ('interpretation','outcome','warning')),
            status TEXT NOT NULL CHECK (status IN ('pending','approved','rejected','needs_review')),
            sort_order INTEGER NOT NULL CHECK (sort_order >= 0),
            FOREIGN KEY (event_id) REFERENCES story_events(event_id) ON DELETE CASCADE,
            FOREIGN KEY (arc_id) REFERENCES story_arcs(arc_id) ON DELETE CASCADE,
            CHECK ((event_id IS NULL) <> (arc_id IS NULL))
        ) STRICT""",
        """CREATE TABLE IF NOT EXISTS story_claim_evidence (
            claim_id TEXT NOT NULL, evidence_id TEXT NOT NULL,
            PRIMARY KEY (claim_id, evidence_id),
            FOREIGN KEY (claim_id) REFERENCES story_claims(claim_id) ON DELETE CASCADE
        ) STRICT""",
        """CREATE TABLE IF NOT EXISTS story_group_enrichment (
            target_kind TEXT NOT NULL CHECK (target_kind IN ('arc','event')),
            target_id TEXT NOT NULL,
            characters_json BLOB NOT NULL,
            importance TEXT NOT NULL
                CHECK (importance IN ('supporting','major','turning point')),
            outcomes_json BLOB NOT NULL,
            promoted_fact_ids_json BLOB NOT NULL,
            warnings_json BLOB NOT NULL,
            PRIMARY KEY (target_kind, target_id)
        ) STRICT""",
        """CREATE TABLE IF NOT EXISTS story_edits (
            edit_id TEXT PRIMARY KEY NOT NULL,
            operation TEXT NOT NULL
                CHECK (operation IN (
                    'rename','split','merge','move','hide','pin','approve','reject'
                )),
            target_kind TEXT NOT NULL CHECK (target_kind IN ('arc','event','claim')),
            target_id TEXT NOT NULL, payload_json BLOB NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('applied','needs_review')),
            created_utc TEXT NOT NULL
        ) STRICT""",
        "CREATE INDEX IF NOT EXISTS organization_runs_status_idx "
        "ON organization_runs(status, started_utc)",
        "CREATE INDEX IF NOT EXISTS organization_chunks_run_idx "
        "ON organization_chunks(run_id, ordinal)",
        "CREATE INDEX IF NOT EXISTS organization_chunks_invalidation_idx "
        "ON organization_chunks(reconciliation_scope, input_hash)",
        "CREATE INDEX IF NOT EXISTS organization_cache_lookup_idx "
        "ON organization_cache(provider_mode, model_profile, model_fingerprint, prompt_version, "
        "output_schema_version, input_hash, ordered_ids_hash)",
        "CREATE INDEX IF NOT EXISTS organization_drafts_status_idx "
        "ON organization_drafts(status, created_utc)",
        "CREATE INDEX IF NOT EXISTS organization_draft_reviews_decision_idx "
        "ON organization_draft_reviews(draft_id, decision, target_kind, target_id)",
        "CREATE INDEX IF NOT EXISTS story_arcs_order_idx ON story_arcs(hidden, sort_order, arc_id)",
        "CREATE INDEX IF NOT EXISTS story_events_order_idx "
        "ON story_events(hidden, sort_order, event_id)",
        "CREATE INDEX IF NOT EXISTS story_event_members_beat_idx "
        "ON story_event_members(beat_id, event_id)",
        "CREATE INDEX IF NOT EXISTS story_arc_members_order_idx "
        "ON story_arc_members(arc_id, ordinal, event_id)",
        "CREATE INDEX IF NOT EXISTS story_event_edges_source_idx "
        "ON story_event_edges(source_event_id, kind, target_event_id)",
        "CREATE INDEX IF NOT EXISTS story_event_edges_target_idx "
        "ON story_event_edges(target_event_id, kind, source_event_id)",
        "CREATE INDEX IF NOT EXISTS story_claims_event_idx "
        "ON story_claims(event_id, sort_order, claim_id)",
        "CREATE INDEX IF NOT EXISTS story_claim_evidence_evidence_idx "
        "ON story_claim_evidence(evidence_id, claim_id)",
        "CREATE INDEX IF NOT EXISTS story_group_enrichment_target_idx "
        "ON story_group_enrichment(target_kind, target_id)",
        "CREATE INDEX IF NOT EXISTS story_edits_target_idx "
        "ON story_edits(target_kind, target_id, created_utc)",
    )
    for statement in statements:
        connection.execute(statement)
    connection.execute(
        "INSERT OR REPLACE INTO schema_migrations(version, applied_utc) VALUES (?, ?)",
        (4, utc_now()),
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
