"""A small schema-constrained Codex CLI seam for the AI-first storyboard path.

The client is deliberately independent of the repository's durable workflows.  One call receives
one JSON object on stdin, runs in an isolated temporary directory with a read-only sandbox, and
returns one schema-bound JSON object.  It never reads the game directory or invokes a shell.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError  # type: ignore[import-untyped]

_POLL_SECONDS = 0.05
_CANCEL_GRACE_SECONDS = 0.5
_KILL_GRACE_SECONDS = 0.1
_MAX_MODEL_LENGTH = 200
_REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh"})
_MAXIMUM_DEFAULT_INPUT_BYTES = 2_000_000
_MAXIMUM_DEFAULT_OUTPUT_BYTES = 2_000_000

_DISABLED_CODEX_FEATURES = (
    "plugins",
    "apps",
    "hooks",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "computer_use",
    "image_generation",
    "in_app_browser",
    "multi_agent",
    "goals",
    "shell_tool",
    "tool_call_mcp_elicitation",
    "tool_suggest",
    "workspace_dependencies",
)
_FORBIDDEN_MARKERS = frozenset(
    {
        "apply_patch",
        "collab_tool_call",
        "command_execution",
        "dynamic_tool_call",
        "file_change",
        "function_call",
        "mcp_tool_call",
        "provider_call",
        "shell_command",
        "web_search",
    }
)
_POLICY_TYPE_FIELDS = frozenset({"type", "kind", "name", "tool", "tool_name"})
_TEXT_PAYLOAD_FIELDS = frozenset({"text", "message", "content", "output", "summary"})
_SAFE_CODEX_ITEM_TYPES = frozenset({"agent_message", "error", "reasoning", "todo_list"})
_METADATA_KEYS = frozenset(
    {"model", "reasoning_effort", "model_reasoning_effort", "fast_mode"}
)


class TransmissionDisposition(StrEnum):
    """Whether the request crossed the child-process boundary."""

    NOT_TRANSMITTED = "not_transmitted"
    TRANSMITTED = "transmitted"
    UNKNOWN = "unknown"


class StoryboardAIError(RuntimeError):
    """Sanitized, machine-readable failure from the storyboard AI boundary."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        transient: bool = False,
        transmission: TransmissionDisposition = TransmissionDisposition.UNKNOWN,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.transient = transient
        self.transmission = transmission


class ProviderUnavailableError(StoryboardAIError):
    pass


class ProviderAuthenticationError(StoryboardAIError):
    pass


class ProviderRateLimitError(StoryboardAIError):
    pass


class ProviderTimeoutError(StoryboardAIError):
    pass


class ProviderCancelledError(StoryboardAIError):
    pass


class ProviderPolicyViolationError(StoryboardAIError):
    pass


class ProviderOutputError(StoryboardAIError):
    pass


class ProviderIdentityMismatchError(StoryboardAIError):
    pass


class ProviderLimitError(StoryboardAIError):
    pass


class ProviderProcessError(StoryboardAIError):
    pass


class ProviderRuntimeConfigurationError(StoryboardAIError):
    pass


@dataclass(frozen=True)
class ProcessSpec:
    """The exact child-process invocation, exposed for focused mocked tests."""

    command: tuple[str, ...]
    cwd: Path
    shell: bool = False


class Process(Protocol):
    returncode: int | None

    def communicate(
        self, input: bytes | None = None, timeout: float | None = None
    ) -> tuple[bytes, bytes]: ...

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


ProcessFactory = Callable[[ProcessSpec], Process]
ExecutableResolver = Callable[[str], str | None]
CancelledCallback = Callable[[], bool]


@dataclass(frozen=True)
class RuntimeMetadata:
    """Observed provider identity and bounded accounting for the last successful call."""

    requested_model: str
    resolved_model: str
    requested_reasoning_effort: str
    resolved_reasoning_effort: str | None
    requested_fast_mode: bool
    resolved_fast_mode: bool | None
    metadata_verified: bool
    cli_version: str | None
    input_tokens: int | None
    output_tokens: int | None
    elapsed_ms: int


class StoryboardJsonClient(Protocol):
    """Provider-neutral contract used by profile and story-analysis callers."""

    def complete(
        self,
        *,
        payload: Mapping[str, object],
        schema_path: Path,
        model: str,
        reasoning_effort: str,
        fast_mode: bool,
        timeout_seconds: float | None = None,
        cancelled: CancelledCallback = lambda: False,
    ) -> dict[str, object]: ...

    def cancel(self) -> None: ...


def _validate_model(model: str) -> None:
    if (
        not model
        or model != model.strip()
        or len(model) > _MAX_MODEL_LENGTH
        or not model.isprintable()
    ):
        raise ValueError("model must be a trimmed printable string of at most 200 characters")


def _validate_reasoning_effort(reasoning_effort: str) -> None:
    if reasoning_effort not in _REASONING_EFFORTS:
        raise ValueError("reasoning_effort must be one of low, medium, high, or xhigh")


def _load_schema_validator(schema_path: Path) -> tuple[Path, Draft202012Validator]:
    resolved = schema_path.resolve()
    if not resolved.is_absolute() or not resolved.is_file():
        raise ValueError("schema_path must be an existing absolute file")
    try:
        schema = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("schema_path must contain valid UTF-8 JSON") from None
    if not isinstance(schema, dict):
        raise ValueError("schema_path must contain a JSON object")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        raise ValueError("schema_path must contain a valid JSON schema") from None
    return resolved, Draft202012Validator(schema)


def _validate_schema_path(schema_path: Path) -> Path:
    resolved, _validator = _load_schema_validator(schema_path)
    return resolved


def _serialize_payload(payload: Mapping[str, object]) -> bytes:
    try:
        encoded = json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise ValueError("provider payload must be a finite JSON object") from None
    if not encoded:
        raise ValueError("provider payload cannot be empty")
    return encoded


def _default_process_factory(spec: ProcessSpec) -> Process:
    creation_flags = cast(int, getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return cast(
        Process,
        subprocess.Popen(
            spec.command,
            cwd=spec.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=spec.shell,
            creationflags=creation_flags,
        ),
    )


def discover_native_codex(executable: str = "codex") -> str | None:
    """Resolve a native executable without delegating a ``.cmd`` shim to a shell."""

    configured = Path(executable)
    if configured.is_absolute():
        if configured.suffix.casefold() == ".exe" and configured.is_file():
            return str(configured.resolve())
        return None
    if configured.name != executable:
        return None
    candidates: list[Path] = []
    for raw_directory in os.environ.get("PATH", "").split(os.pathsep):
        directory_text = raw_directory.strip().strip('"')
        if not directory_text:
            continue
        directory = Path(directory_text)
        if not directory.is_absolute():
            continue
        candidates.append(directory / f"{executable}.exe")
        package_root = directory / "node_modules" / "@openai" / "codex"
        candidates.extend(
            sorted(package_root.glob("node_modules/@openai/codex-*/vendor/*/bin/codex.exe"))
        )
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate.is_file():
            continue
        resolved = str(candidate.resolve())
        key = resolved.casefold()
        if key not in seen:
            seen.add(key)
            return resolved
    return None


def build_codex_command(
    executable: str,
    *,
    model: str,
    reasoning_effort: str,
    fast_mode: bool,
    schema_path: Path,
) -> tuple[str, ...]:
    """Build the direct, ephemeral, schema-constrained command for one call."""

    if not Path(executable).is_absolute() or Path(executable).suffix.casefold() != ".exe":
        raise ValueError("the client requires an absolute native Codex executable")
    _validate_model(model)
    _validate_reasoning_effort(reasoning_effort)
    resolved_schema = _validate_schema_path(schema_path)
    arguments: list[str] = [
        executable,
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
    ]
    for feature in _DISABLED_CODEX_FEATURES:
        arguments.extend(("--disable", feature))
    arguments.extend(
        (
            "-c",
            f'model_reasoning_effort="{reasoning_effort}"',
            "-c",
            f"fast_mode={'true' if fast_mode else 'false'}",
            "-c",
            'web_search="disabled"',
            "-c",
            "analytics.enabled=false",
            "--json",
            "--output-schema",
            str(resolved_schema),
            "--model",
            model,
            "-",
        )
    )
    return tuple(arguments)


class CodexCliJsonClient:
    """Run one bounded JSON request through a direct native Codex CLI process."""

    def __init__(
        self,
        *,
        executable: str = "codex",
        process_factory: ProcessFactory = _default_process_factory,
        executable_resolver: ExecutableResolver = discover_native_codex,
        timeout_seconds: float = 300.0,
        maximum_input_bytes: int = _MAXIMUM_DEFAULT_INPUT_BYTES,
        maximum_output_bytes: int = _MAXIMUM_DEFAULT_OUTPUT_BYTES,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if maximum_input_bytes <= 0 or maximum_output_bytes <= 0:
            raise ValueError("provider byte limits must be positive")
        self._executable = executable
        self._process_factory = process_factory
        self._executable_resolver = executable_resolver
        self._timeout_seconds = timeout_seconds
        self._maximum_input_bytes = maximum_input_bytes
        self._maximum_output_bytes = maximum_output_bytes
        self._cancel_generation = 0
        self._active: Process | None = None
        self._lock = threading.Lock()
        self._resolved_executable: str | None = None
        self._last_metadata: RuntimeMetadata | None = None

    @property
    def last_metadata(self) -> RuntimeMetadata | None:
        return self._last_metadata

    def cancel(self) -> None:
        with self._lock:
            self._cancel_generation += 1
            active = self._active
        if active is not None:
            _stop_process(active)

    def complete(
        self,
        *,
        payload: Mapping[str, object],
        schema_path: Path,
        model: str,
        reasoning_effort: str,
        fast_mode: bool,
        timeout_seconds: float | None = None,
        cancelled: CancelledCallback = lambda: False,
    ) -> dict[str, object]:
        started = time.monotonic()
        self._last_metadata = None
        _validate_model(model)
        _validate_reasoning_effort(reasoning_effort)
        if not isinstance(fast_mode, bool):
            raise ValueError("fast_mode must be a boolean")
        resolved_schema, response_validator = _load_schema_validator(schema_path)
        request = _serialize_payload(payload)
        if len(request) > self._maximum_input_bytes:
            raise ProviderLimitError(
                "input_limit",
                "The storyboard AI request exceeds its input limit.",
                transmission=TransmissionDisposition.NOT_TRANSMITTED,
            )
        with self._lock:
            generation = self._cancel_generation

        def is_cancelled() -> bool:
            return cancelled() or self._generation_changed(generation)

        if is_cancelled():
            raise ProviderCancelledError(
                "cancelled",
                "The storyboard AI request was cancelled.",
                transmission=TransmissionDisposition.NOT_TRANSMITTED,
            )
        executable = self._resolved_executable or self._executable_resolver(self._executable)
        if executable is None:
            raise ProviderUnavailableError(
                "provider_unavailable",
                "The native Codex CLI is unavailable.",
                transmission=TransmissionDisposition.NOT_TRANSMITTED,
            )
        self._resolved_executable = executable
        command = build_codex_command(
            executable,
            model=model,
            reasoning_effort=reasoning_effort,
            fast_mode=fast_mode,
            schema_path=resolved_schema,
        )
        process: Process | None = None
        try:
            with tempfile.TemporaryDirectory(prefix="renpy-storyboard-ai-") as directory:
                spec = ProcessSpec(command=command, cwd=Path(directory).resolve())
                try:
                    process = self._process_factory(spec)
                except Exception:
                    raise ProviderUnavailableError(
                        "provider_start_failed",
                        "The native Codex CLI could not start.",
                        transmission=TransmissionDisposition.NOT_TRANSMITTED,
                    ) from None
                with self._lock:
                    self._active = process
                try:
                    stdout, stderr = self._communicate(
                        process,
                        request,
                        timeout_seconds=(
                            self._timeout_seconds if timeout_seconds is None else timeout_seconds
                        ),
                        cancelled=is_cancelled,
                    )
                finally:
                    with self._lock:
                        if self._active is process:
                            self._active = None
                    if process.poll() is None:
                        _stop_process(process)
                if process.returncode != 0:
                    _raise_process_failure(
                        stderr,
                        transmission=TransmissionDisposition.TRANSMITTED,
                    )
                payload_value, observed = _parse_jsonl(stdout)
                if next(response_validator.iter_errors(payload_value), None) is not None:
                    raise ProviderOutputError(
                        "schema_mismatch",
                        "The provider returned JSON that does not match the requested schema.",
                        transmission=TransmissionDisposition.TRANSMITTED,
                    )
        except StoryboardAIError:
            raise
        except OSError:
            raise ProviderProcessError(
                "provider_process_failed",
                "The native Codex CLI process failed.",
                transmission=TransmissionDisposition.UNKNOWN,
            ) from None
        elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
        metadata = _verify_runtime_metadata(
            observed,
            requested_model=model,
            requested_reasoning_effort=reasoning_effort,
            requested_fast_mode=fast_mode,
            elapsed_ms=elapsed_ms,
        )
        self._last_metadata = metadata
        return payload_value

    def _generation_changed(self, generation: int) -> bool:
        with self._lock:
            return self._cancel_generation != generation

    def _communicate(
        self,
        process: Process,
        request: bytes,
        *,
        timeout_seconds: float,
        cancelled: CancelledCallback,
    ) -> tuple[bytes, bytes]:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        deadline = time.monotonic() + timeout_seconds
        pending: bytes | None = request
        transmitted = False
        while True:
            if cancelled():
                _stop_process(process)
                raise ProviderCancelledError(
                    "cancelled",
                    "The storyboard AI request was cancelled.",
                    transmission=(
                        TransmissionDisposition.TRANSMITTED
                        if transmitted
                        else TransmissionDisposition.NOT_TRANSMITTED
                    ),
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _stop_process(process)
                raise ProviderTimeoutError(
                    "timeout",
                    "The storyboard AI request timed out.",
                    transient=True,
                    transmission=(
                        TransmissionDisposition.TRANSMITTED
                        if transmitted
                        else TransmissionDisposition.NOT_TRANSMITTED
                    ),
                )
            try:
                stdout, stderr = process.communicate(
                    input=pending,
                    timeout=min(_POLL_SECONDS, remaining),
                )
            except subprocess.TimeoutExpired as error:
                transmitted = True
                pending = None
                partial = _as_bytes(getattr(error, "output", None)) + _as_bytes(
                    getattr(error, "stderr", None)
                )
                if len(partial) > self._maximum_output_bytes:
                    _stop_process(process)
                    raise ProviderLimitError(
                        "output_limit",
                        "The storyboard AI output exceeds its transport limit.",
                        transmission=TransmissionDisposition.TRANSMITTED,
                    ) from None
                continue
            except OSError:
                _stop_process(process)
                raise ProviderProcessError(
                    "transport_failure",
                    "The storyboard AI transport failed.",
                    transient=True,
                    transmission=(
                        TransmissionDisposition.TRANSMITTED
                        if transmitted
                        else TransmissionDisposition.NOT_TRANSMITTED
                    ),
                ) from None
            transmitted = True
            if len(stdout) + len(stderr) > self._maximum_output_bytes:
                raise ProviderLimitError(
                    "output_limit",
                    "The storyboard AI output exceeds its transport limit.",
                    transmission=TransmissionDisposition.TRANSMITTED,
                )
            return stdout, stderr


@dataclass(frozen=True)
class _ObservedMetadata:
    models: frozenset[str]
    reasonings: frozenset[str]
    fast_modes: frozenset[bool]
    cli_versions: frozenset[str]
    input_tokens: int | None
    output_tokens: int | None


def _parse_jsonl(raw: bytes) -> tuple[dict[str, object], _ObservedMetadata]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise ProviderOutputError(
            "invalid_utf8",
            "The provider returned non-UTF-8 structured output.",
            transmission=TransmissionDisposition.TRANSMITTED,
        ) from None
    candidates: list[dict[str, object]] = []
    models: set[str] = set()
    reasonings: set[str] = set()
    fast_modes: set[bool] = set()
    cli_versions: set[str] = set()
    input_tokens: int | None = None
    output_tokens: int | None = None
    for line in lines:
        if not line.strip():
            continue
        try:
            value: object = json.loads(line)
        except json.JSONDecodeError:
            raise ProviderOutputError(
                "invalid_jsonl",
                "The provider returned malformed structured output.",
                transmission=TransmissionDisposition.TRANSMITTED,
            ) from None
        if _contains_forbidden_policy_event(value):
            raise ProviderPolicyViolationError(
                "policy_violation",
                "The provider attempted a forbidden action.",
                transmission=TransmissionDisposition.TRANSMITTED,
            )
        if not isinstance(value, dict):
            continue
        if value.get("type") in {"error", "turn.failed"}:
            _raise_process_failure(
                json.dumps(value, separators=(",", ":")).encode("utf-8"),
                transmission=TransmissionDisposition.TRANSMITTED,
            )
        _collect_metadata(
            value,
            models=models,
            reasonings=reasonings,
            fast_modes=fast_modes,
            cli_versions=cli_versions,
        )
        usage = value.get("usage")
        if isinstance(usage, dict):
            input_tokens = _optional_nonnegative_int(usage.get("input_tokens"))
            output_tokens = _optional_nonnegative_int(usage.get("output_tokens"))
        item = value.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            text = item.get("text")
            if isinstance(text, str):
                try:
                    decoded: object = json.loads(text)
                except json.JSONDecodeError:
                    decoded = None
                if isinstance(decoded, dict):
                    candidates.append(decoded)
        response = value.get("response")
        if isinstance(response, dict):
            candidates.append(cast(dict[str, object], response))
        if (
            "type" not in value
            and "item" not in value
            and "response" not in value
            and not _METADATA_KEYS.intersection(value)
        ):
            candidates.append(cast(dict[str, object], value))
    if len(candidates) != 1:
        raise ProviderOutputError(
            "response_envelope_invalid",
            "The provider did not return exactly one structured JSON object.",
            transmission=TransmissionDisposition.TRANSMITTED,
        )
    return candidates[0], _ObservedMetadata(
        frozenset(models),
        frozenset(reasonings),
        frozenset(fast_modes),
        frozenset(cli_versions),
        input_tokens,
        output_tokens,
    )


def _collect_metadata(
    value: Mapping[str, object],
    *,
    models: set[str],
    reasonings: set[str],
    fast_modes: set[bool],
    cli_versions: set[str],
) -> None:
    model = value.get("model")
    if model is not None:
        if not isinstance(model, str) or not model.strip() or not model.isprintable():
            raise ProviderOutputError(
                "model_metadata_invalid",
                "The provider returned invalid model metadata.",
                transmission=TransmissionDisposition.TRANSMITTED,
            )
        models.add(model)
    reasoning = value.get("reasoning_effort", value.get("model_reasoning_effort"))
    if reasoning is not None:
        if not isinstance(reasoning, str) or reasoning not in _REASONING_EFFORTS:
            raise ProviderOutputError(
                "reasoning_metadata_invalid",
                "The provider returned invalid reasoning metadata.",
                transmission=TransmissionDisposition.TRANSMITTED,
            )
        reasonings.add(reasoning)
    fast_mode = value.get("fast_mode")
    if fast_mode is not None:
        if not isinstance(fast_mode, bool):
            raise ProviderOutputError(
                "fast_metadata_invalid",
                "The provider returned invalid Fast-mode metadata.",
                transmission=TransmissionDisposition.TRANSMITTED,
            )
        fast_modes.add(fast_mode)
    cli_version = value.get("cli_version")
    if cli_version is not None:
        if (
            not isinstance(cli_version, str)
            or not cli_version.strip()
            or not cli_version.isprintable()
        ):
            raise ProviderOutputError(
                "cli_metadata_invalid",
                "The provider returned invalid CLI metadata.",
                transmission=TransmissionDisposition.TRANSMITTED,
            )
        cli_versions.add(cli_version)


def _verify_runtime_metadata(
    observed: _ObservedMetadata,
    *,
    requested_model: str,
    requested_reasoning_effort: str,
    requested_fast_mode: bool,
    elapsed_ms: int,
) -> RuntimeMetadata:
    if len(observed.models) > 1 or (
        observed.models and observed.models != frozenset({requested_model})
    ):
        raise ProviderIdentityMismatchError(
            "model_mismatch",
            "The provider resolved a different model than requested.",
            transmission=TransmissionDisposition.TRANSMITTED,
        )
    if len(observed.reasonings) > 1 or (
        observed.reasonings and observed.reasonings != frozenset({requested_reasoning_effort})
    ):
        raise ProviderIdentityMismatchError(
            "reasoning_mismatch",
            "The provider resolved a different reasoning setting than requested.",
            transmission=TransmissionDisposition.TRANSMITTED,
        )
    if len(observed.fast_modes) > 1 or (
        observed.fast_modes and observed.fast_modes != frozenset({requested_fast_mode})
    ):
        raise ProviderIdentityMismatchError(
            "fast_mode_mismatch",
            "The provider resolved a different Fast setting than requested.",
            transmission=TransmissionDisposition.TRANSMITTED,
        )
    if len(observed.cli_versions) > 1:
        raise ProviderOutputError(
            "cli_metadata_conflict",
            "The provider returned conflicting CLI metadata.",
            transmission=TransmissionDisposition.TRANSMITTED,
        )
    return RuntimeMetadata(
        requested_model=requested_model,
        resolved_model=next(iter(observed.models), requested_model),
        requested_reasoning_effort=requested_reasoning_effort,
        resolved_reasoning_effort=next(iter(observed.reasonings), None),
        requested_fast_mode=requested_fast_mode,
        resolved_fast_mode=next(iter(observed.fast_modes), None),
        metadata_verified=bool(observed.models and observed.reasonings and observed.fast_modes),
        cli_version=next(iter(observed.cli_versions), None),
        input_tokens=observed.input_tokens,
        output_tokens=observed.output_tokens,
        elapsed_ms=elapsed_ms,
    )


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProviderOutputError(
            "usage_metadata_invalid",
            "The provider returned invalid usage metadata.",
            transmission=TransmissionDisposition.TRANSMITTED,
        )
    return value


def _contains_forbidden_policy_event(value: object) -> bool:
    if isinstance(value, dict):
        nested_item = value.get("item")
        if isinstance(nested_item, dict):
            item_type = nested_item.get("type")
            if not isinstance(item_type, str) or item_type not in _SAFE_CODEX_ITEM_TYPES:
                return True
        for key, item in value.items():
            normalized_key = str(key).casefold()
            if (
                normalized_key in _POLICY_TYPE_FIELDS
                and isinstance(item, str)
                and item.casefold() in _FORBIDDEN_MARKERS
            ):
                return True
            if (
                normalized_key not in _TEXT_PAYLOAD_FIELDS or not isinstance(item, str)
            ) and _contains_forbidden_policy_event(item):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_policy_event(item) for item in value)
    return False


def _as_bytes(value: object) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace")
    return b""


def _raise_process_failure(
    raw: bytes,
    *,
    transmission: TransmissionDisposition,
) -> None:
    category = raw.decode("utf-8", errors="ignore").casefold()
    if any(
        marker in category
        for marker in ("rate limit", "rate_limit", "too many requests", "429")
    ):
        raise ProviderRateLimitError(
            "rate_limited",
            "The provider is rate limited.",
            transient=True,
            transmission=transmission,
        )
    if any(
        marker in category
        for marker in (
            "not logged in",
            "sign in",
            "unauthorized",
            "authentication failed",
            "invalid authentication",
            "authentication required",
            "login required",
            "status 401",
            "http 401",
        )
    ):
        raise ProviderAuthenticationError(
            "authentication_failed",
            "The provider authentication was rejected.",
            transmission=transmission,
        )
    if "refus" in category:
        raise ProviderOutputError(
            "provider_refusal",
            "The provider refused the request.",
            transmission=transmission,
        )
    if any(marker in category for marker in ("timed out", "request timeout")):
        raise ProviderTimeoutError(
            "timeout",
            "The provider request timed out.",
            transient=True,
            transmission=transmission,
        )
    if any(
        marker in category
        for marker in (
            "connection reset",
            "connection refused",
            "connection aborted",
            "connection closed",
            "network is unreachable",
            "dns failure",
            "connect error",
            "connection error",
            "transport error",
        )
    ):
        raise ProviderProcessError(
            "transport_failure",
            "The provider transport failed.",
            transient=True,
            transmission=transmission,
        )
    raise ProviderProcessError(
        "provider_process_failed",
        "The provider process failed.",
        transmission=transmission,
    )


def _stop_process(process: Process) -> None:
    try:
        process.terminate()
    except Exception:
        return
    try:
        process.wait(timeout=_CANCEL_GRACE_SECONDS)
    except Exception:
        try:
            process.kill()
            process.wait(timeout=_KILL_GRACE_SECONDS)
        except Exception:
            return
