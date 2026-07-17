"""Reusable direct-process boundary for schema-constrained Codex CLI calls.

The runner is deliberately semantic-free: callers supply structured UTF-8 input and a JSON
schema, while this module owns process isolation, bounded transport, policy-event rejection,
cancellation, and sanitized failure classification.  It never invokes a shell.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from PySide6.QtCore import QByteArray, QProcess

_POLL_MS = 20
_START_POLL_ATTEMPTS = 35
_CANCEL_GRACE_MS = 500
_KILL_CLEANUP_MS = 100
_DISCOVERY_TIMEOUT_SECONDS = 0.5

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
_FORBIDDEN_MARKERS = {
    "command_execution",
    "shell_command",
    "function_call",
    "mcp_tool_call",
    "collab_tool_call",
    "dynamic_tool_call",
    "web_search",
    "file_change",
    "apply_patch",
}
_POLICY_TYPE_FIELDS = {"type", "kind", "name", "tool", "tool_name"}
_TEXT_PAYLOAD_FIELDS = {"text", "message", "content", "output", "summary"}
_SAFE_CODEX_ITEM_TYPES = {"agent_message", "reasoning", "todo_list", "error"}
_REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh"})


class Process(Protocol):
    def setWorkingDirectory(self, directory: str) -> None: ...
    def start(self, program: str, arguments: list[str]) -> None: ...
    def waitForStarted(self, msecs: int = 30000) -> bool: ...
    def write(self, data: bytes) -> int: ...
    def closeWriteChannel(self) -> None: ...
    def waitForFinished(self, msecs: int = 30000) -> bool: ...
    def readAllStandardOutput(self) -> object: ...
    def readAllStandardError(self) -> object: ...
    def exitCode(self) -> int: ...
    def state(self) -> QProcess.ProcessState: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...


ProcessFactory = Callable[[], Process]
ExecutableResolver = Callable[[str], tuple[str | None, str | None]]
CancelledCallback = Callable[[], bool]


@dataclass(frozen=True)
class SterileRunRequest:
    model: str
    schema_path: Path
    stdin: bytes
    timeout_seconds: float
    maximum_output_bytes: int
    model_reasoning_effort: str | None = None

    def __post_init__(self) -> None:
        _validate_model(self.model)
        if not self.schema_path.is_absolute() or not self.schema_path.is_file():
            raise ValueError("The provider output schema must be an existing absolute file.")
        if not self.stdin:
            raise ValueError("Structured provider input cannot be empty.")
        try:
            self.stdin.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("Structured provider input must be UTF-8.") from None
        if self.timeout_seconds <= 0:
            raise ValueError("Provider timeout must be positive.")
        if self.maximum_output_bytes <= 0:
            raise ValueError("Provider output limit must be positive.")
        if (
            self.model_reasoning_effort is not None
            and self.model_reasoning_effort not in _REASONING_EFFORTS
        ):
            raise ValueError("Unsupported provider reasoning effort.")


@dataclass(frozen=True)
class SterileRunResult:
    events: tuple[object, ...]
    cli_version: str | None


class SterileRunnerError(RuntimeError):
    """A sanitized transport failure safe to persist by code only."""

    def __init__(self, error_code: str, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.transient = transient


def _qt_process() -> Process:
    return cast(Process, QProcess())


def _as_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    return bytes(cast(QByteArray, value).data())


def _validate_model(model: str) -> None:
    if (
        not model
        or model != model.strip()
        or len(model) > 200
        or not model.isprintable()
    ):
        raise ValueError(
            "Model identifiers must be 1-200 printable characters without surrounding whitespace."
        )


def _path_executable_candidates(command: str) -> tuple[Path, ...]:
    """Resolve a bare Windows command from absolute PATH entries, never the CWD."""

    command_path = Path(command)
    if command_path.name != command or command_path.is_absolute():
        return ()
    path_extensions = tuple(
        extension.casefold()
        for extension in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";")
        if extension
    )
    names = (
        (command,)
        if command_path.suffix
        else tuple(f"{command}{extension}" for extension in path_extensions)
    )
    candidates: list[Path] = []
    seen: set[str] = set()
    for raw_directory in os.environ.get("PATH", "").split(os.pathsep):
        directory_text = raw_directory.strip().strip('"')
        if not directory_text:
            continue
        directory = Path(directory_text)
        if not directory.is_absolute():
            continue
        for name in names:
            candidate = directory / name
            if not candidate.is_file():
                continue
            normalized = str(candidate.resolve()).casefold()
            if normalized not in seen:
                seen.add(normalized)
                candidates.append(candidate.resolve())
    return tuple(candidates)


def _probe_version(executable: str, deadline: float) -> str | None:
    remaining_ms = max(0, round((deadline - time.monotonic()) * 1000))
    if remaining_ms <= 0:
        return None
    process = QProcess()
    process.start(executable, ["--version"])
    if not process.waitForStarted(remaining_ms):
        process.kill()
        process.waitForFinished(50)
        return None
    remaining_ms = max(0, round((deadline - time.monotonic()) * 1000))
    if remaining_ms <= 0 or not process.waitForFinished(remaining_ms):
        process.kill()
        process.waitForFinished(50)
        return None
    if process.exitCode() != 0:
        return None
    version = _as_bytes(process.readAllStandardOutput()).decode("utf-8", errors="ignore").strip()
    return version or None


def discover_native_codex(executable: str) -> tuple[str | None, str | None]:
    """Find a native executable without delegating a ``.cmd`` shim to a shell."""

    deadline = time.monotonic() + _DISCOVERY_TIMEOUT_SECONDS
    configured = Path(executable)
    candidates: list[Path] = []
    if configured.is_absolute() and configured.suffix.casefold() == ".exe" and configured.is_file():
        candidates.append(configured.resolve())
    for shim in _path_executable_candidates(executable):
        if shim.suffix.casefold() == ".exe":
            candidates.append(shim)
        npm_package = shim.parent / "node_modules" / "@openai" / "codex"
        candidates.extend(
            sorted(npm_package.glob("node_modules/@openai/codex-*/vendor/*/bin/codex.exe"))
        )
    seen: set[str] = set()
    for candidate in candidates:
        if time.monotonic() >= deadline:
            break
        normalized = str(candidate.resolve()).casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        version = _probe_version(str(candidate.resolve()), deadline)
        if version is not None:
            return str(candidate.resolve()), version
    return None, None


def contains_forbidden_policy_event(value: object) -> bool:
    """Inspect event metadata without treating quoted narrative text as an action."""

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
            ) and contains_forbidden_policy_event(item):
                return True
    elif isinstance(value, list):
        return any(contains_forbidden_policy_event(item) for item in value)
    return False


def build_sterile_codex_command(
    executable: str,
    *,
    model: str,
    schema_path: Path,
    model_reasoning_effort: str | None = None,
) -> tuple[str, list[str]]:
    """Build the direct, ephemeral, schema-constrained command for one cloud call."""

    _validate_model(model)
    if (
        model_reasoning_effort is not None
        and model_reasoning_effort not in _REASONING_EFFORTS
    ):
        raise ValueError("Unsupported provider reasoning effort.")
    arguments = [
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
        arguments.extend(["--disable", feature])
    if model_reasoning_effort is not None:
        arguments.extend(["-c", f'model_reasoning_effort="{model_reasoning_effort}"'])
    arguments.extend(
        [
            "-c",
            'web_search="disabled"',
            "-c",
            "analytics.enabled=false",
            "--json",
            "--output-schema",
            str(schema_path),
            "--model",
            model,
            "-",
        ]
    )
    return executable, arguments


class SterileCodexRunner:
    """Execute bounded structured calls with generation-based cancellation."""

    def __init__(
        self,
        *,
        executable: str = "codex",
        process_factory: ProcessFactory | None = None,
        executable_resolver: ExecutableResolver | None = None,
    ) -> None:
        self.executable = executable
        self._process_factory = process_factory or _qt_process
        self._using_default_factory = process_factory is None
        self._executable_resolver = executable_resolver or discover_native_codex
        self._resolved_executable: str | None = None
        self._cli_version: str | None = None
        self._cancel_generation = 0
        self._lock = threading.Lock()

    def status(self) -> tuple[str | None, str | None]:
        if self._resolved_executable is not None:
            return self._resolved_executable, self._cli_version
        if self._using_default_factory or self._executable_resolver is not discover_native_codex:
            resolved, version = self._executable_resolver(self.executable)
        else:
            resolved, version = self.executable, None
        if resolved is not None:
            self._resolved_executable = resolved
            self._cli_version = version
        return resolved, version

    def cancel(self) -> None:
        with self._lock:
            self._cancel_generation += 1

    def execute(
        self,
        request: SterileRunRequest,
        cancelled: CancelledCallback,
    ) -> SterileRunResult:
        resolved, cli_version = self.status()
        if resolved is None:
            raise SterileRunnerError(
                "provider_unavailable",
                "The Codex CLI provider is unavailable.",
            )
        with self._lock:
            cancellation_generation = self._cancel_generation

        def is_cancelled() -> bool:
            with self._lock:
                generation_changed = self._cancel_generation != cancellation_generation
            return cancelled() or generation_changed

        if is_cancelled():
            raise SterileRunnerError("cancelled", "The provider request was cancelled.")
        with tempfile.TemporaryDirectory(prefix="renpy-story-narrative-") as temp_path:
            process = self._process_factory()
            try:
                process.setWorkingDirectory(temp_path)
                program, arguments = build_sterile_codex_command(
                    resolved,
                    model=request.model,
                    schema_path=request.schema_path,
                    model_reasoning_effort=request.model_reasoning_effort,
                )
                process.start(program, arguments)
                self._wait_for_start(process, is_cancelled)
                if process.write(request.stdin) != len(request.stdin):
                    self._stop_process(process)
                    raise SterileRunnerError(
                        "transport_failure",
                        "The provider did not accept the complete structured request.",
                        transient=True,
                    )
                process.closeWriteChannel()
                return self._collect(
                    process,
                    timeout_seconds=request.timeout_seconds,
                    maximum_output_bytes=request.maximum_output_bytes,
                    cancelled=is_cancelled,
                    cli_version=cli_version,
                )
            finally:
                if not process.waitForFinished(0):
                    self._stop_process(process)

    @staticmethod
    def _wait_for_start(process: Process, cancelled: CancelledCallback) -> None:
        for _attempt in range(_START_POLL_ATTEMPTS):
            if cancelled():
                SterileCodexRunner._stop_process(process)
                raise SterileRunnerError("cancelled", "The provider request was cancelled.")
            if process.waitForStarted(_POLL_MS):
                return
            if process.state() == QProcess.ProcessState.NotRunning:
                raise SterileRunnerError(
                    "provider_unavailable",
                    "The Codex CLI provider could not start.",
                )
        SterileCodexRunner._stop_process(process)
        raise SterileRunnerError(
            "startup_timeout",
            "The provider startup timed out.",
            transient=True,
        )

    @staticmethod
    def _collect(
        process: Process,
        *,
        timeout_seconds: float,
        maximum_output_bytes: int,
        cancelled: CancelledCallback,
        cli_version: str | None,
    ) -> SterileRunResult:
        deadline = time.monotonic() + timeout_seconds
        buffer = b""
        output_bytes = 0
        events: list[object] = []
        while not process.waitForFinished(_POLL_MS):
            chunk = _as_bytes(process.readAllStandardOutput())
            output_bytes += len(chunk)
            if output_bytes > maximum_output_bytes:
                SterileCodexRunner._stop_process(process)
                raise SterileRunnerError(
                    "output_limit",
                    "The provider output exceeded its transport limit.",
                )
            buffer += chunk
            buffer = SterileCodexRunner._consume_lines(buffer, process, events)
            if cancelled():
                SterileCodexRunner._stop_process(process)
                raise SterileRunnerError("cancelled", "The provider request was cancelled.")
            if time.monotonic() >= deadline:
                SterileCodexRunner._stop_process(process)
                raise SterileRunnerError(
                    "timeout",
                    "The provider request timed out.",
                    transient=True,
                )
        chunk = _as_bytes(process.readAllStandardOutput())
        output_bytes += len(chunk)
        if output_bytes > maximum_output_bytes:
            raise SterileRunnerError(
                "output_limit",
                "The provider output exceeded its transport limit.",
            )
        buffer += chunk
        remainder = SterileCodexRunner._consume_lines(buffer + b"\n", process, events)
        if remainder.strip():
            raise SterileRunnerError("invalid_jsonl", "The provider emitted malformed JSONL.")
        if process.exitCode() != 0:
            SterileCodexRunner._raise_process_failure(_as_bytes(process.readAllStandardError()))
        return SterileRunResult(events=tuple(events), cli_version=cli_version)

    @staticmethod
    def _consume_lines(buffer: bytes, process: Process, events: list[object]) -> bytes:
        lines = buffer.split(b"\n")
        remainder = lines.pop()
        for line in lines:
            if not line.strip():
                continue
            try:
                event: object = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                SterileCodexRunner._stop_process(process)
                raise SterileRunnerError(
                    "invalid_jsonl",
                    "The provider emitted malformed JSONL.",
                ) from None
            if contains_forbidden_policy_event(event):
                SterileCodexRunner._stop_process(process)
                raise SterileRunnerError(
                    "policy_violation",
                    "The provider attempted a forbidden action.",
                )
            if isinstance(event, dict) and event.get("type") in {"error", "turn.failed"}:
                SterileCodexRunner._stop_process(process)
                SterileCodexRunner._raise_process_failure(
                    json.dumps(event, separators=(",", ":")).encode("utf-8")
                )
            events.append(event)
        return remainder

    @staticmethod
    def _stop_process(process: Process) -> None:
        process.terminate()
        if not process.waitForFinished(_CANCEL_GRACE_MS):
            process.kill()
            process.waitForFinished(_KILL_CLEANUP_MS)

    @staticmethod
    def _raise_process_failure(raw: bytes) -> None:
        category = raw.decode("utf-8", errors="ignore").casefold()
        if any(
            marker in category
            for marker in ("rate limit", "rate_limit", "too many requests", "429")
        ):
            raise SterileRunnerError(
                "rate_limited",
                "The provider is rate limited.",
                transient=True,
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
                "status code: 401",
            )
        ):
            raise SterileRunnerError(
                "authentication_failed",
                "The provider authentication was rejected.",
            )
        runtime_setting_rejected = (
            "model_reasoning_effort" in category
            and any(
                marker in category
                for marker in ("invalid value", "unknown variant", "unsupported")
            )
        ) or (
            "fast_mode" in category
            and any(
                marker in category
                for marker in ("unknown feature", "unrecognized feature", "feature not found")
            )
        )
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
            raise SterileRunnerError(
                "output_schema_rejected",
                "The provider rejected the output schema.",
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
                "invalid value for 'model_reasoning_effort'",
                'invalid value for "model_reasoning_effort"',
            )
        ):
            raise SterileRunnerError(
                "runtime_configuration_rejected",
                "The provider runtime configuration was rejected.",
            )
        if "refus" in category:
            raise SterileRunnerError("provider_refusal", "The provider refused the request.")
        if "timed out" in category or "request timeout" in category:
            raise SterileRunnerError(
                "timeout",
                "The provider request timed out.",
                transient=True,
            )
        if any(
            marker in category
            for marker in (
                "connection reset",
                "connection refused",
                "connection aborted",
                "connection closed",
                "network is unreachable",
                "temporary failure in name resolution",
                "dns failure",
                "dns error",
                "connect error",
                "connection error",
                "error sending request",
                "tls handshake",
                "certificate verify",
                "transport error",
            )
        ):
            raise SterileRunnerError(
                "transport_failure",
                "The provider transport failed.",
                transient=True,
            )
        if any(
            marker in category
            for marker in (
                "internal server error",
                "service unavailable",
                "bad gateway",
                "gateway timeout",
                "server overloaded",
                "status 500",
                "status 502",
                "status 503",
                "status 504",
                "http 500",
                "http 502",
                "http 503",
                "http 504",
            )
        ):
            raise SterileRunnerError(
                "server_transient",
                "The provider server failed temporarily.",
                transient=True,
            )
        raise SterileRunnerError(
            "provider_process_failed",
            "The provider process failed.",
        )
