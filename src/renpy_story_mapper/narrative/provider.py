"""Provider-neutral M13 transport and one isolated Codex CLI cloud adapter.

Logical jobs remain independent even when several are transported together.  This module only
serializes bounded structured input, invokes the sterile direct-process boundary, captures exact
runtime provider identity and usage, and returns independently keyed output items.  Claim and
authority validation belong to the deterministic M13 validation layer.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import as_file, files
from typing import Protocol, cast

from renpy_story_mapper.narrative.contracts import (
    JsonScalar,
    JsonValue,
    ProviderIdentity,
    ProviderSettings,
)
from renpy_story_mapper.organization.sterile_runner import (
    SterileCodexRunner,
    SterileRunnerError,
    SterileRunRequest,
    SterileRunResult,
)

PROMPT_TEMPLATE_VERSION = "m13-narrative-batch-prompt-v4"
RESPONSE_SCHEMA_VERSION = "m13-narrative-batch-response-v3"
ADAPTER_NAME = "codex_cli_structured"
ADAPTER_VERSION = "m13-codex-cli-adapter-v3"
DEFAULT_MAXIMUM_INPUT_BYTES = 512_000
DEFAULT_MAXIMUM_OUTPUT_BYTES = 256_000
HARD_MAXIMUM_INPUT_BYTES = 2_000_000
HARD_MAXIMUM_OUTPUT_BYTES = 2_000_000
HARD_MAXIMUM_BATCH_ITEMS = 64

_PROMPT_RESOURCE = "narrative_batch_v4.json"
_SCHEMA_RESOURCE = "narrative_batch_v3.schema.json"
_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh"})
_SETTING_KEYS = frozenset({"fast_mode", "model_reasoning_effort"})


def _require_text(value: str, label: str, *, maximum: int = 200) -> None:
    if not value or value != value.strip() or len(value) > maximum or not value.isprintable():
        raise ValueError(f"{label} must be a trimmed printable string of at most {maximum} chars")


def _json_value(value: object, *, label: str) -> JsonValue:
    """Copy one value into the strict JSON value domain, rejecting NaN and foreign types."""

    if value is None or isinstance(value, (str, bool, int)):
        return cast(JsonScalar, value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{label} cannot contain non-finite numbers")
        return value
    if isinstance(value, list):
        return [_json_value(item, label=label) for item in value]
    if isinstance(value, dict):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{label} object keys must be strings")
            result[key] = _json_value(item, label=label)
        return result
    raise ValueError(f"{label} must contain JSON values only")


def _json_object(value: object, *, label: str) -> dict[str, JsonValue]:
    normalized = _json_value(value, label=label)
    if not isinstance(normalized, dict):
        raise ValueError(f"{label} must be a JSON object")
    return normalized


def validate_codex_provider_settings(settings: ProviderSettings) -> str | None:
    """Validate the exact bounded Codex adapter settings before provider discovery."""

    values = settings.to_dict()
    unknown = set(values) - _SETTING_KEYS
    if unknown:
        raise ProviderRuntimeConfigurationError(
            "runtime_configuration_rejected",
            "The provider settings contain an unsupported key.",
        )
    reasoning = values.get("model_reasoning_effort")
    if reasoning is not None and reasoning not in _REASONING_EFFORTS:
        raise ProviderRuntimeConfigurationError(
            "runtime_configuration_rejected",
            "The provider reasoning effort is unsupported.",
        )
    fast_mode = values.get("fast_mode")
    if fast_mode is not None and fast_mode is not False:
        raise ProviderRuntimeConfigurationError(
            "runtime_configuration_rejected",
            "Fast mode must remain disabled for this provider adapter.",
        )
    return reasoning


@dataclass(frozen=True)
class ProviderBatchItem:
    """One independently identified logical job inside a provider transport request."""

    logical_job_id: str
    input_revision_id: str
    payload: dict[str, JsonValue]

    def __post_init__(self) -> None:
        _require_text(self.logical_job_id, "logical job ID", maximum=160)
        _require_text(self.input_revision_id, "input revision ID", maximum=160)
        normalized = _json_object(self.payload, label="provider item payload")
        if not normalized:
            raise ValueError("provider item payload cannot be empty")
        object.__setattr__(self, "payload", normalized)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "logical_job_id": self.logical_job_id,
            "input_revision_id": self.input_revision_id,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class ProviderRequest:
    """One consent-bound cloud transmission containing independent logical items."""

    request_id: str
    consent_manifest_id: str
    requested_model: str
    settings: ProviderSettings
    items: tuple[ProviderBatchItem, ...]
    timeout_seconds: float
    maximum_output_bytes: int = DEFAULT_MAXIMUM_OUTPUT_BYTES
    maximum_input_bytes: int = DEFAULT_MAXIMUM_INPUT_BYTES

    def __post_init__(self) -> None:
        _require_text(self.request_id, "provider request ID", maximum=160)
        _require_text(self.consent_manifest_id, "consent manifest ID", maximum=160)
        _require_text(self.requested_model, "requested model")
        if not self.items:
            raise ValueError("provider requests require at least one logical item")
        if len(self.items) > HARD_MAXIMUM_BATCH_ITEMS:
            raise ValueError("provider request exceeds the hard item-count limit")
        identifiers = tuple(item.logical_job_id for item in self.items)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("provider requests cannot repeat a logical job ID")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("provider timeout must be a finite positive number")
        if not 0 < self.maximum_input_bytes <= HARD_MAXIMUM_INPUT_BYTES:
            raise ValueError("provider input-byte limit is outside the hard bound")
        if not 0 < self.maximum_output_bytes <= HARD_MAXIMUM_OUTPUT_BYTES:
            raise ValueError("provider output-byte limit is outside the hard bound")


@dataclass(frozen=True)
class ProviderOutputItem:
    """A safe per-item transport result; malformed siblings do not erase valid items."""

    logical_job_id: str | None
    transport_index: int
    payload: dict[str, JsonValue] | None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.logical_job_id is not None:
            _require_text(self.logical_job_id, "output logical job ID", maximum=160)
        if self.transport_index < 0:
            raise ValueError("transport index cannot be negative")
        if self.error_code is None:
            if self.logical_job_id is None or self.payload is None:
                raise ValueError("successful output items require an ID and payload")
            object.__setattr__(
                self,
                "payload",
                _json_object(self.payload, label="provider output payload"),
            )
        else:
            if not _ERROR_CODE.fullmatch(self.error_code):
                raise ValueError("provider error codes must be sanitized identifiers")
            if self.payload is not None:
                raise ValueError("failed provider output items cannot carry payloads")

    @property
    def succeeded(self) -> bool:
        return self.error_code is None


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int
    output_tokens: int
    elapsed_ms: int
    cost_micros: int | None = None
    provider_calls: int = 1

    def __post_init__(self) -> None:
        for name in ("input_tokens", "output_tokens", "elapsed_ms"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.cost_micros is not None and (
            not isinstance(self.cost_micros, int)
            or isinstance(self.cost_micros, bool)
            or self.cost_micros < 0
        ):
            raise ValueError("cost_micros must be a non-negative integer when supplied")
        if self.provider_calls != 1:
            raise ValueError("one provider response must account for exactly one call")


@dataclass(frozen=True)
class ProviderResponse:
    request_id: str
    provider: ProviderIdentity
    items: tuple[ProviderOutputItem, ...]
    usage: ProviderUsage
    prompt_template_version: str
    response_schema_version: str

    def __post_init__(self) -> None:
        _require_text(self.request_id, "provider response request ID", maximum=160)
        _require_text(self.prompt_template_version, "prompt template version")
        _require_text(self.response_schema_version, "response schema version")


@dataclass(frozen=True)
class ProviderStatus:
    available: bool
    provider: str
    adapter: str
    adapter_version: str
    cli_version: str | None = None
    message_code: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.provider, "provider name")
        _require_text(self.adapter, "provider adapter")
        _require_text(self.adapter_version, "provider adapter version")
        if self.cli_version is not None:
            _require_text(self.cli_version, "CLI version")
        if self.message_code is not None and not _ERROR_CODE.fullmatch(self.message_code):
            raise ValueError("provider status codes must be sanitized identifiers")


class NarrativeProviderError(RuntimeError):
    """Sanitized provider failure with explicit scheduler retry eligibility."""

    def __init__(self, error_code: str, message: str, *, transient: bool = False) -> None:
        if not _ERROR_CODE.fullmatch(error_code):
            raise ValueError("provider error codes must be sanitized identifiers")
        super().__init__(message)
        self.error_code = error_code
        self.transient = transient


class ProviderUnavailableError(NarrativeProviderError):
    pass


class ProviderRateLimitError(NarrativeProviderError):
    pass


class ProviderTimeoutError(NarrativeProviderError):
    pass


class ProviderCancelledError(NarrativeProviderError):
    pass


class ProviderPolicyViolationError(NarrativeProviderError):
    pass


class ProviderOutputError(NarrativeProviderError):
    pass


class ProviderRefusalError(NarrativeProviderError):
    pass


class ProviderIdentityMismatchError(NarrativeProviderError):
    pass


class ProviderLimitError(NarrativeProviderError):
    pass


class ProviderSchemaRejectedError(NarrativeProviderError):
    pass


class ProviderRuntimeConfigurationError(NarrativeProviderError):
    pass


class ProviderAuthenticationError(NarrativeProviderError):
    pass


class ProviderProcessError(NarrativeProviderError):
    pass


class ProviderTransportError(NarrativeProviderError):
    pass


class ProviderServerTransientError(NarrativeProviderError):
    pass


CancelledCallback = Callable[[], bool]


class NarrativeProvider(Protocol):
    def status(self) -> ProviderStatus: ...

    def submit(
        self,
        request: ProviderRequest,
        cancelled: CancelledCallback,
    ) -> ProviderResponse: ...

    def cancel(self) -> None: ...


class StructuredRunner(Protocol):
    def status(self) -> tuple[str | None, str | None]: ...

    def execute(
        self,
        request: SterileRunRequest,
        cancelled: CancelledCallback,
    ) -> SterileRunResult: ...

    def cancel(self) -> None: ...


class CodexCliNarrativeProvider:
    """Approved cloud adapter over the existing direct Codex CLI process boundary."""

    def __init__(
        self,
        *,
        provider_name: str = "openai",
        runner: StructuredRunner | None = None,
        executable: str = "codex",
    ) -> None:
        _require_text(provider_name, "provider name")
        self._provider_name = provider_name
        self._runner = runner or SterileCodexRunner(executable=executable)

    def status(self) -> ProviderStatus:
        resolved, cli_version = self._runner.status()
        return ProviderStatus(
            available=resolved is not None,
            provider=self._provider_name,
            adapter=ADAPTER_NAME,
            adapter_version=ADAPTER_VERSION,
            cli_version=cli_version,
            message_code=None if resolved is not None else "provider_unavailable",
        )

    def cancel(self) -> None:
        self._runner.cancel()

    def submit(
        self,
        request: ProviderRequest,
        cancelled: CancelledCallback,
    ) -> ProviderResponse:
        if cancelled():
            raise ProviderCancelledError("cancelled", "The provider request was cancelled.")
        reasoning_effort = validate_codex_provider_settings(request.settings)
        status = self.status()
        if not status.available:
            raise ProviderUnavailableError(
                "provider_unavailable",
                "The cloud provider adapter is unavailable.",
            )
        prompt = _serialize_prompt(request)
        if len(prompt) > request.maximum_input_bytes:
            raise ProviderLimitError(
                "input_limit",
                "The structured provider request exceeds its input-byte limit.",
            )
        schema = files("renpy_story_mapper.narrative.schemas").joinpath(_SCHEMA_RESOURCE)
        started_at = time.monotonic()
        try:
            with as_file(schema) as schema_path:
                run_result = self._runner.execute(
                    SterileRunRequest(
                        model=request.requested_model,
                        schema_path=schema_path,
                        stdin=prompt,
                        timeout_seconds=request.timeout_seconds,
                        maximum_output_bytes=request.maximum_output_bytes,
                        model_reasoning_effort=reasoning_effort,
                    ),
                    cancelled,
                )
        except SterileRunnerError as exc:
            raise _mapped_runner_error(exc) from None
        elapsed_ms = round((time.monotonic() - started_at) * 1000)
        resolved_model = _resolved_model(
            run_result.events,
            requested_model=request.requested_model,
        )
        if resolved_model != request.requested_model:
            raise ProviderIdentityMismatchError(
                "model_mismatch",
                "The provider resolved a different model than requested.",
            )
        input_tokens, output_tokens, cost_micros = _usage(run_result.events)
        payload = _single_response_payload(run_result.events)
        output_items = _parse_output_items(payload)
        identity = ProviderIdentity(
            provider=self._provider_name,
            adapter=ADAPTER_NAME,
            adapter_version=ADAPTER_VERSION,
            requested_model=request.requested_model,
            resolved_model=resolved_model,
            settings=request.settings,
        )
        return ProviderResponse(
            request_id=request.request_id,
            provider=identity,
            items=output_items,
            usage=ProviderUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                elapsed_ms=elapsed_ms,
                cost_micros=cost_micros,
            ),
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            response_schema_version=RESPONSE_SCHEMA_VERSION,
        )


def _serialize_prompt(request: ProviderRequest) -> bytes:
    resource = files("renpy_story_mapper.narrative.prompts").joinpath(_PROMPT_RESOURCE)
    try:
        template_raw: object = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ProviderOutputError(
            "prompt_template_invalid",
            "The versioned provider prompt template is unavailable or invalid.",
        ) from None
    try:
        template = _json_object(template_raw, label="provider prompt template")
    except ValueError:
        raise ProviderOutputError(
            "prompt_template_invalid",
            "The versioned provider prompt template is unavailable or invalid.",
        ) from None
    if template.get("template_version") != PROMPT_TEMPLATE_VERSION:
        raise ProviderOutputError(
            "prompt_version_mismatch",
            "The provider prompt template version does not match the adapter.",
        )
    envelope: dict[str, JsonValue] = {
        **template,
        "request": {
            "request_id": request.request_id,
            "consent_manifest_id": request.consent_manifest_id,
            "requested_model": request.requested_model,
            "settings": request.settings.to_dict(),
            "logical_jobs": [item.to_dict() for item in request.items],
        },
    }
    return json.dumps(
        envelope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _resolved_model(
    events: tuple[object, ...],
    *,
    requested_model: str,
) -> str:
    models: set[str] = set()
    for event in events:
        if not isinstance(event, dict) or "model" not in event:
            continue
        model = event["model"]
        if not isinstance(model, str):
            raise ProviderOutputError(
                "model_metadata_invalid",
                "The provider returned invalid model metadata.",
            )
        try:
            _require_text(model, "resolved model")
        except ValueError:
            raise ProviderOutputError(
                "model_metadata_invalid",
                "The provider returned invalid model metadata.",
            ) from None
        models.add(model)
    if not models:
        # Codex CLI 0.144 may omit redundant model metadata on a successful run.  The
        # explicit, validated --model selection remains authoritative in that case.
        return requested_model
    if len(models) != 1:
        raise ProviderIdentityMismatchError(
            "model_metadata_conflict",
            "The provider reported conflicting resolved model identities.",
        )
    return next(iter(models))


def _usage(events: tuple[object, ...]) -> tuple[int, int, int | None]:
    latest: dict[object, object] | None = None
    for event in events:
        if isinstance(event, dict) and isinstance(event.get("usage"), dict):
            latest = event["usage"]
    if latest is None:
        raise ProviderOutputError(
            "usage_metadata_missing",
            "The provider did not report token usage.",
        )
    input_tokens = latest.get("input_tokens")
    output_tokens = latest.get("output_tokens")
    for value in (input_tokens, output_tokens):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ProviderOutputError(
                "usage_metadata_invalid",
                "The provider returned invalid token usage.",
            )
    cost = latest.get("cost_micros")
    if cost is not None and (not isinstance(cost, int) or isinstance(cost, bool) or cost < 0):
        raise ProviderOutputError(
            "cost_metadata_invalid",
            "The provider returned invalid cost metadata.",
        )
    return cast(int, input_tokens), cast(int, output_tokens), cost


def _single_response_payload(events: tuple[object, ...]) -> dict[str, object]:
    candidates: list[dict[str, object]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if set(event) == {"items"} and isinstance(event.get("items"), list):
            candidates.append(cast(dict[str, object], event))
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            text = item.get("text")
            if isinstance(text, str):
                try:
                    decoded: object = json.loads(text)
                except json.JSONDecodeError:
                    decoded = None
                if isinstance(decoded, dict):
                    candidates.append(cast(dict[str, object], decoded))
        response = event.get("response")
        if isinstance(response, dict):
            candidates.append(cast(dict[str, object], response))
    if len(candidates) != 1:
        raise ProviderOutputError(
            "response_envelope_invalid",
            "The provider did not return exactly one structured response envelope.",
        )
    if set(candidates[0]) != {"items"} or not isinstance(candidates[0]["items"], list):
        raise ProviderOutputError(
            "response_envelope_invalid",
            "The provider response envelope is invalid.",
        )
    return candidates[0]


def _parse_output_items(payload: dict[str, object]) -> tuple[ProviderOutputItem, ...]:
    raw_items = cast(list[object], payload["items"])
    results: list[ProviderOutputItem] = []
    for index, raw_item in enumerate(raw_items):
        logical_job_id: str | None = None
        if isinstance(raw_item, dict):
            candidate_id = raw_item.get("logical_job_id")
            if isinstance(candidate_id, str):
                try:
                    _require_text(candidate_id, "output logical job ID", maximum=160)
                except ValueError:
                    pass
                else:
                    logical_job_id = candidate_id
            status = raw_item.get("status")
            if status == "ok" and raw_item.get("error_code") is None:
                try:
                    normalized = _json_object(
                        raw_item.get("payload"),
                        label="provider output payload",
                    )
                except ValueError:
                    pass
                else:
                    if logical_job_id is not None:
                        results.append(
                            ProviderOutputItem(
                                logical_job_id=logical_job_id,
                                transport_index=index,
                                payload=normalized,
                            )
                        )
                        continue
            if (
                status == "content_refusal"
                and raw_item.get("payload") is None
                and raw_item.get("error_code") == "content_refusal"
            ):
                results.append(
                    ProviderOutputItem(
                        logical_job_id=logical_job_id,
                        transport_index=index,
                        payload=None,
                        error_code="content_refusal",
                    )
                )
                continue
        results.append(
            ProviderOutputItem(
                logical_job_id=logical_job_id,
                transport_index=index,
                payload=None,
                error_code="malformed_provider_item",
            )
        )
    return tuple(results)


def _mapped_runner_error(error: SterileRunnerError) -> NarrativeProviderError:
    code = error.error_code
    if code == "cancelled":
        return ProviderCancelledError("cancelled", "The provider request was cancelled.")
    if code in {"timeout", "startup_timeout"}:
        return ProviderTimeoutError(code, "The provider request timed out.", transient=True)
    if code == "rate_limited":
        return ProviderRateLimitError(
            code,
            "The provider is rate limited.",
            transient=True,
        )
    if code == "transport_failure":
        return ProviderTransportError(
            code,
            "The provider transport failed.",
            transient=True,
        )
    if code == "server_transient":
        return ProviderServerTransientError(
            code,
            "The provider server failed temporarily.",
            transient=True,
        )
    if code == "policy_violation":
        return ProviderPolicyViolationError(
            code,
            "The provider attempted a forbidden action.",
        )
    if code == "provider_refusal":
        return ProviderRefusalError(code, "The provider refused the request.")
    if code in {"output_limit"}:
        return ProviderLimitError(code, "The provider exceeded a hard transport limit.")
    if code in {"invalid_jsonl"}:
        return ProviderOutputError(code, "The provider returned invalid structured output.")
    if code == "output_schema_rejected":
        return ProviderSchemaRejectedError(
            code,
            "The provider rejected the output schema.",
        )
    if code == "runtime_configuration_rejected":
        return ProviderRuntimeConfigurationError(
            code,
            "The provider runtime configuration was rejected.",
        )
    if code in {"authentication_failed", "provider_auth"}:
        return ProviderAuthenticationError(
            "authentication_failed",
            "The provider authentication was rejected.",
        )
    if code == "provider_unavailable":
        return ProviderUnavailableError(
            code,
            "The cloud provider adapter is unavailable.",
        )
    return ProviderProcessError(
        "provider_process_failed",
        "The provider process failed.",
    )
