from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from renpy_story_mapper.storyboard.ai_client import (
    CodexCliJsonClient,
    ProcessSpec,
    ProviderCancelledError,
    ProviderIdentityMismatchError,
    ProviderPolicyViolationError,
    ProviderTimeoutError,
    build_codex_command,
)
from renpy_story_mapper.storyboard.prompts import (
    ANALYSIS_SCHEMA_ID,
    PROFILE_SCHEMA_ID,
    build_game_profile_request,
    build_story_analysis_request,
    schema_path,
)


class FakeProcess:
    def __init__(self, stdout: bytes, *, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.inputs: list[bytes | None] = []
        self.terminated = False
        self.killed = False

    def communicate(
        self, input: bytes | None = None, timeout: float | None = None
    ) -> tuple[bytes, bytes]:
        del timeout
        self.inputs.append(input)
        return self.stdout, b""

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return self.returncode or 0


class HangingProcess(FakeProcess):
    def __init__(self) -> None:
        super().__init__(b"", returncode=None)

    def communicate(
        self, input: bytes | None = None, timeout: float | None = None
    ) -> tuple[bytes, bytes]:
        self.inputs.append(input)
        raise subprocess.TimeoutExpired("codex", timeout or 0.0)


def _jsonl(
    payload: dict[str, object],
    *,
    model: str = "model-a",
    reasoning_effort: str = "high",
    fast_mode: bool = True,
) -> bytes:
    events = [
        {
            "type": "turn.started",
            "model": model,
            "reasoning_effort": reasoning_effort,
            "fast_mode": fast_mode,
        },
        {"type": "turn.completed", "usage": {"input_tokens": 11, "output_tokens": 7}},
        {"item": {"type": "agent_message", "text": json.dumps(payload)}},
    ]
    return b"".join(
        json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        for event in events
    )


def _client(
    process: FakeProcess,
    created: list[tuple[ProcessSpec, FakeProcess]],
    *,
    timeout_seconds: float = 1.0,
) -> CodexCliJsonClient:
    def factory(spec: ProcessSpec) -> FakeProcess:
        created.append((spec, process))
        return process

    return CodexCliJsonClient(
        executable="codex",
        process_factory=factory,
        executable_resolver=lambda _command: "C:/synthetic/codex.exe",
        timeout_seconds=timeout_seconds,
    )


def test_command_is_direct_read_only_schema_bound_and_explicitly_fast(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")

    command = build_codex_command(
        "C:/synthetic/codex.exe",
        model="model-a",
        reasoning_effort="high",
        fast_mode=True,
        schema_path=schema,
    )

    assert command[0] == "C:/synthetic/codex.exe"
    assert command[1:3] == ("exec", "--ephemeral")
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert "--strict-config" in command
    assert "--model" in command
    assert command[command.index("--model") + 1] == "model-a"
    assert str(schema) in command
    assert 'model_reasoning_effort="high"' in command
    assert "fast_mode=true" in command
    assert "--disable" in command
    assert "shell_tool" in command
    disabled = {
        command[index + 1]
        for index, value in enumerate(command[:-1])
        if value == "--disable"
    }
    assert "fast_mode" not in disabled
    assert command[-1] == "-"


def test_complete_sends_canonical_json_and_verifies_runtime_metadata(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    process = FakeProcess(_jsonl({"schema": "storyboard-test-v1", "ok": True}))
    created: list[tuple[ProcessSpec, FakeProcess]] = []
    client = _client(process, created)

    result = client.complete(
        payload={"z": 2, "a": "exact"},
        schema_path=schema,
        model="model-a",
        reasoning_effort="high",
        fast_mode=True,
    )

    assert result == {"schema": "storyboard-test-v1", "ok": True}
    assert client.last_metadata is not None
    assert client.last_metadata.resolved_model == "model-a"
    assert client.last_metadata.resolved_reasoning_effort == "high"
    assert client.last_metadata.resolved_fast_mode is True
    assert client.last_metadata.metadata_verified
    assert client.last_metadata.input_tokens == 11
    assert client.last_metadata.output_tokens == 7
    assert len(created) == 1
    spec, _ = created[0]
    assert spec.shell is False
    assert not spec.cwd.exists()
    assert process.inputs == [b'{"a":"exact","z":2}']


def test_runtime_model_mismatch_is_sanitized() -> None:
    process = FakeProcess(_jsonl({"ok": True}, model="unexpected-model"))
    created: list[tuple[ProcessSpec, FakeProcess]] = []
    client = _client(process, created)

    with pytest.raises(ProviderIdentityMismatchError) as raised:
        client.complete(
            payload={"request": "profile"},
            schema_path=schema_path("game-profile"),
            model="model-a",
            reasoning_effort="high",
            fast_mode=True,
        )

    assert raised.value.error_code == "model_mismatch"
    assert "unexpected-model" not in str(raised.value)


def test_forbidden_policy_event_is_rejected() -> None:
    process = FakeProcess(b'{"type":"mcp_tool_call"}\n')
    created: list[tuple[ProcessSpec, FakeProcess]] = []
    client = _client(process, created)

    with pytest.raises(ProviderPolicyViolationError) as raised:
        client.complete(
            payload={"request": "analysis"},
            schema_path=schema_path("story-analysis"),
            model="model-a",
            reasoning_effort="high",
            fast_mode=True,
        )

    assert raised.value.error_code == "policy_violation"
    assert "mcp_tool_call" not in str(raised.value)


def test_cancel_before_transmission_does_not_start_a_process(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    process = FakeProcess(_jsonl({"ok": True}))
    created: list[tuple[ProcessSpec, FakeProcess]] = []
    client = _client(process, created)

    with pytest.raises(ProviderCancelledError) as raised:
        client.complete(
            payload={"request": "cancelled"},
            schema_path=schema,
            model="model-a",
            reasoning_effort="high",
            fast_mode=True,
            cancelled=lambda: True,
        )

    assert raised.value.transmission.value == "not_transmitted"
    assert created == []


def test_timeout_terminates_a_hanging_process(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    process = HangingProcess()
    created: list[tuple[ProcessSpec, FakeProcess]] = []
    client = _client(process, created, timeout_seconds=0.01)

    with pytest.raises(ProviderTimeoutError) as raised:
        client.complete(
            payload={"request": "timeout"},
            schema_path=schema,
            model="model-a",
            reasoning_effort="high",
            fast_mode=True,
        )

    assert raised.value.error_code == "timeout"
    assert process.terminated


def test_prompt_builders_and_schemas_are_generic() -> None:
    evidence = {"entries": [{"id": "E1", "source": {"path": "scene.rpy"}}]}
    profile = build_game_profile_request(evidence_index=evidence)
    analysis = build_story_analysis_request(
        evidence_index=evidence,
        game_profile={"schema": PROFILE_SCHEMA_ID},
        canary_evidence_ids=("E1",),
    )

    assert profile["output_contract"] == {
        "schema": PROFILE_SCHEMA_ID,
        "return": "one JSON object matching the supplied schema",
    }
    assert analysis["output_contract"] == {
        "schema": ANALYSIS_SCHEMA_ID,
        "return": "one JSON object matching the supplied schema",
    }
    assert analysis["input"]["canary_evidence_ids"] == ["E1"]
    for kind, schema_id in (
        ("game-profile", PROFILE_SCHEMA_ID),
        ("story-analysis", ANALYSIS_SCHEMA_ID),
    ):
        schema = json.loads(schema_path(kind).read_text(encoding="utf-8"))
        assert schema["$id"] == schema_id
        assert schema["additionalProperties"] is False
        assert schema["required"]
