"""Schema-v6 persistence adapter for the parallel organization scheduler."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, cast

from renpy_story_mapper import storage
from renpy_story_mapper.m07_model import (
    Assembly,
    AttemptAccounting,
    CheckpointStatus,
    M07ModelService,
    ScopeCheckpoint,
)
from renpy_story_mapper.organization.contracts import (
    CodexMode,
    InterpretationClaim,
    OrganizationChunkResult,
    OrganizationGroup,
    OrganizationStage,
    ProviderAttemptUsage,
    ProviderExecutionMetadata,
)
from renpy_story_mapper.organization.parallel import (
    CheckpointState,
    OutcomeEvent,
    RouteScope,
    SchedulerConfig,
    ScopeEnvelope,
    normalized_cache_identity,
)
from renpy_story_mapper.route_map import RouteScope as DeterministicRouteScope
from renpy_story_mapper.story_organization import CacheIdentity, StoryOrganizationService

if TYPE_CHECKING:
    from renpy_story_mapper.project import Project

_RESULT_SCHEMA_VERSION = 1


def encode_organization_result(result: OrganizationChunkResult) -> dict[str, object]:
    """Encode the complete provider result into deterministic schema-safe data."""

    metadata = result.metadata
    return {
        "schema_version": _RESULT_SCHEMA_VERSION,
        "stage": result.stage.value,
        "groups": [
            {
                "id": group.id,
                "title": group.title,
                "summary": group.summary,
                "member_ids": list(group.member_ids),
                "characters": list(group.characters),
                "importance": group.importance,
                "outcomes": list(group.outcomes),
                "promoted_fact_ids": list(group.promoted_fact_ids),
                "claims": [
                    {"text": claim.text, "evidence_ids": list(claim.evidence_ids)}
                    for claim in group.claims
                ],
                "warnings": list(group.warnings),
            }
            for group in result.groups
        ],
        "ungrouped_ids": list(result.ungrouped_ids),
        "raw_normalized": result.raw_normalized,
        "attempts": result.attempts,
        "metadata": (
            None
            if metadata is None
            else {
                "provider_mode": metadata.provider_mode.value,
                "model_identifier": metadata.model_identifier,
                "cli_version": metadata.cli_version,
                "elapsed_ms": metadata.elapsed_ms,
                "input_hash": metadata.input_hash,
                "output_hash": metadata.output_hash,
                "input_tokens": metadata.input_tokens,
                "output_tokens": metadata.output_tokens,
                "context_window_tokens": metadata.context_window_tokens,
            }
        ),
    }


def decode_organization_result(value: object) -> OrganizationChunkResult:
    """Decode a complete cached/checkpoint result or reject corrupted data."""

    root = _mapping(value, "organization result")
    _exact_keys(
        root,
        {
            "schema_version",
            "stage",
            "groups",
            "ungrouped_ids",
            "raw_normalized",
            "attempts",
            "metadata",
        },
        "organization result",
    )
    if _integer(root["schema_version"], "schema_version") != _RESULT_SCHEMA_VERSION:
        raise storage.ProjectCorruptError("organization result schema version is unsupported")
    try:
        stage = OrganizationStage(_string(root["stage"], "stage"))
    except ValueError as exc:
        raise storage.ProjectCorruptError("organization result stage is invalid") from exc
    groups_value = root["groups"]
    if not isinstance(groups_value, list):
        raise storage.ProjectCorruptError("organization result groups must be a list")
    groups = tuple(_decode_group(item) for item in groups_value)
    raw = _mapping(root["raw_normalized"], "raw_normalized")
    attempts = _integer(root["attempts"], "attempts")
    if attempts < 1:
        raise storage.ProjectCorruptError("organization result attempts must be positive")
    return OrganizationChunkResult(
        stage=stage,
        groups=groups,
        ungrouped_ids=_strings(root["ungrouped_ids"], "ungrouped_ids"),
        raw_normalized=dict(raw),
        attempts=attempts,
        metadata=_decode_metadata(root["metadata"]),
    )


class PersistentCheckpointSink:
    """Persist scheduler state through current M07 and organization-cache services."""

    def __init__(
        self,
        project: Project,
        *,
        generation: str,
        deterministic_scopes: Sequence[DeterministicRouteScope],
        organization_scopes: Sequence[RouteScope],
        config: SchedulerConfig,
    ) -> None:
        if not generation.strip():
            raise ValueError("generation cannot be empty")
        self._model: M07ModelService = project.m07_model_service()
        self._cache: StoryOrganizationService = project.organization_service()
        self._project_path = project.path
        self._generation = generation
        self._config = config
        self._lock = threading.RLock()
        self._pending_errors: dict[str, str | None] = {}
        self._cache_hits: set[str] = set()
        self._sequence = 0
        self.events: list[OutcomeEvent] = []
        self.last_assembly: Assembly | None = None

        by_id = {scope.request.scope_id: scope for scope in organization_scopes}
        if len(by_id) != len(organization_scopes):
            raise ValueError("organization scope IDs must be unique")
        if set(by_id) != {scope.id for scope in deterministic_scopes}:
            raise ValueError("deterministic and organization scope IDs must match exactly")
        registered = tuple(
            replace(
                scope,
                input_hash=normalized_cache_identity(by_id[scope.id].request, config),
            )
            for scope in deterministic_scopes
        )
        self._model.register_scopes(registered, generation=generation)
        attempt_floors = {
            str(row["scope_id"]): int(row["next_ordinal"])
            for row in project._require_open().execute(
                """SELECT scope_id,COALESCE(MAX(ordinal)+1,0) next_ordinal
                   FROM m07_provider_attempts GROUP BY scope_id"""
            )
        }
        self._next_attempt = {
            checkpoint.scope_id: max(
                checkpoint.attempts, attempt_floors.get(checkpoint.scope_id, 0)
            )
            for checkpoint in self._model.checkpoints()
        }

    def checkpoint(self, scope_id: str) -> ScopeEnvelope | None:
        with self._lock:
            checkpoint = self._checkpoint(scope_id)
            if checkpoint is None:
                return None
            result: OrganizationChunkResult | None = None
            identity = checkpoint.input_hash
            if checkpoint.result is not None:
                persisted = _mapping(checkpoint.result, "checkpoint result")
                _exact_keys(
                    persisted,
                    {"cache_identity", "organization_result"},
                    "checkpoint result",
                )
                identity = _digest(persisted["cache_identity"], "cache_identity")
                result = decode_organization_result(persisted["organization_result"])
            return ScopeEnvelope(
                checkpoint.ordinal,
                checkpoint.scope_id,
                _parallel_state(checkpoint.status),
                identity,
                result,
            )

    def cached(self, identity: str) -> OrganizationChunkResult | None:
        with self._lock:
            cached = self._cache.cache_result(self._cache_identity(identity))
            if cached is None:
                return None
            result = decode_organization_result(cached)
            self._cache_hits.add(identity)
            return result

    def event(
        self,
        scope: RouteScope,
        state: CheckpointState,
        identity: str,
        *,
        error_code: str | None = None,
        message: str | None = None,
    ) -> None:
        del message
        with self._lock:
            self._sequence += 1
            self.events.append(
                OutcomeEvent(
                    self._sequence,
                    scope.request.scope_id,
                    state,
                    identity,
                    error_code,
                    None,
                )
            )
            self._pending_errors[scope.request.scope_id] = error_code
            if state is CheckpointState.PENDING:
                return
            if state is CheckpointState.CACHED_OR_IN_FLIGHT:
                status = (
                    CheckpointStatus.CACHED
                    if identity in self._cache_hits
                    else CheckpointStatus.IN_FLIGHT
                )
                current = self._require_checkpoint(scope.request.scope_id)
                if current.status is not status:
                    self._model.transition(scope.request.scope_id, status)

    def attempt(self, scope_id: str, usage: ProviderAttemptUsage) -> None:
        with self._lock:
            ordinal = self._next_attempt[scope_id]
            self._next_attempt[scope_id] = ordinal + 1
            attempt_id = _attempt_id(self._generation, scope_id, ordinal)
            attempt = AttemptAccounting(
                attempt_id=attempt_id,
                scope_id=scope_id,
                ordinal=ordinal,
                outcome=usage.outcome,
                calls=1,
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                elapsed_ms=usage.elapsed_ms,
            )
            connection = storage.connect(self._project_path)
            try:
                with storage.transaction(connection):
                    connection.execute(
                        """INSERT INTO m07_provider_attempts(
                           attempt_id,scope_id,ordinal,outcome,calls,input_tokens,output_tokens,
                           elapsed_ms,cached,created_utc) VALUES (?,?,?,?,?,?,?,?,?,?)""",
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
            finally:
                connection.close()

    def flush_attempts(self) -> None:
        """Attempt records are already committed synchronously by ``attempt``."""

    def publish(self, envelope: ScopeEnvelope) -> None:
        with self._lock:
            status = _checkpoint_status(envelope.state)
            checkpoint = self._require_checkpoint(envelope.scope_id)
            if checkpoint.status is status and status is not CheckpointStatus.VALIDATED:
                return
            result: object | None = None
            if envelope.result is not None:
                result = {
                    "cache_identity": envelope.cache_identity,
                    "organization_result": encode_organization_result(envelope.result),
                }
            self._model.transition(
                envelope.scope_id,
                status,
                result=result,
                error_code=self._pending_errors.get(envelope.scope_id),
            )

    def cache(self, identity: str, result: OrganizationChunkResult) -> None:
        with self._lock:
            self._cache.store_cache_result(
                self._cache_identity(identity), encode_organization_result(result)
            )

    def assemble(self, envelopes: Iterable[ScopeEnvelope]) -> tuple[ScopeEnvelope, ...]:
        with self._lock:
            ordered = tuple(sorted(envelopes, key=lambda item: (item.ordinal, item.scope_id)))
            self.last_assembly = self._model.assemble(
                generation=self._generation, allow_partial=True
            )
            return ordered

    def _cache_identity(self, identity: str) -> CacheIdentity:
        return self._cache.cache_identity(
            provider_mode=self._config.provider_mode.value,
            model_profile=self._config.reasoning_profile,
            model_fingerprint=self._config.model,
            prompt_version=self._config.prompt_version,
            output_schema_version=self._config.schema_version,
            input_hash=_digest(identity, "cache identity"),
            ordered_ids=(),
        )

    def _checkpoint(self, scope_id: str) -> ScopeCheckpoint | None:
        return next(
            (item for item in self._model.checkpoints() if item.scope_id == scope_id), None
        )

    def _require_checkpoint(self, scope_id: str) -> ScopeCheckpoint:
        checkpoint = self._checkpoint(scope_id)
        if checkpoint is None:
            raise KeyError(f"unknown route scope: {scope_id}")
        return checkpoint


def _decode_group(value: object) -> OrganizationGroup:
    group = _mapping(value, "organization group")
    _exact_keys(
        group,
        {
            "id",
            "title",
            "summary",
            "member_ids",
            "characters",
            "importance",
            "outcomes",
            "promoted_fact_ids",
            "claims",
            "warnings",
        },
        "organization group",
    )
    raw_claims = group["claims"]
    if not isinstance(raw_claims, list):
        raise storage.ProjectCorruptError("organization claims must be a list")
    claims: list[InterpretationClaim] = []
    for value in raw_claims:
        claim = _mapping(value, "organization claim")
        _exact_keys(claim, {"text", "evidence_ids"}, "organization claim")
        claims.append(
            InterpretationClaim(
                _string(claim["text"], "claim text"),
                _strings(claim["evidence_ids"], "claim evidence_ids"),
            )
        )
    return OrganizationGroup(
        id=_string(group["id"], "group id"),
        title=_string(group["title"], "group title"),
        summary=_string(group["summary"], "group summary"),
        member_ids=_strings(group["member_ids"], "group member_ids"),
        characters=_strings(group["characters"], "group characters"),
        importance=_string(group["importance"], "group importance"),
        outcomes=_strings(group["outcomes"], "group outcomes"),
        promoted_fact_ids=_strings(group["promoted_fact_ids"], "promoted fact IDs"),
        claims=tuple(claims),
        warnings=_strings(group["warnings"], "group warnings"),
    )


def _decode_metadata(value: object) -> ProviderExecutionMetadata | None:
    if value is None:
        return None
    metadata = _mapping(value, "provider metadata")
    _exact_keys(
        metadata,
        {
            "provider_mode",
            "model_identifier",
            "cli_version",
            "elapsed_ms",
            "input_hash",
            "output_hash",
            "input_tokens",
            "output_tokens",
            "context_window_tokens",
        },
        "provider metadata",
    )
    try:
        mode = CodexMode(_string(metadata["provider_mode"], "provider mode"))
    except ValueError as exc:
        raise storage.ProjectCorruptError("provider mode is invalid") from exc
    return ProviderExecutionMetadata(
        provider_mode=mode,
        model_identifier=_optional_string(metadata["model_identifier"], "model identifier"),
        cli_version=_optional_string(metadata["cli_version"], "CLI version"),
        elapsed_ms=_integer(metadata["elapsed_ms"], "elapsed milliseconds"),
        input_hash=_digest(metadata["input_hash"], "input hash"),
        output_hash=_digest(metadata["output_hash"], "output hash"),
        input_tokens=_optional_integer(metadata["input_tokens"], "input tokens"),
        output_tokens=_optional_integer(metadata["output_tokens"], "output tokens"),
        context_window_tokens=_optional_integer(
            metadata["context_window_tokens"], "context window tokens"
        ),
    )


def _attempt_id(generation: str, scope_id: str, ordinal: int) -> str:
    material = storage.canonical_json([generation, scope_id, ordinal])
    return f"attempt_{hashlib.sha256(material).hexdigest()[:24]}"


def _parallel_state(status: CheckpointStatus) -> CheckpointState:
    if status in {CheckpointStatus.CACHED, CheckpointStatus.IN_FLIGHT}:
        return CheckpointState.CACHED_OR_IN_FLIGHT
    return CheckpointState(status.value)


def _checkpoint_status(state: CheckpointState) -> CheckpointStatus:
    if state is CheckpointState.CACHED_OR_IN_FLIGHT:
        return CheckpointStatus.IN_FLIGHT
    return CheckpointStatus(state.value)


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise storage.ProjectCorruptError(f"{name} must be an object")
    return cast(Mapping[str, object], value)


def _exact_keys(value: Mapping[str, object], keys: set[str], name: str) -> None:
    if set(value) != keys:
        raise storage.ProjectCorruptError(f"{name} fields are invalid")


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise storage.ProjectCorruptError(f"{name} must be non-empty text")
    return value


def _optional_string(value: object, name: str) -> str | None:
    return None if value is None else _string(value, name)


def _integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise storage.ProjectCorruptError(f"{name} must be a non-negative integer")
    return value


def _optional_integer(value: object, name: str) -> int | None:
    return None if value is None else _integer(value, name)


def _strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise storage.ProjectCorruptError(f"{name} must be a list")
    return tuple(_string(item, name) for item in value)


def _digest(value: object, name: str) -> str:
    digest = _string(value, name)
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise storage.ProjectCorruptError(f"{name} must be a SHA-256 digest")
    return digest
