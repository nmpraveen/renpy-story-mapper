"""Provider-neutral transport beneath the M15 semantic boundary.

The prepared job payload is transient.  Only validated normalized results and identity metadata
may cross into :mod:`narrative_map.persistence`.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from importlib.resources import as_file, files
from threading import Lock
from typing import Protocol, cast

from renpy_story_mapper.narrative.contracts import ProviderIdentity, ProviderSettings
from renpy_story_mapper.narrative.provider import ProviderUsage
from renpy_story_mapper.narrative_map.contracts import (
    AuthorityBinding,
    BoundaryCandidate,
    JsonValue,
    NarrativeEvent,
    canonical_hash,
    stable_m15_id,
)
from renpy_story_mapper.organization.sterile_runner import (
    SterileCodexRunner,
    SterileRunnerError,
    SterileRunRequest,
    SterileRunResult,
)

BOUNDARY_PROMPT_VERSION = "m15-boundary-prompt-v1"
BOUNDARY_RESPONSE_SCHEMA = "m15-boundary-decision-v1"
SUMMARY_PROMPT_VERSION = "m15-event-summary-prompt-v1"
SUMMARY_RESPONSE_SCHEMA = "m15-event-summary-v1"
MAXIMUM_INPUT_BYTES = 1_000_000
MAXIMUM_OUTPUT_BYTES = 2_000_000
_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")

CancelledCallback = Callable[[], bool]


class _ConsentCallLedger:
    """Transient atomic call grants shared by copies of one consent manifest."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._bound_manifest_id: str | None = None
        self._reserved_calls = 0

    def reserve(
        self,
        manifest: NarrativeConsentManifest,
        job: PreparedNarrativeJob,
        profile: ProviderProfile,
    ) -> None:
        with self._lock:
            manifest.validate_job(job, profile)
            manifest_id = manifest.manifest_id
            if self._bound_manifest_id is None:
                self._bound_manifest_id = manifest_id
            elif self._bound_manifest_id != manifest_id:
                raise ValueError("M15 consent call ledger identity does not match")
            if self._reserved_calls >= manifest.maximum_provider_calls:
                raise NarrativeMapProviderError(
                    "consent_call_limit",
                    "The M15 consent has no remaining provider call grant.",
                )
            self._reserved_calls += 1


class ProviderJobKind(StrEnum):
    BOUNDARY = "boundary"
    EVENT_SUMMARY = "event_summary"


@dataclass(frozen=True)
class ProviderProfile:
    """Exact non-secret provider/model/settings identity used before submission and for cache."""

    provider: str
    adapter: str
    adapter_version: str
    requested_model: str
    settings: ProviderSettings

    def __post_init__(self) -> None:
        for value, label in (
            (self.provider, "provider"),
            (self.adapter, "provider adapter"),
            (self.adapter_version, "provider adapter version"),
            (self.requested_model, "requested model"),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{label} must be a non-empty trimmed string")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "provider": self.provider,
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
            "requested_model": self.requested_model,
            "settings": self.settings.to_dict(),
        }

    @property
    def settings_hash(self) -> str:
        return canonical_hash(self.settings.to_dict())


@dataclass(frozen=True)
class PreparedNarrativeJob:
    """One exact transient semantic job; ``payload`` must never be persisted."""

    kind: ProviderJobKind
    authority: AuthorityBinding
    subject: BoundaryCandidate | NarrativeEvent
    subject_id: str
    input_hash: str
    prompt_version: str
    response_schema: str
    payload: dict[str, JsonValue]
    known_evidence_ids: tuple[str, ...]
    known_characters: tuple[str, ...] = ()
    story_facing: bool = True

    def __post_init__(self) -> None:
        if not self.subject_id or self.subject_id != self.subject_id.strip():
            raise ValueError("job subject ID must be a non-empty trimmed string")
        if not self.input_hash or not self.prompt_version or not self.response_schema:
            raise ValueError("job input, prompt, and schema identities are required")
        if len(self.known_evidence_ids) != len(set(self.known_evidence_ids)):
            raise ValueError("job evidence IDs must be unique")
        if len(self.known_characters) != len(set(self.known_characters)):
            raise ValueError("job characters must be unique")
        expected_subject = (
            self.subject.candidate_id
            if isinstance(self.subject, BoundaryCandidate)
            else self.subject.event_id
        )
        if self.subject_id != expected_subject:
            raise ValueError("job subject does not match its frozen contract identity")
        self.validate_integrity()

    @property
    def job_id(self) -> str:
        return stable_m15_id(
            f"{self.kind.value}_job",
            {
                "kind": self.kind.value,
                "authority": self.authority.to_dict(),
                "subject_id": self.subject_id,
                "input_hash": self.input_hash,
                "prompt_version": self.prompt_version,
                "response_schema": self.response_schema,
            },
        )

    def durable_metadata(self) -> dict[str, JsonValue]:
        """Return identifiers/counts only; source evidence and prompt content are omitted."""

        return {
            "job_id": self.job_id,
            "kind": self.kind.value,
            "subject_id": self.subject_id,
            "authority": self.authority.to_dict(),
            "input_hash": self.input_hash,
            "prompt_version": self.prompt_version,
            "response_schema": self.response_schema,
            "known_evidence_ids": list(self.known_evidence_ids),
            "known_characters": list(self.known_characters),
            "story_facing": self.story_facing,
        }

    def validate_integrity(self) -> None:
        if canonical_hash(self.payload) != self.input_hash:
            raise ValueError("prepared M15 input hash does not match its provider payload")


@dataclass(frozen=True)
class NarrativeConsentManifest:
    """Fresh, granted consent bound to exact jobs, provider identity, and transport limits."""

    run_id: str
    profile: ProviderProfile
    job_ids: tuple[str, ...]
    job_identity_hashes: tuple[str, ...]
    job_identity_hash: str
    issued_utc: str
    expires_utc: str
    maximum_provider_calls: int
    maximum_input_bytes: int
    maximum_output_bytes: int
    timeout_seconds: float
    consent_granted: bool = False
    version: str = "m15-narrative-consent-v1"
    _call_ledger: _ConsentCallLedger = field(
        default_factory=_ConsentCallLedger,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not self.run_id or self.run_id != self.run_id.strip():
            raise ValueError("consent run ID must be a non-empty trimmed string")
        if not self.job_ids or len(self.job_ids) != len(set(self.job_ids)):
            raise ValueError("consent scope requires unique M15 jobs")
        if len(self.job_identity_hashes) != len(self.job_ids):
            raise ValueError("consent job identities must cover the exact scope")
        transport_limits = (
            self.maximum_provider_calls,
            self.maximum_input_bytes,
            self.maximum_output_bytes,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1
            for value in transport_limits
        ):
            raise ValueError("consent transport limits must be positive")
        if self.maximum_input_bytes > MAXIMUM_INPUT_BYTES:
            raise ValueError("consent input limit exceeds the sterile boundary")
        if self.maximum_output_bytes > MAXIMUM_OUTPUT_BYTES:
            raise ValueError("consent output limit exceeds the sterile boundary")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("consent timeout must be positive")
        _consent_times(self.issued_utc, self.expires_utc)

    @classmethod
    def for_jobs(
        cls,
        *,
        run_id: str,
        profile: ProviderProfile,
        jobs: Sequence[PreparedNarrativeJob],
        consent_granted: bool = False,
        valid_for: timedelta = timedelta(minutes=15),
        maximum_provider_calls: int | None = None,
        maximum_input_bytes: int = MAXIMUM_INPUT_BYTES,
        maximum_output_bytes: int = MAXIMUM_OUTPUT_BYTES,
        timeout_seconds: float = 300.0,
    ) -> NarrativeConsentManifest:
        if not jobs:
            raise ValueError("consent scope requires at least one M15 job")
        if valid_for <= timedelta(0) or valid_for > timedelta(hours=1):
            raise ValueError("consent freshness window must be between zero and one hour")
        for job in jobs:
            job.validate_integrity()
        issued = datetime.now(UTC)
        return cls(
            run_id=run_id,
            profile=profile,
            job_ids=tuple(job.job_id for job in jobs),
            job_identity_hashes=tuple(
                canonical_hash(job.durable_metadata()) for job in jobs
            ),
            job_identity_hash=_job_identity_hash(jobs),
            issued_utc=issued.isoformat(),
            expires_utc=(issued + valid_for).isoformat(),
            maximum_provider_calls=(
                maximum_provider_calls
                if maximum_provider_calls is not None
                else 2 * len(jobs)
            ),
            maximum_input_bytes=maximum_input_bytes,
            maximum_output_bytes=maximum_output_bytes,
            timeout_seconds=timeout_seconds,
            consent_granted=consent_granted,
        )

    @property
    def manifest_id(self) -> str:
        return stable_m15_id("consent", self.identity_dict())

    def identity_dict(self) -> dict[str, JsonValue]:
        return {
            "version": self.version,
            "run_id": self.run_id,
            "profile": self.profile.to_dict(),
            "job_ids": list(self.job_ids),
            "job_identity_hashes": list(self.job_identity_hashes),
            "job_identity_hash": self.job_identity_hash,
            "issued_utc": self.issued_utc,
            "expires_utc": self.expires_utc,
            "maximum_provider_calls": self.maximum_provider_calls,
            "maximum_input_bytes": self.maximum_input_bytes,
            "maximum_output_bytes": self.maximum_output_bytes,
            "timeout_seconds": self.timeout_seconds,
        }

    def validate_for(
        self,
        jobs: Sequence[PreparedNarrativeJob],
        profile: ProviderProfile,
    ) -> None:
        if not self.consent_granted:
            raise ValueError("M15 provider transmission requires granted consent")
        self.validate_fresh()
        if canonical_hash(self.profile.to_dict()) != canonical_hash(profile.to_dict()):
            raise ValueError("M15 consent provider profile does not match")
        if tuple(job.job_id for job in jobs) != self.job_ids:
            raise ValueError("M15 consent scope does not match the scheduled jobs")
        for job in jobs:
            job.validate_integrity()
        if _job_identity_hash(jobs) != self.job_identity_hash:
            raise ValueError("M15 consent input identity does not match")

    def validate_job(self, job: PreparedNarrativeJob, profile: ProviderProfile) -> None:
        if not self.consent_granted:
            raise ValueError("M15 provider transmission requires granted consent")
        self.validate_fresh()
        if canonical_hash(self.profile.to_dict()) != canonical_hash(profile.to_dict()):
            raise ValueError("M15 consent provider profile does not match")
        job.validate_integrity()
        try:
            index = self.job_ids.index(job.job_id)
        except ValueError:
            raise ValueError("M15 consent scope does not include the provider job") from None
        if canonical_hash(job.durable_metadata()) != self.job_identity_hashes[index]:
            raise ValueError("M15 consent job identity does not match")

    def validate_fresh(self) -> None:
        issued, expires = _consent_times(self.issued_utc, self.expires_utc)
        now = datetime.now(UTC)
        if issued > now + timedelta(minutes=1) or now >= expires:
            raise ValueError("M15 provider consent is not fresh")

    def reserve_provider_call(
        self,
        job: PreparedNarrativeJob,
        profile: ProviderProfile,
    ) -> None:
        """Atomically consume one call grant immediately before transmission."""

        self._call_ledger.reserve(self, job, profile)


@dataclass(frozen=True)
class NarrativeMapProviderRequest:
    request_id: str
    consent: NarrativeConsentManifest
    profile: ProviderProfile
    job: PreparedNarrativeJob
    repair_codes: tuple[str, ...] = ()
    repair_semantics: Mapping[str, JsonValue] | None = None
    timeout_seconds: float = 300.0
    maximum_input_bytes: int = MAXIMUM_INPUT_BYTES
    maximum_output_bytes: int = MAXIMUM_OUTPUT_BYTES

    def __post_init__(self) -> None:
        for value, label in (
            (self.request_id, "provider request ID"),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{label} must be a non-empty trimmed string")
        if len(self.repair_codes) != len(set(self.repair_codes)):
            raise ValueError("repair codes must be unique")
        if bool(self.repair_codes) != (self.repair_semantics is not None):
            raise ValueError("schema repair metadata must be supplied together")
        self.validate_for_submission()

    def validate_for_submission(self) -> None:
        if (
            not isinstance(self.timeout_seconds, int | float)
            or isinstance(self.timeout_seconds, bool)
            or not math.isfinite(float(self.timeout_seconds))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("provider timeout bound must be finite and positive")
        for value, label in (
            (self.maximum_input_bytes, "input"),
            (self.maximum_output_bytes, "output"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"provider {label} bound must be a positive integer")
        if self.maximum_input_bytes > self.consent.maximum_input_bytes:
            raise ValueError("provider input bound exceeds consent")
        if self.maximum_output_bytes > self.consent.maximum_output_bytes:
            raise ValueError("provider output bound exceeds consent")
        if self.timeout_seconds > self.consent.timeout_seconds:
            raise ValueError("provider timeout bound exceeds consent")
        self.consent.validate_job(self.job, self.profile)

    @property
    def consent_manifest_id(self) -> str:
        return self.consent.manifest_id


@dataclass(frozen=True)
class NarrativeMapProviderResponse:
    request_id: str
    provider: ProviderIdentity
    payload: dict[str, object]
    usage: ProviderUsage


class NarrativeMapProvider(Protocol):
    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: CancelledCallback,
    ) -> NarrativeMapProviderResponse: ...

    def cancel(self) -> None: ...


class StructuredRunner(Protocol):
    def execute(
        self,
        request: SterileRunRequest,
        cancelled: CancelledCallback,
    ) -> SterileRunResult: ...

    def cancel(self) -> None: ...


class NarrativeMapProviderError(RuntimeError):
    """A sanitized failure code; callers persist the code and never the message."""

    def __init__(self, error_code: str, message: str, *, transient: bool = False) -> None:
        if _ERROR_CODE.fullmatch(error_code) is None:
            raise ValueError("provider error codes must be sanitized identifiers")
        super().__init__(message)
        self.error_code = error_code
        self.transient = transient


class SterileNarrativeMapProvider:
    """M15 semantics over the existing shell-free sterile Codex process runner."""

    def __init__(
        self,
        *,
        runner: StructuredRunner | None = None,
        executable: str = "codex",
    ) -> None:
        self._runner = runner or SterileCodexRunner(executable=executable)

    def cancel(self) -> None:
        self._runner.cancel()

    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: CancelledCallback,
    ) -> NarrativeMapProviderResponse:
        if cancelled():
            raise NarrativeMapProviderError("cancelled", "The provider request was cancelled.")
        request.validate_for_submission()
        prompt_name, schema_name = _resource_names(request.job.kind)
        prompt = _serialize_prompt(request, prompt_name)
        if len(prompt) > request.maximum_input_bytes:
            raise NarrativeMapProviderError("input_limit", "The provider request is too large.")
        schema_resource = files("renpy_story_mapper.narrative_map.schemas").joinpath(schema_name)
        reasoning = request.profile.settings.to_dict().get("reasoning_effort")
        if reasoning is not None and not isinstance(reasoning, str):
            raise NarrativeMapProviderError(
                "runtime_configuration_rejected", "The reasoning profile is invalid."
            )
        try:
            with as_file(schema_resource) as schema_path:
                sterile_request = SterileRunRequest(
                    model=request.profile.requested_model,
                    schema_path=schema_path,
                    stdin=prompt,
                    timeout_seconds=request.timeout_seconds,
                    maximum_output_bytes=request.maximum_output_bytes,
                    model_reasoning_effort=reasoning,
                )
                if cancelled():
                    raise NarrativeMapProviderError(
                        "cancelled", "The provider request was cancelled."
                    )
                request.consent.reserve_provider_call(request.job, request.profile)
                started_at = time.monotonic()
                result = self._runner.execute(
                    sterile_request,
                    cancelled,
                )
        except SterileRunnerError as exc:
            raise NarrativeMapProviderError(
                exc.error_code,
                "The sterile provider process failed safely.",
                transient=exc.transient,
            ) from None
        payload = _extract_payload(result)
        resolved_model = _resolved_model(result, request.profile.requested_model)
        if resolved_model != request.profile.requested_model:
            raise NarrativeMapProviderError(
                "model_mismatch", "The provider resolved a different model."
            )
        input_tokens, output_tokens, cost_micros = _usage(result)
        elapsed_ms = round((time.monotonic() - started_at) * 1000)
        return NarrativeMapProviderResponse(
            request_id=request.request_id,
            provider=ProviderIdentity(
                provider=request.profile.provider,
                adapter=request.profile.adapter,
                adapter_version=request.profile.adapter_version,
                requested_model=request.profile.requested_model,
                resolved_model=resolved_model,
                settings=request.profile.settings,
            ),
            payload=payload,
            usage=ProviderUsage(
                input_tokens,
                output_tokens,
                elapsed_ms,
                cost_micros=cost_micros,
            ),
        )


def _resource_names(kind: ProviderJobKind) -> tuple[str, str]:
    if kind is ProviderJobKind.BOUNDARY:
        return "boundary_decision_v1.json", "boundary_decision_v1.schema.json"
    return "event_summary_v1.json", "event_summary_v1.schema.json"


def _serialize_prompt(request: NarrativeMapProviderRequest, resource_name: str) -> bytes:
    resource = files("renpy_story_mapper.narrative_map.prompts").joinpath(resource_name)
    try:
        template = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise NarrativeMapProviderError(
            "prompt_template_invalid", "The M15 prompt template is unavailable."
        ) from None
    if not isinstance(template, dict) or template.get("version") != request.job.prompt_version:
        raise NarrativeMapProviderError(
            "prompt_version_mismatch", "The M15 prompt identity does not match."
        )
    envelope = {
        **template,
        "request": {
            "request_id": request.request_id,
            "consent_manifest_id": request.consent_manifest_id,
            "job_id": request.job.job_id,
            "input_hash": request.job.input_hash,
            "response_schema": request.job.response_schema,
            "schema_only_repair": bool(request.repair_codes),
            "repair_codes": list(request.repair_codes),
            "locked_semantics": request.repair_semantics,
            "job": request.job.payload,
        },
    }
    return json.dumps(
        envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _extract_payload(result: SterileRunResult) -> dict[str, object]:
    payloads: list[dict[str, object]] = []
    for event in result.events:
        if not isinstance(event, Mapping):
            continue
        item = event.get("item")
        if isinstance(item, Mapping) and item.get("type") == "agent_message":
            text = item.get("text")
            if isinstance(text, str):
                try:
                    decoded = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded, dict):
                    payloads.append(cast(dict[str, object], decoded))
        response = event.get("response")
        if isinstance(response, dict):
            payloads.append(cast(dict[str, object], response))
    if len(payloads) != 1:
        raise NarrativeMapProviderError(
            "response_envelope_invalid", "The provider returned no unique structured result."
        )
    return payloads[0]


def _resolved_model(result: SterileRunResult, requested_model: str) -> str:
    models = {
        value
        for event in result.events
        if isinstance(event, Mapping)
        for value in (event.get("model"),)
        if isinstance(value, str)
    }
    if not models:
        return requested_model
    if len(models) != 1:
        raise NarrativeMapProviderError(
            "model_metadata_conflict", "The provider returned conflicting model identities."
        )
    return next(iter(models))


def _usage(result: SterileRunResult) -> tuple[int, int, int | None]:
    latest: Mapping[object, object] | None = None
    for event in result.events:
        if isinstance(event, Mapping) and isinstance(event.get("usage"), Mapping):
            latest = cast(Mapping[object, object], event["usage"])
    if latest is None:
        raise NarrativeMapProviderError("usage_metadata_missing", "Provider usage is missing.")
    input_tokens = latest.get("input_tokens")
    output_tokens = latest.get("output_tokens")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in (input_tokens, output_tokens)
    ):
        raise NarrativeMapProviderError("usage_metadata_invalid", "Provider usage is invalid.")
    cost = latest.get("cost_micros")
    if cost is not None and (
        not isinstance(cost, int) or isinstance(cost, bool) or cost < 0
    ):
        raise NarrativeMapProviderError("usage_metadata_invalid", "Provider cost is invalid.")
    return cast(int, input_tokens), cast(int, output_tokens), cost


def _job_identity_hash(jobs: Sequence[PreparedNarrativeJob]) -> str:
    return canonical_hash([job.durable_metadata() for job in jobs])


def _consent_times(issued_value: str, expires_value: str) -> tuple[datetime, datetime]:
    try:
        issued = datetime.fromisoformat(issued_value)
        expires = datetime.fromisoformat(expires_value)
    except ValueError:
        raise ValueError("consent timestamps must be ISO-8601 values") from None
    if issued.tzinfo is None or expires.tzinfo is None:
        raise ValueError("consent timestamps must be timezone-aware")
    issued = issued.astimezone(UTC)
    expires = expires.astimezone(UTC)
    if expires <= issued or expires - issued > timedelta(hours=1):
        raise ValueError("consent freshness window is invalid")
    return issued, expires
