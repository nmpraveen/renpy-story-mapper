"""Backend adapters and typed route dispatch for the local browser shell."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path
from typing import Final, Protocol, cast

from renpy_story_mapper import storage
from renpy_story_mapper.ai_story_map import AIStoryMapQueryResult, query_ai_story_map
from renpy_story_mapper.analysis_phases import ANALYSIS_STATE_SCHEMA_VERSION
from renpy_story_mapper.bounded_window import (
    MAX_WINDOW_BOUNDARY_EDGES,
    MAX_WINDOW_EVIDENCE,
    MAX_WINDOW_FACTS,
    MAX_WINDOW_INTERNAL_EDGES,
    MAX_WINDOW_NODES,
    BoundedWindowError,
    build_bounded_narrative_window,
)
from renpy_story_mapper.canonical_graph_contract import CANONICAL_GRAPH_SCHEMA
from renpy_story_mapper.inspection_projection import INSPECTION_PROJECTION_SCHEMA
from renpy_story_mapper.m07_model import Assembly, CheckpointStatus
from renpy_story_mapper.m07_workflow import (
    M07WorkflowService,
    PreparedRunError,
    ProviderFactory,
    validate_persisted_assembly,
)
from renpy_story_mapper.m11_persistence import M11Availability
from renpy_story_mapper.m11_scene_projection import stored_scene_model_mapping
from renpy_story_mapper.organization.contracts import (
    M05_CLOUD_MODEL,
    M05_REASONING_PROFILE,
    OrganizationProvider,
)
from renpy_story_mapper.organization.errors import InvalidProviderOutputError
from renpy_story_mapper.organization.parallel import BudgetPolicy, ProgressSnapshot, RouteScope
from renpy_story_mapper.presentation import (
    MAX_RESULTS,
    PresentationLevel,
    PresentationNode,
    PresentationRequest,
    PresentationService,
)
from renpy_story_mapper.project import (
    Project,
    ProjectCancelledError,
    create_ingested_project,
    open_project,
    refresh_ingested_project,
)
from renpy_story_mapper.web.contracts import (
    M07_API_ROUTES,
    M07_PREPARE_REQUEST_FIELDS,
    M07_START_REQUEST_FIELDS,
    M07_WINDOW_RESOLVE_REQUEST_FIELDS,
    M08_AI_STORY_DETAIL_REQUEST_FIELDS,
    M08_AI_STORY_MAP_REQUEST_FIELDS,
    M08_API_ROUTES,
    M08_COMPARISON_REQUEST_FIELDS,
    M10_API_ROUTES,
    M10_DETAIL_REQUEST_FIELDS,
    M10_INSPECTION_MAP_REQUEST_FIELDS,
    M11_API_ROUTES,
    M11_DETAIL_REQUEST_FIELDS,
    M11_SCENE_MAP_REQUEST_FIELDS,
    ApiErrorBody,
    JsonValue,
    SelectionResult,
    TaskStatus,
    boolean,
    bounded_int,
    exact_fields,
    json_value,
    object_tuple,
    object_value,
    optional_bounded_int,
    optional_string,
    require_string,
    required_string_tuple,
    string_tuple,
)
from renpy_story_mapper.web.inspection_api import inspection_detail, inspection_page
from renpy_story_mapper.web.scene_api import scene_detail, scene_page
from renpy_story_mapper.web.state import UserStateStore

MAX_M07_SELECTION_ITEMS: Final = 64
M07_BUDGET_FIELDS: Final = (
    "soft_seconds",
    "hard_seconds",
    "soft_tokens",
    "hard_tokens",
    "hard_calls",
)
M07_MODEL_FIELDS: Final = ("id", "reasoning", "fast_mode")
M07_EXPECTED_WINDOW_FIELDS: Final = (
    "id",
    "node_ids",
    "internal_edge_ids",
    "boundary_node_ids",
    "boundary_edge_ids",
    "evidence_ids",
    "fact_ids",
    "input_hash",
    "authority_hash",
)
M07_MODEL_IDENTITY: Final[dict[str, JsonValue]] = {
    "id": M05_CLOUD_MODEL,
    "reasoning": M05_REASONING_PROFILE,
    "fast_mode": False,
}
M07_DEFAULT_BUDGETS: Final[dict[str, JsonValue]] = {
    "soft_seconds": 600,
    "hard_seconds": 900,
    "soft_tokens": 1_500_000,
    "hard_tokens": 2_000_000,
    "hard_calls": 48,
}
LEGACY_ORGANIZATION_ROUTES: Final = frozenset(
    {
        "/api/v1/organization/consent",
        "/api/v1/organization/draft",
        "/api/v1/organization/review",
        "/api/v1/organization/apply",
        "/api/v1/organization/discard",
    }
)


class ApiProblem(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class DialogAdapter(Protocol):
    def choose_source(self, kind: str) -> Path | None: ...

    def choose_open_project(self) -> Path | None: ...

    def choose_save_project(self) -> Path | None: ...


class SelectionRegistry:
    """Per-launch opaque references; paths are never serialized to the browser."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[str, Path]] = {}
        self._lock = threading.Lock()

    def add(self, kind: str, path: Path) -> SelectionResult:
        identifier = uuid.uuid4().hex
        with self._lock:
            self._items[identifier] = (kind, path.resolve())
        return SelectionResult(identifier, kind, path.name)

    def require(self, identifier: str, kinds: set[str]) -> Path:
        with self._lock:
            item = self._items.get(identifier)
        if item is None or item[0] not in kinds:
            raise ApiProblem(404, "selection_not_found", "The selected local item is unavailable.")
        return item[1]


class ProjectApi:
    """One-session project facade with serialized cancellable lifecycle work."""

    def __init__(
        self,
        dialogs: DialogAdapter,
        *,
        state_store: UserStateStore | None = None,
        m07_provider_factory: ProviderFactory | None = None,
    ) -> None:
        self._dialogs = dialogs
        self._selections = SelectionRegistry()
        self._project_path: Path | None = None
        self._source_path: Path | None = None
        self._task: TaskStatus | None = None
        self._cancel_event: threading.Event | None = None
        self._future: Future[None] | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="story-mapper-web")
        self._lock = threading.Lock()
        self._classification_lock = threading.Lock()
        self._unresolved_cache: tuple[Path, str, frozenset[str], frozenset[str]] | None = None
        self._state_store = state_store or UserStateStore()
        self._m07_provider_factory = m07_provider_factory or _default_m07_provider_factory
        self._m07_service: M07WorkflowService | None = None
        self._m07_service_path: Path | None = None
        self._m07_consent_snapshot: dict[str, JsonValue] | None = None
        self._m07_start_binding: dict[str, JsonValue] | None = None
        self._m07_run_id: str | None = None
        self._m07_run_baseline: dict[str, int] | None = None
        self._m07_run_progress: ProgressSnapshot | None = None
        self._m07_run_started_at: float | None = None
        self._m07_run_elapsed_seconds: float | None = None
        self._m07_run_cache_hits = 0
        self._m07_run_selected_ids: tuple[str, ...] = ()

    def close(self) -> None:
        self.cancel()
        future = self._future
        if future is not None:
            with suppress(Exception):
                future.result(timeout=5)
        self._executor.shutdown(wait=True, cancel_futures=True)

    def cancel(self) -> None:
        with self._lock:
            if self._cancel_event is not None:
                self._cancel_event.set()

    def dispatch(self, method: str, path: str, body: dict[str, JsonValue]) -> JsonValue:
        if method == "GET" and path == "/api/v1/bootstrap":
            state = self._state()
            assert isinstance(state, dict)
            return {
                "api_version": "v1",
                **state,
                "recent_projects": self._recent_projects(),
                "settings": self._state_store.settings(),
                "routes": {
                    "recent": "/api/v1/recent",
                    "pick": "/api/v1/native-picker",
                    "open": "/api/v1/projects/open",
                    "create": "/api/v1/projects/create",
                    "refresh": "/api/v1/projects/refresh",
                    "progress": "/api/v1/analysis/progress",
                    "cancel": "/api/v1/analysis/cancel",
                    "view": "/api/v1/story/view",
                    "search": "/api/v1/story/search",
                    "evidence": "/api/v1/story/evidence",
                    "facts": "/api/v1/story/facts",
                    "settings": "/api/v1/settings",
                    "diagnostics": "/api/v1/diagnostics",
                    "shutdown": "/api/v1/shutdown",
                    "m07": dict(M07_API_ROUTES),
                    "m08": dict(M08_API_ROUTES),
                    "m10": dict(M10_API_ROUTES),
                    "m11": dict(M11_API_ROUTES),
                },
            }
        if path in LEGACY_ORGANIZATION_ROUTES:
            raise ApiProblem(404, "not_found", "The requested API endpoint does not exist.")
        if method == "GET" and path == "/api/v1/recent":
            return {"recent_projects": self._recent_projects()}
        if method == "GET" and path == "/api/v1/analysis/progress":
            with self._lock:
                task = self._task
            return json_value(task) if task is not None else {"state": "idle", "percent": 0}
        if method == "POST" and path == "/api/v1/native-picker":
            kind = require_string(body, "kind", maximum=32)
            if kind in {"folder", "archive", "source"}:
                return self._select("source", self._dialogs.choose_source(kind))
            if kind == "project":
                return self._select("project_open", self._dialogs.choose_open_project())
            if kind == "project_save":
                return self._select("project_save", self._dialogs.choose_save_project())
            raise ValueError("unsupported picker kind")
        if method == "POST" and path == "/api/v1/projects/open":
            selected = self._selections.require(
                require_string(body, "selection_id"), {"project_open"}
            )
            return self._start("open", lambda cancelled: self._open(selected, cancelled))
        if method == "POST" and path == "/api/v1/projects/create":
            source = self._selections.require(
                require_string(body, "source_selection_id"), {"source"}
            )
            project = self._selections.require(
                require_string(body, "project_selection_id"), {"project_save"}
            )
            return self._start("create", lambda cancelled: self._create(project, source, cancelled))
        if method == "POST" and path == "/api/v1/projects/refresh":
            return self._start("refresh", self._refresh)
        if method == "POST" and path == "/api/v1/analysis/cancel":
            self.cancel()
            return {"state": "cancelling"}
        if method == "POST" and path == M08_API_ROUTES["ai_story_map"]:
            exact_fields(body, allowed=M08_AI_STORY_MAP_REQUEST_FIELDS)
            return json_value(self._m08_ai_story_page(body))
        if method == "POST" and path == M08_API_ROUTES["ai_story_detail"]:
            exact_fields(
                body,
                allowed=M08_AI_STORY_DETAIL_REQUEST_FIELDS,
                required=("element_id",),
            )
            return json_value(self._m08_ai_story_detail(body))
        if method == "POST" and path == M08_API_ROUTES["comparison"]:
            exact_fields(body, allowed=M08_COMPARISON_REQUEST_FIELDS)
            return json_value(self._m08_comparison(body))
        if method == "POST" and path == M10_API_ROUTES["inspection_map"]:
            exact_fields(body, allowed=M10_INSPECTION_MAP_REQUEST_FIELDS)
            projection, canonical, analysis_state, projection_reason = self._m10_payloads()
            return json_value(
                inspection_page(
                    projection,
                    canonical,
                    analysis_state,
                    view=require_string(body, "view", maximum=16),
                    offset=bounded_int(
                        body, "offset", default=0, minimum=0, maximum=2_000_000
                    ),
                    limit=bounded_int(body, "limit", default=30, minimum=1, maximum=30),
                    edge_offset=bounded_int(
                        body, "edge_offset", default=0, minimum=0, maximum=2_000_000
                    ),
                    edge_limit=bounded_int(
                        body, "edge_limit", default=180, minimum=1, maximum=180
                    ),
                    query=optional_string(body, "query", maximum=256),
                    focus=optional_string(body, "focus", maximum=512),
                    projection_unavailable_reason=projection_reason,
                )
            )
        if method == "POST" and path == M10_API_ROUTES["detail"]:
            exact_fields(
                body,
                allowed=M10_DETAIL_REQUEST_FIELDS,
                required=M10_DETAIL_REQUEST_FIELDS,
            )
            projection, canonical, analysis_state, projection_reason = self._m10_payloads()
            try:
                return json_value(
                    inspection_detail(
                        projection,
                        canonical,
                        analysis_state,
                        view=require_string(body, "view", maximum=16),
                        element_id=require_string(body, "element_id", maximum=512),
                        projection_unavailable_reason=projection_reason,
                    )
                )
            except KeyError as exc:
                raise ApiProblem(
                    404,
                    "m10_element_not_found",
                    "The inspection element is unavailable.",
                ) from exc
        if method == "POST" and path == M11_API_ROUTES["scene_map"]:
            exact_fields(body, allowed=M11_SCENE_MAP_REQUEST_FIELDS)
            scene_model_value, presentation, _canonical, generation, canonical_hash, reason = (
                self._m11_payloads(include_canonical=False)
            )
            page = scene_page(
                scene_model_value,
                presentation,
                current_source_generation=generation,
                current_canonical_hash=canonical_hash,
                offset=bounded_int(body, "offset", default=0, minimum=0, maximum=2_000_000),
                limit=bounded_int(body, "limit", default=30, minimum=1, maximum=30),
                relationship_offset=bounded_int(
                    body,
                    "relationship_offset",
                    default=0,
                    minimum=0,
                    maximum=2_000_000,
                ),
                relationship_limit=bounded_int(
                    body,
                    "relationship_limit",
                    default=180,
                    minimum=1,
                    maximum=180,
                ),
                query=optional_string(body, "query", maximum=256),
                focus=optional_string(body, "focus", maximum=512),
            )
            if page.get("status") == "unavailable":
                page["reason"] = reason or page.get("reason")
                page["fallback"] = {
                    "route": M10_API_ROUTES["inspection_map"],
                    "view": "simplified",
                }
            return json_value(page)
        if method == "POST" and path == M11_API_ROUTES["detail"]:
            exact_fields(
                body,
                allowed=M11_DETAIL_REQUEST_FIELDS,
                required=M11_DETAIL_REQUEST_FIELDS,
            )
            scene_model_value, presentation, canonical, generation, canonical_hash, reason = (
                self._m11_payloads(include_canonical=True)
            )
            try:
                detail = scene_detail(
                    scene_model_value,
                    presentation,
                    canonical,
                    current_source_generation=generation,
                    current_canonical_hash=canonical_hash,
                    element_id=require_string(body, "element_id", maximum=512),
                )
            except KeyError as exc:
                raise ApiProblem(
                    404,
                    "m11_element_not_found",
                    "The scene element is unavailable.",
                ) from exc
            if detail.get("status") == "unavailable":
                detail["reason"] = reason or detail.get("reason")
                detail["fallback"] = {
                    "route": M10_API_ROUTES["inspection_map"],
                    "view": "simplified",
                }
            return json_value(detail)
        if method == "POST" and path == M07_API_ROUTES["route_map"]:
            exact_fields(body, allowed=("offset", "limit", "edge_offset", "edge_limit"))
            page = self._m07_workflow().route_map(
                offset=bounded_int(body, "offset", default=0, minimum=0, maximum=2_000_000),
                limit=bounded_int(body, "limit", default=30, minimum=1, maximum=30),
                edge_offset=bounded_int(
                    body, "edge_offset", default=0, minimum=0, maximum=2_000_000
                ),
                edge_limit=bounded_int(
                    body, "edge_limit", default=180, minimum=1, maximum=180
                ),
            )
            return json_value(self._story_display_route_page(page))
        if method == "POST" and path == M07_API_ROUTES["route_search"]:
            return json_value(
                self._m07_workflow().search_route(
                    require_string(body, "query", maximum=256),
                    after=optional_string(body, "after"),
                    limit=bounded_int(body, "limit", default=30, minimum=1, maximum=30),
                )
            )
        if method == "POST" and path == M07_API_ROUTES["detail"]:
            exact_fields(body, allowed=("element_id",), required=("element_id",))
            try:
                detail = self._m07_workflow().detail(require_string(body, "element_id"))
                return json_value(self._story_display_detail(detail))
            except KeyError as exc:
                raise ApiProblem(
                    404, "m07_element_not_found", "The route-map element is unavailable."
                ) from exc
        if method == "POST" and path == M07_API_ROUTES["window_resolve"]:
            exact_fields(body, allowed=M07_WINDOW_RESOLVE_REQUEST_FIELDS)
            try:
                window = build_bounded_narrative_window(
                    self._m07_route_authority(),
                    node_ids=string_tuple(body, "node_ids", maximum_items=MAX_WINDOW_NODES),
                    entry_node_id=optional_string(body, "entry_node_id"),
                    exit_node_id=optional_string(body, "exit_node_id"),
                )
            except ValueError as exc:
                raise ApiProblem(
                    400,
                    "m07_bounded_window_invalid",
                    "The bounded narrative window selection is invalid.",
                ) from exc
            return json_value(
                {
                    "window": window.to_dict(),
                    "selection_request": window.selection_request(),
                }
            )
        if method == "GET" and path == M07_API_ROUTES["organization"]:
            with self._lock:
                task = self._task
            stage = task.stage if task is not None and task.kind == "m07_organization" else "idle"
            status_override = (
                task.state
                if task is not None
                and task.kind == "m07_organization"
                and task.state in {"running", "cancelled", "failed"}
                else None
            )
            response = self._m07_workflow().status(
                stage=stage,
                status_override=status_override,
            )
            response["refresh"] = (
                json_value(task) if task is not None and task.kind == "refresh" else None
            )
            return json_value(self._m07_browser_status(response))
        if method == "POST" and path == M07_API_ROUTES["prepare"]:
            exact_fields(body, allowed=M07_PREPARE_REQUEST_FIELDS)
            scope_ids = string_tuple(body, "scope_ids", maximum_items=MAX_M07_SELECTION_ITEMS)
            window_requests = _bounded_window_requests(body)
            if not scope_ids and not window_requests:
                raise ApiProblem(
                    400,
                    "m07_selection_required",
                    "Select at least one bounded route scope or narrative window.",
                )
            if len(scope_ids) + len(window_requests) > MAX_M07_SELECTION_ITEMS:
                raise ValueError("the selected work-unit count exceeds the API limit")
            budget = _budget_policy(body, with_finite_defaults=True)
            _validate_budget_order(budget)
            try:
                raw_prepared = self._m07_workflow().prepare(
                    scope_ids=scope_ids,
                    window_requests=window_requests,
                    budget=budget,
                )
            except BoundedWindowError as exc:
                raise ApiProblem(
                    400,
                    "m07_bounded_window_invalid",
                    "The bounded narrative window selection is invalid or stale.",
                ) from exc
            prepared_contract = self._m07_prepared_contract(raw_prepared)
            with self._lock:
                self._m07_consent_snapshot = _consent_snapshot(prepared_contract)
                self._m07_start_binding = _strict_start_binding(prepared_contract)
            return json_value(prepared_contract)
        if method == "POST" and path == M07_API_ROUTES["start"]:
            exact_fields(
                body,
                allowed=M07_START_REQUEST_FIELDS,
                required=M07_START_REQUEST_FIELDS,
            )
            workflow = self._m07_workflow()
            budget_body = object_value(body, "budgets")
            exact_fields(
                budget_body,
                allowed=M07_BUDGET_FIELDS,
                required=M07_BUDGET_FIELDS,
                name="budgets",
            )
            start_budget = _budget_policy(budget_body, with_finite_defaults=False)
            _validate_budget_order(start_budget)
            scope_ids = required_string_tuple(
                body, "scope_ids", maximum_items=MAX_M07_SELECTION_ITEMS
            )
            window_ids = required_string_tuple(
                body, "window_ids", maximum_items=MAX_M07_SELECTION_ITEMS
            )
            if not scope_ids and not window_ids:
                raise ValueError("the start selection cannot be empty")
            if len(scope_ids) + len(window_ids) > MAX_M07_SELECTION_ITEMS:
                raise ValueError("the start work-unit count exceeds the API limit")
            if len(set(scope_ids)) != len(scope_ids) or len(set(window_ids)) != len(window_ids):
                raise ValueError("start selection IDs must be unique")
            selection_hash = _sha256(body, "selection_hash")
            authority_hash = _sha256(body, "authority_hash")
            recovered_acknowledgement = _sha256(body, "recovered_source_acknowledgement")
            model = object_value(body, "model")
            exact_fields(
                model,
                allowed=M07_MODEL_FIELDS,
                required=M07_MODEL_FIELDS,
                name="model",
            )
            if model != M07_MODEL_IDENTITY:
                raise ValueError("the exact provider model identity is required")
            run_id = require_string(body, "run_id")
            confirm_cloud = boolean(body, "confirm_cloud")
            if confirm_cloud:
                self._consume_m07_start_binding(
                    {
                        "run_id": run_id,
                        "scope_ids": list(scope_ids),
                        "window_ids": list(window_ids),
                        "selection_hash": selection_hash,
                        "authority_hash": authority_hash,
                        "recovered_source_acknowledgement": recovered_acknowledgement,
                        "model": dict(model),
                        "budgets": dict(budget_body),
                    }
                )
            authorized = workflow.authorize_start(
                run_id,
                confirm_cloud=confirm_cloud,
                scope_ids=scope_ids,
                window_ids=window_ids,
                selection_hash=selection_hash,
                authority_hash=authority_hash,
                recovered_source_acknowledgement=recovered_acknowledgement,
                model=cast(dict[str, object], model),
                budget=start_budget,
            )
            self._begin_m07_run_metrics(authorized.run_id)

            def run_m07(cancelled: threading.Event) -> None:
                workflow.run_prepared(
                    authorized,
                    cancelled=cancelled.is_set,
                    progress=self._m07_progress,
                )

            try:
                started = self._start(
                    "m07_organization",
                    run_m07,
                )
            except Exception:
                self._clear_m07_run_metrics()
                raise
            response = workflow.status(stage="starting", status_override="running")
            response["run_id"] = authorized.run_id
            response["task"] = started.get("analysis") if isinstance(started, dict) else None
            return json_value(self._m07_browser_status(response))
        if method == "POST" and path == M07_API_ROUTES["cancel"]:
            self.cancel()
            # The packaged browser polls only while status is ``running``.  Keep that
            # lifecycle status until the background boundary durably reports cancellation;
            # advertising ``cancelled`` here would also enable Resume before the old task exits.
            return json_value(
                self._m07_browser_status(
                    self._m07_workflow().status(
                        stage="cancelling",
                        status_override="running",
                    )
                )
            )
        if method == "POST" and path == M07_API_ROUTES["source_acknowledge"]:
            if not boolean(body, "acknowledge"):
                raise ValueError("explicit recovered-source acknowledgement is required")
            return json_value(
                self._m07_workflow().acknowledge_recovered_sources(
                    coverage_token=require_string(body, "coverage_token")
                )
            )
        if method == "POST" and path == M07_API_ROUTES["scope_override"]:
            correction = object_value(body, "correction")
            return json_value(
                self._m07_workflow().set_override(
                    require_string(body, "scope_id"),
                    generation=require_string(body, "authority_hash"),
                    correction=correction,
                    pinned=boolean(body, "pinned"),
                )
            )
        if method == "POST" and path == M07_API_ROUTES["assembly_apply"]:
            try:
                workflow = self._m07_workflow()
                assembly_id = require_string(body, "assembly_id")
                assembly = workflow.apply(assembly_id)
            except KeyError as exc:
                raise ApiProblem(
                    404, "m07_assembly_not_found", "The assembly is unavailable."
                ) from exc
            except ValueError as exc:
                raise ApiProblem(
                    409, "m07_assembly_stale", "The assembly is stale for this route map."
                ) from exc
            response = workflow.status(stage="applied", status_override="applied")
            response["assembly_id"] = assembly_id
            response["assembly"] = assembly
            return json_value(self._m07_browser_status(response))
        if method == "POST" and path == M07_API_ROUTES["assembly_discard"]:
            workflow = self._m07_workflow()
            assembly_id = require_string(body, "assembly_id")
            try:
                assembly = workflow.discard(assembly_id)
            except KeyError as exc:
                raise ApiProblem(
                    404, "m07_assembly_not_found", "The assembly is unavailable."
                ) from exc
            except ValueError as exc:
                raise ApiProblem(
                    409, "m07_assembly_stale", "The assembly is not a current draft."
                ) from exc
            response = workflow.status(stage="discarded")
            response["discarded_assembly"] = assembly
            return json_value(self._m07_browser_status(response))
        if method == "POST" and path == "/api/v1/story/view":
            return self._presentation_view(body)
        if method == "POST" and path == "/api/v1/story/search":
            return self._presentation_search(body)
        if method == "POST" and path == "/api/v1/story/evidence":
            return self._presentation_evidence(body)
        if method == "POST" and path == "/api/v1/story/facts":
            return self._presentation_facts(body)
        if method == "PUT" and path == "/api/v1/settings":
            return {"settings": self._state_store.save_settings(body)}
        if method == "GET" and path == "/api/v1/diagnostics":
            with self._lock:
                ready = self._project_path is not None
            return {
                "version": "0.1.0",
                "project_schema": 6 if ready else None,
                "browser_api": "v1",
                "provider_requests_on_open": 0,
                "messages": ["Rendering is bounded", "No provider is invoked by project open"],
            }
        if method == "POST" and path == "/api/v1/shutdown":
            return {"state": "shutting_down"}
        raise ApiProblem(404, "not_found", "The requested API endpoint does not exist.")

    def _select(self, kind: str, path: Path | None) -> JsonValue:
        if path is None:
            return {"selection_id": None, "display_name": None}
        selection = self._selections.add(kind, path)
        return {
            "selection_id": selection.id,
            "display_name": selection.name,
            "kind": selection.kind,
        }

    def _recent_projects(self) -> list[JsonValue]:
        result: list[JsonValue] = []
        for path in self._state_store.recent_projects():
            selection = self._selections.add("project_open", path)
            result.append(
                {
                    "selection_id": selection.id,
                    "name": path.stem,
                    "source_type": "Project",
                    "organization": "Saved project",
                    "deterministic": True,
                }
            )
        return result

    def _state(self) -> JsonValue:
        with self._lock:
            task = self._task
            project = self._project_path
        return {
            "project": None if project is None else {"name": project.stem, "ready": True},
            "task": json_value(task),
            "limits": {"nodes": 80, "edges": 120, "items": 240, "results": MAX_RESULTS},
        }

    def _start(self, kind: str, operation: Callable[[threading.Event], None]) -> JsonValue:
        with self._lock:
            if self._future is not None and not self._future.done():
                raise ApiProblem(409, "operation_busy", "Another project operation is in progress.")
            task_id = uuid.uuid4().hex
            cancelled = threading.Event()
            self._cancel_event = cancelled
            self._task = TaskStatus(task_id, kind, "running", "starting", 0, True)
            self._future = self._executor.submit(self._run, task_id, kind, operation, cancelled)
        with self._lock:
            task = self._task
        return {
            "project": {"name": "Opening", "organization": "Technical organization"},
            "analysis": json_value(task),
        }

    def _run(
        self,
        task_id: str,
        kind: str,
        operation: Callable[[threading.Event], None],
        cancelled: threading.Event,
    ) -> None:
        try:
            self._progress(task_id, kind, "working", 10)
            operation(cancelled)
            if cancelled.is_set():
                raise ProjectCancelledError("cancelled")
            self._progress(task_id, kind, "complete", 100, state="completed", cancellable=False)
        except ProjectCancelledError:
            self._progress(task_id, kind, "cancelled", 100, state="cancelled", cancellable=False)
        except Exception:
            if cancelled.is_set():
                self._progress(
                    task_id,
                    kind,
                    "cancelled",
                    100,
                    state="cancelled",
                    cancellable=False,
                )
                return
            error = ApiErrorBody("project_operation_failed", "The project operation failed safely.")
            self._progress(
                task_id, kind, "failed", 100, state="failed", cancellable=False, error=error
            )
        finally:
            with self._lock:
                self._cancel_event = None

    def _progress(
        self,
        task_id: str,
        kind: str,
        stage: str,
        percent: int,
        *,
        state: str = "running",
        cancellable: bool = True,
        error: ApiErrorBody | None = None,
    ) -> None:
        with self._lock:
            self._task = TaskStatus(task_id, kind, state, stage, percent, cancellable, error)
            if (
                kind == "m07_organization"
                and state != "running"
                and self._m07_run_started_at is not None
                and self._m07_run_elapsed_seconds is None
            ):
                self._m07_run_elapsed_seconds = max(
                    0.0, time.monotonic() - self._m07_run_started_at
                )

    def _open(self, path: Path, cancelled: threading.Event) -> None:
        if cancelled.is_set():
            raise ProjectCancelledError("cancelled")
        project = open_project(path)
        try:
            metadata = project.metadata()
            raw_source = metadata.get("source_path", metadata.get("source_root"))
            source = Path(raw_source) if isinstance(raw_source, str) else None
        finally:
            project.close()
        with self._lock:
            self._project_path = path
            self._source_path = source
            self._m07_service = None
            self._m07_service_path = None
            self._m07_consent_snapshot = None
            self._m07_start_binding = None
            self._clear_m07_run_metrics_locked()
        self._state_store.record_project(path)

    def _create(self, path: Path, source: Path, cancelled: threading.Event) -> None:
        try:
            project = create_ingested_project(
                path,
                source,
                cancel_check=cancelled.is_set,
                progress=lambda stage, percent: self._deterministic_progress(
                    "create", stage, percent
                ),
            )
            project.close()
        except BaseException:
            if path.exists():
                with Project.open(path) as partial:
                    retained = partial.payload("m10_analysis_state", "authoritative") is not None
                if retained:
                    self._retain_project_path(path, source)
            raise
        self._retain_project_path(path, source)

    def _retain_project_path(self, path: Path, source: Path) -> None:
        with self._lock:
            self._project_path = path
            self._source_path = source
            self._m07_service = None
            self._m07_service_path = None
            self._m07_consent_snapshot = None
            self._m07_start_binding = None
            self._clear_m07_run_metrics_locked()
        self._state_store.record_project(path)

    def _refresh(self, cancelled: threading.Event) -> None:
        with self._lock:
            project, source = self._project_path, self._source_path
        if project is None or source is None:
            raise ApiProblem(409, "no_project", "Open a project first.")
        refresh_ingested_project(
            project,
            source,
            cancel_check=cancelled.is_set,
            progress=lambda stage, percent: self._deterministic_progress(
                "refresh", stage, percent
            ),
        )
        self._clear_m07_run_metrics()

    def _deterministic_progress(self, kind: str, stage: str, percent: int) -> None:
        with self._lock:
            task = self._task
        if task is not None and task.kind == kind and task.state == "running":
            self._progress(task.id, kind, stage, percent)

    def _project(self) -> Path:
        with self._lock:
            path = self._project_path
        if path is None:
            raise ApiProblem(409, "no_project", "Open a project first.")
        return path

    def _m07_workflow(self) -> M07WorkflowService:
        path = self._project()
        with self._lock:
            if self._m07_service is None or self._m07_service_path != path:
                self._m07_service = M07WorkflowService(path, self._m07_provider_factory)
                self._m07_service_path = path
            return self._m07_service

    def _m07_route_authority(self) -> dict[str, object]:
        with Project.open(self._project()) as project:
            route = project.payload("m07_route_map", "authoritative")
        if not isinstance(route, dict):
            raise ValueError("the project has no valid M07 route map")
        return cast(dict[str, object], route)

    def _m11_payloads(
        self,
        *,
        include_canonical: bool,
    ) -> tuple[
        dict[str, object] | None,
        dict[str, object] | None,
        dict[str, object] | None,
        str,
        str,
        str | None,
    ]:
        """Load a current M11 publication; map requests avoid canonical decoding."""

        with Project.open(self._project()) as project:
            raw_state = project.payload("m10_analysis_state", "authoritative")
            if not isinstance(raw_state, dict):
                raise ValueError("the project has no valid M10 generation state")
            source_generation = raw_state.get("source_generation")
            canonical_generation = raw_state.get("canonical_generation")
            canonical_hash = raw_state.get("canonical_hash")
            generation = source_generation if isinstance(source_generation, str) else "unknown"
            authority_hash = canonical_hash if isinstance(canonical_hash, str) else "0" * 64
            row = project._require_open().execute(
                """SELECT payload_hash FROM payloads
                   WHERE collection='m10_canonical_graph' AND record_key='authoritative'"""
            ).fetchone()
            if (
                raw_state.get("canonical_availability") != "current_complete"
                or canonical_generation != generation
                or row is None
                or str(row["payload_hash"]) != authority_hash
            ):
                return (
                    None,
                    None,
                    None,
                    generation,
                    authority_hash,
                    "m10_canonical_not_current",
                )
            selection = project.m11_persistence().select_current(
                source_generation=generation,
                canonical_schema=CANONICAL_GRAPH_SCHEMA,
                canonical_hash=authority_hash,
            )
            if (
                selection.availability is not M11Availability.CURRENT_COMPLETE
                or selection.phase_results is None
            ):
                return (
                    None,
                    None,
                    None,
                    generation,
                    authority_hash,
                    selection.reason,
                )
            try:
                model = stored_scene_model_mapping(selection.phase_results)
                raw_presentation = selection.phase_results["scene_presentation"]
                presentation = dict(raw_presentation)
            except (KeyError, TypeError, ValueError):
                return (
                    None,
                    None,
                    None,
                    generation,
                    authority_hash,
                    "m11_publication_invalid",
                )
            canonical: dict[str, object] | None = None
            if include_canonical:
                raw_canonical = project.payload("m10_canonical_graph", "authoritative")
                if not isinstance(raw_canonical, dict):
                    return (
                        None,
                        None,
                        None,
                        generation,
                        authority_hash,
                        "canonical_missing",
                    )
                canonical = raw_canonical
            return (
                model,
                presentation,
                canonical,
                generation,
                authority_hash,
                None,
            )

    def _m10_payloads(
        self,
    ) -> tuple[
        dict[str, object] | None,
        dict[str, object] | None,
        dict[str, object],
        str | None,
    ]:
        with Project.open(self._project()) as project:
            raw_projection = project.payload("m10_inspection_projection", "authoritative")
            raw_canonical = project.payload("m10_canonical_graph", "authoritative")
            analysis_state = project.payload("m10_analysis_state", "authoritative")
        if not isinstance(analysis_state, dict):
            raise ValueError("the project has no valid M10 generation state")
        if (
            analysis_state.get("schema_version") != ANALYSIS_STATE_SCHEMA_VERSION
            or not isinstance(analysis_state.get("source_generation"), str)
        ):
            raise ValueError("the project has an incompatible M10 generation state")
        canonical = (
            cast(dict[str, object], raw_canonical)
            if isinstance(raw_canonical, dict)
            and raw_canonical.get("schema") == CANONICAL_GRAPH_SCHEMA
            and isinstance(raw_canonical.get("source_generation"), str)
            else None
        )
        state_canonical_generation = analysis_state.get("canonical_generation")
        state_canonical_hash = analysis_state.get("canonical_hash")
        if canonical is not None:
            canonical_hash = hashlib.sha256(storage.canonical_json(canonical)).hexdigest()
            if (
                state_canonical_generation != canonical["source_generation"]
                or state_canonical_hash != canonical_hash
            ):
                raise ValueError("the M10 generation state does not bind the canonical graph")
        elif state_canonical_generation is not None or state_canonical_hash is not None:
            raise ValueError("the M10 generation state references an invalid canonical graph")
        projection_reason: str | None = None
        projection = (
            cast(dict[str, object], raw_projection)
            if isinstance(raw_projection, dict)
            and raw_projection.get("schema") == INSPECTION_PROJECTION_SCHEMA
            and isinstance(raw_projection.get("source_generation"), str)
            and isinstance(raw_projection.get("canonical_graph_hash"), str)
            else None
        )
        if projection is None:
            projection_reason = (
                "projection_missing" if raw_projection is None else "projection_invalid"
            )
        elif canonical is None:
            projection = None
            projection_reason = "canonical_missing"
        elif projection["source_generation"] != canonical["source_generation"]:
            projection = None
            projection_reason = "projection_generation_mismatch"
        elif projection["canonical_graph_hash"] != state_canonical_hash:
            projection = None
            projection_reason = "projection_canonical_hash_mismatch"
        elif (
            analysis_state.get("simplified_generation") != projection["source_generation"]
            or analysis_state.get("simplified_canonical_hash")
            != projection["canonical_graph_hash"]
        ):
            projection = None
            projection_reason = "projection_analysis_state_mismatch"
        return (
            projection,
            canonical,
            cast(dict[str, object], analysis_state),
            projection_reason,
        )

    def _m08_query(
        self,
    ) -> tuple[AIStoryMapQueryResult, dict[str, object], dict[str, dict[str, object]]]:
        """Resolve only the applied assembly for the current exact route authority.

        A latest stale applied row is inspected only to return the explicit stale reason. It is
        never projected over current authority and never becomes the default map.
        """

        with Project.open(self._project()) as project:
            route = project.payload("m07_route_map", "authoritative")
            if not isinstance(route, dict):
                raise ValueError("the project has no valid M07 route map")
            typed_route = cast(dict[str, object], route)
            generation = hashlib.sha256(storage.canonical_json(typed_route)).hexdigest()
            model = project.m07_model_service()
            facts = _m08_facts_by_id(project)
            try:
                assembly: object | None = model.applied_assembly(generation=generation)
            except (storage.ProjectCorruptError, TypeError, ValueError):
                assembly = {
                    "assembly_id": "invalid",
                    "generation": generation,
                    "status": "applied",
                    "payload": None,
                    "payload_hash": "invalid",
                }
            if isinstance(assembly, Assembly):
                try:
                    validate_persisted_assembly(
                        project,
                        route=typed_route,
                        generation=generation,
                        assembly_id=assembly.assembly_id,
                    )
                except (
                    InvalidProviderOutputError,
                    KeyError,
                    TypeError,
                    ValueError,
                    storage.ProjectCorruptError,
                ):
                    assembly = {
                        "assembly_id": "invalid",
                        "generation": generation,
                        "status": "applied",
                        "payload": None,
                        "payload_hash": "invalid",
                    }
            if assembly is None:
                row = (
                    project._require_open()
                    .execute(
                        """SELECT assembly_id,generation,status,payload_json,payload_hash
                       FROM m07_assemblies WHERE status='applied'
                       ORDER BY applied_utc DESC,assembly_id DESC LIMIT 1"""
                    )
                    .fetchone()
                )
                if row is not None:
                    try:
                        assembly = {
                            "assembly_id": str(row["assembly_id"]),
                            "generation": str(row["generation"]),
                            "status": str(row["status"]),
                            "payload": storage.decode_json(row["payload_json"]),
                            "payload_hash": str(row["payload_hash"]),
                        }
                    except (storage.ProjectCorruptError, TypeError, ValueError):
                        assembly = {
                            "assembly_id": "invalid",
                            "generation": generation,
                            "status": "applied",
                            "payload": None,
                            "payload_hash": "invalid",
                        }
            result = query_ai_story_map(typed_route, assembly, facts=facts)  # type: ignore[arg-type]
        return result, typed_route, facts

    def _persisted_attempt_metrics(self) -> dict[str, int]:
        with Project.open(self._project()) as project:
            row = (
                project._require_open()
                .execute(
                    """SELECT COALESCE(SUM(calls),0) calls,
                          COALESCE(SUM(input_tokens),0) input_tokens,
                          COALESCE(SUM(output_tokens),0) output_tokens,
                          COALESCE(SUM(elapsed_ms),0) elapsed_ms,
                          COALESCE(SUM(cached),0) cache_hits,
                          COUNT(*) attempts
                   FROM m07_provider_attempts"""
                )
                .fetchone()
            )
        names = ("calls", "input_tokens", "output_tokens", "elapsed_ms", "cache_hits", "attempts")
        return {name: 0 if row is None else int(row[name]) for name in names}

    def _m08_attempt_metrics(
        self,
        response: Mapping[str, object],
        *,
        use_current_run: bool | None = None,
    ) -> dict[str, object]:
        persisted = self._persisted_attempt_metrics()
        with self._lock:
            run_id = self._m07_run_id
            baseline = None if self._m07_run_baseline is None else dict(self._m07_run_baseline)
            progress = self._m07_run_progress
            started_at = self._m07_run_started_at
            finished_elapsed = self._m07_run_elapsed_seconds
            current_cache_hits = self._m07_run_cache_hits

        current_run = run_id is not None and baseline is not None
        if use_current_run is not None:
            current_run = current_run and use_current_run
        if not current_run:
            scope = "project_history"
            label = "Persisted project history"
            metrics = persisted
            elapsed_seconds = metrics["elapsed_ms"] / 1000
            elapsed_basis = "provider_attempts"
            accounting_run_id = None
        else:
            assert run_id is not None and baseline is not None
            scope = "current_run"
            label = "Current run"
            metrics = {name: max(0, persisted[name] - baseline[name]) for name in persisted}
            if progress is not None:
                metrics["calls"] = progress.calls
                metrics["input_tokens"] = progress.input_tokens
                metrics["output_tokens"] = progress.output_tokens
                metrics["attempts"] = max(metrics["attempts"], progress.calls)
            metrics["cache_hits"] = current_cache_hits
            if finished_elapsed is not None:
                elapsed_seconds = finished_elapsed
            elif started_at is not None:
                elapsed_seconds = max(0.0, time.monotonic() - started_at)
            else:
                elapsed_seconds = 0.0
            elapsed_basis = "wall_clock"
            accounting_run_id = run_id

        token_total = metrics["input_tokens"] + metrics["output_tokens"]
        raw_tokens = response.get("tokens")
        budget = raw_tokens.get("budget", 0) if isinstance(raw_tokens, Mapping) else 0
        accounting = {
            "scope": scope,
            "label": label,
            "run_id": accounting_run_id,
            "calls": metrics["calls"],
            "tokens": {
                "input": metrics["input_tokens"],
                "output": metrics["output_tokens"],
                "total": token_total,
            },
            "elapsed_seconds": elapsed_seconds,
            "elapsed_basis": elapsed_basis,
            "cache_hits": metrics["cache_hits"],
            "attempts": metrics["attempts"],
        }
        return {
            "accounting": accounting,
            "calls": metrics["calls"],
            "tokens": {
                "used": token_total,
                "budget": budget,
                "input": metrics["input_tokens"],
                "output": metrics["output_tokens"],
                "total": token_total,
            },
            "elapsed_seconds": elapsed_seconds,
            "cache_hits": metrics["cache_hits"],
            "attempts": metrics["attempts"],
        }

    def _m07_browser_status(self, response: dict[str, object]) -> dict[str, object]:
        project_history = _m07_scope_metrics(response)
        project_history["accounting"] = self._m08_attempt_metrics(response, use_current_run=False)[
            "accounting"
        ]
        with self._lock:
            current_run = self._m07_run_id is not None
            selected_ids = self._m07_run_selected_ids
        if current_run:
            _filter_m07_scope_metrics(response, selected_ids)
        response.update(self._m08_attempt_metrics(response))
        if current_run:
            scope_counts = response.get("scope_counts")
            tokens = response.get("tokens")
            if isinstance(scope_counts, dict) and isinstance(tokens, dict):
                scope_counts["calls"] = response["calls"]
                scope_counts["input_tokens"] = tokens["input"]
                scope_counts["output_tokens"] = tokens["output"]
        response["status_scope"] = "current_run" if current_run else "project_history"
        response["status_label"] = "Current run" if current_run else "Persisted project history"
        response["project_history"] = project_history
        return self._with_m07_consent(response)

    def _begin_m07_run_metrics(self, run_id: str) -> None:
        baseline = self._persisted_attempt_metrics()
        with self._lock:
            snapshot = self._m07_consent_snapshot or {}
            cached = snapshot.get("cached", 0)
            validated = snapshot.get("validated", 0)
            scope_ids = snapshot.get("scope_ids", [])
            window_ids = snapshot.get("window_ids", [])
            self._m07_run_id = run_id
            self._m07_run_baseline = baseline
            self._m07_run_progress = None
            self._m07_run_started_at = time.monotonic()
            self._m07_run_elapsed_seconds = None
            self._m07_run_cache_hits = (
                cached if isinstance(cached, int) and not isinstance(cached, bool) else 0
            ) + (validated if isinstance(validated, int) and not isinstance(validated, bool) else 0)
            self._m07_run_selected_ids = tuple(
                item
                for values in (scope_ids, window_ids)
                if isinstance(values, list)
                for item in values
                if isinstance(item, str)
            )

    def _clear_m07_run_metrics(self) -> None:
        with self._lock:
            self._clear_m07_run_metrics_locked()

    def _clear_m07_run_metrics_locked(self) -> None:
        self._m07_run_id = None
        self._m07_run_baseline = None
        self._m07_run_progress = None
        self._m07_run_started_at = None
        self._m07_run_elapsed_seconds = None
        self._m07_run_cache_hits = 0
        self._m07_run_selected_ids = ()

    def _m08_ai_story_page(self, body: dict[str, JsonValue]) -> dict[str, object]:
        node_offset = bounded_int(body, "node_offset", default=0, minimum=0, maximum=2_000_000)
        node_limit = bounded_int(body, "node_limit", default=30, minimum=1, maximum=30)
        edge_offset = bounded_int(body, "edge_offset", default=0, minimum=0, maximum=2_000_000)
        edge_limit = bounded_int(body, "edge_limit", default=180, minimum=1, maximum=180)
        edge_cursor = optional_string(body, "edge_cursor", maximum=80)
        result, _route, _facts = self._m08_query()
        if result.story_map is None:
            return result.to_dict()
        return result.story_map.page(
            node_offset=node_offset,
            node_limit=node_limit,
            edge_offset=edge_offset,
            edge_limit=edge_limit,
            edge_cursor=edge_cursor,
        )

    def _m08_ai_story_detail(self, body: dict[str, JsonValue]) -> dict[str, object]:
        element_id = require_string(body, "element_id")
        route_node_offset = bounded_int(
            body, "route_node_offset", default=0, minimum=0, maximum=2_000_000
        )
        route_node_limit = bounded_int(body, "route_node_limit", default=30, minimum=1, maximum=30)
        route_edge_offset = bounded_int(
            body, "route_edge_offset", default=0, minimum=0, maximum=2_000_000
        )
        route_edge_limit = bounded_int(
            body, "route_edge_limit", default=180, minimum=1, maximum=180
        )
        evidence_offset = bounded_int(
            body, "evidence_offset", default=0, minimum=0, maximum=2_000_000
        )
        evidence_limit = bounded_int(body, "evidence_limit", default=60, minimum=1, maximum=60)
        result, _route, _facts = self._m08_query()
        if result.story_map is None:
            return result.to_dict()
        story_map = result.story_map
        try:
            detail = story_map.detail(
                element_id,
                route_node_offset=route_node_offset,
                route_node_limit=route_node_limit,
                route_edge_offset=route_edge_offset,
                route_edge_limit=route_edge_limit,
                evidence_offset=evidence_offset,
                evidence_limit=evidence_limit,
            )
        except KeyError as exc:
            raise ApiProblem(
                404, "m08_element_not_found", "The AI Story Map element is unavailable."
            ) from exc
        node = next((item for item in story_map.nodes if item.id == element_id), None)
        edge = next((item for item in story_map.edges if item.id == element_id), None)
        if node is not None:
            predecessor_ids = [
                item.source_id for item in story_map.edges if item.target_id == node.id
            ]
            successor_ids = [
                item.target_id for item in story_map.edges if item.source_id == node.id
            ]
        else:
            assert edge is not None
            predecessor_ids = [edge.source_id]
            successor_ids = [edge.target_id]
        detail["predecessor_ids"] = predecessor_ids
        detail["successor_ids"] = successor_ids
        detail["local_path"] = [*predecessor_ids, element_id, *successor_ids]
        with Project.open(self._project()) as project:
            qualified = {
                str(item["id"]): item
                for item in (
                    _m08_qualify_evidence(project, cast(Mapping[str, object], evidence))
                    for evidence in cast(list[object], detail["evidence"])
                    if isinstance(evidence, Mapping) and isinstance(evidence.get("id"), str)
                )
            }
        detail["evidence"] = [
            qualified.get(str(item.get("id")), item)
            for item in cast(list[dict[str, object]], detail["evidence"])
        ]
        return self._story_display_detail(detail)

    def _m08_comparison(self, body: dict[str, JsonValue]) -> dict[str, object]:
        ai = self._m08_ai_story_page({**body, "edge_offset": 0})
        technical = self._m07_workflow().route_map(
            offset=bounded_int(body, "node_offset", default=0, minimum=0, maximum=2_000_000),
            limit=bounded_int(body, "node_limit", default=30, minimum=1, maximum=30),
            edge_offset=bounded_int(body, "edge_offset", default=0, minimum=0, maximum=2_000_000),
            edge_limit=bounded_int(body, "edge_limit", default=180, minimum=1, maximum=180),
        )
        technical = self._story_display_route_page(technical)
        authority_hash = str(technical["authority_hash"])
        if ai.get("authority_hash") != authority_hash:
            raise ApiProblem(
                409,
                "m08_authority_changed",
                "The route authority changed while preparing the comparison.",
            )
        return {
            "schema_version": 1,
            "authority_hash": authority_hash,
            "default_view": "ai_story_map" if ai.get("status") == "available" else "technical",
            "ai": ai,
            "technical": technical,
            "authority_unchanged": True,
        }

    def _story_display_route_page(self, page: dict[str, object]) -> dict[str, object]:
        with Project.open(self._project()) as project:
            context = _story_display_context(project)
        return _enrich_route_page(page, context)

    def _story_display_detail(self, detail: dict[str, object]) -> dict[str, object]:
        with Project.open(self._project()) as project:
            context = _story_display_context(project)
        return _enrich_story_detail(detail, context)

    def _m07_prepared_contract(self, raw: dict[str, object]) -> dict[str, object]:
        scope_ids = _object_strings(raw.get("scope_ids"), "prepared scope_ids")
        window_ids = _object_strings(raw.get("window_ids"), "prepared window_ids")
        windows = _object_records(raw.get("windows"), "prepared windows")
        model = raw.get("model")
        budgets = raw.get("budgets")
        if model != M07_MODEL_IDENTITY or not isinstance(budgets, dict):
            raise ValueError("the prepared provider binding is invalid")
        exact_fields(
            cast(dict[str, JsonValue], budgets),
            allowed=M07_BUDGET_FIELDS,
            required=M07_BUDGET_FIELDS,
            name="prepared budgets",
        )
        authority_hash = _object_sha256(raw.get("authority_hash"), "prepared authority_hash")
        selected_ids = {*scope_ids, *window_ids}
        with Project.open(self._project()) as project:
            route = project.payload("m07_route_map", "authoritative")
            if not isinstance(route, dict):
                raise ValueError("the project has no valid M07 route map")
            checkpoints = project.m07_model_service().checkpoints(generation=authority_hash)
            source_coverage = project.source_coverage()
        cached = sum(
            item.scope_id in selected_ids and item.status is CheckpointStatus.CACHED
            for item in checkpoints
        )
        validated = sum(
            item.scope_id in selected_ids and item.status is CheckpointStatus.VALIDATED
            for item in checkpoints
        )
        return {
            "run_id": _object_string(raw.get("run_id"), "prepared run_id"),
            "scopes": len(scope_ids) + len(window_ids),
            "scope_ids": list(scope_ids),
            "window_ids": list(window_ids),
            "windows": windows,
            "selected_counts": _selected_counts(cast(dict[str, object], route), scope_ids, windows),
            "cached": cached,
            "validated": validated,
            "model": dict(M07_MODEL_IDENTITY),
            "budgets": dict(budgets),
            "authority_hash": authority_hash,
            "selection_hash": _object_sha256(raw.get("selection_hash"), "prepared selection_hash"),
            "recovered_source_acknowledgement": _object_sha256(
                raw.get("recovered_source_acknowledgement"),
                "prepared recovered-source acknowledgement",
            ),
            "source_coverage": source_coverage,
            "requires_confirm_cloud": raw.get("requires_confirm_cloud") is True,
        }

    def _with_m07_consent(self, response: dict[str, object]) -> dict[str, object]:
        with self._lock:
            stored = self._m07_consent_snapshot
            snapshot = None if stored is None else dict(stored)
        if snapshot is None:
            empty = json_value(
                {
                    "scope_ids": [],
                    "window_ids": [],
                    "selected_counts": _empty_selected_counts(),
                    "cached": 0,
                    "validated": 0,
                    "model": dict(M07_MODEL_IDENTITY),
                    "budgets": dict(M07_DEFAULT_BUDGETS),
                    "selection_hash": None,
                    "prepared_authority_hash": None,
                    "recovered_source_acknowledgement": None,
                }
            )
            if not isinstance(empty, dict):
                raise TypeError("empty consent snapshot must be an object")
            snapshot = empty
        else:
            cached, validated = _selected_checkpoint_counts(
                response.get("scope_statuses"),
                {
                    *cast(list[str], snapshot["scope_ids"]),
                    *cast(list[str], snapshot["window_ids"]),
                },
            )
            snapshot["cached"] = cached
            snapshot["validated"] = validated
        return {**response, **snapshot}

    def _consume_m07_start_binding(self, actual: dict[str, JsonValue]) -> None:
        with self._lock:
            expected = self._m07_start_binding
            if expected is None or not secrets.compare_digest(
                cast(str, expected["run_id"]), cast(str, actual["run_id"])
            ):
                raise PreparedRunError("the prepared run is missing or stale")
            self._m07_start_binding = None
        comparisons = (
            ("scope_ids", "the start scope_ids do not match the prepared run"),
            ("window_ids", "the start window_ids do not match the prepared run"),
            ("budgets", "the start budget does not match the prepared run"),
            ("selection_hash", "the start selection_hash does not match the prepared run"),
            ("authority_hash", "the start authority_hash does not match the prepared run"),
            (
                "recovered_source_acknowledgement",
                "the recovered-source acknowledgement does not match the prepared run",
            ),
            ("model", "the provider identity does not match the prepared run"),
        )
        for name, message in comparisons:
            if actual[name] != expected[name]:
                raise PreparedRunError(message)

    def _presentation_view(self, body: dict[str, JsonValue]) -> JsonValue:
        raw_level = body.get("level", "arcs")
        if isinstance(raw_level, str):
            level_value = {"arcs": 1, "events": 2, "evidence": 3}.get(raw_level)
            if level_value is None:
                raise ValueError("invalid level")
            level_name = raw_level
        else:
            level_value = bounded_int(body, "level", default=1, minimum=1, maximum=3)
            level_name = {1: "arcs", 2: "events", 3: "evidence"}[level_value]
        request = PresentationRequest(
            level=PresentationLevel(level_value),
            parent_ids=string_tuple(body, "parent_ids"),
            focus_ids=string_tuple(body, "focus_ids"),
            expanded_ids=string_tuple(body, "expanded_ids"),
            collapsed_ids=string_tuple(body, "collapsed_ids"),
            after=optional_string(body, "after"),
            edge_after=optional_string(body, "edge_after"),
            node_limit=bounded_int(body, "node_limit", default=80, minimum=1, maximum=80),
            edge_limit=bounded_int(body, "edge_limit", default=120, minimum=1, maximum=120),
            include_technical=boolean(body, "include_technical"),
        )
        path = self._project()
        with Project.open(path) as project:
            service = PresentationService(project)
            page = service.view(request, selected_id=optional_string(body, "selected_id"))
            unresolved_ids, resolved_ids = self._unresolved_presentation_ids(project)
        nodes = [
            _story_view_node(
                node,
                authoritative_unresolved=node.id in unresolved_ids,
                authoritative_resolved=node.id in resolved_ids,
            )
            for node in page.nodes
        ]
        edges = [
            {
                "id": edge.id,
                "source": edge.source_id,
                "target": edge.target_id,
                "kind": edge.kind,
                "payload": json_value(edge.payload),
            }
            for edge in page.edges
        ]
        return json_value(
            {
                "level": level_name,
                "nodes": nodes,
                "edges": edges,
                "selected_id": page.selected_id,
                "overflow": {
                    "nodes_more": page.node_continuation.has_more,
                    "edges_more": page.edge_continuation.has_more,
                },
            }
        )

    def _unresolved_presentation_ids(
        self, project: Project
    ) -> tuple[frozenset[str], frozenset[str]]:
        """Classify semantic unresolved authority once per project generation."""

        connection = project._require_open()
        generation_row = connection.execute(
            "SELECT payload_hash FROM payloads "
            "WHERE collection='m02_semantic' AND record_key='authoritative'"
        ).fetchone()
        if generation_row is None:
            return frozenset(), frozenset()
        generation = str(generation_row["payload_hash"])
        key_path = project.path.resolve()
        with self._classification_lock:
            cached = self._unresolved_cache
            if cached is not None and cached[0] == key_path and cached[1] == generation:
                return cached[2], cached[3]
            rows = connection.execute(
                """WITH authority(graph_node_id, is_unresolved, is_resolved) AS (
                     SELECT CAST(graph_id.value AS TEXT),
                            CASE WHEN json_extract(record.value,'$.resolved')=0 THEN 1 ELSE 0 END,
                            CASE WHEN json_extract(record.value,'$.resolved')=1 THEN 1 ELSE 0 END
                     FROM payloads payload,
                          json_each(CAST(payload.payload_json AS TEXT),'$.unresolved') record,
                          json_each(record.value,'$.graph_node_ids') graph_id
                     WHERE payload.collection='m02_semantic'
                       AND payload.record_key='authoritative'
                       AND json_extract(record.value,'$.resolved') IN (0,1)
                   ), matched(node_id, parent_id, scene_id, is_unresolved, is_resolved) AS (
                     SELECT node.node_id,node.parent_id,parent.parent_id,
                            authority.is_unresolved,authority.is_resolved
                     FROM presentation_nodes node
                     JOIN presentation_nodes parent ON parent.node_id=node.parent_id,
                          json_each(CAST(node.payload_json AS TEXT),'$.graph_node_ids') graph_id
                     JOIN authority ON authority.graph_node_id=CAST(graph_id.value AS TEXT)
                     WHERE node.level=3
                   ), expanded(node_id, is_unresolved, is_resolved) AS (
                     SELECT node_id,is_unresolved,is_resolved FROM matched
                     UNION ALL
                     SELECT parent_id,is_unresolved,is_resolved FROM matched
                     UNION ALL
                     SELECT scene_id,is_unresolved,is_resolved FROM matched
                   )
                   SELECT node_id,MAX(is_unresolved) AS is_unresolved,
                          MAX(is_resolved) AS is_resolved
                   FROM expanded WHERE node_id IS NOT NULL GROUP BY node_id"""
            ).fetchall()
            unresolved = frozenset(
                str(row["node_id"]) for row in rows if bool(row["is_unresolved"])
            )
            resolved = frozenset(
                str(row["node_id"])
                for row in rows
                if not bool(row["is_unresolved"]) and bool(row["is_resolved"])
            )
            self._unresolved_cache = (key_path, generation, unresolved, resolved)
            return unresolved, resolved

    def _presentation_search(self, body: dict[str, JsonValue]) -> JsonValue:
        query = require_string(body, "query", maximum=256)
        with PresentationService.open(self._project()) as service:
            result = service.search(
                query,
                after=optional_string(body, "after"),
                limit=bounded_int(body, "limit", default=25, minimum=1, maximum=MAX_RESULTS),
            )
        return json_value(result)

    def _presentation_evidence(self, body: dict[str, JsonValue]) -> JsonValue:
        with PresentationService.open(self._project()) as service:
            result = service.evidence(
                require_string(body, "node_id"),
                after=optional_string(body, "after"),
                limit=bounded_int(body, "limit", default=25, minimum=1, maximum=MAX_RESULTS),
            )
        return {
            "node_id": require_string(body, "node_id"),
            "records": json_value(result.items),
            "truncated": result.continuation.has_more,
        }

    def _presentation_facts(self, body: dict[str, JsonValue]) -> JsonValue:
        with PresentationService.open(self._project()) as service:
            result = service.facts(
                node_id=require_string(body, "node_id"),
                after=optional_string(body, "after"),
                limit=bounded_int(body, "limit", default=25, minimum=1, maximum=MAX_RESULTS),
            )
        return json_value(result)

    def _m07_progress(self, progress: ProgressSnapshot) -> None:
        with self._lock:
            task = self._task
            if task is not None and task.kind == "m07_organization":
                self._m07_run_progress = progress
        if task is not None and task.kind == "m07_organization":
            completed = (
                progress.validated + progress.fallback + progress.failed + progress.cancelled
            )
            percent = 0 if progress.total == 0 else round(completed * 100 / progress.total)
            self._progress(task.id, task.kind, "organizing route scopes", min(99, percent))


type StoryDisplayContext = tuple[
    dict[str, str],
    dict[str, tuple[str, str]],
    dict[str, str],
    dict[str, str],
]


def _story_display_context(project: Project) -> StoryDisplayContext:
    aliases: dict[str, str] = {}
    state_names: dict[str, tuple[str, str]] = {}
    scene_titles: dict[str, str] = {}
    ambiguous_scene_titles: set[str] = set()
    control_labels: dict[str, str] = {}

    metadata = project.payload("story_metadata", "authoritative")
    if isinstance(metadata, Mapping):
        characters = metadata.get("characters")
        if isinstance(characters, list):
            for item in characters:
                if not isinstance(item, Mapping):
                    continue
                alias, display_name = item.get("alias"), item.get("display_name")
                if isinstance(alias, str) and isinstance(display_name, str):
                    aliases[alias] = display_name
        titles = metadata.get("scene_titles")
        if isinstance(titles, list):
            for item in titles:
                if not isinstance(item, Mapping):
                    continue
                key, title = item.get("key"), item.get("title")
                if isinstance(key, str) and isinstance(title, str):
                    if key in scene_titles or key in ambiguous_scene_titles:
                        scene_titles.pop(key, None)
                        ambiguous_scene_titles.add(key)
                    else:
                        scene_titles[key] = title

    registry = project.payload("state_registry", "authoritative")
    if isinstance(registry, list):
        for item in registry:
            if not isinstance(item, Mapping):
                continue
            name, display_name, category = (
                item.get("original_name"),
                item.get("display_name"),
                item.get("category"),
            )
            if all(isinstance(value, str) for value in (name, display_name, category)):
                state_names[cast(str, name)] = (cast(str, display_name), cast(str, category))

    control_flow = project.payload("m06_control_flow", "authoritative")
    if isinstance(control_flow, Mapping) and isinstance(control_flow.get("nodes"), list):
        for item in cast(list[object], control_flow["nodes"]):
            if not isinstance(item, Mapping) or item.get("kind") != "label":
                continue
            node_id, label = item.get("id"), item.get("label")
            if isinstance(node_id, str) and isinstance(label, str):
                control_labels[node_id] = label
    return aliases, state_names, scene_titles, control_labels


def _enrich_route_page(
    page: Mapping[str, object], context: StoryDisplayContext
) -> dict[str, object]:
    result = dict(page)
    nodes = page.get("nodes")
    if isinstance(nodes, list):
        result["nodes"] = [
            _enrich_route_node(item, context) if isinstance(item, Mapping) else item
            for item in nodes
        ]
    return result


def _enrich_route_node(
    node: Mapping[str, object], context: StoryDisplayContext
) -> dict[str, object]:
    _aliases, _state_names, scene_titles, control_labels = context
    result = dict(node)
    control_id = node.get("control_node_id")
    label = control_labels.get(control_id) if isinstance(control_id, str) else None
    title = scene_titles.get(label) if label is not None else None
    if title is None or node.get("organization") == "ai_interpretation":
        return result
    previous_title = result.get("title")
    result["title"] = title
    result["scene_title_key"] = label
    if result.get("summary") == previous_title:
        result["summary"] = title
    return result


def _enrich_story_detail(
    detail: Mapping[str, object], context: StoryDisplayContext
) -> dict[str, object]:
    aliases, state_names, _scene_titles, _control_labels = context
    result = dict(detail)
    element = detail.get("element")
    if isinstance(element, Mapping):
        result["element"] = _enrich_route_node(element, context)
    members = detail.get("member_route_nodes")
    if isinstance(members, list):
        result["member_route_nodes"] = [
            _enrich_route_node(item, context) if isinstance(item, Mapping) else item
            for item in members
        ]
    for collection in ("facts", "gates", "effects"):
        raw_items = detail.get(collection)
        if isinstance(raw_items, list):
            result[collection] = [
                _enrich_story_fact(item, state_names) if isinstance(item, Mapping) else item
                for item in raw_items
            ]
    enriched_facts = result.get("facts")
    if isinstance(enriched_facts, list):
        if "gates" not in detail:
            result["gates"] = [
                item
                for item in enriched_facts
                if isinstance(item, Mapping) and isinstance(item.get("variables"), list)
            ]
        if "effects" not in detail:
            result["effects"] = [
                item
                for item in enriched_facts
                if isinstance(item, Mapping) and isinstance(item.get("variable"), str)
            ]

    evidence = detail.get("evidence")
    if isinstance(evidence, list):
        enriched_evidence: list[object] = []
        dialogue: list[dict[str, object]] = []
        for item in evidence:
            if not isinstance(item, Mapping):
                enriched_evidence.append(item)
                continue
            enriched, records = _enrich_story_evidence(item, aliases)
            enriched_evidence.append(enriched)
            dialogue.extend(records[: max(0, MAX_RESULTS - len(dialogue))])
        result["evidence"] = enriched_evidence
        if dialogue:
            result["dialogue"] = dialogue
    return result


def _enrich_story_fact(
    fact: Mapping[str, object], state_names: Mapping[str, tuple[str, str]]
) -> dict[str, object]:
    result = dict(fact)
    variable = fact.get("variable")
    if not isinstance(variable, str):
        variables = fact.get("variables")
        variable = variables[0] if isinstance(variables, list) and variables else None
    display = state_names.get(variable) if isinstance(variable, str) else None
    if display is not None:
        result["variable_display_name"] = display[0]
        result["category"] = display[1]
    return result


def _enrich_story_evidence(
    evidence: Mapping[str, object], aliases: Mapping[str, str]
) -> tuple[dict[str, object], list[dict[str, object]]]:
    result = dict(evidence)
    payload = evidence.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("content"), list):
        return result, []
    content: list[object] = []
    dialogue: list[dict[str, object]] = []
    evidence_id = str(evidence.get("id", "evidence"))
    for index, raw in enumerate(cast(list[object], payload["content"])):
        if not isinstance(raw, Mapping):
            content.append(raw)
            continue
        item = dict(raw)
        speaker, text = item.get("speaker"), item.get("text")
        display_name = aliases.get(speaker) if isinstance(speaker, str) else None
        if display_name is not None and isinstance(text, str):
            item["speaker_display_name"] = display_name
            dialogue.append(
                {
                    "id": f"{evidence_id}:dialogue:{index}",
                    "speaker": speaker,
                    "speaker_display_name": display_name,
                    "text": text,
                }
            )
        content.append(item)
    enriched_payload = dict(payload)
    enriched_payload["content"] = content
    result["payload"] = enriched_payload
    return result, dialogue


def _m07_scope_metrics(response: Mapping[str, object]) -> dict[str, object]:
    scopes = response.get("scopes")
    scope_counts = response.get("scope_counts")
    scope_statuses = response.get("scope_statuses")
    coverage = response.get("coverage")
    return {
        "scope": "project_history",
        "label": "Persisted project history",
        "status": response.get("status"),
        "scopes": dict(scopes) if isinstance(scopes, Mapping) else {},
        "scope_counts": dict(scope_counts) if isinstance(scope_counts, Mapping) else {},
        "scope_statuses": list(scope_statuses) if isinstance(scope_statuses, list) else [],
        "coverage": dict(coverage) if isinstance(coverage, Mapping) else {},
        "ai_coverage": response.get("ai_coverage"),
        "technical_coverage": response.get("technical_coverage"),
        "partial": response.get("partial"),
        "cached": _m07_status_count(scope_statuses, "cached"),
        "validated": _m07_status_count(scope_statuses, "validated"),
    }


def _m07_status_count(value: object, status: str) -> int:
    if not isinstance(value, list):
        return 0
    return sum(isinstance(item, Mapping) and item.get("status") == status for item in value)


def _filter_m07_scope_metrics(response: dict[str, object], selected_ids: tuple[str, ...]) -> None:
    selected = set(selected_ids)
    raw_statuses = response.get("scope_statuses")
    statuses = (
        [
            item
            for item in raw_statuses
            if isinstance(item, Mapping) and item.get("scope_id") in selected
        ]
        if isinstance(raw_statuses, list)
        else []
    )
    counts = {
        name: _m07_status_count(statuses, name)
        for name in (
            "pending",
            "cached",
            "in_flight",
            "validated",
            "fallback",
            "failed",
            "cancelled",
        )
    }
    total = len(selected_ids)
    pending = counts["pending"] + counts["cached"] + counts["in_flight"]
    completed = counts["validated"] + counts["fallback"]
    ai_coverage = 1.0 if total == 0 else counts["validated"] / total
    technical_coverage = 1.0 if total == 0 else completed / total
    response["scope_statuses"] = statuses
    response["scopes"] = {
        "total": total,
        "pending": pending,
        "validated": counts["validated"],
        "fallback": counts["fallback"],
        "failed": counts["failed"],
        "cancelled": counts["cancelled"],
    }
    response["scope_counts"] = {
        "total": total,
        "pending": counts["pending"],
        "cached_or_in_flight": counts["cached"] + counts["in_flight"],
        "validated": counts["validated"],
        "fallback": counts["fallback"],
        "failed": counts["failed"],
        "cancelled": counts["cancelled"],
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "completed": completed,
        "ratio": 1.0 if total == 0 else completed / total,
    }
    response["coverage"] = {"ai": ai_coverage, "technical": technical_coverage}
    response["ai_coverage"] = ai_coverage
    response["technical_coverage"] = technical_coverage
    response["partial"] = completed < total or counts["fallback"] > 0


def _m08_facts_by_id(project: Project) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for collection in ("gates", "effects"):
        for key in project.payload_keys(collection):
            value = project.payload(collection, key)
            if not isinstance(value, list):
                continue
            for item in value:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    result[str(item["id"])] = cast(dict[str, object], item)
    return result


def _m08_qualify_evidence(project: Project, evidence: Mapping[str, object]) -> dict[str, object]:
    """Attach relative qualified line evidence without exposing local filesystem paths."""

    result = dict(evidence)
    source = evidence.get("source")
    if not isinstance(source, Mapping):
        graph_sources: dict[str, Mapping[str, object]] = {}
        for collection in ("m01_graph", "m06_control_flow"):
            graph = project.payload(collection, "authoritative")
            if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
                continue
            for node in graph["nodes"]:
                if (
                    isinstance(node, dict)
                    and isinstance(node.get("id"), str)
                    and isinstance(node.get("source"), Mapping)
                ):
                    graph_sources.setdefault(str(node["id"]), node["source"])
        payload = evidence.get("payload")
        if isinstance(payload, Mapping):
            source = next(
                (
                    graph_sources[candidate]
                    for candidate in (payload.get("source"), payload.get("target"))
                    if isinstance(candidate, str) and candidate in graph_sources
                ),
                None,
            )
    if not isinstance(source, Mapping):
        raise storage.ProjectCorruptError("route evidence has no qualified source location")
    path = source.get("path")
    start = source.get("start")
    end = source.get("end")
    if (
        not isinstance(path, str)
        or Path(path).is_absolute()
        or not isinstance(start, Mapping)
        or not isinstance(end, Mapping)
        or not isinstance(start.get("line"), int)
        or isinstance(start.get("line"), bool)
        or not isinstance(end.get("line"), int)
        or isinstance(end.get("line"), bool)
    ):
        raise storage.ProjectCorruptError("route evidence has invalid qualified source lines")
    derivation = next(
        (item for item in project.source_derivations() if item.get("source_path") == path),
        None,
    )
    result.update(
        {
            "source_path": path,
            "start_line": int(start["line"]),
            "end_line": int(end["line"]),
            "line_basis": (
                derivation.get("line_basis") if derivation is not None else "physical_source"
            ),
            "provenance": None if derivation is None else dict(derivation),
        }
    )
    return result


def _bounded_window_requests(
    body: dict[str, JsonValue],
) -> tuple[dict[str, object], ...]:
    requests = object_tuple(body, "window_requests", maximum_items=MAX_M07_SELECTION_ITEMS)
    result: list[dict[str, object]] = []
    expected_limits = {
        "node_ids": MAX_WINDOW_NODES,
        "internal_edge_ids": MAX_WINDOW_INTERNAL_EDGES,
        "boundary_node_ids": MAX_WINDOW_BOUNDARY_EDGES,
        "boundary_edge_ids": MAX_WINDOW_BOUNDARY_EDGES,
        "evidence_ids": MAX_WINDOW_EVIDENCE,
        "fact_ids": MAX_WINDOW_FACTS,
    }
    for request in requests:
        exact_fields(
            request,
            allowed=("node_ids", "entry_node_id", "exit_node_id", "expected"),
            required=("expected",),
            name="bounded-window request",
        )
        if "node_ids" in request:
            required_string_tuple(request, "node_ids", maximum_items=MAX_WINDOW_NODES)
        else:
            require_string(request, "entry_node_id")
            require_string(request, "exit_node_id")
        expected = object_value(request, "expected")
        exact_fields(
            expected,
            allowed=M07_EXPECTED_WINDOW_FIELDS,
            required=M07_EXPECTED_WINDOW_FIELDS,
            name="bounded-window expected",
        )
        require_string(expected, "id", maximum=128)
        for key, maximum in expected_limits.items():
            required_string_tuple(expected, key, maximum_items=maximum)
        _sha256(expected, "input_hash")
        _sha256(expected, "authority_hash")
        result.append(cast(dict[str, object], request))
    return tuple(result)


def _sha256(body: dict[str, JsonValue], name: str) -> str:
    return _object_sha256(body.get(name), name)


def _object_sha256(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _object_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError(f"{name} must be a non-empty bounded string")
    return value


def _object_strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > MAX_M07_SELECTION_ITEMS:
        raise ValueError(f"{name} must be a bounded string array")
    result = tuple(_object_string(item, name) for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must contain unique strings")
    return result


def _object_records(value: object, name: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{name} must be an object array")
    return [cast(dict[str, object], item) for item in value]


def _selected_counts(
    route: dict[str, object],
    scope_ids: tuple[str, ...],
    windows: list[dict[str, object]],
) -> dict[str, int]:
    scopes = {
        _object_string(item.get("id"), "route scope id"): item
        for item in _object_records(route.get("scopes"), "route scopes")
    }
    edges = {
        _object_string(item.get("id"), "route edge id"): item
        for item in _object_records(route.get("edges"), "route edges")
    }
    nodes: set[str] = set()
    internal_edges: set[str] = set()
    boundary_nodes: set[str] = set()
    boundary_edges: set[str] = set()
    evidence: set[str] = set()
    facts: set[str] = set()
    for scope_id in scope_ids:
        scope = scopes.get(scope_id)
        if scope is None:
            raise ValueError("prepared route scope is unavailable")
        nodes.update(_record_ids(scope, "node_ids", MAX_WINDOW_NODES))
        internal_edges.update(
            _record_ids(
                scope,
                "edge_ids",
                MAX_WINDOW_INTERNAL_EDGES + MAX_WINDOW_BOUNDARY_EDGES,
            )
        )
        evidence.update(_record_ids(scope, "evidence_ids", MAX_WINDOW_EVIDENCE))
    for window in windows:
        nodes.update(_record_ids(window, "node_ids", MAX_WINDOW_NODES))
        internal_edges.update(_record_ids(window, "internal_edge_ids", MAX_WINDOW_INTERNAL_EDGES))
        boundary_nodes.update(_record_ids(window, "boundary_node_ids", MAX_WINDOW_BOUNDARY_EDGES))
        boundary_edges.update(_record_ids(window, "boundary_edge_ids", MAX_WINDOW_BOUNDARY_EDGES))
        evidence.update(_record_ids(window, "evidence_ids", MAX_WINDOW_EVIDENCE))
        facts.update(_record_ids(window, "fact_ids", MAX_WINDOW_FACTS))
    for edge_id in internal_edges | boundary_edges:
        edge = edges.get(edge_id)
        if edge is None:
            raise ValueError("prepared route edge is unavailable")
        facts.update(_record_ids(edge, "gate_ids", MAX_WINDOW_FACTS))
        facts.update(_record_ids(edge, "effect_ids", MAX_WINDOW_FACTS))
    return {
        "work_units": len(scope_ids) + len(windows),
        "deterministic_scopes": len(scope_ids),
        "windows": len(windows),
        "nodes": len(nodes),
        "internal_edges": len(internal_edges),
        "boundary_nodes": len(boundary_nodes),
        "boundary_edges": len(boundary_edges),
        "evidence": len(evidence),
        "facts": len(facts),
    }


def _record_ids(record: dict[str, object], name: str, maximum: int) -> tuple[str, ...]:
    value = record.get(name)
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{name} must be a bounded string array")
    result = tuple(_object_string(item, name) for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must contain unique strings")
    return result


def _empty_selected_counts() -> dict[str, int]:
    return {
        "work_units": 0,
        "deterministic_scopes": 0,
        "windows": 0,
        "nodes": 0,
        "internal_edges": 0,
        "boundary_nodes": 0,
        "boundary_edges": 0,
        "evidence": 0,
        "facts": 0,
    }


def _consent_snapshot(prepared: dict[str, object]) -> dict[str, JsonValue]:
    value = json_value(
        {
            "scope_ids": prepared["scope_ids"],
            "window_ids": prepared["window_ids"],
            "selected_counts": prepared["selected_counts"],
            "cached": prepared["cached"],
            "validated": prepared["validated"],
            "model": prepared["model"],
            "budgets": prepared["budgets"],
            "selection_hash": prepared["selection_hash"],
            "prepared_authority_hash": prepared["authority_hash"],
            "recovered_source_acknowledgement": prepared["recovered_source_acknowledgement"],
        }
    )
    if not isinstance(value, dict):
        raise TypeError("prepared consent snapshot must be an object")
    return value


def _strict_start_binding(prepared: dict[str, object]) -> dict[str, JsonValue]:
    value = json_value(
        {
            "run_id": prepared["run_id"],
            "scope_ids": prepared["scope_ids"],
            "window_ids": prepared["window_ids"],
            "selection_hash": prepared["selection_hash"],
            "authority_hash": prepared["authority_hash"],
            "recovered_source_acknowledgement": prepared["recovered_source_acknowledgement"],
            "model": prepared["model"],
            "budgets": prepared["budgets"],
        }
    )
    if not isinstance(value, dict):
        raise TypeError("strict start binding must be an object")
    return value


def _selected_checkpoint_counts(raw_statuses: object, selected_ids: set[str]) -> tuple[int, int]:
    if not isinstance(raw_statuses, list):
        return 0, 0
    cached = 0
    validated = 0
    for item in raw_statuses:
        if not isinstance(item, dict) or item.get("scope_id") not in selected_ids:
            continue
        cached += item.get("status") == CheckpointStatus.CACHED.value
        validated += item.get("status") == CheckpointStatus.VALIDATED.value
    return cached, validated


def _story_view_node(
    node: PresentationNode,
    *,
    authoritative_unresolved: bool = False,
    authoritative_resolved: bool = False,
) -> dict[str, JsonValue]:
    folded_kind = node.kind.casefold()
    unresolved = authoritative_unresolved or (
        not authoritative_resolved and ("unresolved" in folded_kind or "dynamic" in folded_kind)
    )
    return {
        "id": node.id,
        "title": node.name,
        "summary": node.name,
        "kind": node.kind,
        "technical": node.technical,
        "unresolved": unresolved,
        "parent_id": node.parent_id,
        "source": None
        if node.source_path is None
        else {
            "path": node.source_path,
            "start_line": node.start_line,
            "end_line": node.end_line,
        },
        "evidence_count": node.child_count,
        "payload": json_value(node.payload),
    }


def _default_m07_provider_factory(_scope: RouteScope) -> OrganizationProvider:
    """Import and construct the cloud provider only from a confirmed scheduler worker."""

    from renpy_story_mapper.organization.contracts import CodexMode
    from renpy_story_mapper.organization.provider import CodexCliProvider

    return CodexCliProvider(CodexMode.CODEX_CHATGPT)


def _budget_policy(body: dict[str, JsonValue], *, with_finite_defaults: bool) -> BudgetPolicy:
    hard_seconds = optional_bounded_int(body, "hard_seconds", minimum=1, maximum=7_200)
    hard_tokens = optional_bounded_int(body, "hard_tokens", minimum=1, maximum=40_000_000)
    hard_calls = optional_bounded_int(body, "hard_calls", minimum=1, maximum=10_000)
    if with_finite_defaults:
        hard_seconds = 900 if hard_seconds is None else hard_seconds
        hard_tokens = 2_000_000 if hard_tokens is None else hard_tokens
        hard_calls = 48 if hard_calls is None else hard_calls
    return BudgetPolicy(
        soft_seconds=optional_bounded_int(body, "soft_seconds", minimum=1, maximum=3_600),
        hard_seconds=hard_seconds,
        soft_tokens=optional_bounded_int(body, "soft_tokens", minimum=1, maximum=20_000_000),
        hard_tokens=hard_tokens,
        hard_calls=hard_calls,
    )


def _validate_budget_order(budget: BudgetPolicy) -> None:
    if (
        budget.soft_seconds is not None
        and budget.hard_seconds is not None
        and budget.soft_seconds > budget.hard_seconds
    ):
        raise ValueError("soft_seconds cannot exceed hard_seconds")
    if (
        budget.soft_tokens is not None
        and budget.hard_tokens is not None
        and budget.soft_tokens > budget.hard_tokens
    ):
        raise ValueError("soft_tokens cannot exceed hard_tokens")
