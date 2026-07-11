"""Background bridge from the bounded presentation model to the native Qt canvas."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QListWidget

from renpy_story_mapper.presentation import (
    EvidenceRecord,
    FactRecord,
    PresentationEdge,
    PresentationLevel,
    PresentationNode,
    PresentationRequest,
    PresentationService,
    SearchHit,
)
from renpy_story_mapper.project import ProjectCancelledError
from renpy_story_mapper.storage import ProjectOperationCancelled
from renpy_story_mapper.ui.graph_canvas import (
    GraphCanvas,
    GraphEdgeSpec,
    GraphNodeSpec,
    SemanticLevel,
    SourceEvidence,
)
from renpy_story_mapper.ui.project_controller import ProjectSession
from renpy_story_mapper.ui.workers import CancelCheck, ProgressReporter, WorkerTask


@dataclass(frozen=True)
class _MapResult:
    level: SemanticLevel
    nodes: tuple[GraphNodeSpec, ...]
    edges: tuple[GraphEdgeSpec, ...]
    has_more: bool


@dataclass(frozen=True)
class _SearchResult:
    hit_ids: tuple[str, ...]
    target_id: str | None
    lineage: tuple[PresentationNode, ...]


class StoryMapPresenter(QObject):
    """Coordinate bounded background queries and interactive map state."""

    status_changed = Signal(str)
    error_occurred = Signal(str)
    busy_changed = Signal(bool)

    def __init__(
        self,
        canvas: GraphCanvas,
        evidence_list: QListWidget,
        diagnostics_list: QListWidget,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.canvas = canvas
        self.evidence_list = evidence_list
        self.diagnostics_list = diagnostics_list
        self._project_path: Path | None = None
        self._task: WorkerTask | None = None
        self._pending: tuple[
            Callable[[CancelCheck, ProgressReporter], object], Callable[[object], None], str
        ] | None = None
        self._generation = 0
        self._level = SemanticLevel.OVERVIEW
        self._selected_id: str | None = None
        self._selected_by_level: dict[SemanticLevel, str] = {}
        self._last_nodes: dict[SemanticLevel, tuple[str, ...]] = {}
        self._expanded_overview: set[str] = set()
        self._expanded_events: set[str] = set()
        self._include_technical = False
        self._focus_after_render: str | None = None
        self._continue_to_evidence = False
        self._render_suppressed = False

        canvas.semantic_level_changed.connect(self.set_level)
        canvas.expansion_requested.connect(self._expansion_requested)
        canvas.selection_changed.connect(self._selection_changed)
        canvas.render_limit_reached.connect(self._render_limit_reached)

    @property
    def is_busy(self) -> bool:
        return self._task is not None

    @property
    def level(self) -> SemanticLevel:
        return self._level

    @property
    def selected_overview_scope_ids(self) -> tuple[str, ...]:
        """Return the chosen Level-1 scope, or the currently loaded bounded Level-1 set."""

        selected = self._selected_by_level.get(SemanticLevel.OVERVIEW)
        if selected is not None:
            return (selected,)
        return self._last_nodes.get(SemanticLevel.OVERVIEW, ())

    def set_project(self, session: ProjectSession | None) -> None:
        self._generation += 1
        self.cancel(clear_pending=True)
        self._render_suppressed = False
        self._project_path = None if session is None else session.project_path
        self._level = SemanticLevel.OVERVIEW
        self._selected_id = None
        self._selected_by_level.clear()
        self._last_nodes.clear()
        self._expanded_overview.clear()
        self._expanded_events.clear()
        self._focus_after_render = None
        self._continue_to_evidence = False
        self.evidence_list.clear()
        self.canvas.set_slice((), (), preserve_navigation=False)
        self.canvas.set_semantic_level(SemanticLevel.OVERVIEW)
        if session is not None:
            self._load_map()

    def set_render_suppressed(self, suppressed: bool) -> None:
        """Keep deterministic scope loading available without replacing an accepted map."""

        self._render_suppressed = suppressed
        if not suppressed and self._project_path is not None and self._task is None:
            self._load_map()

    def cancel(self, *, clear_pending: bool = True) -> None:
        if clear_pending:
            self._pending = None
        if self._task is not None:
            self._task.cancel()
            self.status_changed.emit("Cancelling map operation")

    @Slot(int)
    def set_level(self, value: int) -> None:
        if self._render_suppressed:
            return
        level = SemanticLevel(value)
        if level == self._level:
            return
        if level is SemanticLevel.EVENTS:
            parent = self._selected_by_level.get(SemanticLevel.OVERVIEW)
            if parent is None:
                parent = _first(self._last_nodes.get(SemanticLevel.OVERVIEW, ()))
            if parent is not None:
                self._expanded_overview.add(parent)
        elif level is SemanticLevel.EVIDENCE:
            parent = self._selected_by_level.get(SemanticLevel.EVENTS)
            if parent is None:
                parent = _first(self._last_nodes.get(SemanticLevel.EVENTS, ()))
            if parent is None:
                root = self._selected_by_level.get(SemanticLevel.OVERVIEW)
                if root is None:
                    root = _first(self._last_nodes.get(SemanticLevel.OVERVIEW, ()))
                if root is not None:
                    self._expanded_overview.add(root)
                    self._continue_to_evidence = True
                    self._level = SemanticLevel.EVENTS
                    self._load_map()
                    return
            else:
                self._expanded_events.add(parent)
        self._level = level
        self._load_map()

    def go_up(self) -> None:
        if self._level is SemanticLevel.EVIDENCE:
            self.canvas.set_semantic_level(SemanticLevel.EVENTS)
        elif self._level is SemanticLevel.EVENTS:
            self.canvas.set_semantic_level(SemanticLevel.OVERVIEW)

    def set_include_technical(self, include: bool) -> None:
        self._include_technical = include
        if not self._render_suppressed:
            self._load_map()

    def search(self, query: str) -> None:
        term = query.strip()
        if not term:
            self.canvas.set_search_results(())
            return
        project_path = self._project_path
        if project_path is None:
            return
        token = self._generation

        def operation(cancelled: CancelCheck, _progress: ProgressReporter) -> object:
            with PresentationService.open(project_path, cancelled=cancelled) as service:
                hits = tuple(
                    cast(SearchHit, item) for item in service.search(term, limit=100).items
                )
                if cancelled():
                    raise ProjectOperationCancelled("map query cancelled")
                target = next(
                    (hit for hit in hits if service.lineage(hit.node_id)), None
                )
                lineage = () if target is None else service.lineage(target.node_id)
                return token, _SearchResult(
                    tuple(dict.fromkeys(hit.node_id for hit in hits)),
                    None if target is None else target.node_id,
                    lineage,
                )

        self._start(operation, self._accept_search, "Searching map")

    def rename_selected(self, name: str) -> None:
        selected = self._selected_id
        if selected is None or not name.strip():
            return
        self._mutate(
            lambda service: service.rename_node(selected, name.strip()),
            "Renaming map item",
        )

    def reset_selected_name(self) -> None:
        selected = self._selected_id
        if selected is not None:
            self._mutate(lambda service: service.rename_node(selected, None), "Resetting name")

    def hide_selected(self) -> None:
        selected = self._selected_id
        if selected is not None:
            self._mutate(lambda service: service.set_hidden(selected, True), "Hiding map item")
            self._selected_id = None

    def update_state_variable(
        self, original_name: str, display_name: str, category: str
    ) -> None:
        original = original_name.strip()
        display = display_name.strip()
        group = category.strip()
        if not original or (not display and not group):
            return
        self._mutate(
            lambda service: service.update_state_variable(
                original,
                display_name=display or None,
                category=group or None,
            ),
            "Updating state variable",
        )

    def _mutate(
        self, action: Callable[[PresentationService], None], status: str
    ) -> None:
        project_path = self._project_path
        if project_path is None:
            return
        token = self._generation

        def operation(cancelled: CancelCheck, _progress: ProgressReporter) -> object:
            with PresentationService.open(project_path, cancelled=cancelled) as service:
                action(service)
            return token

        self._start(operation, self._accept_mutation, status)

    @Slot(str, bool)
    def _expansion_requested(self, node_id: str, expanded: bool) -> None:
        if self._render_suppressed:
            return
        if self._level is SemanticLevel.OVERVIEW:
            _set_membership(self._expanded_overview, node_id, expanded)
            if expanded:
                self._selected_by_level[SemanticLevel.OVERVIEW] = node_id
                self.canvas.set_semantic_level(SemanticLevel.EVENTS)
            else:
                self._load_map()
        elif self._level is SemanticLevel.EVENTS:
            _set_membership(self._expanded_events, node_id, expanded)
            if expanded:
                self._selected_by_level[SemanticLevel.EVENTS] = node_id
                self.canvas.set_semantic_level(SemanticLevel.EVIDENCE)
            else:
                self._load_map()

    @Slot(object)
    def _selection_changed(self, value: object) -> None:
        if self._render_suppressed:
            return
        self._selected_id = value if isinstance(value, str) else None
        if self._selected_id is None:
            self.evidence_list.clear()
            return
        self._selected_by_level[self._level] = self._selected_id
        self._load_evidence(self._selected_id)

    @Slot(int)
    def _render_limit_reached(self, count: int) -> None:
        self.diagnostics_list.addItem(f"Map render bound reached at {count} items")

    def _load_map(self) -> None:
        project_path = self._project_path
        if project_path is None:
            return
        token = self._generation
        level = self._level
        parent_ids: tuple[str, ...] = ()
        if level is SemanticLevel.EVENTS:
            parent_ids = tuple(sorted(self._expanded_overview))
        elif level is SemanticLevel.EVIDENCE:
            parent_ids = tuple(sorted(self._expanded_events))
        request = PresentationRequest(
            PresentationLevel(int(level)),
            parent_ids=parent_ids,
            focus_ids=(self._focus_after_render,) if self._focus_after_render is not None else (),
            node_limit=80,
            edge_limit=120,
            include_technical=self._include_technical,
        )

        def operation(cancelled: CancelCheck, progress: ProgressReporter) -> object:
            progress(5, "Opening map index")
            with PresentationService.open(project_path, cancelled=cancelled) as service:
                page = service.view(request, selected_id=self._selected_id)
                raw_nodes: list[
                    tuple[PresentationNode, tuple[FactRecord, ...], tuple[EvidenceRecord, ...]]
                ] = []
                variable_names: set[str] = set()
                for index, node in enumerate(page.nodes):
                    if cancelled():
                        raise ProjectOperationCancelled("map query cancelled")
                    base_facts = tuple(
                        cast(FactRecord, item)
                        for item in service.facts(node_id=node.id, limit=12).items
                    )
                    outcome_facts = (
                        tuple(
                            cast(FactRecord, item)
                            for item in service.choice_outcome_facts(node.id, limit=50).items
                        )
                        if node.kind == "choice_group"
                        else ()
                    )
                    facts = tuple(
                        {fact.id: fact for fact in (*base_facts, *outcome_facts)}.values()
                    )
                    variable_names.update(
                        fact.variable for fact in facts if fact.variable is not None
                    )
                    evidence = (
                        tuple(
                            cast(EvidenceRecord, item)
                            for item in service.evidence(node.id, limit=12).items
                        )
                        if level is not SemanticLevel.OVERVIEW
                        else ()
                    )
                    raw_nodes.append((node, facts, evidence))
                    progress(10 + int((index + 1) * 70 / max(1, len(page.nodes))), "Loading map")
                display_names = service.variable_display_names(variable_names)
                specs = tuple(
                    _graph_node(
                        node,
                        facts,
                        evidence,
                        display_names,
                        level,
                        self._expanded_ids(level),
                    )
                    for node, facts, evidence in raw_nodes
                )
                if cancelled():
                    raise ProjectOperationCancelled("map query cancelled")
                progress(90, "Laying out map")
                edges = tuple(_graph_edge(edge) for edge in page.edges)
                result = _MapResult(
                    level,
                    specs,
                    edges,
                    page.node_continuation.has_more or page.edge_continuation.has_more,
                )
            progress(100, "Map ready")
            return token, result

        self._start(operation, self._accept_map, "Loading map")

    def _load_evidence(self, node_id: str) -> None:
        project_path = self._project_path
        if project_path is None:
            return
        token = self._generation

        def operation(cancelled: CancelCheck, _progress: ProgressReporter) -> object:
            with PresentationService.open(project_path, cancelled=cancelled) as service:
                records = tuple(
                    cast(EvidenceRecord, item) for item in service.evidence(node_id, limit=50).items
                )
            return token, node_id, records

        self._start(operation, self._accept_evidence, "Loading source evidence")

    def _start(
        self,
        operation: Callable[[CancelCheck, ProgressReporter], object],
        accept: Callable[[object], None],
        status: str,
    ) -> None:
        if self._task is not None:
            self._pending = (operation, accept, status)
            self._task.cancel()
            return
        task = WorkerTask(operation, self)
        self._task = task
        task.progress.connect(lambda _percent, message: self.status_changed.emit(message))
        task.succeeded.connect(accept)
        task.failed.connect(self._failure)
        task.finished.connect(self._finished)
        self.busy_changed.emit(True)
        self.status_changed.emit(status)
        task.start()

    @Slot(object)
    def _accept_map(self, value: object) -> None:
        token, result = cast(tuple[int, _MapResult], value)
        if token != self._generation:
            return
        self._last_nodes[result.level] = tuple(node.id for node in result.nodes)
        if self._render_suppressed:
            return
        self.canvas.set_semantic_level(result.level)
        self.canvas.set_slice(result.nodes, result.edges, preserve_navigation=True)
        restored = self._selected_by_level.get(result.level)
        if restored is not None and self.canvas.restore_selection(restored):
            self._selected_id = restored
        if self._continue_to_evidence and result.level is SemanticLevel.EVENTS:
            event = _first(tuple(node.id for node in result.nodes))
            self._continue_to_evidence = False
            if event is not None:
                self._expanded_events.add(event)
                self._level = SemanticLevel.EVIDENCE
                self.canvas.set_semantic_level(SemanticLevel.EVIDENCE)
                self._load_map()
                return
        if self._focus_after_render is not None and self.canvas.focus_search_result(
            self._focus_after_render
        ):
            self._focus_after_render = None
        suffix = " - more available" if result.has_more else ""
        self.status_changed.emit(
            f"Level {int(result.level)} - {len(result.nodes)} items{suffix}"
        )

    @Slot(object)
    def _accept_search(self, value: object) -> None:
        token, result = cast(tuple[int, _SearchResult], value)
        if token != self._generation:
            return
        self.canvas.set_search_results(result.hit_ids)
        if result.target_id is None:
            self.status_changed.emit("No search results")
            return
        if self.canvas.focus_search_result(result.target_id):
            self.status_changed.emit(f"Search found {len(result.hit_ids)} matches")
            return
        lineage = result.lineage
        if lineage:
            root = lineage[0]
            self._expanded_overview.add(root.id)
            if len(lineage) > 1:
                self._expanded_events.add(lineage[1].id)
            target_level = SemanticLevel(int(lineage[-1].level))
            self._level = target_level
            self._focus_after_render = result.target_id
            self.canvas.set_semantic_level(target_level)
            self._load_map()

    @Slot(object)
    def _accept_evidence(self, value: object) -> None:
        token, node_id, records = cast(tuple[int, str, tuple[EvidenceRecord, ...]], value)
        if token != self._generation or node_id != self._selected_id:
            return
        self.evidence_list.clear()
        for record in records:
            span = (
                str(record.start_line)
                if record.start_line == record.end_line
                else f"{record.start_line}-{record.end_line}"
            )
            self.evidence_list.addItem(
                f"{record.source_path}:{span}  {record.text.strip()}"
            )
        if not records:
            self.evidence_list.addItem("No exact source evidence for this item")
        self.status_changed.emit(f"Source evidence - {len(records)} records")

    @Slot(object)
    def _accept_mutation(self, value: object) -> None:
        if cast(int, value) == self._generation:
            self._load_map()

    @Slot(object)
    def _failure(self, value: object) -> None:
        error = cast(BaseException, value)
        if isinstance(error, (ProjectCancelledError, ProjectOperationCancelled)):
            return
        self.diagnostics_list.addItem("The map operation failed safely")
        self.error_occurred.emit("The map operation failed safely.")

    @Slot()
    def _finished(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.deleteLater()
        self.busy_changed.emit(False)
        pending = self._pending
        self._pending = None
        if pending is not None:
            self._start(*pending)

    def _expanded_ids(self, level: SemanticLevel) -> frozenset[str]:
        if level is SemanticLevel.OVERVIEW:
            return frozenset(self._expanded_overview)
        if level is SemanticLevel.EVENTS:
            return frozenset(self._expanded_events)
        return frozenset()


def _graph_node(
    node: PresentationNode,
    facts: tuple[FactRecord, ...],
    records: tuple[EvidenceRecord, ...],
    display_names: Mapping[str, str],
    level: SemanticLevel,
    expanded_ids: frozenset[str],
) -> GraphNodeSpec:
    requirements = tuple(
        _display_expression(fact, display_names) for fact in facts if fact.kind == "gate"
    )
    effects = tuple(
        _display_expression(fact, display_names) for fact in facts if fact.kind == "effect"
    )
    evidence = tuple(
        SourceEvidence(
            record.source_path,
            record.start_line,
            record.end_line,
            record.text,
        )
        for record in records
    )
    if (
        not evidence
        and node.source_path is not None
        and node.start_line is not None
        and node.end_line is not None
    ):
        evidence = (SourceEvidence(node.source_path, node.start_line, node.end_line, node.name),)
    variables = frozenset(fact.variable for fact in facts if fact.variable is not None)
    categories = frozenset(fact.category for fact in facts if fact.category is not None)
    return GraphNodeSpec(
        id=node.id,
        kind=_visual_kind(node),
        title=node.name,
        summary=_summary(node, records),
        detail=(
            ""
            if node.source_path is None or node.start_line is None
            else f"{node.source_path}:{node.start_line}"
        ),
        semantic_levels=frozenset({level}),
        requirements=requirements,
        effects=effects,
        variables=variables,
        categories=categories,
        evidence=evidence,
        expandable=node.expandable,
        expanded=node.id in expanded_ids,
    )


def _graph_edge(edge: PresentationEdge) -> GraphEdgeSpec:
    return GraphEdgeSpec(edge.source_id, edge.target_id, edge.kind)


def _display_expression(fact: FactRecord, display_names: Mapping[str, str]) -> str:
    variable = fact.variable
    if variable is None:
        return fact.expression
    display_name = display_names.get(variable, variable)
    if display_name == variable:
        return fact.expression
    return re.sub(rf"\b{re.escape(variable)}\b", display_name, fact.expression)


def _visual_kind(node: PresentationNode) -> str:
    if node.technical:
        return "technical"
    if node.level is PresentationLevel.OVERVIEW:
        return "container"
    if node.kind == "choice_group" or node.kind == "choice":
        return "choice"
    if node.kind in {"condition_group", "condition"}:
        return "gate"
    if node.kind in {"jump", "call", "shared_call", "merge", "loop", "return", "ending"}:
        return node.kind
    if "unresolved" in node.kind or "dynamic" in node.kind:
        return "unresolved"
    return "event" if node.level is PresentationLevel.EVENT else "story"


def _summary(node: PresentationNode, records: tuple[EvidenceRecord, ...]) -> str:
    if node.level is PresentationLevel.OVERVIEW:
        return f"{node.child_count} deterministic event groups"
    if node.level is PresentationLevel.EVENT:
        choices: list[str] = []
        for record in records:
            if not isinstance(record.payload, dict):
                continue
            raw_choices = record.payload.get("choices")
            if not isinstance(raw_choices, list):
                continue
            choices.extend(
                str(choice.get("caption"))
                for choice in raw_choices
                if isinstance(choice, dict) and choice.get("caption")
            )
        if choices:
            return "Choices: " + " / ".join(choices[:4])
        return "Deterministic structural group; AI scene grouping is not applied"
    payload = node.payload
    if isinstance(payload, dict):
        content = payload.get("content")
        if isinstance(content, list):
            texts = [
                str(item.get("text"))
                for item in content
                if isinstance(item, dict) and item.get("text")
            ]
            if texts:
                return " ".join(texts[:2])
        source = payload.get("source_text")
        if isinstance(source, str):
            return source
    return node.kind.replace("_", " ")


def _first(values: tuple[str, ...]) -> str | None:
    return values[0] if values else None


def _set_membership(values: set[str], item: str, included: bool) -> None:
    if included:
        values.add(item)
    else:
        values.discard(item)


__all__ = ["StoryMapPresenter"]
