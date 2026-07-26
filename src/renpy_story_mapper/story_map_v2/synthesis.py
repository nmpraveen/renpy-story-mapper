"""Optional one-call whole-story synthesis over accepted Story Map V2 anchors."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Protocol, cast

from renpy_story_mapper.story_map_v2.contracts import (
    CoreEvent,
    StoryMapCore,
    canonical_hash,
    canonical_json,
)
from renpy_story_mapper.story_map_v2.phase03_contracts import (
    SYNTHESIS_PREVIEW_SCHEMA,
    SYNTHESIS_PROMPT_VERSION,
    SYNTHESIS_RECORD_SCHEMA,
    SYNTHESIS_REQUEST_SCHEMA,
    SYNTHESIS_RESPONSE_SCHEMA,
    StoryMapProjectIdentity,
    SynthesisArmInput,
    SynthesisChoiceInput,
    SynthesisEventInput,
    SynthesisExecutionResult,
    SynthesisFailureKind,
    SynthesisOutcomeInput,
    SynthesisPreview,
    SynthesisProviderReply,
    SynthesisProviderSettings,
    SynthesisRequest,
    SynthesisResponse,
    SynthesisSection,
    SynthesisStatus,
    SynthesisThread,
    ValidatedSynthesis,
)

_TRANSMITTED_FIELDS = (
    "schema",
    "prompt_version",
    "instructions",
    "events",
    "branch_outcomes",
    "choices",
)
_INSTRUCTIONS = (
    "Group only the supplied event anchor IDs into five to seven chronological sections.",
    "Do not invent, duplicate, reorder, or reinterpret anchors or mechanics.",
    "Return only the response object defined by the supplied JSON schema.",
)
_PRIVACY_EXCLUSIONS = (
    "raw Ren'Py or game source",
    "source paths",
    "private references or prior provider responses",
    "screenshots, secrets, unrelated files, or game assets",
)


class SynthesisValidationError(ValueError):
    """Provider output or a frozen synthesis contract is structurally invalid."""


class SynthesisRefusalError(RuntimeError):
    """A sterile provider explicitly refused the one allowed synthesis call."""


class SynthesisProviderFailure(RuntimeError):
    """Sanitized production-provider failure with exact submission accounting."""

    def __init__(
        self,
        kind: SynthesisFailureKind,
        reason: str,
        *,
        call_count: int,
        provider: str | None = None,
        resolved_model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        elapsed_ms: int = 0,
    ) -> None:
        super().__init__(reason)
        if call_count not in {0, 1}:
            raise ValueError("provider failure call count must be zero or one")
        self.kind = kind
        self.reason = reason
        self.call_count = call_count
        self.provider = provider
        self.resolved_model = resolved_model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.elapsed_ms = elapsed_ms


class SynthesisProvider(Protocol):
    def synthesize(
        self,
        payload: bytes,
        *,
        response_schema: Mapping[str, object],
        settings: SynthesisProviderSettings,
    ) -> SynthesisProviderReply: ...


def _events(core: StoryMapCore) -> tuple[CoreEvent, ...]:
    return tuple(event for chunk in core.chunks for event in chunk.events)


def build_synthesis_request(
    core: StoryMapCore,
    identity: StoryMapProjectIdentity,
) -> SynthesisRequest:
    """Build the exact story-facing request without source paths or raw source text."""

    if core.source_identity != identity.source_identity or core.schema != identity.core_schema:
        raise ValueError("core and project identity do not match")
    if canonical_hash(asdict(core)) != identity.core_hash:
        raise ValueError("core hash does not match the project identity")
    events = _events(core)
    anchor_ids = tuple(event.anchor.id for event in events)
    if not events or len(anchor_ids) != len(set(anchor_ids)):
        raise ValueError("accepted core event anchors must be non-empty and unique")
    event_inputs = tuple(
        SynthesisEventInput(
            event.anchor.id,
            event.title,
            event.summary,
            event.characters,
            ordinal,
        )
        for ordinal, event in enumerate(events)
    )
    outcomes = tuple(outcome for chunk in core.chunks for outcome in chunk.branch_outcomes)
    outcome_ids = tuple(item.anchor.id for item in outcomes)
    if len(outcome_ids) != len(set(outcome_ids)):
        raise ValueError("accepted branch-outcome anchors must be unique")
    outcome_inputs = tuple(SynthesisOutcomeInput(item.anchor.id, item.summary) for item in outcomes)

    choices = tuple(choice for chunk in core.chunks for choice in chunk.choices)
    if len({choice.key for choice in choices}) != len(choices):
        raise ValueError("accepted choice keys must be unique")
    aliases = {choice.key: f"choice-{index}" for index, choice in enumerate(choices, start=1)}
    choice_inputs = tuple(
        SynthesisChoiceInput(
            aliases[choice.key],
            tuple(
                SynthesisArmInput(
                    arm.order,
                    arm.caption,
                    arm.condition,
                    arm.effects,
                    arm.destination_id,
                    arm.rejoin_node_id,
                )
                for arm in choice.arms
            ),
            tuple((aliases[step.choice_key], step.arm_order) for step in choice.parent_lineage),
        )
        for choice in choices
    )
    return SynthesisRequest(
        schema=SYNTHESIS_REQUEST_SCHEMA,
        prompt_version=SYNTHESIS_PROMPT_VERSION,
        project_identity_hash=identity.identity_hash,
        events=event_inputs,
        branch_outcomes=outcome_inputs,
        choices=choice_inputs,
        instructions=_INSTRUCTIONS,
        transmitted_fields=_TRANSMITTED_FIELDS,
    )


def _request_value(request: SynthesisRequest) -> dict[str, object]:
    if request.schema != SYNTHESIS_REQUEST_SCHEMA:
        raise SynthesisValidationError("unsupported synthesis request schema")
    if request.prompt_version != SYNTHESIS_PROMPT_VERSION:
        raise SynthesisValidationError("unsupported synthesis prompt version")
    if request.transmitted_fields != _TRANSMITTED_FIELDS:
        raise SynthesisValidationError("synthesis transmitted fields do not match the contract")
    return {
        "schema": request.schema,
        "prompt_version": request.prompt_version,
        "instructions": list(request.instructions),
        "events": [asdict(item) for item in request.events],
        "branch_outcomes": [asdict(item) for item in request.branch_outcomes],
        "choices": [asdict(item) for item in request.choices],
    }


def serialize_synthesis_request(request: SynthesisRequest) -> bytes:
    return canonical_json(_request_value(request))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SynthesisValidationError(f"synthesis response contains duplicate key {key!r}")
        result[key] = value
    return result


def _object(value: object, path: str) -> dict[str, object]:
    if type(value) is not dict:
        raise SynthesisValidationError(f"{path} must be an object")
    return cast(dict[str, object], value)


def _array(value: object, path: str) -> list[object]:
    if type(value) is not list:
        raise SynthesisValidationError(f"{path} must be an array")
    return cast(list[object], value)


def _exact(value: Mapping[str, object], expected: set[str], path: str) -> None:
    if set(value) != expected:
        raise SynthesisValidationError(f"{path} has missing or unsupported fields")


def _text(value: object, path: str, maximum: int) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > maximum:
        raise SynthesisValidationError(f"{path} must be a non-empty trimmed bounded string")
    return value


def _anchor_array(
    value: object,
    path: str,
    order: Mapping[str, int],
) -> tuple[str, ...]:
    raw = _array(value, path)
    if not raw:
        raise SynthesisValidationError(f"{path} must not be empty")
    anchors = tuple(_text(item, f"{path}[]", 256) for item in raw)
    if len(anchors) != len(set(anchors)):
        raise SynthesisValidationError(f"{path} contains duplicate anchors")
    if any(anchor not in order for anchor in anchors):
        raise SynthesisValidationError(f"{path} contains an unknown or foreign anchor")
    ordinals = tuple(order[anchor] for anchor in anchors)
    if ordinals != tuple(sorted(ordinals)):
        raise SynthesisValidationError(f"{path} reverses chronological anchor order")
    return anchors


def deserialize_synthesis_response(
    payload: bytes | str,
    ordered_event_anchor_ids: tuple[str, ...],
) -> SynthesisResponse:
    """Strictly parse response JSON and enforce anchor chronology and uniqueness."""

    if not ordered_event_anchor_ids or len(ordered_event_anchor_ids) != len(
        set(ordered_event_anchor_ids)
    ):
        raise ValueError("accepted event anchor order must be non-empty and unique")
    try:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        decoded = json.loads(text, object_pairs_hook=_unique_object)
    except SynthesisValidationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise SynthesisValidationError("synthesis response is not valid UTF-8 JSON") from exc
    root = _object(decoded, "root")
    _exact(root, {"story_title", "story_overview", "ordered_sections", "optional_threads"}, "root")
    order = {anchor: index for index, anchor in enumerate(ordered_event_anchor_ids)}
    raw_sections = _array(root["ordered_sections"], "ordered_sections")
    if not 5 <= len(raw_sections) <= 7:
        raise SynthesisValidationError("successful synthesis requires five to seven sections")
    sections: list[SynthesisSection] = []
    referenced: list[str] = []
    for index, raw in enumerate(raw_sections):
        path = f"ordered_sections[{index}]"
        value = _object(raw, path)
        _exact(value, {"section_title", "section_summary", "event_anchor_ids"}, path)
        anchors = _anchor_array(value["event_anchor_ids"], f"{path}.event_anchor_ids", order)
        sections.append(
            SynthesisSection(
                _text(value["section_title"], f"{path}.section_title", 160),
                _text(value["section_summary"], f"{path}.section_summary", 1_500),
                anchors,
            )
        )
        referenced.extend(anchors)
    if len(referenced) != len(set(referenced)):
        raise SynthesisValidationError("ordered sections duplicate an event anchor")
    referenced_ordinals = tuple(order[anchor] for anchor in referenced)
    if referenced_ordinals != tuple(sorted(referenced_ordinals)):
        raise SynthesisValidationError("ordered sections reverse chronology")

    threads: list[SynthesisThread] = []
    for index, raw in enumerate(_array(root["optional_threads"], "optional_threads")):
        if index >= 2:
            raise SynthesisValidationError("optional_threads may contain at most two items")
        path = f"optional_threads[{index}]"
        value = _object(raw, path)
        _exact(value, {"title", "summary", "event_anchor_ids"}, path)
        threads.append(
            SynthesisThread(
                _text(value["title"], f"{path}.title", 160),
                _text(value["summary"], f"{path}.summary", 1_000),
                _anchor_array(value["event_anchor_ids"], f"{path}.event_anchor_ids", order),
            )
        )
    return SynthesisResponse(
        _text(root["story_title"], "story_title", 160),
        _text(root["story_overview"], "story_overview", 2_000),
        tuple(sections),
        tuple(threads),
    )


def complete_synthesis(
    response: SynthesisResponse,
    ordered_event_anchor_ids: tuple[str, ...],
) -> ValidatedSynthesis:
    """Place each validly omitted event into its nearest chronological section once."""

    order = {anchor: index for index, anchor in enumerate(ordered_event_anchor_ids)}
    referenced = {
        anchor for section in response.ordered_sections for anchor in section.event_anchor_ids
    }
    omitted = tuple(anchor for anchor in ordered_event_anchor_ids if anchor not in referenced)
    section_anchors = [list(section.event_anchor_ids) for section in response.ordered_sections]
    for anchor in omitted:
        ordinal = order[anchor]
        selected = min(
            range(len(section_anchors)),
            key=lambda index: (
                min(abs(ordinal - order[item]) for item in section_anchors[index]),
                index,
            ),
        )
        section_anchors[selected].append(anchor)
        section_anchors[selected].sort(key=order.__getitem__)
    completed = tuple(
        SynthesisSection(
            section.section_title,
            section.section_summary,
            tuple(section_anchors[index]),
        )
        for index, section in enumerate(response.ordered_sections)
    )
    flattened = tuple(anchor for section in completed for anchor in section.event_anchor_ids)
    if flattened != ordered_event_anchor_ids:
        raise SynthesisValidationError("completed synthesis does not preserve exact chronology")
    notes: tuple[str, ...] = ()
    if omitted:
        if len(omitted) == 1:
            notes = (
                "One accepted event omitted by synthesis was placed chronologically by the app.",
            )
        else:
            notes = (
                f"{len(omitted)} accepted events omitted by synthesis were placed "
                "chronologically by the app.",
            )
    return ValidatedSynthesis(
        response.story_title,
        response.story_overview,
        completed,
        response.optional_threads,
        notes,
    )


def response_schema() -> dict[str, object]:
    path = Path(__file__).with_name("schemas") / "story_map_synthesis_v1.schema.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict or value.get("$id") != SYNTHESIS_RESPONSE_SCHEMA:
        raise RuntimeError("the bundled synthesis response schema has an invalid identity")
    result = cast(dict[str, object], value)
    validate_provider_schema(result)
    return result


_PROVIDER_SCHEMA_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "$ref",
        "$defs",
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
    }
)


def validate_provider_schema(schema: Mapping[str, object]) -> None:
    """Require the recursively strict subset accepted by Codex Structured Outputs."""

    def visit(value: object, path: str) -> None:
        if not isinstance(value, Mapping):
            raise ValueError(f"provider schema {path} must be an object")
        unknown = set(value) - _PROVIDER_SCHEMA_KEYWORDS
        if unknown:
            raise ValueError(f"provider schema {path} contains an unsupported keyword")
        schema_type = value.get("type")
        if schema_type == "object":
            properties = value.get("properties")
            required = value.get("required")
            if not isinstance(properties, Mapping) or not isinstance(required, list):
                raise ValueError(f"provider schema {path} object fields are invalid")
            if any(not isinstance(item, str) for item in required) or set(required) != set(
                properties
            ):
                raise ValueError(
                    f"provider schema {path} required fields must equal properties"
                )
            if value.get("additionalProperties") is not False:
                raise ValueError(
                    f"provider schema {path} must set additionalProperties to false"
                )
            for name, child in properties.items():
                visit(child, f"{path}/properties/{name}")
        elif schema_type == "array":
            if "items" not in value:
                raise ValueError(f"provider schema {path} array items are required")
            visit(value["items"], f"{path}/items")
        elif schema_type is not None and schema_type != "string":
            raise ValueError(f"provider schema {path} has an unsupported type")
        definitions = value.get("$defs")
        if definitions is not None:
            if not isinstance(definitions, Mapping):
                raise ValueError(f"provider schema {path}/$defs must be an object")
            for name, child in definitions.items():
                visit(child, f"{path}/$defs/{name}")

    visit(schema, "$")


def build_synthesis_preview(request: SynthesisRequest) -> SynthesisPreview:
    payload = serialize_synthesis_request(request)
    return SynthesisPreview(
        SYNTHESIS_PREVIEW_SCHEMA,
        request.project_identity_hash,
        canonical_hash(json.loads(payload)),
        request.prompt_version,
        SYNTHESIS_RESPONSE_SCHEMA,
        request.transmitted_fields,
        SynthesisProviderSettings(),
        1,
        _PRIVACY_EXCLUSIONS,
    )


def _failure(
    request: SynthesisRequest,
    preview: SynthesisPreview,
    kind: SynthesisFailureKind,
    reason: str,
    *,
    provider: str | None = None,
    resolved_model: str | None = None,
    call_count: int = 0,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    elapsed_ms: int = 0,
) -> SynthesisExecutionResult:
    return SynthesisExecutionResult(
        SYNTHESIS_RECORD_SCHEMA,
        request.project_identity_hash,
        preview.request_payload_hash,
        preview.confirmation_hash,
        preview.prompt_version,
        preview.response_schema,
        SynthesisStatus.FAILED,
        None,
        provider,
        preview.settings.model,
        resolved_model,
        preview.settings.reasoning,
        preview.settings.fast_mode,
        call_count,
        input_tokens,
        output_tokens,
        elapsed_ms,
        kind,
        reason,
    )


def execute_synthesis(
    request: SynthesisRequest,
    preview: SynthesisPreview,
    provider_factory: Callable[[], SynthesisProvider],
) -> SynthesisExecutionResult:
    """Execute exactly one provider call, with no retry, auditor, or substitution."""

    expected = build_synthesis_preview(request)
    if preview != expected:
        raise ValueError("synthesis preview is stale or does not bind the exact request")
    payload = serialize_synthesis_request(request)
    try:
        provider = provider_factory()
    except Exception:
        return _failure(
            request,
            preview,
            SynthesisFailureKind.TRANSPORT,
            "The synthesis provider was unavailable before submission.",
        )
    try:
        reply = provider.synthesize(
            payload,
            response_schema=response_schema(),
            settings=preview.settings,
        )
    except SynthesisProviderFailure as exc:
        return _failure(
            request,
            preview,
            exc.kind,
            exc.reason,
            provider=exc.provider,
            resolved_model=exc.resolved_model,
            call_count=exc.call_count,
            input_tokens=exc.input_tokens,
            output_tokens=exc.output_tokens,
            elapsed_ms=exc.elapsed_ms,
        )
    except SynthesisRefusalError:
        return _failure(
            request,
            preview,
            SynthesisFailureKind.REFUSED,
            "The provider refused the synthesis request.",
            call_count=1,
        )
    except TimeoutError:
        return _failure(
            request,
            preview,
            SynthesisFailureKind.TIMEOUT,
            "The synthesis request timed out.",
            call_count=1,
        )
    except Exception:
        return _failure(
            request,
            preview,
            SynthesisFailureKind.TRANSPORT,
            "The synthesis transport failed after submission.",
            call_count=1,
        )
    if type(reply) is not SynthesisProviderReply:
        return _failure(
            request,
            preview,
            SynthesisFailureKind.IDENTITY,
            "The provider identity or usage provenance could not be verified.",
            call_count=1,
        )
    usage_valid = all(
        value is None or (type(value) is int and value >= 0)
        for value in (reply.input_tokens, reply.output_tokens)
    )
    identity_valid = (
        isinstance(reply.provider, str)
        and reply.provider.strip() != ""
        and isinstance(reply.requested_model, str)
        and reply.requested_model == preview.settings.model
        and isinstance(reply.resolved_model, str)
        and reply.resolved_model == preview.settings.model
        and isinstance(reply.reasoning, str)
        and reply.reasoning == preview.settings.reasoning
        and reply.fast_mode is preview.settings.fast_mode
        and type(reply.elapsed_ms) is int
        and reply.elapsed_ms >= 0
        and usage_valid
    )
    if not identity_valid:
        failed_provider = (
            reply.provider if isinstance(reply.provider, str) and reply.provider else None
        )
        failed_model = (
            reply.resolved_model
            if isinstance(reply.resolved_model, str) and reply.resolved_model
            else None
        )
        failed_elapsed = (
            reply.elapsed_ms if type(reply.elapsed_ms) is int and reply.elapsed_ms >= 0 else 0
        )
        return _failure(
            request,
            preview,
            SynthesisFailureKind.IDENTITY,
            "The provider identity or usage provenance could not be verified.",
            provider=failed_provider,
            resolved_model=failed_model,
            call_count=1,
            input_tokens=reply.input_tokens if usage_valid else None,
            output_tokens=reply.output_tokens if usage_valid else None,
            elapsed_ms=failed_elapsed,
        )
    try:
        response = deserialize_synthesis_response(
            reply.payload,
            tuple(item.anchor_id for item in request.events),
        )
        synthesis = complete_synthesis(
            response,
            tuple(item.anchor_id for item in request.events),
        )
    except SynthesisValidationError:
        return _failure(
            request,
            preview,
            SynthesisFailureKind.INVALID_RESPONSE,
            "The provider returned an invalid synthesis response.",
            provider=reply.provider,
            resolved_model=reply.resolved_model,
            call_count=1,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            elapsed_ms=reply.elapsed_ms,
        )
    return SynthesisExecutionResult(
        SYNTHESIS_RECORD_SCHEMA,
        request.project_identity_hash,
        preview.request_payload_hash,
        preview.confirmation_hash,
        preview.prompt_version,
        preview.response_schema,
        SynthesisStatus.SUCCEEDED,
        synthesis,
        reply.provider,
        reply.requested_model,
        reply.resolved_model,
        reply.reasoning,
        reply.fast_mode,
        1,
        reply.input_tokens,
        reply.output_tokens,
        reply.elapsed_ms,
        None,
        None,
    )
