from __future__ import annotations

import json
import subprocess
from itertools import pairwise
from pathlib import Path

import pytest

from renpy_story_mapper.cli import _parser
from renpy_story_mapper.storyboard.ai_client import (
    CODEX_UNSUPPORTED_SCHEMA_KEYWORDS,
    CodexCliJsonClient,
    ProcessSpec,
    ProviderCancelledError,
    ProviderIdentityMismatchError,
    ProviderOutputError,
    ProviderPolicyViolationError,
    ProviderTimeoutError,
    build_codex_command,
    derive_codex_provider_schema,
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
    assert ("--enable", "fast_mode") in tuple(pairwise(command))
    assert all(
        not (value == "-c" and command[index + 1].startswith("fast_mode="))
        for index, value in enumerate(command[:-1])
    )
    assert "--disable" in command
    assert "shell_tool" in command
    disabled = {
        command[index + 1]
        for index, value in enumerate(command[:-1])
        if value == "--disable"
    }
    assert "fast_mode" not in disabled
    assert command[-1] == "-"


def test_no_fast_mode_cli_flag_builds_supported_disabled_feature_command(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")

    args = _parser().parse_args(
        [
            "storyboard",
            "game.rpy",
            "--output",
            "output",
            "--model",
            "gpt-5.6-luna",
            "--reasoning-effort",
            "xhigh",
            "--no-fast-mode",
        ]
    )
    assert args.fast_mode is False

    command = build_codex_command(
        "C:/synthetic/codex.exe",
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        fast_mode=args.fast_mode,
        schema_path=schema,
    )
    config_overrides = {
        command[index + 1]
        for index, value in enumerate(command[:-1])
        if value == "-c"
    }

    assert command[0] == "C:/synthetic/codex.exe"
    assert command[1:3] == ("exec", "--ephemeral")
    assert "--sandbox" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert "--strict-config" in command
    assert ("--disable", "fast_mode") in tuple(pairwise(command))
    assert "fast_mode=false" not in config_overrides
    assert "features.fast_mode=false" not in config_overrides
    assert 'model_reasoning_effort="xhigh"' in config_overrides
    assert command[command.index("--model") + 1] == "gpt-5.6-luna"
    assert "--json" in command
    assert "--output-schema" in command
    assert str(schema) in command
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


def test_provider_schema_copy_is_recursive_non_mutating_and_explicit() -> None:
    canonical = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "uniqueItems": True,
        "properties": {
            "nested": {
                "type": "array",
                "uniqueItems": True,
                "items": {"uniqueItems": True},
            }
        },
        "allOf": [{"$defs": {"deep": {"uniqueItems": True}}}],
    }
    original = json.loads(json.dumps(canonical))

    provider = derive_codex_provider_schema(canonical)

    assert canonical == original
    assert frozenset({"uniqueItems", "unevaluatedProperties", "allOf", "if"}) == (
        CODEX_UNSUPPORTED_SCHEMA_KEYWORDS
    )
    assert "uniqueItems" not in json.dumps(provider)
    assert provider["properties"] == {
        "nested": {"type": "array", "items": {}}
    }
    assert provider["type"] == "object"
    assert provider["additionalProperties"] is False
    assert "allOf" not in provider


def test_complete_materializes_provider_schema_without_mutating_canonical_input() -> None:
    schema = schema_path("game-profile").resolve()
    canonical_bytes = schema.read_bytes()
    profile = {
        "schema": PROFILE_SCHEMA_ID,
        "source": {"evidence_index_hash": "probe", "scope_evidence_ids": ["E1"]},
        "entry_points": [],
        "characters": [],
        "variables": [],
        "custom_constructs": [],
        "conventions": [],
        "ending_patterns": [],
        "unresolved": [],
        "status": "resolved",
        "uncertainty": None,
    }
    process = FakeProcess(_jsonl(profile, fast_mode=False))
    created: list[tuple[ProcessSpec, FakeProcess]] = []
    observed_provider_schema: dict[str, object] = {}
    observed_schema_path: Path | None = None

    def factory(spec: ProcessSpec) -> FakeProcess:
        nonlocal observed_schema_path
        observed_schema_path = Path(spec.command[spec.command.index("--output-schema") + 1])
        observed_provider_schema.update(
            json.loads(observed_schema_path.read_text(encoding="utf-8"))
        )
        created.append((spec, process))
        return process

    client = CodexCliJsonClient(
        executable="codex",
        process_factory=factory,
        executable_resolver=lambda _command: "C:/synthetic/codex.exe",
        timeout_seconds=1.0,
    )

    assert client.complete(
        payload={"request": "profile"},
        schema_path=schema,
        model="model-a",
        reasoning_effort="high",
        fast_mode=False,
    ) == profile

    assert created
    assert observed_schema_path is not None
    assert observed_schema_path != schema
    assert not observed_schema_path.exists()
    assert "uniqueItems" not in json.dumps(observed_provider_schema)
    assert schema.read_bytes() == canonical_bytes


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        (
            "game-profile",
            {
                "schema": PROFILE_SCHEMA_ID,
                "source": {
                    "evidence_index_hash": "probe",
                    "scope_evidence_ids": ["E1", "E1"],
                },
                "entry_points": [],
                "characters": [],
                "variables": [],
                "custom_constructs": [],
                "conventions": [],
                "ending_patterns": [],
                "unresolved": [],
                "status": "resolved",
                "uncertainty": None,
            },
        ),
        (
            "story-analysis",
            {
                "schema": ANALYSIS_SCHEMA_ID,
                "source": {
                    "evidence_index_hash": "probe",
                    "profile_hash": "probe",
                    "canary_evidence_ids": ["E1"],
                },
                "scenes": [],
                "choices": [],
                "transitions": [],
                "claims": [],
                "excluded_evidence_ids": ["E1", "E1"],
                "unresolved": [],
                "disagreements": [],
                "status": "resolved",
                "uncertainty": None,
            },
        ),
    ],
)
def test_canonical_validation_still_rejects_duplicate_ids_after_provider_relaxation(
    kind: str, payload: dict[str, object]
) -> None:
    process = FakeProcess(_jsonl(payload))
    created: list[tuple[ProcessSpec, FakeProcess]] = []
    client = _client(process, created)

    with pytest.raises(ProviderOutputError) as raised:
        client.complete(
            payload={"request": kind},
            schema_path=schema_path(kind),
            model="model-a",
            reasoning_effort="high",
            fast_mode=False,
        )

    assert raised.value.error_code == "schema_mismatch"
    assert raised.value.transmission.value == "transmitted"


def test_bundled_canonical_schemas_retain_unique_items_constraints() -> None:
    for kind in ("game-profile", "story-analysis"):
        canonical = json.loads(schema_path(kind).read_text(encoding="utf-8"))
        serialized = json.dumps(canonical)
        assert serialized.count('"uniqueItems"') > 0
        assert derive_codex_provider_schema(canonical) != canonical


def test_provider_schema_flattens_composition_and_closes_real_object_fields() -> None:
    def assert_provider_objects(value: object) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object":
                properties = value.get("properties")
                required = value.get("required")
                assert isinstance(properties, dict)
                assert isinstance(required, list)
                assert set(required) == set(properties)
                assert value.get("additionalProperties") is False
            for child in value.values():
                assert_provider_objects(child)
        elif isinstance(value, list):
            for child in value:
                assert_provider_objects(child)

    profile = derive_codex_provider_schema(
        json.loads(schema_path("game-profile").read_text(encoding="utf-8"))
    )
    analysis = derive_codex_provider_schema(
        json.loads(schema_path("story-analysis").read_text(encoding="utf-8"))
    )

    assert_provider_objects(profile)
    assert_provider_objects(analysis)
    assert "$defs" not in profile
    assert "$defs" not in analysis
    assert profile["properties"]["schema"]["type"] == "string"
    assert analysis["properties"]["schema"]["type"] == "string"

    profile_character = profile["properties"]["characters"]["items"]
    assert isinstance(profile_character, dict)
    assert {"id", "names", "description", "evidence_ids", "confidence"}.issubset(
        profile_character["properties"]
    )
    analysis_scene = analysis["properties"]["scenes"]["items"]
    assert isinstance(analysis_scene, dict)
    assert {"id", "title", "summary", "order", "line_evidence_ids"}.issubset(
        analysis_scene["properties"]
    )


def test_runtime_model_mismatch_is_sanitized() -> None:
    profile = {
        "schema": PROFILE_SCHEMA_ID,
        "source": {"evidence_index_hash": "hash", "scope_evidence_ids": ["E1"]},
        "entry_points": [],
        "characters": [],
        "variables": [],
        "custom_constructs": [],
        "conventions": [],
        "ending_patterns": [],
        "unresolved": [],
        "status": "resolved",
        "uncertainty": None,
    }
    process = FakeProcess(_jsonl(profile, model="unexpected-model"))
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


def test_complete_rejects_provider_json_that_misses_the_requested_schema() -> None:
    process = FakeProcess(_jsonl({"ok": True}))
    created: list[tuple[ProcessSpec, FakeProcess]] = []
    client = _client(process, created)

    with pytest.raises(ProviderOutputError) as raised:
        client.complete(
            payload={"request": "profile"},
            schema_path=schema_path("game-profile"),
            model="model-a",
            reasoning_effort="high",
            fast_mode=True,
        )

    assert raised.value.error_code == "schema_mismatch"
    assert "ok" not in str(raised.value)


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
