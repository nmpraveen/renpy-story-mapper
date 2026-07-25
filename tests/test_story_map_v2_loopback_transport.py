from __future__ import annotations

import hashlib
import json
from urllib.error import URLError
from urllib.request import Request

import pytest

from renpy_story_mapper.story_map_v2.cloud_transport import serialize_chunk_packet
from renpy_story_mapper.story_map_v2.contracts import (
    DensityMetrics,
    FailureKind,
    StoryChunk,
    canonical_hash,
)
from renpy_story_mapper.story_map_v2.loopback_transport import LoopbackLmStudioTransport
from renpy_story_mapper.story_map_v2.provider_policy import LOCAL_MAPPER_MODEL, ProviderFailure


def _chunk() -> StoryChunk:
    return StoryChunk(
        index=1,
        span_keys=("span:one",),
        choice_keys=("choice:one",),
        raw_text='scripts/story.rpy:10 narrator "Hello"',
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
        "http://localhost:1234/v1",
    ],
)
def test_endpoint_is_strictly_plain_http_ipv4_or_localhost_origin(endpoint: str) -> None:
    with pytest.raises(ValueError):
        LoopbackLmStudioTransport(endpoint=endpoint, opener=FakeOpener([]))


def test_exact_loaded_model_and_byte_identical_packet_are_verified_before_submission() -> None:
    endpoint = "http://127.0.0.1:1234"
    opener = FakeOpener(
        [
            FakeResponse(_models(LOCAL_MAPPER_MODEL), f"{endpoint}/v1/models"),
            FakeResponse(_completion(), f"{endpoint}/v1/chat/completions"),
        ]
    )
    transport = LoopbackLmStudioTransport(endpoint=endpoint, opener=opener)
    chunk = _chunk()
    response = transport.map_chunk(chunk)

    assert [request.get_method() for request in opener.requests] == ["GET", "POST"]
    submitted = json.loads(opener.requests[1].data or b"")
    packet = submitted["messages"][0]["content"].encode("utf-8")
    assert packet == serialize_chunk_packet(chunk)
    assert submitted["model"] == LOCAL_MAPPER_MODEL
    assert transport.input_hash == hashlib.sha256(packet).hexdigest()
    assert transport.input_tokens == 91 and transport.output_tokens == 22
    assert response.events[0].title == "Arrival"


def test_model_mismatch_fails_before_any_submission() -> None:
    endpoint = "http://localhost:1234"
    opener = FakeOpener([FakeResponse(_models("another-model"), f"{endpoint}/v1/models")])
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
    endpoint = "http://127.0.0.1:1234"
    opener = FakeOpener(
        [
            FakeResponse(_models(LOCAL_MAPPER_MODEL), f"{endpoint}/v1/models"),
            FakeResponse(
                second,
                f"{endpoint}/v1/chat/completions",
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
