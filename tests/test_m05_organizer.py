from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from importlib.resources import as_file, files
from pathlib import Path

import pytest
from PySide6.QtCore import QProcess, QProcessEnvironment

import renpy_story_mapper.organization.provider as provider_module
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
    serialize_organization_prompt,
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
    assigned = [member for request in requests for member in request.constraints.ordered_member_ids]
    assert assigned == [beat.id for beat in beats]
    assert len(assigned) == len(set(assigned))
    assert all(
        len(request.constraints.ordered_member_ids) <= MAX_ASSIGNED_BEATS for request in requests
    )
    assert all(len(request.constraints.context_member_ids) <= 2 for request in requests)
    assert all(
        len(serialize_organization_prompt(request, repair=repair)) <= MAX_CHARS
        for request in requests
        for repair in (False, True)
    )
    assert all(
        request.constraints.context_member_ids.isdisjoint(request.constraints.ordered_member_ids)
        for request in requests
    )


def test_dense_boundaries_pack_scene_instead_of_flushing_every_beat() -> None:
    kinds = ("condition", "choice", "jump", "return")
    beats = [
        _beat(number, kind=kinds[(number - 1) % len(kinds)])
        for number in range(1, 41)
    ]

    requests = build_event_chunks(
        run_id="run",
        scope_id="scope",
        beats=beats,
        facts=[FactRecord("fact-1", "points += 1", "points +1", "proven", ("evidence-1",))],
    )

    assert len(requests) == 1
    assert requests[0].constraints.ordered_member_ids == tuple(beat.id for beat in beats)


def test_required_split_prefers_strongest_nearby_boundary() -> None:
    beats = [_beat(number) for number in range(1, 131)]
    beats[112] = _beat(113, kind="return")
    beats[118] = _beat(119, kind="condition")

    requests = build_event_chunks(
        run_id="run",
        scope_id="scope",
        beats=beats,
        facts=[FactRecord("fact-1", "points += 1", "points +1", "proven", ("evidence-1",))],
    )

    assert requests[0].constraints.ordered_member_ids == tuple(
        beat.id for beat in beats[:113]
    )
    assert [
        member for request in requests for member in request.constraints.ordered_member_ids
    ] == [beat.id for beat in beats]


def test_fact_bearing_technical_beat_is_required_without_raw_command_text() -> None:
    technical = BeatRecord(
        **{
            **_beat(1, kind="opaque").__dict__,
            "text": "$ secret_flag = calculate_dynamic_value()",
            "fact_ids": ("fact-1",),
        }
    )
    fallback: list[str] = []

    requests = build_event_chunks(
        run_id="run",
        scope_id="scope",
        beats=[technical],
        facts=[FactRecord("fact-1", "secret_flag = ?", "unknown", "possible", ("evidence-1",))],
        on_deterministic_fallback=lambda beat: fallback.append(beat.id),
    )

    assert fallback == []
    assert len(requests) == 1
    assert requests[0].constraints.required_member_ids == frozenset({technical.id})
    payload_beats = requests[0].payload["beats"]
    payload_facts = requests[0].payload["facts"]
    assert isinstance(payload_beats, list) and isinstance(payload_beats[0], dict)
    assert isinstance(payload_facts, list) and isinstance(payload_facts[0], dict)
    assert "text" not in payload_beats[0]
    assert payload_facts[0]["id"] == "fact-1"


def test_factless_technical_only_scene_can_stay_deterministic_without_provider() -> None:
    technical = BeatRecord(**{**_beat(2, kind="show").__dict__, "fact_ids": ()})
    fallback: list[str] = []

    requests = build_event_chunks(
        run_id="run",
        scope_id="scope",
        beats=[technical],
        on_deterministic_fallback=lambda beat: fallback.append(beat.id),
    )

    assert requests == []
    assert fallback == [technical.id]


def test_prompt_embeds_exact_raw_json_output_contract_for_initial_and_repair() -> None:
    request = _request()
    initial = json.loads(serialize_organization_prompt(request, repair=False))
    repair = json.loads(serialize_organization_prompt(request, repair=True))

    for envelope in (initial, repair):
        output = envelope["output_contract"]
        assert output["top_level"]["exact_keys"] == [
            "stage",
            "groups",
            "ungrouped_ids",
        ]
        assert output["top_level"]["stage"] == "events"
        assert output["group"]["exact_keys"] == [
            "id",
            "title",
            "summary",
            "member_ids",
            "characters",
            "importance",
            "outcomes",
            "promoted_fact_ids",
            "claims",
            "warnings",
        ]
        assert output["claim"]["exact_keys"] == ["text", "evidence_ids"]
        assert output["claim"]["text"].startswith("non-empty")
        assert "unique" in output["ordering"]
        assert "non-crossing" in output["ordering"]
        assert envelope["contract"]["required_member_ids"] == [
            "beat-1",
            "beat-2",
            "beat-3",
        ]
        assert "Do not emit analysis" in output["serialization"]
    assert "Produce a new response from scratch" in repair["instruction"]
    assert "Do not use Markdown" in initial["instruction"]


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
            facts=[FactRecord("fact-1", "points += 1", "points +1", "proven", ("evidence-1",))],
        )

    fallback_ids: list[str] = []
    requests = build_event_chunks(
        run_id="run",
        scope_id="scope",
        beats=[huge, _beat(2)],
        facts=[FactRecord("fact-1", "points += 1", "points +1", "proven", ("evidence-1",))],
        on_oversized=lambda beat: fallback_ids.append(beat.id),
    )
    assert fallback_ids == [huge.id]
    assert [
        member for request in requests for member in request.constraints.ordered_member_ids
    ] == ["beat-2"]


def test_chunking_preserves_supplied_chronology_across_reverse_lexical_scenes() -> None:
    beats = [_beat(1, scene="z-last-lexically"), _beat(2, scene="a-first-lexically")]
    chunks = build_event_chunks(
        run_id="run",
        scope_id="scope",
        beats=beats,
        facts=[FactRecord("fact-1", "points += 1", "points +1", "proven", ("evidence-1",))],
    )
    assert [chunk.payload["scene_id"] for chunk in chunks] == [
        "z-last-lexically",
        "a-first-lexically",
    ]
    assert [member for chunk in chunks for member in chunk.constraints.ordered_member_ids] == [
        "beat-1",
        "beat-2",
    ]


def test_chunking_serializes_and_authorizes_all_evidenced_speakers() -> None:
    beat = BeatRecord(
        **{
            **_beat(1).__dict__,
            "speaker_names": ("Ben", "Ava", "Cara", "Ben"),
        }
    )
    chunks = build_event_chunks(
        run_id="run",
        scope_id="scope",
        beats=[beat],
        facts=[FactRecord("fact-1", "points += 1", "points +1", "proven", ("evidence-1",))],
    )
    payload_beat = chunks[0].payload["beats"][0]
    assert payload_beat["speaker"] == "Ava"
    assert payload_beat["speakers"] == ["Ava", "Ben", "Cara"]
    assert chunks[0].constraints.character_names == frozenset({"Ava", "Ben", "Cara"})


@pytest.mark.parametrize("speaker_name", ["", " padded", "x" * 121])
def test_chunking_rejects_invalid_evidenced_speaker_names(speaker_name: str) -> None:
    beat = BeatRecord(
        **{
            **_beat(2).__dict__,
            "speaker": None,
            "speaker_names": (speaker_name,),
        }
    )
    with pytest.raises(ValueError, match="Speaker names"):
        build_event_chunks(run_id="run", scope_id="scope", beats=[beat])


def test_multi_speaker_metadata_remains_inside_exact_chunk_size_limit() -> None:
    speakers = tuple(f"Speaker-{index:02d}-{'x' * 80}" for index in range(40))
    beat = BeatRecord(
        **{
            **_beat(2).__dict__,
            "speaker": None,
            "speaker_names": speakers,
            "text": "n" * 37_000,
        }
    )
    chunks = build_event_chunks(run_id="run", scope_id="scope", beats=[beat])
    assert len(chunks) == 1
    assert chunks[0].payload["beats"][0]["speakers"] == list(speakers)
    assert all(
        len(serialize_organization_prompt(chunks[0], repair=repair)) <= MAX_CHARS
        for repair in (False, True)
    )


@pytest.mark.parametrize(
    ("speaker", "speaker_names", "message"),
    [
        (None, "Ada", "sequence"),
        (None, 42, "sequence"),
        (None, ("Ada", 42), "members"),
        (42, (), "speaker must be text"),
    ],
)
def test_chunking_rejects_runtime_invalid_speaker_types(
    speaker: object, speaker_names: object, message: str
) -> None:
    beat = BeatRecord(
        **{
            **_beat(2).__dict__,
            "speaker": speaker,
            "speaker_names": speaker_names,
        }
    )
    with pytest.raises(ValueError, match=message):
        build_event_chunks(run_id="run", scope_id="scope", beats=[beat])


def test_chunk_limit_reduces_context_and_repartitions_for_fact_payload() -> None:
    near_limit = BeatRecord(**{**_beat(3).__dict__, "text": "x" * 43_000, "fact_ids": ("fact-1",)})
    chunks = build_event_chunks(
        run_id="run",
        scope_id="scope",
        beats=[_beat(1), _beat(2, kind="choice"), near_limit],
        facts=[
            FactRecord(
                "fact-1",
                "points += 1 " + "f" * 1_000,
                "points +1",
                "proven",
                ("evidence-1",),
            )
        ],
    )
    assert [member for chunk in chunks for member in chunk.constraints.ordered_member_ids] == [
        "beat-1",
        "beat-2",
        "beat-3",
    ]
    assert all(
        len(serialize_organization_prompt(chunk, repair=repair)) <= MAX_CHARS
        for chunk in chunks
        for repair in (False, True)
    )
    final_chunk = next(
        chunk for chunk in chunks if "beat-3" in chunk.constraints.ordered_member_ids
    )
    assert "beat-2" not in final_chunk.constraints.context_member_ids
    assert len(final_chunk.constraints.context_member_ids) < 2

    large_a = BeatRecord(
        **{**_beat(10).__dict__, "text": "a" * 22_000, "fact_ids": ("large-fact",)}
    )
    large_b = BeatRecord(
        **{**_beat(11).__dict__, "text": "b" * 22_000, "fact_ids": ("large-fact",)}
    )
    fact_heavy = build_event_chunks(
        run_id="run",
        scope_id="scope",
        beats=[large_a, large_b],
        facts=[
            FactRecord(
                "large-fact",
                "expression " + "f" * 5_000,
                "value",
                "proven",
                ("evidence-large",),
            )
        ],
    )
    assert len(fact_heavy) == 2
    assert all(
        len(serialize_organization_prompt(chunk, repair=repair)) <= MAX_CHARS
        for chunk in fact_heavy
        for repair in (False, True)
    )


def test_three_stage_requests_keep_full_dialogue_out_of_arc_stage() -> None:
    reconcile = build_reconciliation_request(
        run_id="run",
        chunk_id="reconcile",
        scope_id="scene",
        events=[
            {
                "id": "event-1",
                "title": "Event One",
                "summary": "Summary",
                "member_ids": ["beat-1"],
            }
        ],
        ordered_event_ids=("event-1",),
        evidence_ids=frozenset({"evidence-1"}),
        fact_ids=frozenset({"fact-1"}),
    )
    arc = build_arc_request(
        run_id="run",
        chunk_id="arcs",
        scope_id="story",
        event_summaries=[
            {
                "id": "event-1",
                "title": "Event One",
                "summary": "Summary",
                "major_fact_ids": ["fact-1"],
                "characters": ["Ava"],
                "importance": "major",
                "outcomes": ["Outcome"],
                "evidence_ids": ["evidence-1"],
            },
            {
                "id": "event-2",
                "title": "Event Two",
                "summary": "Next summary",
                "major_fact_ids": [],
                "characters": ["Ava"],
                "importance": "supporting",
                "outcomes": [],
                "evidence_ids": ["evidence-1"],
            },
        ],
        ordered_event_ids=("event-1", "event-2"),
        evidence_ids=frozenset({"evidence-1"}),
        fact_ids=frozenset({"fact-1"}),
        characters=frozenset({"Ava"}),
        local_connectivity=[{"source": "event-1", "target": "event-2"}],
    )
    assert reconcile.stage is OrganizationStage.RECONCILE
    assert arc.stage is OrganizationStage.ARCS
    assert "dialogue" not in json.dumps(arc.payload).lower()
    assert arc.payload["local_connectivity"] == [{"source": "event-1", "target": "event-2"}]

    for forbidden_field in (
        "dialogue",
        "narration",
        "source_text",
        "source_location",
        "condition",
    ):
        forbidden = dict(arc.payload["events"][0])
        forbidden[forbidden_field] = "raw story text"
        with pytest.raises(ValueError, match="allowlist"):
            build_arc_request(
                run_id="run",
                chunk_id="arcs",
                scope_id="story",
                event_summaries=[forbidden],
                ordered_event_ids=("event-1",),
                evidence_ids=frozenset({"evidence-1"}),
                fact_ids=frozenset({"fact-1"}),
                characters=frozenset({"Ava"}),
                local_connectivity=[],
            )
    with pytest.raises(ValueError, match="forbidden raw story"):
        build_reconciliation_request(
            run_id="run",
            chunk_id="reconcile",
            scope_id="scene",
            events=[
                {
                    "id": "event-1",
                    "title": "Event One",
                    "summary": "Summary",
                    "member_ids": ["beat-1"],
                    "source_text": "forbidden",
                }
            ],
            ordered_event_ids=("event-1",),
            evidence_ids=frozenset({"evidence-1"}),
            fact_ids=frozenset({"fact-1"}),
        )


def test_reconcile_and_arc_builders_reject_oversized_complete_prompts() -> None:
    oversized_member_ids = [f"beat-{index:04d}-{'x' * 50}" for index in range(1_000)]
    with pytest.raises(ValueError, match="complete organization prompt"):
        build_reconciliation_request(
            run_id="run",
            chunk_id="reconcile",
            scope_id="scene",
            events=[
                {
                    "id": "event-1",
                    "title": "Event One",
                    "summary": "Summary",
                    "member_ids": oversized_member_ids,
                }
            ],
            ordered_event_ids=("event-1",),
            evidence_ids=frozenset(),
            fact_ids=frozenset(),
        )

    event_ids = tuple(f"event-{index:03d}" for index in range(180))
    arc_events = [
        {
            "id": event_id,
            "title": f"Event {index}",
            "summary": "s" * 320,
            "major_fact_ids": [],
            "characters": ["Ava"],
            "importance": "supporting",
            "outcomes": ["o" * 320],
            "evidence_ids": [],
        }
        for index, event_id in enumerate(event_ids)
    ]
    with pytest.raises(ValueError, match="complete organization prompt"):
        build_arc_request(
            run_id="run",
            chunk_id="arcs",
            scope_id="story",
            event_summaries=arc_events,
            ordered_event_ids=event_ids,
            evidence_ids=frozenset(),
            fact_ids=frozenset(),
            characters=frozenset({"Ava"}),
            local_connectivity=[],
        )


def test_cache_key_covers_content_order_provider_model_prompt_and_schema() -> None:
    request = _request()
    baseline = build_cache_key(
        request,
        provider_mode=CodexMode.CODEX_CHATGPT,
        model_profile="balanced",
        model_fingerprint="model-sha-a",
        prompt_version="p1",
        schema_version="s1",
    )
    duplicate = build_cache_key(
        request,
        provider_mode=CodexMode.CODEX_CHATGPT,
        model_profile="balanced",
        model_fingerprint="model-sha-a",
        prompt_version="p1",
        schema_version="s1",
    )
    assert baseline.digest() == duplicate.digest()
    variants = [
        build_cache_key(
            request,
            provider_mode=mode,
            model_profile=profile,
            model_fingerprint=model,
            prompt_version=prompt,
            schema_version=schema,
        ).digest()
        for mode, profile, model, prompt, schema in [
            (CodexMode.CODEX_LMSTUDIO, "balanced", "model-sha-a", "p1", "s1"),
            (CodexMode.CODEX_CHATGPT, "quality", "model-sha-a", "p1", "s1"),
            (CodexMode.CODEX_CHATGPT, "balanced", "model-sha-b", "p1", "s1"),
            (CodexMode.CODEX_CHATGPT, "balanced", "model-sha-a", "p2", "s1"),
            (CodexMode.CODEX_CHATGPT, "balanced", "model-sha-a", "p1", "s2"),
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
        assert "uniqueItems" not in json.dumps(schema)
        assert "$defs" in schema
        group_properties = schema["$defs"]["group"]["properties"]
        assert group_properties["title"]["minLength"] == 1
        assert group_properties["summary"]["minLength"] == 1
        serialized = json.dumps(schema)
        assert "events.schema.json" not in serialized


@pytest.mark.parametrize("field", ["title", "summary"])
def test_validator_rejects_empty_titles_and_summaries(field: str) -> None:
    payload = _valid_payload()
    payload["groups"][0][field] = "   "
    with pytest.raises(InvalidProviderOutputError, match="must not be empty"):
        validate_result(payload, _request())


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
        write_result: int | None = None,
        remains_starting: bool = False,
        startup_waits_in_real_time: bool = False,
    ) -> None:
        self.output = output
        self.stderr = stderr
        self.exit_code = exit_code
        self.never_finishes = never_finishes
        self.ignore_terminate = ignore_terminate
        self.start_ok = start_ok
        self.write_result = write_result
        self.remains_starting = remains_starting
        self.startup_waits_in_real_time = startup_waits_in_real_time
        self.started: tuple[str, list[str]] | None = None
        self.cwd = ""
        self.stdin = b""
        self.terminated = False
        self.killed = False
        self.read = False
        self.wait_arguments: list[int] = []
        self.environment: QProcessEnvironment | None = None

    def setProcessEnvironment(self, environment: QProcessEnvironment) -> None:
        self.environment = environment

    def setWorkingDirectory(self, directory: str) -> None:
        self.cwd = directory

    def start(self, program: str, arguments: list[str]) -> None:
        self.started = (program, arguments)

    def waitForStarted(self, msecs: int = 30000) -> bool:
        if self.startup_waits_in_real_time:
            time.sleep(msecs / 1000)
        if self.remains_starting:
            return False
        return self.start_ok

    def write(self, data: bytes) -> int:
        written = len(data) if self.write_result is None else self.write_result
        if written > 0:
            self.stdin += data[:written]
        return written

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

    def state(self) -> QProcess.ProcessState:
        if self.terminated or self.killed or not self.start_ok:
            return QProcess.ProcessState.NotRunning
        if self.remains_starting:
            return QProcess.ProcessState.Starting
        return QProcess.ProcessState.Running

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


def _lmstudio_payload(
    *instance_ids: str,
    context_length: object = 8_192,
    model_type: str = "llm",
) -> dict[str, object]:
    return {
        "models": [
            {
                "type": model_type,
                "key": "synthetic-model-key",
                "max_context_length": 32_768,
                "loaded_instances": [
                    {
                        "id": instance_id,
                        "config": {"context_length": context_length},
                    }
                    for instance_id in instance_ids
                ],
            }
        ]
    }


def test_provider_commands_are_direct_stdin_only_and_sterile() -> None:
    usage = json.dumps(
        {
            "type": "turn.completed",
            "model": "gpt-5.6-luna",
            "usage": {"input_tokens": 123, "output_tokens": 45},
        }
    ).encode()
    process = FakeProcess(usage + b"\n" + _jsonl(_valid_payload()))
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=lambda: process)
    result = provider.organize(_request(), lambda _percent, _status: None, lambda: False)
    assert result.groups[0].id == "group-1"
    assert process.started is not None
    program, args = process.started
    assert program == "codex"
    assert args[:8] == [
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
    ]
    schema_index = args.index("--output-schema")
    disabled = args[8 : args.index("-c")]
    assert disabled == [
        value
        for feature in (
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
        for value in ("--disable", feature)
    ]
    assert args[args.index("-c") : args.index("--json")] == [
        "-c",
        'web_search="disabled"',
        "-c",
        "analytics.enabled=false",
        "-c",
        'model_reasoning_effort="high"',
    ]
    assert args[schema_index + 2 :] == ["--model", "gpt-5.6-luna", "-"]
    assert Path(process.cwd).name.startswith("renpy-story-organizer-")
    assert not Path(process.cwd).exists()
    assert b"synthetic" in process.stdin
    assert "--output-last-message" not in args
    assert "--enable" not in args
    assert result.metadata is not None
    assert result.metadata.model_identifier == "gpt-5.6-luna"
    assert result.metadata.input_tokens == 123
    assert result.metadata.output_tokens == 45
    assert len(result.metadata.input_hash) == 64
    assert len(result.metadata.output_hash) == 64


def test_chatgpt_command_explicitly_selects_luna_high_without_fast_mode() -> None:
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT)
    _program, args = provider.command(Path("schema.json"), model="gpt-5.6-luna")

    assert args[args.index("--model") + 1] == "gpt-5.6-luna"
    assert 'model_reasoning_effort="high"' in args
    assert args[args.index("--disable") + 1] == "plugins"
    assert [args[index + 1] for index, value in enumerate(args[:-1]) if value == "--disable"].count(
        "fast_mode"
    ) == 1


def test_explicit_cloud_model_records_selection_and_rejects_conflicting_metadata() -> None:
    request = replace(_request(), model="gpt-5.6-luna")
    missing_metadata = FakeProcess(_jsonl(_valid_payload()))
    selected = CodexCliProvider(
        CodexMode.CODEX_CHATGPT,
        process_factory=lambda: missing_metadata,
    ).organize(request, lambda _percent, _status: None, lambda: False)
    assert selected.metadata is not None
    assert selected.metadata.model_identifier == "gpt-5.6-luna"

    model_event = json.dumps(
        {"type": "turn.completed", "model": "gpt-5.6-luna"}
    ).encode("utf-8")
    matching = FakeProcess(model_event + b"\n" + _jsonl(_valid_payload()))
    result = CodexCliProvider(
        CodexMode.CODEX_CHATGPT,
        process_factory=lambda: matching,
    ).organize(request, lambda _percent, _status: None, lambda: False)
    assert result.metadata is not None
    assert result.metadata.model_identifier == "gpt-5.6-luna"

    conflicting_event = json.dumps(
        {"type": "turn.completed", "model": "different-model"}
    ).encode("utf-8")
    conflicting = FakeProcess(conflicting_event + b"\n" + _jsonl(_valid_payload()))
    with pytest.raises(ProviderUnavailableError, match="different model"):
        CodexCliProvider(
            CodexMode.CODEX_CHATGPT,
            process_factory=lambda: conflicting,
        ).organize(request, lambda _percent, _status: None, lambda: False)


def test_lmstudio_command_adds_only_locked_local_flags() -> None:
    provider = CodexCliProvider(CodexMode.CODEX_LMSTUDIO)
    _program, args = provider.command(Path("schema.json"), model="local-model")
    assert args[-4:] == ["--oss", "--local-provider", "lmstudio", "-"]
    assert args[args.index("--model") + 1] == "local-model"


def test_lmstudio_status_resolves_one_model_from_loopback_without_story_input() -> None:
    calls: list[tuple[str, float]] = []

    def discover(url: str, timeout: float) -> object:
        calls.append((url, timeout))
        return _lmstudio_payload("local/model-a", context_length=12_288)

    provider = CodexCliProvider(
        CodexMode.CODEX_LMSTUDIO,
        process_factory=lambda: FakeProcess(b""),
        lmstudio_base_url="http://127.0.0.1:1234",
        model_discovery=discover,
    )
    status = provider.status()
    assert status.state is ProviderState.READY
    assert status.model_identifier == "local/model-a"
    assert status.context_window_tokens == 12_288
    assert calls == [("http://127.0.0.1:1234/api/v1/models", 0.5)]
    assert "story" not in calls[0][0].lower()


def test_lmstudio_status_sanitizes_an_empty_loaded_instance_identifier() -> None:
    provider = CodexCliProvider(
        CodexMode.CODEX_LMSTUDIO,
        process_factory=lambda: FakeProcess(b""),
        model_discovery=lambda _url, _timeout: _lmstudio_payload(""),
    )

    status = provider.status()

    assert status.state is ProviderState.MISSING
    assert "invalid native model list" in status.message


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"models": []}, "no matching loaded llm"),
        (_lmstudio_payload("model-a", "model-b"), "multiple matching"),
        ({"unexpected": []}, "invalid native model list"),
        ({"models": [{}]}, "invalid native model list"),
        (_lmstudio_payload("embedding", model_type="embedding"), "non-llm"),
        (_lmstudio_payload("bad-context", context_length=0), "context capability"),
        (_lmstudio_payload("bad-context", context_length=True), "context capability"),
        ("not-an-object", "invalid native model list"),
    ],
)
def test_lmstudio_status_safely_rejects_missing_ambiguous_or_malformed_models(
    payload: object, message: str
) -> None:
    provider = CodexCliProvider(
        CodexMode.CODEX_LMSTUDIO,
        process_factory=lambda: FakeProcess(b""),
        model_discovery=lambda _url, _timeout: payload,
    )
    status = provider.status()
    assert status.state is ProviderState.MISSING
    assert status.model_identifier is None
    assert message in status.message.lower()


@pytest.mark.parametrize("failure", [TimeoutError(), ConnectionRefusedError()])
def test_lmstudio_status_sanitizes_timeout_and_refusal(failure: OSError) -> None:
    def unavailable(_url: str, _timeout: float) -> object:
        raise failure

    provider = CodexCliProvider(
        CodexMode.CODEX_LMSTUDIO,
        process_factory=lambda: FakeProcess(b""),
        model_discovery=unavailable,
    )
    status = provider.status()
    assert status.state is ProviderState.MISSING
    assert status.model_identifier is None
    assert status.message == (
        "LM Studio is unavailable. Start it on loopback port 1234 and load exactly one model."
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "https://localhost:1234",
        "http://localhost:1234",
        "http://[::1]:1234",
        "http://example.com:1234",
        "http://127.0.0.1:9999",
        "http://127.0.0.1:1234/v1/models",
        "http://user:secret@127.0.0.1:1234",
        "http://127.0.0.1:1234?redirect=example.com",
    ],
)
def test_lmstudio_status_never_discovers_outside_strict_loopback_base(
    base_url: str,
) -> None:
    called = False

    def discover(_url: str, _timeout: float) -> object:
        nonlocal called
        called = True
        return _lmstudio_payload("should-not-run")

    provider = CodexCliProvider(
        CodexMode.CODEX_LMSTUDIO,
        process_factory=lambda: FakeProcess(b""),
        lmstudio_base_url=base_url,
        model_discovery=discover,
    )
    status = provider.status()
    assert status.state is ProviderState.MISSING
    assert "restricted" in status.message.lower()
    assert not called


def test_explicit_lmstudio_model_override_selects_matching_loaded_instance() -> None:
    called = False
    process = FakeProcess(_jsonl(_valid_payload()))

    def discover(_url: str, _timeout: float) -> object:
        nonlocal called
        called = True
        return _lmstudio_payload("explicit-model", "other-model")

    provider = CodexCliProvider(
        CodexMode.CODEX_LMSTUDIO,
        process_factory=lambda: process,
        model_discovery=discover,
    )
    provider.set_model_override("explicit-model")
    status = provider.status()
    assert status.model_identifier == "explicit-model"
    assert status.context_window_tokens == 8_192
    result = provider.organize(_request(), lambda _p, _s: None, lambda: False)
    assert called
    assert process.started is not None
    assert process.started[1][process.started[1].index("--model") + 1] == "explicit-model"
    assert result.metadata is not None
    assert result.metadata.model_identifier == "explicit-model"
    assert result.metadata.context_window_tokens == 8_192


def test_ambiguous_loaded_llms_require_an_exact_explicit_override() -> None:
    payload = _lmstudio_payload("model-a", "model-b")
    without_override = CodexCliProvider(
        CodexMode.CODEX_LMSTUDIO,
        process_factory=lambda: FakeProcess(b""),
        model_discovery=lambda _url, _timeout: payload,
    ).status()
    assert without_override.state is ProviderState.MISSING
    assert "multiple matching" in without_override.message.lower()

    with_override = CodexCliProvider(
        CodexMode.CODEX_LMSTUDIO,
        process_factory=lambda: FakeProcess(b""),
        model_override="model-b",
        model_discovery=lambda _url, _timeout: payload,
    ).status()
    assert with_override.state is ProviderState.READY
    assert with_override.model_identifier == "model-b"
    assert with_override.context_window_tokens == 8_192


def test_explicit_override_cannot_bypass_preflight_or_loaded_embedding() -> None:
    mismatched = CodexCliProvider(
        CodexMode.CODEX_LMSTUDIO,
        process_factory=lambda: FakeProcess(b""),
        model_override="not-loaded",
        model_discovery=lambda _url, _timeout: _lmstudio_payload("loaded-model"),
    ).status()
    assert mismatched.state is ProviderState.MISSING
    assert "no matching" in mismatched.message.lower()

    llm_models = _lmstudio_payload("loaded-model")["models"]
    embedding_models = _lmstudio_payload("embed-1", model_type="embedding")["models"]
    assert isinstance(llm_models, list)
    assert isinstance(embedding_models, list)
    mixed_payload = {"models": [*llm_models, *embedding_models]}
    embedding_loaded = CodexCliProvider(
        CodexMode.CODEX_LMSTUDIO,
        process_factory=lambda: FakeProcess(b""),
        model_override="loaded-model",
        model_discovery=lambda _url, _timeout: mixed_payload,
    ).status()
    assert embedding_loaded.state is ProviderState.MISSING
    assert "non-llm" in embedding_loaded.message.lower()


@pytest.mark.parametrize(
    "invalid_model",
    [" padded-model", "model\nname", "model\x00name", "x" * 201, "   "],
)
def test_model_override_rejects_unbounded_or_control_content(
    invalid_model: str,
) -> None:
    provider = CodexCliProvider(
        CodexMode.CODEX_LMSTUDIO,
        process_factory=lambda: FakeProcess(b""),
        model_override="original-model",
        model_discovery=lambda _url, _timeout: _lmstudio_payload("original-model"),
    )
    with pytest.raises(ValueError, match="1-200 printable"):
        provider.set_model_override(invalid_model)
    assert provider.status().model_identifier == "original-model"


def test_empty_model_override_clears_and_reenables_discovery() -> None:
    provider = CodexCliProvider(
        CodexMode.CODEX_LMSTUDIO,
        process_factory=lambda: FakeProcess(b""),
        model_override="original-model",
        model_discovery=lambda _url, _timeout: _lmstudio_payload("discovered-model"),
    )
    provider.set_model_override("")
    assert provider.status().model_identifier == "discovered-model"


def test_lmstudio_discovery_failure_is_refreshable_without_rediscovering_executable() -> None:
    discovery_calls = 0
    resolver_calls = 0

    def discover(_url: str, _timeout: float) -> object:
        nonlocal discovery_calls
        discovery_calls += 1
        if discovery_calls == 1:
            raise ConnectionRefusedError
        return _lmstudio_payload("newly-loaded-model")

    def resolve(_executable: str) -> str:
        nonlocal resolver_calls
        resolver_calls += 1
        return "synthetic-codex.exe"

    provider = CodexCliProvider(
        CodexMode.CODEX_LMSTUDIO,
        process_factory=lambda: FakeProcess(b""),
        executable_resolver=resolve,
        model_discovery=discover,
    )
    first = provider.status()
    second = provider.status()
    assert first.state is ProviderState.MISSING
    assert second.state is ProviderState.READY
    assert second.model_identifier == "newly-loaded-model"
    assert discovery_calls == 2
    assert resolver_calls == 1


def test_lmstudio_default_discovery_caps_response_before_json_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OversizedResponse:
        requested_bytes = 0
        total_bytes = 0

        def __enter__(self) -> OversizedResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, amount: int) -> bytes:
            self.requested_bytes = amount
            self.total_bytes += amount
            return b"x" * amount

    class FakeOpener:
        response = OversizedResponse()

        def open(self, request: object, *, timeout: float) -> OversizedResponse:
            assert timeout == 0.1
            assert isinstance(request, provider_module.Request)
            assert request.full_url == "http://127.0.0.1:1234/api/v1/models"
            assert request.get_method() == "GET"
            return self.response

    opener = FakeOpener()
    handlers: list[object] = []

    def fake_build_opener(*supplied: object) -> FakeOpener:
        handlers.extend(supplied)
        return opener

    monkeypatch.setattr(provider_module, "build_opener", fake_build_opener)
    with pytest.raises(ValueError, match="size limit"):
        provider_module._discover_models("http://127.0.0.1:1234/api/v1/models", 0.5)
    assert opener.response.requested_bytes <= 4_096
    assert opener.response.total_bytes == 65_537
    proxy_handler = next(
        handler for handler in handlers if isinstance(handler, provider_module.ProxyHandler)
    )
    assert proxy_handler.proxies == {}
    assert any(isinstance(handler, provider_module._NoRedirect) for handler in handlers)


def test_lmstudio_discovery_enforces_total_deadline_with_only_daemon_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowResponse:
        body = json.dumps(_lmstudio_payload("slow-model")).encode()
        offset = 0

        def __enter__(self) -> SlowResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _amount: int) -> bytes:
            time.sleep(0.02)
            if self.offset >= len(self.body):
                return b""
            value = self.body[self.offset : self.offset + 1]
            self.offset += 1
            return value

    class SlowOpener:
        def open(self, _request: object, *, timeout: float) -> SlowResponse:
            assert timeout == 0.05
            return SlowResponse()

    monkeypatch.setattr(provider_module, "build_opener", lambda *_handlers: SlowOpener())
    started = time.perf_counter()
    with pytest.raises(TimeoutError, match="total deadline"):
        provider_module._discover_models("http://127.0.0.1:1234/api/v1/models", 0.05)
    elapsed = time.perf_counter() - started
    workers = [
        thread for thread in threading.enumerate() if thread.name == "lmstudio-model-preflight"
    ]
    assert elapsed < 0.3
    assert workers
    assert all(worker.daemon for worker in workers)


def test_chatgpt_status_never_performs_cloud_model_discovery() -> None:
    called = False

    def discover(_url: str, _timeout: float) -> object:
        nonlocal called
        called = True
        raise AssertionError("ChatGPT status must not perform model discovery")

    provider = CodexCliProvider(
        CodexMode.CODEX_CHATGPT,
        process_factory=lambda: FakeProcess(b""),
        model_discovery=discover,
    )
    status = provider.status()
    assert status.state is ProviderState.READY
    assert status.model_identifier == "gpt-5.6-luna"
    assert not called


def test_resolved_lmstudio_model_supports_metadata_cache_hit_without_second_process() -> None:
    process_count = 0
    processes: list[FakeProcess] = []

    def factory() -> FakeProcess:
        nonlocal process_count
        process_count += 1
        process = FakeProcess(_jsonl(_valid_payload()))
        processes.append(process)
        return process

    provider = CodexCliProvider(
        CodexMode.CODEX_LMSTUDIO,
        process_factory=factory,
        model_discovery=lambda _url, _timeout: _lmstudio_payload("cache-model"),
    )
    status = provider.status()
    assert status.model_identifier == "cache-model"
    cache: dict[str, object] = {}
    request = _request()
    cache_key = build_cache_key(
        request,
        provider_mode=CodexMode.CODEX_LMSTUDIO,
        model_profile="balanced",
        model_fingerprint=status.model_identifier,
        prompt_version="p1",
        schema_version="s1",
    ).digest()
    result = provider.organize(request, lambda _p, _s: None, lambda: False)
    cache[cache_key] = result
    rerun_status = provider.status()
    assert rerun_status.model_identifier == "cache-model"
    rerun_key = build_cache_key(
        request,
        provider_mode=CodexMode.CODEX_LMSTUDIO,
        model_profile="balanced",
        model_fingerprint=rerun_status.model_identifier,
        prompt_version="p1",
        schema_version="s1",
    ).digest()
    rerun = cache.get(rerun_key)
    assert rerun is result
    assert result.metadata is not None
    assert result.metadata.model_identifier == "cache-model"
    assert result.metadata.context_window_tokens == 8_192
    assert process_count == 1
    assert processes[0].started is not None
    arguments = processes[0].started[1]
    assert arguments[arguments.index("--model") + 1] == "cache-model"


def test_lmstudio_child_removes_proxies_and_sets_loopback_no_proxy() -> None:
    process = FakeProcess(_jsonl(_valid_payload()))
    inherited = QProcessEnvironment()
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "FTP_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "ftp_proxy",
        "no_proxy",
    ):
        inherited.insert(name, "http://proxy.invalid:8080")
    inherited.insert("KEEP_ME", "safe")
    provider = CodexCliProvider(
        CodexMode.CODEX_LMSTUDIO,
        process_factory=lambda: process,
        model_discovery=lambda _url, _timeout: _lmstudio_payload("local-model"),
        environment_factory=lambda: inherited,
    )
    provider.organize(_request(), lambda _p, _s: None, lambda: False)
    assert process.environment is not None
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "FTP_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "ftp_proxy",
    ):
        assert not process.environment.contains(name)
    assert process.environment.value("NO_PROXY") == "127.0.0.1,localhost,::1"
    assert process.environment.value("no_proxy") == "127.0.0.1,localhost,::1"
    assert process.environment.value("KEEP_ME") == "safe"
    isolated_home = Path(process.environment.value("CODEX_HOME"))
    assert isolated_home.name.startswith("renpy-story-organizer-")
    assert isolated_home == Path(process.cwd)
    assert not isolated_home.exists()


def test_chatgpt_child_environment_is_not_replaced() -> None:
    process = FakeProcess(_jsonl(_valid_payload()))
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=lambda: process)
    provider.organize(_request(), lambda _p, _s: None, lambda: False)
    assert process.environment is None


@pytest.mark.parametrize(("reported", "matches"), [("model-a", True), ("model-b", False)])
def test_lmstudio_rejects_executed_model_mismatch(reported: str, matches: bool) -> None:
    model_event = json.dumps({"type": "turn.started", "model": reported}).encode()
    process = FakeProcess(model_event + b"\n" + _jsonl(_valid_payload()))
    provider = CodexCliProvider(
        CodexMode.CODEX_LMSTUDIO,
        process_factory=lambda: process,
        model_discovery=lambda _url, _timeout: _lmstudio_payload("model-a"),
    )
    if matches:
        result = provider.organize(_request(), lambda _p, _s: None, lambda: False)
        assert result.metadata is not None
        assert result.metadata.model_identifier == "model-a"
    else:
        with pytest.raises(ProviderUnavailableError, match="different model"):
            provider.organize(_request(), lambda _p, _s: None, lambda: False)


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

    for run_id, consent in (("", ""), ("   ", "   "), ("run-1", None)):
        called = False
        invalid = OrganizationRequest(
            **{
                **_request().__dict__,
                "run_id": run_id,
                "cloud_consent_run_id": consent,
            }
        )
        with pytest.raises(ConsentRequiredError):
            CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=factory).organize(
                invalid, lambda _p, _s: None, lambda: False
            )
        assert not called


def test_injected_provider_does_not_consult_machine_codex_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_which(_name: str) -> tuple[Path, ...]:
        raise AssertionError("machine PATH must not be consulted for an injected provider")

    monkeypatch.setattr(
        "renpy_story_mapper.organization.provider._path_executable_candidates",
        forbidden_which,
    )
    process = FakeProcess(_jsonl(_valid_payload()))
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=lambda: process)
    assert provider.status().state is ProviderState.READY
    assert (
        provider.organize(_request(), lambda _p, _s: None, lambda: False).groups[0].id == "group-1"
    )


def test_native_discovery_never_executes_a_cwd_planted_codex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    planted = cwd / "codex.exe"
    planted.write_bytes(b"untrusted")
    path_root = tmp_path / "trusted-bin"
    path_root.mkdir()
    (path_root / "codex.cmd").write_text("@echo off\r\n", encoding="utf-8")
    vendor = (
        path_root
        / "node_modules"
        / "@openai"
        / "codex"
        / "node_modules"
        / "@openai"
        / "codex-win32-x64"
        / "vendor"
        / "x86_64-pc-windows-msvc"
        / "bin"
        / "codex.exe"
    )
    vendor.parent.mkdir(parents=True)
    vendor.write_bytes(b"trusted")
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("PATH", str(path_root))
    monkeypatch.setenv("PATHEXT", ".EXE;.CMD")
    probed: list[str] = []
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT)

    def probe(executable: str, _deadline: float | None = None) -> str:
        probed.append(executable)
        return "codex-cli synthetic"

    monkeypatch.setattr(provider, "_probe_version", probe)
    status = provider.status()

    assert status.state is ProviderState.READY
    assert status.executable == str(vendor.resolve())
    assert probed == [str(vendor.resolve())]
    assert str(planted.resolve()) not in probed


def test_native_executable_discovery_has_one_strict_total_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path_root = tmp_path / "bin"
    path_root.mkdir()
    (path_root / "codex.exe").write_bytes(b"first")
    (path_root / "codex.cmd").write_text("@echo off\r\n", encoding="utf-8")
    vendor = (
        path_root
        / "node_modules"
        / "@openai"
        / "codex"
        / "node_modules"
        / "@openai"
        / "codex-win32-x64"
        / "vendor"
        / "x86_64-pc-windows-msvc"
        / "bin"
        / "codex.exe"
    )
    vendor.parent.mkdir(parents=True)
    vendor.write_bytes(b"second")
    monkeypatch.setenv("PATH", str(path_root))
    monkeypatch.setenv("PATHEXT", ".EXE;.CMD")
    calls: list[str] = []
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT)

    def slow_probe(executable: str, deadline: float | None = None) -> None:
        assert deadline is not None
        calls.append(executable)
        time.sleep(max(0.0, deadline - time.monotonic()) + 0.02)

    monkeypatch.setattr(provider, "_probe_version", slow_probe)
    started = time.monotonic()
    status = provider.status()
    elapsed = time.monotonic() - started

    assert status.state is ProviderState.MISSING
    assert len(calls) == 1
    assert elapsed < 0.8


@pytest.mark.parametrize("use_cancel_method", [False, True])
def test_pre_cancel_never_creates_process_or_writes_story_input(
    use_cancel_method: bool,
) -> None:
    created: list[FakeProcess] = []

    def factory() -> FakeProcess:
        process = FakeProcess(b"")
        created.append(process)
        return process

    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=factory)
    if use_cancel_method:
        provider.cancel()
    with pytest.raises(OrganizationCancelledError, match="before transmission"):
        provider.organize(
            _request(),
            lambda _p, _s: None,
            (lambda: False) if use_cancel_method else (lambda: True),
        )
    assert created == []


def test_provider_rejects_oversized_initial_and_repair_prompts_before_process() -> None:
    created = False

    def factory() -> FakeProcess:
        nonlocal created
        created = True
        return FakeProcess(b"")

    request = _request()
    request = OrganizationRequest(**{**request.__dict__, "payload": {"story": "x" * MAX_CHARS}})
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=factory)
    with pytest.raises(ValueError, match="complete organization prompt"):
        provider.organize(request, lambda _p, _s: None, lambda: False)
    with pytest.raises(ValueError, match="complete organization prompt"):
        provider._execute(
            request,
            lambda _p, _s: None,
            lambda: False,
            repair=True,
        )
    assert not created


def test_direct_execute_pre_cancel_never_creates_process() -> None:
    called = False

    def factory() -> FakeProcess:
        nonlocal called
        called = True
        return FakeProcess(b"")

    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=factory)
    with pytest.raises(OrganizationCancelledError, match="before transmission"):
        provider._execute(_request(), lambda _p, _s: None, lambda: True, repair=False)
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


def test_provider_totals_retry_usage_and_hashes_every_transmitted_prompt() -> None:
    request = _request()
    first_usage = (
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 111, "output_tokens": 22},
            }
        )
        + "\n"
    ).encode()
    second_usage = (
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 222, "output_tokens": 33},
            }
        )
        + "\n"
    ).encode()
    processes = [
        FakeProcess(first_usage + _jsonl({"bad": True})),
        FakeProcess(second_usage + _jsonl(_valid_payload())),
    ]
    provider = CodexCliProvider(
        CodexMode.CODEX_CHATGPT, process_factory=lambda: processes.pop(0)
    )

    result = provider.organize(request, lambda _p, _s: None, lambda: False)

    assert result.attempts == 2
    assert result.metadata is not None
    assert result.metadata.input_tokens == 333
    assert result.metadata.output_tokens == 55
    prompts = [
        serialize_organization_prompt(request, repair=repair).encode("utf-8")
        for repair in (False, True)
    ]
    framed = b"".join(len(prompt).to_bytes(8, "big") + prompt for prompt in prompts)
    first_only = len(prompts[0]).to_bytes(8, "big") + prompts[0]
    assert result.metadata.input_hash == hashlib.sha256(framed).hexdigest()
    assert result.metadata.input_hash != hashlib.sha256(first_only).hexdigest()


@pytest.mark.parametrize(
    "marker",
    [
        "command_execution",
        "mcp_tool_call",
        "collab_tool_call",
        "dynamic_tool_call",
        "web_search",
        "file_change",
    ],
)
def test_provider_terminates_and_rejects_policy_events(marker: str) -> None:
    process = FakeProcess((json.dumps({"type": marker}) + "\n").encode())
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=lambda: process)
    with pytest.raises(PolicyViolationError):
        provider.organize(_request(), lambda _p, _s: None, lambda: False)
    assert process.terminated


@pytest.mark.parametrize(
    "event",
    [
        {"type": "turn.completed", "output": [{"type": "mcp_tool_call"}]},
        {"type": "item.completed", "item": {"type": "future_action"}},
        {"type": "item.started", "item": {}},
    ],
)
def test_provider_fail_closes_nested_or_unknown_action_items(
    event: dict[str, object],
) -> None:
    process = FakeProcess((json.dumps(event) + "\n").encode())
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=lambda: process)

    with pytest.raises(PolicyViolationError):
        provider.organize(_request(), lambda _p, _s: None, lambda: False)

    assert process.terminated


def test_provider_does_not_treat_quoted_policy_words_as_executed_tools() -> None:
    payload = _valid_payload()
    groups = payload["groups"]
    assert isinstance(groups, list) and isinstance(groups[0], dict)
    groups[0]["warnings"] = [
        "The source literally mentions web_search, shell_command, and apply_patch."
    ]
    process = FakeProcess(_jsonl(payload))
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=lambda: process)

    result = provider.organize(_request(), lambda _p, _s: None, lambda: False)

    assert result.groups[0].warnings == (
        "The source literally mentions web_search, shell_command, and apply_patch.",
    )
    assert not process.terminated


def test_provider_cancellation_terminates_with_bounded_wait_and_cleans_temp() -> None:
    process = FakeProcess(b"", never_finishes=True, ignore_terminate=True)
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=lambda: process)
    checks = 0

    def cancel_after_start() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 4

    with pytest.raises(OrganizationCancelledError):
        provider.organize(_request(), lambda _p, _s: None, cancel_after_start)
    assert process.terminated
    assert process.killed
    assert 500 in process.wait_arguments
    assert 100 in process.wait_arguments
    assert sum(value for value in process.wait_arguments if value > 0) <= 620
    assert not Path(process.cwd).exists()


def test_provider_startup_is_pollable_and_cancellable_with_margin() -> None:
    process = FakeProcess(
        b"",
        never_finishes=True,
        remains_starting=True,
        startup_waits_in_real_time=True,
    )
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=lambda: process)
    checks = 0

    def cancel_during_startup() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 4

    started = time.perf_counter()
    with pytest.raises(OrganizationCancelledError, match="during provider startup"):
        provider.organize(_request(), lambda _p, _s: None, cancel_during_startup)
    elapsed = time.perf_counter() - started
    assert elapsed < 1.2
    assert process.terminated
    assert process.stdin == b""
    assert provider._active is None
    assert not Path(process.cwd).exists()


def test_provider_startup_timeout_cleans_up_inside_two_seconds() -> None:
    process = FakeProcess(
        b"",
        never_finishes=True,
        ignore_terminate=True,
        remains_starting=True,
        startup_waits_in_real_time=True,
    )
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=lambda: process)
    started = time.perf_counter()
    with pytest.raises(ProviderTimeoutError, match="startup timed out"):
        provider.organize(_request(), lambda _p, _s: None, lambda: False)
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0
    assert process.terminated
    assert process.killed
    assert process.stdin == b""
    assert provider._active is None
    assert not Path(process.cwd).exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows cancellation authority")
def test_real_windows_helper_process_cancellation_returns_with_margin() -> None:
    process = QProcess()
    process.start(sys.executable, ["-c", "import time; time.sleep(30)"])
    assert process.waitForStarted(2_000)
    started = time.perf_counter()
    CodexCliProvider._stop_process(process)
    elapsed = time.perf_counter() - started
    assert process.state() == QProcess.ProcessState.NotRunning
    assert elapsed < 1.5


@pytest.mark.parametrize("write_result", [-1, 5])
def test_failed_or_partial_stdin_write_stops_and_cleans_process(
    write_result: int,
) -> None:
    process = FakeProcess(b"", never_finishes=True, write_result=write_result)
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=lambda: process)
    with pytest.raises(ProviderUnavailableError, match="complete organization input"):
        provider.organize(_request(), lambda _p, _s: None, lambda: False)
    assert process.terminated
    assert provider._active is None
    assert not Path(process.cwd).exists()
    assert len(process.stdin) == max(0, write_result)


def test_running_error_event_stops_process_clears_active_and_cleans_temp() -> None:
    event = {
        "type": "turn.failed",
        "error": {"message": "429 rate limit SECRET-STORY"},
    }
    process = FakeProcess((json.dumps(event) + "\n").encode(), never_finishes=True)
    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT, process_factory=lambda: process)
    with pytest.raises(ProviderRateLimitError) as exc_info:
        provider.organize(_request(), lambda _p, _s: None, lambda: False)
    assert "SECRET-STORY" not in str(exc_info.value)
    assert process.terminated
    assert provider._active is None
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
    assert provider._active is None
    assert not Path(process.cwd).exists()
