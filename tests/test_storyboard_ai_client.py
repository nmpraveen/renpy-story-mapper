from __future__ import annotations

import json
import subprocess
from itertools import pairwise
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from renpy_story_mapper.cli import _parser
from renpy_story_mapper.storyboard.ai_client import (
    CODEX_UNSUPPORTED_SCHEMA_KEYWORDS,
    CodexCliJsonClient,
    ProcessSpec,
    ProviderCancelledError,
    ProviderIdentityMismatchError,
    ProviderLimitError,
    ProviderOutputError,
    ProviderPolicyViolationError,
    ProviderRuntimeConfigurationError,
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
    def __init__(
        self,
        stdout: bytes,
        *,
        stderr: bytes = b"",
        returncode: int = 0,
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.inputs: list[bytes | None] = []
        self.terminated = False
        self.killed = False

    def communicate(
        self, input: bytes | None = None, timeout: float | None = None
    ) -> tuple[bytes, bytes]:
        del timeout
        self.inputs.append(input)
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
    maximum_input_tokens: int = 200_000,
) -> CodexCliJsonClient:
    def factory(spec: ProcessSpec) -> FakeProcess:
        created.append((spec, process))
        return process

    return CodexCliJsonClient(
        executable="codex",
        process_factory=factory,
        executable_resolver=lambda _command: "C:/synthetic/codex.exe",
        timeout_seconds=timeout_seconds,
        maximum_input_tokens=maximum_input_tokens,
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


def test_max_reasoning_cli_flag_is_supported() -> None:
    args = _parser().parse_args(
        [
            "storyboard",
            "game.rpy",
            "--output",
            "output",
            "--reasoning-effort",
            "max",
        ]
    )
    assert args.reasoning_effort == "max"


def test_input_token_ceiling_rejects_before_starting_codex(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    process = FakeProcess(_jsonl({"ok": True}))
    created: list[tuple[ProcessSpec, FakeProcess]] = []
    client = _client(process, created, maximum_input_tokens=1)

    with pytest.raises(ProviderLimitError) as failure:
        client.complete(
            payload={"input": "exact source evidence"},
            schema_path=schema,
            model="gpt-5.6-luna",
            reasoning_effort="max",
            fast_mode=False,
        )

    assert failure.value.error_code == "input_token_limit"
    assert failure.value.transmission == "not_transmitted"
    assert created == []


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


def test_story_analysis_transport_omits_non_nullable_optional_menu_hint() -> None:
    schema = schema_path("story-analysis").resolve()
    canonical_bytes = schema.read_bytes()
    canonical = json.loads(canonical_bytes)
    assert "menu_evidence_id" in canonical["$defs"]["choice"]["allOf"][1]["properties"]
    analysis = {
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
        "excluded_evidence_ids": [],
        "unresolved": [],
        "disagreements": [],
        "status": "resolved",
        "uncertainty": None,
    }
    process = FakeProcess(_jsonl(analysis, fast_mode=False))
    observed_provider_schema: dict[str, object] = {}

    def factory(spec: ProcessSpec) -> FakeProcess:
        provider_path = Path(spec.command[spec.command.index("--output-schema") + 1])
        observed_provider_schema.update(json.loads(provider_path.read_text(encoding="utf-8")))
        return process

    client = CodexCliJsonClient(
        executable="codex",
        process_factory=factory,
        executable_resolver=lambda _command: "C:/synthetic/codex.exe",
        timeout_seconds=1.0,
    )

    assert client.complete(
        payload={"request": "analysis"},
        schema_path=schema,
        model="model-a",
        reasoning_effort="high",
        fast_mode=False,
    ) == analysis

    choices = observed_provider_schema["properties"]["choices"]
    choice = choices["items"]
    assert "menu_evidence_id" not in choice["properties"]
    assert "menu_evidence_id" not in choice["required"]
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


def test_bundled_transition_retains_anyof_and_rejects_resolved_null_target() -> None:
    canonical = json.loads(schema_path("story-analysis").read_text(encoding="utf-8"))
    provider = derive_codex_provider_schema(canonical)
    transitions = provider["properties"]["transitions"]
    assert isinstance(transitions, dict)
    transition = transitions["items"]
    assert isinstance(transition, dict)
    alternatives = transition.get("anyOf")
    assert isinstance(alternatives, list)
    assert len(alternatives) == 3
    assert isinstance(alternatives[0], dict)
    assert len(alternatives[0]["properties"]) == len(transition["properties"])

    valid = {
        "evidence_ids": ["E1"],
        "confidence": "high",
        "status": "resolved",
        "uncertainty": None,
        "rationale": None,
        "interpretation_rationale": None,
        "id": "T1",
        "from_id": "S1",
        "to_id": "S2",
        "kind": "jump",
        "source_evidence_ids": [],
        "target_evidence_ids": [],
    }
    invalid = {**valid, "to_id": None}
    validator = Draft202012Validator(transition)
    assert validator.is_valid(valid)
    assert not validator.is_valid(invalid)

    canonical_payload = {
        "schema": ANALYSIS_SCHEMA_ID,
        "source": {
            "evidence_index_hash": "hash",
            "profile_hash": "profile",
            "canary_evidence_ids": ["E1"],
        },
        "scenes": [],
        "choices": [],
        "transitions": [invalid],
        "claims": [],
        "excluded_evidence_ids": [],
        "unresolved": [],
        "disagreements": [],
        "status": "resolved",
        "uncertainty": None,
    }
    assert not Draft202012Validator(canonical).is_valid(canonical_payload)


@pytest.mark.parametrize(
    "canonical",
    [
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "child": {"$ref": "#/$defs/node"},
            },
            "$defs": {
                "node": {
                    "type": "object",
                    "properties": {"child": {"$ref": "#/$defs/node"}},
                }
            },
        },
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"child": {"$ref": "#/$defs/missing"}},
            "$defs": {},
        },
    ],
)
def test_provider_schema_rejects_recursive_or_missing_local_refs(
    canonical: dict[str, object],
) -> None:
    original = json.loads(json.dumps(canonical))

    with pytest.raises(ValueError, match="reference"):
        derive_codex_provider_schema(canonical)

    assert canonical == original


@pytest.mark.parametrize(
    "canonical",
    [
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"child": {"$ref": "#/$defs/missing"}},
            "$defs": {},
        },
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "allOf": [
                {"type": "string", "minLength": 4},
                {"type": "string", "maxLength": 2},
            ],
        },
    ],
)
def test_schema_derivation_failure_is_isolated_before_provider_start(
    tmp_path: Path, canonical: dict[str, object]
) -> None:
    schema = tmp_path / "invalid-provider-derivation.schema.json"
    schema.write_text(json.dumps(canonical), encoding="utf-8")
    process = FakeProcess(_jsonl({"ok": True}))
    created: list[tuple[ProcessSpec, FakeProcess]] = []
    client = _client(process, created)

    with pytest.raises(ProviderRuntimeConfigurationError) as raised:
        client.complete(
            payload={"request": "derivation"},
            schema_path=schema,
            model="model-a",
            reasoning_effort="high",
            fast_mode=False,
        )

    assert raised.value.error_code == "provider_schema_derivation_failed"
    assert raised.value.transmission.value == "not_transmitted"
    assert created == []


def test_compatible_scalar_allof_constraints_intersect_without_mutation() -> None:
    canonical = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "allOf": [
            {
                "type": "object",
                "properties": {
                    "number": {"type": "number", "minimum": 0, "maximum": 10},
                    "integer": {"type": "number"},
                    "text": {"type": "string", "minLength": 1, "maxLength": 10},
                    "array": {"type": "array", "minItems": 1, "maxItems": 5},
                    "value": {
                        "type": ["string", "null"],
                        "enum": ["a", "b"],
                    },
                },
            },
            {
                "type": "object",
                "properties": {
                    "number": {"minimum": 1, "maximum": 9},
                    "integer": {"type": "integer"},
                    "text": {"minLength": 3, "maxLength": 8},
                    "array": {"minItems": 2, "maxItems": 4},
                    "value": {"type": "string", "const": "a"},
                },
            },
        ],
    }
    original = json.loads(json.dumps(canonical))

    provider = derive_codex_provider_schema(canonical)

    assert canonical == original
    properties = provider["properties"]
    assert isinstance(properties, dict)
    assert properties["number"] == {
        "type": "number",
        "minimum": 1,
        "maximum": 9,
    }
    assert properties["integer"] == {"type": "integer"}
    assert properties["text"] == {
        "type": "string",
        "minLength": 3,
        "maxLength": 8,
    }
    assert properties["array"] == {
        "type": "array",
        "minItems": 2,
        "maxItems": 4,
    }
    assert properties["value"] == {
        "type": "string",
        "enum": ["a"],
        "const": "a",
    }


@pytest.mark.parametrize(
    "canonical",
    [
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "allOf": [{"type": "string"}, {"type": "integer"}],
        },
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "allOf": [{"const": "a"}, {"const": "b"}],
        },
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "allOf": [{"const": True}, {"const": 1}],
        },
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "allOf": [
                {"type": "string", "minLength": 4},
                {"type": "string", "maxLength": 2},
            ],
        },
    ],
)
def test_genuinely_conflicting_scalar_allof_is_deterministic(
    canonical: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        derive_codex_provider_schema(canonical)


@pytest.mark.parametrize(
    "canonical",
    [
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "allOf": [{"const": 1}, {"minimum": 2}],
        },
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "allOf": [{"enum": [1, 2]}, {"type": "integer", "minimum": 3}],
        },
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "integer",
            "minimum": 0.1,
            "maximum": 0.9,
        },
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "allOf": [
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"a": {"type": "string"}},
                },
                {
                    "type": "object",
                    "required": ["b"],
                    "properties": {"b": {"type": "string"}},
                },
            ],
        },
    ],
)
def test_empty_scalar_or_closed_object_domains_fail_before_provider_start(
    tmp_path: Path, canonical: dict[str, object]
) -> None:
    schema = tmp_path / "empty-domain.schema.json"
    schema.write_text(json.dumps(canonical), encoding="utf-8")
    process = FakeProcess(_jsonl({"ok": True}))
    created: list[tuple[ProcessSpec, FakeProcess]] = []
    client = _client(process, created)

    with pytest.raises(ProviderRuntimeConfigurationError) as raised:
        client.complete(
            payload={"request": "empty-domain"},
            schema_path=schema,
            model="model-a",
            reasoning_effort="high",
            fast_mode=False,
        )

    assert raised.value.error_code == "provider_schema_derivation_failed"
    assert raised.value.transmission.value == "not_transmitted"
    assert created == []


def test_enum_intersection_filters_incompatible_members_and_keeps_canonical_input() -> None:
    canonical = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "allOf": [
            {"enum": [1, "x"]},
            {"type": "integer", "minimum": 1, "maximum": 1},
        ],
    }
    original = json.loads(json.dumps(canonical))

    provider = derive_codex_provider_schema(canonical)

    assert canonical == original
    assert provider == {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "enum": [1],
        "maximum": 1,
        "minimum": 1,
        "type": "integer",
    }


def test_enum_intersection_filters_string_and_array_values_by_applicable_limits() -> None:
    string_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "allOf": [{"enum": ["a", "long"]}, {"minLength": 2}],
    }
    array_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "allOf": [{"enum": [[], [1]]}, {"type": "array", "minItems": 1}],
    }

    assert derive_codex_provider_schema(string_schema)["enum"] == ["long"]
    assert derive_codex_provider_schema(array_schema)["enum"] == [[1]]


def test_multiple_of_intersection_is_exact_for_integer_and_decimal_json_numbers() -> None:
    integer_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "allOf": [{"type": "integer", "multipleOf": 2}, {"multipleOf": 3}],
    }
    decimal_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "allOf": [{"type": "number", "multipleOf": 0.2}, {"multipleOf": 0.3}],
    }

    integer_provider = derive_codex_provider_schema(integer_schema)
    decimal_provider = derive_codex_provider_schema(decimal_schema)

    assert integer_provider["multipleOf"] == 6
    assert decimal_provider["multipleOf"] == 0.6
    assert Draft202012Validator(integer_provider).is_valid(6)
    assert not Draft202012Validator(integer_provider).is_valid(2)
    assert Draft202012Validator(decimal_provider).is_valid(1.2)
    assert not Draft202012Validator(decimal_provider).is_valid(0.3)


def test_allof_conjunction_is_order_independent_and_impossible_domains_do_not_start(
    tmp_path: Path,
) -> None:
    allof_first = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "allOf": [
            {
                "type": "object",
                "properties": {"b": {"type": "integer"}},
                "required": ["b"],
            }
        ],
        "type": "object",
        "additionalProperties": False,
        "properties": {"a": {"type": "string"}},
    }
    siblings_first = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {"a": {"type": "string"}},
        "allOf": [
            {
                "type": "object",
                "properties": {"b": {"type": "integer"}},
                "required": ["b"],
            }
        ],
    }
    values = ({}, {"a": "x"}, {"b": 1}, {"a": "x", "b": 1})
    for index, canonical in enumerate((allof_first, siblings_first)):
        assert not any(Draft202012Validator(canonical).is_valid(value) for value in values)
        schema = tmp_path / f"allof-order-{index}.json"
        schema.write_text(json.dumps(canonical), encoding="utf-8")
        process = FakeProcess(_jsonl({"ok": True}))
        created: list[tuple[ProcessSpec, FakeProcess]] = []
        client = _client(process, created)

        with pytest.raises(ProviderRuntimeConfigurationError) as raised:
            client.complete(
                payload={"request": "allof-order"},
                schema_path=schema,
                model="model-a",
                reasoning_effort="high",
                fast_mode=False,
            )

        assert raised.value.error_code == "provider_schema_derivation_failed"
        assert raised.value.transmission.value == "not_transmitted"
        assert created == []


def test_closed_anyof_alternatives_are_projected_independently_without_property_union() -> None:
    canonical = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"a": {"const": 1}, "b": {"const": 2}},
        "anyOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"a": {"const": 1}},
                "required": ["a"],
            },
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"b": {"const": 2}},
                "required": ["b"],
            },
        ],
    }
    provider = derive_codex_provider_schema(canonical)
    alternatives = provider["anyOf"]
    assert isinstance(alternatives, list)
    assert [set(alternative["properties"]) for alternative in alternatives] == [
        {"a"},
        {"b"},
    ]
    values = ({}, {"a": 1}, {"b": 2}, {"a": 1, "b": 2})
    canonical_valid = [Draft202012Validator(canonical).is_valid(value) for value in values]
    provider_valid = [Draft202012Validator(provider).is_valid(value) for value in values]
    assert canonical_valid == [False, True, True, False]
    assert provider_valid == canonical_valid


@pytest.mark.parametrize(
    "canonical",
    [
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "array",
            "const": [1, 1],
            "uniqueItems": True,
        },
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "array",
            "enum": [[1, 1]],
            "uniqueItems": True,
        },
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "array",
            "items": {"const": 1},
            "minItems": 2,
            "uniqueItems": True,
        },
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "array",
            "contains": False,
        },
    ],
)
def test_impossible_finite_array_domains_fail_before_provider_projection(
    canonical: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        derive_codex_provider_schema(canonical)


def test_required_impossible_nested_array_stops_before_provider_start(tmp_path: Path) -> None:
    canonical = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["value"],
        "properties": {
            "value": {
                "type": "array",
                "const": [1, 1],
                "uniqueItems": True,
            }
        },
    }
    schema = tmp_path / "impossible-nested-array.schema.json"
    schema.write_text(json.dumps(canonical), encoding="utf-8")
    process = FakeProcess(_jsonl({"value": [1, 1]}))
    created: list[tuple[ProcessSpec, FakeProcess]] = []
    client = _client(process, created)

    with pytest.raises(ProviderRuntimeConfigurationError) as raised:
        client.complete(
            payload={"request": "impossible-nested-array"},
            schema_path=schema,
            model="model-a",
            reasoning_effort="high",
            fast_mode=False,
        )

    assert raised.value.error_code == "provider_schema_derivation_failed"
    assert raised.value.transmission.value == "not_transmitted"
    assert created == []


def test_prefix_items_do_not_apply_items_to_the_prefix_tuple() -> None:
    canonical = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "array",
        "prefixItems": [{"const": 1}],
        "items": False,
    }
    provider = derive_codex_provider_schema(canonical)
    values = ([], [1], [2], [1, 2])
    canonical_valid = [Draft202012Validator(canonical).is_valid(value) for value in values]
    provider_valid = [Draft202012Validator(provider).is_valid(value) for value in values]
    assert canonical_valid == [True, True, False, False]
    assert provider_valid == canonical_valid


def test_optional_impossible_nested_properties_are_omitted_but_required_ones_fail() -> None:
    impossible_child = {
        "allOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"a": {"type": "string"}},
            },
            {
                "type": "object",
                "required": ["b"],
                "properties": {"b": {"type": "integer"}},
            },
        ]
    }
    optional = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"child": impossible_child},
    }
    provider = derive_codex_provider_schema(optional)
    assert provider["properties"] == {}
    assert Draft202012Validator(optional).is_valid({})
    assert Draft202012Validator(provider).is_valid({})

    required = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["child"],
        "properties": {"child": impossible_child},
    }
    with pytest.raises(ValueError):
        derive_codex_provider_schema(required)


def test_high_precision_multiple_of_uses_exact_decimal_materialization(tmp_path: Path) -> None:
    canonical = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["step"],
        "properties": {
            "step": {
                "allOf": [
                    {"type": "number", "multipleOf": 0.6666666666666666},
                    {"minimum": 0, "maximum": 3000000000000000, "multipleOf": 0.8},
                ]
            }
        },
    }
    schema = tmp_path / "high-precision.schema.json"
    schema.write_text(json.dumps(canonical), encoding="utf-8")
    provider = derive_codex_provider_schema(canonical)
    step = provider["properties"]["step"]
    assert str(step["multipleOf"]) == "2666666666666666.4"
    Draft202012Validator.check_schema(provider)

    observed_schema_text: list[str] = []
    process = FakeProcess(_jsonl({"step": 0}, fast_mode=False))

    def factory(spec: ProcessSpec) -> FakeProcess:
        provider_path = Path(spec.command[spec.command.index("--output-schema") + 1])
        observed_schema_text.append(provider_path.read_text(encoding="utf-8"))
        return process

    client = CodexCliJsonClient(
        executable="codex",
        process_factory=factory,
        executable_resolver=lambda _command: "C:/synthetic/codex.exe",
        timeout_seconds=1.0,
    )
    assert client.complete(
        payload={"request": "high-precision"},
        schema_path=schema,
        model="model-a",
        reasoning_effort="high",
        fast_mode=False,
    ) == {"step": 0}
    assert '"multipleOf":2666666666666666.4' in observed_schema_text[0]
    assert '"multipleOf":"2666666666666666.4"' not in observed_schema_text[0]


@pytest.mark.parametrize("multiple_of", [0, -1, 0.0])
def test_invalid_multiple_of_is_rejected_before_projection(multiple_of: int | float) -> None:
    canonical = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "number",
        "multipleOf": multiple_of,
    }

    with pytest.raises(ValueError, match="multipleOf"):
        derive_codex_provider_schema(canonical)


@pytest.mark.parametrize("multiple_of", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_multiple_of_is_rejected_before_projection(multiple_of: float) -> None:
    canonical = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "number",
        "multipleOf": multiple_of,
    }

    with pytest.raises(ValueError, match="multipleOf"):
        derive_codex_provider_schema(canonical)


def test_closed_object_intersection_keeps_only_the_true_property_intersection() -> None:
    canonical = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "allOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "a": {"type": "string"},
                    "b": {"type": "integer"},
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "b": {"type": "number"},
                    "c": {"type": "string"},
                },
            },
        ],
    }
    original = json.loads(json.dumps(canonical))

    provider = derive_codex_provider_schema(canonical)

    assert canonical == original
    assert provider["properties"] == {"b": {"type": "integer"}}
    assert provider["required"] == ["b"]
    assert provider["additionalProperties"] is False
    assert Draft202012Validator(canonical).is_valid({"b": 2})
    assert Draft202012Validator(provider).is_valid({"b": 2})
    assert not Draft202012Validator(provider).is_valid({"a": "x", "b": 2})


def test_open_and_closed_object_intersection_preserves_closed_authority() -> None:
    canonical = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "allOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"a": {"type": "string"}},
            },
            {
                "type": "object",
                "required": ["a"],
                "properties": {
                    "a": {"minLength": 1},
                    "b": {"type": "string"},
                },
            },
        ],
    }

    provider = derive_codex_provider_schema(canonical)

    assert provider["properties"] == {"a": {"type": "string", "minLength": 1}}
    assert provider["required"] == ["a"]
    assert Draft202012Validator(canonical).is_valid({"a": "x"})
    assert not Draft202012Validator(provider).is_valid({"a": "x", "b": "y"})


def test_two_closed_objects_with_disjoint_optional_properties_intersect_at_empty_object() -> None:
    canonical = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "allOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"a": {"type": "string"}},
            },
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"b": {"type": "string"}},
            },
        ],
    }

    provider = derive_codex_provider_schema(canonical)

    assert provider["properties"] == {}
    assert provider["required"] == []
    assert Draft202012Validator(canonical).is_valid({})
    assert Draft202012Validator(provider).is_valid({})


def test_closed_and_open_additional_properties_intersect_named_property_constraints() -> None:
    canonical = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "allOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"a": {"type": "string"}},
            },
            {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "properties": {"a": {"minLength": 2}},
            },
        ],
    }

    provider = derive_codex_provider_schema(canonical)

    assert provider["properties"] == {"a": {"type": "string", "minLength": 2}}
    assert provider["additionalProperties"] is False


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


def test_nonzero_process_uses_stdout_category_and_preserves_private_diagnostic() -> None:
    stdout = b'{"type":"turn.failed","message":"invalid_json_schema"}\n'
    process = FakeProcess(stdout, stderr=b"provider warning\n", returncode=1)
    created: list[tuple[ProcessSpec, FakeProcess]] = []
    client = _client(process, created)

    with pytest.raises(ProviderRuntimeConfigurationError) as raised:
        client.complete(
            payload={"request": "profile"},
            schema_path=schema_path("game-profile"),
            model="model-a",
            reasoning_effort="high",
            fast_mode=False,
        )

    error = raised.value
    assert error.error_code == "provider_schema_rejected"
    assert "invalid_json_schema" not in str(error)
    assert error.diagnostic_path is not None
    diagnostic_path = error.diagnostic_path
    try:
        diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
        assert diagnostic["returncode"] == 1
        assert diagnostic["stdout_utf8"] == stdout.decode("utf-8")
        assert diagnostic["stderr_utf8"] == "provider warning\n"
        assert "request" not in diagnostic
    finally:
        diagnostic_path.unlink(missing_ok=True)
        diagnostic_path.parent.rmdir()


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
    analysis_authority = analysis["authority"]
    assert isinstance(analysis_authority, str)
    assert "physical_ownership map is authoritative" in analysis_authority
    assert "Never repeat branch-owned lines in a scene body." in analysis_authority
    assert "Scene order is zero-based and contiguous." in analysis_authority
    assert "never a continuation ID" in analysis_authority
    assert "Do not emit menu_evidence_id" in analysis_authority
    for request in (profile, analysis):
        authority = request["authority"]
        assert isinstance(authority, str)
        assert "status=resolved requires uncertainty=null." in authority
        assert (
            "status in uncertain, unresolved, or excluded requires a non-empty uncertainty "
            "string."
        ) in authority
    for kind, schema_id in (
        ("game-profile", PROFILE_SCHEMA_ID),
        ("story-analysis", ANALYSIS_SCHEMA_ID),
    ):
        schema = json.loads(schema_path(kind).read_text(encoding="utf-8"))
        assert schema["$id"] == schema_id
        assert schema["additionalProperties"] is False
        assert schema["required"]
