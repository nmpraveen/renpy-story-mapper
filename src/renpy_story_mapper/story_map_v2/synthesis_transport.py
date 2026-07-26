"""Sterile one-process Codex CLI transport for optional Phase 03 synthesis."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

from renpy_story_mapper.story_map_v2.cloud_transport import (
    Process,
    ProcessSpec,
    discover_native_codex,
)
from renpy_story_mapper.story_map_v2.contracts import canonical_json
from renpy_story_mapper.story_map_v2.phase03_contracts import (
    SynthesisFailureKind,
    SynthesisProviderReply,
    SynthesisProviderSettings,
)
from renpy_story_mapper.story_map_v2.synthesis import (
    SynthesisProviderFailure,
    validate_provider_schema,
)
from renpy_story_mapper.story_map_v2.synthesis import (
    response_schema as bundled_response_schema,
)

SYNTHESIS_MODEL = "gpt-5.6-terra"
SYNTHESIS_REASONING = "high"
SYNTHESIS_FAST_MODE = False
PROVIDER_IDENTITY = "openai-codex-cli-synthesis-v1"
_APPROVED_SCHEMA_SHA256 = "4febec35bc987cd8e273465ffbe69176cac02e8577690185fd84fa383b727bcc"
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAXIMUM_INPUT_BYTES = 2_000_000
DEFAULT_MAXIMUM_OUTPUT_BYTES = 2_000_000

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


def build_synthesis_command(executable: str, schema_path: Path) -> tuple[str, ...]:
    """Build the hardened direct Terra/High/fast-off synthesis command."""

    if not Path(executable).is_absolute() or Path(executable).suffix.casefold() != ".exe":
        raise ValueError("The synthesis transport requires an absolute native executable path.")
    if not schema_path.is_absolute() or not schema_path.is_file():
        raise ValueError("The synthesis schema must be an existing absolute file.")
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
            f'model_reasoning_effort="{SYNTHESIS_REASONING}"',
            "-c",
            "fast_mode=false",
            "-c",
            'web_search="disabled"',
            "-c",
            "analytics.enabled=false",
            "--json",
            "--output-schema",
            str(schema_path),
            "--model",
            SYNTHESIS_MODEL,
            "-",
        )
    )
    return tuple(arguments)


class CodexCliSynthesisProvider:
    """Submit one approved canonical payload to one sterile Codex CLI process."""

    def __init__(
        self,
        *,
        executable: str = "codex",
        process_factory: ProcessFactory = _default_process_factory,
        executable_resolver: ExecutableResolver = discover_native_codex,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        maximum_input_bytes: int = DEFAULT_MAXIMUM_INPUT_BYTES,
        maximum_output_bytes: int = DEFAULT_MAXIMUM_OUTPUT_BYTES,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("The synthesis timeout must be positive.")
        if maximum_input_bytes <= 0 or maximum_output_bytes <= 0:
            raise ValueError("Synthesis byte limits must be positive.")
        self._executable = executable
        self._process_factory = process_factory
        self._executable_resolver = executable_resolver
        self._timeout_seconds = timeout_seconds
        self._maximum_input_bytes = maximum_input_bytes
        self._maximum_output_bytes = maximum_output_bytes

    def synthesize(
        self,
        payload: bytes,
        *,
        response_schema: Mapping[str, object],
        settings: SynthesisProviderSettings,
    ) -> SynthesisProviderReply:
        started = time.monotonic()
        _verify_requested_settings(settings)
        try:
            validate_provider_schema(response_schema)
        except ValueError:
            raise _failure(
                SynthesisFailureKind.INVALID_RESPONSE,
                "The synthesis output schema is invalid.",
                call_count=0,
                started=started,
            ) from None
        try:
            approved_schema = canonical_json(bundled_response_schema())
        except (OSError, RuntimeError, ValueError):
            raise _failure(
                SynthesisFailureKind.INVALID_RESPONSE,
                "The approved synthesis output schema is unavailable.",
                call_count=0,
                started=started,
            ) from None
        if hashlib.sha256(approved_schema).hexdigest() != _APPROVED_SCHEMA_SHA256:
            raise _failure(
                SynthesisFailureKind.INVALID_RESPONSE,
                "The approved synthesis output schema identity is invalid.",
                call_count=0,
                started=started,
            )
        provider_schema = canonical_json(response_schema)
        if provider_schema != approved_schema:
            raise _failure(
                SynthesisFailureKind.INVALID_RESPONSE,
                "The synthesis output schema identity is invalid.",
                call_count=0,
                started=started,
            )
        if len(payload) > self._maximum_input_bytes:
            raise _failure(
                SynthesisFailureKind.TRANSPORT,
                "The synthesis request exceeds its bounded input limit.",
                call_count=0,
                started=started,
            )
        executable = self._executable_resolver(self._executable)
        if (
            executable is None
            or not Path(executable).is_absolute()
            or Path(executable).suffix.casefold() != ".exe"
        ):
            raise _failure(
                SynthesisFailureKind.TRANSPORT,
                "The native Codex CLI is unavailable.",
                call_count=0,
                started=started,
            )
        with tempfile.TemporaryDirectory(prefix="renpy-story-map-v2-synthesis-") as directory:
            cwd = Path(directory).resolve()
            schema_path = cwd / "story_map_synthesis_v1.schema.json"
            try:
                schema_path.write_bytes(approved_schema)
            except OSError:
                raise _failure(
                    SynthesisFailureKind.TRANSPORT,
                    "The synthesis schema could not be materialized.",
                    call_count=0,
                    started=started,
                ) from None
            command = build_synthesis_command(executable, schema_path)
            spec = ProcessSpec(command=command, cwd=cwd)
            try:
                process = self._process_factory(spec)
            except Exception:
                raise _failure(
                    SynthesisFailureKind.TRANSPORT,
                    "The native Codex CLI could not start.",
                    call_count=0,
                    started=started,
                ) from None
            try:
                stdout, stderr = process.communicate(
                    input=payload,
                    timeout=self._timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                _stop_process(process)
                raise _failure(
                    SynthesisFailureKind.TIMEOUT,
                    "The synthesis request timed out.",
                    call_count=1,
                    started=started,
                ) from None
            except OSError:
                _stop_process(process)
                raise _failure(
                    SynthesisFailureKind.TRANSPORT,
                    "The synthesis transport failed after submission.",
                    call_count=1,
                    started=started,
                ) from None
            finally:
                if process.poll() is None:
                    _stop_process(process)
        if len(stdout) + len(stderr) > self._maximum_output_bytes:
            raise _failure(
                SynthesisFailureKind.INVALID_RESPONSE,
                "The synthesis output exceeded its bounded limit.",
                call_count=1,
                started=started,
            )
        try:
            structured, metadata = _parse_jsonl(stdout, started=started)
        except SynthesisProviderFailure as exc:
            if process.returncode != 0 and not _has_structured_failure_or_action(stdout):
                raise _classify_process_failure(stderr, started=started) from exc
            raise
        if process.returncode != 0:
            raise _classify_process_failure(stderr, started=started)
        _verify_runtime_identity(metadata, started=started)
        if metadata.input_tokens is None or metadata.output_tokens is None:
            raise _failure(
                SynthesisFailureKind.INVALID_RESPONSE,
                "The synthesis usage metadata is invalid.",
                call_count=1,
                started=started,
            )
        return SynthesisProviderReply(
            payload=canonical_json(structured),
            provider=PROVIDER_IDENTITY,
            requested_model=SYNTHESIS_MODEL,
            resolved_model=SYNTHESIS_MODEL,
            reasoning=SYNTHESIS_REASONING,
            fast_mode=SYNTHESIS_FAST_MODE,
            input_tokens=metadata.input_tokens,
            output_tokens=metadata.output_tokens,
            elapsed_ms=_elapsed(started),
        )


class _RuntimeMetadata:
    def __init__(
        self,
        models: set[str],
        reasonings: set[str],
        fast_modes: set[bool],
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> None:
        self.models = frozenset(models)
        self.reasonings = frozenset(reasonings)
        self.fast_modes = frozenset(fast_modes)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


def _verify_requested_settings(settings: SynthesisProviderSettings) -> None:
    if (
        settings.model != SYNTHESIS_MODEL
        or settings.reasoning != SYNTHESIS_REASONING
        or settings.fast_mode is not SYNTHESIS_FAST_MODE
    ):
        raise SynthesisProviderFailure(
            SynthesisFailureKind.IDENTITY,
            "The synthesis provider settings are invalid.",
            call_count=0,
        )


def _parse_jsonl(
    raw: bytes,
    *,
    started: float,
) -> tuple[dict[str, object], _RuntimeMetadata]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise _failure(
            SynthesisFailureKind.INVALID_RESPONSE,
            "The synthesis provider emitted non-UTF-8 output.",
            call_count=1,
            started=started,
        ) from None
    payloads: list[dict[str, object]] = []
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
            raise _failure(
                SynthesisFailureKind.INVALID_RESPONSE,
                "The synthesis provider emitted malformed JSONL.",
                call_count=1,
                started=started,
            ) from None
        if _contains_forbidden_action(event):
            raise _failure(
                SynthesisFailureKind.INVALID_RESPONSE,
                "The synthesis provider attempted a forbidden action.",
                call_count=1,
                started=started,
            )
        if not isinstance(event, dict):
            continue
        _collect_identity(event, models, reasonings, fast_modes, started=started)
        if "usage" in event:
            input_tokens, output_tokens = _parse_usage(event["usage"], started=started)
        metadata = _RuntimeMetadata(
            models,
            reasonings,
            fast_modes,
            input_tokens,
            output_tokens,
        )
        if event.get("type") in {"error", "turn.failed"}:
            _verify_runtime_identity(metadata, started=started)
            raise _classify_structured_failure(event, metadata=metadata, started=started)
        candidate = _extract_payload(event)
        if candidate is not None:
            payloads.append(candidate)
    metadata = _RuntimeMetadata(
        models,
        reasonings,
        fast_modes,
        input_tokens,
        output_tokens,
    )
    if len(payloads) != 1:
        raise _failure(
            SynthesisFailureKind.INVALID_RESPONSE,
            "The synthesis provider returned no unique structured response.",
            call_count=1,
            started=started,
        )
    return payloads[0], metadata


def _collect_identity(
    event: dict[str, object],
    models: set[str],
    reasonings: set[str],
    fast_modes: set[bool],
    *,
    started: float,
) -> None:
    if "model" in event:
        model = event["model"]
        if not isinstance(model, str) or not model:
            raise _identity_failure(started)
        models.add(model)
    for key in ("reasoning_effort", "model_reasoning_effort"):
        if key in event:
            reasoning = event[key]
            if not isinstance(reasoning, str) or not reasoning:
                raise _identity_failure(started)
            reasonings.add(reasoning.casefold())
    if "fast_mode" in event:
        fast_mode = event["fast_mode"]
        if not isinstance(fast_mode, bool):
            raise _identity_failure(started)
        fast_modes.add(fast_mode)


def _verify_runtime_identity(metadata: _RuntimeMetadata, *, started: float) -> None:
    if metadata.models and metadata.models != frozenset({SYNTHESIS_MODEL}):
        raise _identity_failure(started)
    if metadata.reasonings and metadata.reasonings != frozenset({SYNTHESIS_REASONING}):
        raise _identity_failure(started)
    if metadata.fast_modes and metadata.fast_modes != frozenset({SYNTHESIS_FAST_MODE}):
        raise _identity_failure(started)


def _identity_failure(started: float) -> SynthesisProviderFailure:
    return _failure(
        SynthesisFailureKind.IDENTITY,
        "The provider identity could not be verified.",
        call_count=1,
        started=started,
    )


def _parse_usage(value: object, *, started: float) -> tuple[int, int]:
    if not isinstance(value, dict) or not {
        "input_tokens",
        "output_tokens",
    } <= set(value):
        raise _failure(
            SynthesisFailureKind.INVALID_RESPONSE,
            "The synthesis usage metadata is invalid.",
            call_count=1,
            started=started,
        )
    result: list[int] = []
    for key in ("input_tokens", "output_tokens"):
        item = value[key]
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise _failure(
                SynthesisFailureKind.INVALID_RESPONSE,
                "The synthesis usage metadata is invalid.",
                call_count=1,
                started=started,
            )
        result.append(item)
    return result[0], result[1]


def _extract_payload(event: dict[str, object]) -> dict[str, object] | None:
    if _is_synthesis_payload(event):
        return event
    item = event.get("item")
    if isinstance(item, dict) and item.get("type") == "agent_message":
        text = item.get("text")
        if isinstance(text, str):
            try:
                parsed: object = json.loads(text)
            except json.JSONDecodeError:
                return None
            return cast(dict[str, object], parsed) if _is_synthesis_payload(parsed) else None
    response = event.get("response")
    return cast(dict[str, object], response) if _is_synthesis_payload(response) else None


def _is_synthesis_payload(value: object) -> bool:
    return isinstance(value, dict) and set(value) == {
        "story_title",
        "story_overview",
        "ordered_sections",
        "optional_threads",
    }


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


def _classify_structured_failure(
    value: dict[str, object],
    *,
    metadata: _RuntimeMetadata,
    started: float,
) -> SynthesisProviderFailure:
    category = _sanitization_category(value)
    kind = (
        SynthesisFailureKind.REFUSED
        if any(
            marker in category
            for marker in (
                "content_filter",
                "content policy violation",
                "content_policy_violation",
                "safety refusal",
                "safety_policy_violation",
            )
        )
        else SynthesisFailureKind.TRANSPORT
    )
    reason = (
        "The provider refused the synthesis request."
        if kind is SynthesisFailureKind.REFUSED
        else "The synthesis provider reported a failure."
    )
    return _failure(
        kind,
        reason,
        call_count=1,
        started=started,
        input_tokens=metadata.input_tokens,
        output_tokens=metadata.output_tokens,
    )


def _classify_process_failure(raw: bytes, *, started: float) -> SynthesisProviderFailure:
    category = raw.decode("utf-8", errors="ignore").casefold()
    if any(
        marker in category
        for marker in (
            "output schema is invalid",
            "output schema rejected",
            "invalid output schema",
            "unsupported output schema",
            "invalid_json_schema",
            "json schema is invalid",
            "json schema rejected",
        )
    ):
        return _failure(
            SynthesisFailureKind.INVALID_RESPONSE,
            "The synthesis output schema was rejected.",
            call_count=1,
            started=started,
        )
    if any(
        marker in category
        for marker in (
            "model_reasoning_effort",
            "fast_mode",
            "configuration error",
            "invalid configuration",
            "unknown config key",
            "unsupported config",
            "unknown model",
            "unsupported model",
        )
    ):
        return _identity_failure(started)
    if any(marker in category for marker in ("timed out", "timeout")):
        return _failure(
            SynthesisFailureKind.TIMEOUT,
            "The synthesis request timed out.",
            call_count=1,
            started=started,
        )
    return _failure(
        SynthesisFailureKind.TRANSPORT,
        "The synthesis provider process failed.",
        call_count=1,
        started=started,
    )


def _sanitization_category(value: object) -> str:
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


def _has_structured_failure_or_action(raw: bytes) -> bool:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return False
    for line in lines:
        try:
            event: object = json.loads(line)
        except json.JSONDecodeError:
            continue
        if _contains_forbidden_action(event):
            return True
        if isinstance(event, dict) and event.get("type") in {"error", "turn.failed"}:
            return True
    return False


def _failure(
    kind: SynthesisFailureKind,
    reason: str,
    *,
    call_count: int,
    started: float,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> SynthesisProviderFailure:
    return SynthesisProviderFailure(
        kind,
        reason,
        call_count=call_count,
        provider=PROVIDER_IDENTITY if call_count else None,
        resolved_model=SYNTHESIS_MODEL if call_count else None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        elapsed_ms=_elapsed(started),
    )


def _elapsed(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1_000))


def _stop_process(process: Process) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=0.5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=0.1)
        except (OSError, subprocess.TimeoutExpired):
            pass


__all__ = [
    "CodexCliSynthesisProvider",
    "ProcessSpec",
    "build_synthesis_command",
]
