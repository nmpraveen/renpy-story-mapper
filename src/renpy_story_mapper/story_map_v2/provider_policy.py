"""Track B seam for exact preview, cloud mapping, and bounded local execution."""

from __future__ import annotations

import hmac
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict
from typing import Protocol
from urllib.parse import urlsplit

from renpy_story_mapper.story_map_v2.contracts import (
    MAPPER_SCHEMA_VERSION,
    PREVIEW_SCHEMA_VERSION,
    ChunkExecutionResult,
    ChunkStatus,
    ExecutionMode,
    FailureKind,
    MapperResponse,
    ProviderOrigin,
    ProviderSettings,
    RunPreview,
    StoryChunk,
    StoryScope,
    canonical_hash,
)

LOCAL_MAPPER_MODEL = "qwen3.5-35b-a3b-uncensored-hauhaucs-aggressive"
LOCAL_MAPPER_ENDPOINT = "http://127.0.0.1:1234/v1"
CLOUD_MAPPER_MODEL = "gpt-5.6-luna"
MAPPER_PROMPT_VERSION = "story-map-v2-mapper-prompt-v1"
MAXIMUM_HOSTED_PLANNED = 6
MAXIMUM_HOSTED_ABSOLUTE = 8
TRANSMITTED_FIELDS = ("raw_text", "mechanics")
PRIVACY_EXCLUSIONS = (
    "private evaluation sheet",
    "external AI answers and images",
    "old provider responses",
    "screenshots",
    "unrelated files",
    "secrets",
    "game assets",
)


class ProviderFailure(RuntimeError):
    def __init__(self, kind: FailureKind, reason: str) -> None:
        super().__init__(reason)
        self.kind = kind


class ChunkMapper(Protocol):
    @property
    def resolved_model(self) -> str: ...

    def map_chunk(self, chunk: StoryChunk) -> MapperResponse: ...

    def cancel(self) -> None: ...


MapperFactory = Callable[[], ChunkMapper]
Cancelled = Callable[[], bool]


class ExecutionResults(tuple[ChunkExecutionResult, ...]):
    """Per-chunk terminal results with a sanitized ledger of actual provider submissions."""

    attempts: tuple[ChunkExecutionResult, ...]

    def __new__(
        cls,
        results: tuple[ChunkExecutionResult, ...],
        attempts: tuple[ChunkExecutionResult, ...],
    ) -> ExecutionResults:
        value = super().__new__(cls, results)
        value.attempts = attempts
        return value


def prepare_preview(
    scope: StoryScope,
    chunks: tuple[StoryChunk, ...],
    *,
    mode: ExecutionMode,
    allow_local_fallback: bool,
    local_model: str | None = None,
    local_endpoint: str | None = None,
) -> RunPreview:
    """Create a zero-submit preview whose hash binds every executable input. Track B owns it."""

    if not chunks:
        raise ValueError("At least one ordered story chunk is required.")
    _validate_ordered_chunks(chunks)
    if mode is ExecutionMode.CLOUD_PRIMARY:
        if len(chunks) > MAXIMUM_HOSTED_PLANNED:
            raise ValueError("The planned cloud packet count exceeds the six-call ceiling.")
        if allow_local_fallback:
            selected_local_model = local_model or LOCAL_MAPPER_MODEL
            if selected_local_model != LOCAL_MAPPER_MODEL:
                raise ValueError("Local fallback is locked to the approved mapper model.")
            selected_local_endpoint = _normalize_local_endpoint(
                local_endpoint or LOCAL_MAPPER_ENDPOINT
            )
        elif local_model is not None or local_endpoint is not None:
            raise ValueError("A local model and endpoint require enabled local fallback.")
        else:
            selected_local_model = None
            selected_local_endpoint = None
        cloud_settings: ProviderSettings | None = ProviderSettings(
            model=CLOUD_MAPPER_MODEL,
            reasoning="high",
            fast_mode=False,
        )
        maximum_hosted_planned = MAXIMUM_HOSTED_PLANNED
        maximum_hosted_absolute = MAXIMUM_HOSTED_ABSOLUTE
        maximum_local = len(chunks) if allow_local_fallback else 0
    elif mode is ExecutionMode.LOCAL_ONLY:
        if allow_local_fallback:
            raise ValueError("Local-only execution cannot also enable cloud refusal fallback.")
        selected_local_model = local_model or LOCAL_MAPPER_MODEL
        if selected_local_model != LOCAL_MAPPER_MODEL:
            raise ValueError("Local-only execution is locked to the approved mapper model.")
        selected_local_endpoint = _normalize_local_endpoint(
            local_endpoint or LOCAL_MAPPER_ENDPOINT
        )
        cloud_settings = None
        maximum_hosted_planned = 0
        maximum_hosted_absolute = 0
        maximum_local = len(chunks)
    else:  # pragma: no cover - StrEnum exhaustiveness guard
        raise ValueError("Unsupported Story Map V2 execution mode.")

    return RunPreview(
        schema=PREVIEW_SCHEMA_VERSION,
        source_identity=scope.source_identity,
        chunk_identities=tuple(chunk.identity for chunk in chunks),
        packet_hashes=tuple(chunk.packet_hash for chunk in chunks),
        payload_hashes=tuple(chunk.payload_hash for chunk in chunks),
        transmitted_fields=TRANSMITTED_FIELDS,
        prompt_version=MAPPER_PROMPT_VERSION,
        mapper_schema=MAPPER_SCHEMA_VERSION,
        mode=mode,
        cloud_settings=cloud_settings,
        allow_local_fallback=allow_local_fallback,
        local_model=selected_local_model,
        local_endpoint=selected_local_endpoint,
        maximum_hosted_planned=maximum_hosted_planned,
        maximum_hosted_absolute=maximum_hosted_absolute,
        maximum_local=maximum_local,
        privacy_exclusions=PRIVACY_EXCLUSIONS,
    )


def execute_chunks(
    preview: RunPreview,
    confirmed_hash: str,
    chunks: tuple[StoryChunk, ...],
    *,
    cloud_factory: MapperFactory | None,
    local_factory: MapperFactory | None,
    cancelled: Cancelled,
) -> ExecutionResults:
    """Execute one exact confirmed plan without retry, substitution, or provider cascade."""

    _validate_confirmation(preview, confirmed_hash, chunks)
    if preview.mode is ExecutionMode.LOCAL_ONLY:
        return _execute_local_only(
            chunks,
            local_factory=local_factory,
            expected_endpoint=preview.local_endpoint,
            cancelled=cancelled,
        )
    if cancelled():
        return ExecutionResults(tuple(_cancelled_result(chunk) for chunk in chunks), ())
    if cloud_factory is None:
        return ExecutionResults(
            tuple(
                _failure_result(chunk, FailureKind.TRANSPORT, elapsed_ms=0)
                for chunk in chunks
            ),
            (),
        )

    # Confirmation and the current packet plan have already been checked.  The provider is
    # constructed only now, immediately before the first possible submission.
    try:
        cloud = cloud_factory()
    except Exception:
        return ExecutionResults(
            tuple(
                _failure_result(chunk, FailureKind.TRANSPORT, elapsed_ms=0)
                for chunk in chunks
            ),
            (),
        )
    try:
        resolved_model = cloud.resolved_model
    except Exception:
        resolved_model = None
    if resolved_model != CLOUD_MAPPER_MODEL:
        return ExecutionResults(
            tuple(
                _failure_result(
                    chunk,
                    FailureKind.IDENTITY,
                    elapsed_ms=0,
                    resolved_model=resolved_model if isinstance(resolved_model, str) else None,
                )
                for chunk in chunks
            ),
            (),
        )

    results: list[ChunkExecutionResult] = []
    attempts: list[ChunkExecutionResult] = []
    local: ChunkMapper | None = None
    local_failure: FailureKind | None = None
    for offset, chunk in enumerate(chunks):
        if cancelled():
            _cancel_mapper(cloud)
            _cancel_mapper(local)
            results.extend(_cancelled_result(item) for item in chunks[offset:])
            break
        started = time.monotonic()
        try:
            stop_monitor, monitor = _start_cancellation_monitor(cloud, cancelled)
            try:
                response = cloud.map_chunk(chunk)
            finally:
                _stop_cancellation_monitor(stop_monitor, monitor)
        except ProviderFailure as exc:
            elapsed_ms = round((time.monotonic() - started) * 1000)
            if exc.kind is FailureKind.CANCELLED:
                _cancel_mapper(cloud)
                cloud_attempt = _cancelled_result(
                    chunk,
                    elapsed_ms=elapsed_ms,
                    resolved_model=_observed_model(cloud),
                    input_tokens=_optional_usage(cloud, "input_tokens"),
                    output_tokens=_optional_usage(cloud, "output_tokens"),
                )
                attempts.append(cloud_attempt)
                results.append(cloud_attempt)
                results.extend(_cancelled_result(item) for item in chunks[offset + 1 :])
                break
            cloud_attempt = _failure_result(
                chunk,
                exc.kind,
                elapsed_ms=elapsed_ms,
                resolved_model=_observed_model(cloud),
                input_tokens=_optional_usage(cloud, "input_tokens"),
                output_tokens=_optional_usage(cloud, "output_tokens"),
            )
            attempts.append(cloud_attempt)
            if exc.kind is FailureKind.CONTENT_REFUSAL and preview.allow_local_fallback:
                if local is None and local_failure is None:
                    local, local_failure, local_resolved_model = _construct_local(
                        local_factory, preview.local_endpoint
                    )
                if local is None:
                    assert local_failure is not None
                    results.append(
                        _failure_result(
                            chunk,
                            local_failure,
                            elapsed_ms=elapsed_ms,
                            local=True,
                            resolved_model=local_resolved_model,
                        )
                    )
                    continue
                local_result = _submit_local(
                    chunk,
                    local,
                    origin=ProviderOrigin.LOCAL_FALLBACK,
                    cancelled=cancelled,
                )
                attempts.append(local_result)
                results.append(local_result)
                if local_result.failure_kind is FailureKind.CANCELLED:
                    _cancel_mapper(local)
                    _cancel_mapper(cloud)
                    results.extend(_cancelled_result(item) for item in chunks[offset + 1 :])
                    break
                continue
            results.append(cloud_attempt)
            if exc.kind is FailureKind.IDENTITY:
                results.extend(
                    _failure_result(
                        item,
                        FailureKind.IDENTITY,
                        elapsed_ms=0,
                        resolved_model=_observed_model(cloud),
                    )
                    for item in chunks[offset + 1 :]
                )
                break
        except Exception:
            cloud_attempt = _failure_result(
                chunk,
                FailureKind.TRANSPORT,
                elapsed_ms=round((time.monotonic() - started) * 1000),
                resolved_model=_observed_model(cloud),
                input_tokens=_optional_usage(cloud, "input_tokens"),
                output_tokens=_optional_usage(cloud, "output_tokens"),
            )
            attempts.append(cloud_attempt)
            results.append(cloud_attempt)
        else:
            cloud_attempt = ChunkExecutionResult(
                chunk_identity=chunk.identity,
                origin=ProviderOrigin.CLOUD,
                status=ChunkStatus.COMPLETE,
                response=response,
                failure_kind=None,
                elapsed_ms=round((time.monotonic() - started) * 1000),
                response_hash=canonical_hash(asdict(response)),
                sanitized_reason=None,
                input_tokens=_optional_usage(cloud, "input_tokens"),
                output_tokens=_optional_usage(cloud, "output_tokens"),
                requested_model=CLOUD_MAPPER_MODEL,
                resolved_model=_observed_model(cloud),
                reasoning="high",
                fast_mode=False,
            )
            attempts.append(cloud_attempt)
            results.append(cloud_attempt)
    return ExecutionResults(tuple(results), tuple(attempts))


def _execute_local_only(
    chunks: tuple[StoryChunk, ...],
    *,
    local_factory: MapperFactory | None,
    expected_endpoint: str | None,
    cancelled: Cancelled,
) -> ExecutionResults:
    """Execute a deliberate local-only plan while constructing no cloud provider."""

    if cancelled():
        return ExecutionResults(
            tuple(_cancelled_result(chunk, local=True) for chunk in chunks), ()
        )
    local, failure, resolved_model = _construct_local(local_factory, expected_endpoint)
    if local is None:
        assert failure is not None
        return ExecutionResults(
            tuple(
                _failure_result(
                    chunk,
                    failure,
                    elapsed_ms=0,
                    local=True,
                    resolved_model=resolved_model,
                )
                for chunk in chunks
            ),
            (),
        )

    results: list[ChunkExecutionResult] = []
    attempts: list[ChunkExecutionResult] = []
    for offset, chunk in enumerate(chunks):
        if cancelled():
            _cancel_mapper(local)
            results.extend(
                _cancelled_result(
                    item,
                    local=True,
                    resolved_model=_observed_model(local),
                )
                for item in chunks[offset:]
            )
            break
        result = _submit_local(
            chunk,
            local,
            origin=ProviderOrigin.LOCAL_ONLY,
            cancelled=cancelled,
        )
        attempts.append(result)
        results.append(result)
        if result.failure_kind is FailureKind.CANCELLED:
            _cancel_mapper(local)
            results.extend(
                _cancelled_result(
                    item,
                    local=True,
                    resolved_model=_observed_model(local),
                )
                for item in chunks[offset + 1 :]
            )
            break
    return ExecutionResults(tuple(results), tuple(attempts))


def _construct_local(
    local_factory: MapperFactory | None,
    expected_endpoint: str | None,
) -> tuple[ChunkMapper | None, FailureKind | None, str | None]:
    if local_factory is None:
        return None, FailureKind.LOCAL_UNAVAILABLE, None
    try:
        local = local_factory()
    except ProviderFailure as exc:
        return None, _local_failure_kind(exc.kind), None
    except Exception:
        return None, FailureKind.LOCAL_UNAVAILABLE, None
    try:
        resolved_model = local.resolved_model
    except ProviderFailure as exc:
        return None, _local_failure_kind(exc.kind), None
    except Exception:
        return None, FailureKind.LOCAL_UNAVAILABLE, None
    if resolved_model != LOCAL_MAPPER_MODEL:
        return (
            None,
            FailureKind.IDENTITY,
            resolved_model if isinstance(resolved_model, str) else None,
        )
    if expected_endpoint is None or _mapper_endpoint(local) != expected_endpoint:
        return None, FailureKind.IDENTITY, _observed_model(local)
    return local, None, _observed_model(local)


def _submit_local(
    chunk: StoryChunk,
    local: ChunkMapper,
    *,
    origin: ProviderOrigin,
    cancelled: Cancelled,
) -> ChunkExecutionResult:
    """Submit the unchanged confirmed StoryChunk exactly once to the local mapper."""

    started = time.monotonic()
    try:
        stop_monitor, monitor = _start_cancellation_monitor(local, cancelled)
        try:
            response = local.map_chunk(chunk)
        finally:
            _stop_cancellation_monitor(stop_monitor, monitor)
    except ProviderFailure as exc:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        if exc.kind is FailureKind.CANCELLED:
            return _cancelled_result(
                chunk,
                elapsed_ms=elapsed_ms,
                local=True,
                resolved_model=_observed_model(local),
                input_tokens=_optional_usage(local, "input_tokens"),
                output_tokens=_optional_usage(local, "output_tokens"),
            )
        return _failure_result(
            chunk,
            _local_failure_kind(exc.kind),
            elapsed_ms=elapsed_ms,
            local=True,
            resolved_model=_observed_model(local),
            input_tokens=_optional_usage(local, "input_tokens"),
            output_tokens=_optional_usage(local, "output_tokens"),
        )
    except Exception:
        return _failure_result(
            chunk,
            FailureKind.LOCAL_UNAVAILABLE,
            elapsed_ms=round((time.monotonic() - started) * 1000),
            local=True,
            resolved_model=_observed_model(local),
            input_tokens=_optional_usage(local, "input_tokens"),
            output_tokens=_optional_usage(local, "output_tokens"),
        )
    return ChunkExecutionResult(
        chunk_identity=chunk.identity,
        origin=origin,
        status=ChunkStatus.COMPLETE,
        response=response,
        failure_kind=None,
        elapsed_ms=max(0, round((time.monotonic() - started) * 1000)),
        response_hash=canonical_hash(asdict(response)),
        sanitized_reason=None,
        input_tokens=_optional_usage(local, "input_tokens"),
        output_tokens=_optional_usage(local, "output_tokens"),
        requested_model=LOCAL_MAPPER_MODEL,
        resolved_model=_observed_model(local),
        reasoning=None,
        fast_mode=None,
    )


def _local_failure_kind(kind: FailureKind) -> FailureKind:
    if kind in {
        FailureKind.CONTENT_REFUSAL,
        FailureKind.TIMEOUT,
        FailureKind.RATE_LIMIT,
        FailureKind.AUTHENTICATION,
        FailureKind.TRANSPORT,
        FailureKind.INVALID_RESPONSE,
        FailureKind.IDENTITY,
        FailureKind.CANCELLED,
        FailureKind.LOCAL_UNAVAILABLE,
    }:
        return kind
    return FailureKind.INVALID_RESPONSE


def _cancel_mapper(mapper: ChunkMapper | None) -> None:
    if mapper is None:
        return
    with suppress(Exception):
        mapper.cancel()


def _start_cancellation_monitor(
    mapper: ChunkMapper,
    cancelled: Cancelled,
) -> tuple[threading.Event, threading.Thread]:
    stop = threading.Event()

    def monitor() -> None:
        while not stop.wait(0.01):
            try:
                requested = cancelled()
            except Exception:
                requested = True
            if requested:
                _cancel_mapper(mapper)
                return

    thread = threading.Thread(target=monitor, name="story-map-v2-cancel", daemon=True)
    thread.start()
    return stop, thread


def _stop_cancellation_monitor(stop: threading.Event, thread: threading.Thread) -> None:
    stop.set()
    thread.join(timeout=0.1)


def _validate_ordered_chunks(chunks: tuple[StoryChunk, ...]) -> None:
    expected = tuple(range(1, len(chunks) + 1))
    if tuple(chunk.index for chunk in chunks) != expected:
        raise ValueError("Story chunks must be complete and ordered from index one.")
    identities = tuple(chunk.identity for chunk in chunks)
    if len(set(identities)) != len(identities):
        raise ValueError("Story chunk identities must be unique.")


def _normalize_local_endpoint(endpoint: str) -> str:
    if not isinstance(endpoint, str) or not endpoint:
        raise ValueError("The local endpoint must be an explicit loopback URL.")
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme.casefold() != "http"
        or parsed.hostname is None
        or parsed.hostname.casefold() not in {"127.0.0.1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/v1"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("The local endpoint must be a loopback-only HTTP /v1 URL.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("The local endpoint port is invalid.") from exc
    host = parsed.hostname.casefold()
    return f"http://{host}{f':{port}' if port is not None else ''}/v1"


def _validate_confirmation(
    preview: RunPreview,
    confirmed_hash: str,
    chunks: tuple[StoryChunk, ...],
) -> None:
    """Fail closed before either provider factory can be constructed."""

    if not isinstance(confirmed_hash, str) or not hmac.compare_digest(
        preview.confirmation_hash, confirmed_hash
    ):
        raise ValueError("The run confirmation does not match the prepared preview.")
    _validate_ordered_chunks(chunks)
    if preview.chunk_identities != tuple(chunk.identity for chunk in chunks):
        raise ValueError("The confirmed story chunk identities changed after preview.")
    if preview.packet_hashes != tuple(chunk.packet_hash for chunk in chunks):
        raise ValueError("The confirmed story packets changed after preview.")
    if preview.payload_hashes != tuple(chunk.payload_hash for chunk in chunks):
        raise ValueError("The confirmed provider payloads changed after preview.")
    if preview.schema != PREVIEW_SCHEMA_VERSION:
        raise ValueError("The confirmed preview schema is not supported.")
    if preview.prompt_version != MAPPER_PROMPT_VERSION:
        raise ValueError("The confirmed mapper prompt version changed.")
    if preview.mapper_schema != MAPPER_SCHEMA_VERSION:
        raise ValueError("The confirmed mapper schema changed.")
    if preview.transmitted_fields != TRANSMITTED_FIELDS:
        raise ValueError("The confirmed transmitted fields changed.")
    if preview.privacy_exclusions != PRIVACY_EXCLUSIONS:
        raise ValueError("The confirmed privacy exclusions changed.")
    if preview.mode is ExecutionMode.CLOUD_PRIMARY:
        if preview.cloud_settings != ProviderSettings(
            model=CLOUD_MAPPER_MODEL, reasoning="high", fast_mode=False
        ):
            raise ValueError("Cloud mapping requires exact Luna, High, fast-off settings.")
        if (
            preview.maximum_hosted_planned != MAXIMUM_HOSTED_PLANNED
            or preview.maximum_hosted_absolute != MAXIMUM_HOSTED_ABSOLUTE
            or len(chunks) > MAXIMUM_HOSTED_PLANNED
        ):
            raise ValueError("The confirmed hosted-call ceilings changed.")
        expected_local = len(chunks) if preview.allow_local_fallback else 0
        if preview.maximum_local != expected_local:
            raise ValueError("The confirmed local-call ceiling changed.")
        if preview.allow_local_fallback:
            _validate_local_binding(preview)
        elif preview.local_model is not None or preview.local_endpoint is not None:
            raise ValueError("The confirmed local fallback binding changed.")
    elif preview.mode is ExecutionMode.LOCAL_ONLY:
        if (
            preview.cloud_settings is not None
            or preview.maximum_hosted_planned != 0
            or preview.maximum_hosted_absolute != 0
            or preview.allow_local_fallback
            or preview.maximum_local != len(chunks)
        ):
            raise ValueError("The confirmed local-only settings changed.")
        _validate_local_binding(preview)
    else:  # pragma: no cover - StrEnum exhaustiveness guard
        raise ValueError("The confirmed execution mode is unsupported.")


def _validate_local_binding(preview: RunPreview) -> None:
    if preview.local_model != LOCAL_MAPPER_MODEL or preview.local_endpoint is None:
        raise ValueError("The confirmed local model or endpoint changed.")
    try:
        endpoint = _normalize_local_endpoint(preview.local_endpoint)
    except ValueError:
        raise ValueError("The confirmed local endpoint is not loopback-only.") from None
    if endpoint != preview.local_endpoint:
        raise ValueError("The confirmed local endpoint is not canonical.")


def _optional_usage(mapper: ChunkMapper, name: str) -> int | None:
    value = getattr(mapper, name, None)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


_MISSING = object()


def _observed_model(mapper: ChunkMapper) -> str | None:
    """Return actual observed identity when a transport exposes it, else its verified seam."""

    observed = getattr(mapper, "observed_model", _MISSING)
    if observed is not _MISSING:
        return observed if isinstance(observed, str) and observed else None
    resolved = getattr(mapper, "resolved_model", None)
    return resolved if isinstance(resolved, str) and resolved else None


def _mapper_endpoint(mapper: ChunkMapper) -> str | None:
    try:
        endpoint = getattr(mapper, "endpoint", None)
    except Exception:
        return None
    return endpoint if isinstance(endpoint, str) and endpoint else None


def _failure_result(
    chunk: StoryChunk,
    kind: FailureKind,
    *,
    elapsed_ms: int,
    local: bool = False,
    resolved_model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> ChunkExecutionResult:
    return ChunkExecutionResult(
        chunk_identity=chunk.identity,
        origin=ProviderOrigin.MISSING,
        status=ChunkStatus.MISSING,
        response=None,
        failure_kind=kind,
        elapsed_ms=max(0, elapsed_ms),
        response_hash=None,
        sanitized_reason=(_LOCAL_SANITIZED_REASONS if local else _SANITIZED_REASONS)[kind],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        requested_model=LOCAL_MAPPER_MODEL if local else CLOUD_MAPPER_MODEL,
        resolved_model=resolved_model,
        reasoning=None if local else "high",
        fast_mode=None if local else False,
    )


def _cancelled_result(
    chunk: StoryChunk,
    *,
    elapsed_ms: int = 0,
    local: bool = False,
    resolved_model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> ChunkExecutionResult:
    return ChunkExecutionResult(
        chunk_identity=chunk.identity,
        origin=ProviderOrigin.MISSING,
        status=ChunkStatus.CANCELLED,
        response=None,
        failure_kind=FailureKind.CANCELLED,
        elapsed_ms=max(0, elapsed_ms),
        response_hash=None,
        sanitized_reason=(
            _LOCAL_SANITIZED_REASONS if local else _SANITIZED_REASONS
        )[FailureKind.CANCELLED],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        requested_model=LOCAL_MAPPER_MODEL if local else CLOUD_MAPPER_MODEL,
        resolved_model=resolved_model,
        reasoning=None if local else "high",
        fast_mode=None if local else False,
    )


_SANITIZED_REASONS = {
    FailureKind.CONTENT_REFUSAL: "The cloud mapper declined this section for content or safety.",
    FailureKind.TIMEOUT: "The cloud mapper timed out.",
    FailureKind.RATE_LIMIT: "The cloud mapper is rate limited.",
    FailureKind.AUTHENTICATION: "Cloud mapper authentication failed.",
    FailureKind.TRANSPORT: "The cloud mapper transport failed.",
    FailureKind.INVALID_RESPONSE: "The cloud mapper returned an invalid response.",
    FailureKind.IDENTITY: "The cloud mapper identity or settings did not match.",
    FailureKind.CANCELLED: "Cloud mapping was cancelled.",
    FailureKind.LOCAL_UNAVAILABLE: "The confirmed local mapper is unavailable.",
}

_LOCAL_SANITIZED_REASONS = {
    FailureKind.CONTENT_REFUSAL: "The local mapper declined this section.",
    FailureKind.TIMEOUT: "The local mapper timed out.",
    FailureKind.RATE_LIMIT: "The local mapper is rate limited.",
    FailureKind.AUTHENTICATION: "Local mapper authentication failed.",
    FailureKind.TRANSPORT: "The local mapper transport failed.",
    FailureKind.INVALID_RESPONSE: "The local mapper returned an invalid response.",
    FailureKind.IDENTITY: "The confirmed local mapper model did not match.",
    FailureKind.CANCELLED: "Local mapping was cancelled.",
    FailureKind.LOCAL_UNAVAILABLE: "The confirmed local mapper is unavailable.",
}
