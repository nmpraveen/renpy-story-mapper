"""Durable M07 scope checkpoints, accounting, coverage, and serialized assembly."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from renpy_story_mapper import storage
from renpy_story_mapper.route_map import RouteScope

if TYPE_CHECKING:
    from renpy_story_mapper.project import Project


class CheckpointStatus(StrEnum):
    PENDING = "pending"
    CACHED = "cached"
    IN_FLIGHT = "in_flight"
    VALIDATED = "validated"
    FALLBACK = "fallback"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TRANSITIONS: Mapping[CheckpointStatus, frozenset[CheckpointStatus]] = {
    CheckpointStatus.PENDING: frozenset(
        {CheckpointStatus.CACHED, CheckpointStatus.IN_FLIGHT, CheckpointStatus.CANCELLED}
    ),
    CheckpointStatus.CACHED: frozenset(
        {CheckpointStatus.VALIDATED, CheckpointStatus.FALLBACK, CheckpointStatus.FAILED}
    ),
    CheckpointStatus.IN_FLIGHT: frozenset(
        {
            CheckpointStatus.VALIDATED,
            CheckpointStatus.FALLBACK,
            CheckpointStatus.FAILED,
            CheckpointStatus.CANCELLED,
        }
    ),
    CheckpointStatus.VALIDATED: frozenset({CheckpointStatus.VALIDATED}),
    CheckpointStatus.FALLBACK: frozenset(
        {CheckpointStatus.CACHED, CheckpointStatus.IN_FLIGHT, CheckpointStatus.FALLBACK}
    ),
    CheckpointStatus.FAILED: frozenset(
        {CheckpointStatus.CACHED, CheckpointStatus.IN_FLIGHT, CheckpointStatus.CANCELLED}
    ),
    CheckpointStatus.CANCELLED: frozenset(
        {CheckpointStatus.CACHED, CheckpointStatus.IN_FLIGHT, CheckpointStatus.CANCELLED}
    ),
}


def normalized_cache_key(
    *,
    input_hash: str,
    model_profile: str,
    prompt_version: str,
    output_schema_version: str,
) -> str:
    """Return scope-agnostic cache identity for byte-identical provider inputs."""

    if len(input_hash) != 64:
        raise ValueError("input_hash must be a SHA-256 digest")
    identity = {
        "input_hash": input_hash,
        "model_profile": model_profile,
        "prompt_version": prompt_version,
        "output_schema_version": output_schema_version,
    }
    return hashlib.sha256(storage.canonical_json(identity)).hexdigest()


@dataclass(frozen=True)
class ScopeCheckpoint:
    scope_id: str
    ordinal: int
    input_hash: str
    status: CheckpointStatus
    result: object | None
    result_hash: str | None
    attempts: int
    calls: int
    input_tokens: int
    output_tokens: int
    error_code: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "scope_id": self.scope_id,
            "ordinal": self.ordinal,
            "input_hash": self.input_hash,
            "status": self.status.value,
            "result": self.result,
            "result_hash": self.result_hash,
            "attempts": self.attempts,
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class AttemptAccounting:
    attempt_id: str
    scope_id: str
    ordinal: int
    outcome: str
    calls: int
    input_tokens: int
    output_tokens: int
    elapsed_ms: int
    cached: bool = False


@dataclass(frozen=True)
class CoverageSnapshot:
    total: int
    pending: int
    cached_or_in_flight: int
    validated: int
    fallback: int
    failed: int
    cancelled: int
    calls: int
    input_tokens: int
    output_tokens: int

    @property
    def completed(self) -> int:
        return self.validated + self.fallback

    @property
    def ratio(self) -> float:
        return 1.0 if self.total == 0 else self.completed / self.total

    def to_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "pending": self.pending,
            "cached_or_in_flight": self.cached_or_in_flight,
            "validated": self.validated,
            "fallback": self.fallback,
            "failed": self.failed,
            "cancelled": self.cancelled,
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "completed": self.completed,
            "ratio": self.ratio,
        }


@dataclass(frozen=True)
class Assembly:
    assembly_id: str
    generation: str
    status: str
    payload: Mapping[str, object]
    payload_hash: str
    coverage: CoverageSnapshot

    def to_dict(self) -> dict[str, object]:
        return {
            "assembly_id": self.assembly_id,
            "generation": self.generation,
            "status": self.status,
            "payload": dict(self.payload),
            "payload_hash": self.payload_hash,
            "coverage": self.coverage.to_dict(),
        }


class M07ModelService:
    """Serialized storage boundary used by future AI workers and browser adapters."""

    def __init__(self, project: Project) -> None:
        self._project = project

    def register_scopes(self, scopes: Sequence[RouteScope], *, generation: str) -> None:
        """Atomically replace pending scope definitions without discarding reusable validation."""

        connection = self._project._require_open()
        ordered = sorted(scopes, key=lambda item: (item.ordinal, item.id))
        if len({scope.id for scope in ordered}) != len(ordered):
            raise ValueError("scope IDs must be unique")
        with storage.transaction(connection):
            now = storage.utc_now()
            keep = {scope.id for scope in ordered}
            for scope in ordered:
                scope_json = storage.canonical_json(scope.to_dict())
                row = connection.execute(
                    "SELECT input_hash,status FROM m07_scope_checkpoints WHERE scope_id=?",
                    (scope.id,),
                ).fetchone()
                reusable = (
                    row is not None
                    and str(row["input_hash"]) == scope.input_hash
                    and str(row["status"]) == CheckpointStatus.VALIDATED.value
                )
                if reusable:
                    connection.execute(
                        """UPDATE m07_scope_checkpoints
                           SET ordinal=?,generation=?,scope_json=?,updated_utc=?
                           WHERE scope_id=?""",
                        (scope.ordinal, generation, scope_json, now, scope.id),
                    )
                else:
                    connection.execute(
                        """INSERT INTO m07_scope_checkpoints(
                               scope_id,ordinal,generation,input_hash,scope_json,status,result_json,
                               result_hash,attempts,calls,input_tokens,output_tokens,error_code,
                               updated_utc)
                           VALUES (?,?,?,?,?,'pending',NULL,NULL,0,0,0,0,NULL,?)
                           ON CONFLICT(scope_id) DO UPDATE SET ordinal=excluded.ordinal,
                               generation=excluded.generation,input_hash=excluded.input_hash,
                               scope_json=excluded.scope_json,status='pending',result_json=NULL,
                               result_hash=NULL,attempts=0,calls=0,input_tokens=0,output_tokens=0,
                               error_code=NULL,updated_utc=excluded.updated_utc""",
                        (scope.id, scope.ordinal, generation, scope.input_hash, scope_json, now),
                    )
            rows = connection.execute("SELECT scope_id FROM m07_scope_checkpoints").fetchall()
            stale = [str(row["scope_id"]) for row in rows if str(row["scope_id"]) not in keep]
            connection.executemany(
                "DELETE FROM m07_scope_checkpoints WHERE scope_id=?",
                ((scope_id,) for scope_id in stale),
            )

    def checkpoints(self) -> tuple[ScopeCheckpoint, ...]:
        rows = self._project._require_open().execute(
            "SELECT * FROM m07_scope_checkpoints ORDER BY ordinal,scope_id"
        )
        return tuple(_checkpoint(row) for row in rows)

    def transition(
        self,
        scope_id: str,
        status: CheckpointStatus,
        *,
        result: object | None = None,
        error_code: str | None = None,
    ) -> ScopeCheckpoint:
        connection = self._project._require_open()
        with storage.transaction(connection):
            row = connection.execute(
                "SELECT * FROM m07_scope_checkpoints WHERE scope_id=?", (scope_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown route scope: {scope_id}")
            current = CheckpointStatus(str(row["status"]))
            if status not in _TRANSITIONS[current]:
                raise ValueError(
                    f"invalid checkpoint transition: {current.value} -> {status.value}"
                )
            if status in {CheckpointStatus.VALIDATED, CheckpointStatus.FALLBACK} and result is None:
                raise ValueError("validated and fallback checkpoints require a result")
            result_json = None if result is None else storage.canonical_json(result)
            result_hash = None if result_json is None else hashlib.sha256(result_json).hexdigest()
            connection.execute(
                """UPDATE m07_scope_checkpoints SET status=?,result_json=?,result_hash=?,
                   error_code=?,updated_utc=? WHERE scope_id=?""",
                (status.value, result_json, result_hash, error_code, storage.utc_now(), scope_id),
            )
            updated = connection.execute(
                "SELECT * FROM m07_scope_checkpoints WHERE scope_id=?", (scope_id,)
            ).fetchone()
            assert updated is not None
            return _checkpoint(updated)

    def record_attempt(self, attempt: AttemptAccounting) -> None:
        if (
            min(
                attempt.ordinal,
                attempt.calls,
                attempt.input_tokens,
                attempt.output_tokens,
                attempt.elapsed_ms,
            )
            < 0
        ):
            raise ValueError("attempt accounting cannot be negative")
        connection = self._project._require_open()
        with storage.transaction(connection):
            if (
                connection.execute(
                    "SELECT 1 FROM m07_scope_checkpoints WHERE scope_id=?", (attempt.scope_id,)
                ).fetchone()
                is None
            ):
                raise KeyError(f"unknown route scope: {attempt.scope_id}")
            connection.execute(
                """INSERT INTO m07_provider_attempts(
                   attempt_id,scope_id,ordinal,outcome,calls,input_tokens,output_tokens,elapsed_ms,
                   cached,created_utc) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    attempt.attempt_id,
                    attempt.scope_id,
                    attempt.ordinal,
                    attempt.outcome,
                    attempt.calls,
                    attempt.input_tokens,
                    attempt.output_tokens,
                    attempt.elapsed_ms,
                    int(attempt.cached),
                    storage.utc_now(),
                ),
            )
            connection.execute(
                """UPDATE m07_scope_checkpoints SET attempts=attempts+1,calls=calls+?,
                   input_tokens=input_tokens+?,output_tokens=output_tokens+?,updated_utc=?
                   WHERE scope_id=?""",
                (
                    attempt.calls,
                    attempt.input_tokens,
                    attempt.output_tokens,
                    storage.utc_now(),
                    attempt.scope_id,
                ),
            )

    def coverage(self) -> CoverageSnapshot:
        row = (
            self._project._require_open()
            .execute(
                """SELECT COUNT(*) total,
               SUM(status='pending') pending,
               SUM(status IN ('cached','in_flight')) active,
               SUM(status='validated') validated,SUM(status='fallback') fallback,
               SUM(status='failed') failed,SUM(status='cancelled') cancelled,
               COALESCE(SUM(calls),0) calls,COALESCE(SUM(input_tokens),0) input_tokens,
               COALESCE(SUM(output_tokens),0) output_tokens FROM m07_scope_checkpoints"""
            )
            .fetchone()
        )
        assert row is not None
        return CoverageSnapshot(*(int(row[index] or 0) for index in range(len(row))))

    def set_override(
        self, scope_id: str, *, correction: Mapping[str, object] | None = None, pinned: bool = False
    ) -> None:
        connection = self._project._require_open()
        payload = storage.canonical_json({} if correction is None else dict(correction))
        with storage.transaction(connection):
            connection.execute(
                """INSERT INTO m07_scope_overrides(scope_id,correction_json,pinned,updated_utc)
                   VALUES (?,?,?,?) ON CONFLICT(scope_id) DO UPDATE SET
                   correction_json=excluded.correction_json,pinned=excluded.pinned,
                   updated_utc=excluded.updated_utc""",
                (scope_id, payload, int(pinned), storage.utc_now()),
            )

    def assemble(self, *, generation: str, allow_partial: bool = True) -> Assembly:
        """Serialize deterministic ordinal assembly, independent of worker completion order."""

        connection = self._project._require_open()
        with storage.transaction(connection):
            checkpoints = tuple(
                _checkpoint(row)
                for row in connection.execute(
                    "SELECT * FROM m07_scope_checkpoints ORDER BY ordinal,scope_id"
                )
            )
            incomplete = [
                item
                for item in checkpoints
                if item.status not in {CheckpointStatus.VALIDATED, CheckpointStatus.FALLBACK}
            ]
            if incomplete and not allow_partial:
                raise ValueError("assembly has incomplete scopes")
            overrides = {
                str(row["scope_id"]): (
                    storage.decode_json(row["correction_json"]),
                    bool(row["pinned"]),
                )
                for row in connection.execute("SELECT * FROM m07_scope_overrides")
            }
            items: list[dict[str, object]] = []
            for item in checkpoints:
                correction, pinned = overrides.get(item.scope_id, ({}, False))
                items.append(
                    {
                        "scope_id": item.scope_id,
                        "ordinal": item.ordinal,
                        "status": item.status.value,
                        "result": item.result,
                        "correction": correction,
                        "pinned": pinned,
                    }
                )
            coverage = self.coverage()
            payload: dict[str, object] = {
                "schema_version": 1,
                "generation": generation,
                "partial": bool(incomplete),
                "items": items,
                "coverage": coverage.to_dict(),
            }
            payload_json = storage.canonical_json(payload)
            payload_hash = hashlib.sha256(payload_json).hexdigest()
            assembly_id = f"assembly_{payload_hash[:20]}"
            connection.execute(
                """INSERT INTO m07_assemblies(
                   assembly_id,generation,status,payload_json,payload_hash,coverage_json,created_utc,
                   applied_utc) VALUES (?,?, 'draft',?,?,?,?,NULL)
                   ON CONFLICT(assembly_id) DO UPDATE SET payload_json=excluded.payload_json,
                   payload_hash=excluded.payload_hash,coverage_json=excluded.coverage_json""",
                (
                    assembly_id,
                    generation,
                    payload_json,
                    payload_hash,
                    storage.canonical_json(coverage.to_dict()),
                    storage.utc_now(),
                ),
            )
            return Assembly(assembly_id, generation, "draft", payload, payload_hash, coverage)

    def apply(self, assembly_id: str) -> Assembly:
        connection = self._project._require_open()
        with storage.transaction(connection):
            row = connection.execute(
                "SELECT * FROM m07_assemblies WHERE assembly_id=?", (assembly_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown assembly: {assembly_id}")
            connection.execute(
                "UPDATE m07_assemblies SET status='superseded' WHERE status='applied'"
            )
            connection.execute(
                "UPDATE m07_assemblies SET status='applied',applied_utc=? WHERE assembly_id=?",
                (storage.utc_now(), assembly_id),
            )
            return _assembly(row, status="applied")


def _checkpoint(row: sqlite3.Row) -> ScopeCheckpoint:
    raw = row["result_json"]
    return ScopeCheckpoint(
        str(row["scope_id"]),
        int(row["ordinal"]),
        str(row["input_hash"]),
        CheckpointStatus(str(row["status"])),
        None if raw is None else storage.decode_json(raw),
        None if row["result_hash"] is None else str(row["result_hash"]),
        int(row["attempts"]),
        int(row["calls"]),
        int(row["input_tokens"]),
        int(row["output_tokens"]),
        None if row["error_code"] is None else str(row["error_code"]),
    )


def _assembly(row: sqlite3.Row, *, status: str | None = None) -> Assembly:
    payload = storage.decode_json(row["payload_json"])
    coverage = storage.decode_json(row["coverage_json"])
    if not isinstance(payload, dict) or not isinstance(coverage, dict):
        raise storage.ProjectCorruptError("M07 assembly payload is invalid")
    snapshot = CoverageSnapshot(
        int(coverage["total"]),
        int(coverage["pending"]),
        int(coverage["cached_or_in_flight"]),
        int(coverage["validated"]),
        int(coverage["fallback"]),
        int(coverage["failed"]),
        int(coverage["cancelled"]),
        int(coverage["calls"]),
        int(coverage["input_tokens"]),
        int(coverage["output_tokens"]),
    )
    return Assembly(
        str(row["assembly_id"]),
        str(row["generation"]),
        str(row["status"] if status is None else status),
        payload,
        str(row["payload_hash"]),
        snapshot,
    )
