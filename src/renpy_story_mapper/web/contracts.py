"""Typed transport contracts for the local browser API."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import TypeGuard

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True)
class ApiErrorBody:
    code: str
    message: str


@dataclass(frozen=True)
class TaskStatus:
    id: str
    kind: str
    state: str
    stage: str
    percent: int
    cancellable: bool
    error: ApiErrorBody | None = None


@dataclass(frozen=True)
class SelectionResult:
    id: str
    kind: str
    name: str


def json_value(value: object) -> JsonValue:
    """Convert known immutable domain records to JSON without path-specific magic."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return json_value(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    raise TypeError(f"unsupported API result type: {type(value).__name__}")


def is_json_object(value: JsonValue) -> TypeGuard[dict[str, JsonValue]]:
    return isinstance(value, dict)


def require_string(body: dict[str, JsonValue], name: str, *, maximum: int = 512) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def optional_string(body: dict[str, JsonValue], name: str, *, maximum: int = 512) -> str | None:
    value = body.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"{name} must be a string")
    return value


def string_tuple(
    body: dict[str, JsonValue], name: str, *, maximum_items: int = 250
) -> tuple[str, ...]:
    value = body.get(name, [])
    if not isinstance(value, list) or len(value) > maximum_items:
        raise ValueError(f"{name} must be a bounded string array")
    if any(not isinstance(item, str) or not item or len(item) > 512 for item in value):
        raise ValueError(f"{name} must contain non-empty strings")
    return tuple(value)  # type: ignore[arg-type]


def bounded_int(
    body: dict[str, JsonValue], name: str, *, default: int, minimum: int, maximum: int
) -> int:
    value = body.get(name, default)
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ValueError(f"{name} is outside the allowed range")
    return value


def boolean(body: dict[str, JsonValue], name: str, *, default: bool = False) -> bool:
    value = body.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value
