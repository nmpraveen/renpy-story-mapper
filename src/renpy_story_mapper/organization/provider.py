"""Isolated Codex CLI provider using direct QProcess execution."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from collections.abc import Callable
from http.client import HTTPMessage
from importlib.resources import as_file, files
from pathlib import Path
from queue import Empty, Queue
from typing import IO, Protocol, cast
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from PySide6.QtCore import QByteArray, QProcess, QProcessEnvironment

from renpy_story_mapper.organization.contracts import (
    M05_CLOUD_MODEL,
    MAX_PROMPT_CHARS,
    CancelledCallback,
    CodexMode,
    OrganizationChunkResult,
    OrganizationRequest,
    ProgressCallback,
    ProviderAttemptUsage,
    ProviderExecutionMetadata,
    ProviderState,
    ProviderStatus,
    serialize_organization_prompt,
)
from renpy_story_mapper.organization.errors import (
    ConsentRequiredError,
    InvalidProviderOutputError,
    OrganizationCancelledError,
    PolicyViolationError,
    ProviderRateLimitError,
    ProviderRefusalError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from renpy_story_mapper.organization.validation import validate_result

_POLL_MS = 20
_CANCEL_GRACE_MS = 500
_KILL_CLEANUP_MS = 100
_MODEL_DISCOVERY_TIMEOUT_SECONDS = 0.5
_EXECUTABLE_DISCOVERY_TIMEOUT_SECONDS = 0.5
_MAX_MODEL_DISCOVERY_BYTES = 64 * 1024
_START_POLL_ATTEMPTS = 35
_DISCOVERY_SOCKET_TIMEOUT_SECONDS = 0.1
_DISCOVERY_DEADLINE_MARGIN_SECONDS = 0.01
_LMSTUDIO_BASE_URL = "http://127.0.0.1:1234"
_LMSTUDIO_MODELS_URL = f"{_LMSTUDIO_BASE_URL}/api/v1/models"
_LOOPBACK_NO_PROXY = "127.0.0.1,localhost,::1"
_PROXY_VARIABLES = {"ALL_PROXY", "FTP_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"}
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


class Process(Protocol):
    def setWorkingDirectory(self, directory: str) -> None: ...
    def setProcessEnvironment(self, environment: QProcessEnvironment) -> None: ...
    def start(self, program: str, arguments: list[str]) -> None: ...
    def waitForStarted(self, msecs: int = 30000) -> bool: ...
    def write(self, data: bytes) -> int: ...
    def closeWriteChannel(self) -> None: ...
    def waitForReadyRead(self, msecs: int = 30000) -> bool: ...
    def waitForFinished(self, msecs: int = 30000) -> bool: ...
    def readAllStandardOutput(self) -> object: ...
    def readAllStandardError(self) -> object: ...
    def exitCode(self) -> int: ...
    def state(self) -> QProcess.ProcessState: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...


ProcessFactory = Callable[[], Process]
ExecutableResolver = Callable[[str], str | None]
ModelDiscovery = Callable[[str, float], object]
EnvironmentFactory = Callable[[], QProcessEnvironment]


def _validated_model_identifier(model_identifier: str | None) -> str | None:
    if model_identifier is None or model_identifier == "":
        return None
    if (
        model_identifier != model_identifier.strip()
        or len(model_identifier) > 200
        or not model_identifier.isprintable()
    ):
        raise ValueError(
            "Model identifiers must be 1-200 printable characters without surrounding whitespace."
        )
    return model_identifier


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> None:
        return None


def _discover_models(url: str, timeout_seconds: float) -> object:
    if url != _LMSTUDIO_MODELS_URL:
        raise ValueError("LM Studio model discovery URL is not the locked loopback endpoint.")
    if timeout_seconds <= 0:
        raise TimeoutError("LM Studio model discovery timed out.")
    deadline = time.monotonic() + timeout_seconds

    result: Queue[tuple[bool, object]] = Queue(maxsize=1)
    stop_requested = threading.Event()

    def fetch() -> None:
        try:
            opener = build_opener(ProxyHandler({}), _NoRedirect())
            request = Request(url, headers={"Accept": "application/json"}, method="GET")
            with opener.open(
                request,
                timeout=min(timeout_seconds, _DISCOVERY_SOCKET_TIMEOUT_SECONDS),
            ) as response:
                body = bytearray()
                read_one = getattr(response, "read1", None)
                reader = read_one if callable(read_one) else response.read
                while not stop_requested.is_set():
                    remaining = _MAX_MODEL_DISCOVERY_BYTES + 1 - len(body)
                    if remaining <= 0:
                        raise ValueError(
                            "LM Studio model discovery response exceeded the size limit."
                        )
                    chunk = reader(min(4_096, remaining))
                    if not isinstance(chunk, bytes):
                        raise ValueError(
                            "LM Studio model discovery returned an invalid response body."
                        )
                    if not chunk:
                        break
                    body.extend(chunk)
                    if len(body) > _MAX_MODEL_DISCOVERY_BYTES:
                        raise ValueError(
                            "LM Studio model discovery response exceeded the size limit."
                        )
            if stop_requested.is_set():
                return
            result.put((True, cast(object, json.loads(body))))
        except Exception as exc:
            if not stop_requested.is_set():
                result.put((False, exc))

    worker = threading.Thread(
        target=fetch,
        name="lmstudio-model-preflight",
        daemon=True,
    )
    worker.start()
    wait_seconds = max(
        0.0,
        deadline - time.monotonic() - _DISCOVERY_DEADLINE_MARGIN_SECONDS,
    )
    try:
        succeeded, value = result.get(timeout=wait_seconds)
    except Empty:
        stop_requested.set()
        raise TimeoutError("LM Studio model discovery exceeded its total deadline.") from None
    if not succeeded:
        raise cast(BaseException, value)
    return value


def _qt_process() -> Process:
    return cast(Process, QProcess())


def _as_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    return bytes(cast(QByteArray, value).data())


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


def _contains_forbidden_policy_event(value: object) -> bool:
    """Inspect event metadata without treating quoted story/result text as a tool call."""

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


class CodexCliProvider:
    """Run one explicit organization request without a shell or persistent rollout."""

    def __init__(
        self,
        mode: CodexMode,
        *,
        executable: str = "codex",
        process_factory: ProcessFactory | None = None,
        executable_resolver: ExecutableResolver | None = None,
        model_override: str | None = None,
        lmstudio_base_url: str = "http://127.0.0.1:1234",
        model_discovery: ModelDiscovery | None = None,
        environment_factory: EnvironmentFactory | None = None,
        attempt_observer: Callable[[ProviderAttemptUsage], None] | None = None,
        repair_semaphore: threading.Semaphore | None = None,
    ) -> None:
        self.mode = mode
        self.executable = executable
        self._process_factory = process_factory or _qt_process
        self._active: Process | None = None
        self._cancel_requested = threading.Event()
        self._using_default_factory = process_factory is None
        self._executable_resolver = executable_resolver
        normalized_model = _validated_model_identifier(model_override)
        if mode is CodexMode.CODEX_CHATGPT:
            if normalized_model not in {None, M05_CLOUD_MODEL}:
                raise ValueError(f"ChatGPT organization is locked to {M05_CLOUD_MODEL}.")
            normalized_model = M05_CLOUD_MODEL
        self._model_override = normalized_model
        self._lmstudio_base_url = lmstudio_base_url
        self._model_discovery = model_discovery or _discover_models
        self._environment_factory = environment_factory or QProcessEnvironment.systemEnvironment
        self._cached_status: ProviderStatus | None = None
        self._resolved_executable: str | None = None
        self._resolved_cli_version: str | None = None
        self._input_tokens: int | None = None
        self._output_tokens: int | None = None
        self._effective_model: str | None = None
        self._reported_model: str | None = None
        self._attempt_observer = attempt_observer
        self._repair_semaphore = repair_semaphore

    def set_attempt_observer(self, observer: Callable[[ProviderAttemptUsage], None] | None) -> None:
        """Install a scheduler-owned incremental accounting sink."""
        self._attempt_observer = observer

    def set_repair_semaphore(self, semaphore: threading.Semaphore | None) -> None:
        """Share a scheduler repair bound across otherwise independent providers."""
        self._repair_semaphore = semaphore

    def status(self) -> ProviderStatus:
        if self._cached_status is not None:
            return self._cached_status
        resolved: str | None
        version: str | None
        if self._resolved_executable is not None:
            resolved = self._resolved_executable
            version = self._resolved_cli_version
        elif self._using_default_factory:
            resolved, version = self._discover_native_executable()
        else:
            resolved = (
                self._executable_resolver(self.executable)
                if self._executable_resolver is not None
                else self.executable
            )
            version = None
        if resolved is None:
            self._cached_status = ProviderStatus(
                ProviderState.MISSING,
                None,
                message="Codex CLI was not found. Install it or select deterministic organization.",
            )
            return self._cached_status
        self._resolved_executable = resolved
        self._resolved_cli_version = version
        model_identifier = self._model_override
        if self.mode is CodexMode.CODEX_LMSTUDIO:
            lmstudio_status = self._lmstudio_status(
                resolved, version, requested_model=model_identifier
            )
            if lmstudio_status.state is ProviderState.READY:
                self._cached_status = lmstudio_status
            return lmstudio_status
        self._cached_status = ProviderStatus(
            ProviderState.READY,
            resolved,
            cli_version=version,
            model_identifier=model_identifier,
        )
        return self._cached_status

    def set_model_override(self, model_identifier: str | None) -> None:
        """Apply an advanced model choice before status/cache preflight."""
        normalized = _validated_model_identifier(model_identifier)
        if self.mode is CodexMode.CODEX_CHATGPT:
            if normalized not in {None, M05_CLOUD_MODEL}:
                raise ValueError(f"ChatGPT organization is locked to {M05_CLOUD_MODEL}.")
            normalized = M05_CLOUD_MODEL
        if normalized == self._model_override:
            return
        self._model_override = normalized
        self._cached_status = None

    def _lmstudio_status(
        self,
        executable: str,
        version: str | None,
        *,
        requested_model: str | None,
    ) -> ProviderStatus:
        discovery_url = self._lmstudio_discovery_url()
        if discovery_url is None:
            return ProviderStatus(
                ProviderState.MISSING,
                executable,
                cli_version=version,
                message="LM Studio discovery is restricted to a loopback HTTP endpoint.",
            )
        try:
            payload = self._model_discovery(discovery_url, _MODEL_DISCOVERY_TIMEOUT_SECONDS)
        except (OSError, ValueError):
            return ProviderStatus(
                ProviderState.MISSING,
                executable,
                cli_version=version,
                message=(
                    "LM Studio is unavailable. Start it on loopback port 1234 and load "
                    "exactly one model."
                ),
            )
        if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
            return self._invalid_lmstudio_status(executable, version)
        loaded_instances: list[tuple[str, int]] = []
        for model in payload["models"]:
            if not isinstance(model, dict):
                return self._invalid_lmstudio_status(executable, version)
            model_type = model.get("type")
            instances = model.get("loaded_instances")
            if not isinstance(model_type, str) or not isinstance(instances, list):
                return self._invalid_lmstudio_status(executable, version)
            for instance in instances:
                if model_type != "llm":
                    return ProviderStatus(
                        ProviderState.MISSING,
                        executable,
                        cli_version=version,
                        message=(
                            "LM Studio has a loaded non-LLM instance. Leave exactly one "
                            "loaded LLM instance and retry."
                        ),
                    )
                if not isinstance(instance, dict):
                    return self._invalid_lmstudio_status(executable, version)
                identifier = instance.get("id")
                config = instance.get("config")
                if not isinstance(identifier, str) or not isinstance(config, dict):
                    return self._invalid_lmstudio_status(executable, version)
                context_length = config.get("context_length")
                if (
                    not isinstance(context_length, int)
                    or isinstance(context_length, bool)
                    or context_length <= 0
                ):
                    return ProviderStatus(
                        ProviderState.MISSING,
                        executable,
                        cli_version=version,
                        message=(
                            "LM Studio does not report a valid loaded context capability. "
                            "Reload exactly one LLM with a positive context length."
                        ),
                    )
                try:
                    validated_identifier = _validated_model_identifier(identifier)
                except ValueError:
                    return self._invalid_lmstudio_status(executable, version)
                if validated_identifier is None:
                    return self._invalid_lmstudio_status(executable, version)
                loaded_instances.append((validated_identifier, context_length))
        selected_instances = loaded_instances
        if requested_model is not None:
            selected_instances = [item for item in loaded_instances if item[0] == requested_model]
        if not selected_instances:
            return ProviderStatus(
                ProviderState.MISSING,
                executable,
                cli_version=version,
                message=(
                    "LM Studio has no matching loaded LLM instance. Load the selected model "
                    "with a positive context length and retry."
                ),
            )
        if len(selected_instances) != 1:
            return ProviderStatus(
                ProviderState.MISSING,
                executable,
                cli_version=version,
                message=(
                    "LM Studio reports multiple matching loaded LLM instances. Leave exactly "
                    "one selected instance and retry."
                ),
            )
        identifier, context_length = selected_instances[0]
        return ProviderStatus(
            ProviderState.READY,
            executable,
            cli_version=version,
            model_identifier=identifier,
            context_window_tokens=context_length,
        )

    @staticmethod
    def _invalid_lmstudio_status(executable: str, version: str | None) -> ProviderStatus:
        return ProviderStatus(
            ProviderState.MISSING,
            executable,
            cli_version=version,
            message=(
                "LM Studio returned an invalid native model list. Restart it and load "
                "exactly one LLM instance."
            ),
        )

    def _lmstudio_discovery_url(self) -> str | None:
        try:
            parsed = urlsplit(self._lmstudio_base_url)
            port = parsed.port
        except ValueError:
            return None
        hostname = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "http"
            or hostname != "127.0.0.1"
            or port != 1234
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            return None
        return _LMSTUDIO_MODELS_URL

    def command(self, schema_path: Path, model: str | None = None) -> tuple[str, list[str]]:
        selected_model = model
        if self.mode is CodexMode.CODEX_CHATGPT:
            if selected_model not in {None, M05_CLOUD_MODEL}:
                raise ValueError(f"ChatGPT organization is locked to {M05_CLOUD_MODEL}.")
            selected_model = M05_CLOUD_MODEL
        args = [
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
            args.extend(["--disable", feature])
        args.extend(
            [
                "-c",
                'web_search="disabled"',
                "-c",
                "analytics.enabled=false",
            ]
        )
        if self.mode is CodexMode.CODEX_CHATGPT:
            args.extend(["-c", 'model_reasoning_effort="high"'])
        args.extend(["--json", "--output-schema", str(schema_path)])
        if selected_model:
            args.extend(["--model", selected_model])
        if self.mode is CodexMode.CODEX_LMSTUDIO:
            args.extend(["--oss", "--local-provider", "lmstudio"])
        args.append("-")
        return self._resolved_executable or self.executable, args

    def organize(
        self,
        request: OrganizationRequest,
        progress: ProgressCallback,
        cancelled: CancelledCallback,
    ) -> OrganizationChunkResult:
        try:
            if cancelled() or self._cancel_requested.is_set():
                raise OrganizationCancelledError(
                    "Story organization was cancelled before transmission; "
                    "the accepted map was not changed."
                )
            if (
                self.mode is CodexMode.CODEX_CHATGPT
                and (
                    not request.run_id
                    or request.run_id != request.run_id.strip()
                    or request.cloud_consent_run_id != request.run_id
                )
            ):
                raise ConsentRequiredError(
                    "Confirm cloud story transmission for this organization run before continuing."
                )
            self._validate_prompt_limits(request)
            if request.model is not None and request.model != self._model_override:
                self.set_model_override(request.model)
            provider_status = self.status()
            if provider_status.state is ProviderState.MISSING:
                raise ProviderUnavailableError(
                    provider_status.message
                    or "Codex CLI is unavailable. Install it or use deterministic organization."
                )
            self._effective_model = request.model or provider_status.model_identifier
            self._reported_model = None
            progress(0, "Preparing isolated organizer")
            started_at = time.monotonic()
            last_error: InvalidProviderOutputError | None = None
            transmitted_prompts: list[bytes] = []
            input_usage: list[int | None] = []
            output_usage: list[int | None] = []
            for attempt in (1, 2):
                repair = attempt == 2
                transmitted_prompts.append(
                    self._prompt(request, repair=repair).encode("utf-8")
                )
                self._input_tokens = None
                self._output_tokens = None
                usage_recorded = False
                attempt_started_at = time.monotonic()
                outcome = "failed"
                repair_acquired = False
                try:
                    if repair and self._repair_semaphore is not None:
                        while not self._repair_semaphore.acquire(timeout=0.05):
                            if cancelled() or self._cancel_requested.is_set():
                                raise OrganizationCancelledError(
                                    "Story organization was cancelled while awaiting repair."
                                )
                        repair_acquired = True
                    raw = self._execute(request, progress, cancelled, repair=repair)
                    input_usage.append(self._input_tokens)
                    output_usage.append(self._output_tokens)
                    usage_recorded = True
                    result = validate_result(raw, request)
                    outcome = "validated"
                    normalized = json.dumps(
                        result.raw_normalized,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    input_material = b"".join(
                        len(prompt).to_bytes(8, "big") + prompt
                        for prompt in transmitted_prompts
                    )
                    total_input_tokens = (
                        sum(cast(int, value) for value in input_usage)
                        if all(value is not None for value in input_usage)
                        else None
                    )
                    total_output_tokens = (
                        sum(cast(int, value) for value in output_usage)
                        if all(value is not None for value in output_usage)
                        else None
                    )
                    return OrganizationChunkResult(
                        stage=result.stage,
                        groups=result.groups,
                        ungrouped_ids=result.ungrouped_ids,
                        raw_normalized=result.raw_normalized,
                        attempts=attempt,
                        metadata=ProviderExecutionMetadata(
                            provider_mode=self.mode,
                            model_identifier=self._effective_model,
                            cli_version=self.status().cli_version,
                            elapsed_ms=round((time.monotonic() - started_at) * 1000),
                            input_hash=hashlib.sha256(input_material).hexdigest(),
                            output_hash=hashlib.sha256(normalized).hexdigest(),
                            input_tokens=total_input_tokens,
                            output_tokens=total_output_tokens,
                            context_window_tokens=provider_status.context_window_tokens,
                        ),
                    )
                except InvalidProviderOutputError as exc:
                    if not usage_recorded:
                        input_usage.append(None)
                        output_usage.append(None)
                    last_error = exc
                    if attempt == 1:
                        progress(75, "Repairing structured output")
                        continue
                    raise InvalidProviderOutputError(
                        "The organizer returned invalid structured output twice; "
                        "using deterministic organization."
                    ) from None
                except OrganizationCancelledError:
                    outcome = "cancelled"
                    raise
                except ProviderTimeoutError:
                    outcome = "timeout"
                    raise
                except ProviderRateLimitError:
                    outcome = "rate_limited"
                    raise
                finally:
                    if repair_acquired and self._repair_semaphore is not None:
                        self._repair_semaphore.release()
                    if self._attempt_observer is not None:
                        self._attempt_observer(
                            ProviderAttemptUsage(
                                attempt=attempt,
                                elapsed_ms=round(
                                    (time.monotonic() - attempt_started_at) * 1000
                                ),
                                outcome=outcome,
                                input_tokens=self._input_tokens,
                                output_tokens=self._output_tokens,
                            )
                        )
            assert last_error is not None
            raise last_error
        finally:
            self._cancel_requested.clear()

    def cancel(self) -> None:
        self._cancel_requested.set()

    def _execute(
        self,
        request: OrganizationRequest,
        progress: ProgressCallback,
        cancelled: CancelledCallback,
        *,
        repair: bool,
    ) -> object:
        if cancelled() or self._cancel_requested.is_set():
            raise OrganizationCancelledError(
                "Story organization was cancelled before transmission; "
                "the accepted map was not changed."
            )
        self._validate_prompt_limits(request)
        schema = files("renpy_story_mapper.organization.schemas").joinpath(
            f"{request.stage.value}.schema.json"
        )
        with (
            as_file(schema) as schema_path,
            tempfile.TemporaryDirectory(prefix="renpy-story-organizer-") as temp_path,
        ):
            process = self._process_factory()
            self._active = process
            try:
                if cancelled() or self._cancel_requested.is_set():
                    raise OrganizationCancelledError(
                        "Story organization was cancelled before transmission; "
                        "the accepted map was not changed."
                    )
                process.setWorkingDirectory(temp_path)
                if self.mode is CodexMode.CODEX_LMSTUDIO:
                    process.setProcessEnvironment(
                        self._lmstudio_process_environment(Path(temp_path))
                    )
                program, arguments = self.command(
                    schema_path,
                    self._model_override or self._effective_model,
                )
                process.start(program, arguments)
                for _attempt in range(_START_POLL_ATTEMPTS):
                    if cancelled() or self._cancel_requested.is_set():
                        self._stop_process(process)
                        raise OrganizationCancelledError(
                            "Story organization was cancelled during provider startup; "
                            "the accepted map was not changed."
                        )
                    if process.waitForStarted(_POLL_MS):
                        break
                    if cancelled() or self._cancel_requested.is_set():
                        self._stop_process(process)
                        raise OrganizationCancelledError(
                            "Story organization was cancelled during provider startup; "
                            "the accepted map was not changed."
                        )
                    if process.state() == QProcess.ProcessState.NotRunning:
                        raise ProviderUnavailableError(
                            "Codex CLI could not start. Check the installation and provider "
                            "availability."
                        )
                else:
                    self._stop_process(process)
                    raise ProviderTimeoutError(
                        "Codex CLI startup timed out. Check provider availability and retry."
                    )
                prompt = self._prompt(request, repair=repair).encode("utf-8")
                written = process.write(prompt)
                if written != len(prompt):
                    self._stop_process(process)
                    raise ProviderUnavailableError(
                        "Codex CLI did not accept the complete organization input."
                    )
                process.closeWriteChannel()
                progress(20, "Organizing story structure")
                deadline = time.monotonic() + request.timeout_seconds
                buffer = b""
                final_payload: object | None = None
                while not process.waitForFinished(_POLL_MS):
                    buffer += _as_bytes(process.readAllStandardOutput())
                    buffer, found = self._consume_lines(buffer, process)
                    if found is not None:
                        final_payload = found
                    if cancelled() or self._cancel_requested.is_set():
                        self._stop_process(process)
                        raise OrganizationCancelledError(
                            "Story organization was cancelled; the accepted map was not changed."
                        )
                    if time.monotonic() >= deadline:
                        self._stop_process(process)
                        raise ProviderTimeoutError(
                            "The organizer timed out. Retry a smaller scope or check the "
                            "local model."
                        )
                buffer += _as_bytes(process.readAllStandardOutput())
                buffer, found = self._consume_lines(buffer + b"\n", process)
                if found is not None:
                    final_payload = found
                if process.exitCode() != 0:
                    self._raise_process_failure(_as_bytes(process.readAllStandardError()))
                if final_payload is None:
                    raise InvalidProviderOutputError(
                        "The organizer did not return a structured result; "
                        "using deterministic organization."
                    )
                progress(100, "Organization chunk validated")
                return final_payload
            finally:
                if not process.waitForFinished(0):
                    self._stop_process(process)
                if self._active is process:
                    self._active = None

    def _consume_lines(self, buffer: bytes, process: Process) -> tuple[bytes, object | None]:
        lines = buffer.split(b"\n")
        remainder = lines.pop()
        final: object | None = None
        for line in lines:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._stop_process(process)
                raise InvalidProviderOutputError(
                    "The organizer emitted malformed JSONL; using deterministic organization."
                ) from None
            marker_text = json.dumps(event, separators=(",", ":")).lower()
            if _contains_forbidden_policy_event(event):
                self._stop_process(process)
                raise PolicyViolationError(
                    "The organizer attempted a forbidden tool, web, MCP, command, or file action."
                )
            if isinstance(event, dict) and event.get("type") in {"error", "turn.failed"}:
                self._stop_process(process)
                self._raise_process_failure(marker_text.encode("utf-8"))
            self._capture_metadata(event)
            candidate = self._extract_result(event)
            if candidate is not None:
                final = candidate
        return remainder, final

    @staticmethod
    def _extract_result(event: object) -> object | None:
        if not isinstance(event, dict):
            return None
        if set(event) == {"stage", "groups", "ungrouped_ids"}:
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
        if isinstance(response, dict):
            return response
        return None

    def _capture_metadata(self, event: object) -> None:
        if not isinstance(event, dict):
            return
        usage = event.get("usage")
        if isinstance(usage, dict):
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            if isinstance(input_tokens, int):
                self._input_tokens = input_tokens
            if isinstance(output_tokens, int):
                self._output_tokens = output_tokens
        if "model" not in event:
            return
        model = event["model"]
        if not isinstance(model, str):
            raise ProviderUnavailableError("The organizer reported invalid model metadata.")
        try:
            validated_model = _validated_model_identifier(model)
        except ValueError:
            raise ProviderUnavailableError(
                "The organizer reported invalid model metadata."
            ) from None
        if validated_model is None:
            raise ProviderUnavailableError("The organizer reported invalid model metadata.")
        if self._effective_model is not None and validated_model != self._effective_model:
            raise ProviderUnavailableError(
                "The organizer reported a different model than the preflight selection."
            )
        self._reported_model = validated_model
        self._effective_model = validated_model

    @staticmethod
    def _prompt(request: OrganizationRequest, *, repair: bool) -> str:
        return serialize_organization_prompt(request, repair=repair)

    @staticmethod
    def _validate_prompt_limits(request: OrganizationRequest) -> None:
        if any(
            len(serialize_organization_prompt(request, repair=repair)) > MAX_PROMPT_CHARS
            for repair in (False, True)
        ):
            raise ValueError("The complete organization prompt exceeds the 48,000-character limit.")

    def _lmstudio_process_environment(self, codex_home: Path) -> QProcessEnvironment:
        """Return a proxy-free local environment with no user Codex state."""

        if not codex_home.is_absolute():
            raise ValueError("The isolated local Codex home must be absolute.")
        environment = self._environment_factory()
        for name in environment.keys():  # noqa: SIM118 - Qt wrapper is not iterable
            if name.upper() in _PROXY_VARIABLES:
                environment.remove(name)
        environment.insert("CODEX_HOME", str(codex_home))
        environment.insert("NO_PROXY", _LOOPBACK_NO_PROXY)
        environment.insert("no_proxy", _LOOPBACK_NO_PROXY)
        return environment

    @staticmethod
    def _stop_process(process: Process) -> None:
        process.terminate()
        if not process.waitForFinished(_CANCEL_GRACE_MS):
            process.kill()
            process.waitForFinished(_KILL_CLEANUP_MS)

    @staticmethod
    def _probe_version(executable: str, deadline: float | None = None) -> str | None:
        if deadline is None:
            deadline = time.monotonic() + _EXECUTABLE_DISCOVERY_TIMEOUT_SECONDS
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
        version = (
            bytes(process.readAllStandardOutput().data()).decode("utf-8", errors="ignore").strip()
        )
        return version or None

    def _discover_native_executable(self) -> tuple[str | None, str | None]:
        deadline = time.monotonic() + _EXECUTABLE_DISCOVERY_TIMEOUT_SECONDS
        candidates: list[Path] = []
        configured = Path(self.executable)
        if (
            configured.is_absolute()
            and configured.suffix.casefold() == ".exe"
            and configured.is_file()
        ):
            candidates.append(configured.resolve())
        for shim in _path_executable_candidates(self.executable):
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
            normalized = str(candidate.resolve())
            if normalized in seen:
                continue
            seen.add(normalized)
            version = self._probe_version(normalized, deadline)
            if version is not None:
                return normalized, version
        return None, None

    @staticmethod
    def _raise_process_failure(stderr: bytes) -> None:
        category = stderr.decode("utf-8", errors="ignore").lower()
        if "rate limit" in category or "429" in category:
            raise ProviderRateLimitError(
                "The organizer is rate limited. Wait and retry, or use local organization."
            )
        if "not logged in" in category or "sign in" in category or "unauthorized" in category:
            raise ProviderUnavailableError(
                "Codex is signed out. Run codex login, then retry the explicit organization action."
            )
        if "lm studio" in category or "connection refused" in category:
            raise ProviderUnavailableError(
                "LM Studio is unavailable or has no loaded model. Start it and load a model "
                "before retrying."
            )
        if "refus" in category:
            raise ProviderRefusalError(
                "The organizer declined this chunk. Use deterministic organization or "
                "revise the scope."
            )
        raise ProviderUnavailableError(
            "The organizer process failed. Check provider availability and diagnostics, then retry."
        )
