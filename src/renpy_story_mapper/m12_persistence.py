"""Atomic, exact-key persistence for deterministic M12 route results.

The cache owns no route semantics.  It accepts canonical mappings from the M12
solver, binds them to exact M10/M11 provenance plus a complete deterministic
limit profile, and publishes one inert result envelope transactionally.  A
cancelled, failed, or emergency wall-clock attempt remains an in-memory
diagnostic and can never replace a valid normalized result.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from renpy_story_mapper import storage
from renpy_story_mapper.project import PayloadRecord

if TYPE_CHECKING:
    from renpy_story_mapper.project import Project


ROUTE_RESULTS_COLLECTION: Final = "m12_route_results"
ROUTE_IDENTITY_SCHEMA: Final = "m12-route-cache-identity-v1"
ROUTE_RESULT_ENVELOPE_SCHEMA: Final = "m12-route-result-envelope-v1"
ROUTE_ATTEMPT_SCHEMA: Final = "m12-route-attempt-diagnostic-v1"

REQUIRED_LIMIT_FIELDS: Final = (
    "expanded_states",
    "retained_states",
    "frontier_states",
    "prefix_records",
    "call_depth",
    "repetition_per_transition",
    "alternatives",
    "accounting_units",
)

_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_UNCACHEABLE_STATUSES: Final = frozenset(
    {
        "cancelled",
        "canceled",
        "emergency_abort",
        "emergency_wall_clock_abort",
        "wall_clock_abort",
        "failed",
    }
)
_NEGATIVE_STATUSES: Final = frozenset(
    {
        "state_infeasible",
        "no_route",
        "no_static_route",
        "no_route_in_the_resolved_static_graph",
        "no_route_in_resolved_static_graph",
    }
)
_INCOMPLETE_TERMINATIONS: Final = frozenset(
    {
        "expanded_states",
        "frontier_states",
        "retained_states",
        "prefix_records",
        "call_depth",
        "repetition_per_transition",
        "loop_repetitions",
        "alternatives",
        "accounting_units",
        "memory_units",
        "deterministic_budget",
        "cancelled",
        "canceled",
        "emergency_abort",
        "emergency_wall_clock_abort",
        "wall_clock_abort",
    }
)
_OPERATIONAL_ABORT_TERMINATIONS: Final = frozenset(
    {
        "cancelled",
        "canceled",
        "emergency_abort",
        "emergency_wall_clock",
        "emergency_wall_clock_abort",
        "wall_clock",
        "wall_clock_abort",
        "wall_clock_timeout",
    }
)
_VOLATILE_EXACT_KEYS: Final = frozenset(
    {
        "volatile_metrics",
        "duration",
        "duration_ms",
        "elapsed",
        "elapsed_ms",
        "timestamp",
        "created_utc",
        "updated_utc",
        "started_utc",
        "finished_utc",
        "machine_memory",
        "machine_memory_bytes",
        "observed_memory",
        "observed_memory_bytes",
        "peak_memory",
        "peak_memory_bytes",
        "process_memory",
        "process_memory_bytes",
        "rss",
        "rss_bytes",
        "wall_clock",
        "wall_clock_ms",
    }
)


class RouteCacheState(StrEnum):
    """Outcome of an exact cache lookup."""

    HIT = "hit"
    MISS = "miss"
    UNAVAILABLE = "unavailable"


class AttemptStatus(StrEnum):
    """Operational attempts that never create a normalized cache entry."""

    CANCELLED = "cancelled"
    EMERGENCY_ABORT = "emergency_abort"
    FAILED = "failed"


@dataclass(frozen=True)
class RouteCacheIdentity:
    """Canonical request, limits, solver, and authority identity."""

    cache_key: str
    identity_hash: str
    normalized_bytes: bytes
    document: Mapping[str, object]


@dataclass(frozen=True)
class RouteCacheLookup:
    """Validated lookup result without solver execution."""

    state: RouteCacheState
    reason: str
    identity: RouteCacheIdentity
    result: Mapping[str, object] | None = None
    normalized_bytes: bytes | None = None
    result_hash: str | None = None


@dataclass(frozen=True)
class RoutePublication:
    """One atomically published or exactly reused normalized result."""

    identity: RouteCacheIdentity
    result_hash: str
    normalized_bytes: bytes
    reused: bool


@dataclass(frozen=True)
class RouteAttemptDiagnostic:
    """Uncached operational diagnostic; volatile metrics are allowed here only."""

    identity_hash: str
    status: AttemptStatus
    reason: str
    volatile_metrics: Mapping[str, object]
    schema: str = ROUTE_ATTEMPT_SCHEMA
    cached: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "identity_hash": self.identity_hash,
            "status": self.status.value,
            "reason": self.reason,
            "volatile_metrics": dict(self.volatile_metrics),
            "cached": self.cached,
        }


def route_cache_identity(
    request: Mapping[str, object],
    deterministic_limits: Mapping[str, object],
    *,
    m10_provenance: Mapping[str, object],
    m11_provenance: Mapping[str, object],
    solver_version: str,
) -> RouteCacheIdentity:
    """Build the exact deterministic identity for one target-specific solve."""

    if not solver_version.strip():
        raise ValueError("solver_version cannot be empty")
    request_value = _detached_mapping(request, "route request")
    limits_value = _validate_limit_profile(deterministic_limits)
    m10_value = _validate_m10_provenance(m10_provenance)
    m11_value = _validate_m11_provenance(m11_provenance)
    document: dict[str, object] = {
        "schema": ROUTE_IDENTITY_SCHEMA,
        "solver_version": solver_version,
        "request": request_value,
        "deterministic_limits": limits_value,
        "authority": {
            "m10": m10_value,
            "m11": m11_value,
        },
    }
    normalized = storage.canonical_json(document)
    identity_hash = hashlib.sha256(normalized).hexdigest()
    return RouteCacheIdentity(
        cache_key=f"route:{identity_hash}",
        identity_hash=identity_hash,
        normalized_bytes=normalized,
        document=document,
    )


def normalized_result_bytes(result: Mapping[str, object]) -> bytes:
    """Return deterministic result bytes after removing operational volatility."""

    normalized = normalized_route_result(result)
    return storage.canonical_json(normalized)


def normalized_route_result(result: Mapping[str, object]) -> dict[str, object]:
    """Detach a route result and exclude machine- or wall-clock-dependent fields."""

    stripped = _strip_volatile(dict(result))
    if not isinstance(stripped, dict):  # defensive: the root is always a dict above
        raise TypeError("route result must normalize to an object")
    detached = _detached_mapping(stripped, "route result")
    _validate_cacheable_result(detached)
    return detached


class M12Persistence:
    """Exact-key cache and uncached operational-attempt boundary for M12."""

    def __init__(self, project: Project) -> None:
        self._project = project

    def identity(
        self,
        request: Mapping[str, object],
        deterministic_limits: Mapping[str, object],
        *,
        m10_provenance: Mapping[str, object],
        m11_provenance: Mapping[str, object],
        solver_version: str,
    ) -> RouteCacheIdentity:
        return route_cache_identity(
            request,
            deterministic_limits,
            m10_provenance=m10_provenance,
            m11_provenance=m11_provenance,
            solver_version=solver_version,
        )

    def lookup(self, identity: RouteCacheIdentity) -> RouteCacheLookup:
        """Return a validated hit, an ordinary miss, or a safe corrupt/stale miss."""

        _validate_identity(identity)
        try:
            raw = self._project.payload(ROUTE_RESULTS_COLLECTION, identity.cache_key)
        except storage.ProjectStorageError:
            return RouteCacheLookup(
                RouteCacheState.UNAVAILABLE,
                "corrupt_cache_entry",
                identity,
            )
        if raw is None:
            return RouteCacheLookup(RouteCacheState.MISS, "not_cached", identity)
        try:
            result, normalized, result_hash = _decode_envelope(raw, identity)
        except _StaleEnvelopeError:
            return RouteCacheLookup(RouteCacheState.MISS, "authority_or_request_mismatch", identity)
        except storage.ProjectStorageError:
            return RouteCacheLookup(
                RouteCacheState.UNAVAILABLE,
                "corrupt_cache_entry",
                identity,
            )
        return RouteCacheLookup(
            RouteCacheState.HIT,
            "exact_cache_hit",
            identity,
            result,
            normalized,
            result_hash,
        )

    def publish_result(
        self,
        identity: RouteCacheIdentity,
        result: Mapping[str, object],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> RoutePublication:
        """Atomically publish a cacheable result without replacing conflicting bytes."""

        _validate_identity(identity)
        _raise_if_cancelled(cancelled)
        normalized_result = normalized_route_result(result)
        normalized = storage.canonical_json(normalized_result)
        result_hash = hashlib.sha256(normalized).hexdigest()
        envelope = {
            "schema": ROUTE_RESULT_ENVELOPE_SCHEMA,
            "identity_hash": identity.identity_hash,
            "identity": dict(identity.document),
            "result_hash": result_hash,
            "result": normalized_result,
        }

        connection = self._project._require_open()
        with storage.transaction(connection):
            existing = self._project.payload(ROUTE_RESULTS_COLLECTION, identity.cache_key)
            if existing is not None:
                try:
                    _, existing_bytes, existing_hash = _decode_envelope(existing, identity)
                except _StaleEnvelopeError as exc:
                    raise storage.ProjectCorruptError(
                        "M12 cache key resolves to a different request identity"
                    ) from exc
                if existing_hash != result_hash or existing_bytes != normalized:
                    raise storage.ProjectCorruptError(
                        "M12 cache identity resolves to different normalized result bytes"
                    )
                _raise_if_cancelled(cancelled)
                return RoutePublication(identity, result_hash, normalized, reused=True)

            self._project._write_payloads_in_transaction(
                (PayloadRecord(ROUTE_RESULTS_COLLECTION, identity.cache_key, envelope),),
                cancelled=cancelled,
            )

        return RoutePublication(identity, result_hash, normalized, reused=False)

    def attempt_diagnostic(
        self,
        identity: RouteCacheIdentity,
        status: AttemptStatus,
        reason: str,
        *,
        volatile_metrics: Mapping[str, object] | None = None,
    ) -> RouteAttemptDiagnostic:
        """Create an in-memory attempt diagnostic and deliberately perform no write."""

        _validate_identity(identity)
        if not isinstance(status, AttemptStatus):
            raise TypeError("attempt status must be an AttemptStatus")
        if not reason.strip():
            raise ValueError("attempt reason cannot be empty")
        metrics = _detached_mapping(
            {} if volatile_metrics is None else volatile_metrics,
            "volatile attempt metrics",
        )
        return RouteAttemptDiagnostic(identity.identity_hash, status, reason, metrics)


class _StaleEnvelopeError(storage.ProjectStorageError):
    """A well-formed envelope belongs to a different exact cache identity."""


def _validate_identity(identity: RouteCacheIdentity) -> None:
    document = identity.document
    request = document.get("request")
    limits = document.get("deterministic_limits")
    authority = document.get("authority")
    solver_version = document.get("solver_version")
    if (
        document.get("schema") != ROUTE_IDENTITY_SCHEMA
        or not isinstance(request, Mapping)
        or not isinstance(limits, Mapping)
        or not isinstance(authority, Mapping)
        or not isinstance(solver_version, str)
    ):
        raise ValueError("route cache identity document is invalid")
    m10 = authority.get("m10")
    m11 = authority.get("m11")
    if not isinstance(m10, Mapping) or not isinstance(m11, Mapping):
        raise ValueError("route cache identity authority is invalid")
    rebuilt = route_cache_identity(
        request,
        limits,
        m10_provenance=m10,
        m11_provenance=m11,
        solver_version=solver_version,
    )
    if (
        rebuilt.cache_key != identity.cache_key
        or rebuilt.identity_hash != identity.identity_hash
        or rebuilt.normalized_bytes != identity.normalized_bytes
    ):
        raise ValueError("route cache identity is internally inconsistent")


def _decode_envelope(
    raw: object,
    identity: RouteCacheIdentity,
) -> tuple[Mapping[str, object], bytes, str]:
    if not isinstance(raw, Mapping):
        raise storage.ProjectCorruptError("M12 route envelope is not an object")
    if raw.get("schema") != ROUTE_RESULT_ENVELOPE_SCHEMA:
        raise storage.ProjectCorruptError("M12 route envelope schema is unsupported")
    if raw.get("identity_hash") != identity.identity_hash:
        raise _StaleEnvelopeError("M12 route identity hash does not match")
    stored_identity = raw.get("identity")
    if not isinstance(stored_identity, Mapping):
        raise storage.ProjectCorruptError("M12 route envelope identity is invalid")
    if storage.canonical_json(dict(stored_identity)) != identity.normalized_bytes:
        raise _StaleEnvelopeError("M12 route identity bytes do not match")
    result_hash = raw.get("result_hash")
    if not isinstance(result_hash, str) or not _SHA256_RE.fullmatch(result_hash):
        raise storage.ProjectCorruptError("M12 route result hash is invalid")
    result = raw.get("result")
    if not isinstance(result, Mapping):
        raise storage.ProjectCorruptError("M12 route result is not an object")
    try:
        normalized_result = normalized_route_result(result)
    except (TypeError, ValueError) as exc:
        raise storage.ProjectCorruptError("M12 normalized route result is invalid") from exc
    normalized = storage.canonical_json(normalized_result)
    if hashlib.sha256(normalized).hexdigest() != result_hash:
        raise storage.ProjectCorruptError("M12 normalized route result checksum does not match")
    return normalized_result, normalized, result_hash


def _validate_limit_profile(value: Mapping[str, object]) -> dict[str, object]:
    limits = _detached_mapping(value, "deterministic limit profile")
    version = limits.get("version")
    if isinstance(version, bool) or not isinstance(version, (int, str)):
        raise ValueError("deterministic limit profile version must be an integer or string")
    if isinstance(version, int) and version < 1:
        raise ValueError("deterministic limit profile version must be positive")
    if isinstance(version, str) and not version.strip():
        raise ValueError("deterministic limit profile version cannot be empty")
    missing = [field for field in REQUIRED_LIMIT_FIELDS if field not in limits]
    if missing:
        raise ValueError(f"deterministic limit profile is incomplete: {', '.join(missing)}")
    for field in REQUIRED_LIMIT_FIELDS:
        field_value = limits[field]
        if isinstance(field_value, bool) or not isinstance(field_value, int) or field_value < 1:
            raise ValueError(f"deterministic limit {field} must be a positive integer")
    return limits


def _validate_m10_provenance(value: Mapping[str, object]) -> dict[str, object]:
    provenance = _detached_mapping(value, "M10 provenance")
    _require_text(provenance, "source_generation", "M10 provenance")
    _require_text(provenance, "schema", "M10 provenance")
    _require_version(provenance, "schema_version", "M10 provenance")
    _require_hash(provenance, "canonical_hash", "M10 provenance")
    return provenance


def _validate_m11_provenance(value: Mapping[str, object]) -> dict[str, object]:
    provenance = _detached_mapping(value, "M11 provenance")
    _require_text(provenance, "schema", "M11 provenance")
    _require_version(provenance, "schema_version", "M11 provenance")
    _require_hash(provenance, "model_hash", "M11 provenance")
    return provenance


def _validate_cacheable_result(result: Mapping[str, object]) -> None:
    status = result.get("semantic_status", result.get("status"))
    if not isinstance(status, str) or not status.strip():
        raise ValueError("route result must contain a non-empty semantic status")
    normalized_status = _normalized_token(status)
    if normalized_status in _UNCACHEABLE_STATUSES:
        raise ValueError("cancelled, failed, and emergency-abort attempts are not cacheable")
    limiting_dimension = _limiting_dimension(result)
    raw_complete = result.get("complete")
    if raw_complete is None:
        complete = normalized_status != "incomplete" and not limiting_dimension
    elif isinstance(raw_complete, bool):
        complete = raw_complete
    else:
        raise ValueError("route result complete must be boolean when present")
    termination = _termination_token(result)
    if termination in _OPERATIONAL_ABORT_TERMINATIONS:
        raise ValueError("operational abort attempts cannot publish normalized route results")
    if normalized_status == "incomplete" and complete:
        raise ValueError("an incomplete semantic status cannot be complete")
    if termination in _INCOMPLETE_TERMINATIONS and complete:
        raise ValueError("a deterministic budget or emergency abort cannot be complete")
    if normalized_status in _NEGATIVE_STATUSES and not complete:
        raise ValueError("negative route conclusions require an exhaustive complete result")
    if normalized_status in _NEGATIVE_STATUSES:
        if result.get("exhaustive") is not True:
            raise ValueError("negative route conclusions require exhaustive evidence")
        if result.get("closed_world") is not True:
            raise ValueError("negative route conclusions require closed-world evidence")
        if termination not in {"", "exhaustive"}:
            raise ValueError("negative route conclusions require exhaustive termination")


def _termination_token(result: Mapping[str, object]) -> str:
    raw = result.get("termination_reason")
    if isinstance(raw, str):
        return _normalized_token(raw)
    termination = result.get("termination")
    if isinstance(termination, Mapping):
        kind = termination.get("kind")
        if isinstance(kind, str):
            return _normalized_token(kind)
    return _limiting_dimension(result)


def _limiting_dimension(result: Mapping[str, object]) -> str:
    usage = result.get("budget_usage")
    if not isinstance(usage, Mapping):
        return ""
    raw = usage.get("limiting_dimension")
    return _normalized_token(raw) if isinstance(raw, str) else ""


def _normalized_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _strip_volatile(value: object) -> object:
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("route result object keys must be strings")
            if _is_volatile_key(key):
                continue
            normalized[key] = _strip_volatile(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_strip_volatile(item) for item in value]
    return value


def _is_volatile_key(key: str) -> bool:
    normalized = _normalized_token(key)
    return (
        normalized in _VOLATILE_EXACT_KEYS
        or normalized.endswith("_timestamp")
        or normalized.endswith("_utc")
        or normalized.startswith("duration_")
        or normalized.startswith("elapsed_")
        or normalized.startswith("wall_clock_")
        or normalized.startswith("machine_memory_")
        or normalized.startswith("observed_memory_")
        or normalized.startswith("peak_memory_")
        or normalized.startswith("process_memory_")
        or normalized.startswith("rss_")
    )


def _detached_mapping(value: Mapping[str, object], label: str) -> dict[str, object]:
    try:
        normalized = storage.canonical_json(dict(value))
        decoded = storage.decode_json(normalized)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be canonical JSON") from exc
    if not isinstance(decoded, dict):
        raise TypeError(f"{label} must be an object")
    return decoded


def _require_text(value: Mapping[str, object], key: str, label: str) -> None:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{label} {key} cannot be empty")


def _require_version(value: Mapping[str, object], key: str, label: str) -> None:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, (int, str)):
        raise ValueError(f"{label} {key} must be an integer or string")
    if isinstance(item, int) and item < 1:
        raise ValueError(f"{label} {key} must be positive")
    if isinstance(item, str) and not item.strip():
        raise ValueError(f"{label} {key} cannot be empty")


def _require_hash(value: Mapping[str, object], key: str, label: str) -> None:
    item = value.get(key)
    if not isinstance(item, str) or not _SHA256_RE.fullmatch(item):
        raise ValueError(f"{label} {key} must be a lowercase SHA-256 digest")


def _raise_if_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise storage.ProjectOperationCancelled("M12 result publication was cancelled")
