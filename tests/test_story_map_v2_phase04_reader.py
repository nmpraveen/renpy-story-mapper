from __future__ import annotations

import hashlib
import http.client
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import pytest

from renpy_story_mapper import storage
from renpy_story_mapper.m12_service import M12RouteService, load_m12_authority
from renpy_story_mapper.project import Project
from renpy_story_mapper.story_map_v2.contracts import (
    ChunkStatus,
    Reachability,
    StoryMapCore,
    canonical_hash,
)
from renpy_story_mapper.story_map_v2.durable_repository import (
    FrozenRunDescriptor,
    GenerationDescriptor,
    GenerationKind,
    SectionPageRecord,
    SelectionIndexRecord,
)
from renpy_story_mapper.story_map_v2.navigation import StoryMapNavigator
from renpy_story_mapper.story_map_v2.persistence import (
    load_story_map_v2_for_current_project,
)
from renpy_story_mapper.story_map_v2.phase03_contracts import (
    PROJECT_SCHEMA,
    NavigationBinding,
    SourceBinding,
    StoryEventReadModel,
    StoryMapProjectEnvelope,
    StoryMapProjectIdentity,
    StoryMapReadModel,
    StorySectionReadModel,
)
from renpy_story_mapper.story_map_v2.presentation import project_story_map
from renpy_story_mapper.story_map_v2.reader import (
    BRANCH_PAGE_ENDPOINT,
    DETAIL_PAGE_ENDPOINT,
    MAX_RENDERED_ITEMS,
    MAX_SECTION_EVENTS,
    MAX_SERIALIZED_BYTES,
    PATH_PAGE_ENDPOINT,
    READER_SCHEMA,
    SECTION_PAGE_ENDPOINT,
    InvalidStoryMapCursorError,
    MemoryStoryMapReaderSource,
    ReaderLocation,
    ReaderSlice,
    ReaderSnapshot,
    StaleMapRevisionError,
    StoryMapReader,
    StoryMapReaderDataError,
)
from renpy_story_mapper.story_map_v2.reader_compat import phase03_compatibility_source
from renpy_story_mapper.story_map_v2.reader_store import (
    DurableStoryMapReaderSource,
    reader_storage_page,
)
from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.contracts import (
    STORY_MAP_V2_API_ROUTES,
    STORY_MAP_V2_READER_API_ROUTES,
)
from renpy_story_mapper.web.security import SessionSecurity
from renpy_story_mapper.web.server import LocalWebServer, start_in_thread
from renpy_story_mapper.web.state import UserStateStore

FIXTURES = Path(__file__).parent / "fixtures" / "story_map_v2"
READER_V1_FIXTURE = FIXTURES / "phase04_reader_contract_v1.json"
READER_V2_FIXTURE = FIXTURES / "phase04_reader_contract_v2.json"
SCALE_FIXTURE = FIXTURES / "phase04_reader_scale_v1.json"
AUTHORITY = hashlib.sha256(b"phase04-reader-authority").hexdigest()


@dataclass
class _Dialogs:
    def choose_source(self, _kind: str) -> None:
        return None

    def choose_open_project(self) -> None:
        return None

    def choose_save_project(self) -> None:
        return None


@dataclass(frozen=True)
class _LargeFixture:
    reader: StoryMapReader
    source: MemoryStoryMapReaderSource
    resources: Mapping[
        tuple[str, str],
        tuple[Sequence[Mapping[str, object]], Sequence[Mapping[str, object]]],
    ]
    locations: Mapping[str, ReaderLocation]
    search_results: Sequence[Mapping[str, object]]
    manifest: Mapping[str, object]
    status: Mapping[str, object]


def _json_size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def _reader_snapshot(
    revision: int,
    manifest: Mapping[str, object],
    status: Mapping[str, object],
) -> ReaderSnapshot:
    return ReaderSnapshot(
        map_revision=revision,
        generation_id=f"generation:complete:{revision}",
        freshness="current",
        manifest=manifest,
        status=status,
        cursor_authority=AUTHORITY,
    )


def _fixture_examples() -> tuple[dict[str, object], dict[str, object]]:
    fixture = json.loads(READER_V1_FIXTURE.read_text(encoding="utf-8"))
    examples = fixture["examples"]
    return examples["manifest"], examples["status"]


def _small_reader(*, revision: int = 7) -> StoryMapReader:
    manifest, status = _fixture_examples()
    section_items = [
        {
            "id": f"event:{index:02d}",
            "kind": "event",
            "order": index,
            "title": f"Event {index:02d}",
            "summary": "Unloaded section event.",
            "selection_id": f"event:{index:02d}",
            "is_new": index == 30,
            "new_facts": [{"kind": "event", "fact_id": "event:30"}]
            if index == 30
            else [],
        }
        for index in range(31)
    ]
    branch_items = [
        {
            "id": f"arm:{index:03d}",
            "kind": "arm",
            "order": index,
            "title": f"Route arm {index:03d}",
            "summary": "Unloaded branch arm.",
            "selection_id": f"arm:{index:03d}",
            "condition": None,
            "effects": [],
            "is_new": False,
            "new_facts": [],
        }
        for index in range(241)
    ]
    resources = {
        (SECTION_PAGE_ENDPOINT, "section:prologue"): (
            section_items,
            (
                {
                    "id": "shell:prologue",
                    "kind": "timeline",
                    "item_ids": [item["id"] for item in section_items],
                    "parent_shell_id": None,
                    "route_id": None,
                    "rejoin_selection_id": None,
                },
            ),
        ),
        (BRANCH_PAGE_ENDPOINT, "choice:first"): (
            branch_items,
            (
                {
                    "id": "shell:first",
                    "kind": "branch",
                    "item_ids": [item["id"] for item in branch_items],
                    "parent_shell_id": "shell:prologue",
                    "route_id": "route:first",
                    "rejoin_selection_id": "event:30",
                },
            ),
        ),
    }
    locations = {
        "event:30": ReaderLocation(
            "section:prologue", None, 30, "shell:prologue", "event:30"
        ),
        "arm:240": ReaderLocation(
            "section:prologue", "choice:first", 240, "shell:first", "arm:240"
        ),
    }
    search_results = (
        {
            "selection_id": "event:30",
            "kind": "event",
            "title": "Event 30",
            "snippet": "Found without hydrating its section.",
            "section_id": "section:prologue",
            "is_loaded": False,
        },
        {
            "selection_id": "arm:240",
            "kind": "arm",
            "title": "Route arm 240",
            "snippet": "Found without hydrating its branch.",
            "section_id": "section:prologue",
            "is_loaded": False,
        },
    )
    source = MemoryStoryMapReaderSource(
        _reader_snapshot(revision, manifest, status),
        resources=resources,
        locations=locations,
        search_results=search_results,
    )
    return StoryMapReader(source)


def _large_fixture() -> _LargeFixture:
    spec = json.loads(SCALE_FIXTURE.read_text(encoding="utf-8"))
    counts = spec["counts"]
    shape = spec["shape"]
    section_items: list[list[dict[str, object]]] = [[] for _ in range(counts["sections"])]
    resources: dict[
        tuple[str, str],
        tuple[Sequence[Mapping[str, object]], Sequence[Mapping[str, object]]],
    ] = {}
    locations: dict[str, ReaderLocation] = {}
    search_results: list[dict[str, object]] = []

    def section_for(index: int, total: int) -> int:
        return min(counts["sections"] - 1, index * counts["sections"] // total)

    for index in range(counts["events"]):
        selection_id = f"event:{index:05d}"
        section_index = section_for(index, counts["events"])
        item = {
            "id": selection_id,
            "kind": "event",
            "order": len(section_items[section_index]),
            "title": f"Event {index:05d}",
            "summary": f"Deterministic event {index:05d}.",
            "selection_id": selection_id,
            "is_new": index % 997 == 0,
            "new_facts": (
                [{"kind": "event", "fact_id": selection_id}] if index % 997 == 0 else []
            ),
        }
        item_ordinal = len(section_items[section_index])
        section_items[section_index].append(item)
        locations[selection_id] = ReaderLocation(
            f"section:{section_index:03d}",
            None,
            (item_ordinal // MAX_SECTION_EVENTS) * MAX_SECTION_EVENTS,
            f"shell:section:{section_index:03d}",
            selection_id,
        )
        search_results.append(
            {
                "selection_id": selection_id,
                "kind": "event",
                "title": item["title"],
                "snippet": item["summary"],
                "section_id": f"section:{section_index:03d}",
                "is_loaded": False,
            }
        )

    next_arm_index = 0
    for index in range(counts["choices"]):
        choice_id = f"choice:{index:05d}"
        section_index = section_for(index, counts["choices"])
        choice_item = {
            "id": choice_id,
            "kind": "choice",
            "order": len(section_items[section_index]),
            "title": f"Choice {index:05d}",
            "summary": "Deterministic branch point.",
            "selection_id": choice_id,
            "depth": index % 9,
            "is_new": False,
            "new_facts": [],
        }
        item_ordinal = len(section_items[section_index])
        section_items[section_index].append(choice_item)
        locations[choice_id] = ReaderLocation(
            f"section:{section_index:03d}",
            None,
            (item_ordinal // MAX_SECTION_EVENTS) * MAX_SECTION_EVENTS,
            f"shell:section:{section_index:03d}",
            choice_id,
        )
        search_results.append(
            {
                "selection_id": choice_id,
                "kind": "choice",
                "title": choice_item["title"],
                "snippet": choice_item["summary"],
                "section_id": f"section:{section_index:03d}",
                "is_loaded": False,
            }
        )

        arm_count = 241 if index == 0 else (4 if index <= 4_762 else 3)
        arms: list[dict[str, object]] = []
        arm_ids: list[str] = []
        for arm_index in range(arm_count):
            arm_id = f"arm:{index:05d}:{arm_index:03d}"
            global_arm_index = next_arm_index + arm_index
            rejoin = (
                "event:00200" if global_arm_index == 0 else f"event:{global_arm_index:05d}"
            ) if global_arm_index < counts["rejoins"] else None
            arm = {
                "id": arm_id,
                "kind": "arm",
                "order": arm_index,
                "title": f"Arm {index:05d}/{arm_index:03d}",
                "summary": "Deterministic branch arm.",
                "selection_id": arm_id,
                "condition": None,
                "effects": [],
                "rejoin_selection_id": rejoin,
                "is_new": False,
                "new_facts": [],
            }
            arms.append(arm)
            arm_ids.append(arm_id)
            locations[arm_id] = ReaderLocation(
                f"section:{section_index:03d}",
                choice_id,
                (arm_index // MAX_RENDERED_ITEMS) * MAX_RENDERED_ITEMS,
                f"shell:branch:{choice_id}",
                arm_id,
            )
            search_results.append(
                {
                    "selection_id": arm_id,
                    "kind": "arm",
                    "title": arm["title"],
                    "snippet": arm["summary"],
                    "section_id": f"section:{section_index:03d}",
                    "is_loaded": False,
                }
            )
        resources[(BRANCH_PAGE_ENDPOINT, choice_id)] = (
            tuple(arms),
            (
                {
                    "id": f"shell:branch:{choice_id}",
                    "kind": "branch",
                    "item_ids": arm_ids,
                    "parent_shell_id": f"shell:section:{section_index:03d}",
                    "route_id": "route:persistent" if section_index < 50 else None,
                    "rejoin_selection_id": arms[0]["rejoin_selection_id"] if arms else None,
                },
            ),
        )
        next_arm_index += arm_count

    for index in range(counts["rejoins"]):
        selection_id = f"rejoin:{index:05d}"
        section_index = section_for(index, counts["rejoins"])
        item_ordinal = len(section_items[section_index])
        item = {
            "id": selection_id,
            "kind": "rejoin",
            "order": item_ordinal,
            "title": f"Rejoin {index:05d}",
            "summary": "Deterministic topology rejoin.",
            "selection_id": selection_id,
            "is_new": False,
            "new_facts": [],
        }
        section_items[section_index].append(item)
        locations[selection_id] = ReaderLocation(
            f"section:{section_index:03d}",
            None,
            (item_ordinal // MAX_SECTION_EVENTS) * MAX_SECTION_EVENTS,
            f"shell:section:{section_index:03d}",
            selection_id,
        )
        search_results.append(
            {
                "selection_id": selection_id,
                "kind": "rejoin",
                "title": item["title"],
                "snippet": item["summary"],
                "section_id": f"section:{section_index:03d}",
                "is_loaded": False,
            }
        )

    sections: list[dict[str, object]] = []
    for index, items in enumerate(section_items):
        section_id = f"section:{index:03d}"
        item_ids = [str(item["id"]) for item in items]
        resources[(SECTION_PAGE_ENDPOINT, section_id)] = (
            tuple(items),
            (
                {
                    "id": f"shell:section:{index:03d}",
                    "kind": "timeline",
                    "item_ids": item_ids,
                    "parent_shell_id": None,
                    "route_id": "route:persistent" if index < 50 else None,
                    "rejoin_selection_id": None,
                },
            ),
        )
        sections.append(
            {
                "id": section_id,
                "order": index,
                "title": f"Section {index:03d}",
                "summary": "Deterministic scalable section.",
                "route_id": "route:persistent" if index < 50 else None,
                "status": "complete",
                "event_count": sum(item["kind"] == "event" for item in items),
                "is_new": False,
                "new_facts": [],
            }
        )

    manifest = {
        "status": "complete",
        "overview": {"title": "Large deterministic fixture", "summary": "Scale proof."},
        "counts": {
            **counts,
            "endings": 1,
        },
        "sections": sections,
        "landmarks": [
            {
                "kind": "ending",
                "id": "ending:final",
                "section_id": "section:255",
                "selection_id": shape["final_section_target"],
                "title": "Final section target",
            }
        ],
        "new_facts": {
            "baseline_generation_id": "generation:complete:6",
            "facts": [{"kind": "event", "fact_id": "event:00000"}],
        },
    }
    status = {
        "run_id": "run:scale",
        "state": "complete",
        "coverage": {
            "completed_chunks": 256,
            "total_chunks": 256,
            "event_fraction": 1.0,
        },
        "progress": {
            "completed_jobs": 256,
            "total_jobs": 256,
            "failed_jobs": 0,
            "indeterminate_jobs": 0,
        },
        "actions": {
            "can_cancel": False,
            "can_resume": False,
            "retry_approval_required": False,
        },
        "current_complete_generation": "generation:complete:7",
        "active_build_generation": None,
    }
    source = MemoryStoryMapReaderSource(
        _reader_snapshot(7, manifest, status),
        resources=resources,
        locations=locations,
        search_results=search_results,
    )
    return _LargeFixture(
        StoryMapReader(source),
        source,
        resources,
        locations,
        search_results,
        manifest,
        status,
    )


def _store_page(
    repository: object,
    *,
    generation_id: str,
    section_id: str,
    page_ordinal: int,
    payload: Mapping[str, object],
) -> None:
    page_bytes = storage.canonical_json(dict(payload))
    repository.store_section_page(  # type: ignore[attr-defined]
        SectionPageRecord(
            generation_id,
            section_id,
            page_ordinal,
            len(payload["items"]),  # type: ignore[arg-type]
            dict(payload),
            hashlib.sha256(page_bytes).hexdigest(),
        )
    )


def _reader_generation_descriptor(
    generation_id: str,
    manifest: Mapping[str, object],
    status: Mapping[str, object],
    *,
    lineage_seed: str | None = None,
) -> dict[str, object]:
    seed = generation_id if lineage_seed is None else lineage_seed

    def identity(kind: str) -> str:
        return hashlib.sha256(f"{kind}:{seed}".encode()).hexdigest()

    return {
        "schema": "story-map-v2-phase04-generation-v1",
        "generation_id": generation_id,
        "story_chunk_plan_identity": identity("chunk-plan"),
        "source_identity": identity("source"),
        "coverage_hash": identity("coverage"),
        "path_facts": [],
        "baseline_generation_id": None,
        "reader_manifest": dict(manifest),
        "reader_status": dict(status),
    }


def _durable_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "phase04-reader.rsmproj"
    manifest, status = _fixture_examples()
    with Project.create(project_path) as project:
        repository = project.story_map_v2_repository()
        repository.create_run(FrozenRunDescriptor("run-reader", "plan-reader", AUTHORITY), ())
        generation_id = "generation-reader"
        build_id = "build-reader"
        descriptor = _reader_generation_descriptor(generation_id, manifest, status)
        build = GenerationDescriptor(
            build_id,
            "run-reader",
            "plan-reader",
            AUTHORITY,
            GenerationKind.CANDIDATE,
            _reader_generation_descriptor(
                build_id,
                manifest,
                status,
                lineage_seed=generation_id,
            ),
        )
        generation = GenerationDescriptor(
            generation_id,
            "run-reader",
            "plan-reader",
            AUTHORITY,
            GenerationKind.COMPLETE,
            descriptor,
        )
        repository.create_generation(build)
        repository.create_generation(generation)
        repository.set_active_generation(
            build.generation_id,
            expected_active_generation_id=None,
            expected_complete_generation_id=None,
        )

        section_payload = reader_storage_page(
            endpoint=SECTION_PAGE_ENDPOINT,
            resource_id="section:prologue",
            resource_offset=0,
            items=(
                {
                    "id": "event:intro",
                    "kind": "event",
                    "order": 0,
                    "title": "Arrival",
                    "summary": "Durably indexed unloaded event.",
                    "selection_id": "event:intro",
                    "is_new": True,
                    "new_facts": [{"kind": "event", "fact_id": "event:intro"}],
                },
            ),
            shells=(
                {
                    "id": "shell:prologue",
                    "kind": "timeline",
                    "item_ids": ["event:intro"],
                    "parent_shell_id": None,
                    "route_id": None,
                    "rejoin_selection_id": None,
                },
            ),
        )
        branch_payload = reader_storage_page(
            endpoint=BRANCH_PAGE_ENDPOINT,
            resource_id="choice:first",
            resource_offset=0,
            items=(
                {
                    "id": "arm:a",
                    "kind": "arm",
                    "order": 0,
                    "title": "Take route A",
                    "summary": "Durably indexed unloaded arm.",
                    "selection_id": "arm:a",
                    "condition": None,
                    "effects": [],
                    "is_new": False,
                    "new_facts": [],
                },
            ),
            shells=(
                {
                    "id": "shell:branch:a",
                    "kind": "branch",
                    "item_ids": ["arm:a"],
                    "parent_shell_id": "shell:prologue",
                    "route_id": "route:a",
                    "rejoin_selection_id": None,
                },
            ),
        )
        _store_page(
            repository,
            generation_id=generation.generation_id,
            section_id="section:prologue",
            page_ordinal=0,
            payload=section_payload,
        )
        _store_page(
            repository,
            generation_id=generation.generation_id,
            section_id="section:prologue",
            page_ordinal=1,
            payload=branch_payload,
        )
        for record in (
            SelectionIndexRecord(
                generation.generation_id,
                "event:intro",
                "section:prologue",
                0,
                0,
                "event",
            ),
            SelectionIndexRecord(
                generation.generation_id,
                "choice:first",
                "section:prologue",
                1,
                0,
                "branch_resource",
            ),
            SelectionIndexRecord(
                generation.generation_id,
                "arm:a",
                "section:prologue",
                1,
                0,
                "arm",
            ),
        ):
            repository.store_selection(record)
        repository.publish_generation(
            generation.generation_id,
            expected_active_generation_id=build.generation_id,
            expected_complete_generation_id=None,
        )
    return project_path


def _publish_reader_generation(
    project: Project,
    *,
    suffix: str,
    authority: str,
    pages: Sequence[tuple[str, int, Mapping[str, object]]],
    selections: Sequence[SelectionIndexRecord] = (),
) -> GenerationDescriptor:
    manifest, status = _fixture_examples()
    repository = project.story_map_v2_repository()
    run_id = f"run-{suffix}"
    plan_id = f"plan-{suffix}"
    generation_id = f"generation-{suffix}"
    build_id = f"build-{suffix}"
    repository.create_run(FrozenRunDescriptor(run_id, plan_id, authority), ())
    build = GenerationDescriptor(
        build_id,
        run_id,
        plan_id,
        authority,
        GenerationKind.CANDIDATE,
        _reader_generation_descriptor(
            build_id,
            manifest,
            status,
            lineage_seed=generation_id,
        ),
    )
    generation = GenerationDescriptor(
        generation_id,
        run_id,
        plan_id,
        authority,
        GenerationKind.COMPLETE,
        _reader_generation_descriptor(generation_id, manifest, status),
    )
    repository.create_generation(build)
    repository.create_generation(generation)
    previous_complete = repository.generation_pointers().current_complete_generation
    repository.set_active_generation(
        build_id,
        expected_active_generation_id=None,
        expected_complete_generation_id=previous_complete,
    )
    for section_id, page_ordinal, payload in pages:
        _store_page(
            repository,
            generation_id=generation_id,
            section_id=section_id,
            page_ordinal=page_ordinal,
            payload=payload,
        )
    for selection in selections:
        repository.store_selection(selection)
    repository.publish_generation(
        generation_id,
        expected_active_generation_id=build_id,
        expected_complete_generation_id=previous_complete,
    )
    return generation


def _api(tmp_path: Path, project_path: Path, provider_calls: list[str]) -> ProjectApi:
    def provider_trap() -> object:
        provider_calls.append("provider")
        raise AssertionError("reader APIs must not construct a provider")

    api = ProjectApi(
        _Dialogs(),
        state_store=UserStateStore(tmp_path / "state.json"),
        m07_provider_factory=provider_trap,
        m13_provider_factory=provider_trap,
    )
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    api._retain_project_path(project_path, source)
    return api


def _post_json(
    server: LocalWebServer,
    path: str,
    body: Mapping[str, object],
) -> tuple[int, dict[str, object]]:
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    payload = json.dumps(body).encode()
    connection.request(
        "POST",
        path,
        body=payload,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
            "Host": f"127.0.0.1:{server.port}",
            "Origin": f"http://127.0.0.1:{server.port}",
            "X-RSM-Session": "session-secret",
            "X-RSM-CSRF": "csrf-secret",
        },
    )
    response = connection.getresponse()
    decoded = json.loads(response.read())
    connection.close()
    assert isinstance(decoded, dict)
    return response.status, decoded


def test_reader_v2_contract_and_bootstrap_routes_are_exact(tmp_path: Path) -> None:
    v1 = json.loads(READER_V1_FIXTURE.read_text(encoding="utf-8"))
    v2 = json.loads(READER_V2_FIXTURE.read_text(encoding="utf-8"))
    assert READER_SCHEMA == "story-map-v2-reader-contract-v2"
    assert v2["extends"] == v1["schema"]
    assert v2["delta"] == {
        "locate_location_required_field": "branch_id",
        "page_cursor_binding": "branch_id_when_non_null_else_section_id",
    }
    assert v1["routes"] == STORY_MAP_V2_READER_API_ROUTES

    project_path = _durable_project(tmp_path)
    api = _api(tmp_path, project_path, [])
    try:
        bootstrap = api.dispatch("GET", "/api/v1/bootstrap", {})
    finally:
        api.close()
    assert bootstrap["routes"]["story_map_v2"] == STORY_MAP_V2_API_ROUTES
    assert bootstrap["routes"]["story_map_v2_reader"] == v1["routes"]


def test_manifest_status_and_view_state_preserve_python_new_facts() -> None:
    reader = _small_reader()
    manifest = reader.manifest()
    status = reader.status()
    assert manifest["schema"] == status["schema"] == READER_SCHEMA
    assert manifest["map_revision"] == status["map_revision"] == 7
    original_new_facts = manifest["new_facts"]

    assert reader.view_state(map_revision=7, view_key="route-map")["state"] == {
        "hide_new": False
    }
    saved = reader.save_view_state(
        map_revision=7,
        view_key="route-map",
        state={
            "section_id": "section:prologue",
            "selection_id": "event:30",
            "hide_new": True,
        },
    )
    assert saved["state"]["hide_new"] is True
    assert reader.manifest()["new_facts"] == original_new_facts


def test_pages_enforce_limits_bytes_shells_and_repeatability() -> None:
    reader = _small_reader()
    first = reader.section_page(
        map_revision=7, section_id="section:prologue", limit=MAX_SECTION_EVENTS
    )
    assert first == reader.section_page(
        map_revision=7, section_id="section:prologue", limit=MAX_SECTION_EVENTS
    )
    assert first["rendered_item_count"] == MAX_SECTION_EVENTS
    assert first["shells"]
    assert first["next_cursor"]
    second = reader.section_page(
        map_revision=7,
        section_id="section:prologue",
        limit=MAX_SECTION_EVENTS,
        cursor=first["next_cursor"],
    )
    assert second["rendered_item_count"] == 1
    assert second["shells"]

    branch = reader.branch_page(map_revision=7, branch_id="choice:first")
    assert branch["rendered_item_count"] == MAX_RENDERED_ITEMS
    assert branch["shells"]
    assert _json_size(branch) <= MAX_SERIALIZED_BYTES

    manifest, status = _fixture_examples()
    huge_items = tuple(
        {
            "id": f"event:huge:{index}",
            "kind": "event",
            "title": "Huge",
            "summary": "x" * 600_000,
        }
        for index in range(2)
    )
    source = MemoryStoryMapReaderSource(
        _reader_snapshot(7, manifest, status),
        resources={
            (SECTION_PAGE_ENDPOINT, "section:huge"): (
                huge_items,
                (
                    {
                        "id": "shell:huge",
                        "kind": "timeline",
                        "item_ids": [item["id"] for item in huge_items],
                    },
                ),
            )
        },
        locations={},
        search_results=(),
    )
    bounded = StoryMapReader(source).section_page(
        map_revision=7, section_id="section:huge", limit=2
    )
    assert bounded["rendered_item_count"] == 1
    assert bounded["next_cursor"]
    assert bounded["shells"]
    assert _json_size(bounded) <= MAX_SERIALIZED_BYTES

    no_shell_source = MemoryStoryMapReaderSource(
        _reader_snapshot(7, manifest, status),
        resources={(SECTION_PAGE_ENDPOINT, "section:no-shell"): ((huge_items[0],), ())},
        locations={},
        search_results=(),
    )
    with pytest.raises(StoryMapReaderDataError, match="requires a shell"):
        StoryMapReader(no_shell_source).section_page(
            map_revision=7, section_id="section:no-shell", limit=1
        )


def test_cursors_fail_closed_for_tampering_foreign_binding_and_stale_revision() -> None:
    reader = _small_reader()
    first = reader.section_page(
        map_revision=7, section_id="section:prologue", limit=30
    )
    cursor = first["next_cursor"]
    assert isinstance(cursor, str)
    tampered = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
    with pytest.raises(InvalidStoryMapCursorError):
        reader.section_page(
            map_revision=7,
            section_id="section:prologue",
            limit=30,
            cursor=tampered,
        )
    with pytest.raises(InvalidStoryMapCursorError):
        reader.section_page(
            map_revision=7,
            section_id="section:prologue",
            limit=29,
            cursor=cursor,
        )
    with pytest.raises(InvalidStoryMapCursorError):
        reader.branch_page(
            map_revision=7,
            branch_id="choice:first",
            limit=30,
            cursor=cursor,
        )

    revised = _small_reader(revision=8)
    with pytest.raises(StaleMapRevisionError) as raised:
        revised.section_page(
            map_revision=8,
            section_id="section:prologue",
            limit=30,
            cursor=cursor,
        )
    assert raised.value.current_revision == 8
    with pytest.raises(StaleMapRevisionError) as explicit:
        revised.section_page(map_revision=7, section_id="section:prologue")
    assert explicit.value.current_revision == 8


def test_unloaded_locate_search_and_v2_resource_bound_cursor_replay() -> None:
    reader = _small_reader()
    section_location = reader.locate(map_revision=7, selection_id="event:30")
    assert section_location["location"]["branch_id"] is None
    section_cursor = section_location["location"]["page_cursor"]
    section_page = reader.section_page(
        map_revision=7,
        section_id=section_location["location"]["section_id"],
        cursor=section_cursor,
    )
    assert section_page["items"][0]["id"] == "event:30"

    branch_location = reader.locate(map_revision=7, selection_id="arm:240")
    assert branch_location["location"]["branch_id"] == "choice:first"
    branch_cursor = branch_location["location"]["page_cursor"]
    branch_page = reader.branch_page(
        map_revision=7,
        branch_id=branch_location["location"]["branch_id"],
        cursor=branch_cursor,
    )
    assert branch_page["items"][0]["id"] == "arm:240"
    with pytest.raises(InvalidStoryMapCursorError):
        reader.section_page(
            map_revision=7,
            section_id=branch_location["location"]["section_id"],
            cursor=branch_cursor,
        )

    search = reader.search(map_revision=7, query="without hydrating", limit=2)
    assert [result["selection_id"] for result in search["results"]] == [
        "event:30",
        "arm:240",
    ]
    assert all(result["is_loaded"] is False for result in search["results"])


@pytest.mark.parametrize("endpoint", (PATH_PAGE_ENDPOINT, DETAIL_PAGE_ENDPOINT))
def test_existing_path_and_detail_projection_is_paged_without_rebuilding(endpoint: str) -> None:
    reader = _small_reader()
    calls: list[tuple[int, int]] = []
    all_items = tuple(
        {"id": f"{endpoint}:item:{index}", "kind": endpoint, "order": index}
        for index in range(241)
    )
    shell = {
        "id": f"shell:{endpoint}",
        "kind": endpoint,
        "item_ids": [item["id"] for item in all_items],
    }

    def supplier(offset: int, limit: int) -> ReaderSlice:
        calls.append((offset, limit))
        items = all_items[offset : offset + limit]
        next_offset = offset + len(items) if offset + len(items) < len(all_items) else None
        return ReaderSlice(items, (shell,), next_offset)

    first = reader.projection_page(
        map_revision=7,
        endpoint=endpoint,
        selection_id="event:30",
        limit=240,
        cursor=None,
        supplier=supplier,
    )
    second = reader.projection_page(
        map_revision=7,
        endpoint=endpoint,
        selection_id="event:30",
        limit=240,
        cursor=first["next_cursor"],
        supplier=supplier,
    )
    assert calls == [(0, 240), (240, 240)]
    assert first["rendered_item_count"] == 240
    assert second["rendered_item_count"] == 1


def test_phase03_compatibility_reader_is_read_only_and_provider_free(tmp_path: Path) -> None:
    core = StoryMapCore(
        "story-map-v2-core-v1",
        "phase03-reader-fixture",
        ChunkStatus.COMPLETE,
        (),
        "Phase 03 story",
        "A preserved single-core record.",
    )
    identity = StoryMapProjectIdentity(
        PROJECT_SCHEMA,
        core.schema,
        canonical_hash(asdict(core)),
        core.source_identity,
        "a" * 64,
        "b" * 64,
        ("game/story.rpy",),
    )
    envelope = StoryMapProjectEnvelope(
        PROJECT_SCHEMA,
        identity,
        core,
        None,
        "2026-07-26T20:00:00+00:00",
    )
    source_binding = SourceBinding("game/story.rpy", 1, 2)
    navigation = NavigationBinding(
        "event:phase03",
        "scene",
        "scene:phase03",
        "scene_detail",
        "scene:phase03",
        source_binding,
    )
    event = StoryEventReadModel(
        "event:phase03",
        "Preserved event",
        "Readable through the additive compatibility surface.",
        (),
        Reachability.REACHABLE,
        (),
        navigation,
        (),
    )
    page = StoryMapReadModel(
        "story-map-v2-page-v1",
        "fallback",
        None,
        "Phase 03 story",
        "A preserved single-core record.",
        (),
        (
            StorySectionReadModel(
                "section-1",
                "Phase 03 story",
                "Compatibility section.",
                (event,),
            ),
        ),
    )
    preserved = asdict(envelope)
    project_path = tmp_path / "phase03-compatibility.rsmproj"
    with Project.create(project_path) as project:
        reader = StoryMapReader(
            phase03_compatibility_source(
                envelope,
                page,
                project.story_map_v2_repository(),
            )
        )
        manifest = reader.manifest()
        assert manifest["freshness"] == "phase03_compatible"
        assert manifest["counts"] == {
            "sections": 1,
            "events": 1,
            "choices": 0,
            "arms": 0,
            "endings": 0,
        }
        assert reader.locate(
            map_revision=0, selection_id="event:phase03"
        )["location"]["branch_id"] is None
        assert reader.search(
            map_revision=0, query="additive compatibility"
        )["results"][0]["is_loaded"] is False
        reader.save_view_state(
            map_revision=0,
            view_key="route-map",
            state={"selection_id": "event:phase03", "hide_new": True},
        )
    assert asdict(envelope) == preserved


def test_durable_indexed_source_and_repository_primitives_survive_reopen(
    tmp_path: Path,
) -> None:
    project_path = _durable_project(tmp_path)
    with Project.open(project_path) as project:
        repository = project.story_map_v2_repository()
        generation = repository.load_generation("generation-reader")
        assert generation is not None
        assert [page.page_ordinal for page in repository.list_section_pages(
            generation.generation_id, "section:prologue", limit=1
        )] == [0]
        assert repository.count_selections(generation.generation_id) == 3
        assert len(repository.list_selections(generation.generation_id, limit=2)) == 2

        reader = StoryMapReader(DurableStoryMapReaderSource(repository))
        manifest = reader.manifest()
        assert manifest["map_revision"] == 1
        assert manifest["new_facts"]
        assert reader.section_page(
            map_revision=1, section_id="section:prologue"
        )["items"][0]["id"] == "event:intro"
        located = reader.locate(map_revision=1, selection_id="arm:a")
        assert located["location"]["branch_id"] == "choice:first"
        found = reader.search(map_revision=1, query="unloaded")
        assert {item["selection_id"] for item in found["results"]} == {
            "event:intro",
            "arm:a",
        }
        reader.save_view_state(
            map_revision=1,
            view_key="route-map",
            state={"selection_id": "arm:a", "hide_new": True},
        )
    with Project.open(project_path) as reopened:
        reader = StoryMapReader(DurableStoryMapReaderSource(
            reopened.story_map_v2_repository()
        ))
        assert reader.view_state(map_revision=1, view_key="route-map")["state"] == {
            "selection_id": "arm:a",
            "hide_new": True,
        }


def test_durable_status_is_honest_without_an_accepted_workflow_projector(
    tmp_path: Path,
) -> None:
    project_path = _durable_project(tmp_path)
    with Project.open(project_path) as project:
        status = StoryMapReader(
            DurableStoryMapReaderSource(project.story_map_v2_repository())
        ).status()
    assert status["run_id"] == "run-reader"
    assert status["state"] == "unavailable"
    assert status["progress"] == {
        "completed_jobs": 0,
        "total_jobs": 0,
        "failed_jobs": 0,
        "indeterminate_jobs": 0,
    }
    assert status["actions"] == {
        "can_cancel": False,
        "can_resume": False,
        "retry_approval_required": False,
    }


def test_oversized_storage_page_is_rejected_and_locator_replays_split_target(
    tmp_path: Path,
) -> None:
    huge_items = tuple(
        {
            "id": f"event:huge:{index}",
            "kind": "event",
            "order": index,
            "title": f"Huge {index}",
            "summary": "x" * 600_000,
            "selection_id": f"event:huge:{index}",
        }
        for index in range(2)
    )
    combined_shell = {
        "id": "shell:huge",
        "kind": "timeline",
        "item_ids": [item["id"] for item in huge_items],
    }
    with pytest.raises(ValueError, match="serialized page cap"):
        reader_storage_page(
            endpoint=SECTION_PAGE_ENDPOINT,
            resource_id="section:huge",
            resource_offset=0,
            items=huge_items,
            shells=(combined_shell,),
        )

    pages = tuple(
        (
            "section:huge",
            index,
            reader_storage_page(
                endpoint=SECTION_PAGE_ENDPOINT,
                resource_id="section:huge",
                resource_offset=index,
                items=(item,),
                shells=(
                    {
                        "id": "shell:huge",
                        "kind": "timeline",
                        "item_ids": [item["id"]],
                    },
                ),
            ),
        )
        for index, item in enumerate(huge_items)
    )
    project_path = tmp_path / "split-reader.rsmproj"
    with Project.create(project_path) as project:
        _publish_reader_generation(
            project,
            suffix="split",
            authority=AUTHORITY,
            pages=pages,
            selections=(
                SelectionIndexRecord(
                    "generation-split",
                    "event:huge:0",
                    "section:huge",
                    0,
                    0,
                    "event",
                ),
                SelectionIndexRecord(
                    "generation-split",
                    "event:huge:1",
                    "section:huge",
                    1,
                    0,
                    "event",
                ),
            ),
        )
        reader = StoryMapReader(
            DurableStoryMapReaderSource(project.story_map_v2_repository())
        )
        located = reader.locate(map_revision=1, selection_id="event:huge:1")
        replayed = reader.section_page(
            map_revision=1,
            section_id="section:huge",
            cursor=located["location"]["page_cursor"],
        )
    assert located["location"]["page_cursor"]
    assert [item["id"] for item in replayed["items"]] == ["event:huge:1"]
    assert _json_size(replayed) <= MAX_SERIALIZED_BYTES


def test_old_cursor_is_stale_across_authority_change_but_tampering_is_invalid(
    tmp_path: Path,
) -> None:
    def pages(label: str) -> tuple[tuple[str, int, Mapping[str, object]], ...]:
        items = tuple(
            {
                "id": f"event:{label}:{index:02d}",
                "kind": "event",
                "order": index,
                "title": f"{label} {index}",
                "selection_id": f"event:{label}:{index:02d}",
            }
            for index in range(31)
        )
        return tuple(
            (
                "section:cursor",
                ordinal,
                reader_storage_page(
                    endpoint=SECTION_PAGE_ENDPOINT,
                    resource_id="section:cursor",
                    resource_offset=offset,
                    items=items[offset : offset + 30],
                    shells=(
                        {
                            "id": "shell:cursor",
                            "kind": "timeline",
                            "item_ids": [item["id"] for item in items[offset : offset + 30]],
                        },
                    ),
                ),
            )
            for ordinal, offset in enumerate((0, 30))
        )

    project_path = tmp_path / "cursor-reader.rsmproj"
    with Project.create(project_path) as project:
        _publish_reader_generation(
            project,
            suffix="cursor-a",
            authority=hashlib.sha256(b"authority-a").hexdigest(),
            pages=pages("a"),
        )
        source = DurableStoryMapReaderSource(project.story_map_v2_repository())
        first = StoryMapReader(source).section_page(
            map_revision=1,
            section_id="section:cursor",
            limit=30,
        )
        cursor = first["next_cursor"]
        assert isinstance(cursor, str)
        _publish_reader_generation(
            project,
            suffix="cursor-b",
            authority=hashlib.sha256(b"authority-b").hexdigest(),
            pages=pages("b"),
        )
        revised = StoryMapReader(
            DurableStoryMapReaderSource(project.story_map_v2_repository())
        )
        with pytest.raises(StaleMapRevisionError) as stale:
            revised.section_page(
                map_revision=2,
                section_id="section:cursor",
                limit=30,
                cursor=cursor,
            )
        assert stale.value.current_revision == 2
        tampered = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
        with pytest.raises(InvalidStoryMapCursorError):
            revised.section_page(
                map_revision=2,
                section_id="section:cursor",
                limit=30,
                cursor=tampered,
            )


def test_durable_first_page_decodes_only_a_bounded_page_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = tuple(
        (
            "section:thousand",
            index,
            reader_storage_page(
                endpoint=SECTION_PAGE_ENDPOINT,
                resource_id="section:thousand",
                resource_offset=index,
                items=(
                    {
                        "id": f"event:thousand:{index:04d}",
                        "kind": "event",
                        "order": index,
                        "title": f"Event {index}",
                        "selection_id": f"event:thousand:{index:04d}",
                    },
                ),
                shells=(
                    {
                        "id": "shell:thousand",
                        "kind": "timeline",
                        "item_ids": [f"event:thousand:{index:04d}"],
                    },
                ),
            ),
        )
        for index in range(1_000)
    )
    project_path = tmp_path / "thousand-reader.rsmproj"
    with Project.create(project_path) as project:
        _publish_reader_generation(
            project,
            suffix="thousand",
            authority=AUTHORITY,
            pages=pages,
        )
        repository = project.story_map_v2_repository()
        original = repository.list_section_pages
        decoded_pages = 0

        def counted(
            generation_id: str,
            section_id: str,
            *,
            start_page_ordinal: int = 0,
            limit: int = 64,
        ) -> tuple[SectionPageRecord, ...]:
            nonlocal decoded_pages
            result = original(
                generation_id,
                section_id,
                start_page_ordinal=start_page_ordinal,
                limit=limit,
            )
            decoded_pages += len(result)
            return result

        monkeypatch.setattr(repository, "list_section_pages", counted)
        page = StoryMapReader(DurableStoryMapReaderSource(repository)).section_page(
            map_revision=1,
            section_id="section:thousand",
            limit=30,
        )
    assert page["rendered_item_count"] == 30
    assert page["next_cursor"]
    assert decoded_pages <= 32


def test_durable_view_state_write_is_revision_and_generation_cas(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "view-state-cas.rsmproj"
    first_page = reader_storage_page(
        endpoint=SECTION_PAGE_ENDPOINT,
        resource_id="section:view",
        resource_offset=0,
        items=({"id": "event:view", "kind": "event", "selection_id": "event:view"},),
        shells=({"id": "shell:view", "kind": "timeline", "item_ids": ["event:view"]},),
    )
    with Project.create(project_path) as project:
        _publish_reader_generation(
            project,
            suffix="view-a",
            authority=hashlib.sha256(b"view-a").hexdigest(),
            pages=(("section:view", 0, first_page),),
        )
        repository = project.story_map_v2_repository()
        old_source = DurableStoryMapReaderSource(repository)
        old_snapshot = old_source.snapshot()
        assert old_snapshot is not None
        old_source.save_view_state(
            old_snapshot,
            "route-map",
            {"selection_id": "event:view", "focus_id": "old", "hide_new": False},
        )
        _publish_reader_generation(
            project,
            suffix="view-b",
            authority=hashlib.sha256(b"view-b").hexdigest(),
            pages=(("section:view", 0, first_page),),
        )
        new_source = DurableStoryMapReaderSource(repository)
        new_snapshot = new_source.snapshot()
        assert new_snapshot is not None
        new_source.save_view_state(
            new_snapshot,
            "route-map",
            {"selection_id": "event:view", "focus_id": "new", "hide_new": True},
        )
        with pytest.raises(StaleMapRevisionError) as stale:
            old_source.save_view_state(
                old_snapshot,
                "route-map",
                {"selection_id": "event:view", "focus_id": "stale", "hide_new": False},
            )
        retained = repository.load_view_state("route-map")
    assert stale.value.current_revision == 2
    assert retained is not None
    assert retained.map_revision == 2
    assert retained.state == {
        "selection_id": "event:view",
        "focus_id": "new",
        "hide_new": True,
    }


def test_durable_only_selection_uses_indexed_path_detail_and_source(
    tmp_path: Path,
) -> None:
    from test_story_map_v2_phase03_track_c import _project as create_phase03_project

    _source, project_path, core = create_phase03_project(tmp_path)
    selection_id = "event:durable-only"
    with Project.open(project_path) as project:
        authority = load_m12_authority(project)
        stored = load_story_map_v2_for_current_project(project)
        assert stored is not None
        page = project_story_map(core, stored.synthesis)
        navigator = StoryMapNavigator(
            authority,
            M12RouteService(project),
            core,
            page,
        )
        phase03_selection = page.sections[0].events[0].selection_id
        binding = navigator.binding(phase03_selection)
        detail_kind, detail_id = navigator.detail_service_target(phase03_selection)
        source_navigation = navigator.source_navigation(phase03_selection)
        assert source_navigation["status"] == "available"
        item = {
            "id": selection_id,
            "kind": "event",
            "title": "Durable-only selection",
            "selection_id": selection_id,
            "_reader_navigation": {
                "destination_kind": binding.destination_kind,
                "target_id": binding.target_id,
                "detail_service_kind": detail_kind,
                "detail_service_id": detail_id,
                "evidence_id": source_navigation["evidence_id"],
                "relative_path": source_navigation["path"],
                "start_line": source_navigation["start_line"],
                "end_line": source_navigation["end_line"],
                "line_basis": source_navigation["line_basis"],
                "effects": [],
            },
        }
        payload = reader_storage_page(
            endpoint=SECTION_PAGE_ENDPOINT,
            resource_id="section:durable-only",
            resource_offset=0,
            items=(item,),
            shells=(
                {
                    "id": "shell:durable-only",
                    "kind": "timeline",
                    "item_ids": [selection_id],
                },
            ),
        )
        _publish_reader_generation(
            project,
            suffix="durable-nav",
            authority=AUTHORITY,
            pages=(("section:durable-only", 0, payload),),
            selections=(
                SelectionIndexRecord(
                    "generation-durable-nav",
                    selection_id,
                    "section:durable-only",
                    0,
                    0,
                    "event",
                ),
            ),
        )

    provider_calls: list[str] = []
    api = _api(tmp_path, project_path, provider_calls)
    try:
        section_page = api.dispatch(
            "POST",
            STORY_MAP_V2_READER_API_ROUTES["section_page"],
            {"map_revision": 1, "section_id": "section:durable-only"},
        )
        path_page = api.dispatch(
            "POST",
            STORY_MAP_V2_READER_API_ROUTES["path_page"],
            {"map_revision": 1, "selection_id": selection_id, "limit": 240},
        )
        detail_page = api.dispatch(
            "POST",
            STORY_MAP_V2_READER_API_ROUTES["detail_page"],
            {"map_revision": 1, "selection_id": selection_id, "limit": 240},
        )
    finally:
        api.close()

    assert "_reader_navigation" not in section_page["items"][0]
    for response in (path_page, detail_page):
        assert response["map_revision"] == 1
        assert response["resource_id"] == selection_id
        assert 1 <= response["rendered_item_count"] <= MAX_RENDERED_ITEMS
        assert _json_size(response) <= MAX_SERIALIZED_BYTES
    assert any(item["kind"] == "evidence" for item in detail_page["items"])
    assert provider_calls == []


def test_api_and_http_stale_transport_are_provider_free(tmp_path: Path) -> None:
    project_path = _durable_project(tmp_path)
    provider_calls: list[str] = []
    api = _api(tmp_path, project_path, provider_calls)
    manifest = api.dispatch("POST", STORY_MAP_V2_READER_API_ROUTES["manifest"], {})
    found = api.dispatch(
        "POST",
        STORY_MAP_V2_READER_API_ROUTES["search"],
        {"map_revision": 1, "query": "unloaded", "limit": 50},
    )
    assert manifest["schema"] == found["schema"] == READER_SCHEMA
    assert provider_calls == []

    static_root = tmp_path / "static"
    static_root.mkdir()
    server = LocalWebServer(
        "127.0.0.1",
        0,
        api,
        static_root=static_root,
        security=SessionSecurity("session-secret", "csrf-secret"),
    )
    thread = start_in_thread(server)
    try:
        status, body = _post_json(
            server,
            STORY_MAP_V2_READER_API_ROUTES["section_page"],
            {"map_revision": 0, "section_id": "section:prologue", "limit": 30},
        )
    finally:
        server.close_service()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert status == 409
    assert body == {
        "error": {
            "code": "stale_map_revision",
            "message": "The requested map revision is stale.",
        },
        "map_revision": 1,
    }
    assert provider_calls == []


def test_phase03_api_path_and_detail_pages_remain_compatible(tmp_path: Path) -> None:
    from test_story_map_v2_phase03_track_c import _project as create_phase03_project

    _source, project_path, _core = create_phase03_project(tmp_path)
    provider_calls: list[str] = []
    api = _api(tmp_path, project_path, provider_calls)
    try:
        manifest = api.dispatch(
            "POST", STORY_MAP_V2_READER_API_ROUTES["manifest"], {}
        )
        old_page = api.dispatch("POST", STORY_MAP_V2_API_ROUTES["map"], {})
        selection_id = old_page["sections"][0]["events"][0]["selection_id"]
        path_page = api.dispatch(
            "POST",
            STORY_MAP_V2_READER_API_ROUTES["path_page"],
            {"map_revision": 0, "selection_id": selection_id, "limit": 240},
        )
        detail_page = api.dispatch(
            "POST",
            STORY_MAP_V2_READER_API_ROUTES["detail_page"],
            {"map_revision": 0, "selection_id": selection_id, "limit": 240},
        )
    finally:
        api.close()

    assert manifest["freshness"] == "phase03_compatible"
    for response in (path_page, detail_page):
        assert response["schema"] == READER_SCHEMA
        assert response["map_revision"] == 0
        assert response["resource_id"] == selection_id
        assert response["rendered_item_count"] <= MAX_RENDERED_ITEMS
        assert _json_size(response) <= MAX_SERIALIZED_BYTES
    assert provider_calls == []


def test_large_fixture_meets_exact_scale_shape_and_reader_acceptance() -> None:
    spec = json.loads(SCALE_FIXTURE.read_text(encoding="utf-8"))
    fixture = _large_fixture()
    manifest = fixture.reader.manifest()
    counts = manifest["counts"]
    assert {key: counts[key] for key in spec["counts"]} == spec["counts"]
    assert len(manifest["sections"]) == 256
    assert sum(
        section["route_id"] == "route:persistent" for section in manifest["sections"]
    ) == 50

    choices = [
        item
        for (endpoint, _resource), (items, _shells) in fixture.resources.items()
        if endpoint == SECTION_PAGE_ENDPOINT
        for item in items
        if item["kind"] == "choice"
    ]
    arms = [
        item
        for (endpoint, _resource), (items, _shells) in fixture.resources.items()
        if endpoint == BRANCH_PAGE_ENDPOINT
        for item in items
    ]
    assert len(choices) == 5_000
    assert max(item["depth"] for item in choices) == 8
    assert len(arms) == 20_000
    assert sum(item["rejoin_selection_id"] is not None for item in arms) == 2_000
    assert fixture.resources[(BRANCH_PAGE_ENDPOINT, "choice:00000")][0][0][
        "rejoin_selection_id"
    ] == "event:00200"
    assert fixture.locations["event:04999"].section_id == "section:255"

    oversized = fixture.reader.branch_page(
        map_revision=7, branch_id="choice:00000", limit=240
    )
    assert oversized["rendered_item_count"] == 240
    assert oversized["shells"]
    assert oversized["next_cursor"]
    assert _json_size(oversized) <= MAX_SERIALIZED_BYTES
    final = fixture.reader.locate(map_revision=7, selection_id="event:04999")
    final_page = fixture.reader.section_page(
        map_revision=7,
        section_id=final["location"]["section_id"],
        cursor=final["location"]["page_cursor"],
    )
    assert any(item["id"] == "event:04999" for item in final_page["items"])
    search = fixture.reader.search(map_revision=7, query="Event 04999", limit=50)
    assert search["results"][0]["selection_id"] == "event:04999"
    assert search == fixture.reader.search(map_revision=7, query="Event 04999", limit=50)
