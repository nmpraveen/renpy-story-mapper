"""Durable, privacy-safe generic-payload persistence for M13.

M13 owns advisory narrative artifacts only.  This module deliberately uses the
existing canonical ``payloads`` table rather than adding authority-bearing
tables or changing the SQLite schema version.  Logical records remain
independently keyed, while one validated publication can atomically commit its
job, leaf/ancestor claims, claim edges, artifact, and exact cache reference.

Production envelopes never retain raw prompts, source packets, provider
responses, credentials, or absolute paths.  A small raw debug payload requires
an explicit development-only option and remains bounded and privacy checked.
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


PERSISTENCE_ENVELOPE_SCHEMA: Final = "m13-persistence-envelope-v1"
DEBUG_PAYLOAD_SCHEMA: Final = "m13-debug-payload-v1"
CACHE_ENTRY_SCHEMA: Final = "m13-cache-entry-v1"
MAX_RECORD_ID_CHARS: Final = 512
MAX_DEBUG_BYTES: Final = 65_536

RUNS_COLLECTION: Final = "m13_runs"
CONSENTS_COLLECTION: Final = "m13_consents"
JOBS_COLLECTION: Final = "m13_jobs"
ATTEMPTS_COLLECTION: Final = "m13_attempts"
BATCHES_COLLECTION: Final = "m13_batches"
CLAIMS_COLLECTION: Final = "m13_claims"
CLAIM_EDGES_COLLECTION: Final = "m13_claim_edges"
ARTIFACTS_COLLECTION: Final = "m13_artifacts"
CACHE_COLLECTION: Final = "m13_cache"


class RecordKind(StrEnum):
    """Independently keyed M13 logical record kinds."""

    RUN = "run"
    CONSENT = "consent"
    JOB = "job"
    ATTEMPT = "attempt"
    BATCH = "batch"
    CLAIM = "claim"
    CLAIM_EDGE = "claim_edge"
    ARTIFACT = "artifact"
    CACHE = "cache"


RECORD_COLLECTIONS: Final[Mapping[RecordKind, str]] = {
    RecordKind.RUN: RUNS_COLLECTION,
    RecordKind.CONSENT: CONSENTS_COLLECTION,
    RecordKind.JOB: JOBS_COLLECTION,
    RecordKind.ATTEMPT: ATTEMPTS_COLLECTION,
    RecordKind.BATCH: BATCHES_COLLECTION,
    RecordKind.CLAIM: CLAIMS_COLLECTION,
    RecordKind.CLAIM_EDGE: CLAIM_EDGES_COLLECTION,
    RecordKind.ARTIFACT: ARTIFACTS_COLLECTION,
    RecordKind.CACHE: CACHE_COLLECTION,
}

M13_PAYLOAD_COLLECTIONS: Final = frozenset(RECORD_COLLECTIONS.values())

_IMMUTABLE_KINDS: Final = frozenset(
    {
        RecordKind.CONSENT,
        RecordKind.CLAIM,
        RecordKind.CLAIM_EDGE,
        RecordKind.ARTIFACT,
        RecordKind.CACHE,
    }
)
_PUBLISHED_JOB_STATES: Final = frozenset(
    {"published", "partial", "validated", "complete", "completed", "succeeded"}
)
_UNSUCCESSFUL_ATTEMPT_STATES: Final = frozenset(
    {
        "cancelled",
        "content_refusal",
        "content_refused",
        "failed",
        "hard_limit",
        "malformed",
        "provider_refusal",
        "provider_refused",
        "timed_out",
        "timeout",
        "transient_failure",
    }
)
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_ABSOLUTE_RE: Final = re.compile(r"^[A-Za-z]:[\\/]")

_RAW_KEY_NAMES: Final = frozenset(
    {
        "completeprompt",
        "fullprompt",
        "prompt",
        "prompttext",
        "providerresponse",
        "rawprompt",
        "rawproviderresponse",
        "rawresponse",
        "rawnormalized",
        "rawsourcetext",
        "responsebody",
        "sourcepacket",
        "sourcetext",
        "sourcetextpacket",
    }
)
_SECRET_KEY_NAMES: Final = frozenset(
    {
        "accesstoken",
        "apikey",
        "authorization",
        "authtoken",
        "credential",
        "credentials",
        "password",
        "privatekey",
        "secret",
        "token",
    }
)

SANITIZED_ERROR_MESSAGES: Final[Mapping[str, str]] = {
    "authentication_failed": "The provider authentication was rejected.",
    "authority_stale": "The narrative input is no longer current.",
    "batch_unusable": "The provider batch was unusable and will be split.",
    "budget_exceeded": "The configured provider budget was reached.",
    "cancelled": "The narrative job was cancelled.",
    "content_refusal": "The provider declined this narrative item.",
    "content_refused": "The provider declined this narrative item.",
    "hard_limit": "The configured narrative limit was reached.",
    "internal_error": "The narrative job failed safely.",
    "invalid_output": "The provider returned an unusable narrative item.",
    "malformed": "The provider returned an unusable narrative item.",
    "provider_refusal": "The provider refused this narrative request.",
    "provider_process_failed": "The provider process failed.",
    "provider_refused": "The provider refused this narrative request.",
    "provider_timeout": "The provider did not finish before the timeout.",
    "rate_limited": "The provider temporarily limited this request.",
    "runtime_configuration_rejected": "The provider runtime configuration was rejected.",
    "output_schema_rejected": "The provider rejected the output schema.",
    "timeout": "The provider did not finish before the timeout.",
    "transient_failure": "The provider could not complete this attempt.",
    "transient_provider_error": "The provider could not complete this attempt.",
}


class LookupState(StrEnum):
    """Safe outcome of a durable record or exact-cache lookup."""

    HIT = "hit"
    MISS = "miss"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class DebugRetention:
    """Explicit development-only raw debug retention policy.

    The default is deliberately disabled.  Even enabled debug data cannot hold
    credentials or absolute paths and is capped at ``MAX_DEBUG_BYTES``.
    """

    development_enabled: bool = False
    max_bytes: int = 8_192

    def __post_init__(self) -> None:
        if not 1 <= self.max_bytes <= MAX_DEBUG_BYTES:
            raise ValueError(f"debug max_bytes must be between 1 and {MAX_DEBUG_BYTES}")


DEFAULT_DEBUG_RETENTION: Final = DebugRetention()


@dataclass(frozen=True)
class RecordLookup:
    """One validated read without exposing stale or corrupt payload content."""

    kind: RecordKind
    record_id: str
    state: LookupState
    reason: str
    authority_hash: str | None = None
    payload_hash: str | None = None
    payload: Mapping[str, object] | None = None


@dataclass(frozen=True)
class PersistenceWrite:
    """Result of one independent canonical envelope write."""

    kind: RecordKind
    record_id: str
    authority_hash: str
    payload_hash: str
    reused: bool


@dataclass(frozen=True)
class CacheLookup:
    """Exact cache lookup plus its accepted artifact when safely replayable."""

    state: LookupState
    reason: str
    cache_key: str
    identity_hash: str
    entry: Mapping[str, object] | None = None
    artifact: Mapping[str, object] | None = None


@dataclass(frozen=True)
class ValidatedPublication:
    """One atomically durable validated or partially validated job result."""

    job_id: str
    artifact_id: str
    cache_key: str
    claim_ids: tuple[str, ...]
    claim_edge_ids: tuple[str, ...]
    reused_cache: bool


def sanitized_error(error_code: str) -> dict[str, str]:
    """Return the fixed safe representation for an allowlisted error code."""

    message = SANITIZED_ERROR_MESSAGES.get(error_code)
    if message is None:
        raise ValueError(f"error code is not allowlisted: {error_code!r}")
    return {"code": error_code, "message": message}


def authority_binding_hash(binding: Mapping[str, object]) -> str:
    """Hash a detached, privacy-safe exact M10/M11/M12 authority binding."""

    value = _detached_mapping(binding, "authority binding")
    if not value:
        raise ValueError("authority binding cannot be empty")
    _validate_privacy(value, allow_raw_debug=False)
    return _digest(value)


def cache_identity_hash(identity: Mapping[str, object]) -> str:
    """Hash the complete provider/input/cache identity without model defaults."""

    value = _detached_mapping(identity, "cache identity")
    if not value:
        raise ValueError("cache identity cannot be empty")
    _validate_privacy(value, allow_raw_debug=False)
    return _digest(value)


def cache_record_key(identity: Mapping[str, object]) -> str:
    """Return the exact deterministic generic-payload key for an identity."""

    return f"m13_cache_{cache_identity_hash(identity)}"


class M13Persistence:
    """Canonical M13 record store over the existing generic payload boundary."""

    def __init__(self, project: Project) -> None:
        self._project = project

    def put_run(
        self,
        run_id: str,
        payload: Mapping[str, object],
        *,
        authority_binding: Mapping[str, object],
    ) -> PersistenceWrite:
        return self.put(RecordKind.RUN, run_id, payload, authority_binding=authority_binding)

    def put_consent(
        self,
        consent_id: str,
        payload: Mapping[str, object],
        *,
        authority_binding: Mapping[str, object],
    ) -> PersistenceWrite:
        return self.put(
            RecordKind.CONSENT,
            consent_id,
            payload,
            authority_binding=authority_binding,
        )

    def put_job(
        self,
        job_id: str,
        payload: Mapping[str, object],
        *,
        authority_binding: Mapping[str, object],
    ) -> PersistenceWrite:
        return self.put(RecordKind.JOB, job_id, payload, authority_binding=authority_binding)

    def put_attempt(
        self,
        attempt_id: str,
        payload: Mapping[str, object],
        *,
        authority_binding: Mapping[str, object],
        debug_payload: Mapping[str, object] | None = None,
        debug_retention: DebugRetention = DEFAULT_DEBUG_RETENTION,
    ) -> PersistenceWrite:
        return self.put(
            RecordKind.ATTEMPT,
            attempt_id,
            payload,
            authority_binding=authority_binding,
            debug_payload=debug_payload,
            debug_retention=debug_retention,
        )

    def put_batch(
        self,
        batch_id: str,
        payload: Mapping[str, object],
        *,
        authority_binding: Mapping[str, object],
    ) -> PersistenceWrite:
        return self.put(RecordKind.BATCH, batch_id, payload, authority_binding=authority_binding)

    def put_claim(
        self,
        claim_id: str,
        payload: Mapping[str, object],
        *,
        authority_binding: Mapping[str, object],
    ) -> PersistenceWrite:
        return self.put(RecordKind.CLAIM, claim_id, payload, authority_binding=authority_binding)

    def put_claim_edge(
        self,
        edge_id: str,
        payload: Mapping[str, object],
        *,
        authority_binding: Mapping[str, object],
    ) -> PersistenceWrite:
        return self.put(
            RecordKind.CLAIM_EDGE,
            edge_id,
            payload,
            authority_binding=authority_binding,
        )

    def put_artifact(
        self,
        artifact_id: str,
        payload: Mapping[str, object],
        *,
        authority_binding: Mapping[str, object],
    ) -> PersistenceWrite:
        return self.put(
            RecordKind.ARTIFACT,
            artifact_id,
            payload,
            authority_binding=authority_binding,
        )

    def put(
        self,
        kind: RecordKind,
        record_id: str,
        payload: Mapping[str, object],
        *,
        authority_binding: Mapping[str, object],
        debug_payload: Mapping[str, object] | None = None,
        debug_retention: DebugRetention = DEFAULT_DEBUG_RETENTION,
        cancelled: Callable[[], bool] | None = None,
    ) -> PersistenceWrite:
        """Write one independently keyed envelope; immutable kinds are append-only."""

        envelope = _build_envelope(
            kind,
            record_id,
            payload,
            authority_binding,
            debug_payload=debug_payload,
            debug_retention=debug_retention,
        )
        connection = self._project._require_open()
        _raise_if_cancelled(cancelled)
        with storage.transaction(connection):
            reused = self._check_existing(
                kind,
                record_id,
                envelope,
                immutable=kind in _IMMUTABLE_KINDS,
            )
            if not reused:
                self._project._write_payloads_in_transaction(
                    (PayloadRecord(RECORD_COLLECTIONS[kind], record_id, envelope),),
                    cancelled=cancelled,
                )
            _raise_if_cancelled(cancelled)
        return PersistenceWrite(
            kind,
            record_id,
            str(envelope["authority_hash"]),
            str(envelope["payload_hash"]),
            reused,
        )

    def lookup(
        self,
        kind: RecordKind,
        record_id: str,
        *,
        authority_binding: Mapping[str, object] | None = None,
    ) -> RecordLookup:
        """Read one validated record, fail-closing on corruption or stale authority."""

        _validate_record_id(record_id)
        expected_authority_hash = (
            None if authority_binding is None else authority_binding_hash(authority_binding)
        )
        try:
            raw = self._project.payload(RECORD_COLLECTIONS[kind], record_id)
        except storage.ProjectStorageError:
            return RecordLookup(kind, record_id, LookupState.UNAVAILABLE, "corrupt_payload")
        if raw is None:
            return RecordLookup(kind, record_id, LookupState.MISS, "not_found")
        try:
            envelope = _decode_envelope(raw, kind, record_id)
        except storage.ProjectStorageError:
            return RecordLookup(kind, record_id, LookupState.UNAVAILABLE, "corrupt_envelope")
        authority_hash = str(envelope["authority_hash"])
        payload_hash = str(envelope["payload_hash"])
        if expected_authority_hash is not None and authority_hash != expected_authority_hash:
            return RecordLookup(
                kind,
                record_id,
                LookupState.STALE,
                "authority_binding_mismatch",
                authority_hash,
                payload_hash,
            )
        payload = envelope["payload"]
        assert isinstance(payload, dict)
        return RecordLookup(
            kind,
            record_id,
            LookupState.HIT,
            "exact_record_hit",
            authority_hash,
            payload_hash,
            payload,
        )

    def list_records(
        self,
        kind: RecordKind,
        *,
        authority_binding: Mapping[str, object] | None = None,
    ) -> tuple[RecordLookup, ...]:
        """List all keys deterministically, including explicit stale/unavailable states."""

        return tuple(
            self.lookup(kind, key, authority_binding=authority_binding)
            for key in self._project.payload_keys(RECORD_COLLECTIONS[kind])
        )

    def lookup_cache(
        self,
        identity: Mapping[str, object],
        *,
        authority_binding: Mapping[str, object],
        include_artifact: bool = True,
    ) -> CacheLookup:
        """Replay one exact accepted cache entry without invoking any provider."""

        identity_value = _detached_mapping(identity, "cache identity")
        identity_hash = cache_identity_hash(identity_value)
        cache_key = f"m13_cache_{identity_hash}"
        lookup = self.lookup(
            RecordKind.CACHE,
            cache_key,
            authority_binding=authority_binding,
        )
        if lookup.state is not LookupState.HIT or lookup.payload is None:
            return CacheLookup(lookup.state, lookup.reason, cache_key, identity_hash)
        try:
            entry = _validate_cache_entry(lookup.payload, identity_value, identity_hash)
        except storage.ProjectStorageError:
            return CacheLookup(
                LookupState.UNAVAILABLE,
                "corrupt_cache_entry",
                cache_key,
                identity_hash,
            )
        if not include_artifact:
            return CacheLookup(
                LookupState.HIT,
                "exact_cache_hit",
                cache_key,
                identity_hash,
                entry,
            )
        artifact_id = entry.get("artifact_id")
        artifact_payload_hash = entry.get("artifact_payload_hash")
        if not isinstance(artifact_id, str) or not isinstance(artifact_payload_hash, str):
            return CacheLookup(
                LookupState.UNAVAILABLE,
                "corrupt_cache_reference",
                cache_key,
                identity_hash,
            )
        artifact_lookup = self.lookup(
            RecordKind.ARTIFACT,
            artifact_id,
            authority_binding=authority_binding,
        )
        if artifact_lookup.state is not LookupState.HIT or artifact_lookup.payload is None:
            reason = (
                "stale_cache_artifact"
                if artifact_lookup.state is LookupState.STALE
                else "unavailable_cache_artifact"
            )
            return CacheLookup(
                artifact_lookup.state,
                reason,
                cache_key,
                identity_hash,
            )
        if artifact_lookup.payload_hash != artifact_payload_hash:
            return CacheLookup(
                LookupState.UNAVAILABLE,
                "cache_artifact_hash_mismatch",
                cache_key,
                identity_hash,
            )
        return CacheLookup(
            LookupState.HIT,
            "exact_cache_hit",
            cache_key,
            identity_hash,
            entry,
            artifact_lookup.payload,
        )

    def publish_validated(
        self,
        *,
        job_id: str,
        job: Mapping[str, object],
        claims: Mapping[str, Mapping[str, object]],
        claim_edges: Mapping[str, Mapping[str, object]],
        artifact_id: str,
        artifact: Mapping[str, object],
        cache_identity: Mapping[str, object],
        cache_metadata: Mapping[str, object] | None = None,
        attempt_id: str | None = None,
        attempt: Mapping[str, object] | None = None,
        authority_binding: Mapping[str, object],
        cancelled: Callable[[], bool] | None = None,
    ) -> ValidatedPublication:
        """Atomically publish independently keyed validated work and exact cache state.

        Claims and artifacts are immutable.  A collision with different canonical
        bytes fails closed.  Cancellation at any write boundary rolls the entire
        publication back, preserving any prior accepted artifact and cache entry.
        """

        _validate_record_id(job_id)
        _validate_record_id(artifact_id)
        if (attempt_id is None) != (attempt is None):
            raise ValueError("validated attempt ID and payload must be supplied together")
        if attempt_id is not None:
            _validate_record_id(attempt_id)
        claim_ids = tuple(sorted(claims))
        edge_ids = tuple(sorted(claim_edges))
        for record_id in (*claim_ids, *edge_ids):
            _validate_record_id(record_id)
        identity_value = _detached_mapping(cache_identity, "cache identity")
        identity_hash = cache_identity_hash(identity_value)
        cache_key = f"m13_cache_{identity_hash}"

        artifact_envelope = _build_envelope(
            RecordKind.ARTIFACT,
            artifact_id,
            artifact,
            authority_binding,
        )
        artifact_hash = str(artifact_envelope["payload_hash"])
        cache_value = _merge_reserved(
            {} if cache_metadata is None else cache_metadata,
            {
                "schema": CACHE_ENTRY_SCHEMA,
                "cache_identity": identity_value,
                "cache_identity_hash": identity_hash,
                "job_id": job_id,
                "artifact_id": artifact_id,
                "artifact_payload_hash": artifact_hash,
                "claim_ids": list(claim_ids),
                "claim_edge_ids": list(edge_ids),
            },
            label="cache metadata",
        )
        cache_envelope = _build_envelope(
            RecordKind.CACHE,
            cache_key,
            cache_value,
            authority_binding,
        )
        job_value = _merge_reserved(
            job,
            {
                "job_id": job_id,
                "artifact_id": artifact_id,
                "cache_key": cache_key,
                "claim_ids": list(claim_ids),
                "claim_edge_ids": list(edge_ids),
            },
            label="job",
        )
        envelopes: list[tuple[RecordKind, str, dict[str, object], bool]] = [
            (
                RecordKind.CLAIM,
                claim_id,
                _build_envelope(
                    RecordKind.CLAIM,
                    claim_id,
                    claims[claim_id],
                    authority_binding,
                ),
                True,
            )
            for claim_id in claim_ids
        ]
        envelopes.extend(
            (
                RecordKind.CLAIM_EDGE,
                edge_id,
                _build_envelope(
                    RecordKind.CLAIM_EDGE,
                    edge_id,
                    claim_edges[edge_id],
                    authority_binding,
                ),
                True,
            )
            for edge_id in edge_ids
        )
        if attempt_id is not None and attempt is not None:
            envelopes.append(
                (
                    RecordKind.ATTEMPT,
                    attempt_id,
                    _build_envelope(
                        RecordKind.ATTEMPT,
                        attempt_id,
                        attempt,
                        authority_binding,
                    ),
                    True,
                )
            )
        envelopes.extend(
            (
                (
                    RecordKind.ARTIFACT,
                    artifact_id,
                    artifact_envelope,
                    True,
                ),
                (
                    RecordKind.CACHE,
                    cache_key,
                    cache_envelope,
                    True,
                ),
                (
                    RecordKind.JOB,
                    job_id,
                    _build_envelope(
                        RecordKind.JOB,
                        job_id,
                        job_value,
                        authority_binding,
                    ),
                    False,
                ),
            )
        )

        connection = self._project._require_open()
        _raise_if_cancelled(cancelled)
        with storage.transaction(connection):
            reuse_by_kind: dict[tuple[RecordKind, str], bool] = {}
            for kind, record_id, envelope, immutable in envelopes:
                reuse_by_kind[(kind, record_id)] = self._check_existing(
                    kind,
                    record_id,
                    envelope,
                    immutable=immutable,
                )
            records = tuple(
                PayloadRecord(RECORD_COLLECTIONS[kind], record_id, envelope)
                for kind, record_id, envelope, _immutable in envelopes
                if not reuse_by_kind[(kind, record_id)]
            )
            if records:
                self._project._write_payloads_in_transaction(records, cancelled=cancelled)
            _raise_if_cancelled(cancelled)
        return ValidatedPublication(
            job_id,
            artifact_id,
            cache_key,
            claim_ids,
            edge_ids,
            reuse_by_kind[(RecordKind.CACHE, cache_key)],
        )

    def record_unsuccessful_attempt(
        self,
        *,
        job_id: str,
        attempt_id: str,
        status: str,
        error_code: str,
        authority_binding: Mapping[str, object],
        metrics: Mapping[str, object] | None = None,
    ) -> None:
        """Persist one job-local failure/cancellation without erasing last-good work."""

        _validate_record_id(job_id)
        _validate_record_id(attempt_id)
        if status not in _UNSUCCESSFUL_ATTEMPT_STATES:
            raise ValueError(f"unsupported unsuccessful attempt status: {status!r}")
        safe_error = sanitized_error(error_code)
        attempt = {
            "attempt_id": attempt_id,
            "job_id": job_id,
            "status": status,
            "error": safe_error,
            "metrics": {} if metrics is None else dict(metrics),
        }
        attempt_envelope = _build_envelope(
            RecordKind.ATTEMPT,
            attempt_id,
            attempt,
            authority_binding,
        )
        current = self.lookup(
            RecordKind.JOB,
            job_id,
            authority_binding=authority_binding,
        )
        if current.state is LookupState.UNAVAILABLE:
            raise storage.ProjectCorruptError("existing M13 job envelope is unavailable")
        if current.state is LookupState.STALE:
            raise storage.ProjectCorruptError("existing M13 job has different authority binding")
        if current.payload is None:
            job_value: dict[str, object] = {
                "job_id": job_id,
                "status": status,
                "latest_attempt_id": attempt_id,
                "latest_error": safe_error,
            }
        else:
            job_value = dict(current.payload)
            prior_status = job_value.get("status")
            job_value["latest_attempt_id"] = attempt_id
            job_value["latest_attempt_status"] = status
            job_value["latest_error"] = safe_error
            if not isinstance(prior_status, str) or prior_status not in _PUBLISHED_JOB_STATES:
                job_value["status"] = status
        job_envelope = _build_envelope(
            RecordKind.JOB,
            job_id,
            job_value,
            authority_binding,
        )
        connection = self._project._require_open()
        with storage.transaction(connection):
            reused_attempt = self._check_existing(
                RecordKind.ATTEMPT,
                attempt_id,
                attempt_envelope,
                immutable=True,
            )
            records = [PayloadRecord(JOBS_COLLECTION, job_id, job_envelope)]
            if not reused_attempt:
                records.insert(0, PayloadRecord(ATTEMPTS_COLLECTION, attempt_id, attempt_envelope))
            self._project._write_payloads_in_transaction(tuple(records))

    def _check_existing(
        self,
        kind: RecordKind,
        record_id: str,
        envelope: Mapping[str, object],
        *,
        immutable: bool,
    ) -> bool:
        raw = self._project.payload(RECORD_COLLECTIONS[kind], record_id)
        if raw is None:
            return False
        existing = _decode_envelope(raw, kind, record_id)
        if existing.get("authority_hash") != envelope.get("authority_hash"):
            raise storage.ProjectCorruptError(
                f"M13 {kind.value} key resolves to a different authority binding"
            )
        if storage.canonical_json(existing) == storage.canonical_json(envelope):
            return True
        if immutable:
            raise storage.ProjectCorruptError(
                f"M13 {kind.value} key resolves to different canonical bytes"
            )
        return False


def _build_envelope(
    kind: RecordKind,
    record_id: str,
    payload: Mapping[str, object],
    authority_binding: Mapping[str, object],
    *,
    debug_payload: Mapping[str, object] | None = None,
    debug_retention: DebugRetention = DEFAULT_DEBUG_RETENTION,
) -> dict[str, object]:
    _validate_record_id(record_id)
    binding = _detached_mapping(authority_binding, "authority binding")
    binding_hash = authority_binding_hash(binding)
    value = _detached_mapping(payload, f"{kind.value} payload")
    _validate_privacy(value, allow_raw_debug=False)
    envelope: dict[str, object] = {
        "schema": PERSISTENCE_ENVELOPE_SCHEMA,
        "record_kind": kind.value,
        "record_id": record_id,
        "authority": binding,
        "authority_hash": binding_hash,
        "payload": value,
        "payload_hash": _digest(value),
    }
    if debug_payload is not None:
        if not debug_retention.development_enabled:
            raise ValueError("raw debug retention is disabled")
        debug = _detached_mapping(debug_payload, "debug payload")
        _validate_privacy(debug, allow_raw_debug=True)
        debug_bytes = storage.canonical_json(debug)
        if len(debug_bytes) > debug_retention.max_bytes:
            raise ValueError("debug payload exceeds the configured byte limit")
        envelope["debug"] = {
            "schema": DEBUG_PAYLOAD_SCHEMA,
            "max_bytes": debug_retention.max_bytes,
            "payload": debug,
            "payload_hash": hashlib.sha256(debug_bytes).hexdigest(),
        }
    storage.canonical_json(envelope)
    return envelope


def _decode_envelope(
    raw: object,
    expected_kind: RecordKind,
    expected_record_id: str,
) -> dict[str, object]:
    if not isinstance(raw, Mapping):
        raise storage.ProjectCorruptError("M13 payload envelope is not an object")
    root = _detached_mapping(raw, "M13 payload envelope")
    expected_fields = {
        "schema",
        "record_kind",
        "record_id",
        "authority",
        "authority_hash",
        "payload",
        "payload_hash",
    }
    if "debug" in root:
        expected_fields.add("debug")
    if set(root) != expected_fields:
        raise storage.ProjectCorruptError("M13 payload envelope fields are invalid")
    if (
        root.get("schema") != PERSISTENCE_ENVELOPE_SCHEMA
        or root.get("record_kind") != expected_kind.value
        or root.get("record_id") != expected_record_id
    ):
        raise storage.ProjectCorruptError("M13 payload envelope binding is invalid")
    authority = root.get("authority")
    payload = root.get("payload")
    authority_hash = root.get("authority_hash")
    payload_hash = root.get("payload_hash")
    if not isinstance(authority, Mapping) or not isinstance(payload, Mapping):
        raise storage.ProjectCorruptError("M13 envelope authority or payload is invalid")
    if not isinstance(authority_hash, str) or not isinstance(payload_hash, str):
        raise storage.ProjectCorruptError("M13 envelope hashes are invalid")
    if not _SHA256_RE.fullmatch(authority_hash) or not _SHA256_RE.fullmatch(payload_hash):
        raise storage.ProjectCorruptError("M13 envelope hashes are malformed")
    try:
        _validate_privacy(authority, allow_raw_debug=False)
        _validate_privacy(payload, allow_raw_debug=False)
        actual_authority_hash = authority_binding_hash(authority)
        actual_payload_hash = _digest(payload)
    except (TypeError, ValueError) as exc:
        raise storage.ProjectCorruptError("M13 envelope content is unsafe") from exc
    if authority_hash != actual_authority_hash or payload_hash != actual_payload_hash:
        raise storage.ProjectCorruptError("M13 envelope content hash does not match")
    if "debug" in root:
        _validate_debug_envelope(root["debug"])
    return root


def _validate_debug_envelope(raw: object) -> None:
    if not isinstance(raw, Mapping) or set(raw) != {
        "schema",
        "max_bytes",
        "payload",
        "payload_hash",
    }:
        raise storage.ProjectCorruptError("M13 debug envelope is invalid")
    max_bytes = raw.get("max_bytes")
    payload = raw.get("payload")
    payload_hash = raw.get("payload_hash")
    if (
        raw.get("schema") != DEBUG_PAYLOAD_SCHEMA
        or not isinstance(max_bytes, int)
        or isinstance(max_bytes, bool)
        or not 1 <= max_bytes <= MAX_DEBUG_BYTES
        or not isinstance(payload, Mapping)
        or not isinstance(payload_hash, str)
    ):
        raise storage.ProjectCorruptError("M13 debug envelope metadata is invalid")
    try:
        _validate_privacy(payload, allow_raw_debug=True)
        encoded = storage.canonical_json(payload)
    except (TypeError, ValueError) as exc:
        raise storage.ProjectCorruptError("M13 debug payload is unsafe") from exc
    if len(encoded) > max_bytes or hashlib.sha256(encoded).hexdigest() != payload_hash:
        raise storage.ProjectCorruptError("M13 debug payload bounds or hash are invalid")


def _validate_cache_entry(
    payload: Mapping[str, object],
    expected_identity: Mapping[str, object],
    expected_identity_hash: str,
) -> dict[str, object]:
    entry = _detached_mapping(payload, "cache entry")
    identity = entry.get("cache_identity")
    identity_hash = entry.get("cache_identity_hash")
    if (
        entry.get("schema") != CACHE_ENTRY_SCHEMA
        or not isinstance(identity, Mapping)
        or identity_hash != expected_identity_hash
    ):
        raise storage.ProjectCorruptError("M13 cache identity fields are invalid")
    if storage.canonical_json(identity) != storage.canonical_json(expected_identity):
        raise storage.ProjectCorruptError("M13 cache identity bytes do not match")
    if cache_identity_hash(identity) != expected_identity_hash:
        raise storage.ProjectCorruptError("M13 cache identity hash does not match")
    return entry


def _merge_reserved(
    original: Mapping[str, object],
    reserved: Mapping[str, object],
    *,
    label: str,
) -> dict[str, object]:
    value = _detached_mapping(original, label)
    for key, expected in reserved.items():
        if key in value and storage.canonical_json(value[key]) != storage.canonical_json(expected):
            raise ValueError(f"{label} contains conflicting reserved field {key!r}")
        value[key] = expected
    return value


def _detached_mapping(value: Mapping[str, object], label: str) -> dict[str, object]:
    try:
        decoded = storage.decode_json(storage.canonical_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain canonical JSON data") from exc
    if not isinstance(decoded, dict):
        raise TypeError(f"{label} must be an object")
    return decoded


def _digest(value: object) -> str:
    return hashlib.sha256(storage.canonical_json(value)).hexdigest()


def _validate_record_id(record_id: str) -> None:
    if (
        not isinstance(record_id, str)
        or not record_id
        or len(record_id) > MAX_RECORD_ID_CHARS
        or "\x00" in record_id
        or _looks_like_absolute_path(record_id)
    ):
        raise ValueError("M13 record ID must be a bounded non-path string")


def _normalized_key(key: str) -> str:
    return "".join(character for character in key.casefold() if character.isalnum())


def _validate_privacy(value: object, *, allow_raw_debug: bool) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("stored JSON object keys must be strings")
            normalized = _normalized_key(key)
            if normalized in _SECRET_KEY_NAMES:
                raise ValueError(f"credential-like field cannot be persisted: {key!r}")
            if not allow_raw_debug and normalized in _RAW_KEY_NAMES:
                raise ValueError(f"raw provider/source field cannot be persisted: {key!r}")
            if normalized in {"error", "sanitizederror", "latesterror"}:
                if child is not None:
                    _validate_sanitized_error(child)
            elif (
                normalized in {"errorcode", "sanitizederrorcode"}
                and child is not None
                and (not isinstance(child, str) or child not in SANITIZED_ERROR_MESSAGES)
            ):
                raise ValueError("stored error_code must be allowlisted")
            _validate_privacy(child, allow_raw_debug=allow_raw_debug)
        return
    if isinstance(value, list | tuple):
        for child in value:
            _validate_privacy(child, allow_raw_debug=allow_raw_debug)
        return
    if isinstance(value, str) and _looks_like_absolute_path(value):
        raise ValueError("absolute filesystem paths cannot be persisted in M13 data")


def _validate_sanitized_error(value: object) -> None:
    if not isinstance(value, Mapping) or set(value) != {"code", "message"}:
        raise ValueError("stored error must use the sanitized error shape")
    code = value.get("code")
    message = value.get("message")
    if not isinstance(code, str) or SANITIZED_ERROR_MESSAGES.get(code) != message:
        raise ValueError("stored error must use an allowlisted fixed message")


def _looks_like_absolute_path(value: str) -> bool:
    return value.startswith(("/", "\\\\")) or _WINDOWS_ABSOLUTE_RE.match(value) is not None


def _raise_if_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise storage.ProjectOperationCancelled("M13 persistence operation was cancelled")
