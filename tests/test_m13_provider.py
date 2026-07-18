from __future__ import annotations

import json
from importlib.resources import as_file, files
from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import QProcess

from renpy_story_mapper.narrative.contracts import (
    AuthorityReference,
    AuthoritySystem,
    CacheIdentity,
    JsonValue,
    ProviderIdentity,
    ProviderSettings,
)
from renpy_story_mapper.narrative.evidence import HandleBindingError, PromptHandleTable
from renpy_story_mapper.narrative.provider import (
    ADAPTER_NAME,
    ADAPTER_VERSION,
    PROMPT_TEMPLATE_VERSION,
    RESPONSE_SCHEMA_VERSION,
    CodexCliNarrativeProvider,
    NarrativeProviderError,
    ProviderAuthenticationError,
    ProviderBatchItem,
    ProviderCancelledError,
    ProviderIdentityMismatchError,
    ProviderLimitError,
    ProviderOutputError,
    ProviderPolicyViolationError,
    ProviderProcessError,
    ProviderRateLimitError,
    ProviderRequest,
    ProviderRuntimeConfigurationError,
    ProviderSchemaRejectedError,
    ProviderServerTransientError,
    ProviderTimeoutError,
    ProviderTransportError,
    ProviderUnavailableError,
)
from renpy_story_mapper.organization.sterile_runner import (
    SterileCodexRunner,
    SterileRunnerError,
    SterileRunRequest,
    SterileRunResult,
    TransmissionDisposition,
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
        self.status_calls = 0

    def status(self) -> tuple[str | None, str | None]:
        self.status_calls += 1
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


def _walk_schema(node: object) -> tuple[dict[str, object], ...]:
    found: list[dict[str, object]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found.extend(_walk_schema(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_walk_schema(value))
    return tuple(found)


def _assert_supported_schema_node(node: dict[str, object]) -> None:
    supported = {
        "$defs",
        "$id",
        "$ref",
        "$schema",
        "additionalProperties",
        "anyOf",
        "const",
        "enum",
        "items",
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "pattern",
        "properties",
        "required",
        "type",
    }
    assert set(node) <= supported
    for container in ("$defs", "properties"):
        children = node.get(container, {})
        assert isinstance(children, dict)
        for child in children.values():
            assert isinstance(child, dict)
            _assert_supported_schema_node(cast(dict[str, object], child))
    items = node.get("items")
    if items is not None:
        assert isinstance(items, dict)
        _assert_supported_schema_node(cast(dict[str, object], items))
    branches = node.get("anyOf", [])
    assert isinstance(branches, list)
    for branch in branches:
        assert isinstance(branch, dict)
        _assert_supported_schema_node(cast(dict[str, object], branch))


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
    settings = ProviderSettings(
        values=(("fast_mode", False), ("model_reasoning_effort", "xhigh"))
    )

    response = provider.submit(
        _request(_item(), _item("logical-scene-b"), settings=settings),
        lambda: False,
    )

    assert response.provider.provider == "openai"
    assert response.provider.adapter == ADAPTER_NAME
    assert response.provider.adapter_version == ADAPTER_VERSION
    assert response.provider.requested_model == "runtime-model-a"
    assert response.provider.resolved_model == "runtime-model-a"
    assert response.provider.settings == settings
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
    assert runner.requests[0].model_reasoning_effort == "xhigh"
    envelope = json.loads(runner.requests[0].stdin)
    assert envelope["template_version"] == PROMPT_TEMPLATE_VERSION
    assert envelope["request"]["consent_manifest_id"] == "consent-a"
    assert envelope["request"]["settings"] == {
        "fast_mode": False,
        "model_reasoning_effort": "xhigh",
    }
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


def test_cloud_adapter_uses_locked_model_when_cli_omits_redundant_metadata() -> None:
    output = {"items": []}
    events_without_model = tuple(
        {key: value for key, value in event.items() if key != "model"}
        if isinstance(event, dict)
        else event
        for event in _events(output)
    )
    runner = FakeRunner(SterileRunResult(events_without_model, "codex-cli 0.144"))

    response = CodexCliNarrativeProvider(runner=runner).submit(
        _request(model="runtime-model-a"),
        lambda: False,
    )

    assert runner.requests[0].model == "runtime-model-a"
    assert response.provider.requested_model == "runtime-model-a"
    assert response.provider.resolved_model == "runtime-model-a"


def test_cloud_adapter_rejects_conflicting_reported_model_metadata() -> None:
    output = {"items": []}
    conflicting_events = (
        *_events(output, model="runtime-model-a"),
        {"type": "turn.completed", "model": "different-runtime-model"},
    )
    provider = CodexCliNarrativeProvider(
        runner=FakeRunner(SterileRunResult(conflicting_events, "codex-cli 0.144"))
    )

    with pytest.raises(ProviderIdentityMismatchError) as conflict:
        provider.submit(_request(model="runtime-model-a"), lambda: False)

    assert conflict.value.error_code == "model_metadata_conflict"
    assert not conflict.value.transient


@pytest.mark.parametrize("invalid_model", [None, 1, "", " runtime-model-a "])
def test_cloud_adapter_rejects_malformed_reported_model_metadata(
    invalid_model: object,
) -> None:
    events = list(_events({"items": []}))
    events[0] = {"type": "thread.started", "model": invalid_model}
    provider = CodexCliNarrativeProvider(
        runner=FakeRunner(SterileRunResult(tuple(events), "codex-cli 0.144"))
    )

    with pytest.raises(ProviderOutputError) as invalid:
        provider.submit(_request(model="runtime-model-a"), lambda: False)

    assert invalid.value.error_code == "model_metadata_invalid"
    assert not invalid.value.transient


def test_response_schema_v3_recursively_matches_the_supported_subset() -> None:
    schema_root = files("renpy_story_mapper.narrative.schemas")
    with as_file(schema_root.joinpath("narrative_batch_v3.schema.json")) as path:
        schema = json.loads(path.read_text(encoding="utf-8"))
    nodes = _walk_schema(schema)

    assert schema["$id"] == RESPONSE_SCHEMA_VERSION
    assert schema["type"] == "object"
    assert "anyOf" not in schema
    _assert_supported_schema_node(cast(dict[str, object], schema))
    assert all("uniqueItems" not in node for node in nodes)
    for node in nodes:
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False
            assert set(cast(dict[str, object], node["properties"])) == set(
                cast(list[str], node["required"])
            )
        if "enum" in node or "const" in node:
            assert node.get("type") == "string"

    with as_file(schema_root.joinpath("narrative_batch_v2.schema.json")) as path:
        v2_text = path.read_text(encoding="utf-8")
        v2_schema = json.loads(v2_text)
    assert v2_text.count('"uniqueItems": true') == 4
    assert '"$id": "m13-narrative-batch-response-v2"' in v2_text

    def expected_v3(value: object) -> object:
        if isinstance(value, list):
            return [expected_v3(item) for item in value]
        if not isinstance(value, dict):
            return value
        migrated = {
            key: expected_v3(item)
            for key, item in value.items()
            if key != "uniqueItems"
        }
        if "enum" in migrated or "const" in migrated:
            migrated["type"] = "string"
        if migrated.get("$id") == "m13-narrative-batch-response-v2":
            migrated["$id"] = RESPONSE_SCHEMA_VERSION
        return migrated

    assert expected_v3(v2_schema) == schema


def test_schema_adapter_and_settings_changes_invalidate_old_cache_identity() -> None:
    settings = ProviderSettings(
        values=(("fast_mode", False), ("model_reasoning_effort", "high"))
    )

    def identity(adapter_version: str, schema_version: str) -> CacheIdentity:
        return CacheIdentity(
            logical_job_id="logical-job-a",
            input_revision_id="input-revision-a",
            normalized_input_hash="normalized-input-a",
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            response_schema_version=schema_version,
            provider=ProviderIdentity(
                provider="openai",
                adapter=ADAPTER_NAME,
                adapter_version=adapter_version,
                requested_model="runtime-model",
                resolved_model="runtime-model",
                settings=settings,
            ),
        )

    old = identity("m13-codex-cli-adapter-v1", "m13-narrative-batch-response-v2")
    previous_adapter = identity(
        "m13-codex-cli-adapter-v2",
        RESPONSE_SCHEMA_VERSION,
    )
    current = identity(ADAPTER_VERSION, RESPONSE_SCHEMA_VERSION)
    different_settings = CacheIdentity(
        logical_job_id=current.logical_job_id,
        input_revision_id=current.input_revision_id,
        normalized_input_hash=current.normalized_input_hash,
        prompt_template_version=current.prompt_template_version,
        response_schema_version=current.response_schema_version,
        provider=ProviderIdentity(
            provider=current.provider.provider,
            adapter=current.provider.adapter,
            adapter_version=current.provider.adapter_version,
            requested_model=current.provider.requested_model,
            resolved_model=current.provider.resolved_model,
            settings=ProviderSettings(
                values=(("fast_mode", False), ("model_reasoning_effort", "xhigh"))
            ),
        ),
    )

    assert current.key != old.key
    assert current.key != previous_adapter.key
    assert current.key != different_settings.key


@pytest.mark.parametrize("support_kind", ["evidence", "child"])
def test_python_handle_binding_rejects_duplicates_removed_from_schema(
    support_kind: str,
) -> None:
    table = PromptHandleTable.build(
        scope_id="scope-a",
        allowed_owner_ids=("scene-a",),
        evidence_references=(
            AuthorityReference(
                authority=AuthoritySystem.M11,
                record_kind="scene_evidence",
                record_id="evidence-a",
                owner_id="scene-a",
            ),
        ),
        child_claim_ids=("claim-a",),
    )

    with pytest.raises(HandleBindingError, match="duplicate"):
        if support_kind == "evidence":
            table.resolve_support(evidence_handles=("E1", "E1"))
        else:
            table.resolve_support(child_claim_handles=("C1", "C1"))


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


def test_adapter_enforces_consent_binding_input_limits_and_rejects_unknown_settings() -> None:
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
    with pytest.raises(ValueError, match="requested model"):
        _request().__class__(
            request_id="request-a",
            consent_manifest_id="consent-a",
            requested_model="",
            settings=ProviderSettings(),
            items=(_item(),),
            timeout_seconds=1.0,
        )
    with pytest.raises(ProviderRuntimeConfigurationError) as settings_error:
        provider.submit(
            _request(settings=ProviderSettings(values=(("temperature", 0.2),))),
            lambda: False,
        )
    assert settings_error.value.error_code == "runtime_configuration_rejected"
    assert runner.status_calls == 0
    with pytest.raises(ProviderLimitError) as input_error:
        provider.submit(_request(maximum_input_bytes=100), lambda: False)
    assert input_error.value.error_code == "input_limit"
    assert not runner.requests


@pytest.mark.parametrize("reasoning_effort", ["low", "medium", "high", "xhigh"])
def test_adapter_accepts_bounded_settings_and_passes_reasoning_explicitly(
    reasoning_effort: str,
) -> None:
    runner = FakeRunner(SterileRunResult(_events({"items": []}), None))
    settings = ProviderSettings(
        values=(
            ("fast_mode", False),
            ("model_reasoning_effort", reasoning_effort),
        )
    )

    response = CodexCliNarrativeProvider(runner=runner).submit(
        _request(settings=settings),
        lambda: False,
    )

    assert runner.requests[0].model_reasoning_effort == reasoning_effort
    assert response.provider.settings == settings


@pytest.mark.parametrize(
    "settings",
    [
        ProviderSettings(values=(("fast_mode", True),)),
        ProviderSettings(values=(("fast_mode", "false"),)),
        ProviderSettings(values=(("model_reasoning_effort", "minimal"),)),
        ProviderSettings(values=(("model_reasoning_effort", 1),)),
    ],
)
def test_adapter_rejects_unknown_setting_values_before_runner_status_or_spawn(
    settings: ProviderSettings,
) -> None:
    runner = FakeRunner(SterileRunResult(_events({"items": []}), None))

    with pytest.raises(ProviderRuntimeConfigurationError) as error:
        CodexCliNarrativeProvider(runner=runner).submit(
            _request(settings=settings),
            lambda: False,
        )

    assert error.value.error_code == "runtime_configuration_rejected"
    assert runner.requests == []
    assert runner.status_calls == 0


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
        ("transport_failure", ProviderTransportError, True),
        ("server_transient", ProviderServerTransientError, True),
        ("policy_violation", ProviderPolicyViolationError, False),
        ("output_schema_rejected", ProviderSchemaRejectedError, False),
        (
            "runtime_configuration_rejected",
            ProviderRuntimeConfigurationError,
            False,
        ),
        ("authentication_failed", ProviderAuthenticationError, False),
        ("provider_process_failed", ProviderProcessError, False),
        ("unrecognized_runner_code", ProviderProcessError, False),
        ("provider_unavailable", ProviderUnavailableError, False),
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
    expected_code = (
        "provider_process_failed"
        if runner_code == "unrecognized_runner_code"
        else runner_code
    )
    assert error.error_code == expected_code
    assert error.transient is transient
    assert error.transmission_disposition is TransmissionDisposition.UNKNOWN
    assert "SECRET-STORY" not in str(exc_info.value)


def test_runner_transmission_attestation_survives_provider_error_mapping() -> None:
    runner = FakeRunner(
        error=SterileRunnerError(
            "authentication_failed",
            "sanitized",
            transmission_disposition=TransmissionDisposition.TRANSMITTED,
        )
    )
    provider = CodexCliNarrativeProvider(runner=runner)

    with pytest.raises(ProviderAuthenticationError) as raised:
        provider.submit(_request(), lambda: False)

    assert raised.value.transmission_disposition is TransmissionDisposition.TRANSMITTED


def test_direct_command_has_no_shell_fallback_and_passes_selected_reasoning() -> None:
    program, arguments = build_sterile_codex_command(
        "C:/synthetic/codex.exe",
        model="runtime-model-b",
        schema_path=Path("schema.json"),
        model_reasoning_effort="high",
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
    assert "fast_mode" in arguments
    assert arguments[arguments.index("fast_mode") - 1] == "--disable"
    assert 'model_reasoning_effort="high"' in arguments


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
    assert policy_error.value.transmission_disposition is TransmissionDisposition.TRANSMITTED
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
    assert failure.value.transmission_disposition is TransmissionDisposition.TRANSMITTED
    assert "SECRET-STORY" not in str(failure.value)


def test_sterile_runner_attests_not_transmitted_before_process_boundary(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    runner = SterileCodexRunner(executable_resolver=lambda _command: (None, None))

    with pytest.raises(SterileRunnerError) as raised:
        runner.execute(
            SterileRunRequest(
                model="runtime-model-a",
                schema_path=schema.resolve(),
                stdin=b"{}",
                timeout_seconds=1.0,
                maximum_output_bytes=100_000,
            ),
            lambda: False,
        )

    assert raised.value.error_code == "provider_unavailable"
    assert raised.value.transmission_disposition is (
        TransmissionDisposition.NOT_TRANSMITTED
    )


@pytest.mark.parametrize(
    ("stderr", "error_code", "transient"),
    [
        (b"429 rate limit SECRET-STORY", "rate_limited", True),
        (b"request timed out SECRET-STORY", "timeout", True),
        (b"connection reset by peer SECRET-STORY", "transport_failure", True),
        (b"HTTP 503 service unavailable SECRET-STORY", "server_transient", True),
        (
            b"output schema is invalid: uniqueItems SECRET-STORY",
            "output_schema_rejected",
            False,
        ),
        (
            b"unknown config key model_reasoning_effort SECRET-STORY",
            "runtime_configuration_rejected",
            False,
        ),
        (
            b"invalid value 'max' for model_reasoning_effort SECRET-STORY",
            "runtime_configuration_rejected",
            False,
        ),
        (b"HTTP 401 unauthorized SECRET-STORY", "authentication_failed", False),
        (b"unclassified child exit SECRET-STORY", "provider_process_failed", False),
    ],
)
def test_process_failure_classification_is_sanitized_and_fail_closed(
    stderr: bytes,
    error_code: str,
    transient: bool,
) -> None:
    with pytest.raises(SterileRunnerError) as raised:
        SterileCodexRunner._raise_process_failure(stderr)

    assert raised.value.error_code == error_code
    assert raised.value.transient is transient
    assert "SECRET-STORY" not in str(raised.value)
    assert all("SECRET-STORY" not in str(argument) for argument in raised.value.args)


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
