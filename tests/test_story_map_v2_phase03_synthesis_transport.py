from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from renpy_story_mapper.story_map_v2 import synthesis_transport
from renpy_story_mapper.story_map_v2.contracts import canonical_json
from renpy_story_mapper.story_map_v2.phase03_contracts import SynthesisFailureKind
from renpy_story_mapper.story_map_v2.synthesis import (
    SynthesisProviderFailure,
    build_synthesis_preview,
    build_synthesis_request,
    execute_synthesis,
    response_schema,
    serialize_synthesis_request,
    validate_provider_schema,
)
from renpy_story_mapper.story_map_v2.synthesis_transport import (
    CodexCliSynthesisProvider,
    ProcessSpec,
    build_synthesis_command,
)
from test_story_map_v2_phase03_track_a import (
    project_identity,
    synthetic_core,
    valid_response,
)


def _jsonl(*events: object) -> bytes:
    return b"".join(
        json.dumps(event, separators=(",", ":")).encode("utf-8") + b"\n"
        for event in events
    )


class FakeProcess:
    def __init__(self, stdout: bytes, *, stderr: bytes = b"", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.final_returncode = returncode
        self.returncode: int | None = None
        self.stdin: bytes | None = None
        self.communications = 0
        self.terminated = False
        self.killed = False

    def communicate(
        self,
        input: bytes | None = None,
        timeout: float | None = None,
    ) -> tuple[bytes, bytes]:
        self.communications += 1
        self.stdin = input
        self.returncode = self.final_returncode
        return self.stdout, self.stderr

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake", timeout)
        return self.returncode


class TimeoutProcess(FakeProcess):
    def communicate(
        self,
        input: bytes | None = None,
        timeout: float | None = None,
    ) -> tuple[bytes, bytes]:
        self.communications += 1
        self.stdin = input
        raise subprocess.TimeoutExpired("fake", timeout)


def _response_text() -> str:
    core = synthetic_core()
    return valid_response(tuple(event.anchor.id for event in core.chunks[0].events))


def _success_output(
    *,
    model: str = "gpt-5.6-terra",
    reasoning: str = "high",
    fast_mode: bool = False,
    include_identity: bool = True,
    usage: object = None,
) -> bytes:
    completed: dict[str, object] = {"type": "turn.completed"}
    if include_identity:
        completed.update(
            {
                "model": model,
                "reasoning_effort": reasoning,
                "fast_mode": fast_mode,
            }
        )
    completed["usage"] = (
        {"input_tokens": 120, "output_tokens": 40} if usage is None else usage
    )
    return _jsonl(
        {"type": "thread.started"},
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": _response_text()},
        },
        completed,
    )


def _provider(
    tmp_path: Path,
    process: FakeProcess,
    *,
    specs: list[ProcessSpec] | None = None,
) -> CodexCliSynthesisProvider:
    def factory(spec: ProcessSpec) -> FakeProcess:
        if specs is not None:
            specs.append(spec)
        assert spec.cwd.is_dir()
        files = list(spec.cwd.iterdir())
        assert len(files) == 1
        assert files[0].name == "story_map_synthesis_v1.schema.json"
        assert files[0].read_bytes() == canonical_json(response_schema())
        assert spec.command[spec.command.index("--output-schema") + 1] == str(files[0])
        return process

    return CodexCliSynthesisProvider(
        process_factory=factory,
        executable_resolver=lambda _value: str((tmp_path / "codex.exe").resolve()),
        timeout_seconds=0.25,
    )


def _request_and_preview():
    core = synthetic_core()
    request = build_synthesis_request(core, project_identity(core))
    return request, build_synthesis_preview(request)


def test_provider_schema_uses_only_supported_recursive_strict_subset() -> None:
    schema = response_schema()
    validate_provider_schema(schema)
    serialized = json.dumps(schema, sort_keys=True)
    assert "uniqueItems" not in serialized

    unsupported = json.loads(serialized)
    unsupported["$defs"]["anchors"]["uniqueItems"] = True
    with pytest.raises(ValueError, match="unsupported"):
        validate_provider_schema(unsupported)

    incomplete = json.loads(serialized)
    incomplete["required"].remove("story_title")
    with pytest.raises(ValueError, match="required"):
        validate_provider_schema(incomplete)


def test_command_is_exact_direct_terra_high_fast_off(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    command = build_synthesis_command("C:/synthetic/codex.exe", schema.resolve())

    disabled = (
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
    expected = [
        "C:/synthetic/codex.exe",
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
    ]
    for feature in disabled:
        expected.extend(("--disable", feature))
    expected.extend(
        (
        "-c",
        'model_reasoning_effort="high"',
        "-c",
        "fast_mode=false",
        "-c",
        'web_search="disabled"',
        "-c",
        "analytics.enabled=false",
        "--json",
        "--output-schema",
        str(schema.resolve()),
        "--model",
        "gpt-5.6-terra",
        "-",
        )
    )
    assert command == tuple(expected)


def test_success_uses_one_process_exact_stdin_isolated_cwd_and_sanitized_provenance(
    tmp_path: Path,
) -> None:
    process = FakeProcess(_success_output())
    specs: list[ProcessSpec] = []
    provider = _provider(tmp_path, process, specs=specs)
    request, preview = _request_and_preview()
    payload = serialize_synthesis_request(request)

    reply = provider.synthesize(
        payload,
        response_schema=response_schema(),
        settings=preview.settings,
    )

    assert len(specs) == process.communications == 1
    assert specs[0].shell is False
    assert not specs[0].cwd.exists()
    assert process.stdin == payload
    assert b"story/chapter.rpy" not in process.stdin
    assert all("Chapter moment" not in argument for argument in specs[0].command)
    assert reply.requested_model == reply.resolved_model == "gpt-5.6-terra"
    assert reply.reasoning == "high"
    assert reply.fast_mode is False
    assert reply.input_tokens == 120
    assert reply.output_tokens == 40
    assert json.loads(reply.payload) == json.loads(_response_text())


def test_missing_redundant_identity_uses_validated_explicit_cli_selection(
    tmp_path: Path,
) -> None:
    process = FakeProcess(_success_output(include_identity=False))
    provider = _provider(tmp_path, process)
    request, preview = _request_and_preview()

    reply = provider.synthesize(
        serialize_synthesis_request(request),
        response_schema=response_schema(),
        settings=preview.settings,
    )

    assert reply.resolved_model == "gpt-5.6-terra"
    assert reply.reasoning == "high"
    assert reply.fast_mode is False


@pytest.mark.parametrize(
    "output",
    (
        _success_output(model="gpt-5.6-sol"),
        _success_output(reasoning="medium"),
        _success_output(fast_mode=True),
        _jsonl(
            {"model": "gpt-5.6-terra"},
            {"model": "gpt-5.6-sol"},
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": _response_text()},
            },
            {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
        ),
        _jsonl(
            {"model": None},
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": _response_text()},
            },
            {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
        ),
    ),
)
def test_different_conflicting_or_malformed_identity_fails_closed(
    tmp_path: Path,
    output: bytes,
) -> None:
    provider = _provider(tmp_path, FakeProcess(output))
    request, preview = _request_and_preview()

    with pytest.raises(SynthesisProviderFailure) as failure:
        provider.synthesize(
            serialize_synthesis_request(request),
            response_schema=response_schema(),
            settings=preview.settings,
        )

    assert failure.value.kind is SynthesisFailureKind.IDENTITY
    assert failure.value.call_count == 1


@pytest.mark.parametrize(
    "usage",
    (
        {},
        {"input_tokens": -1, "output_tokens": 1},
        {"input_tokens": 1, "output_tokens": "many"},
    ),
)
def test_missing_or_invalid_usage_fails_closed(tmp_path: Path, usage: object) -> None:
    provider = _provider(tmp_path, FakeProcess(_success_output(usage=usage)))
    request, preview = _request_and_preview()
    with pytest.raises(SynthesisProviderFailure) as failure:
        provider.synthesize(
            serialize_synthesis_request(request),
            response_schema=response_schema(),
            settings=preview.settings,
        )
    assert failure.value.kind is SynthesisFailureKind.INVALID_RESPONSE


def test_refusal_forbidden_action_malformed_json_and_timeout_are_sanitized(
    tmp_path: Path,
) -> None:
    cases = (
        (
            FakeProcess(
                _jsonl(
                    {
                        "type": "turn.failed",
                        "error": {
                            "code": "content_policy_violation",
                            "message": "PRIVATE-STORY refusal detail",
                        },
                    }
                )
            ),
            SynthesisFailureKind.REFUSED,
        ),
        (
            FakeProcess(
                _jsonl(
                    {
                        "type": "item.completed",
                        "item": {"type": "command_execution", "command": "PRIVATE-STORY"},
                    }
                )
            ),
            SynthesisFailureKind.INVALID_RESPONSE,
        ),
        (FakeProcess(b"not-json PRIVATE-STORY\n"), SynthesisFailureKind.INVALID_RESPONSE),
        (TimeoutProcess(b""), SynthesisFailureKind.TIMEOUT),
    )
    for process, kind in cases:
        provider = _provider(tmp_path, process)
        request, preview = _request_and_preview()
        with pytest.raises(SynthesisProviderFailure) as failure:
            provider.synthesize(
                serialize_synthesis_request(request),
                response_schema=response_schema(),
                settings=preview.settings,
            )
        assert failure.value.kind is kind
        assert failure.value.call_count == 1
        assert "PRIVATE-STORY" not in str(failure.value)
    assert cases[-1][0].terminated


def test_schema_rejection_start_failure_and_nonzero_transport_are_classified_once(
    tmp_path: Path,
) -> None:
    request, preview = _request_and_preview()
    payload = serialize_synthesis_request(request)

    starts = 0

    def fail_start(spec: ProcessSpec):
        nonlocal starts
        starts += 1
        raise OSError("PRIVATE-STORY start detail")

    start_provider = CodexCliSynthesisProvider(
        process_factory=fail_start,
        executable_resolver=lambda _value: str((tmp_path / "codex.exe").resolve()),
    )
    with pytest.raises(SynthesisProviderFailure) as start:
        start_provider.synthesize(
            payload,
            response_schema=response_schema(),
            settings=preview.settings,
        )
    assert starts == 1
    assert start.value.kind is SynthesisFailureKind.TRANSPORT
    assert start.value.call_count == 0

    schema_process = FakeProcess(
        b"",
        stderr=b"output schema rejected PRIVATE-STORY",
        returncode=1,
    )
    schema_provider = _provider(tmp_path, schema_process)
    with pytest.raises(SynthesisProviderFailure) as schema:
        schema_provider.synthesize(
            payload,
            response_schema=response_schema(),
            settings=preview.settings,
        )
    assert schema.value.kind is SynthesisFailureKind.INVALID_RESPONSE
    assert schema.value.call_count == 1

    transport_process = FakeProcess(b"", stderr=b"PRIVATE-STORY process failed", returncode=1)
    transport_provider = _provider(tmp_path, transport_process)
    with pytest.raises(SynthesisProviderFailure) as transport:
        transport_provider.synthesize(
            payload,
            response_schema=response_schema(),
            settings=preview.settings,
        )
    assert transport.value.kind is SynthesisFailureKind.TRANSPORT
    assert transport.value.call_count == 1


def test_preflight_and_process_io_are_bounded_without_hidden_processes(
    tmp_path: Path,
) -> None:
    request, preview = _request_and_preview()
    payload = serialize_synthesis_request(request)
    starts = 0

    def factory(spec: ProcessSpec) -> FakeProcess:
        nonlocal starts
        starts += 1
        return FakeProcess(_success_output())

    invalid_schema = response_schema()
    invalid_schema["$id"] = "foreign-schema"
    provider = CodexCliSynthesisProvider(
        process_factory=factory,
        executable_resolver=lambda _value: str((tmp_path / "codex.exe").resolve()),
    )
    with pytest.raises(SynthesisProviderFailure) as schema:
        provider.synthesize(
            payload,
            response_schema=invalid_schema,
            settings=preview.settings,
        )
    assert schema.value.kind is SynthesisFailureKind.INVALID_RESPONSE
    assert schema.value.call_count == starts == 0

    input_provider = CodexCliSynthesisProvider(
        process_factory=factory,
        executable_resolver=lambda _value: str((tmp_path / "codex.exe").resolve()),
        maximum_input_bytes=1,
    )
    with pytest.raises(SynthesisProviderFailure) as input_limit:
        input_provider.synthesize(
            payload,
            response_schema=response_schema(),
            settings=preview.settings,
        )
    assert input_limit.value.call_count == starts == 0

    output_provider = CodexCliSynthesisProvider(
        process_factory=factory,
        executable_resolver=lambda _value: str((tmp_path / "codex.exe").resolve()),
        maximum_output_bytes=1,
    )
    with pytest.raises(SynthesisProviderFailure) as output_limit:
        output_provider.synthesize(
            payload,
            response_schema=response_schema(),
            settings=preview.settings,
        )
    assert output_limit.value.kind is SynthesisFailureKind.INVALID_RESPONSE
    assert output_limit.value.call_count == starts == 1


def test_foreign_configured_schema_file_fails_before_process_construction(
    tmp_path: Path,
) -> None:
    foreign_schema = tmp_path / "foreign.schema.json"
    foreign_schema.write_text("{}", encoding="utf-8")
    starts = 0

    def factory(spec: ProcessSpec) -> FakeProcess:
        nonlocal starts
        starts += 1
        return FakeProcess(_success_output())

    with pytest.raises(TypeError, match="schema_path"):
        CodexCliSynthesisProvider(
            schema_path=foreign_schema,  # type: ignore[call-arg]
            process_factory=factory,
            executable_resolver=lambda _value: str((tmp_path / "codex.exe").resolve()),
        )
    assert starts == 0


def test_semantically_stale_bundled_schema_fails_before_process_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale_schema = json.loads(json.dumps(response_schema()))
    properties = stale_schema["properties"]
    assert isinstance(properties, dict)
    story_title = properties["story_title"]
    assert isinstance(story_title, dict)
    story_title["maxLength"] = 159
    monkeypatch.setattr(synthesis_transport, "bundled_response_schema", lambda: stale_schema)
    starts = 0

    def factory(spec: ProcessSpec) -> FakeProcess:
        nonlocal starts
        starts += 1
        return FakeProcess(_success_output())

    provider = CodexCliSynthesisProvider(
        process_factory=factory,
        executable_resolver=lambda _value: str((tmp_path / "codex.exe").resolve()),
    )
    request, preview = _request_and_preview()
    with pytest.raises(SynthesisProviderFailure) as failure:
        provider.synthesize(
            serialize_synthesis_request(request),
            response_schema=stale_schema,
            settings=preview.settings,
        )

    assert failure.value.kind is SynthesisFailureKind.INVALID_RESPONSE
    assert failure.value.call_count == starts == 0


def test_relative_or_non_native_executable_resolution_fails_before_process_start(
    tmp_path: Path,
) -> None:
    request, preview = _request_and_preview()
    starts = 0

    def factory(spec: ProcessSpec) -> FakeProcess:
        nonlocal starts
        starts += 1
        return FakeProcess(_success_output())

    for resolved in ("codex.exe", str((tmp_path / "codex.cmd").resolve())):
        provider = CodexCliSynthesisProvider(
            process_factory=factory,
            executable_resolver=lambda _value, selected=resolved: selected,
        )
        with pytest.raises(SynthesisProviderFailure) as failure:
            provider.synthesize(
                serialize_synthesis_request(request),
                response_schema=response_schema(),
                settings=preview.settings,
            )
        assert failure.value.kind is SynthesisFailureKind.TRANSPORT
        assert failure.value.call_count == 0
    assert starts == 0


def test_structured_non_refusal_failure_is_sanitized_and_not_overridden(
    tmp_path: Path,
) -> None:
    process = FakeProcess(
        _jsonl(
            {
                "type": "turn.failed",
                "error": {"code": "server_error", "message": "PRIVATE-STORY detail"},
            }
        ),
        stderr=b"output schema rejected PRIVATE-STORY",
        returncode=1,
    )
    provider = _provider(tmp_path, process)
    request, preview = _request_and_preview()
    with pytest.raises(SynthesisProviderFailure) as failure:
        provider.synthesize(
            serialize_synthesis_request(request),
            response_schema=response_schema(),
            settings=preview.settings,
        )
    assert failure.value.kind is SynthesisFailureKind.TRANSPORT
    assert failure.value.call_count == 1
    assert "PRIVATE-STORY" not in str(failure.value)


def test_execute_synthesis_preserves_production_failure_classification_and_one_call(
    tmp_path: Path,
) -> None:
    process = FakeProcess(
        _success_output(model="gpt-5.6-sol"),
    )
    provider = _provider(tmp_path, process)
    request, preview = _request_and_preview()

    result = execute_synthesis(request, preview, lambda: provider)

    assert process.communications == 1
    assert result.call_count == 1
    assert result.failure_kind is SynthesisFailureKind.IDENTITY
    assert result.synthesis is None
    assert result.sanitized_reason == "The provider identity could not be verified."
