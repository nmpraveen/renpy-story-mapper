"""Bounded, non-executing extraction of narrow Ren'Py metadata literals."""

from __future__ import annotations

import ast
import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass

from renpy_story_mapper.ingestion.contracts import CancelCheck, IngestionSource

STORY_METADATA_SCHEMA_VERSION = 1

_DEFINE = re.compile(r"^(\s*)define\s+([A-Za-z_]\w*)\s*=\s*(.+)$")
_DEFAULT = re.compile(r"^(\s*)default\s+([A-Za-z_]\w*)\s*=\s*(.+)$")
_TEXT = re.compile(r"^(\s*)text\s+(.+?)\s*$")
_DISPLAY_VARIABLE = re.compile(r"^\[([A-Za-z_]\w*)\]$")
_MEMORY_CONSTRUCTORS = {
    "memory",
    "memory_entry",
    "memory_item",
    "memoryentry",
    "memoryitem",
}
_NOT_LITERAL = object()


class StoryMetadataLimitError(ValueError):
    """A configured extraction resource bound was exceeded."""


@dataclass(frozen=True)
class StoryMetadataLimits:
    max_source_bytes: int = 16 * 1024 * 1024
    max_total_bytes: int = 64 * 1024 * 1024
    max_records: int = 25_000
    max_diagnostics: int = 256

    def validate(self) -> None:
        if (
            min(self.max_source_bytes, self.max_total_bytes, self.max_records) <= 0
            or self.max_diagnostics < 0
        ):
            raise ValueError("story metadata limits must be positive")


@dataclass(frozen=True)
class _Input:
    source: IngestionSource
    role: str


@dataclass(frozen=True)
class _ScreenText:
    value: str
    line: int
    source: dict[str, object]


class _Diagnostics:
    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        self.items: list[dict[str, object]] = []
        self.dropped = 0

    def add(self, code: str, message: str, source: dict[str, object]) -> None:
        if len(self.items) < self.maximum:
            self.items.append({"code": code, "message": message, "source": source})
        else:
            self.dropped += 1

    def result(self) -> list[dict[str, object]]:
        if self.dropped and self.maximum:
            truncated: dict[str, object] = {
                "code": "diagnostics_truncated",
                "message": f"{self.dropped} additional diagnostics were omitted",
            }
            if len(self.items) == self.maximum:
                self.items[-1] = truncated
            else:
                self.items.append(truncated)
        return self.items


def extract_story_metadata(
    canonical_sources: Iterable[IngestionSource],
    secondary_sources: Iterable[IngestionSource] = (),
    *,
    limits: StoryMetadataLimits | None = None,
    cancel_check: CancelCheck = None,
) -> dict[str, object]:
    """Extract only locked literal patterns; source code is parsed as data and never run."""

    configured = limits or StoryMetadataLimits()
    configured.validate()
    inputs = _inputs(canonical_sources, secondary_sources)
    diagnostics = _Diagnostics(configured.max_diagnostics)
    characters: list[dict[str, object]] = []
    state_hints: list[dict[str, object]] = []
    scene_titles: list[dict[str, object]] = []
    source_records: list[dict[str, object]] = []
    total_bytes = 0
    record_count = 0

    for item in inputs:
        _check_cancelled(cancel_check)
        source = item.source
        size = len(source.content)
        if size > configured.max_source_bytes:
            raise StoryMetadataLimitError(
                f"metadata source exceeds configured byte limit: {source.path}"
            )
        total_bytes += size
        if total_bytes > configured.max_total_bytes:
            raise StoryMetadataLimitError("metadata sources exceed aggregate byte limit")
        source_records.append(_source(item))
        try:
            lines = source.content.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            diagnostics.add(
                "invalid_utf8",
                "source is not valid UTF-8 and was skipped",
                _evidence(item, 1, 1, 1, 1),
            )
            continue

        screen_texts: list[_ScreenText] = []
        for line_number, line in enumerate(lines, 1):
            _check_cancelled(cancel_check)
            start_column = len(line) - len(line.lstrip()) + 1
            evidence = _evidence(
                item, line_number, start_column, line_number, len(line) + 1
            )

            define = _DEFINE.match(line)
            if define is not None:
                expression = _expression(define.group(3))
                if _character_call(expression):
                    display_name = _character_name(expression)
                    if display_name is None:
                        diagnostics.add(
                            "dynamic_character_name",
                            "Character name is not one unambiguous literal string",
                            evidence,
                        )
                    else:
                        characters.append(
                            {
                                "alias": define.group(2),
                                "display_name": display_name,
                                "source": evidence,
                            }
                        )
                        record_count = _count(record_count, configured)
                elif "Character" in define.group(3):
                    diagnostics.add(
                        "unsupported_character_definition",
                        "Character definition is malformed or unsupported",
                        evidence,
                    )
                continue

            default = _DEFAULT.match(line)
            if default is not None:
                expression = _expression(default.group(3))
                value = _scalar(expression)
                if expression is None or value is _NOT_LITERAL:
                    diagnostics.add(
                        "dynamic_default",
                        "default value is not a supported literal scalar",
                        evidence,
                    )
                else:
                    state_hints.append(
                        {
                            "name": default.group(2),
                            "kind": "default",
                            "default": value,
                            "source": evidence,
                        }
                    )
                    record_count = _count(record_count, configured)
                continue

            text = _TEXT.match(line)
            if text is not None:
                expression = _expression(text.group(2))
                if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
                    screen_texts.append(_ScreenText(expression.value, line_number, evidence))
                else:
                    diagnostics.add(
                        "dynamic_screen_text",
                        "screen text is not a literal string",
                        evidence,
                    )

            memory = _memory_statement(line)
            if memory is not None:
                title, thumbnail, collection = memory
                if title is None:
                    diagnostics.add(
                        "dynamic_scene_title",
                        "memory title is not one unambiguous literal string",
                        evidence,
                    )
                else:
                    record: dict[str, object] = {
                        "title": title,
                        "collection": collection,
                        "source": evidence,
                    }
                    if thumbnail is not None:
                        record["thumbnail"] = thumbnail
                    scene_titles.append(record)
                    record_count = _count(record_count, configured)

        position = 0
        while position + 1 < len(screen_texts):
            _check_cancelled(cancel_check)
            left, right = screen_texts[position : position + 2]
            if any(
                value.strip() and not value.lstrip().startswith("#")
                for value in lines[left.line : right.line - 1]
            ):
                position += 1
                continue
            pair = _screen_pair(left, right)
            if pair is None:
                position += 1
                continue
            variable, display_name, pair_source = pair
            state_hints.append(
                {
                    "name": variable,
                    "kind": "display_label",
                    "display_name": display_name,
                    "source": pair_source,
                }
            )
            record_count = _count(record_count, configured)
            position += 2

    payload: dict[str, object] = {
        "schema_version": STORY_METADATA_SCHEMA_VERSION,
        "characters": sorted(characters, key=_sort_key),
        "state_hints": sorted(state_hints, key=_sort_key),
        "sources": source_records,
        "diagnostics": sorted(diagnostics.result(), key=_sort_key),
    }
    if scene_titles:
        payload["scene_titles"] = sorted(scene_titles, key=_sort_key)
    return payload


def _inputs(
    canonical: Iterable[IngestionSource], secondary: Iterable[IngestionSource]
) -> tuple[_Input, ...]:
    values = [
        *(_Input(source, "canonical") for source in canonical),
        *(_Input(source, "secondary_metadata") for source in secondary),
    ]
    values.sort(
        key=lambda item: (
            item.role,
            item.source.path.casefold(),
            item.source.provenance.locator.casefold(),
            item.source.provenance.output_sha256,
        )
    )
    result: list[_Input] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in values:
        key = (
            item.role,
            item.source.path,
            item.source.provenance.locator,
            item.source.provenance.output_sha256,
        )
        if key not in seen:
            seen.add(key)
            result.append(item)
    return tuple(result)


def _source(item: _Input) -> dict[str, object]:
    provenance = item.source.provenance
    return {
        "path": item.source.path,
        "role": item.role,
        "locator": provenance.locator,
        "fingerprint": provenance.output_sha256,
        "line_basis": provenance.line_basis,
    }


def _evidence(
    item: _Input, start_line: int, start_column: int, end_line: int, end_column: int
) -> dict[str, object]:
    return {
        **_source(item),
        "span": {
            "start": {"line": start_line, "column": start_column},
            "end": {"line": end_line, "column": end_column},
        },
    }


def _expression(value: str) -> ast.expr | None:
    try:
        return ast.parse(value.strip(), mode="eval").body
    except (SyntaxError, ValueError, MemoryError):
        return None


def _character_call(value: ast.expr | None) -> bool:
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "Character"
    )


def _character_name(value: ast.expr | None) -> str | None:
    if not isinstance(value, ast.Call):
        return None
    candidates = list(value.args[:1])
    candidates.extend(keyword.value for keyword in value.keywords if keyword.arg == "name")
    return _literal_string(candidates[0]) if len(candidates) == 1 else None


def _literal_string(value: ast.expr) -> str | None:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id in {"_", "__"}
        and len(value.args) == 1
        and not value.keywords
        and isinstance(value.args[0], ast.Constant)
        and isinstance(value.args[0].value, str)
    ):
        return value.args[0].value
    return None


def _scalar(value: ast.expr | None) -> str | int | float | bool | None | object:
    if isinstance(value, ast.Constant) and type(value.value) in {str, int, float, bool, type(None)}:
        if isinstance(value.value, float) and not math.isfinite(value.value):
            return _NOT_LITERAL
        return value.value
    if (
        isinstance(value, ast.UnaryOp)
        and isinstance(value.op, (ast.UAdd, ast.USub))
        and isinstance(value.operand, ast.Constant)
        and type(value.operand.value) in {int, float}
    ):
        number = value.operand.value
        assert isinstance(number, (int, float)) and not isinstance(number, bool)
        result = number if isinstance(value.op, ast.UAdd) else -number
        return result if not isinstance(result, float) or math.isfinite(result) else _NOT_LITERAL
    return _NOT_LITERAL


def _memory_statement(line: str) -> tuple[str | None, str | None, str] | None:
    stripped = line.strip()
    if "memory" not in stripped.casefold() and ".append(" not in stripped:
        return None
    try:
        module = ast.parse(stripped, mode="exec")
    except (SyntaxError, ValueError, MemoryError):
        return None
    if len(module.body) != 1:
        return None
    statement = module.body[0]
    if isinstance(statement, (ast.Assign, ast.AnnAssign)):
        value = statement.value
        if value is None or not isinstance(value, ast.Call) or not _memory_call(value):
            return None
        target = statement.targets[0] if isinstance(statement, ast.Assign) else statement.target
        title, thumbnail = _memory_value(value)
        return title, thumbnail, _name(target) or "memory"
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
        return None
    call = statement.value
    if (
        not isinstance(call.func, ast.Attribute)
        or call.func.attr != "append"
        or len(call.args) != 1
    ):
        return None
    collection = _name(call.func.value)
    if collection is None or "mem" not in collection.casefold():
        return None
    title, thumbnail = _memory_value(call.args[0])
    return title, thumbnail, collection


def _memory_call(value: ast.Call) -> bool:
    name = _name(value.func)
    return name is not None and name.rsplit(".", 1)[-1].casefold() in _MEMORY_CONSTRUCTORS


def _memory_value(value: ast.expr) -> tuple[str | None, str | None]:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value, None
    if isinstance(value, (ast.List, ast.Tuple)):
        title = _literal_string(value.elts[0]) if value.elts else None
        thumbnail = _literal_string(value.elts[1]) if len(value.elts) > 1 else None
        return title, thumbnail
    if not isinstance(value, ast.Call) or not _memory_call(value):
        return None, None
    title_nodes = list(value.args[:1])
    title_nodes.extend(
        keyword.value for keyword in value.keywords if keyword.arg in {"name", "title"}
    )
    thumbnail_nodes = list(value.args[1:2])
    thumbnail_nodes.extend(
        keyword.value
        for keyword in value.keywords
        if keyword.arg in {"image", "thumb", "thumbnail"}
    )
    if len(title_nodes) != 1 or len(thumbnail_nodes) > 1:
        return None, None
    title = _literal_string(title_nodes[0])
    thumbnail = _literal_string(thumbnail_nodes[0]) if thumbnail_nodes else None
    if thumbnail_nodes and thumbnail is None:
        return None, None
    return title, thumbnail


def _name(value: ast.expr) -> str | None:
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        parent = _name(value.value)
        return f"{parent}.{value.attr}" if parent else None
    return None


def _screen_pair(
    left: _ScreenText, right: _ScreenText
) -> tuple[str, str, dict[str, object]] | None:
    left_variable = _DISPLAY_VARIABLE.fullmatch(left.value)
    right_variable = _DISPLAY_VARIABLE.fullmatch(right.value)
    if right_variable is not None and left_variable is None and "[" not in left.value:
        variable, display_name = right_variable.group(1), left.value
    elif left_variable is not None and right_variable is None and "[" not in right.value:
        variable, display_name = left_variable.group(1), right.value
    else:
        return None
    source = dict(left.source)
    left_span, right_span = left.source["span"], right.source["span"]
    assert isinstance(left_span, dict) and isinstance(right_span, dict)
    source["span"] = {"start": left_span["start"], "end": right_span["end"]}
    return variable, display_name, source


def _count(current: int, limits: StoryMetadataLimits) -> int:
    current += 1
    if current > limits.max_records:
        raise StoryMetadataLimitError("metadata record count exceeds configured limit")
    return current


def _sort_key(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _check_cancelled(cancel_check: CancelCheck) -> None:
    if cancel_check is not None and cancel_check():
        from renpy_story_mapper.storage import ProjectOperationCancelled

        raise ProjectOperationCancelled("story metadata extraction was cancelled")
