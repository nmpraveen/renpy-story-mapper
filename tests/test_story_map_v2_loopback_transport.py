from __future__ import annotations

import hashlib
import json
from urllib.error import URLError
from urllib.request import ProxyHandler, Request

import pytest

from renpy_story_mapper.story_map_v2 import loopback_transport
from renpy_story_mapper.story_map_v2.cloud_transport import serialize_chunk_packet
from renpy_story_mapper.story_map_v2.contracts import (
    MAPPER_SCHEMA_VERSION,
    DensityMetrics,
    FailureKind,
    StoryChunk,
    canonical_hash,
)
from renpy_story_mapper.story_map_v2.loopback_transport import (
    LoopbackLmStudioTransport,
    parse_coverage_grade,
)
from renpy_story_mapper.story_map_v2.provider_policy import LOCAL_MAPPER_MODEL, ProviderFailure
from renpy_story_mapper.story_map_v2.workflow_contracts import WorkflowFailure
from renpy_story_mapper.story_map_v2.workflow_protocols import WorkflowProviderError


def _chunk() -> StoryChunk:
    return StoryChunk(
        index=1,
        span_keys=("span:one",),
        choice_keys=("choice:one",),
        raw_text='scripts/story.rpy:10 narrator "Hello"',
        mechanics='{"choices":[{"key":"choice:one"}]}',
        raw_tokens=12,
        density=DensityMetrics(menus=1, arms=2),
        packet_hash=canonical_hash({"packet": "one"}),
    )


def _mapper_payload() -> dict[str, object]:
    return {
        "scope_title": "Opening",
        "scope_overview": "A beginning.",
        "events": [
            {
                "title": "Arrival",
                "summary": "The story begins.",
                "relative_path": "scripts/story.rpy",
                "start_line": 10,
                "end_line": 10,
                "characters": ["Narrator"],
                "warning": None,
            }
        ],
        "branch_summaries": [
            {"choice_key": "choice:one", "arm_order": 1, "outcome_summary": "Proceed."}
        ],
    }


class FakeResponse:
    def __init__(self, value: object, url: str, *, status: int = 200, raw: bool = False) -> None:
        self.payload = value if raw else json.dumps(value).encode("utf-8")
        self.url = url
        self.status = status
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        return self.payload[:size] if size >= 0 else self.payload

    def close(self) -> None:
        self.closed = True

    def geturl(self) -> str:
        return self.url


class FakeOpener:
    def __init__(self, outcomes: list[FakeResponse | BaseException]) -> None:
        self.outcomes = outcomes
        self.requests: list[Request] = []

    def open(self, request: Request, timeout: float | None = None) -> FakeResponse:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _models(*identifiers: str) -> dict[str, object]:
    return {"data": [{"id": identifier, "object": "model"} for identifier in identifiers]}


def _completion(*, model: str = LOCAL_MAPPER_MODEL, content: object | None = None):
    return {
        "model": model,
        "choices": [{"message": {"content": json.dumps(content or _mapper_payload())}}],
        "usage": {"prompt_tokens": 91, "completion_tokens": 22},
    }


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://127.0.0.1:1234",
        "http://example.com:1234",
        "http://[::1]:1234",
        "http://user@localhost:1234",
        "http://localhost:1234",
        "http://localhost:1234/v1/",
    ],
)
def test_endpoint_is_strictly_plain_http_loopback_v1(endpoint: str) -> None:
    with pytest.raises(ValueError):
        LoopbackLmStudioTransport(endpoint=endpoint, opener=FakeOpener([]))


def test_default_opener_explicitly_disables_environment_proxies(monkeypatch) -> None:
    captured: list[object] = []

    def fake_build_opener(*handlers):
        captured.extend(handlers)
        return FakeOpener([])

    monkeypatch.setattr(loopback_transport, "build_opener", fake_build_opener)
    LoopbackLmStudioTransport()

    proxy_handlers = [handler for handler in captured if isinstance(handler, ProxyHandler)]
    assert len(proxy_handlers) == 1
    assert proxy_handlers[0].proxies == {}


def test_exact_loaded_model_and_byte_identical_packet_are_verified_before_submission() -> None:
    endpoint = "http://127.0.0.1:1234/v1"
    opener = FakeOpener(
        [
            FakeResponse(_models(LOCAL_MAPPER_MODEL), f"{endpoint}/models"),
            FakeResponse(_completion(), f"{endpoint}/chat/completions"),
        ]
    )
    transport = LoopbackLmStudioTransport(endpoint=endpoint, opener=opener)
    assert transport.endpoint == endpoint
    chunk = _chunk()
    response = transport.map_chunk(chunk)

    assert [request.get_method() for request in opener.requests] == ["GET", "POST"]
    submitted = json.loads(opener.requests[1].data or b"")
    packet = submitted["messages"][0]["content"].encode("utf-8")
    assert packet == serialize_chunk_packet(chunk)
    assert json.loads(packet)["mapper_schema"] == MAPPER_SCHEMA_VERSION == (
        "story-map-v2-mapper-v2"
    )
    assert submitted["model"] == LOCAL_MAPPER_MODEL
    assert transport.input_hash == hashlib.sha256(packet).hexdigest()
    assert transport.input_tokens == 91 and transport.output_tokens == 22
    assert response.events[0].title == "Arrival"


def test_workflow_submit_uses_existing_json_schema_without_small_token_cap() -> None:
    endpoint = "http://127.0.0.1:1234/v1"
    payload = {"section_title": "Opening", "section_summary": "A beginning."}
    opener = FakeOpener(
        [
            FakeResponse(_models(LOCAL_MAPPER_MODEL), f"{endpoint}/models"),
            FakeResponse(
                {
                    "model": LOCAL_MAPPER_MODEL,
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": json.dumps(payload),
                                "reasoning_content": "private chain of thought is ignored",
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 91, "completion_tokens": 293},
                },
                f"{endpoint}/chat/completions",
            ),
        ]
    )
    request = b'{"call_kind":"section_synthesis","story":"public"}'

    result = LoopbackLmStudioTransport(endpoint=endpoint, opener=opener).submit(request)

    submitted = json.loads(opener.requests[1].data or b"")
    assert submitted["messages"][0]["content"].encode() == request
    assert submitted["response_format"]["type"] == "json_schema"
    assert submitted["response_format"]["json_schema"]["name"] == (
        "story_map_phase04_section_prose_v1"
    )
    assert submitted["response_format"]["json_schema"]["schema"]["type"] == "object"
    assert submitted["reasoning_effort"] == "none"
    assert "max_tokens" not in submitted
    assert json.loads(result.payload) == payload
    assert result.accounting.output_tokens == 293
    assert result.resolved_reasoning == "none"


@pytest.mark.parametrize("grade", ["PASS", "PARTIAL", "LOW", "FAIL"])
def test_coverage_check_accepts_only_the_four_local_grades(grade: str) -> None:
    endpoint = "http://127.0.0.1:1234/v1"
    opener = FakeOpener(
        [
            FakeResponse(_models(LOCAL_MAPPER_MODEL), f"{endpoint}/models"),
            FakeResponse(
                _completion(content={"grade": grade}),
                f"{endpoint}/chat/completions",
            ),
        ]
    )
    request = b'{"call_kind":"coverage_check","comparison":"private"}'

    result = LoopbackLmStudioTransport(endpoint=endpoint, opener=opener).submit(request)

    submitted_data = opener.requests[1].data
    assert isinstance(submitted_data, bytes)
    submitted = json.loads(submitted_data)
    schema = submitted["response_format"]["json_schema"]
    assert schema["name"] == "story_map_phase05_coverage_check_v1"
    assert schema["strict"] is True
    assert schema["schema"] == {
        "additionalProperties": False,
        "properties": {
            "grade": {"enum": ["PASS", "PARTIAL", "LOW", "FAIL"], "type": "string"}
        },
        "required": ["grade"],
        "type": "object",
    }
    assert [request.full_url for request in opener.requests] == [
        f"{endpoint}/models",
        f"{endpoint}/chat/completions",
    ]
    assert submitted["model"] == LOCAL_MAPPER_MODEL
    assert parse_coverage_grade(result.payload) == grade


@pytest.mark.parametrize(
    "payload",
    [
        {"grade": "UNKNOWN"},
        {"grade": "PASS", "reason": "extra"},
    ],
)
def test_coverage_check_rejects_invalid_or_extra_response_fields(
    payload: dict[str, str],
) -> None:
    endpoint = "http://127.0.0.1:1234/v1"
    opener = FakeOpener(
        [
            FakeResponse(_models(LOCAL_MAPPER_MODEL), f"{endpoint}/models"),
            FakeResponse(_completion(content=payload), f"{endpoint}/chat/completions"),
        ]
    )

    with pytest.raises(WorkflowProviderError) as raised:
        LoopbackLmStudioTransport(endpoint=endpoint, opener=opener).submit(
            b'{"call_kind":"coverage_check"}'
        )

    assert raised.value.failure is WorkflowFailure.INVALID_RESPONSE
    assert len(opener.requests) == 2


def test_model_mismatch_fails_before_any_submission() -> None:
    endpoint = "http://localhost:1234/v1"
    opener = FakeOpener([FakeResponse(_models("another-model"), f"{endpoint}/models")])
    transport = LoopbackLmStudioTransport(endpoint=endpoint, opener=opener)
    with pytest.raises(ProviderFailure) as raised:
        transport.map_chunk(_chunk())
    assert raised.value.kind is FailureKind.IDENTITY
    assert len(opener.requests) == 1


def test_unavailable_loopback_is_sanitized_and_never_retried() -> None:
    opener = FakeOpener([URLError("private socket detail")])
    transport = LoopbackLmStudioTransport(opener=opener)
    with pytest.raises(ProviderFailure) as raised:
        transport.map_chunk(_chunk())
    assert raised.value.kind is FailureKind.LOCAL_UNAVAILABLE
    assert "private socket detail" not in str(raised.value)
    assert len(opener.requests) == 1


@pytest.mark.parametrize(
    ("second", "expected"),
    [
        (b"not-json", FailureKind.INVALID_RESPONSE),
        (_completion(model="wrong-model"), FailureKind.IDENTITY),
        (
            _completion(content={"events": "wrong", "branch_summaries": []}),
            FailureKind.INVALID_RESPONSE,
        ),
    ],
)
def test_invalid_or_identity_mismatched_response_is_honest_missing_input(
    second: object, expected: FailureKind
) -> None:
    endpoint = "http://127.0.0.1:1234/v1"
    opener = FakeOpener(
        [
            FakeResponse(_models(LOCAL_MAPPER_MODEL), f"{endpoint}/models"),
            FakeResponse(
                second,
                f"{endpoint}/chat/completions",
                raw=isinstance(second, bytes),
            ),
        ]
    )
    transport = LoopbackLmStudioTransport(opener=opener)
    with pytest.raises(ProviderFailure) as raised:
        transport.map_chunk(_chunk())
    assert raised.value.kind is expected
    assert len(opener.requests) == 2


def test_redirect_or_rebound_response_to_non_loopback_is_rejected() -> None:
    opener = FakeOpener([FakeResponse(_models(LOCAL_MAPPER_MODEL), "http://example.com/v1/models")])
    transport = LoopbackLmStudioTransport(opener=opener)
    with pytest.raises(ProviderFailure) as raised:
        transport.map_chunk(_chunk())
    assert raised.value.kind is FailureKind.TRANSPORT
    assert len(opener.requests) == 1


def test_cancel_before_discovery_makes_no_request() -> None:
    opener = FakeOpener([])
    transport = LoopbackLmStudioTransport(opener=opener)
    transport.cancel()
    with pytest.raises(ProviderFailure) as raised:
        transport.map_chunk(_chunk())
    assert raised.value.kind is FailureKind.CANCELLED
    assert opener.requests == []
