from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import asdict
from pathlib import Path

import pytest

from renpy_story_mapper.story_map_v2.cloud_transport import (
    CLOUD_FAST_MODE,
    CLOUD_REASONING,
    CodexCliCloudTransport,
    ProcessSpec,
    build_sterile_command,
)
from renpy_story_mapper.story_map_v2.contracts import (
    DensityMetrics,
    FailureKind,
    StoryChunk,
    canonical_hash,
)
from renpy_story_mapper.story_map_v2.provider_policy import (
    CLOUD_MAPPER_MODEL,
    ProviderFailure,
)


def _chunk() -> StoryChunk:
    return StoryChunk(
        index=1,
        span_keys=("span:one",),
        choice_keys=("choice:one",),
        raw_text="1: A generalized story line.\n",
        raw_tokens=8,
        density=DensityMetrics(menus=1, arms=2),
        packet_hash=canonical_hash({"packet": "one"}),
    )


def _response() -> dict[str, object]:
    return {
        "scope_title": "A Small Scope",
        "scope_overview": "A traveler makes a choice.",
        "events": [
            {
                "title": "Arrival",
                "summary": "The traveler arrives.",
                "relative_path": "scripts/day.rpy",
                "start_line": 1,
                "end_line": 2,
                "characters": ["Traveler"],
                "warning": None,
            }
        ],
        "branch_summaries": [
            {
                "choice_key": "choice:one",
                "arm_order": 1,
                "outcome_summary": "The traveler takes the first route.",
            }
        ],
    }


def _jsonl(*events: object) -> bytes:
    return b"".join(
        json.dumps(event, separators=(",", ":")).encode("utf-8") + b"\n" for event in events
    )


class FakeProcess:
    def __init__(self, stdout: bytes, *, stderr: bytes = b"", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.final_returncode = returncode
        self.returncode: int | None = None
        self.stdin: bytes | None = None
        self.terminated = False
        self.killed = False

    def communicate(
        self, input: bytes | None = None, timeout: float | None = None
    ) -> tuple[bytes, bytes]:
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


def _success_output(*, model: str = CLOUD_MAPPER_MODEL) -> bytes:
    return _jsonl(
        {"type": "thread.started"},
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": json.dumps(_response())},
        },
        {
            "type": "turn.completed",
            "model": model,
            "reasoning_effort": CLOUD_REASONING,
            "fast_mode": CLOUD_FAST_MODE,
            "usage": {"input_tokens": 80, "output_tokens": 30},
        },
    )


def test_sterile_command_is_exact_direct_luna_high_fast_off(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    command = build_sterile_command("C:/synthetic/codex.exe", schema.resolve())

    assert command[:3] == ("C:/synthetic/codex.exe", "exec", "--ephemeral")
    assert command[-1] == "-"
    assert command[command.index("--model") + 1] == CLOUD_MAPPER_MODEL
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert 'model_reasoning_effort="high"' in command
    assert 'web_search="disabled"' in command
    for feature in ("fast_mode", "shell_tool", "apps", "plugins", "multi_agent"):
        position = command.index(feature)
        assert command[position - 1] == "--disable"


def test_transport_uses_stdin_temp_cwd_and_sanitized_accounting(tmp_path: Path) -> None:
    process = FakeProcess(_success_output())
    specs: list[ProcessSpec] = []

    def factory(spec: ProcessSpec) -> FakeProcess:
        specs.append(spec)
        return process

    transport = CodexCliCloudTransport(
        process_factory=factory,
        executable_resolver=lambda _value: str((tmp_path / "codex.exe").resolve()),
        timeout_seconds=1,
    )
    response = transport.map_chunk(_chunk())

    assert response.scope_title == "A Small Scope"
    assert len(specs) == 1
    assert specs[0].shell is False
    assert not specs[0].cwd.exists()
    assert process.stdin is not None
    packet = json.loads(process.stdin)
    assert packet["raw_text"] == _chunk().raw_text
    assert packet["mechanics"] == {"choice_keys": ["choice:one"]}
    assert packet["packet_hash"] == _chunk().packet_hash
    assert transport.input_tokens == 80
    assert transport.output_tokens == 30
    accounting = transport.last_accounting
    assert accounting is not None
    assert accounting.requested_model == accounting.resolved_model == CLOUD_MAPPER_MODEL
    assert accounting.reasoning == "high"
    assert accounting.fast_mode is False
    assert accounting.response_hash == canonical_hash(asdict(response))
    assert "generalized story" not in repr(accounting)


def test_schema_optional_scope_text_may_be_omitted(tmp_path: Path) -> None:
    payload = _response()
    del payload["scope_title"]
    del payload["scope_overview"]
    process = FakeProcess(
        _jsonl(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": json.dumps(payload)},
            }
        )
    )
    transport = CodexCliCloudTransport(
        process_factory=lambda _spec: process,
        executable_resolver=lambda _value: str((tmp_path / "codex.exe").resolve()),
    )

    response = transport.map_chunk(_chunk())

    assert response.scope_title is None
    assert response.scope_overview is None


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"model": "substitute"}, FailureKind.IDENTITY),
        ({"reasoning_effort": "medium"}, FailureKind.IDENTITY),
        ({"fast_mode": True}, FailureKind.IDENTITY),
    ],
)
def test_reported_identity_substitution_fails_closed(
    metadata: dict[str, object], expected: FailureKind, tmp_path: Path
) -> None:
    turn = {
        "type": "turn.completed",
        "model": CLOUD_MAPPER_MODEL,
        "reasoning_effort": CLOUD_REASONING,
        "fast_mode": CLOUD_FAST_MODE,
    }
    turn.update(metadata)
    process = FakeProcess(
        _jsonl(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": json.dumps(_response())},
            },
            turn,
        )
    )
    transport = CodexCliCloudTransport(
        process_factory=lambda _spec: process,
        executable_resolver=lambda _value: str((tmp_path / "codex.exe").resolve()),
    )

    with pytest.raises(ProviderFailure) as raised:
        transport.map_chunk(_chunk())

    assert raised.value.kind is expected


def test_forbidden_action_and_stderr_are_sanitized(tmp_path: Path) -> None:
    policy_process = FakeProcess(
        _jsonl(
            {
                "type": "item.completed",
                "item": {"type": "command_execution", "command": "SECRET-STORY"},
            }
        )
    )
    transport = CodexCliCloudTransport(
        process_factory=lambda _spec: policy_process,
        executable_resolver=lambda _value: str((tmp_path / "codex.exe").resolve()),
    )
    with pytest.raises(ProviderFailure) as policy:
        transport.map_chunk(_chunk())
    assert policy.value.kind is FailureKind.INVALID_RESPONSE
    assert "SECRET-STORY" not in str(policy.value)

    failure_process = FakeProcess(b"", stderr=b"429 rate limit SECRET-STORY raw text", returncode=1)
    failed = CodexCliCloudTransport(
        process_factory=lambda _spec: failure_process,
        executable_resolver=lambda _value: str((tmp_path / "codex.exe").resolve()),
    )
    with pytest.raises(ProviderFailure) as failure:
        failed.map_chunk(_chunk())
    assert failure.value.kind is FailureKind.RATE_LIMIT
    assert "SECRET-STORY" not in str(failure.value)


def test_explicit_structured_content_refusal_is_distinct(tmp_path: Path) -> None:
    process = FakeProcess(
        _jsonl(
            {
                "type": "turn.failed",
                "error": {
                    "code": "content_policy_violation",
                    "message": "SECRET-STORY provider detail",
                },
            }
        )
    )
    transport = CodexCliCloudTransport(
        process_factory=lambda _spec: process,
        executable_resolver=lambda _value: str((tmp_path / "codex.exe").resolve()),
    )

    with pytest.raises(ProviderFailure) as refusal:
        transport.map_chunk(_chunk())

    assert refusal.value.kind is FailureKind.CONTENT_REFUSAL
    assert "SECRET-STORY" not in str(refusal.value)


class SlowProcess(FakeProcess):
    def __init__(self) -> None:
        super().__init__(b"")
        self.communicating = threading.Event()

    def communicate(
        self, input: bytes | None = None, timeout: float | None = None
    ) -> tuple[bytes, bytes]:
        self.stdin = input if input is not None else self.stdin
        self.communicating.set()
        self.communicating.wait(timeout or 0)
        raise subprocess.TimeoutExpired("fake", timeout)


def test_active_cancellation_terminates_process_and_returns_sanitized_failure(
    tmp_path: Path,
) -> None:
    process = SlowProcess()
    transport = CodexCliCloudTransport(
        process_factory=lambda _spec: process,
        executable_resolver=lambda _value: str((tmp_path / "codex.exe").resolve()),
        timeout_seconds=2,
    )
    failures: list[ProviderFailure] = []

    def run() -> None:
        try:
            transport.map_chunk(_chunk())
        except ProviderFailure as exc:
            failures.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    assert process.communicating.wait(1)
    transport.cancel()
    thread.join(1)

    assert not thread.is_alive()
    assert process.terminated
    assert failures and failures[0].kind is FailureKind.CANCELLED
