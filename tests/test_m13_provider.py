from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import QProcess

from renpy_story_mapper.narrative.contracts import JsonValue, ProviderSettings
from renpy_story_mapper.narrative.provider import (
    ADAPTER_NAME,
    ADAPTER_VERSION,
    PROMPT_TEMPLATE_VERSION,
    RESPONSE_SCHEMA_VERSION,
    CodexCliNarrativeProvider,
    NarrativeProviderError,
    ProviderBatchItem,
    ProviderCancelledError,
    ProviderIdentityMismatchError,
    ProviderLimitError,
    ProviderOutputError,
    ProviderPolicyViolationError,
    ProviderRateLimitError,
    ProviderRequest,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from renpy_story_mapper.organization.sterile_runner import (
    SterileCodexRunner,
    SterileRunnerError,
    SterileRunRequest,
    SterileRunResult,
    build_sterile_codex_command,
)


def _item(identifier: str = "logical-scene-a") -> ProviderBatchItem:
    return ProviderBatchItem(
        logical_job_id=identifier,
        input_revision_id=f"revision-{identifier}",
        payload={
            "job_kind": "scene",
            "authority_binding": {"m11_scene_id": identifier},
            "evidence_handles": [{"handle": "E1", "record": "evidence-a"}],
        },
    )


def _request(
    *items: ProviderBatchItem,
    model: str = "runtime-model-a",
    settings: ProviderSettings | None = None,
    maximum_input_bytes: int = 512_000,
) -> ProviderRequest:
    return ProviderRequest(
        request_id="request-a",
        consent_manifest_id="consent-a",
        requested_model=model,
        settings=settings or ProviderSettings(),
        items=items or (_item(),),
        timeout_seconds=2.0,
        maximum_input_bytes=maximum_input_bytes,
    )


def _events(
    payload: object,
    *,
    model: str = "runtime-model-a",
    input_tokens: object = 100,
    output_tokens: object = 20,
    cost_micros: object = 7,
) -> tuple[object, ...]:
    return (
        {"type": "thread.started", "model": model},
        {
            "type": "turn.completed",
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_micros": cost_micros,
            },
        },
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": json.dumps(payload)},
        },
    )


class FakeRunner:
    def __init__(
        self,
        result: SterileRunResult | None = None,
        *,
        error: SterileRunnerError | None = None,
        available: bool = True,
    ) -> None:
        self.result = result
        self.error = error
        self.available = available
        self.requests: list[SterileRunRequest] = []
        self.schema_text = ""
        self.cancelled = False

    def status(self) -> tuple[str | None, str | None]:
        if self.available:
            return "C:/synthetic/codex.exe", "codex-cli synthetic"
        return None, None

    def execute(
        self,
        request: SterileRunRequest,
        cancelled: object,
    ) -> SterileRunResult:
        del cancelled
        self.requests.append(request)
        self.schema_text = request.schema_path.read_text(encoding="utf-8")
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result

    def cancel(self) -> None:
        self.cancelled = True


class FakeProcess:
    def __init__(
        self,
        output: bytes,
        *,
        exit_code: int = 0,
        stderr: bytes = b"",
        never_finishes: bool = False,
        ignore_terminate: bool = False,
        write_result: int | None = None,
    ) -> None:
        self.output = output
        self.stderr = stderr
        self.exit_code = exit_code
        self.never_finishes = never_finishes
        self.ignore_terminate = ignore_terminate
        self.write_result = write_result
        self.started: tuple[str, list[str]] | None = None
        self.cwd = ""
        self.stdin = b""
        self.read = False
        self.terminated = False
        self.killed = False
        self.wait_arguments: list[int] = []

    def setWorkingDirectory(self, directory: str) -> None:
        self.cwd = directory

    def start(self, program: str, arguments: list[str]) -> None:
        self.started = program, arguments

    def waitForStarted(self, msecs: int = 30000) -> bool:
        del msecs
        return True

    def write(self, data: bytes) -> int:
        amount = len(data) if self.write_result is None else self.write_result
        if amount > 0:
            self.stdin += data[:amount]
        return amount

    def closeWriteChannel(self) -> None:
        pass

    def waitForFinished(self, msecs: int = 30000) -> bool:
        self.wait_arguments.append(msecs)
        stopped = self.terminated and not self.ignore_terminate
        return not self.never_finishes or stopped or self.killed

    def readAllStandardOutput(self) -> bytes:
        if self.read:
            return b""
        self.read = True
        return self.output

    def readAllStandardError(self) -> bytes:
        return self.stderr

    def exitCode(self) -> int:
        return self.exit_code

    def state(self) -> QProcess.ProcessState:
        if self.terminated or self.killed:
            return QProcess.ProcessState.NotRunning
        return QProcess.ProcessState.Running

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


def _jsonl(*events: object) -> bytes:
    return b"".join((json.dumps(event) + "\n").encode("utf-8") for event in events)


def test_cloud_adapter_sends_one_structured_batch_and_records_runtime_identity() -> None:
    output = {
        "items": [
            {
                "logical_job_id": "logical-scene-a",
                "status": "ok",
                "payload": {"title": "A", "claims": []},
                "error_code": None,
            },
            {
                "logical_job_id": "logical-scene-b",
                "status": "ok",
                "payload": {"title": "B", "claims": []},
                "error_code": None,
            },
        ]
    }
    runner = FakeRunner(SterileRunResult(_events(output), "codex-cli synthetic"))
    provider = CodexCliNarrativeProvider(runner=runner)

    response = provider.submit(_request(_item(), _item("logical-scene-b")), lambda: False)

    assert response.provider.provider == "openai"
    assert response.provider.adapter == ADAPTER_NAME
    assert response.provider.adapter_version == ADAPTER_VERSION
    assert response.provider.requested_model == "runtime-model-a"
    assert response.provider.resolved_model == "runtime-model-a"
    assert response.prompt_template_version == PROMPT_TEMPLATE_VERSION
    assert response.response_schema_version == RESPONSE_SCHEMA_VERSION
    assert response.usage.input_tokens == 100
    assert response.usage.output_tokens == 20
    assert response.usage.cost_micros == 7
    assert response.usage.provider_calls == 1
    assert [item.logical_job_id for item in response.items] == [
        "logical-scene-a",
        "logical-scene-b",
    ]
    assert len(runner.requests) == 1
    envelope = json.loads(runner.requests[0].stdin)
    assert envelope["template_version"] == PROMPT_TEMPLATE_VERSION
    assert envelope["request"]["consent_manifest_id"] == "consent-a"
    assert [
        item["logical_job_id"] for item in envelope["request"]["logical_jobs"]
    ] == ["logical-scene-a", "logical-scene-b"]
    assert "Never merge jobs" in envelope["instruction"]
    assert envelope["successful_item_payload"]["exact_keys"] == [
        "logical_job_id",
        "title",
        "summary",
        "claims",
    ]
    assert envelope["successful_item_payload"]["claims"]["exact_keys"] == [
        "claim_class",
        "context_scope",
        "text",
        "evidence_handles",
        "child_claim_handles",
        "subject",
        "predicate",
        "polarity",
        "normalized_value",
    ]
    assert "Scene claims use E handles" in envelope["evidence"]
    assert "hierarchy claims use C handles" in envelope["evidence"]
    assert "Never present comparison contexts as one chronology" in envelope["context_scope"]
    assert "must copy that one claim's text" in envelope["m12_exactness"]
    assert "must use claim_class interpretive" in envelope["m12_exactness"]
    assert envelope["targeted_repair_payload"]["exact_keys"] == [
        "logical_job_id",
        "title",
        "summary",
        "claims",
    ]
    assert "runtime-model-a" not in runner.schema_text
    assert RESPONSE_SCHEMA_VERSION in runner.schema_text
    schema = json.loads(runner.schema_text)
    assert schema["properties"]["items"]["maxItems"] == 64
    assert schema["$defs"]["artifact_payload"]["required"] == [
        "logical_job_id",
        "title",
        "summary",
        "claims",
    ]
    assert "ordinal" in schema["$defs"]["replacement_claim"]["required"]
    assert "context_scope" in schema["$defs"]["claim"]["required"]
    assert "raw" not in response.__dict__


def test_output_items_are_salvaged_and_refusals_remain_item_local() -> None:
    payload = {
        "items": [
            {
                "logical_job_id": "logical-scene-a",
                "status": "ok",
                "payload": {"summary": "Valid"},
                "error_code": None,
            },
            {"status": "ok", "payload": None, "error_code": None},
            {
                "logical_job_id": "logical-scene-b",
                "status": "content_refusal",
                "payload": None,
                "error_code": "content_refusal",
            },
            "malformed",
        ]
    }
    provider = CodexCliNarrativeProvider(
        runner=FakeRunner(SterileRunResult(_events(payload), None))
    )

    response = provider.submit(_request(_item(), _item("logical-scene-b")), lambda: False)

    assert response.items[0].succeeded
    assert response.items[0].payload == {"summary": "Valid"}
    assert response.items[1].logical_job_id is None
    assert response.items[1].error_code == "malformed_provider_item"
    assert response.items[2].logical_job_id == "logical-scene-b"
    assert response.items[2].error_code == "content_refusal"
    assert response.items[3].error_code == "malformed_provider_item"


def test_adapter_rejects_model_fallback_missing_usage_and_ambiguous_output() -> None:
    output = {"items": []}
    mismatched = CodexCliNarrativeProvider(
        runner=FakeRunner(
            SterileRunResult(_events(output, model="different-runtime-model"), None)
        )
    )
    with pytest.raises(ProviderIdentityMismatchError) as mismatch:
        mismatched.submit(_request(), lambda: False)
    assert mismatch.value.error_code == "model_mismatch"
    assert not mismatch.value.transient

    no_usage_events = tuple(
        event
        for event in _events(output)
        if not (isinstance(event, dict) and "usage" in event)
    )
    missing_usage = CodexCliNarrativeProvider(
        runner=FakeRunner(SterileRunResult(no_usage_events, None))
    )
    with pytest.raises(ProviderOutputError, match="token usage") as usage:
        missing_usage.submit(_request(), lambda: False)
    assert usage.value.error_code == "usage_metadata_missing"

    ambiguous = CodexCliNarrativeProvider(
        runner=FakeRunner(
            SterileRunResult(
                (
                    *_events(output),
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": json.dumps(output)},
                    },
                ),
                None,
            )
        )
    )
    with pytest.raises(ProviderOutputError) as envelope:
        ambiguous.submit(_request(), lambda: False)
    assert envelope.value.error_code == "response_envelope_invalid"


def test_adapter_enforces_consent_binding_input_limits_and_supported_settings() -> None:
    output = {"items": []}
    runner = FakeRunner(SterileRunResult(_events(output), None))
    provider = CodexCliNarrativeProvider(runner=runner)

    with pytest.raises(ValueError, match="consent manifest"):
        _request().__class__(
            request_id="request-a",
            consent_manifest_id="",
            requested_model="runtime-model-a",
            settings=ProviderSettings(),
            items=(_item(),),
            timeout_seconds=1.0,
        )
    with pytest.raises(ProviderLimitError) as settings_error:
        provider.submit(
            _request(settings=ProviderSettings(values=(("temperature", 0.2),))),
            lambda: False,
        )
    assert settings_error.value.error_code == "unsupported_settings"
    with pytest.raises(ProviderLimitError) as input_error:
        provider.submit(_request(maximum_input_bytes=100), lambda: False)
    assert input_error.value.error_code == "input_limit"
    assert not runner.requests


def test_adapter_cancellation_and_status_do_not_transmit() -> None:
    runner = FakeRunner(SterileRunResult(_events({"items": []}), None), available=False)
    provider = CodexCliNarrativeProvider(runner=runner)
    assert not provider.status().available
    assert provider.status().message_code == "provider_unavailable"
    with pytest.raises(ProviderCancelledError):
        provider.submit(_request(), lambda: True)
    assert not runner.requests
    provider.cancel()
    assert runner.cancelled


@pytest.mark.parametrize(
    ("runner_code", "exception_type", "transient"),
    [
        ("rate_limited", ProviderRateLimitError, True),
        ("timeout", ProviderTimeoutError, True),
        ("policy_violation", ProviderPolicyViolationError, False),
        ("provider_failure", ProviderUnavailableError, True),
        ("output_limit", ProviderLimitError, False),
    ],
)
def test_runner_failures_map_to_sanitized_retry_signals(
    runner_code: str,
    exception_type: type[NarrativeProviderError],
    transient: bool,
) -> None:
    runner = FakeRunner(
        error=SterileRunnerError(runner_code, "sanitized", transient=transient)
    )
    provider = CodexCliNarrativeProvider(runner=runner)
    with pytest.raises(exception_type) as exc_info:
        provider.submit(_request(), lambda: False)
    error = cast(NarrativeProviderError, exc_info.value)
    assert error.error_code == runner_code
    assert error.transient is transient
    assert "SECRET-STORY" not in str(exc_info.value)


def test_direct_command_has_no_shell_session_fallback_or_fixed_reasoning() -> None:
    program, arguments = build_sterile_codex_command(
        "C:/synthetic/codex.exe",
        model="runtime-model-b",
        schema_path=Path("schema.json"),
    )
    assert program == "C:/synthetic/codex.exe"
    assert arguments[:2] == ["exec", "--ephemeral"]
    assert arguments[-1] == "-"
    assert arguments[arguments.index("--model") + 1] == "runtime-model-b"
    assert arguments[arguments.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in arguments
    assert "--ignore-rules" in arguments
    assert "--strict-config" in arguments
    assert 'web_search="disabled"' in arguments
    assert "shell_tool" in arguments
    assert "apps" in arguments
    assert "plugins" in arguments
    assert "model_reasoning_effort" not in " ".join(arguments)


def test_sterile_runner_uses_temp_cwd_structured_stdin_and_schema(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    process = FakeProcess(_jsonl({"type": "turn.completed", "model": "runtime-model-a"}))
    runner = SterileCodexRunner(
        process_factory=lambda: process,
        executable_resolver=lambda _command: (
            "C:/synthetic/codex.exe",
            "codex-cli synthetic",
        ),
    )
    stdin = json.dumps({"request": {"logical_jobs": [{"logical_job_id": "a"}]}}).encode()

    result = runner.execute(
        SterileRunRequest(
            model="runtime-model-a",
            schema_path=schema.resolve(),
            stdin=stdin,
            timeout_seconds=1.0,
            maximum_output_bytes=100_000,
        ),
        lambda: False,
    )

    assert result.cli_version == "codex-cli synthetic"
    assert process.stdin == stdin
    assert process.started is not None
    assert process.started[0] == "C:/synthetic/codex.exe"
    assert process.started[1][-1] == "-"
    assert process.started[1][process.started[1].index("--output-schema") + 1] == str(
        schema.resolve()
    )
    assert process.cwd
    assert not Path(process.cwd).exists()


def test_sterile_runner_rejects_policy_events_and_sanitizes_stderr(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    policy_process = FakeProcess(_jsonl({"type": "mcp_tool_call"}))
    policy_runner = SterileCodexRunner(
        process_factory=lambda: policy_process,
        executable_resolver=lambda _command: ("C:/synthetic/codex.exe", None),
    )
    request = SterileRunRequest(
        model="runtime-model-a",
        schema_path=schema.resolve(),
        stdin=b"{}",
        timeout_seconds=1.0,
        maximum_output_bytes=100_000,
    )
    with pytest.raises(SterileRunnerError) as policy_error:
        policy_runner.execute(request, lambda: False)
    assert policy_error.value.error_code == "policy_violation"
    assert policy_process.terminated

    failure_process = FakeProcess(
        b"",
        exit_code=1,
        stderr=b"429 rate limit SECRET-STORY source text",
    )
    failure_runner = SterileCodexRunner(
        process_factory=lambda: failure_process,
        executable_resolver=lambda _command: ("C:/synthetic/codex.exe", None),
    )
    with pytest.raises(SterileRunnerError) as failure:
        failure_runner.execute(request, lambda: False)
    assert failure.value.error_code == "rate_limited"
    assert failure.value.transient
    assert "SECRET-STORY" not in str(failure.value)


def test_sterile_runner_cancellation_kills_uncooperative_process(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    process = FakeProcess(b"", never_finishes=True, ignore_terminate=True)
    runner = SterileCodexRunner(
        process_factory=lambda: process,
        executable_resolver=lambda _command: ("C:/synthetic/codex.exe", None),
    )
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 4

    with pytest.raises(SterileRunnerError) as error:
        runner.execute(
            SterileRunRequest(
                model="runtime-model-a",
                schema_path=schema.resolve(),
                stdin=b"{}",
                timeout_seconds=1.0,
                maximum_output_bytes=100_000,
            ),
            cancelled,
        )
    assert error.value.error_code == "cancelled"
    assert process.terminated
    assert process.killed
    assert 500 in process.wait_arguments
    assert 100 in process.wait_arguments
    assert not Path(process.cwd).exists()


def test_provider_contracts_reject_duplicate_jobs_and_non_json_payloads() -> None:
    with pytest.raises(ValueError, match="repeat"):
        _request(_item(), _item())
    with pytest.raises(ValueError, match="JSON values"):
        ProviderBatchItem(
            logical_job_id="logical-scene-a",
            input_revision_id="revision-a",
            payload=cast(dict[str, JsonValue], {"bad": object()}),
        )
