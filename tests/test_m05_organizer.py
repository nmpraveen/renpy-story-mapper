from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from importlib.resources import as_file, files
from pathlib import Path

import pytest

from renpy_story_mapper.organization.cache import build_cache_key
from renpy_story_mapper.organization.chunking import (
    MAX_ASSIGNED_BEATS,
    MAX_CHARS,
    build_arc_request,
    build_event_chunks,
    build_reconciliation_request,
)
from renpy_story_mapper.organization.contracts import (
    BeatRecord,
    CodexMode,
    FactRecord,
    OrganizationConstraints,
    OrganizationRequest,
    OrganizationStage,
    ProviderState,
)
from renpy_story_mapper.organization.errors import (
    ConsentRequiredError,
    InvalidProviderOutputError,
    OrganizationCancelledError,
    PolicyViolationError,
    ProviderRateLimitError,
    ProviderRefusalError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from renpy_story_mapper.organization.provider import CodexCliProvider
from renpy_story_mapper.organization.validation import validate_result


def _beat(number: int, *, kind: str = "narrative", scene: str = "scene") -> BeatRecord:
    return BeatRecord(
        id=f"beat-{number}",
        scene_id=scene,
        kind=kind,
        order=number,
        text=f"Synthetic story line {number}",
        speaker="Ava",
        relative_path="synthetic/story.rpy",
        start_line=number,
        end_line=number,
        evidence_ids=(f"evidence-{number}",),
        fact_ids=("fact-1",) if number == 1 else (),
        outgoing_ids=(f"beat-{number + 1}",),
    )


def _request(stage: OrganizationStage = OrganizationStage.EVENTS) -> OrganizationRequest:
    return OrganizationRequest(
        run_id="run-1",
        chunk_id="chunk-1",
        scope_id="scope-1",
        stage=stage,
        payload={"synthetic": True},
        constraints=OrganizationConstraints(
            ordered_member_ids=("beat-1", "beat-2", "beat-3"),
            required_member_ids=frozenset({"beat-1", "beat-2", "beat-3"}),
            fact_ids=frozenset({"fact-1"}),
            evidence_ids=frozenset({"evidence-1", "evidence-2", "evidence-3"}),
            character_names=frozenset({"Ava"}),
        ),
        cloud_consent_run_id="run-1",
        timeout_seconds=0.05,
    )


def _valid_payload(stage: OrganizationStage = OrganizationStage.EVENTS) -> dict[str, object]:
    return {
        "stage": stage.value,
        "groups": [
            {
                "id": "group-1",
                "title": "A synthetic turning point",
                "summary": "Ava makes an evidence-supported choice.",
                "member_ids": ["beat-1", "beat-2", "beat-3"],
                "characters": ["Ava"],
                "importance": "turning point",
                "outcomes": ["The synthetic route continues."],
                "promoted_fact_ids": ["fact-1"],
                "claims": [{"text": "Ava commits to the route.", "evidence_ids": ["evidence-2"]}],
                "warnings": [],
            }
        ],
        "ungrouped_ids": [],
    }


def test_chunking_honors_limits_boundaries_context_and_unique_membership() -> None:
    beats = [_beat(number) for number in range(1, MAX_ASSIGNED_BEATS + 8)]
    beats[60] = _beat(61, kind="choice")
    requests = build_event_chunks(
        run_id="run",
        scope_id="scope",
        beats=beats,
        facts=[FactRecord("fact-1", "points += 1", "points +1", "proven", ("evidence-1",))],
    )
    assigned = [
        member
        for request in requests
        for member in request.constraints.ordered_member_ids
    ]
    assert assigned == [beat.id for beat in beats]
    assert len(assigned) == len(set(assigned))
    assert all(
        len(request.constraints.ordered_member_ids) <= MAX_ASSIGNED_BEATS
        for request in requests
    )
    assert all(len(request.constraints.context_member_ids) <= 2 for request in requests)
    assert all(
        len(json.dumps(request.payload, ensure_ascii=False)) <= MAX_CHARS
        for request in requests
    )
    assert all(
        request.constraints.context_member_ids.isdisjoint(
            request.constraints.ordered_member_ids
        )
        for request in requests
    )


def test_chunking_splits_scenes_and_rejects_duplicate_or_oversized_beats() -> None:
    chunks = build_event_chunks(
        run_id="run",
        scope_id="scope",
        beats=[_beat(1, scene="a"), _beat(2, scene="b")],
        facts=[FactRecord("fact-1", "points += 1", "points +1", "proven", ("evidence-1",))],
    )
    assert [chunk.payload["scene_id"] for chunk in chunks] == ["a", "b"]
    with pytest.raises(ValueError, match="unique"):
        build_event_chunks(run_id="run", scope_id="scope", beats=[_beat(1), _beat(1)])
    missing_fact = BeatRecord(**{**_beat(99).__dict__, "fact_ids": ("missing-fact",)})
    with pytest.raises(ValueError, match="fact ID"):
        build_event_chunks(run_id="run", scope_id="scope", beats=[missing_fact])
    huge = _beat(1)
    huge = BeatRecord(**{**huge.__dict__, "text": "x" * MAX_CHARS})
    with pytest.raises(ValueError, match="48,000"):
        build_event_chunks(
            run_id="run",
            scope_id="scope",
            beats=[huge],
            facts=[
                FactRecord(
                    "fact-1", "points += 1", "points +1", "proven", ("evidence-1",)
                )
            ],
        )


def test_three_stage_requests_keep_full_dialogue_out_of_arc_stage() -> None:
    reconcile = build_reconciliation_request(
        run_id="run",
        chunk_id="reconcile",
        scope_id="scene",
        events=[{"id": "event-1", "summary": "Summary"}],
        ordered_event_ids=("event-1",),
        evidence_ids=frozenset({"evidence-1"}),
        fact_ids=frozenset({"fact-1"}),
    )
    arc = build_arc_request(
        run_id="run",
        chunk_id="arcs",
        scope_id="story",
        event_summaries=[{"id": "event-1", "summary": "Summary", "facts": ["fact-1"]}],
        ordered_event_ids=("event-1",),
        evidence_ids=frozenset({"evidence-1"}),
        fact_ids=frozenset({"fact-1"}),
        characters=frozenset({"Ava"}),
        local_connectivity=[{"source": "event-1", "target": "event-2"}],
    )
    assert reconcile.stage is OrganizationStage.RECONCILE
    assert arc.stage is OrganizationStage.ARCS
    assert "dialogue" not in json.dumps(arc.payload).lower()
    assert arc.payload["local_connectivity"] == [
        {"source": "event-1", "target": "event-2"}
    ]


def test_cache_key_covers_content_order_provider_model_prompt_and_schema() -> None:
    request = _request()
    baseline = build_cache_key(
        request,
        provider_mode=CodexMode.CODEX_CHATGPT,
        model_fingerprint="balanced",
        prompt_version="p1",
        schema_version="s1",
    )
    duplicate = build_cache_key(
        request,
        provider_mode=CodexMode.CODEX_CHATGPT,
        model_fingerprint="balanced",
        prompt_version="p1",
        schema_version="s1",
    )
    assert baseline.digest() == duplicate.digest()
    variants = [
        build_cache_key(
            request,
            provider_mode=mode,
            model_fingerprint=model,
            prompt_version=prompt,
            schema_version=schema,
        ).digest()
        for mode, model, prompt, schema in [
            (CodexMode.CODEX_LMSTUDIO, "balanced", "p1", "s1"),
            (CodexMode.CODEX_CHATGPT, "different", "p1", "s1"),
            (CodexMode.CODEX_CHATGPT, "balanced", "p2", "s1"),
            (CodexMode.CODEX_CHATGPT, "balanced", "p1", "s2"),
        ]
    ]
    assert baseline.digest() not in variants


def test_validator_accepts_exact_ids_coverage_order_and_evidence() -> None:
    result = validate_result(_valid_payload(), _request())
    assert result.groups[0].member_ids == ("beat-1", "beat-2", "beat-3")
    assert result.groups[0].promoted_fact_ids == ("fact-1",)


def test_all_packaged_stage_schemas_are_strict_and_self_contained() -> None:
    schema_root = files("renpy_story_mapper.organization.schemas")
    for stage in OrganizationStage:
        with as_file(schema_root.joinpath(f"{stage.value}.schema.json")) as path:
            schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["additionalProperties"] is False
        assert schema["properties"]["stage"]["const"] == stage.value
        assert "$defs" in schema
        serialized = json.dumps(schema)
        assert "events.schema.json" not in serialized


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update({"authoritative_edges": []}), "root fields"),
        (lambda value: value["groups"][0]["member_ids"].append("invented"), "unknown member"),
        (lambda value: value["groups"][0]["member_ids"].append("beat-1"), "duplicate"),
        (lambda value: value["groups"][0].update({"title": "x" * 81}), "80"),
        (lambda value: value["groups"][0].update({"summary": "x" * 321}), "320"),
        (lambda value: value["groups"][0]["promoted_fact_ids"].append("invented"), "invented"),
        (lambda value: value["groups"][0]["characters"].append("Unknown"), "character"),
        (lambda value: value["groups"][0]["claims"][0].update({"evidence_ids": []}), "evidence"),
        (
            lambda value: value["groups"][0]["claims"][0]["evidence_ids"].append("invented"),
            "invented",
        ),
        (lambda value: value["groups"][0].update({"new_edge": "beat-9"}), "forbidden"),
    ],
)
def test_validator_rejects_malformed_or_invented_authority(
    mutate: Callable[[dict[str, object]], object], message: str
) -> None:
    payload = deepcopy(_valid_payload())
    mutate(payload)
    with pytest.raises(InvalidProviderOutputError, match=message):
        validate_result(payload, _request())


def test_validator_rejects_missing_coverage_crossings_and_context_membership() -> None:
    missing = _valid_payload()
    missing["groups"][0]["member_ids"] = ["beat-1"]
    with pytest.raises(InvalidProviderOutputError, match="coverage"):
        validate_result(missing, _request())
    crossed = _valid_payload()
    crossed["groups"][0]["member_ids"] = ["beat-2", "beat-1", "beat-3"]
    with pytest.raises(InvalidProviderOutputError, match="order"):
        validate_result(crossed, _request())
    request = _request()
    request = OrganizationRequest(
        **{
            **request.__dict__,
            "constraints": OrganizationConstraints(
                ordered_member_ids=("beat-1", "beat-2", "beat-3"),
                required_member_ids=frozenset({"beat-1", "beat-2"}),
                context_member_ids=frozenset({"beat-3"}),
                fact_ids=request.constraints.fact_ids,
                evidence_ids=request.constraints.evidence_ids,
                character_names=request.constraints.character_names,
            ),
        }
    )
    with pytest.raises(InvalidProviderOutputError, match="context-only"):
        validate_result(_valid_payload(), request)


class FakeProcess:
    def __init__(
        self,
        output: bytes,
        *,
        exit_code: int = 0,
        stderr: bytes = b"",
        never_finishes: bool = False,
        ignore_terminate: bool = False,
        start_ok: bool = True,
    ) -> None:
        self.output = output
        self.stderr = stderr
        self.exit_code = exit_code
        self.never_finishes = never_finishes
        self.ignore_terminate = ignore_terminate
        self.start_ok = start_ok
        self.started: tuple[str, list[str]] | None = None
        self.cwd = ""
        self.stdin = b""
        self.terminated = False
        self.killed = False
        self.read = False
        self.wait_arguments: list[int] = []

    def setWorkingDirectory(self, directory: str) -> None:
        self.cwd = directory

    def start(self, program: str, arguments: list[str]) -> None:
        self.started = (program, arguments)

    def waitForStarted(self, msecs: int = 30000) -> bool:
        return self.start_ok

    def write(self, data: bytes) -> int:
        self.stdin += data
        return len(data)

    def closeWriteChannel(self) -> None:
        pass

    def waitForReadyRead(self, msecs: int = 30000) -> bool:
        return True

    def waitForFinished(self, msecs: int = 30000) -> bool:
        self.wait_arguments.append(msecs)
        terminated = self.terminated and not self.ignore_terminate
        return not self.never_finishes or terminated or self.killed

    def readAllStandardOutput(self) -> bytes:
        if self.read:
            return b""
        self.read = True
        return self.output

    def readAllStandardError(self) -> bytes:
        return self.stderr

    def exitCode(self) -> int:
        return self.exit_code

    def state(self) -> object:
        return object()

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


def _jsonl(payload: object) -> bytes:
    event = {
        "type": "item.completed",
        "item": {"type": "agent_message", "text": json.dumps(payload)},
    }
    return (json.dumps(event) + "\n").encode()


def test_provider_commands_are_direct_stdin_only_and_sterile() -> None:
    usage = json.dumps(
        {
            "type": "turn.completed",
            "model": "synthetic-model",
            "usage": {"input_tokens": 123, "output_tokens": 45},
        }
    ).encode()
    process = FakeProcess(usage + b"\n" + _jsonl(_valid_payload()))
    provider = CodexCliProvider(
        CodexMode.CODEX_CHATGPT, process_factory=lambda: process
    )
    result = provider.organize(_request(), lambda _percent, _status: None, lambda: False)
    assert result.groups[0].id == "group-1"
    assert process.started is not None
    program, args = process.started
    assert program == "codex"
    assert args == [
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--ignore-user-config",
        "--ignore-rules",
            "--json",
            "--output-schema",
            args[9],
            "-",
        ]
    assert Path(process.cwd).name.startswith("renpy-story-organizer-")
    assert not Path(process.cwd).exists()
    assert b"synthetic" in process.stdin
    assert "--output-last-message" not in args
    assert "--enable" not in args
    assert result.metadata is not None
    assert result.metadata.model_identifier == "synthetic-model"
    assert result.metadata.input_tokens == 123
    assert result.metadata.output_tokens == 45
    assert len(result.metadata.input_hash) == 64
    assert len(result.metadata.output_hash) == 64


def test_lmstudio_command_adds_only_locked_local_flags() -> None:
    provider = CodexCliProvider(CodexMode.CODEX_LMSTUDIO)
    _program, args = provider.command(Path("schema.json"), model="local-model")
    assert args[-4:] == ["--oss", "--local-provider", "lmstudio", "-"]
    assert args[args.index("--model") + 1] == "local-model"


def test_cloud_provider_requires_fresh_matching_consent_before_process_creation() -> None:
    called = False

    def factory() -> FakeProcess:
        nonlocal called
        called = True
        return FakeProcess(b"")

    request = _request()
    request = OrganizationRequest(**{**request.__dict__, "cloud_consent_run_id": "old-run"})
    with pytest.raises(ConsentRequiredError):
        CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=factory).organize(
            request, lambda _p, _s: None, lambda: False
        )
    assert not called


def test_provider_repairs_once_then_accepts_and_never_more_than_twice() -> None:
    processes = [FakeProcess(_jsonl({"bad": True})), FakeProcess(_jsonl(_valid_payload()))]
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=lambda: processes.pop(0))
    result = provider.organize(_request(), lambda _p, _s: None, lambda: False)
    assert result.attempts == 2
    failures = [FakeProcess(_jsonl({"bad": True})), FakeProcess(_jsonl({"still": "bad"}))]
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=lambda: failures.pop(0))
    with pytest.raises(InvalidProviderOutputError, match="twice"):
        provider.organize(_request(), lambda _p, _s: None, lambda: False)
    assert not failures


@pytest.mark.parametrize(
    "marker", ["command_execution", "mcp_tool_call", "web_search", "file_change"]
)
def test_provider_terminates_and_rejects_policy_events(marker: str) -> None:
    process = FakeProcess((json.dumps({"type": marker}) + "\n").encode())
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=lambda: process)
    with pytest.raises(PolicyViolationError):
        provider.organize(_request(), lambda _p, _s: None, lambda: False)
    assert process.terminated


def test_provider_cancellation_terminates_with_bounded_wait_and_cleans_temp() -> None:
    process = FakeProcess(b"", never_finishes=True, ignore_terminate=True)
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=lambda: process)
    with pytest.raises(OrganizationCancelledError):
        provider.organize(_request(), lambda _p, _s: None, lambda: True)
    assert process.terminated
    assert process.killed
    assert sum(process.wait_arguments[-2:]) == 1_950
    assert not Path(process.cwd).exists()


def test_provider_timeout_rate_limit_missing_executable_and_sanitized_errors() -> None:
    timeout = FakeProcess(b"", never_finishes=True)
    with pytest.raises(ProviderTimeoutError):
        CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=lambda: timeout).organize(
            _request(), lambda _p, _s: None, lambda: False
        )
    limited = FakeProcess(b"", exit_code=1, stderr=b"429 rate limit SECRET-STORY")
    with pytest.raises(ProviderRateLimitError) as exc_info:
        CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=lambda: limited).organize(
            _request(), lambda _p, _s: None, lambda: False
        )
    assert "SECRET-STORY" not in str(exc_info.value)
    missing = CodexCliProvider(CodexMode.CODEX_CHATGPT, executable="definitely-not-codex")
    assert missing.status().state is ProviderState.MISSING
    with pytest.raises(ProviderUnavailableError):
        missing.organize(_request(), lambda _p, _s: None, lambda: False)


@pytest.mark.parametrize(
    ("stderr", "error_type"),
    [
        (b"provider refusal SECRET-STORY", ProviderRefusalError),
        (b"not logged in SECRET-STORY", ProviderUnavailableError),
        (b"LM Studio connection refused SECRET-STORY", ProviderUnavailableError),
    ],
)
def test_provider_classifies_refusal_auth_and_lmstudio_without_leaking_raw_errors(
    stderr: bytes, error_type: type[Exception]
) -> None:
    process = FakeProcess(b"", exit_code=1, stderr=stderr)
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=lambda: process)
    with pytest.raises(error_type) as exc_info:
        provider.organize(_request(), lambda _p, _s: None, lambda: False)
    assert "SECRET-STORY" not in str(exc_info.value)


def test_provider_retries_malformed_jsonl_once_and_rejects_second_failure() -> None:
    processes = [FakeProcess(b"not-json\n"), FakeProcess(b"still-not-json\n")]
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=lambda: processes.pop(0))
    with pytest.raises(InvalidProviderOutputError, match="twice"):
        provider.organize(_request(), lambda _p, _s: None, lambda: False)
    assert not processes


def test_provider_reports_process_start_failure_without_writing_input() -> None:
    process = FakeProcess(b"", start_ok=False)
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=lambda: process)
    with pytest.raises(ProviderUnavailableError, match="could not start"):
        provider.organize(_request(), lambda _p, _s: None, lambda: False)
    assert process.stdin == b""
