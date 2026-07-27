"""Read-only Phase 03 projection into the additive Phase 04 reader surface."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from renpy_story_mapper.story_map_v2.durable_repository import SqliteStoryMapV2Repository
from renpy_story_mapper.story_map_v2.phase03_contracts import (
    StoryChoiceReadModel,
    StoryMapProjectEnvelope,
    StoryMapReadModel,
)
from renpy_story_mapper.story_map_v2.reader import (
    BRANCH_PAGE_ENDPOINT,
    MAX_RENDERED_ITEMS,
    MAX_SECTION_EVENTS,
    SECTION_PAGE_ENDPOINT,
    JsonObject,
    MemoryStoryMapReaderSource,
    ReaderLocation,
    ReaderSnapshot,
    StoryMapReaderDataError,
)

_COMPAT_SECTION_ID = "section:phase03-compatible"


class Phase03CompatibilityReaderSource(MemoryStoryMapReaderSource):
    """One synthetic Level-1 section over immutable Phase 03 records."""

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
        repository: SqliteStoryMapV2Repository,
    ) -> None:
        super().__init__(
            snapshot,
            resources=resources,
            locations=locations,
            search_results=search_results,
        )
        self._repository = repository

    def load_view_state(
        self, snapshot: ReaderSnapshot, view_key: str
    ) -> Mapping[str, object]:
        record = self._repository.load_view_state(view_key)
        if record is None or record.map_revision != snapshot.map_revision:
            return {"hide_new": False}
        if not isinstance(record.state, Mapping):
            raise StoryMapReaderDataError("stored Phase 03 view state must be an object")
        return record.state

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
            generation_id=None,
            map_revision=snapshot.map_revision,
            selection_id=selection,
            section_id=section,
            state=dict(state),
        )
        if not isinstance(record.state, Mapping):
            raise StoryMapReaderDataError("stored Phase 03 view state must be an object")
        return record.state


def phase03_compatibility_source(
    stored: StoryMapProjectEnvelope,
    page: StoryMapReadModel,
    repository: SqliteStoryMapV2Repository,
) -> Phase03CompatibilityReaderSource:
    """Project a legacy record without rewriting its stored bytes."""

    section_items: list[JsonObject] = []
    section_item_ids: list[str] = []
    resources: dict[
        tuple[str, str],
        tuple[Sequence[Mapping[str, object]], Sequence[Mapping[str, object]]],
    ] = {}
    locations: dict[str, ReaderLocation] = {}
    search_results: list[JsonObject] = []
    choice_count = 0
    arm_count = 0

    for section in page.sections:
        for event in section.events:
            event_item: JsonObject = {
                "id": event.selection_id,
                "kind": "event",
                "order": len(section_items),
                "title": event.title,
                "summary": event.summary,
                "selection_id": event.selection_id,
                "is_new": False,
                "new_facts": [],
            }
            section_items.append(event_item)
            section_item_ids.append(event.selection_id)
            event_offset = ((len(section_items) - 1) // MAX_SECTION_EVENTS) * MAX_SECTION_EVENTS
            locations[event.selection_id] = ReaderLocation(
                _COMPAT_SECTION_ID,
                None,
                event_offset,
                "shell:phase03-compatible",
                event.selection_id,
            )
            search_results.append(
                {
                    "selection_id": event.selection_id,
                    "kind": "event",
                    "title": event.title,
                    "snippet": event.summary[:320],
                    "section_id": _COMPAT_SECTION_ID,
                    "is_loaded": False,
                }
            )
            for choice in event.choices:
                added_choices, added_arms = _add_choice(
                    choice,
                    resources,
                    locations,
                    search_results,
                )
                choice_count += added_choices
                arm_count += added_arms

    section_shell: JsonObject = {
        "id": "shell:phase03-compatible",
        "kind": "timeline",
        "item_ids": section_item_ids,
        "parent_shell_id": None,
        "route_id": None,
        "rejoin_selection_id": None,
    }
    resources[(SECTION_PAGE_ENDPOINT, _COMPAT_SECTION_ID)] = (
        tuple(section_items),
        (section_shell,),
    )
    generation_id = f"phase03:{stored.identity.identity_hash}"
    manifest = {
        "status": page.status,
        "overview": {"title": page.title, "summary": page.overview},
        "counts": {
            "sections": 1,
            "events": len(section_items),
            "choices": choice_count,
            "arms": arm_count,
            "endings": 0,
        },
        "sections": [
            {
                "id": _COMPAT_SECTION_ID,
                "order": 0,
                "title": page.title,
                "summary": page.overview,
                "route_id": None,
                "status": page.status,
                "event_count": len(section_items),
                "is_new": False,
                "new_facts": [],
            }
        ],
        "landmarks": [],
        "new_facts": {"baseline_generation_id": None, "facts": []},
    }
    status = {
        "run_id": "phase03-compatible",
        "state": page.status,
        "coverage": {
            "completed_chunks": len(stored.core.chunks),
            "total_chunks": len(stored.core.chunks),
            "event_fraction": 1.0,
        },
        "progress": {
            "completed_jobs": 0,
            "total_jobs": 0,
            "failed_jobs": 0,
            "indeterminate_jobs": 0,
        },
        "actions": {
            "can_cancel": False,
            "can_resume": False,
            "retry_approval_required": False,
        },
        "current_complete_generation": generation_id,
        "active_build_generation": None,
    }
    snapshot = ReaderSnapshot(
        0,
        generation_id,
        "phase03_compatible",
        manifest,
        status,
        stored.identity.authority_hash,
    )
    return Phase03CompatibilityReaderSource(
        snapshot,
        resources=resources,
        locations=locations,
        search_results=search_results,
        repository=repository,
    )


def _add_choice(
    choice: StoryChoiceReadModel,
    resources: dict[
        tuple[str, str],
        tuple[Sequence[Mapping[str, object]], Sequence[Mapping[str, object]]],
    ],
    locations: dict[str, ReaderLocation],
    search_results: list[JsonObject],
) -> tuple[int, int]:
    items: list[JsonObject] = []
    shells: list[JsonObject] = []
    choices = 1
    arms = 0
    for arm in choice.arms:
        item: JsonObject = {
            "id": arm.selection_id,
            "kind": "arm",
            "order": len(items),
            "title": arm.caption,
            "summary": arm.outcome_summary,
            "selection_id": arm.selection_id,
            "condition": arm.condition,
            "effects": list(arm.effects),
            "is_new": False,
            "new_facts": [],
        }
        items.append(item)
        rejoin = arm.rejoin_binding.selection_id if arm.rejoin_binding is not None else None
        shell_id = f"shell:{choice.key}:{len(items) - 1}"
        shells.append(
            {
                "id": shell_id,
                "kind": "branch",
                "item_ids": [arm.selection_id],
                "parent_shell_id": None,
                "route_id": None,
                "rejoin_selection_id": rejoin,
            }
        )
        offset = ((len(items) - 1) // MAX_RENDERED_ITEMS) * MAX_RENDERED_ITEMS
        locations[arm.selection_id] = ReaderLocation(
            _COMPAT_SECTION_ID,
            choice.key,
            offset,
            shell_id,
            arm.selection_id,
        )
        search_results.append(
            {
                "selection_id": arm.selection_id,
                "kind": "arm",
                "title": arm.caption,
                "snippet": arm.outcome_summary[:320],
                "section_id": _COMPAT_SECTION_ID,
                "is_loaded": False,
            }
        )
        arms += 1
        for nested in arm.nested_choices:
            nested_choices, nested_arms = _add_choice(
                nested, resources, locations, search_results
            )
            choices += nested_choices
            arms += nested_arms
    resources[(BRANCH_PAGE_ENDPOINT, choice.key)] = (tuple(items), tuple(shells))
    return choices, arms
