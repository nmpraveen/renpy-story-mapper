"""Deterministic Story Map V2 mapper packet and response JSON handling."""

from __future__ import annotations

import json
import re
from typing import cast

from renpy_story_mapper.story_map_v2.contracts import (
    MAPPER_SCHEMA_VERSION,
    BranchSummary,
    MapperEvent,
    MapperResponse,
    StoryChunk,
    canonical_json,
)

MAPPER_PROMPT_VERSION = "story-map-v2-mapper-prompt-v1"
_LINE_NUMBERED = re.compile(r"^\d+:(?:\s|$)")


class MapperSerializationError(ValueError):
    """A frozen story chunk cannot be serialized without changing its packet."""


class MapperResponseValidationError(ValueError):
    """Mapper JSON violates the frozen provider-neutral response schema."""


def _decoded_mechanics(chunk: StoryChunk) -> dict[str, object]:
    try:
        value = json.loads(chunk.mechanics)
    except json.JSONDecodeError as exc:  # StoryChunk also checks this; defend the I/O boundary.
        raise MapperSerializationError("chunk mechanics are not valid canonical JSON") from exc
    if type(value) is not dict:
        raise MapperSerializationError("chunk mechanics must be one JSON object")
    mechanics = cast(dict[str, object], value)
    if set(mechanics) != {"choices"} or type(mechanics["choices"]) is not list:
        raise MapperSerializationError("chunk mechanics must contain only a choices array")
    choices = cast(list[object], mechanics["choices"])
    keys: list[str] = []
    for index, choice_value in enumerate(choices):
        if type(choice_value) is not dict:
            raise MapperSerializationError(f"chunk mechanics choices[{index}] must be an object")
        choice = cast(dict[str, object], choice_value)
        key = choice.get("key")
        if type(key) is not str or not key:
            raise MapperSerializationError(
                f"chunk mechanics choices[{index}].key must be a non-empty string"
            )
        keys.append(key)
    if tuple(keys) != chunk.choice_keys:
        raise MapperSerializationError(
            "chunk mechanics choice keys do not match the frozen StoryChunk choice order"
        )
    return mechanics


def serialize_mapper_request(
    chunk: StoryChunk,
    *,
    prompt_version: str = MAPPER_PROMPT_VERSION,
) -> bytes:
    """Serialize exact line-numbered story and canonical mechanics for either provider path."""

    if not prompt_version or prompt_version != prompt_version.strip():
        raise MapperSerializationError("prompt version must be a non-empty trimmed string")
    lines = chunk.raw_text.splitlines()
    if not lines or any(_LINE_NUMBERED.match(line) is None for line in lines):
        raise MapperSerializationError("chunk raw text must contain only line-numbered story text")
    return canonical_json(
        {
            "schema": MAPPER_SCHEMA_VERSION,
            "prompt_version": prompt_version,
            "chunk_identity": chunk.identity,
            "packet_hash": chunk.packet_hash,
            "raw_text": chunk.raw_text,
            "mechanics": _decoded_mechanics(chunk),
        }
    )


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MapperResponseValidationError(
                f"mapper response contains duplicate object key {key!r}"
            )
        result[key] = value
    return result


def _object(value: object, path: str) -> dict[str, object]:
    if type(value) is not dict:
        raise MapperResponseValidationError(f"mapper response {path} must be an object")
    return cast(dict[str, object], value)


def _array(value: object, path: str) -> list[object]:
    if type(value) is not list:
        raise MapperResponseValidationError(f"mapper response {path} must be an array")
    return cast(list[object], value)


def _exact_keys(
    value: dict[str, object],
    path: str,
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> None:
    actual = set(value)
    missing = required - actual
    if missing:
        raise MapperResponseValidationError(
            f"mapper response {path} is missing required key {sorted(missing)[0]!r}"
        )
    unknown = actual - required - optional
    if unknown:
        raise MapperResponseValidationError(
            f"mapper response {path} contains unsupported key {sorted(unknown)[0]!r}"
        )


def _string(value: object, path: str) -> str:
    if type(value) is not str:
        raise MapperResponseValidationError(f"mapper response {path} must be a string")
    result = value
    if not result or result != result.strip():
        raise MapperResponseValidationError(
            f"mapper response {path} must be a non-empty trimmed string"
        )
    return result


def _optional_string(value: object, path: str) -> str | None:
    if value is None:
        return None
    return _string(value, path)


def _positive_integer(value: object, path: str) -> int:
    if type(value) is not int:
        raise MapperResponseValidationError(f"mapper response {path} must be an integer")
    result = value
    if result < 1:
        raise MapperResponseValidationError(f"mapper response {path} must be at least 1")
    return result


def validate_mapper_response(response: MapperResponse) -> None:
    """Apply response-schema checks to an already constructed mapper result."""

    if type(response) is not MapperResponse:
        raise MapperResponseValidationError("mapper response must use the frozen MapperResponse")
    _optional_string(response.scope_title, "scope_title")
    _optional_string(response.scope_overview, "scope_overview")
    if type(response.events) is not tuple:
        raise MapperResponseValidationError("mapper response events must be an array")
    for index, event in enumerate(response.events):
        path = f"events[{index}]"
        if type(event) is not MapperEvent:
            raise MapperResponseValidationError(f"mapper response {path} has an invalid item")
        _string(event.title, f"{path}.title")
        _string(event.summary, f"{path}.summary")
        _string(event.relative_path, f"{path}.relative_path")
        start_line = _positive_integer(event.start_line, f"{path}.start_line")
        end_line = _positive_integer(event.end_line, f"{path}.end_line")
        if end_line < start_line:
            raise MapperResponseValidationError(
                f"mapper response {path} has an inverted source range"
            )
        if type(event.characters) is not tuple:
            raise MapperResponseValidationError(
                f"mapper response {path}.characters must be an array"
            )
        characters = tuple(
            _string(item, f"{path}.characters[{character_index}]")
            for character_index, item in enumerate(event.characters)
        )
        if len(characters) != len(set(characters)):
            raise MapperResponseValidationError(
                f"mapper response {path}.characters must not contain duplicates"
            )
        _optional_string(event.warning, f"{path}.warning")

    if type(response.branch_summaries) is not tuple:
        raise MapperResponseValidationError("mapper response branch_summaries must be an array")
    seen_branches: set[tuple[str, int]] = set()
    for index, summary in enumerate(response.branch_summaries):
        path = f"branch_summaries[{index}]"
        if type(summary) is not BranchSummary:
            raise MapperResponseValidationError(f"mapper response {path} has an invalid item")
        choice_key = _string(summary.choice_key, f"{path}.choice_key")
        arm_order = _positive_integer(summary.arm_order, f"{path}.arm_order")
        _string(summary.outcome_summary, f"{path}.outcome_summary")
        key = (choice_key, arm_order)
        if key in seen_branches:
            raise MapperResponseValidationError(
                f"mapper response {path} duplicates choice arm {key!r}"
            )
        seen_branches.add(key)


def deserialize_mapper_response(payload: bytes | str) -> MapperResponse:
    """Decode and strictly validate JSON against the frozen mapper response schema."""

    if isinstance(payload, bytes):
        try:
            serialized = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MapperResponseValidationError("mapper response is not valid UTF-8") from exc
    elif isinstance(payload, str):
        serialized = payload
    else:
        raise MapperResponseValidationError("mapper response must be UTF-8 bytes or text")
    try:
        decoded = json.loads(serialized, object_pairs_hook=_object_without_duplicates)
    except MapperResponseValidationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise MapperResponseValidationError("mapper response is not valid JSON") from exc

    root = _object(decoded, "root")
    _exact_keys(
        root,
        "root",
        required=frozenset({"events", "branch_summaries"}),
        optional=frozenset({"scope_title", "scope_overview"}),
    )
    event_keys = frozenset(
        {
            "title",
            "summary",
            "relative_path",
            "start_line",
            "end_line",
            "characters",
            "warning",
        }
    )
    events: list[MapperEvent] = []
    for index, value in enumerate(_array(root["events"], "events")):
        path = f"events[{index}]"
        event = _object(value, path)
        _exact_keys(event, path, required=event_keys)
        characters = tuple(
            _string(item, f"{path}.characters[{character_index}]")
            for character_index, item in enumerate(
                _array(event["characters"], f"{path}.characters")
            )
        )
        events.append(
            MapperEvent(
                title=_string(event["title"], f"{path}.title"),
                summary=_string(event["summary"], f"{path}.summary"),
                relative_path=_string(event["relative_path"], f"{path}.relative_path"),
                start_line=_positive_integer(event["start_line"], f"{path}.start_line"),
                end_line=_positive_integer(event["end_line"], f"{path}.end_line"),
                characters=characters,
                warning=_optional_string(event["warning"], f"{path}.warning"),
            )
        )

    branch_keys = frozenset({"choice_key", "arm_order", "outcome_summary"})
    summaries: list[BranchSummary] = []
    for index, value in enumerate(_array(root["branch_summaries"], "branch_summaries")):
        path = f"branch_summaries[{index}]"
        summary = _object(value, path)
        _exact_keys(summary, path, required=branch_keys)
        summaries.append(
            BranchSummary(
                choice_key=_string(summary["choice_key"], f"{path}.choice_key"),
                arm_order=_positive_integer(summary["arm_order"], f"{path}.arm_order"),
                outcome_summary=_string(
                    summary["outcome_summary"], f"{path}.outcome_summary"
                ),
            )
        )

    response = MapperResponse(
        scope_title=_optional_string(root.get("scope_title"), "scope_title"),
        scope_overview=_optional_string(root.get("scope_overview"), "scope_overview"),
        events=tuple(events),
        branch_summaries=tuple(summaries),
    )
    validate_mapper_response(response)
    return response
