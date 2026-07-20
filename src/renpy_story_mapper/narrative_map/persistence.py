"""Independent, privacy-safe M15 job and exact-cache persistence."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, cast

from renpy_story_mapper import storage
from renpy_story_mapper.narrative.privacy import validate_privacy_safe_keys
from renpy_story_mapper.narrative.provider import ProviderUsage
from renpy_story_mapper.narrative_map.contracts import JsonValue, canonical_hash
from renpy_story_mapper.narrative_map.provider import (
    PreparedNarrativeJob,
    ProviderJobKind,
    ProviderProfile,
)
from renpy_story_mapper.project import Project

BOUNDARY_JOBS_COLLECTION: Final = "m15_boundary_jobs"
SUMMARY_JOBS_COLLECTION: Final = "m15_event_summary_jobs"
CACHE_COLLECTION: Final = "m15_narrative_cache"
PERSISTENCE_SCHEMA: Final = "m15-narrative-job-envelope-v1"
CACHE_SCHEMA: Final = "m15-narrative-cache-v1"
_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


class NarrativeJobStatus(StrEnum):
    PENDING = "pending"
    VALIDATED = "validated"
    FAILED = "failed"


@dataclass(frozen=True)
class NarrativeJobRecord:
    job_id: str
    kind: ProviderJobKind
    subject_id: str
    input_hash: str
    prompt_version: str
    response_schema: str
    authority_hash: str
    profile_hash: str
    status: NarrativeJobStatus
    attempt_count: int
    result: Mapping[str, object] | None
    provider_identity: Mapping[str, object] | None
    usage: Mapping[str, object] | None
    error_code: str | None


class NarrativeMapRepository:
    """Typed M15 storage over existing atomic canonical payload rows.

    This repository deliberately has no method accepting a prompt, response envelope, source
    packet, credential, or arbitrary debug payload.
    """

    def __init__(self, project: Project) -> None:
        self._project = project

    def stage(self, job: PreparedNarrativeJob, profile: ProviderProfile) -> NarrativeJobRecord:
        existing = self.get(job.kind, job.job_id)
        expected_profile_hash = canonical_hash(profile.to_dict())
        if (
            existing is not None
            and existing.input_hash == job.input_hash
            and existing.profile_hash == expected_profile_hash
            and existing.prompt_version == job.prompt_version
            and existing.response_schema == job.response_schema
        ):
            return existing
        payload = self._envelope(
            job,
            profile,
            status=NarrativeJobStatus.PENDING,
            attempt_count=0,
            result=None,
            provider_identity=None,
            usage=None,
            error_code=None,
        )
        self._write(job.kind, job.job_id, payload)
        return self._decode(payload, job.kind, job.job_id)

    def get(self, kind: ProviderJobKind, job_id: str) -> NarrativeJobRecord | None:
        raw = self._payload(_collection(kind), job_id)
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise storage.ProjectCorruptError("M15 job payload is not an object")
        return self._decode(raw, kind, job_id)

    def list(self, kind: ProviderJobKind) -> tuple[NarrativeJobRecord, ...]:
        return tuple(
            record
            for key in self._keys(_collection(kind))
            for record in (self.get(kind, key),)
            if record is not None
        )

    def record_failure(
        self,
        job: PreparedNarrativeJob,
        profile: ProviderProfile,
        *,
        attempt_count: int,
        error_code: str,
        provider_identity: Mapping[str, object] | None = None,
        usage: ProviderUsage | None = None,
    ) -> NarrativeJobRecord:
        if not _ERROR_CODE.fullmatch(error_code):
            raise ValueError("M15 failure codes must be sanitized identifiers")
        payload = self._envelope(
            job,
            profile,
            status=NarrativeJobStatus.FAILED,
            attempt_count=attempt_count,
            result=None,
            provider_identity=(
                None
                if provider_identity is None
                else _detached_mapping(provider_identity, "failed provider identity")
            ),
            usage=None if usage is None else _usage_payload(usage, attempt_count),
            error_code=error_code,
        )
        self._write(job.kind, job.job_id, payload)
        return self._decode(payload, job.kind, job.job_id)

    def record_validated(
        self,
        job: PreparedNarrativeJob,
        profile: ProviderProfile,
        *,
        attempt_count: int,
        result: Mapping[str, object],
        provider_identity: Mapping[str, object],
        usage: ProviderUsage,
    ) -> NarrativeJobRecord:
        normalized_result = _detached_mapping(result, "validated M15 result")
        normalized_identity = _detached_mapping(provider_identity, "provider identity")
        usage_payload = _usage_payload(usage, attempt_count)
        payload = self._envelope(
            job,
            profile,
            status=NarrativeJobStatus.VALIDATED,
            attempt_count=attempt_count,
            result=normalized_result,
            provider_identity=normalized_identity,
            usage=usage_payload,
            error_code=None,
        )
        cache_key = self.cache_key(job, profile)
        cache_payload: dict[str, object] = {
            "schema": CACHE_SCHEMA,
            "cache_key": cache_key,
            "identity": self.cache_identity(job, profile),
            "result": normalized_result,
            "result_hash": canonical_hash(normalized_result),
            "provider_identity": normalized_identity,
        }
        _validate_durable(cache_payload)
        self._write_payloads(
            (
                (_collection(job.kind), job.job_id, payload),
                (CACHE_COLLECTION, cache_key, cache_payload),
            )
        )
        return self._decode(payload, job.kind, job.job_id)

    def load_cache(
        self, job: PreparedNarrativeJob, profile: ProviderProfile
    ) -> tuple[Mapping[str, object], Mapping[str, object]] | None:
        cache_key = self.cache_key(job, profile)
        raw = self._payload(CACHE_COLLECTION, cache_key)
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise storage.ProjectCorruptError("M15 cache payload is not an object")
        if raw.get("schema") != CACHE_SCHEMA or raw.get("cache_key") != cache_key:
            raise storage.ProjectCorruptError("M15 cache identity is invalid")
        identity = raw.get("identity")
        if not isinstance(identity, Mapping) or storage.canonical_json(
            identity
        ) != storage.canonical_json(self.cache_identity(job, profile)):
            return None
        result = raw.get("result")
        provider_identity = raw.get("provider_identity")
        if not isinstance(result, Mapping) or not isinstance(provider_identity, Mapping):
            raise storage.ProjectCorruptError("M15 cache result is invalid")
        if raw.get("result_hash") != canonical_hash(result):
            raise storage.ProjectCorruptError("M15 cache result checksum is invalid")
        return (
            _detached_mapping(result, "cached M15 result"),
            _detached_mapping(provider_identity, "cached provider identity"),
        )

    @staticmethod
    def cache_identity(
        job: PreparedNarrativeJob, profile: ProviderProfile
    ) -> dict[str, JsonValue]:
        return {
            "kind": job.kind.value,
            "authority": job.authority.to_dict(),
            "subject_id": job.subject_id,
            "input_hash": job.input_hash,
            "provider": profile.to_dict(),
            "prompt_version": job.prompt_version,
            "response_schema": job.response_schema,
        }

    @classmethod
    def cache_key(cls, job: PreparedNarrativeJob, profile: ProviderProfile) -> str:
        return f"m15_cache_{canonical_hash(cls.cache_identity(job, profile))}"

    def _envelope(
        self,
        job: PreparedNarrativeJob,
        profile: ProviderProfile,
        *,
        status: NarrativeJobStatus,
        attempt_count: int,
        result: Mapping[str, object] | None,
        provider_identity: Mapping[str, object] | None,
        usage: Mapping[str, object] | None,
        error_code: str | None,
    ) -> dict[str, object]:
        if attempt_count < 0:
            raise ValueError("M15 attempt counts cannot be negative")
        payload: dict[str, object] = {
            "schema": PERSISTENCE_SCHEMA,
            **job.durable_metadata(),
            "authority_hash": job.authority.identity,
            "profile": profile.to_dict(),
            "profile_hash": canonical_hash(profile.to_dict()),
            "status": status.value,
            "attempt_count": attempt_count,
            "result": result,
            "provider_identity": provider_identity,
            "usage": usage,
            "error_code": error_code,
        }
        _validate_durable(payload)
        return payload

    def _write(self, kind: ProviderJobKind, job_id: str, payload: Mapping[str, object]) -> None:
        _validate_durable(payload)
        self._write_payloads(((_collection(kind), job_id, payload),))

    def _payload(self, collection: str, key: str) -> object | None:
        row = self._project._require_open().execute(
            "SELECT payload_json,payload_hash FROM payloads "
            "WHERE collection=? AND record_key=?",
            (collection, key),
        ).fetchone()
        if row is None:
            return None
        payload = bytes(row["payload_json"])
        if storage.payload_digest(payload) != row["payload_hash"]:
            raise storage.ProjectCorruptError("M15 payload checksum does not match stored data")
        return storage.decode_json(payload)

    def _keys(self, collection: str) -> tuple[str, ...]:
        rows = self._project._require_open().execute(
            "SELECT record_key FROM payloads WHERE collection=? ORDER BY record_key",
            (collection,),
        )
        return tuple(str(row[0]) for row in rows)

    def _write_payloads(
        self, records: tuple[tuple[str, str, Mapping[str, object]], ...]
    ) -> None:
        connection = self._project._require_open()
        now = storage.utc_now()
        with storage.transaction(connection):
            for collection, key, value in records:
                payload = storage.canonical_json(value)
                existing = connection.execute(
                    "SELECT payload_json FROM payloads WHERE collection=? AND record_key=?",
                    (collection, key),
                ).fetchone()
                if (
                    collection == CACHE_COLLECTION
                    and existing is not None
                    and bytes(existing["payload_json"]) != payload
                ):
                    raise storage.ProjectStorageError(
                        "an exact M15 cache identity cannot be overwritten"
                    )
                connection.execute(
                    """
                    INSERT INTO payloads(
                        collection,record_key,payload_json,payload_hash,updated_utc
                    ) VALUES (?,?,?,?,?)
                    ON CONFLICT(collection,record_key) DO UPDATE SET
                        payload_json=excluded.payload_json,
                        payload_hash=excluded.payload_hash,
                        updated_utc=excluded.updated_utc
                    """,
                    (collection, key, payload, storage.payload_digest(payload), now),
                )
                connection.execute(
                    "DELETE FROM payload_dependencies WHERE collection=? AND record_key=?",
                    (collection, key),
                )

    @staticmethod
    def _decode(
        raw: Mapping[str, object], kind: ProviderJobKind, job_id: str
    ) -> NarrativeJobRecord:
        if (
            raw.get("schema") != PERSISTENCE_SCHEMA
            or raw.get("job_id") != job_id
            or raw.get("kind") != kind.value
        ):
            raise storage.ProjectCorruptError("M15 job envelope identity is invalid")
        required_text = (
            "subject_id",
            "input_hash",
            "prompt_version",
            "response_schema",
            "authority_hash",
            "profile_hash",
        )
        if any(not isinstance(raw.get(key), str) or not raw.get(key) for key in required_text):
            raise storage.ProjectCorruptError("M15 job envelope metadata is invalid")
        raw_status = raw.get("status")
        try:
            status = NarrativeJobStatus(raw_status) if isinstance(raw_status, str) else None
        except ValueError:
            raise storage.ProjectCorruptError("M15 job status is invalid") from None
        if status is None:
            raise storage.ProjectCorruptError("M15 job status is invalid")
        attempt_count = raw.get("attempt_count")
        if (
            not isinstance(attempt_count, int)
            or isinstance(attempt_count, bool)
            or attempt_count < 0
        ):
            raise storage.ProjectCorruptError("M15 job attempt count is invalid")
        result = raw.get("result")
        provider_identity = raw.get("provider_identity")
        usage = raw.get("usage")
        if result is not None and not isinstance(result, Mapping):
            raise storage.ProjectCorruptError("M15 validated result is invalid")
        if provider_identity is not None and not isinstance(provider_identity, Mapping):
            raise storage.ProjectCorruptError("M15 provider identity is invalid")
        if usage is not None and not isinstance(usage, Mapping):
            raise storage.ProjectCorruptError("M15 usage is invalid")
        error_code = raw.get("error_code")
        if error_code is not None and (
            not isinstance(error_code, str) or not _ERROR_CODE.fullmatch(error_code)
        ):
            raise storage.ProjectCorruptError("M15 failure code is invalid")
        return NarrativeJobRecord(
            job_id=job_id,
            kind=kind,
            subject_id=cast(str, raw["subject_id"]),
            input_hash=cast(str, raw["input_hash"]),
            prompt_version=cast(str, raw["prompt_version"]),
            response_schema=cast(str, raw["response_schema"]),
            authority_hash=cast(str, raw["authority_hash"]),
            profile_hash=cast(str, raw["profile_hash"]),
            status=status,
            attempt_count=attempt_count,
            result=cast(Mapping[str, object] | None, result),
            provider_identity=cast(Mapping[str, object] | None, provider_identity),
            usage=cast(Mapping[str, object] | None, usage),
            error_code=error_code,
        )


def _collection(kind: ProviderJobKind) -> str:
    return (
        BOUNDARY_JOBS_COLLECTION
        if kind is ProviderJobKind.BOUNDARY
        else SUMMARY_JOBS_COLLECTION
    )


def _detached_mapping(value: Mapping[str, object], label: str) -> dict[str, object]:
    try:
        decoded = storage.decode_json(storage.canonical_json(value))
    except (TypeError, ValueError):
        raise ValueError(f"{label} must contain canonical JSON values") from None
    if not isinstance(decoded, dict):
        raise ValueError(f"{label} must be an object")
    return cast(dict[str, object], decoded)


def _validate_durable(value: object) -> None:
    validate_privacy_safe_keys(value, label="M15 production persistence")
    try:
        storage.canonical_json(value)
    except (TypeError, ValueError):
        raise ValueError("M15 durable values must be finite canonical JSON") from None


def _usage_payload(usage: ProviderUsage, provider_calls: int) -> dict[str, JsonValue]:
    if provider_calls < 1:
        raise ValueError("persisted provider usage requires at least one call")
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "elapsed_ms": usage.elapsed_ms,
        "cost_micros": usage.cost_micros,
        "provider_calls": provider_calls,
    }
