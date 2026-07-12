"""Backend adapters and typed route dispatch for the local browser shell."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path
from typing import Literal, Protocol

from renpy_story_mapper.m07_workflow import M07WorkflowService, ProviderFactory
from renpy_story_mapper.organization.contracts import OrganizationProvider
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
from renpy_story_mapper.story_organization import StoryOrganizationService
from renpy_story_mapper.web.contracts import (
    M07_API_ROUTES,
    ApiErrorBody,
    JsonValue,
    SelectionResult,
    TaskStatus,
    boolean,
    bounded_int,
    json_value,
    optional_bounded_int,
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
                    "organization_review": "/api/v1/organization/review",
                    "organization_apply": "/api/v1/organization/apply",
                    "organization_discard": "/api/v1/organization/discard",
                    "diagnostics": "/api/v1/diagnostics",
                    "shutdown": "/api/v1/shutdown",
                    "m07": dict(M07_API_ROUTES),
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
        if method == "POST" and path == M07_API_ROUTES["route_map"]:
            return json_value(
                self._m07_workflow().route_map(
                    offset=bounded_int(body, "offset", default=0, minimum=0, maximum=2_000_000),
                    limit=bounded_int(body, "limit", default=30, minimum=1, maximum=30),
                )
            )
        if method == "POST" and path == M07_API_ROUTES["detail"]:
            try:
                return json_value(self._m07_workflow().detail(require_string(body, "element_id")))
            except KeyError as exc:
                raise ApiProblem(
                    404, "m07_element_not_found", "The route-map element is unavailable."
                ) from exc
        if method == "GET" and path == M07_API_ROUTES["organization"]:
            with self._lock:
                task = self._task
            stage = task.stage if task is not None and task.kind == "m07_organization" else "idle"
            return json_value(self._m07_workflow().status(stage=stage))
        if method == "POST" and path == M07_API_ROUTES["prepare"]:
            budget = BudgetPolicy(
                soft_seconds=optional_bounded_int(body, "soft_seconds", minimum=1, maximum=3_600),
                hard_seconds=optional_bounded_int(body, "hard_seconds", minimum=1, maximum=7_200),
                soft_tokens=optional_bounded_int(
                    body, "soft_tokens", minimum=1, maximum=20_000_000
                ),
                hard_tokens=optional_bounded_int(
                    body, "hard_tokens", minimum=1, maximum=40_000_000
                ),
                hard_calls=optional_bounded_int(body, "hard_calls", minimum=1, maximum=10_000),
            )
            _validate_budget_order(budget)
            return json_value(
                self._m07_workflow().prepare(
                    scope_ids=string_tuple(body, "scope_ids", maximum_items=10_000),
                    budget=budget,
                )
            )
        if method == "POST" and path == M07_API_ROUTES["start"]:
            workflow = self._m07_workflow()
            prepared = workflow.authorize_start(
                require_string(body, "run_id"),
                confirm_cloud=boolean(body, "confirm_cloud"),
            )

            def run_m07(cancelled: threading.Event) -> None:
                workflow.run_prepared(
                    prepared,
                    cancelled=cancelled.is_set,
                    progress=self._m07_progress,
                )

            return self._start(
                "m07_organization",
                run_m07,
            )
        if method == "POST" and path == M07_API_ROUTES["cancel"]:
            self.cancel()
            return {"state": "cancelling"}
        if method == "POST" and path == M07_API_ROUTES["assembly_apply"]:
            try:
                return json_value(self._m07_workflow().apply(require_string(body, "assembly_id")))
            except KeyError as exc:
                raise ApiProblem(
                    404, "m07_assembly_not_found", "The assembly is unavailable."
                ) from exc
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
        if method == "POST" and path == "/api/v1/organization/review":
            return self._review_draft(body)
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
        self._state_store.record_project(path)

    def _create(self, path: Path, source: Path, cancelled: threading.Event) -> None:
        project = create_ingested_project(path, source, cancel_check=cancelled.is_set)
        project.close()
        with self._lock:
            self._project_path = path
            self._source_path = source
            self._m07_service = None
            self._m07_service_path = None
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

    def _m07_workflow(self) -> M07WorkflowService:
        path = self._project()
        with self._lock:
            if self._m07_service is None or self._m07_service_path != path:
                self._m07_service = M07WorkflowService(path, self._m07_provider_factory)
                self._m07_service_path = path
            return self._m07_service

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

    def _organization(self) -> JsonValue:
        with Project.open(self._project()) as project:
            service = StoryOrganizationService(project)
            drafts = service.drafts(status="pending")
            return {
                "id": drafts[0].id if drafts else None,
                "runs": json_value(service.runs()),
                "drafts": json_value(drafts),
                "reviews": {
                    draft.id: json_value(service.draft_reviews(draft.id)) for draft in drafts
                },
                "arcs": json_value(service.arcs()),
                "events": json_value(service.events()),
                "edges": json_value(service.event_edges()),
            }

    def _draft_action(self, body: dict[str, JsonValue], *, apply: bool) -> JsonValue:
        draft_id = require_string(body, "draft_id")
        try:
            with Project.open(self._project()) as project:
                service = StoryOrganizationService(project)
                if apply:
                    service.apply_draft(draft_id)
                else:
                    service.discard_draft(draft_id)
        except KeyError as exc:
            raise ApiProblem(404, "draft_not_found", "The pending draft is unavailable.") from exc
        except ValueError as exc:
            code = "draft_review_incomplete" if apply else "draft_action_invalid"
            raise ApiProblem(409, code, "The draft action cannot be completed safely.") from exc
        return {"draft_id": draft_id, "status": "applied" if apply else "discarded"}

    def _review_draft(self, body: dict[str, JsonValue]) -> JsonValue:
        draft_id = require_string(body, "draft_id")
        target_kind = require_string(body, "target_kind", maximum=16)
        target_id = require_string(body, "target_id")
        decision = require_string(body, "decision", maximum=16)
        review_kind: Literal["arc", "event"]
        if target_kind == "arc":
            review_kind = "arc"
        elif target_kind == "event":
            review_kind = "event"
        else:
            raise ValueError("invalid draft review")
        review_decision: Literal["approved", "rejected"]
        if decision == "approved":
            review_decision = "approved"
        elif decision == "rejected":
            review_decision = "rejected"
        else:
            raise ValueError("invalid draft review")
        try:
            with Project.open(self._project()) as project:
                StoryOrganizationService(project).review_draft_group(
                    draft_id, review_kind, target_id, review_decision
                )
        except KeyError as exc:
            raise ApiProblem(
                404, "draft_group_not_found", "The pending draft group is unavailable."
            ) from exc
        except ValueError as exc:
            raise ApiProblem(409, "draft_review_invalid", "The draft review is invalid.") from exc
        return {
            "draft_id": draft_id,
            "target_kind": target_kind,
            "target_id": target_id,
            "decision": decision,
        }

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

    def _m07_progress(self, progress: ProgressSnapshot) -> None:
        with self._lock:
            task = self._task
        if task is not None and task.kind == "m07_organization":
            completed = (
                progress.validated + progress.fallback + progress.failed + progress.cancelled
            )
            percent = 0 if progress.total == 0 else round(completed * 100 / progress.total)
            self._progress(task.id, task.kind, "organizing route scopes", min(99, percent))


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

    from renpy_story_mapper.organization import CodexCliProvider, CodexMode

    return CodexCliProvider(CodexMode.CODEX_CHATGPT)


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
