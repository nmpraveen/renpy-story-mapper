"""Typed transport contracts for the local browser API."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Final, TypeGuard, cast

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

# M07 browser-worker integration contract.  These paths and payload field names are
# deliberately centralized here so the static UI can integrate without duplicating
# backend routing knowledge.
M07_API_ROUTES: Final[dict[str, str]] = {
    "route_map": "/api/v1/m07/route-map",
    "route_search": "/api/v1/m07/route-search",
    "detail": "/api/v1/m07/detail",
    "window_resolve": "/api/v1/m07/bounded-window/resolve",
    "organization": "/api/v1/m07/organization",
    "prepare": "/api/v1/m07/organization/prepare",
    "start": "/api/v1/m07/organization/start",
    "cancel": "/api/v1/m07/organization/cancel",
    "source_acknowledge": "/api/v1/m07/source-coverage/acknowledge",
    "scope_override": "/api/v1/m07/scope/override",
    "assembly_apply": "/api/v1/m07/assembly/apply",
    "assembly_discard": "/api/v1/m07/assembly/discard",
}
M07_ROUTE_MAP_REQUEST_FIELDS: Final = ("offset", "limit", "edge_offset", "edge_limit")
M07_DETAIL_REQUEST_FIELDS: Final = ("element_id",)
M07_WINDOW_RESOLVE_REQUEST_FIELDS: Final = (
    "node_ids",
    "entry_node_id",
    "exit_node_id",
)
M07_PREPARE_REQUEST_FIELDS: Final = (
    "scope_ids",
    "window_requests",
    "soft_seconds",
    "hard_seconds",
    "soft_tokens",
    "hard_tokens",
    "hard_calls",
)
M07_START_REQUEST_FIELDS: Final = (
    "run_id",
    "confirm_cloud",
    "scope_ids",
    "window_ids",
    "selection_hash",
    "authority_hash",
    "recovered_source_acknowledgement",
    "model",
    "budgets",
)
M07_ROUTE_SEARCH_REQUEST_FIELDS: Final = ("query", "after", "limit")
M07_SOURCE_ACKNOWLEDGE_REQUEST_FIELDS: Final = ("coverage_token", "acknowledge")
M07_SCOPE_OVERRIDE_REQUEST_FIELDS: Final = (
    "scope_id",
    "authority_hash",
    "correction",
    "pinned",
)
M07_ASSEMBLY_APPLY_REQUEST_FIELDS: Final = ("assembly_id",)
M07_ASSEMBLY_DISCARD_REQUEST_FIELDS: Final = ("assembly_id",)

M08_API_ROUTES: Final[dict[str, str]] = {
    "ai_story_map": "/api/v1/m08/ai-story-map",
    "ai_story_detail": "/api/v1/m08/ai-story-detail",
    "comparison": "/api/v1/m08/comparison",
}
M08_AI_STORY_MAP_REQUEST_FIELDS: Final = (
    "node_offset",
    "node_limit",
    "edge_offset",
    "edge_limit",
    "edge_cursor",
)
M08_COMPARISON_REQUEST_FIELDS: Final = (
    "node_offset",
    "node_limit",
    "edge_offset",
    "edge_limit",
)
M08_AI_STORY_DETAIL_REQUEST_FIELDS: Final = (
    "element_id",
    "route_node_offset",
    "route_node_limit",
    "route_edge_offset",
    "route_edge_limit",
    "evidence_offset",
    "evidence_limit",
)


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


def required_string_tuple(
    body: dict[str, JsonValue], name: str, *, maximum_items: int = 250
) -> tuple[str, ...]:
    if name not in body:
        raise ValueError(f"{name} is required")
    return string_tuple(body, name, maximum_items=maximum_items)


def bounded_int(
    body: dict[str, JsonValue], name: str, *, default: int, minimum: int, maximum: int
) -> int:
    value = body.get(name, default)
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ValueError(f"{name} is outside the allowed range")
    return value


def optional_bounded_int(
    body: dict[str, JsonValue], name: str, *, minimum: int, maximum: int
) -> int | None:
    value = body.get(name)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ValueError(f"{name} is outside the allowed range")
    return value


def boolean(body: dict[str, JsonValue], name: str, *, default: bool = False) -> bool:
    value = body.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def object_value(body: dict[str, JsonValue], name: str) -> dict[str, JsonValue]:
    value = body.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def exact_fields(
    body: dict[str, JsonValue],
    *,
    allowed: Collection[str],
    required: Collection[str] = (),
    name: str = "request",
) -> None:
    """Reject transport objects that contain unknown fields or omit required ones."""

    unknown = set(body) - set(allowed)
    missing = set(required) - set(body)
    if unknown:
        raise ValueError(f"{name} contains unsupported fields")
    if missing:
        raise ValueError(f"{name} is missing required fields")


def object_tuple(
    body: dict[str, JsonValue], name: str, *, maximum_items: int
) -> tuple[dict[str, JsonValue], ...]:
    value = body.get(name, [])
    if not isinstance(value, list) or len(value) > maximum_items:
        raise ValueError(f"{name} must be a bounded object array")
    if any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{name} must contain objects")
    return tuple(cast(dict[str, JsonValue], item) for item in value)
