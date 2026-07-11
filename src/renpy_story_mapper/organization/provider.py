"""Isolated Codex CLI provider using direct QProcess execution."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from importlib.resources import as_file, files
from pathlib import Path
from typing import Protocol, cast

from PySide6.QtCore import QByteArray, QProcess

from renpy_story_mapper.organization.contracts import (
    CancelledCallback,
    CodexMode,
    OrganizationChunkResult,
    OrganizationRequest,
    ProgressCallback,
    ProviderExecutionMetadata,
    ProviderState,
    ProviderStatus,
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

_POLL_MS = 25
_CANCEL_GRACE_MS = 1_750
_KILL_CLEANUP_MS = 200
_FORBIDDEN_MARKERS = {
    "command_execution",
    "shell_command",
    "function_call",
    "mcp_tool_call",
    "web_search",
    "file_change",
    "apply_patch",
}


class Process(Protocol):
    def setWorkingDirectory(self, directory: str) -> None: ...
    def start(self, program: str, arguments: list[str]) -> None: ...
    def waitForStarted(self, msecs: int = 30000) -> bool: ...
    def write(self, data: bytes) -> int: ...
    def closeWriteChannel(self) -> None: ...
    def waitForReadyRead(self, msecs: int = 30000) -> bool: ...
    def waitForFinished(self, msecs: int = 30000) -> bool: ...
    def readAllStandardOutput(self) -> object: ...
    def readAllStandardError(self) -> object: ...
    def exitCode(self) -> int: ...
    def state(self) -> object: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...


ProcessFactory = Callable[[], Process]


def _qt_process() -> Process:
    return cast(Process, QProcess())


def _as_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    return bytes(cast(QByteArray, value).data())


class CodexCliProvider:
    """Run one explicit organization request without a shell or persistent rollout."""

    def __init__(
        self,
        mode: CodexMode,
        *,
        executable: str = "codex",
        process_factory: ProcessFactory | None = None,
    ) -> None:
        self.mode = mode
        self.executable = executable
        self._process_factory = process_factory or _qt_process
        self._active: Process | None = None
        self._cancel_requested = threading.Event()
        self._using_default_factory = process_factory is None
        self._cached_status: ProviderStatus | None = None
        self._resolved_executable: str | None = None
        self._input_tokens: int | None = None
        self._output_tokens: int | None = None
        self._effective_model: str | None = None

    def status(self) -> ProviderStatus:
        if self._cached_status is not None:
            return self._cached_status
        if self._using_default_factory:
            resolved, version = self._discover_native_executable()
        else:
            resolved = shutil.which(self.executable)
            version = None
        if resolved is None:
            self._cached_status = ProviderStatus(
                ProviderState.MISSING,
                None,
                message="Codex CLI was not found. Install it or select deterministic organization.",
            )
            return self._cached_status
        if self._using_default_factory:
            self._resolved_executable = resolved
        self._cached_status = ProviderStatus(ProviderState.READY, resolved, cli_version=version)
        return self._cached_status

    def command(self, schema_path: Path, model: str | None = None) -> tuple[str, list[str]]:
        args = [
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--ignore-user-config",
            "--ignore-rules",
            "--json",
            "--output-schema",
            str(schema_path),
        ]
        if model:
            args.extend(["--model", model])
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
        if self.mode is CodexMode.CODEX_CHATGPT and request.cloud_consent_run_id != request.run_id:
            raise ConsentRequiredError(
                "Confirm cloud story transmission for this organization run before continuing."
            )
        if self.status().state is ProviderState.MISSING:
            raise ProviderUnavailableError(
                "Codex CLI is unavailable. Install it or use deterministic organization."
            )
        self._cancel_requested.clear()
        self._input_tokens = None
        self._output_tokens = None
        self._effective_model = request.model
        progress(0, "Preparing isolated organizer")
        started_at = time.monotonic()
        last_error: InvalidProviderOutputError | None = None
        for attempt in (1, 2):
            try:
                raw = self._execute(request, progress, cancelled, repair=attempt == 2)
                result = validate_result(raw, request)
                normalized = json.dumps(
                    result.raw_normalized,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                input_material = self._prompt(request, repair=False).encode("utf-8")
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
                        input_tokens=self._input_tokens,
                        output_tokens=self._output_tokens,
                    ),
                )
            except InvalidProviderOutputError as exc:
                last_error = exc
                if attempt == 1:
                    progress(75, "Repairing structured output")
                    continue
                raise InvalidProviderOutputError(
                    "The organizer returned invalid structured output twice; "
                    "using deterministic organization."
                ) from None
        assert last_error is not None
        raise last_error

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
        schema = files("renpy_story_mapper.organization.schemas").joinpath(
            f"{request.stage.value}.schema.json"
        )
        with as_file(schema) as schema_path, tempfile.TemporaryDirectory(
            prefix="renpy-story-organizer-"
        ) as temp_path:
            process = self._process_factory()
            self._active = process
            process.setWorkingDirectory(temp_path)
            program, arguments = self.command(schema_path, request.model)
            process.start(program, arguments)
            if not process.waitForStarted(5_000):
                self._active = None
                raise ProviderUnavailableError(
                    "Codex CLI could not start. Check the installation and provider availability."
                )
            prompt = self._prompt(request, repair=repair)
            if process.write(prompt.encode("utf-8")) < 0:
                self._stop_process(process)
                raise ProviderUnavailableError("Codex CLI did not accept organization input.")
            process.closeWriteChannel()
            progress(20, "Organizing story structure")
            deadline = time.monotonic() + request.timeout_seconds
            buffer = b""
            final_payload: object | None = None
            try:
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
            if any(marker in marker_text for marker in _FORBIDDEN_MARKERS):
                self._stop_process(process)
                raise PolicyViolationError(
                    "The organizer attempted a forbidden tool, web, MCP, command, or file action."
                )
            if isinstance(event, dict) and event.get("type") in {"error", "turn.failed"}:
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
        model = event.get("model")
        if isinstance(model, str) and model:
            self._effective_model = model

    @staticmethod
    def _prompt(request: OrganizationRequest, *, repair: bool) -> str:
        instruction = (
            "Repair the prior response. Return only JSON matching the schema and supplied IDs."
            if repair
            else "Organize the supplied deterministic records. Return only schema-valid JSON."
        )
        envelope = {
            "instruction": instruction,
            "security": "Do not use tools, web, MCP, commands, or files.",
            "authority": (
                "Return only titles, summaries, existing memberships, characters supported by "
                "the input, outcomes, existing fact IDs, evidence-backed interpretations, "
                "warnings, and ungrouped IDs. Never invent edges, conditions, facts, source "
                "locations, route destinations, or causal authority."
            ),
            "contract": {
                "stage": request.stage.value,
                "allowed_member_ids": list(request.constraints.ordered_member_ids),
                "context_only_ids": sorted(request.constraints.context_member_ids),
                "allowed_fact_ids": sorted(request.constraints.fact_ids),
                "allowed_evidence_ids": sorted(request.constraints.evidence_ids),
                "allowed_characters": sorted(request.constraints.character_names),
            },
            "input": request.payload,
        }
        return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _stop_process(process: Process) -> None:
        process.terminate()
        if not process.waitForFinished(_CANCEL_GRACE_MS):
            process.kill()
            process.waitForFinished(_KILL_CLEANUP_MS)

    @staticmethod
    def _probe_version(executable: str) -> str | None:
        process = QProcess()
        process.start(executable, ["--version"])
        if not process.waitForStarted(2_000) or not process.waitForFinished(2_000):
            process.kill()
            return None
        if process.exitCode() != 0:
            return None
        version = bytes(process.readAllStandardOutput().data()).decode(
            "utf-8", errors="ignore"
        ).strip()
        return version or None

    def _discover_native_executable(self) -> tuple[str | None, str | None]:
        candidates: list[Path] = []
        configured = Path(self.executable)
        if configured.suffix.lower() == ".exe" and configured.is_file():
            candidates.append(configured)
        shim = shutil.which(self.executable)
        if shim is not None:
            npm_package = Path(shim).parent / "node_modules" / "@openai" / "codex"
            candidates.extend(
                sorted(
                    npm_package.glob(
                        "node_modules/@openai/codex-*/vendor/*/bin/codex.exe"
                    )
                )
            )
        path_executable = shutil.which(f"{self.executable}.exe")
        if path_executable is not None:
            candidates.append(Path(path_executable))
        seen: set[str] = set()
        for candidate in candidates:
            normalized = str(candidate.resolve())
            if normalized in seen:
                continue
            seen.add(normalized)
            version = self._probe_version(normalized)
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
