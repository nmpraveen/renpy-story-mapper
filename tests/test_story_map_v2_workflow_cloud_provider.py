from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from renpy_story_mapper.story_map_v2.cloud_transport import ProcessSpec
from renpy_story_mapper.story_map_v2.contracts import canonical_json
from renpy_story_mapper.story_map_v2.workflow_cloud_provider import (
    CodexCliWorkflowProvider,
)
from renpy_story_mapper.story_map_v2.workflow_contracts import (
    CLOUD_MODEL,
    CLOUD_PROVIDER,
    CLOUD_REASONING,
    TransmissionDisposition,
    WorkflowFailure,
)
from renpy_story_mapper.story_map_v2.workflow_protocols import WorkflowProviderError


class FakeProcess:
    def __init__(self, stdout: bytes, *, returncode: int = 0) -> None:
        self.stdout = stdout
        self.final_returncode = returncode
        self.returncode: int | None = None
        self.stdin: bytes | None = None

    def communicate(
        self, input: bytes | None = None, timeout: float | None = None
    ) -> tuple[bytes, bytes]:
        self.stdin = input
        self.returncode = self.final_returncode
        return self.stdout, b""

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake", timeout)
        return self.returncode


def _response() -> dict[str, object]:
    return {
        "title": "Opening",
        "overview": "A character arrives and makes a decision.",
        "review_requested": False,
        "events": [
            {
                "key": "arrival",
                "placement_ids": ["placement:one"],
                "title": "Arrival",
                "summary": "The character arrives.",
                "characters": ["Character"],
            }
        ],
        "branch_summaries": [],
    }


def _output(*, model: str = CLOUD_MODEL) -> bytes:
    events = (
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": json.dumps(_response())},
        },
        {
            "type": "turn.completed",
            "model": model,
            "reasoning_effort": CLOUD_REASONING,
            "fast_mode": False,
            "usage": {"input_tokens": 123, "output_tokens": 45},
        },
    )
    return b"".join(canonical_json(event) + b"\n" for event in events)


def _executable(tmp_path: Path) -> Path:
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"fixture")
    return executable.resolve()


def test_phase04_schema_accepts_the_validator_response_shape() -> None:
    schema_path = (
        Path(__file__).parents[1]
        / "src"
        / "renpy_story_mapper"
        / "story_map_v2"
        / "schemas"
        / "story_map_phase04_mapper_response_v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    assert not tuple(Draft202012Validator(schema).iter_errors(_response()))


@pytest.mark.parametrize(
    ("schema_name", "payload"),
    [
        (
            "story_map_phase04_section_prose_v1.schema.json",
            {
                "title": "Opening",
                "summary": "The story begins.",
                "sections": [
                    {
                        "first_event_id": "event:one",
                        "last_event_id": "event:one",
                        "title": "First events",
                        "summary": "The opening events establish the situation.",
                    }
                ],
            },
        ),
        (
            "story_map_phase04_rollup_prose_v1.schema.json",
            {"title": "Whole story", "summary": "A concise whole-story overview."},
        ),
    ],
)
def test_derived_prose_schemas_are_valid_and_accept_exact_shapes(
    schema_name: str,
    payload: dict[str, object],
) -> None:
    schema_path = (
        Path(__file__).parents[1]
        / "src"
        / "renpy_story_mapper"
        / "story_map_v2"
        / "schemas"
        / schema_name
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    assert not tuple(Draft202012Validator(schema).iter_errors(payload))


def test_provider_transmits_frozen_bytes_unchanged_with_terra_high(tmp_path: Path) -> None:
    request = canonical_json({"task": "summarize", "raw_story": "private fixture"})
    process = FakeProcess(_output())
    specs: list[ProcessSpec] = []

    def factory(spec: ProcessSpec) -> FakeProcess:
        specs.append(spec)
        return process

    provider = CodexCliWorkflowProvider(
        executable=str(_executable(tmp_path)),
        process_factory=factory,
        timeout_seconds=1,
    )
    result = provider.submit(request)

    assert process.stdin == request
    assert result.payload == canonical_json(_response())
    assert result.resolved_provider == CLOUD_PROVIDER
    assert result.resolved_model == CLOUD_MODEL
    assert result.resolved_reasoning == CLOUD_REASONING
    assert result.resolved_fast_mode is False
    assert result.accounting.input_tokens == 123
    assert result.accounting.output_tokens == 45
    assert specs[0].command[specs[0].command.index("--model") + 1] == CLOUD_MODEL
    assert 'model_reasoning_effort="high"' in specs[0].command
    assert not specs[0].cwd.exists()


def test_provider_rejects_wrong_runtime_identity_as_transmitted(tmp_path: Path) -> None:
    provider = CodexCliWorkflowProvider(
        executable=str(_executable(tmp_path)),
        process_factory=lambda _spec: FakeProcess(_output(model="gpt-5.6-luna")),
    )

    with pytest.raises(WorkflowProviderError) as raised:
        provider.submit(b"{}")

    assert raised.value.failure is WorkflowFailure.IDENTITY_MISMATCH
    assert raised.value.transmission is TransmissionDisposition.TRANSMITTED
    assert raised.value.accounting.calls == 1


def test_provider_selects_section_schema_from_exact_request(tmp_path: Path) -> None:
    prose = {
        "title": "A story section",
        "summary": "The events form one continuous part of the story.",
        "sections": [
            {
                "first_event_id": "event:one",
                "last_event_id": "event:one",
                "title": "Opening",
                "summary": "The story begins.",
            }
        ],
    }
    stdout = b"".join(
        (
            canonical_json(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": json.dumps(prose)},
                }
            )
            + b"\n",
            canonical_json(
                {
                    "type": "turn.completed",
                    "model": CLOUD_MODEL,
                    "reasoning_effort": CLOUD_REASONING,
                    "fast_mode": False,
                    "usage": {"input_tokens": 10, "output_tokens": 10},
                }
            )
            + b"\n",
        )
    )
    process = FakeProcess(stdout)
    specs: list[ProcessSpec] = []

    def factory(spec: ProcessSpec) -> FakeProcess:
        specs.append(spec)
        return process

    provider = CodexCliWorkflowProvider(
        executable=str(_executable(tmp_path)),
        process_factory=factory,
    )
    result = provider.submit(
        canonical_json({"call_kind": "section_synthesis", "task": "group events"})
    )

    schema = specs[0].command[specs[0].command.index("--output-schema") + 1]
    assert Path(schema).name == "story_map_phase04_section_prose_v1.schema.json"
    assert result.payload == canonical_json(prose)


def test_unavailable_executable_is_definitely_not_transmitted(tmp_path: Path) -> None:
    provider = CodexCliWorkflowProvider(executable=str(tmp_path / "missing.exe"))

    with pytest.raises(WorkflowProviderError) as raised:
        provider.submit(b"{}")

    assert raised.value.failure is WorkflowFailure.PROVIDER_UNAVAILABLE
    assert raised.value.transmission is TransmissionDisposition.NOT_TRANSMITTED
    assert raised.value.accounting.calls == 0
