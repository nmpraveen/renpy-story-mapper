"""Provider-free bounded Story Map V2 Phase 04 reader contracts.

The reader owns transport paging, revision checks, opaque cursor validation, and
presentation-only view state.  Its source supplies already-authoritative Python
membership and topology; this module never derives story mechanics.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

READER_SCHEMA: Final = "story-map-v2-reader-contract-v2"
READER_STORAGE_PAGE_SCHEMA: Final = "story-map-v2-reader-page-v1"
SECTION_PAGE_ENDPOINT: Final = "section-page"
BRANCH_PAGE_ENDPOINT: Final = "branch-page"
PATH_PAGE_ENDPOINT: Final = "path-page"
DETAIL_PAGE_ENDPOINT: Final = "detail-page"
SEARCH_ENDPOINT: Final = "search"

MAX_SECTION_EVENTS: Final = 30
MAX_RENDERED_ITEMS: Final = 240
MAX_SERIALIZED_BYTES: Final = 1_048_576
MAX_SEARCH_RESULTS: Final = 100
DEFAULT_SEARCH_RESULTS: Final = 50
MAX_CURSOR_CHARS: Final = 4_096
MAX_VIEW_STATE_BYTES: Final = 65_536

type JsonObject = dict[str, object]


class StoryMapReaderError(ValueError):
    """Base error for a fail-closed reader request or stored record."""


class StoryMapReaderUnavailableError(StoryMapReaderError):
    """No current complete or active-build generation is readable."""


class StoryMapReaderNotFoundError(StoryMapReaderError):
    """A requested reader resource or selection is absent."""


class StoryMapReaderDataError(StoryMapReaderError):
    """Persisted reader material violates the frozen reader contract."""


class InvalidStoryMapCursorError(StoryMapReaderError):
    """An opaque cursor is malformed, tampered, foreign, or mismatched."""


class StaleMapRevisionError(StoryMapReaderError):
    """The request names a map revision other than the readable revision."""

    def __init__(self, current_revision: int) -> None:
        super().__init__("The requested map revision is stale.")
        self.current_revision = current_revision


@dataclass(frozen=True)
class ReaderSnapshot:
    """One current readable generation and its small transport summaries."""

    map_revision: int
    generation_id: str
    freshness: str
    manifest: Mapping[str, object]
    status: Mapping[str, object]
    cursor_authority: str

    def __post_init__(self) -> None:
        if type(self.map_revision) is not int or self.map_revision < 0:
            raise StoryMapReaderDataError("map revision must be a non-negative integer")
        _nonempty(self.generation_id, "generation_id")
        if self.freshness not in {"current", "building", "stale", "phase03_compatible"}:
            raise StoryMapReaderDataError("reader freshness is unsupported")
        _nonempty(self.cursor_authority, "cursor_authority", maximum=2_048)


@dataclass(frozen=True)
class ReaderSlice:
    """A stable ordered bounded slice supplied without hydrating a full map."""

    items: tuple[Mapping[str, object], ...]
    shells: tuple[Mapping[str, object], ...]
    next_offset: int | None

    def __post_init__(self) -> None:
        if self.next_offset is not None and (
            type(self.next_offset) is not int or self.next_offset < 1
        ):
            raise StoryMapReaderDataError("next page offset must be a positive integer")


@dataclass(frozen=True)
class ReaderLocation:
    """Python-supplied selection location, including the v2 branch resource."""

    section_id: str
    branch_id: str | None
    page_offset: int
    shell_id: str
    item_id: str

    def __post_init__(self) -> None:
        _nonempty(self.section_id, "section_id")
        if self.branch_id is not None:
            _nonempty(self.branch_id, "branch_id")
        if type(self.page_offset) is not int or self.page_offset < 0:
            raise StoryMapReaderDataError("location page offset cannot be negative")
        _nonempty(self.shell_id, "shell_id")
        _nonempty(self.item_id, "item_id")


@dataclass(frozen=True)
class ReaderSearchSlice:
    results: tuple[Mapping[str, object], ...]
    next_offset: int | None


class StoryMapReaderSource(Protocol):
    """Indexed source of immutable reader records and semantic view state."""

    def snapshot(self) -> ReaderSnapshot | None: ...

    def resource_slice(
        self,
        snapshot: ReaderSnapshot,
        endpoint: str,
        resource_id: str,
        offset: int,
        limit: int,
    ) -> ReaderSlice | None: ...

    def locate(
        self, snapshot: ReaderSnapshot, selection_id: str
    ) -> ReaderLocation | None: ...

    def search(
        self,
        snapshot: ReaderSnapshot,
        query: str,
        offset: int,
        limit: int,
    ) -> ReaderSearchSlice: ...

    def load_view_state(self, snapshot: ReaderSnapshot, view_key: str) -> Mapping[str, object]: ...

    def save_view_state(
        self,
        snapshot: ReaderSnapshot,
        view_key: str,
        state: Mapping[str, object],
    ) -> Mapping[str, object]: ...


class MemoryStoryMapReaderSource:
    """Deterministic provider-free source for compatibility and scale fixtures."""

    def __init__(
        self,
        snapshot: ReaderSnapshot,
        *,
        resources: Mapping[
            tuple[str, str],
            tuple[Sequence[Mapping[str, object]], Sequence[Mapping[str, object]]],
        ],
        locations: Mapping[str, ReaderLocation],
        search_results: Sequence[Mapping[str, object]],
    ) -> None:
        self._snapshot_value = snapshot
        self._resources = {
            key: (tuple(items), tuple(shells))
            for key, (items, shells) in resources.items()
        }
        self._locations = dict(locations)
        self._search_results = tuple(search_results)
        self._view_states: dict[str, JsonObject] = {}

    def snapshot(self) -> ReaderSnapshot:
        return self._snapshot_value

    def resource_slice(
        self,
        snapshot: ReaderSnapshot,
        endpoint: str,
        resource_id: str,
        offset: int,
        limit: int,
    ) -> ReaderSlice | None:
        del snapshot
        resource = self._resources.get((endpoint, resource_id))
        if resource is None:
            return None
        items, shells = resource
        selected = items[offset : offset + limit]
        next_offset = offset + len(selected) if offset + len(selected) < len(items) else None
        return ReaderSlice(tuple(selected), tuple(shells), next_offset)

    def locate(
        self, snapshot: ReaderSnapshot, selection_id: str
    ) -> ReaderLocation | None:
        del snapshot
        return self._locations.get(selection_id)

    def search(
        self,
        snapshot: ReaderSnapshot,
        query: str,
        offset: int,
        limit: int,
    ) -> ReaderSearchSlice:
        del snapshot
        folded = query.casefold()
        matching = tuple(
            result
            for result in self._search_results
            if folded
            in "\n".join(
                str(result.get(field, ""))
                for field in ("selection_id", "title", "snippet")
            ).casefold()
        )
        selected = matching[offset : offset + limit]
        next_offset = offset + len(selected) if offset + len(selected) < len(matching) else None
        return ReaderSearchSlice(tuple(selected), next_offset)

    def load_view_state(
        self, snapshot: ReaderSnapshot, view_key: str
    ) -> Mapping[str, object]:
        del snapshot
        return dict(self._view_states.get(view_key, {"hide_new": False}))

    def save_view_state(
        self,
        snapshot: ReaderSnapshot,
        view_key: str,
        state: Mapping[str, object],
    ) -> Mapping[str, object]:
        del snapshot
        self._view_states[view_key] = dict(state)
        return dict(state)


@dataclass(frozen=True)
class _CursorExpectation:
    snapshot: ReaderSnapshot
    endpoint: str
    resource_id: str
    order: str
    limit: int
    binding: str


def _nonempty(value: object, label: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum:
        raise StoryMapReaderDataError(f"{label} must be a non-empty bounded string")
    return value


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise StoryMapReaderDataError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, (tuple, list)):
        raise StoryMapReaderDataError(f"{label} must be an array")
    return value


def _json_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise StoryMapReaderDataError("reader payload is not JSON-safe") from exc


def _cursor_secret(snapshot: ReaderSnapshot) -> bytes:
    return hashlib.sha256(
        b"story-map-v2-reader-cursor-v2\x00" + snapshot.cursor_authority.encode("utf-8")
    ).digest()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise InvalidStoryMapCursorError("The page cursor is invalid.") from exc


def _encode_cursor(expectation: _CursorExpectation, offset: int) -> str:
    payload = {
        "binding": expectation.binding,
        "endpoint": expectation.endpoint,
        "generation": expectation.snapshot.generation_id,
        "limit": expectation.limit,
        "offset": offset,
        "order": expectation.order,
        "resource": expectation.resource_id,
        "revision": expectation.snapshot.map_revision,
        "schema": READER_SCHEMA,
    }
    raw = _json_bytes(payload)
    signature = hmac.new(_cursor_secret(expectation.snapshot), raw, hashlib.sha256).digest()
    token = f"{_b64encode(raw)}.{_b64encode(signature)}"
    if len(token) > MAX_CURSOR_CHARS:
        raise StoryMapReaderDataError("minted page cursor exceeds the contract bound")
    return token


def _decode_cursor(token: str, expectation: _CursorExpectation) -> int:
    if not token or len(token) > MAX_CURSOR_CHARS or token.count(".") != 1:
        raise InvalidStoryMapCursorError("The page cursor is invalid.")
    payload_part, signature_part = token.split(".", 1)
    raw = _b64decode(payload_part)
    signature = _b64decode(signature_part)
    expected_signature = hmac.new(
        _cursor_secret(expectation.snapshot), raw, hashlib.sha256
    ).digest()
    if not hmac.compare_digest(signature, expected_signature):
        raise InvalidStoryMapCursorError("The page cursor is invalid.")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidStoryMapCursorError("The page cursor is invalid.") from exc
    if not isinstance(decoded, dict) or set(decoded) != {
        "binding",
        "endpoint",
        "generation",
        "limit",
        "offset",
        "order",
        "resource",
        "revision",
        "schema",
    }:
        raise InvalidStoryMapCursorError("The page cursor is invalid.")
    revision = decoded.get("revision")
    if type(revision) is not int:
        raise InvalidStoryMapCursorError("The page cursor is invalid.")
    if revision != expectation.snapshot.map_revision:
        if revision < expectation.snapshot.map_revision:
            raise StaleMapRevisionError(expectation.snapshot.map_revision)
        raise InvalidStoryMapCursorError("The page cursor is invalid.")
    expected = {
        "binding": expectation.binding,
        "endpoint": expectation.endpoint,
        "generation": expectation.snapshot.generation_id,
        "limit": expectation.limit,
        "order": expectation.order,
        "resource": expectation.resource_id,
        "schema": READER_SCHEMA,
    }
    if any(decoded.get(key) != value for key, value in expected.items()):
        raise InvalidStoryMapCursorError("The page cursor is invalid.")
    offset = decoded.get("offset")
    if type(offset) is not int or offset < 1:
        raise InvalidStoryMapCursorError("The page cursor is invalid.")
    return offset


def _shells_for_items(
    shells: Sequence[Mapping[str, object]], item_ids: Sequence[str]
) -> tuple[JsonObject, ...]:
    allowed = frozenset(item_ids)
    result: list[JsonObject] = []
    for index, source in enumerate(shells):
        shell = dict(source)
        shell_id = _nonempty(shell.get("id"), f"shells[{index}].id")
        members = _array(shell.get("item_ids"), f"shells[{index}].item_ids")
        kept: list[str] = []
        for member in members:
            member_id = _nonempty(member, f"shells[{index}].item_ids[]")
            if member_id in allowed:
                kept.append(member_id)
        if not kept:
            continue
        shell["id"] = shell_id
        shell["item_ids"] = kept
        result.append(shell)
    return tuple(result)


class StoryMapReader:
    """Build contract-v2 responses over one provider-free indexed source."""

    def __init__(self, source: StoryMapReaderSource) -> None:
        self._source = source

    def _snapshot(self) -> ReaderSnapshot:
        snapshot = self._source.snapshot()
        if snapshot is None:
            raise StoryMapReaderUnavailableError("No Story Map V2 generation is readable.")
        return snapshot

    @staticmethod
    def _require_revision(snapshot: ReaderSnapshot, requested: int) -> None:
        if type(requested) is not int or requested < 0:
            raise StoryMapReaderError("map_revision must be a non-negative integer")
        if requested != snapshot.map_revision:
            raise StaleMapRevisionError(snapshot.map_revision)

    def manifest(self) -> JsonObject:
        snapshot = self._snapshot()
        source = snapshot.manifest
        response: JsonObject = {
            "schema": READER_SCHEMA,
            "map_revision": snapshot.map_revision,
            "generation_id": snapshot.generation_id,
            "freshness": snapshot.freshness,
            "status": _nonempty(source.get("status"), "manifest.status"),
            "overview": dict(_object(source.get("overview"), "manifest.overview")),
            "counts": dict(_object(source.get("counts"), "manifest.counts")),
            "sections": [
                dict(_object(item, "manifest.sections[]"))
                for item in _array(source.get("sections"), "manifest.sections")
            ],
            "landmarks": [
                dict(_object(item, "manifest.landmarks[]"))
                for item in _array(source.get("landmarks"), "manifest.landmarks")
            ],
            "new_facts": dict(_object(source.get("new_facts"), "manifest.new_facts")),
        }
        return response

    def status(self) -> JsonObject:
        snapshot = self._snapshot()
        source = snapshot.status
        return {
            "schema": READER_SCHEMA,
            "map_revision": snapshot.map_revision,
            "generation_id": snapshot.generation_id,
            "run_id": _nonempty(source.get("run_id"), "status.run_id"),
            "freshness": snapshot.freshness,
            "state": _nonempty(source.get("state"), "status.state"),
            "coverage": dict(_object(source.get("coverage"), "status.coverage")),
            "progress": dict(_object(source.get("progress"), "status.progress")),
            "actions": dict(_object(source.get("actions"), "status.actions")),
            "current_complete_generation": source.get("current_complete_generation"),
            "active_build_generation": source.get("active_build_generation"),
        }

    def section_page(
        self,
        *,
        map_revision: int,
        section_id: str,
        limit: int = MAX_SECTION_EVENTS,
        cursor: str | None = None,
    ) -> JsonObject:
        return self._resource_page(
            map_revision=map_revision,
            endpoint=SECTION_PAGE_ENDPOINT,
            resource_id=section_id,
            limit=limit,
            maximum=MAX_SECTION_EVENTS,
            cursor=cursor,
        )

    def branch_page(
        self,
        *,
        map_revision: int,
        branch_id: str,
        limit: int = MAX_RENDERED_ITEMS,
        cursor: str | None = None,
    ) -> JsonObject:
        return self._resource_page(
            map_revision=map_revision,
            endpoint=BRANCH_PAGE_ENDPOINT,
            resource_id=branch_id,
            limit=limit,
            maximum=MAX_RENDERED_ITEMS,
            cursor=cursor,
        )

    def _resource_page(
        self,
        *,
        map_revision: int,
        endpoint: str,
        resource_id: str,
        limit: int,
        maximum: int,
        cursor: str | None,
    ) -> JsonObject:
        snapshot = self._snapshot()
        self._require_revision(snapshot, map_revision)
        _nonempty(resource_id, "resource_id")
        _limit(limit, maximum)
        expectation = _CursorExpectation(
            snapshot,
            endpoint,
            resource_id,
            f"{endpoint}-items-v1",
            limit,
            "",
        )
        offset = 0 if cursor is None else _decode_cursor(cursor, expectation)
        source_slice = self._source.resource_slice(
            snapshot, endpoint, resource_id, offset, limit
        )
        if source_slice is None:
            raise StoryMapReaderNotFoundError("The Story Map V2 page resource is unavailable.")
        return self._page_response(snapshot, expectation, offset, source_slice)

    def projection_page(
        self,
        *,
        map_revision: int,
        endpoint: str,
        selection_id: str,
        limit: int,
        cursor: str | None,
        supplier: Callable[[int, int], ReaderSlice],
    ) -> JsonObject:
        """Page an existing M12/Phase 03 projection after validating its cursor."""

        if endpoint not in {PATH_PAGE_ENDPOINT, DETAIL_PAGE_ENDPOINT}:
            raise StoryMapReaderError("projection endpoint is unsupported")
        snapshot = self._snapshot()
        self._require_revision(snapshot, map_revision)
        _nonempty(selection_id, "selection_id")
        _limit(limit, MAX_RENDERED_ITEMS)
        expectation = _CursorExpectation(
            snapshot,
            endpoint,
            selection_id,
            f"{endpoint}-items-v1",
            limit,
            selection_id,
        )
        offset = 0 if cursor is None else _decode_cursor(cursor, expectation)
        return self._page_response(
            snapshot, expectation, offset, supplier(offset, limit)
        )

    def _page_response(
        self,
        snapshot: ReaderSnapshot,
        expectation: _CursorExpectation,
        offset: int,
        source_slice: ReaderSlice,
    ) -> JsonObject:
        if len(source_slice.items) > expectation.limit:
            raise StoryMapReaderDataError("reader source returned more items than requested")
        items: list[JsonObject] = []
        item_ids: list[str] = []
        for index, source_item in enumerate(source_slice.items):
            item = dict(_object(source_item, f"items[{index}]"))
            item_id = _nonempty(item.get("id"), f"items[{index}].id")
            if item_id in item_ids:
                raise StoryMapReaderDataError("reader page contains duplicate item IDs")
            item_ids.append(item_id)
            items.append(item)
        if expectation.endpoint == SECTION_PAGE_ENDPOINT:
            event_count = sum(item.get("kind") == "event" for item in items)
            if event_count > MAX_SECTION_EVENTS:
                raise StoryMapReaderDataError("section page exceeds the event cap")
        if len(items) > MAX_RENDERED_ITEMS:
            raise StoryMapReaderDataError("reader page exceeds the rendered-item cap")
        shells = list(_shells_for_items(source_slice.shells, item_ids))
        if (
            items
            and expectation.endpoint in {SECTION_PAGE_ENDPOINT, BRANCH_PAGE_ENDPOINT}
            and not shells
        ):
            raise StoryMapReaderDataError("a nonempty section or branch page requires a shell")

        next_offset = source_slice.next_offset
        response = self._make_page_response(
            snapshot, expectation, items, shells, next_offset
        )
        while len(_json_bytes(response)) > MAX_SERIALIZED_BYTES and items:
            items.pop()
            item_ids.pop()
            shells = list(_shells_for_items(source_slice.shells, item_ids))
            next_offset = offset + len(items)
            response = self._make_page_response(
                snapshot, expectation, items, shells, next_offset
            )
        if len(_json_bytes(response)) > MAX_SERIALIZED_BYTES or (
            source_slice.items and not items
        ):
            raise StoryMapReaderDataError("one reader item exceeds the serialized page cap")
        if (
            items
            and expectation.endpoint in {SECTION_PAGE_ENDPOINT, BRANCH_PAGE_ENDPOINT}
            and not shells
        ):
            raise StoryMapReaderDataError("a bounded page lost its required shell")
        return response

    @staticmethod
    def _make_page_response(
        snapshot: ReaderSnapshot,
        expectation: _CursorExpectation,
        items: Sequence[Mapping[str, object]],
        shells: Sequence[Mapping[str, object]],
        next_offset: int | None,
    ) -> JsonObject:
        next_cursor = (
            None if next_offset is None else _encode_cursor(expectation, next_offset)
        )
        return {
            "schema": READER_SCHEMA,
            "map_revision": snapshot.map_revision,
            "generation_id": snapshot.generation_id,
            "resource_id": expectation.resource_id,
            "items": [dict(item) for item in items],
            "shells": [dict(shell) for shell in shells],
            "rendered_item_count": len(items),
            "next_cursor": next_cursor,
        }

    def locate(self, *, map_revision: int, selection_id: str) -> JsonObject:
        snapshot = self._snapshot()
        self._require_revision(snapshot, map_revision)
        _nonempty(selection_id, "selection_id")
        location = self._source.locate(snapshot, selection_id)
        if location is None:
            raise StoryMapReaderNotFoundError("The Story Map V2 selection is unavailable.")
        endpoint = (
            BRANCH_PAGE_ENDPOINT if location.branch_id is not None else SECTION_PAGE_ENDPOINT
        )
        resource_id = location.branch_id or location.section_id
        limit = MAX_RENDERED_ITEMS if location.branch_id is not None else MAX_SECTION_EVENTS
        expectation = _CursorExpectation(
            snapshot,
            endpoint,
            resource_id,
            f"{endpoint}-items-v1",
            limit,
            "",
        )
        page_cursor = (
            None
            if location.page_offset == 0
            else _encode_cursor(expectation, location.page_offset)
        )
        return {
            "schema": READER_SCHEMA,
            "map_revision": snapshot.map_revision,
            "generation_id": snapshot.generation_id,
            "selection_id": selection_id,
            "location": {
                "section_id": location.section_id,
                "branch_id": location.branch_id,
                "page_cursor": page_cursor,
                "shell_id": location.shell_id,
                "item_id": location.item_id,
            },
        }

    def search(
        self,
        *,
        map_revision: int,
        query: str,
        limit: int = DEFAULT_SEARCH_RESULTS,
        cursor: str | None = None,
    ) -> JsonObject:
        snapshot = self._snapshot()
        self._require_revision(snapshot, map_revision)
        if not isinstance(query, str) or len(query) > 256:
            raise StoryMapReaderError("query must be a bounded string")
        _limit(limit, MAX_SEARCH_RESULTS)
        expectation = _CursorExpectation(
            snapshot,
            SEARCH_ENDPOINT,
            "search",
            "selection-index-v1",
            limit,
            query,
        )
        offset = 0 if cursor is None else _decode_cursor(cursor, expectation)
        found = self._source.search(snapshot, query, offset, limit)
        if len(found.results) > limit:
            raise StoryMapReaderDataError("search source returned too many results")
        response: JsonObject = {
            "schema": READER_SCHEMA,
            "map_revision": snapshot.map_revision,
            "generation_id": snapshot.generation_id,
            "query": query,
            "results": [
                dict(_object(item, "search.results[]")) for item in found.results
            ],
            "next_cursor": (
                None
                if found.next_offset is None
                else _encode_cursor(expectation, found.next_offset)
            ),
        }
        if len(_json_bytes(response)) > MAX_SERIALIZED_BYTES:
            raise StoryMapReaderDataError("search response exceeds the serialized page cap")
        return response

    def view_state(self, *, map_revision: int, view_key: str) -> JsonObject:
        snapshot = self._snapshot()
        self._require_revision(snapshot, map_revision)
        _nonempty(view_key, "view_key")
        state = dict(self._source.load_view_state(snapshot, view_key))
        state.setdefault("hide_new", False)
        _validate_view_state(state)
        return self._view_state_response(snapshot, view_key, state)

    def save_view_state(
        self,
        *,
        map_revision: int,
        view_key: str,
        state: Mapping[str, object],
    ) -> JsonObject:
        snapshot = self._snapshot()
        self._require_revision(snapshot, map_revision)
        _nonempty(view_key, "view_key")
        normalized = dict(_object(state, "state"))
        normalized.setdefault("hide_new", False)
        _validate_view_state(normalized)
        stored = dict(self._source.save_view_state(snapshot, view_key, normalized))
        stored.setdefault("hide_new", False)
        _validate_view_state(stored)
        return self._view_state_response(snapshot, view_key, stored)

    @staticmethod
    def _view_state_response(
        snapshot: ReaderSnapshot, view_key: str, state: Mapping[str, object]
    ) -> JsonObject:
        return {
            "schema": READER_SCHEMA,
            "map_revision": snapshot.map_revision,
            "generation_id": snapshot.generation_id,
            "view_key": view_key,
            "state": dict(state),
        }


def _limit(value: int, maximum: int) -> None:
    if type(value) is not int or not 1 <= value <= maximum:
        raise StoryMapReaderError("page limit is outside the allowed range")


def _validate_view_state(state: Mapping[str, object]) -> None:
    hide_new = state.get("hide_new")
    if hide_new is not None and not isinstance(hide_new, bool):
        raise StoryMapReaderError("view-state hide_new must be a boolean")
    if len(_json_bytes(dict(state))) > MAX_VIEW_STATE_BYTES:
        raise StoryMapReaderError("view state exceeds the durable bound")
