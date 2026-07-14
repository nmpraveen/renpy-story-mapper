"""Durable SQLite project lifecycle and incremental refresh API."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

from renpy_story_mapper import storage

_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
PROJECT_SCHEMA_VERSION: Final = storage.SCHEMA_VERSION
ProjectCancelledError = storage.ProjectOperationCancelled
ProjectCorruptionError = storage.ProjectCorruptError
IncompatibleProjectVersionError = storage.IncompatibleProjectVersionError

if TYPE_CHECKING:
    from renpy_story_mapper.ingestion.contracts import IngestionResult
    from renpy_story_mapper.m07_model import M07ModelService
    from renpy_story_mapper.presentation import PresentationService
    from renpy_story_mapper.story_organization import StoryOrganizationService


@dataclass(frozen=True)
class SourceFingerprint:
    """An inert source identity; content itself is deliberately not persisted."""

    path: str
    content_hash: str
    size_bytes: int
    modified_ns: int | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized = _normalize_source_path(self.path)
        object.__setattr__(self, "path", normalized)
        if not _SHA256_RE.fullmatch(self.content_hash):
            raise ValueError("content_hash must be a lowercase SHA-256 digest")
        if self.size_bytes < 0:
            raise ValueError("size_bytes cannot be negative")
        storage.canonical_json(dict(self.metadata))

    @classmethod
    def from_bytes(
        cls,
        path: str,
        content: bytes,
        *,
        modified_ns: int | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> SourceFingerprint:
        return cls(
            path=path,
            content_hash=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            modified_ns=modified_ns,
            metadata={} if metadata is None else metadata,
        )


@dataclass(frozen=True)
class PayloadRecord:
    collection: str
    key: str
    value: object
    source_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        storage.check_collection(self.collection)
        if not self.key or "\x00" in self.key:
            raise ValueError("payload key must be non-empty and cannot contain NUL")
        normalized = tuple(sorted({_normalize_source_path(path) for path in self.source_paths}))
        object.__setattr__(self, "source_paths", normalized)
        storage.canonical_json(self.value)


@dataclass(frozen=True)
class RefreshResult:
    changed: tuple[str, ...]
    unchanged: tuple[str, ...]
    removed: tuple[str, ...]
    invalidated_payloads: int

    @property
    def needs_analysis(self) -> tuple[str, ...]:
        return self.changed


@dataclass(frozen=True)
class RefreshReport:
    parsed_sources: tuple[str, ...]
    reused_sources: tuple[str, ...]
    invalidated_sources: tuple[str, ...]
    removed_sources: tuple[str, ...] = ()


class Project:
    """An open local project with atomic lifecycle and canonical payload storage."""

    def __init__(self, path: Path, connection: sqlite3.Connection) -> None:
        self.path = path
        self._connection: sqlite3.Connection | None = connection

    @classmethod
    def create(
        cls,
        path: str | os.PathLike[str],
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> Project:
        destination = Path(path).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(f"project already exists: {destination}")
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        connection: sqlite3.Connection | None = None
        try:
            connection = storage.connect(temporary)
            storage.initialize_database(connection)
            with storage.transaction(connection):
                now = storage.utc_now()
                initial: dict[str, object] = {
                    "project_id": uuid.uuid4().hex,
                    "created_utc": now,
                }
                if metadata is not None:
                    initial.update(metadata)
                _set_metadata(connection, initial, now=now)
            connection.close()
            connection = None
            temporary.replace(destination)
            return cls.open(destination)
        except BaseException:
            if connection is not None:
                connection.close()
            if temporary.exists():
                temporary.unlink()
            raise

    @classmethod
    def open(cls, path: str | os.PathLike[str], *, migrate: bool = True) -> Project:
        project_path = Path(path).resolve()
        if not project_path.is_file():
            raise FileNotFoundError(f"project does not exist: {project_path}")
        connection: sqlite3.Connection | None = None
        try:
            connection = storage.connect(project_path)
            version = storage.validate_database(connection, allow_legacy_v4=True)
            needs_v4_extension = storage.needs_v4_enrichment_extension(connection)
            if version < storage.SCHEMA_VERSION or needs_v4_extension:
                if not migrate:
                    raise storage.IncompatibleProjectVersionError(
                        f"project schema version {version} requires migration to "
                        f"{storage.SCHEMA_VERSION}"
                    )
                connection.close()
                connection = None
                backup = project_path.with_name(f"{project_path.name}.pre-migrate-v{version}.bak")
                storage.make_backup(project_path, backup, allow_legacy_v4=needs_v4_extension)
                connection = storage.connect(project_path)
                storage.initialize_database(connection)
                storage.validate_database(connection)
            return cls(project_path, connection)
        except sqlite3.DatabaseError as exc:
            if connection is not None:
                connection.close()
            raise storage.ProjectCorruptError("project could not be opened safely") from exc
        except BaseException:
            if connection is not None:
                connection.close()
            raise

    @property
    def schema_version(self) -> int:
        connection = self._require_open()
        row = connection.execute("PRAGMA user_version").fetchone()
        assert row is not None
        return int(row[0])

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> Project:
        self._require_open()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def metadata(self) -> dict[str, object]:
        rows = self._require_open().execute(
            "SELECT key, value_json FROM project_metadata ORDER BY key"
        )
        return {str(row["key"]): storage.decode_json(row["value_json"]) for row in rows}

    def set_metadata(self, values: Mapping[str, object]) -> None:
        connection = self._require_open()
        with storage.transaction(connection):
            _set_metadata(connection, values, now=storage.utc_now())

    def sources(self) -> tuple[SourceFingerprint, ...]:
        rows = self._require_open().execute(
            """
            SELECT path, content_hash, size_bytes, modified_ns, metadata_json
            FROM sources ORDER BY path
            """
        )
        result: list[SourceFingerprint] = []
        for row in rows:
            metadata = storage.decode_json(row["metadata_json"])
            if not isinstance(metadata, dict):
                raise storage.ProjectCorruptError("source metadata is not a JSON object")
            result.append(
                SourceFingerprint(
                    path=str(row["path"]),
                    content_hash=str(row["content_hash"]),
                    size_bytes=int(row["size_bytes"]),
                    modified_ns=None if row["modified_ns"] is None else int(row["modified_ns"]),
                    metadata=metadata,
                )
            )
        return tuple(result)

    def replace_ingestion_provenance(self, result: IngestionResult) -> None:
        """Atomically persist schema-v5 derivations, recovery results, and coverage."""

        connection = self._require_open()
        all_sources = (*result.sources, *result.secondary_sources)
        known = {source.path for source in self.sources()}
        incoming = {source.path for source in all_sources}
        if incoming != known:
            raise ValueError("ingestion provenance must exactly cover current project sources")
        now = storage.utc_now()
        with storage.transaction(connection):
            connection.execute("DELETE FROM source_derivations")
            connection.execute("DELETE FROM recovery_results")
            for source in all_sources:
                provenance = source.provenance
                identity = storage.canonical_json(
                    {"source_path": source.path, **provenance.to_dict()}
                )
                derivation_id = f"derivation_{hashlib.sha256(identity).hexdigest()[:24]}"
                connection.execute(
                    """
                    INSERT INTO source_derivations(
                        derivation_id, source_path, source_kind, tier, locator,
                        input_sha256, output_sha256, line_basis, tool_name, tool_version,
                        tool_commit, tool_bundle_sha256, options_json, complete,
                        warnings_json, created_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        derivation_id,
                        source.path,
                        provenance.source_kind,
                        provenance.tier.value,
                        provenance.locator,
                        provenance.input_sha256,
                        provenance.output_sha256,
                        provenance.line_basis,
                        provenance.tool_name,
                        provenance.tool_version,
                        provenance.tool_commit,
                        provenance.tool_bundle_sha256,
                        storage.canonical_json(dict(provenance.options)),
                        int(provenance.complete),
                        storage.canonical_json(list(provenance.warnings)),
                        now,
                    ),
                )
                if provenance.source_kind == "reconstructed":
                    recovery_id = f"recovery_{hashlib.sha256(identity).hexdigest()[:24]}"
                    connection.execute(
                        """
                        INSERT INTO recovery_results(
                            recovery_id, source_path, locator, input_sha256, output_sha256,
                            tool_bundle_sha256, cache_hit, complete, status,
                            sanitized_error, created_utc
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                        """,
                        (
                            recovery_id,
                            source.path,
                            provenance.locator,
                            provenance.input_sha256,
                            provenance.output_sha256,
                            provenance.tool_bundle_sha256,
                            int(provenance.cache_hit),
                            int(provenance.complete),
                            "recovered" if provenance.complete else "partial",
                            now,
                        ),
                    )
            for failure in (*result.recovery_failures, *result.secondary_recovery_failures):
                identity = storage.canonical_json(
                    {
                        "logical_path": failure.logical_path,
                        "locator": failure.locator,
                        "input_sha256": failure.input_sha256,
                        "error_kind": failure.error_kind,
                    }
                )
                recovery_id = f"recovery_{hashlib.sha256(identity).hexdigest()[:24]}"
                connection.execute(
                    """
                    INSERT INTO recovery_results(
                        recovery_id, source_path, locator, input_sha256, output_sha256,
                        tool_bundle_sha256, cache_hit, complete, status,
                        sanitized_error, created_utc
                    ) VALUES (?, NULL, ?, ?, NULL, ?, 0, 0, 'failed', ?, ?)
                    """,
                    (
                        recovery_id,
                        failure.locator,
                        failure.input_sha256,
                        _recovery_bundle_sha256(),
                        failure.sanitized_error,
                        now,
                    ),
                )
            warning = " ".join(result.warnings) if result.warnings else None
            connection.execute(
                """
                INSERT INTO source_coverage(
                    singleton, complete, partial_allowed, ai_transmission_blocked,
                    acknowledged, warning, updated_utc
                ) VALUES (1, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    complete=excluded.complete,
                    partial_allowed=excluded.partial_allowed,
                    ai_transmission_blocked=excluded.ai_transmission_blocked,
                    acknowledged=0,
                    warning=excluded.warning,
                    updated_utc=excluded.updated_utc
                """,
                (
                    int(result.complete),
                    int(not result.complete),
                    int(result.ai_transmission_blocked),
                    warning,
                    now,
                ),
            )

    def source_derivations(self) -> tuple[dict[str, object], ...]:
        rows = self._require_open().execute(
            """
            SELECT source_path, source_kind, tier, locator, input_sha256, output_sha256,
                   line_basis, tool_name, tool_version, tool_commit, tool_bundle_sha256,
                   options_json, complete, warnings_json
            FROM source_derivations ORDER BY source_path
            """
        )
        return tuple(
            {
                "source_path": str(row["source_path"]),
                "source_kind": str(row["source_kind"]),
                "tier": str(row["tier"]),
                "locator": str(row["locator"]),
                "input_sha256": str(row["input_sha256"]),
                "output_sha256": str(row["output_sha256"]),
                "line_basis": str(row["line_basis"]),
                "tool_name": row["tool_name"],
                "tool_version": row["tool_version"],
                "tool_commit": row["tool_commit"],
                "tool_bundle_sha256": row["tool_bundle_sha256"],
                "options": storage.decode_json(row["options_json"]),
                "complete": bool(row["complete"]),
                "warnings": storage.decode_json(row["warnings_json"]),
            }
            for row in rows
        )

    def source_coverage(self) -> dict[str, object]:
        row = (
            self._require_open()
            .execute(
                """SELECT complete, partial_allowed, ai_transmission_blocked, acknowledged, warning,
                          updated_utc
               FROM source_coverage WHERE singleton=1"""
            )
            .fetchone()
        )
        if row is None:
            return {}
        result: dict[str, object] = {
            "complete": bool(row["complete"]),
            "partial_allowed": bool(row["partial_allowed"]),
            "ai_transmission_blocked": bool(row["ai_transmission_blocked"]),
            "acknowledged": bool(row["acknowledged"]),
            "warning": row["warning"],
        }
        token_payload = {**result, "updated_utc": str(row["updated_utc"])}
        result["coverage_token"] = hashlib.sha256(storage.canonical_json(token_payload)).hexdigest()
        return result

    def recovery_results(self) -> tuple[dict[str, object], ...]:
        rows = self._require_open().execute(
            """
            SELECT source_path, locator, input_sha256, output_sha256, tool_bundle_sha256,
                   cache_hit, complete, status, sanitized_error
            FROM recovery_results ORDER BY recovery_id
            """
        )
        return tuple(
            {
                "source_path": row["source_path"],
                "locator": str(row["locator"]),
                "input_sha256": str(row["input_sha256"]),
                "output_sha256": row["output_sha256"],
                "tool_bundle_sha256": str(row["tool_bundle_sha256"]),
                "cache_hit": bool(row["cache_hit"]),
                "complete": bool(row["complete"]),
                "status": str(row["status"]),
                "sanitized_error": row["sanitized_error"],
            }
            for row in rows
        )

    def acknowledge_incomplete_source_coverage(self, *, coverage_token: str | None = None) -> None:
        """Record acknowledgement without silently clearing the persistent warning."""

        connection = self._require_open()
        with storage.transaction(connection):
            coverage = self.source_coverage()
            row = connection.execute(
                "SELECT complete,ai_transmission_blocked FROM source_coverage WHERE singleton=1"
            ).fetchone()
            if row is None or bool(row["complete"]):
                raise ValueError("project does not have incomplete source coverage")
            if not bool(row["ai_transmission_blocked"]):
                raise ValueError("incomplete source coverage was already acknowledged")
            if coverage_token is not None and coverage.get("coverage_token") != coverage_token:
                raise ValueError("source coverage acknowledgement is stale")
            connection.execute(
                """UPDATE source_coverage
                   SET acknowledged=1, ai_transmission_blocked=0, updated_utc=?
                   WHERE singleton=1""",
                (storage.utc_now(),),
            )

    def refresh_sources(
        self,
        sources: Iterable[SourceFingerprint],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> RefreshResult:
        """Refresh an authoritative inventory and invalidate only dependent rows."""

        source_values = tuple(sources)
        incoming = {source.path: source for source in source_values}
        if len(incoming) != len(source_values):
            raise ValueError("source paths must be unique")
        connection = self._require_open()
        existing_rows = connection.execute("SELECT path, content_hash FROM sources").fetchall()
        existing = {str(row["path"]): str(row["content_hash"]) for row in existing_rows}
        changed = tuple(
            sorted(
                path
                for path, source in incoming.items()
                if existing.get(path) != source.content_hash
            )
        )
        unchanged = tuple(
            sorted(
                path
                for path, source in incoming.items()
                if existing.get(path) == source.content_hash
            )
        )
        removed = tuple(sorted(set(existing) - set(incoming)))
        affected = (*changed, *removed)
        _raise_if_cancelled(cancelled)

        invalidated = 0
        with storage.transaction(connection):
            if affected:
                placeholders = ",".join("?" for _ in affected)
                row = connection.execute(
                    f"""
                    SELECT COUNT(*) FROM payloads AS p
                    WHERE EXISTS (
                        SELECT 1 FROM payload_dependencies AS d
                        WHERE d.collection = p.collection
                          AND d.record_key = p.record_key
                          AND d.source_path IN ({placeholders})
                    )
                    """,
                    affected,
                ).fetchone()
                assert row is not None
                invalidated = int(row[0])
                connection.execute(
                    f"""
                    DELETE FROM payloads
                    WHERE EXISTS (
                        SELECT 1 FROM payload_dependencies AS d
                        WHERE d.collection = payloads.collection
                          AND d.record_key = payloads.record_key
                          AND d.source_path IN ({placeholders})
                    )
                    """,
                    affected,
                )
            if removed:
                placeholders = ",".join("?" for _ in removed)
                connection.execute(f"DELETE FROM sources WHERE path IN ({placeholders})", removed)
            now = storage.utc_now()
            for path in changed:
                _raise_if_cancelled(cancelled)
                source = incoming[path]
                connection.execute(
                    """
                    INSERT INTO sources(
                        path, content_hash, size_bytes, modified_ns, metadata_json,
                        refreshed_utc, fingerprint_kind
                    ) VALUES (?, ?, ?, ?, ?, ?, 'sha256')
                    ON CONFLICT(path) DO UPDATE SET
                        content_hash = excluded.content_hash,
                        size_bytes = excluded.size_bytes,
                        modified_ns = excluded.modified_ns,
                        metadata_json = excluded.metadata_json,
                        refreshed_utc = excluded.refreshed_utc,
                        fingerprint_kind = excluded.fingerprint_kind
                    """,
                    (
                        source.path,
                        source.content_hash,
                        source.size_bytes,
                        source.modified_ns,
                        storage.canonical_json(dict(source.metadata)),
                        now,
                    ),
                )
            _raise_if_cancelled(cancelled)
        return RefreshResult(changed, unchanged, removed, invalidated)

    def write_payloads(
        self,
        records: Sequence[PayloadRecord],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        """Write a batch atomically; dependencies must name existing sources."""

        connection = self._require_open()
        _raise_if_cancelled(cancelled)
        with storage.transaction(connection):
            now = storage.utc_now()
            for record in records:
                _raise_if_cancelled(cancelled)
                payload = storage.canonical_json(record.value)
                connection.execute(
                    """
                    INSERT INTO payloads(
                        collection, record_key, payload_json, payload_hash, updated_utc
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(collection, record_key) DO UPDATE SET
                        payload_json = excluded.payload_json,
                        payload_hash = excluded.payload_hash,
                        updated_utc = excluded.updated_utc
                    """,
                    (
                        record.collection,
                        record.key,
                        payload,
                        storage.payload_digest(payload),
                        now,
                    ),
                )
                connection.execute(
                    "DELETE FROM payload_dependencies WHERE collection = ? AND record_key = ?",
                    (record.collection, record.key),
                )
                try:
                    connection.executemany(
                        """
                        INSERT INTO payload_dependencies(collection, record_key, source_path)
                        VALUES (?, ?, ?)
                        """,
                        ((record.collection, record.key, path) for path in record.source_paths),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ValueError(
                        f"payload {record.collection}/{record.key} references an unknown source"
                    ) from exc
            _raise_if_cancelled(cancelled)

    def payload(self, collection: str, key: str) -> object | None:
        storage.check_collection(collection)
        row = (
            self._require_open()
            .execute(
                """
            SELECT payload_json, payload_hash FROM payloads
            WHERE collection = ? AND record_key = ?
            """,
                (collection, key),
            )
            .fetchone()
        )
        if row is None:
            return None
        payload = bytes(row["payload_json"])
        if storage.payload_digest(payload) != row["payload_hash"]:
            raise storage.ProjectCorruptError("payload checksum does not match stored data")
        return storage.decode_json(payload)

    def payload_keys(self, collection: str) -> tuple[str, ...]:
        storage.check_collection(collection)
        rows = self._require_open().execute(
            "SELECT record_key FROM payloads WHERE collection = ? ORDER BY record_key",
            (collection,),
        )
        return tuple(str(row[0]) for row in rows)

    def canonical_export(self) -> bytes:
        """Export all authoritative project data in deterministic byte order."""

        connection = self._require_open()
        payload_rows = connection.execute(
            """
            SELECT collection, record_key, payload_json, payload_hash
            FROM payloads ORDER BY collection, record_key
            """
        ).fetchall()
        dependencies: dict[tuple[str, str], list[str]] = {}
        for row in connection.execute(
            """
            SELECT collection, record_key, source_path FROM payload_dependencies
            ORDER BY collection, record_key, source_path
            """
        ):
            dependencies.setdefault((str(row[0]), str(row[1])), []).append(str(row[2]))
        document = {
            "schema_version": self.schema_version,
            "metadata": self.metadata(),
            "sources": [
                {
                    "path": source.path,
                    "content_hash": source.content_hash,
                    "fingerprint_kind": "sha256",
                    "size_bytes": source.size_bytes,
                    "modified_ns": source.modified_ns,
                    "metadata": dict(source.metadata),
                }
                for source in self.sources()
            ],
            "payloads": [
                {
                    "collection": str(row["collection"]),
                    "key": str(row["record_key"]),
                    "hash": str(row["payload_hash"]),
                    "value": storage.decode_json(row["payload_json"]),
                    "source_paths": dependencies.get(
                        (str(row["collection"]), str(row["record_key"])), []
                    ),
                }
                for row in payload_rows
            ],
        }
        return storage.canonical_json(document)

    def snapshot(self) -> dict[str, object]:
        """Return the deterministic, public authoritative project snapshot."""

        from renpy_story_mapper.project_analysis import project_snapshot

        return project_snapshot(self)

    def update_state_variable(
        self,
        original_name: str,
        *,
        display_name: str | None = None,
        category: str | None = None,
    ) -> None:
        """Persist user-editable state metadata independently of source refreshes."""

        raw = self.payload("state_registry", "authoritative")
        if not isinstance(raw, list):
            raise KeyError(f"state variable does not exist: {original_name}")
        variables: list[dict[str, object]] = []
        found = False
        for item in raw:
            if not isinstance(item, dict):
                raise storage.ProjectCorruptError("state registry contains a non-object record")
            value = dict(item)
            if value.get("original_name") == original_name:
                found = True
                if display_name is not None:
                    if not display_name.strip():
                        raise ValueError("display_name cannot be empty")
                    value["display_name"] = display_name
                if category is not None:
                    if not category.strip():
                        raise ValueError("category cannot be empty")
                    value["category"] = category
                value["user_override"] = True
            variables.append(value)
        if not found:
            raise KeyError(f"state variable does not exist: {original_name}")
        connection = self._require_open()
        self.write_payloads(
            [
                PayloadRecord(
                    "state_registry",
                    "authoritative",
                    variables,
                    tuple(
                        str(row[0])
                        for row in connection.execute(
                            """SELECT source_path FROM payload_dependencies
                               WHERE collection='state_registry'
                                 AND record_key='authoritative'
                               ORDER BY source_path"""
                        )
                    ),
                )
            ]
        )
        with storage.transaction(connection):
            if category is not None:
                connection.execute(
                    "UPDATE presentation_facts SET category = ? WHERE variable = ?",
                    (category, original_name),
                )

    def presentation_service(self) -> PresentationService:
        """Return the bounded, toolkit-neutral presentation query service."""

        from renpy_story_mapper.presentation import PresentationService

        return PresentationService(self)

    def organization_service(self) -> StoryOrganizationService:
        """Return the toolkit-neutral schema-v4 story-organization service."""

        from renpy_story_mapper.story_organization import StoryOrganizationService

        return StoryOrganizationService(self)

    def m07_model_service(self) -> M07ModelService:
        """Return durable M07 scope, accounting, coverage, and assembly contracts."""

        from renpy_story_mapper.m07_model import M07ModelService

        return M07ModelService(self)

    def authoritative_bytes(self) -> bytes:
        """Return byte-stable authoritative data, excluding lifecycle timestamps and IDs."""

        return storage.canonical_json(self.snapshot())

    def backup(self, destination: str | os.PathLike[str]) -> Path:
        backup_path = Path(destination).resolve()
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        storage.make_backup(self.path, backup_path)
        return backup_path

    def delete(self) -> None:
        """Close and remove the project without exposing a partially deleted file."""

        self.close()
        if not self.path.exists():
            return
        staged = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.deleting")
        self.path.replace(staged)
        try:
            staged.unlink()
        except BaseException:
            staged.replace(self.path)
            raise

    @classmethod
    def restore_backup(
        cls,
        backup: str | os.PathLike[str],
        destination: str | os.PathLike[str],
    ) -> Project:
        """Restore a validated backup to a new path, publishing it atomically."""

        backup_path = Path(backup).resolve()
        destination_path = Path(destination).resolve()
        if destination_path.exists():
            raise FileExistsError(f"restore destination already exists: {destination_path}")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        storage.make_backup(backup_path, destination_path)
        return cls.open(destination_path)

    def _require_open(self) -> sqlite3.Connection:
        if self._connection is None:
            raise storage.ProjectStorageError("project is closed")
        return self._connection


def _set_metadata(
    connection: sqlite3.Connection,
    values: Mapping[str, object],
    *,
    now: str,
) -> None:
    for key, value in values.items():
        if not key or "\x00" in key:
            raise ValueError("metadata keys must be non-empty and cannot contain NUL")
        connection.execute(
            """
            INSERT INTO project_metadata(key, value_json, updated_utc) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_utc = excluded.updated_utc
            """,
            (key, storage.canonical_json(value), now),
        )


def _normalize_source_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or ":" in pure.parts[0]
        or any(part in {"", ".", ".."} for part in pure.parts)
        or "\x00" in normalized
    ):
        raise ValueError(f"source path must be a safe relative logical path: {path!r}")
    return pure.as_posix()


def _recovery_bundle_sha256() -> str:
    from renpy_story_mapper.ingestion.runtime import UNRPYC_BUNDLE_SHA256

    return UNRPYC_BUNDLE_SHA256


def _raise_if_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise storage.ProjectOperationCancelled("project operation was cancelled")


def create_project(
    database_path: str | os.PathLike[str],
    source_root: str | os.PathLike[str],
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> Project:
    from renpy_story_mapper.project_analysis import create_folder_project

    return create_folder_project(database_path, source_root, cancel_check=cancel_check)


def open_project(database_path: str | os.PathLike[str]) -> Project:
    return Project.open(database_path)


def create_ingested_project(
    database_path: str | os.PathLike[str],
    input_path: str | os.PathLike[str],
    *,
    entry_label: str = "start",
    options: object | None = None,
    cancel_check: Callable[[], bool] | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> Project:
    """Create through the unified M06 input boundary."""

    from renpy_story_mapper.project_analysis import create_input_project

    return create_input_project(
        database_path,
        input_path,
        entry_label=entry_label,
        options=options,
        cancel_check=cancel_check,
        progress=progress,
    )


def refresh_project(
    database_path: str | os.PathLike[str],
    source_root: str | os.PathLike[str],
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> RefreshReport:
    from renpy_story_mapper.project_analysis import refresh_folder_project

    return refresh_folder_project(database_path, source_root, cancel_check=cancel_check)


def refresh_ingested_project(
    database_path: str | os.PathLike[str],
    input_path: str | os.PathLike[str],
    *,
    options: object | None = None,
    cancel_check: Callable[[], bool] | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> RefreshReport:
    """Refresh through the unified M06 input boundary."""

    from renpy_story_mapper.project_analysis import refresh_input_project

    return refresh_input_project(
        database_path,
        input_path,
        options=options,
        cancel_check=cancel_check,
        progress=progress,
    )


def delete_project(database_path: str | os.PathLike[str]) -> None:
    with Project.open(database_path) as project:
        project.delete()


def create_archive_project(
    database_path: str | os.PathLike[str],
    archive_path: str | os.PathLike[str],
    *,
    entry_label: str = "start",
    cancel_check: Callable[[], bool] | None = None,
) -> Project:
    from renpy_story_mapper.project_analysis import create_rpa_project

    return create_rpa_project(
        database_path,
        archive_path,
        entry_label=entry_label,
        cancel_check=cancel_check,
    )


def refresh_archive_project(
    database_path: str | os.PathLike[str],
    archive_path: str | os.PathLike[str],
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> RefreshReport:
    from renpy_story_mapper.project_analysis import refresh_rpa_project

    return refresh_rpa_project(database_path, archive_path, cancel_check=cancel_check)
