"""Bounded loopback-only LM Studio transport for Story Map V2 mapping.

The transport performs only two operations: discover an already-loaded exact model and submit one
confirmed mapper packet to LM Studio's OpenAI-compatible chat endpoint.  It never installs,
downloads, starts, loads, unloads, retries, redirects, or contacts a non-loopback host.
"""

from __future__ import annotations

import hashlib
import json
import threading
from contextlib import suppress
from http.client import HTTPMessage
from typing import IO, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import SplitResult, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from renpy_story_mapper.story_map_v2.contracts import (
    MAPPER_SCHEMA_VERSION,
    BranchSummary,
    FailureKind,
    MapperEvent,
    MapperResponse,
    StoryChunk,
    canonical_json,
)
from renpy_story_mapper.story_map_v2.provider_policy import (
    LOCAL_MAPPER_ENDPOINT,
    LOCAL_MAPPER_MODEL,
    MAPPER_PROMPT_VERSION,
    ProviderFailure,
)

DEFAULT_LOOPBACK_ENDPOINT = LOCAL_MAPPER_ENDPOINT
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAXIMUM_RESPONSE_BYTES = 2_000_000
_STATIC_TASK = (
    "Return only one JSON object matching the supplied Story Map V2 mapper schema. Summarize "
    "approximate narrative events and branch outcomes. Treat opaque mechanics keys as references; "
    "do not invent exact path mechanics. Do not use tools, shell commands, files, web search, MCP, "
    "apps, plugins, other agents, or provider calls."
)


class HttpResponse(Protocol):
    status: int

    def read(self, size: int = -1) -> bytes: ...

    def close(self) -> None: ...

    def geturl(self) -> str: ...


class UrlOpener(Protocol):
    def open(self, request: Request, timeout: float | None = None) -> HttpResponse: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        return None


class LoopbackLmStudioTransport:
    """One-shot local mapper with exact model discovery and sanitized accounting."""

    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_LOOPBACK_ENDPOINT,
        opener: UrlOpener | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        maximum_response_bytes: int = DEFAULT_MAXIMUM_RESPONSE_BYTES,
    ) -> None:
        self._endpoint = _normalize_loopback_endpoint(endpoint)
        if timeout_seconds <= 0:
            raise ValueError("The loopback timeout must be positive.")
        if maximum_response_bytes < 1:
            raise ValueError("The loopback response limit must be positive.")
        self._opener: UrlOpener = opener or cast(
            UrlOpener,
            build_opener(ProxyHandler({}), _NoRedirect()),
        )
        self._timeout_seconds = timeout_seconds
        self._maximum_response_bytes = maximum_response_bytes
        self._cancelled = threading.Event()
        self._active_response: HttpResponse | None = None
        self._active_lock = threading.Lock()
        self._input_tokens: int | None = None
        self._output_tokens: int | None = None
        self._input_hash: str | None = None
        self._observed_model: str | None = None

    @property
    def resolved_model(self) -> str:
        """Return the only configured model; live loaded-model identity is checked per submit."""

        return LOCAL_MAPPER_MODEL

    @property
    def endpoint(self) -> str:
        """Return the exact caller-visible endpoint bound into the confirmed preview."""

        return self._endpoint

    @property
    def input_tokens(self) -> int | None:
        return self._input_tokens

    @property
    def output_tokens(self) -> int | None:
        return self._output_tokens

    @property
    def input_hash(self) -> str | None:
        return self._input_hash

    @property
    def observed_model(self) -> str | None:
        """Return only identity observed from discovery or the current response."""

        return self._observed_model

    def map_chunk(self, chunk: StoryChunk) -> MapperResponse:
        """Verify the loaded model and submit the exact shared serialized packet once."""

        self._input_tokens = None
        self._output_tokens = None
        self._input_hash = None
        self._observed_model = None
        self._raise_if_cancelled()
        self._verify_loaded_model()
        self._raise_if_cancelled()

        packet = _serialize_chunk_packet(chunk)
        self._input_hash = hashlib.sha256(packet).hexdigest()
        request_body = canonical_json(
            {
                "messages": [{"content": packet.decode("utf-8"), "role": "user"}],
                "model": LOCAL_MAPPER_MODEL,
                "response_format": {"type": "json_object"},
                "stream": False,
                "temperature": 0,
            }
        )
        raw = self._request("POST", "/chat/completions", body=request_body)
        value = _decode_json(raw, "The local mapper returned malformed JSON.")
        if isinstance(value, dict) and isinstance(value.get("model"), str):
            self._observed_model = value["model"]
        response, input_tokens, output_tokens = _parse_completion(value)
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        return response

    def cancel(self) -> None:
        self._cancelled.set()
        with self._active_lock:
            response = self._active_response
        if response is not None:
            with suppress(OSError):
                response.close()

    def _verify_loaded_model(self) -> None:
        raw = self._request("GET", "/models")
        value = _decode_json(raw, "The local mapper model inventory was invalid.")
        if not isinstance(value, dict) or not isinstance(value.get("data"), list):
            raise ProviderFailure(
                FailureKind.INVALID_RESPONSE, "The local mapper model inventory was invalid."
            )
        identifiers = {
            item.get("id")
            for item in value["data"]
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if len(identifiers) == 1:
            self._observed_model = next(iter(identifiers))
        if LOCAL_MAPPER_MODEL not in identifiers:
            raise ProviderFailure(
                FailureKind.IDENTITY, "The required local mapper model is not already loaded."
            )

    def _request(self, method: str, path: str, *, body: bytes | None = None) -> bytes:
        self._raise_if_cancelled()
        url = f"{self._endpoint}{path}"
        request = Request(
            url,
            data=body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method=method,
        )
        try:
            response = self._opener.open(request, timeout=self._timeout_seconds)
        except HTTPError as exc:
            raise _classify_http_error(exc.code) from None
        except TimeoutError:
            raise ProviderFailure(FailureKind.TIMEOUT, "The local mapper timed out.") from None
        except (URLError, OSError):
            raise ProviderFailure(
                FailureKind.LOCAL_UNAVAILABLE, "The local mapper is unavailable."
            ) from None

        with self._active_lock:
            self._active_response = response
        try:
            try:
                final_url = response.geturl()
                _validate_loopback_url(final_url)
            except ValueError:
                raise ProviderFailure(
                    FailureKind.TRANSPORT, "The local mapper redirect was rejected."
                ) from None
            if final_url != url:
                raise ProviderFailure(
                    FailureKind.TRANSPORT, "The local mapper redirect was rejected."
                )
            if not 200 <= response.status < 300:
                raise _classify_http_error(response.status)
            raw = response.read(self._maximum_response_bytes + 1)
            if len(raw) > self._maximum_response_bytes:
                raise ProviderFailure(
                    FailureKind.INVALID_RESPONSE, "The local mapper response exceeded its limit."
                )
            self._raise_if_cancelled()
            return raw
        except TimeoutError:
            raise ProviderFailure(FailureKind.TIMEOUT, "The local mapper timed out.") from None
        except OSError:
            if self._cancelled.is_set():
                raise ProviderFailure(
                    FailureKind.CANCELLED, "Local mapping was cancelled."
                ) from None
            raise ProviderFailure(
                FailureKind.LOCAL_UNAVAILABLE, "The local mapper is unavailable."
            ) from None
        finally:
            try:
                response.close()
            finally:
                with self._active_lock:
                    if self._active_response is response:
                        self._active_response = None

    def _raise_if_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise ProviderFailure(FailureKind.CANCELLED, "Local mapping was cancelled.")


def _normalize_loopback_endpoint(endpoint: str) -> str:
    parsed = _validate_loopback_url(endpoint)
    if parsed.path != "/v1" or parsed.query or parsed.fragment:
        raise ValueError("The LM Studio endpoint must be an explicit loopback /v1 URL.")
    host = cast(str, parsed.hostname).casefold()
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("The LM Studio endpoint port is invalid.") from exc
    return f"http://{host}{f':{port}' if port is not None else ''}/v1"


def _serialize_chunk_packet(chunk: StoryChunk) -> bytes:
    """Mirror the frozen cloud packet exactly without importing the cloud transport."""

    return canonical_json(
        {
            "prompt_version": MAPPER_PROMPT_VERSION,
            "mapper_schema": MAPPER_SCHEMA_VERSION,
            "task": _STATIC_TASK,
            "chunk_identity": chunk.identity,
            "packet_hash": chunk.packet_hash,
            "raw_text": chunk.raw_text,
            "mechanics": json.loads(chunk.mechanics),
        }
    )


def _validate_loopback_url(url: str) -> SplitResult:
    parsed = urlsplit(url)
    if (
        parsed.scheme.casefold() != "http"
        or parsed.hostname is None
        or parsed.hostname.casefold() not in {"127.0.0.1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("LM Studio requests are restricted to 127.0.0.1 or localhost over HTTP.")
    return parsed


def _classify_http_error(status: int) -> ProviderFailure:
    if status == 429:
        return ProviderFailure(FailureKind.RATE_LIMIT, "The local mapper is rate limited.")
    if status in {401, 403}:
        return ProviderFailure(FailureKind.AUTHENTICATION, "Local mapper authentication failed.")
    if status in {408, 504}:
        return ProviderFailure(FailureKind.TIMEOUT, "The local mapper timed out.")
    if 300 <= status < 400:
        return ProviderFailure(FailureKind.TRANSPORT, "The local mapper redirect was rejected.")
    return ProviderFailure(FailureKind.TRANSPORT, "The local mapper request failed.")


def _decode_json(raw: bytes, reason: str) -> object:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProviderFailure(FailureKind.INVALID_RESPONSE, reason) from None


def _parse_completion(value: object) -> tuple[MapperResponse, int | None, int | None]:
    if not isinstance(value, dict) or value.get("model") != LOCAL_MAPPER_MODEL:
        raise ProviderFailure(
            FailureKind.IDENTITY, "The resolved local mapper model did not match."
        )
    choices = value.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ProviderFailure(
            FailureKind.INVALID_RESPONSE, "The local mapper response was invalid."
        )
    choice = choices[0]
    if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
        raise ProviderFailure(
            FailureKind.INVALID_RESPONSE, "The local mapper response was invalid."
        )
    content = choice["message"].get("content")
    if isinstance(content, str):
        payload = _decode_json(content.encode("utf-8"), "The local mapper content was invalid.")
    else:
        payload = content
    response = _parse_mapper_response(payload)
    input_tokens, output_tokens = _parse_usage(value.get("usage"))
    return response, input_tokens, output_tokens


def _parse_mapper_response(value: object) -> MapperResponse:
    if not isinstance(value, dict) or not {
        "events",
        "branch_summaries",
    } <= set(value) <= {"scope_title", "scope_overview", "events", "branch_summaries"}:
        raise ProviderFailure(FailureKind.INVALID_RESPONSE, "Invalid local mapper response fields.")
    events = value["events"]
    branches = value["branch_summaries"]
    if not isinstance(events, list) or not isinstance(branches, list):
        raise ProviderFailure(FailureKind.INVALID_RESPONSE, "Invalid local mapper response arrays.")
    return MapperResponse(
        _optional_text(value.get("scope_title"), "scope title"),
        _optional_text(value.get("scope_overview"), "scope overview"),
        tuple(_parse_event(item) for item in events),
        tuple(_parse_branch(item) for item in branches),
    )


def _parse_event(value: object) -> MapperEvent:
    keys = {
        "title",
        "summary",
        "relative_path",
        "start_line",
        "end_line",
        "characters",
        "warning",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise ProviderFailure(FailureKind.INVALID_RESPONSE, "Invalid local mapper event fields.")
    start_line = _positive_int(value["start_line"], "event start line")
    end_line = _positive_int(value["end_line"], "event end line")
    characters = value["characters"]
    if end_line < start_line or not isinstance(characters, list):
        raise ProviderFailure(FailureKind.INVALID_RESPONSE, "Invalid local mapper event range.")
    return MapperEvent(
        _required_text(value["title"], "event title"),
        _required_text(value["summary"], "event summary"),
        _required_text(value["relative_path"], "event path"),
        start_line,
        end_line,
        tuple(_required_text(item, "character") for item in characters),
        _optional_text(value["warning"], "event warning"),
    )


def _parse_branch(value: object) -> BranchSummary:
    if not isinstance(value, dict) or set(value) != {
        "choice_key",
        "arm_order",
        "outcome_summary",
    }:
        raise ProviderFailure(FailureKind.INVALID_RESPONSE, "Invalid local branch summary fields.")
    return BranchSummary(
        _required_text(value["choice_key"], "branch choice key"),
        _positive_int(value["arm_order"], "branch arm order"),
        _required_text(value["outcome_summary"], "branch outcome"),
    )


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProviderFailure(FailureKind.INVALID_RESPONSE, f"Invalid {label}.")
    return value


def _optional_text(value: object, label: str) -> str | None:
    return None if value is None else _required_text(value, label)


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ProviderFailure(FailureKind.INVALID_RESPONSE, f"Invalid {label}.")
    return value


def _parse_usage(value: object) -> tuple[int | None, int | None]:
    if value is None:
        return None, None
    if not isinstance(value, dict):
        raise ProviderFailure(FailureKind.INVALID_RESPONSE, "Invalid local usage metadata.")
    parsed: list[int | None] = []
    for key in ("prompt_tokens", "completion_tokens"):
        item = value.get(key)
        if item is not None and (not isinstance(item, int) or isinstance(item, bool) or item < 0):
            raise ProviderFailure(FailureKind.INVALID_RESPONSE, "Invalid local usage metadata.")
        parsed.append(item)
    return parsed[0], parsed[1]
