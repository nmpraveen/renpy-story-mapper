"""Sterile raw-request provider for the approved Phase 04 workflow runner.

The durable runner supplies exact frozen JSON bytes.  This adapter transmits those bytes
unchanged to one direct, tool-disabled Codex CLI process and returns only the schema-bound JSON
object plus finite accounting.  It never reads project files or constructs provider input.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import cast

from renpy_story_mapper.story_map_v2.cloud_transport import (
    DEFAULT_MAXIMUM_INPUT_BYTES,
    DEFAULT_MAXIMUM_OUTPUT_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    Process,
    ProcessFactory,
    ProcessSpec,
    _classify_process_failure,
    _classify_structured_failure,
    _contains_forbidden_action,
    _default_process_factory,
    _optional_bytes,
    _stop_process,
    build_sterile_command,
    discover_native_codex,
)
from renpy_story_mapper.story_map_v2.contracts import FailureKind, canonical_json
from renpy_story_mapper.story_map_v2.provider_policy import ProviderFailure
from renpy_story_mapper.story_map_v2.workflow_contracts import (
    CLOUD_FAST_MODE,
    CLOUD_MODEL,
    CLOUD_PROVIDER,
    CLOUD_REASONING,
    AttemptAccounting,
    ProviderCallResult,
    TransmissionDisposition,
    WorkflowFailure,
)
from renpy_story_mapper.story_map_v2.workflow_protocols import WorkflowProviderError

_POLL_SECONDS = 0.05


class CodexCliWorkflowProvider:
    """Submit one exact Phase 04 request through a sterile Terra/High process."""

    def __init__(
        self,
        *,
        executable: str = "codex",
        schema_path: Path | None = None,
        process_factory: ProcessFactory = _default_process_factory,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        maximum_input_bytes: int = DEFAULT_MAXIMUM_INPUT_BYTES,
        maximum_output_bytes: int = DEFAULT_MAXIMUM_OUTPUT_BYTES,
    ) -> None:
        selected_schema = schema_path or (
            Path(__file__).resolve().parent
            / "schemas"
            / "story_map_phase04_mapper_response_v1.schema.json"
        )
        self._schema_path = selected_schema.resolve()
        if not self._schema_path.is_file():
            raise ValueError("The Phase 04 workflow response schema is unavailable.")
        if timeout_seconds <= 0:
            raise ValueError("The workflow provider timeout must be positive.")
        if maximum_input_bytes <= 0 or maximum_output_bytes <= 0:
            raise ValueError("Workflow provider byte limits must be positive.")
        self._executable = executable
        self._process_factory = process_factory
        self._timeout_seconds = timeout_seconds
        self._maximum_input_bytes = maximum_input_bytes
        self._maximum_output_bytes = maximum_output_bytes
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._active: Process | None = None
        self._resolved_executable: str | None = None

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            active = self._active
        if active is not None:
            _stop_process(active)

    def submit(self, request: bytes) -> ProviderCallResult:
        started = time.monotonic()
        if self._cancelled.is_set():
            raise _workflow_error(
                WorkflowFailure.CANCELLED,
                TransmissionDisposition.NOT_TRANSMITTED,
                started,
            )
        if not request or len(request) > self._maximum_input_bytes:
            raise _workflow_error(
                WorkflowFailure.RESOURCE_LIMIT,
                TransmissionDisposition.NOT_TRANSMITTED,
                started,
            )
        executable = self._resolved_executable or discover_native_codex(self._executable)
        if executable is None:
            raise _workflow_error(
                WorkflowFailure.PROVIDER_UNAVAILABLE,
                TransmissionDisposition.NOT_TRANSMITTED,
                started,
            )
        self._resolved_executable = executable
        command = build_sterile_command(
            executable,
            self._schema_path,
            model=CLOUD_MODEL,
            reasoning=CLOUD_REASONING,
        )
        with tempfile.TemporaryDirectory(prefix="renpy-story-map-v2-workflow-") as directory:
            try:
                process = self._process_factory(
                    ProcessSpec(command=command, cwd=Path(directory).resolve())
                )
            except Exception:
                raise _workflow_error(
                    WorkflowFailure.PROVIDER_UNAVAILABLE,
                    TransmissionDisposition.NOT_TRANSMITTED,
                    started,
                ) from None
            with self._lock:
                self._active = process
            try:
                stdout, stderr = self._communicate(process, request)
            except ProviderFailure as exc:
                raise _adapt_failure(exc, started) from None
            finally:
                with self._lock:
                    if self._active is process:
                        self._active = None
                if process.poll() is None:
                    _stop_process(process)
        if process.returncode != 0:
            raise _adapt_failure(_classify_process_failure(stderr), started) from None
        try:
            payload, metadata = _parse_workflow_jsonl(stdout)
        except ProviderFailure as exc:
            raise _adapt_failure(exc, started) from None
        models, reasonings, fast_modes = metadata
        if (
            (models and models != frozenset({CLOUD_MODEL}))
            or (reasonings and reasonings != frozenset({CLOUD_REASONING}))
            or (fast_modes and fast_modes != frozenset({CLOUD_FAST_MODE}))
        ):
            raise _workflow_error(
                WorkflowFailure.IDENTITY_MISMATCH,
                TransmissionDisposition.TRANSMITTED,
                started,
                calls=1,
            )
        try:
            input_tokens, output_tokens = _parse_last_usage(stdout)
        except ProviderFailure as exc:
            raise _adapt_failure(exc, started) from None
        return ProviderCallResult(
            payload=payload,
            accounting=AttemptAccounting(
                calls=1,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                elapsed_ms=_elapsed_ms(started),
            ),
            resolved_provider=CLOUD_PROVIDER,
            resolved_model=CLOUD_MODEL,
            resolved_reasoning=CLOUD_REASONING,
            resolved_fast_mode=CLOUD_FAST_MODE,
        )

    def _communicate(self, process: Process, request: bytes) -> tuple[bytes, bytes]:
        deadline = time.monotonic() + self._timeout_seconds
        pending: bytes | None = request
        while True:
            if self._cancelled.is_set():
                _stop_process(process)
                raise ProviderFailure(FailureKind.CANCELLED, "Workflow call was cancelled.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _stop_process(process)
                raise ProviderFailure(FailureKind.TIMEOUT, "Workflow call timed out.")
            try:
                stdout, stderr = process.communicate(
                    input=pending,
                    timeout=min(_POLL_SECONDS, remaining),
                )
            except subprocess.TimeoutExpired as exc:
                pending = None
                partial = _optional_bytes(exc.output) + _optional_bytes(exc.stderr)
                if len(partial) > self._maximum_output_bytes:
                    _stop_process(process)
                    raise ProviderFailure(
                        FailureKind.INVALID_RESPONSE,
                        "Workflow output exceeded its bounded limit.",
                    ) from None
                continue
            except OSError:
                _stop_process(process)
                raise ProviderFailure(FailureKind.TRANSPORT, "Workflow transport failed.") from None
            if len(stdout) + len(stderr) > self._maximum_output_bytes:
                raise ProviderFailure(
                    FailureKind.INVALID_RESPONSE,
                    "Workflow output exceeded its bounded limit.",
                )
            return stdout, stderr


def _parse_workflow_jsonl(
    raw: bytes,
) -> tuple[bytes, tuple[frozenset[str], frozenset[str], frozenset[bool]]]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise ProviderFailure(
            FailureKind.INVALID_RESPONSE, "Workflow output was not UTF-8."
        ) from None
    payload: object | None = None
    models: set[str] = set()
    reasonings: set[str] = set()
    fast_modes: set[bool] = set()
    for line in lines:
        if not line.strip():
            continue
        try:
            event: object = json.loads(line)
        except json.JSONDecodeError:
            raise ProviderFailure(
                FailureKind.INVALID_RESPONSE, "Workflow output was malformed."
            ) from None
        if _contains_forbidden_action(event):
            raise ProviderFailure(FailureKind.INVALID_RESPONSE, "Workflow attempted an action.")
        if not isinstance(event, dict):
            continue
        if event.get("type") in {"error", "turn.failed"}:
            raise _classify_structured_failure(cast(dict[object, object], event))
        model = event.get("model")
        reasoning = event.get("reasoning_effort", event.get("model_reasoning_effort"))
        fast_mode = event.get("fast_mode")
        if model is not None:
            if not isinstance(model, str):
                raise ProviderFailure(FailureKind.IDENTITY, "Invalid workflow model metadata.")
            models.add(model)
        if reasoning is not None:
            if not isinstance(reasoning, str):
                raise ProviderFailure(FailureKind.IDENTITY, "Invalid reasoning metadata.")
            reasonings.add(reasoning.casefold())
        if fast_mode is not None:
            if not isinstance(fast_mode, bool):
                raise ProviderFailure(FailureKind.IDENTITY, "Invalid fast-mode metadata.")
            fast_modes.add(fast_mode)
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            text = item.get("text")
            if isinstance(text, str):
                with suppress(json.JSONDecodeError):
                    payload = json.loads(text)
        response = event.get("response")
        if isinstance(response, dict):
            payload = response
        if "schema" in event and "type" not in event:
            payload = event
    if payload is None or not isinstance(payload, dict):
        raise ProviderFailure(FailureKind.INVALID_RESPONSE, "Workflow returned no JSON object.")
    return canonical_json(payload), (
        frozenset(models),
        frozenset(reasonings),
        frozenset(fast_modes),
    )


def _parse_last_usage(raw: bytes) -> tuple[int, int]:
    input_tokens = 0
    output_tokens = 0
    for line in raw.decode("utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        usage = event.get("usage") if isinstance(event, dict) else None
        if not isinstance(usage, dict):
            continue
        raw_input = usage.get("input_tokens")
        raw_output = usage.get("output_tokens")
        if (
            not isinstance(raw_input, int)
            or isinstance(raw_input, bool)
            or raw_input < 0
            or not isinstance(raw_output, int)
            or isinstance(raw_output, bool)
            or raw_output < 0
        ):
            raise ProviderFailure(FailureKind.INVALID_RESPONSE, "Invalid workflow usage metadata.")
        input_tokens, output_tokens = raw_input, raw_output
    return input_tokens, output_tokens


def _adapt_failure(error: ProviderFailure, started: float) -> WorkflowProviderError:
    mapping = {
        FailureKind.CONTENT_REFUSAL: WorkflowFailure.CONTENT_REFUSAL,
        FailureKind.INVALID_RESPONSE: WorkflowFailure.INVALID_RESPONSE,
        FailureKind.IDENTITY: WorkflowFailure.IDENTITY_MISMATCH,
        FailureKind.CANCELLED: WorkflowFailure.CANCELLED,
        FailureKind.LOCAL_UNAVAILABLE: WorkflowFailure.PROVIDER_UNAVAILABLE,
    }
    failure = mapping.get(error.kind, WorkflowFailure.PROVIDER_UNAVAILABLE)
    definitely_returned = error.kind in {
        FailureKind.CONTENT_REFUSAL,
        FailureKind.INVALID_RESPONSE,
        FailureKind.IDENTITY,
        FailureKind.RATE_LIMIT,
        FailureKind.AUTHENTICATION,
    }
    transmission = (
        TransmissionDisposition.TRANSMITTED
        if definitely_returned
        else TransmissionDisposition.INDETERMINATE
    )
    return _workflow_error(failure, transmission, started, calls=1)


def _workflow_error(
    failure: WorkflowFailure,
    transmission: TransmissionDisposition,
    started: float,
    *,
    calls: int = 0,
) -> WorkflowProviderError:
    return WorkflowProviderError(
        failure,
        transmission,
        AttemptAccounting(
            calls=calls,
            input_tokens=0,
            output_tokens=0,
            elapsed_ms=_elapsed_ms(started),
        ),
    )


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))
