"""Backend adapters and typed route dispatch for the local browser shell."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path
from typing import Protocol

from renpy_story_mapper.presentation import (
    MAX_RESULTS,
    PresentationLevel,
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
from renpy_story_mapper.story_organization import StoryOrganizationService
from renpy_story_mapper.web.contracts import (
    ApiErrorBody,
    JsonValue,
    SelectionResult,
    TaskStatus,
    boolean,
    bounded_int,
    json_value,
    optional_string,
    require_string,
    string_tuple,
)
from renpy_story_mapper.web.state import UserStateStore


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
        self, dialogs: DialogAdapter, *, state_store: UserStateStore | None = None
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
        self._state_store = state_store or UserStateStore()

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
                    "organization_start": "/api/v1/organization/consent",
                    "organization_draft": "/api/v1/organization/draft",
                    "organization_apply": "/api/v1/organization/apply",
                    "organization_discard": "/api/v1/organization/discard",
                    "diagnostics": "/api/v1/diagnostics",
                },
            }
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
        if method == "GET" and path == "/api/v1/organization/draft":
            return self._organization()
        if method == "POST" and path == "/api/v1/organization/consent":
            if not boolean(body, "consent"):
                raise ValueError("explicit consent is required")
            scopes = string_tuple(body, "scope_ids")
            return self._start("organization", lambda cancelled: self._organize(scopes, cancelled))
        if method == "POST" and path == "/api/v1/organization/apply":
            return self._draft_action(body, apply=True)
        if method == "POST" and path == "/api/v1/organization/discard":
            return self._draft_action(body, apply=False)
        if method == "GET" and path == "/api/v1/diagnostics":
            with self._lock:
                ready = self._project_path is not None
            return {
                "version": "0.1.0",
                "project_schema": 5 if ready else None,
                "browser_api": "v1",
                "provider_requests_on_open": 0,
                "messages": ["Rendering is bounded", "No provider is invoked by project open"],
            }
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
        self._state_store.record_project(path)

    def _create(self, path: Path, source: Path, cancelled: threading.Event) -> None:
        project = create_ingested_project(path, source, cancel_check=cancelled.is_set)
        project.close()
        with self._lock:
            self._project_path = path
            self._source_path = source
        self._state_store.record_project(path)

    def _refresh(self, cancelled: threading.Event) -> None:
        with self._lock:
            project, source = self._project_path, self._source_path
        if project is None or source is None:
            raise ApiProblem(409, "no_project", "Open a project first.")
        refresh_ingested_project(project, source, cancel_check=cancelled.is_set)

    def _project(self) -> Path:
        with self._lock:
            path = self._project_path
        if path is None:
            raise ApiProblem(409, "no_project", "Open a project first.")
        return path

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
        with PresentationService.open(self._project()) as service:
            page = service.view(request, selected_id=optional_string(body, "selected_id"))
        nodes = [
            {
                "id": node.id,
                "title": node.name,
                "summary": node.name,
                "kind": node.kind,
                "technical": node.technical,
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

    def _organization(self) -> JsonValue:
        with Project.open(self._project()) as project:
            service = StoryOrganizationService(project)
            drafts = service.drafts()
            return {
                "id": drafts[0].id if drafts else None,
                "runs": json_value(service.runs()),
                "drafts": json_value(drafts),
                "arcs": json_value(service.arcs()),
                "events": json_value(service.events()),
                "edges": json_value(service.event_edges()),
            }

    def _draft_action(self, body: dict[str, JsonValue], *, apply: bool) -> JsonValue:
        draft_id = require_string(body, "draft_id")
        with Project.open(self._project()) as project:
            service = StoryOrganizationService(project)
            if apply:
                service.apply_draft(draft_id)
            else:
                service.discard_draft(draft_id)
        return {"draft_id": draft_id, "status": "applied" if apply else "discarded"}

    def _organize(self, scope_ids: tuple[str, ...], cancelled: threading.Event) -> None:
        """Reuse the accepted M05 workflow; provider construction occurs only after consent."""

        from renpy_story_mapper.organization import CodexCliProvider
        from renpy_story_mapper.ui.organization_workflow import (
            OrganizationOptions,
            OrganizationWorkflow,
        )

        path = self._project()
        with Project.open(path) as project:
            workflow = OrganizationWorkflow(project, lambda mode: CodexCliProvider(mode))
            workflow.organize(
                scope_ids,
                OrganizationOptions(),
                progress=lambda percent, stage: self._organization_progress(percent, stage),
                cancelled=cancelled.is_set,
                confirm_cloud=lambda _run_id: True,
            )

    def _organization_progress(self, percent: int, stage: str) -> None:
        with self._lock:
            task = self._task
        if task is not None and task.kind == "organization":
            self._progress(task.id, task.kind, stage[:120], max(0, min(99, percent)))
