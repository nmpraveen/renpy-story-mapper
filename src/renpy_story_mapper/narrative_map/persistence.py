"""Independent, privacy-safe M15 job and exact-cache persistence."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
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
SEMANTIC_BOUNDARY_JOBS_COLLECTION: Final = "m15_semantic_boundary_jobs"
SEMANTIC_SUMMARY_JOBS_COLLECTION: Final = "m15_semantic_summary_jobs"
CACHE_COLLECTION: Final = "m15_narrative_cache"
SEMANTIC_BUILD_COLLECTION: Final = "m15_semantic_builds"
SEMANTIC_CURRENT_COLLECTION: Final = "m15_semantic_current"
SEMANTIC_CALL_LEDGER_COLLECTION: Final = "m15_semantic_call_ledgers"
PERSISTENCE_SCHEMA: Final = "m15-narrative-job-envelope-v1"
CACHE_SCHEMA: Final = "m15-narrative-cache-v1"
SEMANTIC_CALL_LEDGER_SCHEMA: Final = "m15-semantic-call-ledger-v2"
_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


class NarrativeJobStatus(StrEnum):
    PENDING = "pending"
    VALIDATED = "validated"
    FAILED = "failed"


class SemanticCallLimitError(RuntimeError):
    """The exact durable consent ledger has no remaining call reservation."""


class SemanticManifestClosedError(SemanticCallLimitError):
    """The consent ledger was sealed against every later reservation."""


class SemanticJobAttemptReservedError(RuntimeError):
    """The exact semantic job attempt was already claimed durably."""


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
    provider_calls: int
    result: Mapping[str, object] | None
    provider_identity: Mapping[str, object] | None
    usage: Mapping[str, object] | None
    error_code: str | None
    consent_manifest_id: str | None


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
            provider_calls=0,
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
        provider_calls: int,
        error_code: str,
        provider_identity: Mapping[str, object] | None = None,
        usage: ProviderUsage | None = None,
        consent_manifest_id: str | None = None,
    ) -> NarrativeJobRecord:
        if not _ERROR_CODE.fullmatch(error_code):
            raise ValueError("M15 failure codes must be sanitized identifiers")
        payload = self._envelope(
            job,
            profile,
            status=NarrativeJobStatus.FAILED,
            attempt_count=attempt_count,
            provider_calls=provider_calls,
            result=None,
            provider_identity=(
                None
                if provider_identity is None
                else _detached_mapping(provider_identity, "failed provider identity")
            ),
            usage=None if usage is None else _usage_payload(usage, provider_calls),
            error_code=error_code,
            consent_manifest_id=consent_manifest_id,
        )
        self._write(job.kind, job.job_id, payload)
        return self._decode(payload, job.kind, job.job_id)

    def record_validated(
        self,
        job: PreparedNarrativeJob,
        profile: ProviderProfile,
        *,
        attempt_count: int,
        provider_calls: int,
        result: Mapping[str, object],
        provider_identity: Mapping[str, object],
        usage: ProviderUsage,
        consent_manifest_id: str,
    ) -> NarrativeJobRecord:
        if not consent_manifest_id or consent_manifest_id != consent_manifest_id.strip():
            raise ValueError("validated M15 results require an exact consent manifest identity")
        normalized_result = _detached_mapping(result, "validated M15 result")
        normalized_identity = _detached_mapping(provider_identity, "provider identity")
        usage_payload = _usage_payload(usage, provider_calls)
        payload = self._envelope(
            job,
            profile,
            status=NarrativeJobStatus.VALIDATED,
            attempt_count=attempt_count,
            provider_calls=provider_calls,
            result=normalized_result,
            provider_identity=normalized_identity,
            usage=usage_payload,
            error_code=None,
            consent_manifest_id=consent_manifest_id,
        )
        cache_key = self.cache_key(job, profile)
        cache_payload: dict[str, object] = {
            "schema": CACHE_SCHEMA,
            "cache_key": cache_key,
            "identity": self.cache_identity(job, profile),
            "result": normalized_result,
            "result_hash": canonical_hash(normalized_result),
            "provider_identity": normalized_identity,
            "consent_manifest_id": consent_manifest_id,
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
    ) -> tuple[Mapping[str, object], Mapping[str, object], str | None] | None:
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
        consent_manifest_id = raw.get("consent_manifest_id")
        if not isinstance(result, Mapping) or not isinstance(provider_identity, Mapping):
            raise storage.ProjectCorruptError("M15 cache result is invalid")
        if raw.get("result_hash") != canonical_hash(result):
            raise storage.ProjectCorruptError("M15 cache result checksum is invalid")
        if consent_manifest_id is not None and (
            not isinstance(consent_manifest_id, str) or not consent_manifest_id
        ):
            raise storage.ProjectCorruptError("M15 cache consent manifest identity is invalid")
        return (
            _detached_mapping(result, "cached M15 result"),
            _detached_mapping(provider_identity, "cached provider identity"),
            consent_manifest_id,
        )

    def write_semantic_build(self, payload: Mapping[str, object]) -> None:
        """Persist the one active M15.1 candidate without changing current publication."""

        normalized = _detached_mapping(payload, "semantic build")
        _validate_durable(normalized)
        self._write_payloads(((SEMANTIC_BUILD_COLLECTION, "active", normalized),))

    def write_semantic_build_if_manifest(
        self,
        payload: Mapping[str, object],
        *,
        stage: str,
        manifest_id: str,
    ) -> bool:
        """Persist a build only while the exact stage manifest remains active."""

        normalized = _detached_mapping(payload, "semantic build")
        _validate_durable(normalized)
        return self._write_payloads_if_manifest(
            ((SEMANTIC_BUILD_COLLECTION, "active", normalized),),
            stage=stage,
            manifest_id=manifest_id,
        )

    def read_semantic_build(self) -> Mapping[str, object] | None:
        raw = self._payload(SEMANTIC_BUILD_COLLECTION, "active")
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise storage.ProjectCorruptError("M15.1 semantic build payload is not an object")
        return _detached_mapping(raw, "semantic build")

    def reconcile_semantic_manifests(
        self,
        *,
        stage: str,
        manifest_ids: Sequence[str],
    ) -> Mapping[str, object]:
        """Atomically remember prior manifests whose reservations are all terminal."""

        if stage not in {"boundary", "summary"}:
            raise ValueError("semantic reconciliation stage is invalid")
        if not manifest_ids or any(not item for item in manifest_ids):
            raise ValueError("semantic reconciliation manifest IDs are invalid")
        connection = self._project._require_open()
        now = storage.utc_now()
        with storage.transaction(connection):
            row = connection.execute(
                "SELECT payload_json,payload_hash FROM payloads "
                "WHERE collection=? AND record_key='active'",
                (SEMANTIC_BUILD_COLLECTION,),
            ).fetchone()
            if row is None:
                raise storage.ProjectCorruptError("M15.1 semantic build is missing")
            encoded = bytes(row["payload_json"])
            if storage.payload_digest(encoded) != row["payload_hash"]:
                raise storage.ProjectCorruptError(
                    "M15.1 semantic build checksum does not match stored data"
                )
            decoded = storage.decode_json(encoded)
            if not isinstance(decoded, Mapping):
                raise storage.ProjectCorruptError("M15.1 semantic build is not an object")
            payload = dict(decoded)
            snapshots = payload.get("confirmed_manifests")
            stages = payload.get("confirmed_manifest_stages")
            if not isinstance(snapshots, Mapping) or not isinstance(stages, Mapping):
                raise storage.ProjectCorruptError(
                    "M15.1 confirmed manifest metadata is invalid"
                )
            if any(item not in snapshots or stages.get(item) != stage for item in manifest_ids):
                raise storage.ProjectCorruptError(
                    "M15.1 reconciled manifest does not belong to its stage"
                )
            key = f"{stage}_reconciled_manifest_ids"
            existing = payload.get(key, [])
            if not isinstance(existing, list) or any(
                not isinstance(item, str) or not item for item in existing
            ):
                raise storage.ProjectCorruptError(
                    "M15.1 reconciled manifest checkpoint is invalid"
                )
            payload[key] = list(dict.fromkeys((*existing, *manifest_ids)))
            normalized = _detached_mapping(payload, "semantic build")
            _validate_durable(normalized)
            updated = storage.canonical_json(normalized)
            connection.execute(
                "UPDATE payloads SET payload_json=?,payload_hash=?,updated_utc=? "
                "WHERE collection=? AND record_key='active'",
                (
                    updated,
                    storage.payload_digest(updated),
                    now,
                    SEMANTIC_BUILD_COLLECTION,
                ),
            )
            connection.execute(
                "DELETE FROM payload_dependencies WHERE collection=? AND record_key='active'",
                (SEMANTIC_BUILD_COLLECTION,),
            )
        return normalized

    def publish_semantic_current(
        self,
        *,
        build: Mapping[str, object],
        publication: Mapping[str, object],
    ) -> None:
        """Atomically advance candidate state and the sole current semantic publication."""

        normalized_build = _detached_mapping(build, "semantic build")
        normalized_publication = _detached_mapping(publication, "semantic publication")
        _validate_durable(normalized_build)
        _validate_durable(normalized_publication)
        self._write_payloads(
            (
                (SEMANTIC_BUILD_COLLECTION, "active", normalized_build),
                (SEMANTIC_CURRENT_COLLECTION, "current", normalized_publication),
            )
        )

    def read_semantic_current(self) -> Mapping[str, object] | None:
        raw = self._payload(SEMANTIC_CURRENT_COLLECTION, "current")
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise storage.ProjectCorruptError("M15.1 current semantic publication is not an object")
        return _detached_mapping(raw, "semantic publication")

    def reserve_semantic_provider_call(
        self,
        *,
        manifest_id: str,
        maximum_provider_calls: int,
        job_id: str,
        attempt: int,
    ) -> int:
        """Atomically consume one durable consent grant before any provider submission."""

        if any(not value or value != value.strip() for value in (manifest_id, job_id)):
            raise ValueError("semantic call reservation identities must be non-empty and trimmed")
        if (
            not isinstance(maximum_provider_calls, int)
            or isinstance(maximum_provider_calls, bool)
            or maximum_provider_calls < 1
            or not isinstance(attempt, int)
            or isinstance(attempt, bool)
            or attempt < 1
        ):
            raise ValueError("semantic call reservation bounds are invalid")
        connection = self._project._require_open()
        with storage.transaction(connection):
            row = connection.execute(
                "SELECT payload_json,payload_hash FROM payloads "
                "WHERE collection=? AND record_key=?",
                (SEMANTIC_CALL_LEDGER_COLLECTION, manifest_id),
            ).fetchone()
            reservations: list[dict[str, object]]
            if row is None:
                reservations = []
            else:
                encoded = bytes(row["payload_json"])
                if storage.payload_digest(encoded) != row["payload_hash"]:
                    raise storage.ProjectCorruptError(
                        "M15.1 semantic call ledger checksum does not match"
                    )
                decoded = storage.decode_json(encoded)
                reservations = _semantic_call_reservations(
                    decoded,
                    manifest_id=manifest_id,
                    maximum_provider_calls=maximum_provider_calls,
                )
                if cast(Mapping[str, object], decoded).get("closed") is True:
                    raise SemanticManifestClosedError(
                        "the exact semantic consent is closed to new provider calls"
                    )
            if any(
                item["job_id"] == job_id and item["attempt"] == attempt
                for item in reservations
            ):
                raise SemanticJobAttemptReservedError(
                    "the exact semantic job attempt is already durably reserved"
                )
            if len(reservations) >= maximum_provider_calls:
                raise SemanticCallLimitError(
                    "the exact semantic consent has no remaining durable call grant"
                )
            ordinal = len(reservations) + 1
            reservations.append(
                {
                    "ordinal": ordinal,
                    "job_id": job_id,
                    "attempt": attempt,
                    "settled": False,
                }
            )
            payload: dict[str, object] = {
                "schema": SEMANTIC_CALL_LEDGER_SCHEMA,
                "manifest_id": manifest_id,
                "maximum_provider_calls": maximum_provider_calls,
                "closed": False,
                "reservations": reservations,
            }
            _validate_durable(payload)
            encoded = storage.canonical_json(payload)
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
                (
                    SEMANTIC_CALL_LEDGER_COLLECTION,
                    manifest_id,
                    encoded,
                    storage.payload_digest(encoded),
                    storage.utc_now(),
                ),
            )
            connection.execute(
                "DELETE FROM payload_dependencies WHERE collection=? AND record_key=?",
                (SEMANTIC_CALL_LEDGER_COLLECTION, manifest_id),
            )
        return ordinal

    def settle_semantic_provider_calls(
        self,
        *,
        manifest_id: str,
        maximum_provider_calls: int,
        reservations_to_settle: Sequence[tuple[str, int]],
    ) -> None:
        """Atomically mark reserved attempts terminal after lifecycle finalization."""

        if not reservations_to_settle:
            return
        if len(reservations_to_settle) != len(set(reservations_to_settle)):
            raise ValueError("semantic call settlements must be unique")

        connection = self._project._require_open()
        with storage.transaction(connection):
            row = connection.execute(
                "SELECT payload_json,payload_hash FROM payloads "
                "WHERE collection=? AND record_key=?",
                (SEMANTIC_CALL_LEDGER_COLLECTION, manifest_id),
            ).fetchone()
            if row is None:
                raise storage.ProjectCorruptError(
                    "M15.1 semantic call settlement has no reservation ledger"
                )
            encoded = bytes(row["payload_json"])
            if storage.payload_digest(encoded) != row["payload_hash"]:
                raise storage.ProjectCorruptError(
                    "M15.1 semantic call ledger checksum does not match"
                )
            decoded = storage.decode_json(encoded)
            reservations = _semantic_call_reservations(
                decoded,
                manifest_id=manifest_id,
                maximum_provider_calls=maximum_provider_calls,
            )
            by_attempt = {
                (cast(str, item["job_id"]), cast(int, item["attempt"])): item
                for item in reservations
            }
            for identity in reservations_to_settle:
                matching = by_attempt.get(identity)
                if matching is None or "settled" not in matching:
                    raise storage.ProjectCorruptError(
                        "M15.1 semantic call settlement does not match a current reservation"
                    )
                if matching["settled"] is True:
                    raise storage.ProjectCorruptError(
                        "M15.1 semantic call reservation is already settled"
                    )
                matching["settled"] = True
            payload: dict[str, object] = {
                "schema": SEMANTIC_CALL_LEDGER_SCHEMA,
                "manifest_id": manifest_id,
                "maximum_provider_calls": maximum_provider_calls,
                "closed": False,
                "reservations": reservations,
            }
            _validate_durable(payload)
            encoded = storage.canonical_json(payload)
            connection.execute(
                "UPDATE payloads SET payload_json=?,payload_hash=?,updated_utc=? "
                "WHERE collection=? AND record_key=?",
                (
                    encoded,
                    storage.payload_digest(encoded),
                    storage.utc_now(),
                    SEMANTIC_CALL_LEDGER_COLLECTION,
                    manifest_id,
                ),
            )

    def semantic_reserved_call_count(
        self,
        *,
        manifest_id: str,
        maximum_provider_calls: int,
    ) -> int:
        raw = self._payload(SEMANTIC_CALL_LEDGER_COLLECTION, manifest_id)
        if raw is None:
            return 0
        count = len(
            _semantic_call_reservations(
                raw,
                manifest_id=manifest_id,
                maximum_provider_calls=maximum_provider_calls,
            )
        )
        if count > maximum_provider_calls:
            raise storage.ProjectCorruptError("M15.1 semantic call ledger exceeds consent")
        return count

    def semantic_manifest_reservation_count(self, manifest_id: str) -> int:
        """Read one durable manifest ledger using its own persisted consent ceiling."""

        raw = self._payload(SEMANTIC_CALL_LEDGER_COLLECTION, manifest_id)
        if raw is None:
            return 0
        if not isinstance(raw, Mapping):
            raise storage.ProjectCorruptError("M15.1 semantic call ledger is not an object")
        maximum_provider_calls = raw.get("maximum_provider_calls")
        if (
            not isinstance(maximum_provider_calls, int)
            or isinstance(maximum_provider_calls, bool)
            or maximum_provider_calls < 1
        ):
            raise storage.ProjectCorruptError("M15.1 semantic call ledger limit is invalid")
        return len(
            _semantic_call_reservations(
                raw,
                manifest_id=manifest_id,
                maximum_provider_calls=maximum_provider_calls,
            )
        )

    def publish_semantic_current_if_manifest(
        self,
        *,
        build: Mapping[str, object],
        publication: Mapping[str, object],
        stage: str,
        manifest_id: str,
    ) -> bool:
        """Atomically publish only while the exact stage manifest remains active."""

        normalized_build = _detached_mapping(build, "semantic build")
        normalized_publication = _detached_mapping(publication, "semantic publication")
        _validate_durable(normalized_build)
        _validate_durable(normalized_publication)
        return self._write_payloads_if_manifest(
            (
                (SEMANTIC_BUILD_COLLECTION, "active", normalized_build),
                (SEMANTIC_CURRENT_COLLECTION, "current", normalized_publication),
            ),
            stage=stage,
            manifest_id=manifest_id,
        )

    def semantic_manifest_settlement_count(self, manifest_id: str) -> int | None:
        """Return durable terminal calls, or ``None`` for a legacy ledger."""

        raw = self._payload(SEMANTIC_CALL_LEDGER_COLLECTION, manifest_id)
        if raw is None:
            return 0
        if not isinstance(raw, Mapping):
            raise storage.ProjectCorruptError("M15.1 semantic call ledger is not an object")
        maximum_provider_calls = raw.get("maximum_provider_calls")
        if (
            not isinstance(maximum_provider_calls, int)
            or isinstance(maximum_provider_calls, bool)
            or maximum_provider_calls < 1
        ):
            raise storage.ProjectCorruptError("M15.1 semantic call ledger limit is invalid")
        reservations = _semantic_call_reservations(
            raw,
            manifest_id=manifest_id,
            maximum_provider_calls=maximum_provider_calls,
        )
        if any("settled" not in item for item in reservations):
            return None
        return sum(item["settled"] is True for item in reservations)

    def seal_semantic_manifest_if_settled(
        self,
        *,
        manifest_id: str,
        maximum_provider_calls: int,
    ) -> bool | None:
        """Atomically close a ledger if every reservation is terminal.

        ``None`` identifies a legacy ledger without durable settlement state. Once
        closed, the manifest cannot acquire another reservation.
        """

        connection = self._project._require_open()
        with storage.transaction(connection):
            row = connection.execute(
                "SELECT payload_json,payload_hash FROM payloads "
                "WHERE collection=? AND record_key=?",
                (SEMANTIC_CALL_LEDGER_COLLECTION, manifest_id),
            ).fetchone()
            if row is None:
                reservations: list[dict[str, object]] = []
                closed = False
            else:
                encoded = bytes(row["payload_json"])
                if storage.payload_digest(encoded) != row["payload_hash"]:
                    raise storage.ProjectCorruptError(
                        "M15.1 semantic call ledger checksum does not match"
                    )
                decoded = storage.decode_json(encoded)
                reservations = _semantic_call_reservations(
                    decoded,
                    manifest_id=manifest_id,
                    maximum_provider_calls=maximum_provider_calls,
                )
                closed = cast(
                    bool,
                    cast(Mapping[str, object], decoded).get("closed", False),
                )
                if any("settled" not in item for item in reservations):
                    return None
            if closed is True:
                return True
            if any(item["settled"] is not True for item in reservations):
                return False
            payload: dict[str, object] = {
                "schema": SEMANTIC_CALL_LEDGER_SCHEMA,
                "manifest_id": manifest_id,
                "maximum_provider_calls": maximum_provider_calls,
                "closed": True,
                "reservations": reservations,
            }
            _validate_durable(payload)
            encoded = storage.canonical_json(payload)
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
                (
                    SEMANTIC_CALL_LEDGER_COLLECTION,
                    manifest_id,
                    encoded,
                    storage.payload_digest(encoded),
                    storage.utc_now(),
                ),
            )
            connection.execute(
                "DELETE FROM payload_dependencies WHERE collection=? AND record_key=?",
                (SEMANTIC_CALL_LEDGER_COLLECTION, manifest_id),
            )
        return True

    @staticmethod
    def cache_identity(
        job: PreparedNarrativeJob, profile: ProviderProfile
    ) -> dict[str, JsonValue]:
        identity: dict[str, JsonValue] = {
            "kind": job.kind.value,
            "authority": job.authority.to_dict(),
            "subject_id": job.subject_id,
            "input_hash": job.input_hash,
            "provider": profile.to_dict(),
            "prompt_version": job.prompt_version,
            "response_schema": job.response_schema,
        }
        if job.source_hash is not None:
            identity["source_hash"] = job.source_hash
        if job.correction_id is not None:
            identity["correction_id"] = job.correction_id
        if job.membership_hash is not None:
            identity["membership_hash"] = job.membership_hash
        if job.privacy_scope is not None:
            identity["privacy_scope"] = job.privacy_scope
        return identity

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
        provider_calls: int,
        result: Mapping[str, object] | None,
        provider_identity: Mapping[str, object] | None,
        usage: Mapping[str, object] | None,
        error_code: str | None,
        consent_manifest_id: str | None = None,
    ) -> dict[str, object]:
        if attempt_count < 0 or not 0 <= provider_calls <= attempt_count:
            raise ValueError("M15 attempt and provider-call counts are inconsistent")
        if consent_manifest_id is not None and (
            not consent_manifest_id or consent_manifest_id != consent_manifest_id.strip()
        ):
            raise ValueError("M15 consent manifest identity must be non-empty and trimmed")
        payload: dict[str, object] = {
            "schema": PERSISTENCE_SCHEMA,
            **job.durable_metadata(),
            "authority_hash": job.authority.identity,
            "profile": profile.to_dict(),
            "profile_hash": canonical_hash(profile.to_dict()),
            "status": status.value,
            "attempt_count": attempt_count,
            "provider_calls": provider_calls,
            "result": result,
            "provider_identity": provider_identity,
            "usage": usage,
            "error_code": error_code,
            "consent_manifest_id": consent_manifest_id,
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

    def _write_payloads_if_manifest(
        self,
        records: tuple[tuple[str, str, Mapping[str, object]], ...],
        *,
        stage: str,
        manifest_id: str,
    ) -> bool:
        if stage not in {"boundary", "summary"} or not manifest_id:
            raise ValueError("semantic manifest write precondition is invalid")
        connection = self._project._require_open()
        now = storage.utc_now()
        with storage.transaction(connection):
            row = connection.execute(
                "SELECT payload_json,payload_hash FROM payloads "
                "WHERE collection=? AND record_key='active'",
                (SEMANTIC_BUILD_COLLECTION,),
            ).fetchone()
            if row is None:
                raise storage.ProjectCorruptError("M15.1 semantic build is missing")
            active_encoded = bytes(row["payload_json"])
            if storage.payload_digest(active_encoded) != row["payload_hash"]:
                raise storage.ProjectCorruptError(
                    "M15.1 semantic build checksum does not match stored data"
                )
            active = storage.decode_json(active_encoded)
            if not isinstance(active, Mapping):
                raise storage.ProjectCorruptError("M15.1 semantic build is not an object")
            if active.get(f"{stage}_manifest_id") != manifest_id:
                return False
            for collection, key, value in records:
                payload = storage.canonical_json(value)
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
        return True

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
        provider_calls = raw.get("provider_calls")
        if (
            not isinstance(attempt_count, int)
            or isinstance(attempt_count, bool)
            or attempt_count < 0
            or not isinstance(provider_calls, int)
            or isinstance(provider_calls, bool)
            or not 0 <= provider_calls <= attempt_count
        ):
            raise storage.ProjectCorruptError(
                "M15 job attempt and provider-call counts are invalid"
            )
        result = raw.get("result")
        provider_identity = raw.get("provider_identity")
        usage = raw.get("usage")
        if result is not None and not isinstance(result, Mapping):
            raise storage.ProjectCorruptError("M15 validated result is invalid")
        if provider_identity is not None and not isinstance(provider_identity, Mapping):
            raise storage.ProjectCorruptError("M15 provider identity is invalid")
        if usage is not None and not isinstance(usage, Mapping):
            raise storage.ProjectCorruptError("M15 usage is invalid")
        if usage is not None and usage.get("provider_calls") != provider_calls:
            raise storage.ProjectCorruptError("M15 usage provider-call count is inconsistent")
        error_code = raw.get("error_code")
        if error_code is not None and (
            not isinstance(error_code, str) or not _ERROR_CODE.fullmatch(error_code)
        ):
            raise storage.ProjectCorruptError("M15 failure code is invalid")
        consent_manifest_id = raw.get("consent_manifest_id")
        if consent_manifest_id is not None and (
            not isinstance(consent_manifest_id, str) or not consent_manifest_id
        ):
            raise storage.ProjectCorruptError("M15 consent manifest identity is invalid")
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
            provider_calls=provider_calls,
            result=cast(Mapping[str, object] | None, result),
            provider_identity=cast(Mapping[str, object] | None, provider_identity),
            usage=cast(Mapping[str, object] | None, usage),
            error_code=error_code,
            consent_manifest_id=consent_manifest_id,
        )


def _collection(kind: ProviderJobKind) -> str:
    if kind is ProviderJobKind.BOUNDARY:
        return BOUNDARY_JOBS_COLLECTION
    if kind is ProviderJobKind.EVENT_SUMMARY:
        return SUMMARY_JOBS_COLLECTION
    if kind is ProviderJobKind.SEMANTIC_BOUNDARY_WINDOW:
        return SEMANTIC_BOUNDARY_JOBS_COLLECTION
    return SEMANTIC_SUMMARY_JOBS_COLLECTION


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
    if provider_calls < 0:
        raise ValueError("persisted provider call count cannot be negative")
    if provider_calls == 0 and any(
        value != 0
        for value in (
            usage.input_tokens,
            usage.output_tokens,
            usage.elapsed_ms,
            usage.cost_micros or 0,
        )
    ):
        raise ValueError("zero-call cache replay cannot carry provider usage")
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "elapsed_ms": usage.elapsed_ms,
        "cost_micros": usage.cost_micros,
        "provider_calls": provider_calls,
    }


def _semantic_call_reservations(
    raw: object,
    *,
    manifest_id: str,
    maximum_provider_calls: int,
) -> list[dict[str, object]]:
    if (
        not isinstance(raw, Mapping)
        or raw.get("schema") != SEMANTIC_CALL_LEDGER_SCHEMA
        or raw.get("manifest_id") != manifest_id
        or raw.get("maximum_provider_calls") != maximum_provider_calls
        or not isinstance(raw.get("reservations"), list)
        or ("closed" in raw and not isinstance(raw.get("closed"), bool))
    ):
        raise storage.ProjectCorruptError("M15.1 semantic call ledger identity is invalid")
    reservations: list[dict[str, object]] = []
    job_attempts: set[tuple[str, int]] = set()
    for expected_ordinal, item in enumerate(cast(list[object], raw["reservations"]), 1):
        if (
            not isinstance(item, Mapping)
            or set(item) not in (
                {"ordinal", "job_id", "attempt"},
                {"ordinal", "job_id", "attempt", "settled"},
            )
            or item.get("ordinal") != expected_ordinal
            or not isinstance(item.get("job_id"), str)
            or not item.get("job_id")
            or not isinstance(item.get("attempt"), int)
            or isinstance(item.get("attempt"), bool)
            or cast(int, item.get("attempt")) < 1
            or ("settled" in item and not isinstance(item.get("settled"), bool))
        ):
            raise storage.ProjectCorruptError(
                "M15.1 semantic call ledger reservation is invalid"
            )
        job_attempt = (cast(str, item["job_id"]), cast(int, item["attempt"]))
        if job_attempt in job_attempts:
            raise storage.ProjectCorruptError(
                "M15.1 semantic call ledger repeats a logical job attempt"
            )
        job_attempts.add(job_attempt)
        reservations.append(dict(item))
    return reservations
