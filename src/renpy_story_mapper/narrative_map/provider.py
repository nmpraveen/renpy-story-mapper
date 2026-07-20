"""Provider-neutral transport beneath the M15 semantic boundary.

The prepared job payload is transient.  Only validated normalized results and identity metadata
may cross into :mod:`narrative_map.persistence`.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from importlib.resources import as_file, files
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


@dataclass(frozen=True)
class NarrativeMapProviderRequest:
    request_id: str
    consent_manifest_id: str
    profile: ProviderProfile
    job: PreparedNarrativeJob
    repair_codes: tuple[str, ...] = ()
    timeout_seconds: float = 300.0
    maximum_output_bytes: int = MAXIMUM_OUTPUT_BYTES

    def __post_init__(self) -> None:
        for value, label in (
            (self.request_id, "provider request ID"),
            (self.consent_manifest_id, "consent manifest ID"),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{label} must be a non-empty trimmed string")
        if self.timeout_seconds <= 0 or self.maximum_output_bytes <= 0:
            raise ValueError("provider bounds must be positive")
        if len(self.repair_codes) != len(set(self.repair_codes)):
            raise ValueError("repair codes must be unique")


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
        prompt_name, schema_name = _resource_names(request.job.kind)
        prompt = _serialize_prompt(request, prompt_name)
        if len(prompt) > MAXIMUM_INPUT_BYTES:
            raise NarrativeMapProviderError("input_limit", "The provider request is too large.")
        schema_resource = files("renpy_story_mapper.narrative_map.schemas").joinpath(schema_name)
        reasoning = request.profile.settings.to_dict().get("reasoning_effort")
        if reasoning is not None and not isinstance(reasoning, str):
            raise NarrativeMapProviderError(
                "runtime_configuration_rejected", "The reasoning profile is invalid."
            )
        try:
            with as_file(schema_resource) as schema_path:
                started_at = time.monotonic()
                result = self._runner.execute(
                    SterileRunRequest(
                        model=request.profile.requested_model,
                        schema_path=schema_path,
                        stdin=prompt,
                        timeout_seconds=request.timeout_seconds,
                        maximum_output_bytes=request.maximum_output_bytes,
                        model_reasoning_effort=reasoning,
                    ),
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
