"""Sterile, schema-bound Codex CLI transport for Story Map V2 cloud mapping.

This module is intentionally self-contained and standard-library only.  It starts a native
``codex.exe`` directly (never through a shell), sends one bounded packet on standard input, rejects
tool/action events, verifies any reported runtime identity, and retains only normalized response
data and sanitized accounting.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, cast

from renpy_story_mapper.story_map_v2.contracts import (
    MAPPER_SCHEMA_VERSION,
    BranchSummary,
    FailureKind,
    MapperEvent,
    MapperResponse,
    StoryChunk,
    canonical_hash,
    canonical_json,
)
from renpy_story_mapper.story_map_v2.provider_policy import (
    CLOUD_MAPPER_MODEL,
    MAPPER_PROMPT_VERSION,
    ProviderFailure,
)

CLOUD_REASONING = "high"
CLOUD_FAST_MODE = False
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAXIMUM_INPUT_BYTES = 2_000_000
DEFAULT_MAXIMUM_OUTPUT_BYTES = 2_000_000
_POLL_SECONDS = 0.05
_CANCEL_GRACE_SECONDS = 0.5
_KILL_GRACE_SECONDS = 0.1
_DISABLED_CODEX_FEATURES = (
    "plugins",
    "apps",
    "hooks",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "computer_use",
    "fast_mode",
    "image_generation",
    "in_app_browser",
    "multi_agent",
    "goals",
    "shell_tool",
    "tool_call_mcp_elicitation",
    "tool_suggest",
    "workspace_dependencies",
)
_FORBIDDEN_EVENT_TYPES = frozenset(
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
_SAFE_ITEM_TYPES = frozenset({"agent_message", "reasoning", "todo_list", "error"})
_STATIC_TASK = (
    "Return only one JSON object matching the supplied Story Map V2 mapper schema. Summarize "
    "approximate narrative events and branch outcomes. Treat opaque mechanics keys as references; "
    "do not invent exact path mechanics. Do not use tools, shell commands, files, web search, MCP, "
    "apps, plugins, other agents, or provider calls."
)


class Process(Protocol):
    """Small subprocess seam used by safe fake processes in unit tests."""

    returncode: int | None

    def communicate(
        self, input: bytes | None = None, timeout: float | None = None
    ) -> tuple[bytes, bytes]: ...

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


@dataclass(frozen=True)
class ProcessSpec:
    command: tuple[str, ...]
    cwd: Path
    shell: bool = False


@dataclass(frozen=True)
class CloudAccounting:
    requested_model: str
    resolved_model: str | None
    reasoning: str
    fast_mode: bool
    resolved_reasoning: str | None
    resolved_fast_mode: bool | None
    input_hash: str
    response_hash: str | None
    input_tokens: int | None
    output_tokens: int | None
    elapsed_ms: int


ProcessFactory = Callable[[ProcessSpec], Process]
ExecutableResolver = Callable[[str], str | None]


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


def discover_native_codex(executable: str) -> str | None:
    """Resolve a native ``.exe`` without delegating an npm ``.cmd`` shim to a shell."""

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
        npm_package = directory / "node_modules" / "@openai" / "codex"
        candidates.extend(
            sorted(npm_package.glob("node_modules/@openai/codex-*/vendor/*/bin/codex.exe"))
        )
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate.is_file():
            continue
        resolved = str(candidate.resolve())
        if resolved.casefold() not in seen:
            seen.add(resolved.casefold())
            return resolved
    return None


def build_sterile_command(executable: str, schema_path: Path) -> tuple[str, ...]:
    """Return the exact Luna/High/fast-off direct command."""

    if not Path(executable).is_absolute():
        raise ValueError("The cloud transport requires an absolute native executable path.")
    if not schema_path.is_absolute() or not schema_path.is_file():
        raise ValueError("The mapper schema must be an existing absolute file.")
    arguments = [
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
            f'model_reasoning_effort="{CLOUD_REASONING}"',
            "-c",
            'web_search="disabled"',
            "-c",
            "analytics.enabled=false",
            "--json",
            "--output-schema",
            str(schema_path),
            "--model",
            CLOUD_MAPPER_MODEL,
            "-",
        )
    )
    return tuple(arguments)


def serialize_chunk_packet(chunk: StoryChunk) -> bytes:
    """Serialize the exact stdin packet without files or unrelated project material."""

    return canonical_json(
        {
            "prompt_version": MAPPER_PROMPT_VERSION,
            "mapper_schema": MAPPER_SCHEMA_VERSION,
            "task": _STATIC_TASK,
            "chunk_identity": chunk.identity,
            "packet_hash": chunk.packet_hash,
            "raw_text": chunk.raw_text,
            "mechanics": json.loads(chunk.mechanics),
        }
    )


class CodexCliCloudTransport:
    """One-process-per-packet sterile cloud mapper with bounded cancellation."""

    def __init__(
        self,
        *,
        executable: str = "codex",
        schema_path: Path | None = None,
        process_factory: ProcessFactory = _default_process_factory,
        executable_resolver: ExecutableResolver = discover_native_codex,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        maximum_input_bytes: int = DEFAULT_MAXIMUM_INPUT_BYTES,
        maximum_output_bytes: int = DEFAULT_MAXIMUM_OUTPUT_BYTES,
    ) -> None:
        selected_schema = schema_path or (
            Path(__file__).resolve().parent / "schemas" / "story_map_mapper_v2.schema.json"
        )
        selected_schema = selected_schema.resolve()
        if not selected_schema.is_file():
            raise ValueError("The Story Map V2 mapper schema is unavailable.")
        if timeout_seconds <= 0:
            raise ValueError("The cloud mapper timeout must be positive.")
        if maximum_input_bytes <= 0 or maximum_output_bytes <= 0:
            raise ValueError("Cloud mapper byte limits must be positive.")
        self._executable = executable
        self._schema_path = selected_schema
        self._process_factory = process_factory
        self._executable_resolver = executable_resolver
        self._timeout_seconds = timeout_seconds
        self._maximum_input_bytes = maximum_input_bytes
        self._maximum_output_bytes = maximum_output_bytes
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._active: Process | None = None
        self._resolved_executable: str | None = None
        self._last_accounting: CloudAccounting | None = None
        self._observed_model: str | None = None
        self._observed_reasoning: str | None = None
        self._observed_fast_mode: bool | None = None
        self._input_tokens: int | None = None
        self._output_tokens: int | None = None

    @property
    def resolved_model(self) -> str:
        """The locked selection; emitted runtime metadata is checked against this value."""

        return CLOUD_MAPPER_MODEL

    @property
    def input_tokens(self) -> int | None:
        return self._input_tokens

    @property
    def output_tokens(self) -> int | None:
        return self._output_tokens

    @property
    def last_accounting(self) -> CloudAccounting | None:
        return self._last_accounting

    @property
    def observed_model(self) -> str | None:
        """Return only model identity actually emitted by the current provider call."""

        return self._observed_model

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            active = self._active
        if active is not None:
            _stop_process(active)

    def map_chunk(self, chunk: StoryChunk) -> MapperResponse:
        self._last_accounting = None
        self._observed_model = None
        self._observed_reasoning = None
        self._observed_fast_mode = None
        self._input_tokens = None
        self._output_tokens = None
        if self._cancelled.is_set():
            raise ProviderFailure(FailureKind.CANCELLED, "Cloud mapping was cancelled.")
        packet = serialize_chunk_packet(chunk)
        if len(packet) > self._maximum_input_bytes:
            raise ProviderFailure(
                FailureKind.TRANSPORT, "The cloud mapper packet exceeds its bounded input limit."
            )
        executable = self._resolved_executable or self._executable_resolver(self._executable)
        if executable is None:
            raise ProviderFailure(FailureKind.TRANSPORT, "The native Codex CLI is unavailable.")
        self._resolved_executable = executable
        command = build_sterile_command(executable, self._schema_path)
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="renpy-story-map-v2-cloud-") as temp_directory:
            spec = ProcessSpec(command=command, cwd=Path(temp_directory).resolve())
            try:
                process = self._process_factory(spec)
            except Exception:
                raise ProviderFailure(
                    FailureKind.TRANSPORT, "The native Codex CLI could not start."
                ) from None
            with self._lock:
                self._active = process
            try:
                stdout, stderr = self._communicate(process, packet)
            finally:
                with self._lock:
                    if self._active is process:
                        self._active = None
                if process.poll() is None:
                    _stop_process(process)
        try:
            response, metadata = _parse_jsonl(stdout)
        except ProviderFailure as exc:
            failure = exc
            if process.returncode != 0 and not (
                exc.kind is FailureKind.IDENTITY or _has_structured_failure_or_action(stdout)
            ):
                failure = _classify_process_failure(stderr)
            self._record_failure(failure, packet=packet, started=started)
            if failure is exc:
                raise
            raise failure from exc
        if process.returncode != 0:
            failure = _classify_process_failure(stderr)
            self._record_failure(failure, packet=packet, started=started)
            raise failure
        if len(metadata.models) == 1:
            self._observed_model = next(iter(metadata.models))
        if len(metadata.reasonings) == 1:
            self._observed_reasoning = next(iter(metadata.reasonings))
        if len(metadata.fast_modes) == 1:
            self._observed_fast_mode = next(iter(metadata.fast_modes))
        self._input_tokens = metadata.input_tokens
        self._output_tokens = metadata.output_tokens
        try:
            _verify_runtime_identity(metadata)
        except ProviderFailure:
            self._last_accounting = self._accounting(
                packet,
                response_hash=None,
                started=started,
            )
            raise
        response_hash = canonical_hash(asdict(response))
        self._last_accounting = self._accounting(
            packet,
            response_hash=response_hash,
            started=started,
        )
        return response

    def _record_failure(self, failure: ProviderFailure, *, packet: bytes, started: float) -> None:
        self._observed_model = failure.resolved_model
        self._observed_reasoning = failure.resolved_reasoning
        self._observed_fast_mode = failure.resolved_fast_mode
        self._input_tokens = failure.input_tokens
        self._output_tokens = failure.output_tokens
        self._last_accounting = self._accounting(
            packet,
            response_hash=None,
            started=started,
        )

    def _accounting(
        self,
        packet: bytes,
        *,
        response_hash: str | None,
        started: float,
    ) -> CloudAccounting:
        return CloudAccounting(
            requested_model=CLOUD_MAPPER_MODEL,
            resolved_model=self._observed_model,
            reasoning=CLOUD_REASONING,
            fast_mode=CLOUD_FAST_MODE,
            resolved_reasoning=self._observed_reasoning,
            resolved_fast_mode=self._observed_fast_mode,
            input_hash=hashlib.sha256(packet).hexdigest(),
            response_hash=response_hash,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            elapsed_ms=round((time.monotonic() - started) * 1000),
        )

    def _communicate(self, process: Process, packet: bytes) -> tuple[bytes, bytes]:
        deadline = time.monotonic() + self._timeout_seconds
        pending_input: bytes | None = packet
        while True:
            if self._cancelled.is_set():
                _stop_process(process)
                raise ProviderFailure(FailureKind.CANCELLED, "Cloud mapping was cancelled.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _stop_process(process)
                raise ProviderFailure(FailureKind.TIMEOUT, "The cloud mapper timed out.")
            try:
                stdout, stderr = process.communicate(
                    input=pending_input,
                    timeout=min(_POLL_SECONDS, remaining),
                )
            except subprocess.TimeoutExpired as exc:
                pending_input = None
                partial_stdout = _optional_bytes(exc.output)
                partial_stderr = _optional_bytes(exc.stderr)
                if len(partial_stdout) + len(partial_stderr) > self._maximum_output_bytes:
                    _stop_process(process)
                    raise ProviderFailure(
                        FailureKind.INVALID_RESPONSE,
                        "The cloud mapper output exceeded its bounded limit.",
                    ) from None
                continue
            except OSError:
                _stop_process(process)
                raise ProviderFailure(
                    FailureKind.TRANSPORT, "The cloud mapper transport failed."
                ) from None
            if self._cancelled.is_set():
                _stop_process(process)
                raise ProviderFailure(FailureKind.CANCELLED, "Cloud mapping was cancelled.")
            if len(stdout) + len(stderr) > self._maximum_output_bytes:
                raise ProviderFailure(
                    FailureKind.INVALID_RESPONSE,
                    "The cloud mapper output exceeded its bounded limit.",
                )
            return stdout, stderr


# Compact alias for callers that do not need to name the CLI implementation detail.
CloudTransport = CodexCliCloudTransport


@dataclass(frozen=True)
class _RuntimeMetadata:
    models: frozenset[str]
    reasonings: frozenset[str]
    fast_modes: frozenset[bool]
    input_tokens: int | None
    output_tokens: int | None


def _optional_bytes(value: bytes | str | None) -> bytes:
    if value is None:
        return b""
    return value if isinstance(value, bytes) else value.encode("utf-8", errors="replace")


def _parse_jsonl(raw: bytes) -> tuple[MapperResponse, _RuntimeMetadata]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise ProviderFailure(
            FailureKind.INVALID_RESPONSE, "The cloud mapper emitted non-UTF-8 output."
        ) from None
    final_payload: object | None = None
    models: set[str] = set()
    reasonings: set[str] = set()
    fast_modes: set[bool] = set()
    input_tokens: int | None = None
    output_tokens: int | None = None
    for line in lines:
        if not line.strip():
            continue
        try:
            event: object = json.loads(line)
        except json.JSONDecodeError:
            raise ProviderFailure(
                FailureKind.INVALID_RESPONSE, "The cloud mapper emitted malformed JSONL."
            ) from None
        if _contains_forbidden_action(event):
            raise ProviderFailure(
                FailureKind.INVALID_RESPONSE, "The cloud mapper attempted a forbidden action."
            )
        model = event.get("model") if isinstance(event, dict) else None
        if model is not None:
            if not isinstance(model, str) or not model:
                raise ProviderFailure(FailureKind.IDENTITY, "Invalid cloud model metadata.")
            models.add(model)
        if isinstance(event, dict):
            reasoning = event.get("reasoning_effort", event.get("model_reasoning_effort"))
            fast_mode = event.get("fast_mode")
            usage = event.get("usage")
            if reasoning is not None:
                if not isinstance(reasoning, str):
                    raise ProviderFailure(FailureKind.IDENTITY, "Invalid reasoning metadata.")
                reasonings.add(reasoning.casefold())
            if fast_mode is not None:
                if not isinstance(fast_mode, bool):
                    raise ProviderFailure(FailureKind.IDENTITY, "Invalid fast-mode metadata.")
                fast_modes.add(fast_mode)
            if usage is not None:
                reported_input, reported_output = _parse_usage(usage)
                input_tokens = reported_input if reported_input is not None else input_tokens
                output_tokens = reported_output if reported_output is not None else output_tokens
            if event.get("type") in {"error", "turn.failed"}:
                metadata = _RuntimeMetadata(
                    models=frozenset(models),
                    reasonings=frozenset(reasonings),
                    fast_modes=frozenset(fast_modes),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                try:
                    _verify_runtime_identity(metadata)
                except ProviderFailure as exc:
                    failure = exc
                else:
                    failure = _classify_structured_failure(event)
                failure.input_tokens = input_tokens
                failure.output_tokens = output_tokens
                failure.resolved_model = next(iter(models)) if len(models) == 1 else None
                failure.resolved_reasoning = (
                    next(iter(reasonings)) if len(reasonings) == 1 else None
                )
                failure.resolved_fast_mode = (
                    next(iter(fast_modes)) if len(fast_modes) == 1 else None
                )
                raise failure
        candidate = _extract_payload(event)
        if candidate is not None:
            final_payload = candidate
    if final_payload is None:
        raise ProviderFailure(
            FailureKind.INVALID_RESPONSE, "The cloud mapper returned no structured response."
        )
    return (
        _parse_mapper_response(final_payload),
        _RuntimeMetadata(
            models=frozenset(models),
            reasonings=frozenset(reasonings),
            fast_modes=frozenset(fast_modes),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
    )


def _has_structured_failure_or_action(raw: bytes) -> bool:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return False
    for line in lines:
        if not line.strip():
            continue
        try:
            event: object = json.loads(line)
        except json.JSONDecodeError:
            continue
        if _contains_forbidden_action(event):
            return True
        if isinstance(event, dict) and event.get("type") in {"error", "turn.failed"}:
            return True
    return False


def _extract_payload(event: object) -> object | None:
    if not isinstance(event, dict):
        return None
    if _is_mapper_payload(event):
        return event
    item = event.get("item")
    if isinstance(item, dict) and item.get("type") == "agent_message":
        text = item.get("text")
        if isinstance(text, str):
            try:
                return cast(object, json.loads(text))
            except json.JSONDecodeError:
                return None
    response = event.get("response")
    return response if isinstance(response, dict) else None


def _parse_mapper_response(value: object) -> MapperResponse:
    if not isinstance(value, dict) or not _is_mapper_payload(value):
        raise ProviderFailure(FailureKind.INVALID_RESPONSE, "Invalid mapper response fields.")
    scope_title = _optional_text(value.get("scope_title"), "scope title")
    scope_overview = _optional_text(value.get("scope_overview"), "scope overview")
    raw_events = value["events"]
    raw_branches = value["branch_summaries"]
    if not isinstance(raw_events, list) or not isinstance(raw_branches, list):
        raise ProviderFailure(FailureKind.INVALID_RESPONSE, "Invalid mapper response arrays.")
    events = tuple(_parse_event(item) for item in raw_events)
    branches = tuple(_parse_branch(item) for item in raw_branches)
    return MapperResponse(scope_title, scope_overview, events, branches)


def _is_mapper_payload(value: dict[object, object]) -> bool:
    keys = set(value)
    return (
        {"events", "branch_summaries"}
        <= keys
        <= {
            "scope_title",
            "scope_overview",
            "events",
            "branch_summaries",
        }
    )


def _parse_event(value: object) -> MapperEvent:
    expected = {
        "title",
        "summary",
        "relative_path",
        "start_line",
        "end_line",
        "characters",
        "warning",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ProviderFailure(FailureKind.INVALID_RESPONSE, "Invalid mapper event fields.")
    start_line = _positive_int(value["start_line"], "event start line")
    end_line = _positive_int(value["end_line"], "event end line")
    if end_line < start_line:
        raise ProviderFailure(FailureKind.INVALID_RESPONSE, "Invalid mapper event line range.")
    characters = value["characters"]
    if not isinstance(characters, list):
        raise ProviderFailure(FailureKind.INVALID_RESPONSE, "Invalid mapper event characters.")
    return MapperEvent(
        title=_required_text(value["title"], "event title"),
        summary=_required_text(value["summary"], "event summary"),
        relative_path=_required_text(value["relative_path"], "event path"),
        start_line=start_line,
        end_line=end_line,
        characters=tuple(_required_text(item, "character") for item in characters),
        warning=_optional_text(value["warning"], "event warning"),
    )


def _parse_branch(value: object) -> BranchSummary:
    if not isinstance(value, dict) or set(value) != {
        "choice_key",
        "arm_order",
        "outcome_summary",
    }:
        raise ProviderFailure(FailureKind.INVALID_RESPONSE, "Invalid branch summary fields.")
    return BranchSummary(
        choice_key=_required_text(value["choice_key"], "branch choice key"),
        arm_order=_positive_int(value["arm_order"], "branch arm order"),
        outcome_summary=_required_text(value["outcome_summary"], "branch outcome"),
    )


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProviderFailure(FailureKind.INVALID_RESPONSE, f"Invalid {label}.")
    return value


def _optional_text(value: object, label: str) -> str | None:
    return None if value is None else _required_text(value, label)


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ProviderFailure(FailureKind.INVALID_RESPONSE, f"Invalid {label}.")
    return value


def _parse_usage(value: object) -> tuple[int | None, int | None]:
    if not isinstance(value, dict):
        raise ProviderFailure(FailureKind.INVALID_RESPONSE, "Invalid cloud usage metadata.")
    parsed: list[int | None] = []
    for name in ("input_tokens", "output_tokens"):
        item = value.get(name)
        if item is not None and (not isinstance(item, int) or isinstance(item, bool) or item < 0):
            raise ProviderFailure(FailureKind.INVALID_RESPONSE, "Invalid cloud usage metadata.")
        parsed.append(item)
    return parsed[0], parsed[1]


def _verify_runtime_identity(metadata: _RuntimeMetadata) -> None:
    if metadata.models and metadata.models != frozenset({CLOUD_MAPPER_MODEL}):
        raise ProviderFailure(FailureKind.IDENTITY, "The resolved cloud model did not match.")
    if metadata.reasonings and metadata.reasonings != frozenset({CLOUD_REASONING}):
        raise ProviderFailure(FailureKind.IDENTITY, "The resolved reasoning level did not match.")
    if metadata.fast_modes and metadata.fast_modes != frozenset({CLOUD_FAST_MODE}):
        raise ProviderFailure(FailureKind.IDENTITY, "The resolved fast-mode setting did not match.")


def _contains_forbidden_action(value: object) -> bool:
    if isinstance(value, dict):
        nested_item = value.get("item")
        if isinstance(nested_item, dict):
            item_type = nested_item.get("type")
            if not isinstance(item_type, str) or item_type not in _SAFE_ITEM_TYPES:
                return True
        for key, item in value.items():
            normalized_key = str(key).casefold()
            if (
                normalized_key in {"type", "kind", "name", "tool", "tool_name"}
                and isinstance(item, str)
                and item.casefold() in _FORBIDDEN_EVENT_TYPES
            ):
                return True
            if normalized_key not in {
                "text",
                "message",
                "content",
                "output",
                "summary",
            } and _contains_forbidden_action(item):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_action(item) for item in value)
    return False


def _classify_structured_failure(value: dict[object, object]) -> ProviderFailure:
    code = value.get("code")
    error = value.get("error")
    if isinstance(error, dict) and code is None:
        code = error.get("code")
    code_text = code.casefold() if isinstance(code, str) else ""
    if code_text in {
        "content_filter",
        "content_policy_violation",
        "safety_refusal",
        "safety_policy_violation",
    }:
        return ProviderFailure(FailureKind.CONTENT_REFUSAL, "The cloud mapper declined content.")
    return _classify_failure_text(_sanitization_category(value))


def _classify_process_failure(raw: bytes) -> ProviderFailure:
    category = raw.decode("utf-8", errors="ignore").casefold()
    return _classify_failure_text(category)


def _classify_failure_text(category: str) -> ProviderFailure:
    content_policy = any(
        marker in category
        for marker in (
            "content_filter",
            "content policy violation",
            "content_policy_violation",
            "safety refusal",
            "safety_policy_violation",
        )
    )
    if content_policy:
        return ProviderFailure(FailureKind.CONTENT_REFUSAL, "The cloud mapper declined content.")
    if any(marker in category for marker in ("rate limit", "rate_limit", "429")):
        return ProviderFailure(FailureKind.RATE_LIMIT, "The cloud mapper is rate limited.")
    if any(
        marker in category
        for marker in ("unauthorized", "authentication", "not logged in", "login required", "401")
    ):
        return ProviderFailure(FailureKind.AUTHENTICATION, "Cloud authentication failed.")
    if any(
        marker in category
        for marker in (
            "output schema is invalid",
            "output schema rejected",
            "invalid output schema",
            "unsupported output schema",
            "schema for response_format",
            "invalid_json_schema",
            "json schema is invalid",
            "json schema rejected",
        )
    ):
        return ProviderFailure(
            FailureKind.INVALID_RESPONSE, "The cloud mapper output schema was rejected."
        )
    runtime_setting_rejected = (
        "model_reasoning_effort" in category
        and any(
            marker in category for marker in ("invalid value", "unknown variant", "unsupported")
        )
    ) or (
        "fast_mode" in category
        and any(
            marker in category
            for marker in ("unknown feature", "unrecognized feature", "feature not found")
        )
    )
    if runtime_setting_rejected or any(
        marker in category
        for marker in (
            "configuration error",
            "configuration is invalid",
            "invalid configuration",
            "unknown config key",
            "unknown configuration key",
            "unsupported config",
            "failed to parse config",
        )
    ):
        return ProviderFailure(
            FailureKind.IDENTITY, "The cloud mapper runtime configuration was rejected."
        )
    if any(marker in category for marker in ("timed out", "timeout")):
        return ProviderFailure(FailureKind.TIMEOUT, "The cloud mapper timed out.")
    if any(
        marker in category
        for marker in (
            "model_reasoning_effort",
            "fast_mode",
            "model mismatch",
            "unknown model",
            "unsupported model",
        )
    ):
        return ProviderFailure(FailureKind.IDENTITY, "Cloud identity or settings were rejected.")
    return ProviderFailure(FailureKind.TRANSPORT, "The cloud mapper process failed.")


def _sanitization_category(value: object) -> str:
    """Extract only error classification fields; never retain or return the raw event."""

    if not isinstance(value, dict):
        return ""
    selected: list[str] = []
    for key in ("type", "code", "kind", "status", "message"):
        item = value.get(key)
        if isinstance(item, str):
            selected.append(item.casefold())
    error = value.get("error")
    if isinstance(error, dict):
        for key in ("type", "code", "kind", "status", "message"):
            item = error.get(key)
            if isinstance(item, str):
                selected.append(item.casefold())
    return " ".join(selected)


def _stop_process(process: Process) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=_CANCEL_GRACE_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=_KILL_GRACE_SECONDS)
        except (OSError, subprocess.TimeoutExpired):
            pass
