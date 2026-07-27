"""Schema-v7 indexed storage adapter for the Phase 04 reader."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Final

from renpy_story_mapper.story_map_v2.durable_repository import (
    GenerationDescriptor,
    GenerationPointers,
    SectionPageRecord,
    SelectionIndexRecord,
    SqliteStoryMapV2Repository,
)
from renpy_story_mapper.story_map_v2.reader import (
    BRANCH_PAGE_ENDPOINT,
    READER_STORAGE_PAGE_SCHEMA,
    SECTION_PAGE_ENDPOINT,
    JsonObject,
    ReaderLocation,
    ReaderSearchSlice,
    ReaderSlice,
    ReaderSnapshot,
    StoryMapReaderDataError,
)

_PAGE_READ_BATCH: Final = 64
_SEARCH_READ_BATCH: Final = 256
type WorkflowStatusProjector = Callable[
    [SqliteStoryMapV2Repository, GenerationDescriptor, GenerationPointers],
    Mapping[str, object],
]


def reader_storage_page(
    *,
    endpoint: str,
    resource_id: str,
    resource_offset: int,
    items: Sequence[Mapping[str, object]],
    shells: Sequence[Mapping[str, object]],
) -> JsonObject:
    """Create the semantic-free immutable page shape consumed by the reader."""

    if endpoint not in {SECTION_PAGE_ENDPOINT, BRANCH_PAGE_ENDPOINT}:
        raise ValueError("reader storage endpoint is unsupported")
    if not resource_id or resource_id != resource_id.strip():
        raise ValueError("reader storage resource ID must be non-empty")
    if type(resource_offset) is not int or resource_offset < 0:
        raise ValueError("reader storage resource offset cannot be negative")
    return {
        "schema": READER_STORAGE_PAGE_SCHEMA,
        "endpoint": endpoint,
        "resource_id": resource_id,
        "resource_offset": resource_offset,
        "items": [dict(item) for item in items],
        "shells": [dict(shell) for shell in shells],
    }


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise StoryMapReaderDataError(f"{label} must be an object")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, (tuple, list)):
        raise StoryMapReaderDataError(f"{label} must be an array")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 512:
        raise StoryMapReaderDataError(f"{label} must be a non-empty bounded string")
    return value


def _page_payload(page: SectionPageRecord) -> Mapping[str, object]:
    payload = _mapping(page.page, "stored reader page")
    if payload.get("schema") != READER_STORAGE_PAGE_SCHEMA:
        raise StoryMapReaderDataError("stored reader page schema is unsupported")
    endpoint = payload.get("endpoint")
    if endpoint not in {SECTION_PAGE_ENDPOINT, BRANCH_PAGE_ENDPOINT}:
        raise StoryMapReaderDataError("stored reader page endpoint is unsupported")
    _text(payload.get("resource_id"), "stored reader page resource_id")
    offset = payload.get("resource_offset")
    if type(offset) is not int or offset < 0:
        raise StoryMapReaderDataError("stored reader page resource_offset is invalid")
    items = _sequence(payload.get("items"), "stored reader page items")
    _sequence(payload.get("shells"), "stored reader page shells")
    if page.item_count != len(items):
        raise StoryMapReaderDataError("stored reader page item count is inconsistent")
    return payload


class DurableStoryMapReaderSource:
    """Read immutable page blobs through the existing schema-v7 covering indexes."""

    def __init__(
        self,
        repository: SqliteStoryMapV2Repository,
        *,
        workflow_status: WorkflowStatusProjector | None = None,
    ) -> None:
        self._repository = repository
        self._workflow_status = workflow_status

    def snapshot(self) -> ReaderSnapshot | None:
        pointers = self._repository.generation_pointers()
        generation_id = (
            pointers.current_complete_generation or pointers.active_build_generation
        )
        if generation_id is None:
            return None
        generation = self._repository.load_generation(generation_id)
        if generation is None:
            raise StoryMapReaderDataError("generation pointer references a missing generation")
        descriptor = _mapping(generation.descriptor, "generation descriptor")
        manifest = _mapping(
            descriptor.get("reader_manifest", descriptor.get("manifest")),
            "generation reader manifest",
        )
        if self._workflow_status is not None:
            status = self._workflow_status(self._repository, generation, pointers)
        else:
            status = _mapping(
                descriptor.get("reader_status", descriptor.get("status")),
                "generation reader status",
            )
        normalized_status = dict(status)
        normalized_status["current_complete_generation"] = pointers.current_complete_generation
        normalized_status["active_build_generation"] = pointers.active_build_generation
        freshness = "current"
        if pointers.active_build_generation is not None:
            freshness = "building"
        declared = manifest.get("freshness")
        if declared in {"current", "building", "stale"}:
            freshness = str(declared)
        return ReaderSnapshot(
            pointers.map_revision,
            generation.generation_id,
            freshness,
            manifest,
            normalized_status,
            generation.authority_identity,
        )

    def resource_slice(
        self,
        snapshot: ReaderSnapshot,
        endpoint: str,
        resource_id: str,
        offset: int,
        limit: int,
    ) -> ReaderSlice | None:
        location = self._resource_location(snapshot.generation_id, endpoint, resource_id)
        if location is None:
            return None
        section_id, start_page = location
        records = self._resource_records(
            snapshot.generation_id, section_id, start_page, endpoint, resource_id
        )
        if not records:
            return None
        selected_items: list[Mapping[str, object]] = []
        selected_shells: list[Mapping[str, object]] = []
        has_more = False
        for record in records:
            payload = _page_payload(record)
            page_offset = payload["resource_offset"]
            assert isinstance(page_offset, int)
            page_items = _sequence(payload["items"], "stored reader page items")
            page_end = page_offset + len(page_items)
            if page_end <= offset:
                continue
            if page_offset > offset + len(selected_items) and not selected_items:
                raise StoryMapReaderDataError("stored reader resource has an offset gap")
            local_start = max(0, offset - page_offset)
            available = page_items[local_start:]
            remaining = limit - len(selected_items)
            for item in available[:remaining]:
                selected_items.append(_mapping(item, "stored reader item"))
            selected_shells.extend(
                _mapping(shell, "stored reader shell")
                for shell in _sequence(payload["shells"], "stored reader page shells")
            )
            if len(available) > remaining:
                has_more = True
                break
            if len(selected_items) == limit:
                has_more = page_end < self._resource_end(records)
                break
        if not selected_items and offset > 0:
            return None
        next_offset = offset + len(selected_items) if has_more else None
        return ReaderSlice(tuple(selected_items), tuple(selected_shells), next_offset)

    def _resource_location(
        self, generation_id: str, endpoint: str, resource_id: str
    ) -> tuple[str, int] | None:
        if endpoint == SECTION_PAGE_ENDPOINT:
            return resource_id, 0
        if endpoint != BRANCH_PAGE_ENDPOINT:
            raise StoryMapReaderDataError("indexed reader endpoint is unsupported")
        index = self._repository.locate_selection(generation_id, resource_id)
        if index is None or index.selection_kind != "branch_resource":
            return None
        return index.section_id, index.page_ordinal

    def _resource_records(
        self,
        generation_id: str,
        section_id: str,
        start_page: int,
        endpoint: str,
        resource_id: str,
    ) -> tuple[SectionPageRecord, ...]:
        records: list[SectionPageRecord] = []
        next_page = start_page
        while True:
            batch = self._repository.list_section_pages(
                generation_id,
                section_id,
                start_page_ordinal=next_page,
                limit=_PAGE_READ_BATCH,
            )
            if not batch:
                break
            for record in batch:
                payload = _page_payload(record)
                if payload["endpoint"] != endpoint or payload["resource_id"] != resource_id:
                    return tuple(records)
                records.append(record)
            if len(batch) < _PAGE_READ_BATCH:
                break
            next_page = batch[-1].page_ordinal + 1
        return tuple(records)

    @staticmethod
    def _resource_end(records: Sequence[SectionPageRecord]) -> int:
        if not records:
            return 0
        payload = _page_payload(records[-1])
        offset = payload["resource_offset"]
        assert isinstance(offset, int)
        return offset + records[-1].item_count

    def locate(
        self, snapshot: ReaderSnapshot, selection_id: str
    ) -> ReaderLocation | None:
        index = self._repository.locate_selection(snapshot.generation_id, selection_id)
        if index is None or index.selection_kind == "branch_resource":
            return None
        record = self._repository.load_section_page(
            snapshot.generation_id, index.section_id, index.page_ordinal
        )
        if record is None:
            raise StoryMapReaderDataError("selection index references a missing page")
        payload = _page_payload(record)
        items = _sequence(payload["items"], "stored reader page items")
        if index.item_ordinal >= len(items):
            raise StoryMapReaderDataError("selection index item ordinal is outside its page")
        item = _mapping(items[index.item_ordinal], "stored reader item")
        item_id = _text(item.get("id"), "stored reader item id")
        item_selection = item.get("selection_id")
        if item_selection != selection_id and item_id != selection_id:
            raise StoryMapReaderDataError("selection index does not match its stored item")
        shell_id: str | None = None
        for shell_value in _sequence(payload["shells"], "stored reader page shells"):
            shell = _mapping(shell_value, "stored reader shell")
            members = _sequence(shell.get("item_ids"), "stored reader shell item_ids")
            if item_id in members:
                shell_id = _text(shell.get("id"), "stored reader shell id")
                break
        if shell_id is None:
            raise StoryMapReaderDataError("selection item has no server-authored shell")
        endpoint = payload["endpoint"]
        resource_id = _text(payload["resource_id"], "stored reader resource_id")
        resource_offset = payload["resource_offset"]
        assert isinstance(resource_offset, int)
        return ReaderLocation(
            section_id=index.section_id,
            branch_id=resource_id if endpoint == BRANCH_PAGE_ENDPOINT else None,
            page_offset=resource_offset,
            shell_id=shell_id,
            item_id=item_id,
        )

    def search(
        self,
        snapshot: ReaderSnapshot,
        query: str,
        offset: int,
        limit: int,
    ) -> ReaderSearchSlice:
        total = self._repository.count_selections(snapshot.generation_id)
        cursor = offset
        folded = query.casefold()
        results: list[JsonObject] = []
        page_cache: dict[tuple[str, int], Mapping[str, object]] = {}
        while cursor < total and len(results) < limit:
            batch = self._repository.list_selections(
                snapshot.generation_id, offset=cursor, limit=_SEARCH_READ_BATCH
            )
            if not batch:
                cursor = total
                break
            for index in batch:
                cursor += 1
                if index.selection_kind == "branch_resource":
                    continue
                item = self._selection_item(snapshot.generation_id, index, page_cache)
                title_value = item.get("title", item.get("caption", index.selection_id))
                title = title_value if isinstance(title_value, str) else index.selection_id
                summary_value = item.get("summary", item.get("text", ""))
                summary = summary_value if isinstance(summary_value, str) else ""
                haystack = "\n".join((index.selection_id, title, summary)).casefold()
                if folded not in haystack:
                    continue
                results.append(
                    {
                        "selection_id": index.selection_id,
                        "kind": index.selection_kind,
                        "title": title,
                        "snippet": summary[:320],
                        "section_id": index.section_id,
                        "is_loaded": False,
                    }
                )
                if len(results) == limit:
                    break
            if len(batch) < _SEARCH_READ_BATCH:
                cursor = total
        return ReaderSearchSlice(tuple(results), cursor if cursor < total else None)

    def _selection_item(
        self,
        generation_id: str,
        index: SelectionIndexRecord,
        cache: dict[tuple[str, int], Mapping[str, object]],
    ) -> Mapping[str, object]:
        key = (index.section_id, index.page_ordinal)
        payload = cache.get(key)
        if payload is None:
            record = self._repository.load_section_page(
                generation_id, index.section_id, index.page_ordinal
            )
            if record is None:
                raise StoryMapReaderDataError("selection index references a missing page")
            payload = _page_payload(record)
            cache[key] = payload
        items = _sequence(payload["items"], "stored reader page items")
        if index.item_ordinal >= len(items):
            raise StoryMapReaderDataError("selection index item ordinal is outside its page")
        return _mapping(items[index.item_ordinal], "stored reader item")

    def load_view_state(
        self, snapshot: ReaderSnapshot, view_key: str
    ) -> Mapping[str, object]:
        record = self._repository.load_view_state(view_key)
        if record is None:
            return {"hide_new": False}
        if (
            record.generation_id != snapshot.generation_id
            or record.map_revision != snapshot.map_revision
        ):
            return {"hide_new": False}
        return _mapping(record.state, "stored reader view state")

    def save_view_state(
        self,
        snapshot: ReaderSnapshot,
        view_key: str,
        state: Mapping[str, object],
    ) -> Mapping[str, object]:
        selection = state.get("selection_id")
        section = state.get("section_id")
        if selection is not None and not isinstance(selection, str):
            raise StoryMapReaderDataError("view-state selection_id must be a string or null")
        if section is not None and not isinstance(section, str):
            raise StoryMapReaderDataError("view-state section_id must be a string or null")
        record = self._repository.save_view_state(
            view_key,
            generation_id=snapshot.generation_id,
            map_revision=snapshot.map_revision,
            selection_id=selection,
            section_id=section,
            state=dict(state),
        )
        return _mapping(record.state, "stored reader view state")
