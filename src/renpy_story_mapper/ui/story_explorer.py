"""Arc-first Story Explorer widgets and background presentation controllers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from renpy_story_mapper import storage
from renpy_story_mapper.organization import (
    CodexCliProvider,
    CodexMode,
    OrganizationProvider,
)
from renpy_story_mapper.organization.errors import (
    OrganizationCancelledError,
    OrganizationError,
)
from renpy_story_mapper.presentation import (
    EvidenceRecord,
    PresentationService,
    SearchHit,
)
from renpy_story_mapper.project import Project
from renpy_story_mapper.story_organization import (
    AttachedFact,
    DraftReview,
    OrganizationDraft,
    OrganizationRun,
    StoryArc,
    StoryClaim,
    StoryEdge,
    StoryEvent,
    StoryOrganizationService,
)
from renpy_story_mapper.ui.graph_canvas import (
    GraphCanvas,
    GraphEdgeSpec,
    GraphNodeSpec,
    SemanticLevel,
    SourceEvidence,
)
from renpy_story_mapper.ui.organization_workflow import (
    OrganizationOptions,
    OrganizationWorkflow,
    WorkflowResult,
)
from renpy_story_mapper.ui.project_controller import ProjectSession
from renpy_story_mapper.ui.story_layout import (
    LayoutEdge,
    LayoutInput,
    LayoutNode,
    layout_story_events,
)
from renpy_story_mapper.ui.workers import WorkerTask

MAX_ARCS = 12
MAX_EVENTS = 30
MAX_VISIBLE_ITEMS = 240
MAX_REVIEW_ITEMS = 240


@dataclass(frozen=True)
class StorySnapshot:
    arcs: tuple[StoryArc, ...]
    events: tuple[StoryEvent, ...]
    event_edges: tuple[StoryEdge, ...]
    arc_edges: tuple[StoryEdge, ...]
    facts: tuple[AttachedFact, ...]
    claims: tuple[StoryClaim, ...]
    pending_draft: OrganizationDraft | None
    latest_run: OrganizationRun | None
    draft_reviews: tuple[DraftReview, ...] = ()
    event_characters: tuple[tuple[str, tuple[str, ...]], ...] = ()
    enrichments: tuple[object, ...] = ()
    event_filters: tuple[
        tuple[str, tuple[str, ...], tuple[str, ...]], ...
    ] = ()


@dataclass(frozen=True)
class _EvidenceSlice:
    records: tuple[EvidenceRecord, ...]
    truncated: bool


class WelcomeWidget(QWidget):
    """Purposeful empty state with recent projects and safe primary actions."""

    open_folder = Signal()
    open_archive = Signal()
    open_project = Signal()
    recent_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("welcomePage")
        root = QVBoxLayout(self)
        root.setContentsMargins(72, 56, 72, 56)
        root.setSpacing(18)
        eyebrow = QLabel("REN'PY STORY MAPPER", self)
        eyebrow.setObjectName("welcomeEyebrow")
        title = QLabel("Read the story, not the script maze.", self)
        title.setObjectName("welcomeTitle")
        safety = QLabel("Static analysis only. The game is never executed or modified.", self)
        safety.setObjectName("welcomeSafety")
        actions = QHBoxLayout()
        self.folder_button = QPushButton("Open Game Folder", self)
        self.folder_button.setObjectName("welcomeOpenFolder")
        self.archive_button = QPushButton("Open Archive", self)
        self.archive_button.setObjectName("welcomeOpenArchive")
        self.project_button = QPushButton("Open Project", self)
        self.project_button.setObjectName("welcomeOpenProject")
        for button, name in (
            (self.folder_button, "Open a Ren'Py game folder"),
            (self.archive_button, "Open a Ren'Py scripts archive"),
            (self.project_button, "Open an existing Story Mapper project"),
        ):
            button.setAccessibleName(name)
            actions.addWidget(button)
        recent_title = QLabel("Recent projects", self)
        recent_title.setObjectName("recentProjectsTitle")
        self.recent_list = QListWidget(self)
        self.recent_list.setObjectName("recentProjects")
        self.recent_list.setAccessibleName("Recent Story Mapper projects")
        self.recent_list.setAlternatingRowColors(True)
        root.addWidget(eyebrow)
        root.addWidget(title)
        root.addWidget(safety)
        root.addLayout(actions)
        root.addSpacing(12)
        root.addWidget(recent_title)
        root.addWidget(self.recent_list, 1)
        self.folder_button.clicked.connect(self.open_folder)
        self.archive_button.clicked.connect(self.open_archive)
        self.project_button.clicked.connect(self.open_project)
        self.recent_list.itemActivated.connect(
            lambda item: self.recent_selected.emit(str(item.data(Qt.ItemDataRole.UserRole)))
        )

    def set_recent_projects(self, values: Sequence[tuple[str, str, str, str]]) -> None:
        self.recent_list.clear()
        for path, source_kind, last_opened, organization in values:
            item = QListWidgetItem(
                f"{Path(path).stem}\n{source_kind.title()}  •  {last_opened}  •  {organization}"
            )
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setData(
                Qt.ItemDataRole.AccessibleTextRole,
                f"{Path(path).stem}, {source_kind}, {last_opened}, {organization}"
            )
            self.recent_list.addItem(item)


class InspectorTabs(QTabWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("storyInspector")
        self.setAccessibleName("Story inspector")
        self.summary = QLabel("Select a story card", self)
        self.summary.setObjectName("inspectorSummary")
        self.summary.setWordWrap(True)
        self.state = QListWidget(self)
        self.state.setObjectName("inspectorState")
        self.evidence = QListWidget(self)
        self.evidence.setObjectName("sourceEvidenceInspector")
        self.details = QLabel("", self)
        self.details.setObjectName("inspectorDetails")
        self.details.setWordWrap(True)
        self.addTab(_padded(self.summary), "Summary")
        self.addTab(self.state, "Choices & State")
        self.addTab(self.evidence, "Evidence")
        self.addTab(_padded(self.details), "Details")
        for index in range(self.count()):
            page = self.widget(index)
            if page is not None:
                page.setAccessibleName(f"{self.tabText(index)} inspector tab")


class _LegacyDraftReviewDialog(QDialog):
    review_requested = Signal(str, str, str)
    apply_requested = Signal(str)
    discard_requested = Signal(str)

    def __init__(
        self,
        draft: OrganizationDraft,
        run: OrganizationRun | None,
        current_arcs: Sequence[StoryArc],
        current_events: Sequence[StoryEvent],
        reviews: Sequence[DraftReview],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.draft = draft
        self.setObjectName("draftReviewDialog")
        self.setWindowTitle("Review organized story")
        self.resize(920, 680)
        root = QVBoxLayout(self)
        metadata = QLabel(self)
        metadata.setObjectName("draftMetadata")
        if run is None:
            metadata.setText("Validated draft • provider metadata unavailable")
        else:
            location = "Local" if "lmstudio" in run.provider_mode else "Cloud"
            metadata.setText(
                f"{location} • {run.model_profile} • {run.prompt_version} • "
                f"{run.elapsed_ms or 0} ms"
            )
        root.addWidget(metadata)
        usage = run.usage if run is not None and isinstance(run.usage, dict) else {}
        model = "Default model"
        if run is not None and run.model_fingerprint:
            model = run.model_fingerprint
        self.provider_metadata = QLabel(
            (
                f"Provider: {run.provider_mode if run else 'unavailable'}  •  Model: {model}  •  "
                f"Profile: {run.model_profile if run else 'unavailable'}  •  "
                f"Schema: {run.output_schema_version if run else 'unavailable'}  •  "
                f"Cache hits: {usage.get('cache_hits', 0)}  •  "
                f"Provider calls: {usage.get('provider_calls', 0)}  •  "
                f"Context: {usage.get('context_window_tokens', 'unknown')}  •  "
                f"Tokens: {usage.get('input_tokens', 0)} in / "
                f"{usage.get('output_tokens', 0)} out"
            ),
            self,
        )
        self.provider_metadata.setObjectName("draftProviderMetadata")
        self.provider_metadata.setWordWrap(True)
        root.addWidget(self.provider_metadata)
        self.comparison_summary = QLabel(self)
        self.comparison_summary.setObjectName("draftComparisonSummary")
        self.comparison_summary.setWordWrap(True)
        root.addWidget(self.comparison_summary)
        self.comparison = QListWidget(self)
        self.comparison.setObjectName("draftComparison")
        self.comparison.setAccessibleName("Current versus proposed story comparison")
        self._fallback_item: QListWidgetItem | None = None
        root.addWidget(self.comparison)
        self.groups = QListWidget(self)
        self.groups.setObjectName("draftReviewGroups")
        self.groups.setAccessibleName("Candidate arcs and events requiring review")
        self.groups.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        candidate = draft.candidate if isinstance(draft.candidate, dict) else {}
        self._expected: set[tuple[str, str]] = set()
        self._decisions = {
            (review.target_kind, review.target_id): review.decision for review in reviews
        }
        for kind, key in (("arc", "arcs"), ("event", "events")):
            values = candidate.get(key, [])
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, dict):
                    continue
                identifier = value.get("id")
                title = value.get("title")
                if not isinstance(identifier, str) or not isinstance(title, str):
                    continue
                item = QListWidgetItem(f"{kind.title()}  •  {title}")
                item.setData(Qt.ItemDataRole.UserRole, (kind, identifier))
                self._expected.add((kind, identifier))
                decision = self._decisions.get((kind, identifier))
                if decision is not None:
                    item.setText(f"{item.text()}  —  {decision.title()}")
                self.groups.addItem(item)
        self._populate_comparison(candidate, current_arcs, current_events)
        controls = QHBoxLayout()
        self.decision = QComboBox(self)
        self.decision.setObjectName("draftDecision")
        self.decision.setAccessibleName("Review decision")
        self.decision.addItems(["Approve", "Reject"])
        self.save_decision = QPushButton("Save decision", self)
        self.save_decision.setObjectName("saveDraftDecision")
        controls.addWidget(self.decision)
        controls.addWidget(self.save_decision)
        controls.addStretch(1)
        root.addWidget(self.groups, 1)
        root.addLayout(controls)
        buttons = QDialogButtonBox(self)
        self.apply_button = buttons.addButton(
            "Apply Draft", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.discard_button = buttons.addButton(
            "Discard Draft", QDialogButtonBox.ButtonRole.DestructiveRole
        )
        self.close_button = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self.apply_button.setObjectName("applyDraftButton")
        self.discard_button.setObjectName("discardDraftButton")
        self.apply_button.setEnabled(self._expected.issubset(self._decisions))
        root.addWidget(buttons)
        self.save_decision.clicked.connect(self._save)
        self.apply_button.clicked.connect(lambda: self.apply_requested.emit(draft.id))
        self.discard_button.clicked.connect(lambda: self.discard_requested.emit(draft.id))
        self.close_button.clicked.connect(self.reject)

    @Slot()
    def _save(self) -> None:
        item = self.groups.currentItem()
        if item is None:
            return
        kind, identifier = cast(tuple[str, str], item.data(Qt.ItemDataRole.UserRole))
        decision = "approved" if self.decision.currentIndex() == 0 else "rejected"
        self.review_requested.emit(kind, identifier, decision)

    @Slot(str, str, str)
    def confirm_review(self, kind: str, identifier: str, decision: str) -> None:
        """Count a decision only after the domain service confirms persistence."""

        self._decisions[(kind, identifier)] = decision
        for index in range(self.groups.count()):
            item = self.groups.item(index)
            if item.data(Qt.ItemDataRole.UserRole) != (kind, identifier):
                continue
            base = item.text().split("  —  ", 1)[0]
            item.setText(f"{base}  —  {decision.title()}")
            break
        self.apply_button.setEnabled(self._expected.issubset(self._decisions))
        self._update_fallback_summary()

    def _populate_comparison(
        self,
        candidate: dict[str, object],
        current_arcs: Sequence[StoryArc],
        current_events: Sequence[StoryEvent],
    ) -> None:
        current_by_kind: dict[str, dict[str, object]] = {
            "arc": {arc.id: arc for arc in current_arcs},
            "event": {event.id: event for event in current_events},
        }
        counts = {name: 0 for name in ("added", "removed", "renamed", "split", "merged")}
        proposed_events: list[dict[str, object]] = []
        for kind, key in (("arc", "arcs"), ("event", "events")):
            values = candidate.get(key, [])
            proposed: dict[str, dict[str, object]] = {
                str(value.get("id")): value
                for value in values
                if isinstance(value, dict) and isinstance(value.get("id"), str)
            } if isinstance(values, list) else {}
            current = current_by_kind[kind]
            if kind == "event":
                proposed_events = list(proposed.values())
            for identifier, value in proposed.items():
                existing = current.get(identifier)
                if existing is None:
                    counts["added"] += 1
                    self.comparison.addItem(f"Added {kind}  •  {value.get('title', identifier)}")
                elif getattr(existing, "title", None) != value.get("title"):
                    counts["renamed"] += 1
                    self.comparison.addItem(f"Renamed {kind}  •  {value.get('title', identifier)}")
            for identifier, current_value in current.items():
                if identifier not in proposed:
                    counts["removed"] += 1
                    self.comparison.addItem(
                        f"Removed {kind}  •  {getattr(current_value, 'title', identifier)}"
                    )
        current_memberships = [set(event.beat_ids) for event in current_events]
        proposed_memberships: list[set[str]] = []
        for value in proposed_events:
            raw_members = value.get("beat_ids")
            if isinstance(raw_members, list):
                proposed_memberships.append(
                    {beat_id for beat_id in raw_members if isinstance(beat_id, str)}
                )
        counts["split"] = sum(
            sum(bool(current & proposed) for proposed in proposed_memberships) > 1
            for current in current_memberships
        )
        counts["merged"] = sum(
            sum(bool(proposed & current) for current in current_memberships) > 1
            for proposed in proposed_memberships
        )
        ungrouped = candidate.get("ungrouped_beat_ids", [])
        ungrouped_count = len(ungrouped) if isinstance(ungrouped, list) else 0
        claims = candidate.get("claims", [])
        evidence_ids: set[str] = set()
        if isinstance(claims, list):
            for claim in claims:
                if not isinstance(claim, dict):
                    continue
                raw_evidence = claim.get("evidence_ids", [])
                if isinstance(raw_evidence, list):
                    evidence_ids.update(
                        evidence for evidence in raw_evidence if isinstance(evidence, str)
                    )
        self.comparison_summary.setText(
            "Current vs proposed  •  "
            f"Added {counts['added']}  •  Removed {counts['removed']}  •  "
            f"Renamed {counts['renamed']}  •  Split {counts['split']}  •  "
            f"Merged {counts['merged']}  •  Ungrouped {ungrouped_count}  •  "
            f"Evidence records {len(evidence_ids)}"
        )
        self._update_fallback_summary()

    def _update_fallback_summary(self) -> None:
        rejected = sum(value == "rejected" for value in self._decisions.values())
        if self._fallback_item is None:
            self._fallback_item = QListWidgetItem()
            self.comparison.addItem(self._fallback_item)
        self._fallback_item.setText(f"Deterministic fallback scopes  •  {rejected}")


class DraftReviewDialog(QDialog):
    """Bounded, covered-scope comparison with durable explicit decisions."""

    review_requested = Signal(str, str, str)
    apply_requested = Signal(str)
    discard_requested = Signal(str)

    def __init__(
        self,
        draft: OrganizationDraft,
        run: OrganizationRun | None,
        current_arcs: Sequence[StoryArc],
        current_events: Sequence[StoryEvent],
        reviews: Sequence[DraftReview],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.draft = draft
        self.setObjectName("draftReviewDialog")
        self.setWindowTitle("Review organized story")
        self.resize(920, 680)
        root = QVBoxLayout(self)
        candidate = draft.candidate if isinstance(draft.candidate, dict) else {}

        metadata = QLabel(self)
        metadata.setObjectName("draftMetadata")
        if run is None:
            metadata.setText("Validated draft | provider metadata unavailable")
        else:
            location = "Local" if "lmstudio" in run.provider_mode else "Cloud"
            metadata.setText(
                f"{location} | {run.model_profile} | {run.prompt_version} | "
                f"{run.elapsed_ms or 0} ms"
            )
        root.addWidget(metadata)
        usage = run.usage if run is not None and isinstance(run.usage, dict) else {}
        model = run.model_fingerprint if run is not None and run.model_fingerprint else "Default"
        self.provider_metadata = QLabel(
            f"Provider: {run.provider_mode if run else 'unavailable'} | Model: {model} | "
            f"Profile: {run.model_profile if run else 'unavailable'} | "
            f"Schema: {run.output_schema_version if run else 'unavailable'} | "
            f"Cache hits: {usage.get('cache_hits', 0)} | "
            f"Provider calls: {usage.get('provider_calls', 0)} | "
            f"Context: {usage.get('context_window_tokens', 'unknown')} | "
            f"Tokens: {usage.get('input_tokens', 0)} in / "
            f"{usage.get('output_tokens', 0)} out",
            self,
        )
        self.provider_metadata.setObjectName("draftProviderMetadata")
        self.provider_metadata.setWordWrap(True)
        root.addWidget(self.provider_metadata)

        scope_ids, covered_beat_ids = _draft_scope(candidate)
        self.scope_summary = QLabel(
            (
                f"Covered scope: {len(scope_ids)} container(s), "
                f"{len(covered_beat_ids)} deterministic beat(s)"
                if scope_ids
                else "Covered scope: full accepted organization"
            ),
            self,
        )
        self.scope_summary.setObjectName("draftScopeSummary")
        root.addWidget(self.scope_summary)
        self.comparison_summary = QLabel(self)
        self.comparison_summary.setObjectName("draftComparisonSummary")
        self.comparison_summary.setWordWrap(True)
        root.addWidget(self.comparison_summary)

        self.comparison = QListWidget(self)
        self.comparison.setObjectName("draftComparison")
        self.comparison.setAccessibleName("Covered-scope current and proposed comparison")
        self._fallback_item: QListWidgetItem | None = None
        self._comparison_total = 0
        root.addWidget(self.comparison)

        self.groups = QListWidget(self)
        self.groups.setObjectName("draftReviewGroups")
        self.groups.setAccessibleName("Candidate arcs and events requiring review")
        self.groups.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._expected: set[tuple[str, str]] = set()
        self._decisions = {
            (review.target_kind, review.target_id): review.decision for review in reviews
        }
        self._group_records: list[tuple[str, str, dict[str, object]]] = []
        self._group_page = 0
        for kind, key in (("arc", "arcs"), ("event", "events")):
            values = candidate.get(key, [])
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, dict):
                    continue
                identifier = value.get("id")
                title = value.get("title")
                if not isinstance(identifier, str) or not isinstance(title, str):
                    continue
                self._expected.add((kind, identifier))
                self._group_records.append((kind, identifier, value))

        scoped_events = tuple(current_events)
        scoped_arcs = tuple(current_arcs)
        if covered_beat_ids:
            covered = frozenset(covered_beat_ids)
            scoped_events = tuple(
                event for event in current_events if covered.intersection(event.beat_ids)
            )
            scoped_event_ids = {event.id for event in scoped_events}
            scoped_arcs = tuple(
                arc for arc in current_arcs if scoped_event_ids.intersection(arc.event_ids)
            )
        self._populate_comparison(candidate, scoped_arcs, scoped_events)
        root.addWidget(self.groups, 1)

        controls = QHBoxLayout()
        self.previous_groups = QPushButton("Previous", self)
        self.previous_groups.setObjectName("previousDraftGroups")
        self.next_groups = QPushButton("Next", self)
        self.next_groups.setObjectName("nextDraftGroups")
        self.group_page_status = QLabel(self)
        self.group_page_status.setObjectName("draftGroupPageStatus")
        self.decision = QComboBox(self)
        self.decision.setObjectName("draftDecision")
        self.decision.setAccessibleName("Review decision")
        self.decision.addItems(["Approve", "Reject"])
        self.save_decision = QPushButton("Save decision", self)
        self.save_decision.setObjectName("saveDraftDecision")
        controls.addWidget(self.previous_groups)
        controls.addWidget(self.next_groups)
        controls.addWidget(self.group_page_status)
        controls.addStretch(1)
        controls.addWidget(self.decision)
        controls.addWidget(self.save_decision)
        root.addLayout(controls)

        buttons = QDialogButtonBox(self)
        self.apply_button = buttons.addButton(
            "Apply Draft", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.discard_button = buttons.addButton(
            "Discard Draft", QDialogButtonBox.ButtonRole.DestructiveRole
        )
        self.close_button = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self.apply_button.setObjectName("applyDraftButton")
        self.discard_button.setObjectName("discardDraftButton")
        self.apply_button.setEnabled(self._expected.issubset(self._decisions))
        root.addWidget(buttons)

        self.save_decision.clicked.connect(self._save)
        self.groups.currentItemChanged.connect(self._sync_decision)
        self.previous_groups.clicked.connect(lambda: self._change_group_page(-1))
        self.next_groups.clicked.connect(lambda: self._change_group_page(1))
        self.apply_button.clicked.connect(lambda: self.apply_requested.emit(draft.id))
        self.discard_button.clicked.connect(lambda: self.discard_requested.emit(draft.id))
        self.close_button.clicked.connect(self.reject)
        self._render_group_page()

    @Slot(object, object)
    def _sync_decision(self, current: object, _previous: object) -> None:
        if not isinstance(current, QListWidgetItem):
            return
        key = current.data(Qt.ItemDataRole.UserRole)
        decision = self._decisions.get(key) if isinstance(key, tuple) else None
        self.decision.setCurrentIndex(1 if decision == "rejected" else 0)

    @Slot()
    def _save(self) -> None:
        item = self.groups.currentItem()
        if item is None:
            return
        kind, identifier = cast(tuple[str, str], item.data(Qt.ItemDataRole.UserRole))
        decision = "approved" if self.decision.currentIndex() == 0 else "rejected"
        self.review_requested.emit(kind, identifier, decision)

    @Slot(str, str, str)
    def confirm_review(self, kind: str, identifier: str, decision: str) -> None:
        """Count a decision only after the domain service confirms persistence."""

        self._decisions[(kind, identifier)] = decision
        self._render_group_page()
        self.apply_button.setEnabled(self._expected.issubset(self._decisions))
        self._update_fallback_summary()

    def _change_group_page(self, delta: int) -> None:
        page_count = max(
            1, (len(self._group_records) + MAX_REVIEW_ITEMS - 1) // MAX_REVIEW_ITEMS
        )
        self._group_page = max(0, min(page_count - 1, self._group_page + delta))
        self._render_group_page()

    def _render_group_page(self) -> None:
        self.groups.clear()
        start = self._group_page * MAX_REVIEW_ITEMS
        stop = min(len(self._group_records), start + MAX_REVIEW_ITEMS)
        candidate = self.draft.candidate if isinstance(self.draft.candidate, dict) else {}
        claims = candidate.get("claims", [])
        for kind, identifier, value in self._group_records[start:stop]:
            item = QListWidgetItem(
                _review_group_text(
                    kind,
                    identifier,
                    value,
                    claims if isinstance(claims, list) else [],
                    self._decisions.get((kind, identifier)),
                )
            )
            item.setData(Qt.ItemDataRole.UserRole, (kind, identifier))
            self.groups.addItem(item)
        total = len(self._group_records)
        page_count = max(1, (total + MAX_REVIEW_ITEMS - 1) // MAX_REVIEW_ITEMS)
        shown_start = 0 if total == 0 else start + 1
        self.group_page_status.setText(
            f"{shown_start}-{stop} of {total} | Page {self._group_page + 1}/{page_count}"
        )
        self.previous_groups.setEnabled(self._group_page > 0)
        self.next_groups.setEnabled(self._group_page + 1 < page_count)

    def _add_comparison(self, text: str) -> None:
        self._comparison_total += 1
        # Reserve one of the 240 rows for deterministic-fallback status.
        if self.comparison.count() < MAX_REVIEW_ITEMS - 1:
            self.comparison.addItem(_bounded_text(text, 260))

    def _populate_comparison(
        self,
        candidate: dict[str, object],
        current_arcs: Sequence[StoryArc],
        current_events: Sequence[StoryEvent],
    ) -> None:
        current_by_kind: dict[str, dict[str, object]] = {
            "arc": {arc.id: arc for arc in current_arcs},
            "event": {event.id: event for event in current_events},
        }
        counts = {name: 0 for name in ("added", "removed", "renamed", "split", "merged")}
        proposed_events: list[dict[str, object]] = []
        for kind, key in (("arc", "arcs"), ("event", "events")):
            values = candidate.get(key, [])
            proposed = (
                {
                    str(value.get("id")): value
                    for value in values
                    if isinstance(value, dict) and isinstance(value.get("id"), str)
                }
                if isinstance(values, list)
                else {}
            )
            current = current_by_kind[kind]
            if kind == "event":
                proposed_events = list(proposed.values())
            for identifier, value in proposed.items():
                existing = current.get(identifier)
                if existing is None:
                    counts["added"] += 1
                    self._add_comparison(
                        f"Added {kind} | {value.get('title', identifier)}"
                    )
                elif getattr(existing, "title", None) != value.get("title"):
                    counts["renamed"] += 1
                    self._add_comparison(
                        f"Renamed {kind} | {value.get('title', identifier)}"
                    )
            for identifier, current_value in current.items():
                if identifier not in proposed:
                    counts["removed"] += 1
                    self._add_comparison(
                        f"Removed {kind} | {getattr(current_value, 'title', identifier)}"
                    )

        counts["split"], counts["merged"] = _split_merge_counts(
            current_events, proposed_events
        )
        ungrouped_count = len(_string_sequence(candidate.get("ungrouped_beat_ids")))
        raw_claims = candidate.get("claims", [])
        claims = raw_claims if isinstance(raw_claims, list) else []
        evidence_ids = {
            evidence
            for claim in claims
            if isinstance(claim, dict)
            for evidence in _string_sequence(claim.get("evidence_ids"))
        }
        self.comparison_summary.setText(
            "Current vs proposed inside the covered scope | "
            f"Added {counts['added']} | Removed {counts['removed']} | "
            f"Renamed {counts['renamed']} | Split {counts['split']} | "
            f"Merged {counts['merged']} | Ungrouped {ungrouped_count} | "
            f"Evidence records {len(evidence_ids)} | "
            f"Details {min(self._comparison_total, MAX_REVIEW_ITEMS - 1)}/"
            f"{self._comparison_total}"
        )
        self._update_fallback_summary()

    def _update_fallback_summary(self) -> None:
        rejected = sum(value == "rejected" for value in self._decisions.values())
        if self._fallback_item is None:
            self._fallback_item = QListWidgetItem()
            self.comparison.addItem(self._fallback_item)
        self._fallback_item.setText(
            "Covered-scope deterministic fallbacks | "
            f"{rejected} rejected group(s); untouched scopes stay in Technical map"
        )


class AcceptedStoryPresenter(QObject):
    """Project-open adapter that never invokes an organization provider."""

    busy_changed = Signal(bool)
    status_changed = Signal(str)
    error_occurred = Signal(str)
    visible_count_changed = Signal(int)
    provenance_changed = Signal(str)
    level_changed = Signal(int)
    pending_draft_changed = Signal(object, object, object)
    technical_map_requested = Signal()
    accepted_map_requested = Signal()
    selection_context_changed = Signal(object)
    ready = Signal()

    def __init__(
        self,
        canvas: GraphCanvas,
        navigator: QListWidget,
        inspector: InspectorTabs,
        center_stack: QStackedWidget,
        evidence_timeline: QListWidget,
        parent: QObject | None = None,
        *,
        canvas_page: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.canvas = canvas
        self.navigator = navigator
        self.inspector = inspector
        self.center_stack = center_stack
        self.canvas_page = canvas if canvas_page is None else canvas_page
        self.evidence_timeline = evidence_timeline
        self._session: ProjectSession | None = None
        self._snapshot: StorySnapshot | None = None
        self._task: WorkerTask | None = None
        self._evidence_task: WorkerTask | None = None
        self._search_task: WorkerTask | None = None
        self._selected_arc: str | None = None
        self._selected_event: str | None = None
        self._active = False
        self._technical_mode = False
        self._syncing_level = False
        self._load_generation = 0
        self._evidence_generation = 0
        self._search_generation = 0
        self._arc_window_start: dict[str, int] = {}
        self.navigator.itemActivated.connect(self._navigator_activated)
        self.canvas.selection_changed.connect(self._selected)
        self.canvas.expansion_requested.connect(self._expanded)
        self.canvas.semantic_level_changed.connect(self._semantic_level_requested)

    @property
    def active(self) -> bool:
        return self._active

    @property
    def viewing_accepted(self) -> bool:
        return self._active and not self._technical_mode

    @property
    def is_busy(self) -> bool:
        return (
            self._task is not None
            or self._evidence_task is not None
            or self._search_task is not None
        )

    @property
    def selected_target(self) -> tuple[str, str] | None:
        if not self.viewing_accepted:
            return None
        if self._selected_event is not None:
            return "event", self._selected_event
        if self._selected_arc is not None and (
            self.canvas.rendered_item_count == 0
            or (
                self.canvas.semantic_level is SemanticLevel.OVERVIEW
                and self.canvas.selected_node_id == self._selected_arc
            )
        ):
            return "arc", self._selected_arc
        return None

    @property
    def selected_arc_id(self) -> str | None:
        return self._selected_arc

    @property
    def selected_event_id(self) -> str | None:
        return self._selected_event

    @property
    def selected_pinned(self) -> bool:
        snapshot = self._snapshot
        target = self.selected_target
        if snapshot is None or target is None:
            return False
        kind, identifier = target
        values = snapshot.arcs if kind == "arc" else snapshot.events
        return bool(next((item.pinned for item in values if item.id == identifier), False))

    @property
    def selected_hidden(self) -> bool:
        snapshot = self._snapshot
        target = self.selected_target
        if snapshot is None or target is None:
            return False
        kind, identifier = target
        values = snapshot.arcs if kind == "arc" else snapshot.events
        return bool(next((item.hidden for item in values if item.id == identifier), False))

    @property
    def selected_approval_state(self) -> str | None:
        snapshot = self._snapshot
        target = self.selected_target
        if snapshot is None or target is None:
            return None
        kind, identifier = target
        values = snapshot.arcs if kind == "arc" else snapshot.events
        return next(
            (item.approval_state for item in values if item.id == identifier), None
        )

    def enter_technical_mode(self) -> None:
        """Suspend accepted-map reactions while the deterministic M04 map is visible."""

        if not self._active:
            return
        self._technical_mode = True
        self._cancel_evidence()
        self._cancel_search()
        self.center_stack.setCurrentWidget(self.canvas_page)
        self.provenance_changed.emit("Technical organization")
        self.status_changed.emit("Technical map | all deterministic scopes remain available")
        self.selection_context_changed.emit(None)

    def enter_accepted_mode(self) -> None:
        if not self._active:
            return
        self._technical_mode = False
        self.show_overview()

    def correction_choices(
        self,
    ) -> tuple[
        tuple[tuple[str, str], ...],
        tuple[tuple[str, str], ...],
        tuple[tuple[str, str], ...],
    ]:
        snapshot = self._snapshot
        event_id = self._selected_event
        if snapshot is None or event_id is None:
            return (), (), ()
        event = next((value for value in snapshot.events if value.id == event_id), None)
        if event is None:
            return (), (), ()
        boundaries = tuple(
            (beat_id, f"After beat {index}")
            for index, beat_id in enumerate(event.beat_ids[1:], start=1)
        )
        parent_arc = next((arc for arc in snapshot.arcs if event_id in arc.event_ids), None)
        event_by_id = {value.id: value for value in snapshot.events}
        neighboring_ids: tuple[str, ...] = ()
        if parent_arc is not None:
            position = parent_arc.event_ids.index(event_id)
            neighboring_ids = parent_arc.event_ids[
                max(0, position - 1) : min(len(parent_arc.event_ids), position + 2)
            ]
        siblings = tuple(
            (identifier, event_by_id[identifier].title)
            for identifier in neighboring_ids
            if identifier != event_id and identifier in event_by_id
        )
        arcs = tuple(
            (arc.id, arc.title)
            for arc in snapshot.arcs
            if parent_arc is None or arc.id != parent_arc.id
        )
        return boundaries, siblings, arcs

    def set_project(self, session: ProjectSession | None) -> None:
        self.cancel()
        self._session = session
        self._snapshot = None
        self._active = False
        self._technical_mode = False
        self._selected_arc = None
        self._selected_event = None
        self._arc_window_start.clear()
        self.inspector.summary.clear()
        self.inspector.state.clear()
        self.inspector.evidence.clear()
        self.inspector.details.clear()
        self.navigator.clear()
        self.evidence_timeline.clear()
        self.canvas.set_slice((), (), preserve_navigation=False)
        self.center_stack.setCurrentWidget(self.canvas_page)
        if session is None:
            return

        generation = self._load_generation

        def operation(
            cancelled: Callable[[], bool], _progress: Callable[[int, str], None]
        ) -> object:
            if cancelled():
                return None
            return _load_snapshot(session.project_path)

        task = WorkerTask(operation, self)
        self._task = task
        task.succeeded.connect(
            lambda value, expected=generation: self._accept_loaded(expected, value)
        )
        task.failed.connect(lambda _error, expected=generation: self._load_failed(expected))
        task.finished.connect(lambda current=task: self._finish_load(current))
        self.busy_changed.emit(True)
        task.start()

    def reload(self) -> None:
        """Retry loading accepted organization for the current project."""

        session = self._session
        if session is not None:
            self.set_project(session)

    def cancel(self) -> None:
        self._load_generation += 1
        if self._task is not None:
            self._task.cancel()
        self._cancel_evidence()
        self._cancel_search()

    def _cancel_evidence(self) -> None:
        self._evidence_generation += 1
        if self._evidence_task is not None:
            self._evidence_task.cancel()

    def _cancel_search(self) -> None:
        self._search_generation += 1
        if self._search_task is not None:
            self._search_task.cancel()

    def _accept_loaded(self, generation: int, value: object) -> None:
        if generation == self._load_generation and self._session is not None:
            self._loaded(value)

    def _load_failed(self, generation: int) -> None:
        if generation == self._load_generation and self._session is not None:
            self.error_occurred.emit("The story view failed safely.")

    @Slot(object)
    def _loaded(self, value: object) -> None:
        if not isinstance(value, StorySnapshot):
            return
        self._snapshot = value
        self._active = bool(value.arcs)
        if self._active:
            self._populate_navigator()
            self.show_overview()
        else:
            self.provenance_changed.emit("Technical organization")
            self.navigator.clear()
        self.pending_draft_changed.emit(value.pending_draft, value.latest_run, value)
        self.ready.emit()

    def _finish_load(self, task: WorkerTask) -> None:
        if self._task is task:
            self._task = None
        task.deleteLater()
        self.busy_changed.emit(self.is_busy)

    def _populate_navigator_legacy(self) -> None:
        snapshot = self._snapshot
        if snapshot is None:
            return
        self.navigator.clear()
        overview = QListWidgetItem("Overview")
        overview.setData(Qt.ItemDataRole.UserRole, ("overview", ""))
        self.navigator.addItem(overview)
        for arc in snapshot.arcs[:MAX_ARCS]:
            suffix = "  •  Needs review" if arc.needs_review else ""
            item = QListWidgetItem(f"{arc.title}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, ("arc", arc.id))
            item.setData(
                Qt.ItemDataRole.AccessibleTextRole, f"Story arc {arc.title}{suffix}"
            )
            self.navigator.addItem(item)
        for title, kind in (
            ("Characters", "characters"),
            ("Outcomes", "outcomes"),
            ("Saved filters", "filters"),
        ):
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, (kind, ""))
            self.navigator.addItem(item)

    def _populate_navigator(self) -> None:
        snapshot = self._snapshot
        if snapshot is None:
            return
        self.navigator.clear()
        overview = QListWidgetItem("Accepted overview")
        overview.setData(Qt.ItemDataRole.UserRole, ("overview", ""))
        self.navigator.addItem(overview)
        visible_arcs = [arc for arc in snapshot.arcs if not arc.hidden]
        for arc in visible_arcs[:MAX_ARCS]:
            states = []
            if arc.needs_review:
                states.append("Needs review")
            if arc.approval_state == "rejected":
                states.append("Rejected")
            suffix = " | " + ", ".join(states) if states else ""
            item = QListWidgetItem(f"{arc.title}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, ("arc", arc.id))
            item.setData(
                Qt.ItemDataRole.AccessibleTextRole, f"Accepted story arc {arc.title}{suffix}"
            )
            self.navigator.addItem(item)
        technical = QListWidgetItem("Technical map / unorganized scopes")
        technical.setData(Qt.ItemDataRole.UserRole, ("technical", ""))
        technical.setData(
            Qt.ItemDataRole.AccessibleTextRole,
            "Open the deterministic technical map and all unorganized scopes",
        )
        self.navigator.addItem(technical)
        hidden_items: list[tuple[str, str, str]] = [
            ("arc", arc.id, arc.title) for arc in snapshot.arcs if arc.hidden
        ]
        hidden_items.extend(
            ("event", event.id, event.title) for event in snapshot.events if event.hidden
        )
        # Keep room for three fixed rows, one truncation row, and two event-page rows.
        hidden_limit = max(0, MAX_VISIBLE_ITEMS - self.navigator.count() - 6)
        for kind, identifier, title in hidden_items[:hidden_limit]:
            item = QListWidgetItem(f"View hidden {kind} | {title}")
            item.setData(Qt.ItemDataRole.UserRole, (f"hidden-{kind}", identifier))
            self.navigator.addItem(item)
        if len(hidden_items) > hidden_limit:
            truncation = QListWidgetItem(
                f"Hidden items truncated | showing {hidden_limit} of {len(hidden_items)}"
            )
            truncation.setData(Qt.ItemDataRole.UserRole, ("hidden-truncated", ""))
            self.navigator.addItem(truncation)
        for title, kind in (
            ("Characters", "characters"),
            ("Outcomes", "outcomes"),
            ("Saved filters", "filters"),
        ):
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, (kind, ""))
            self.navigator.addItem(item)

    def show_overview(self) -> None:
        snapshot = self._snapshot
        if snapshot is None or not snapshot.arcs:
            return
        self._technical_mode = False
        self._remove_event_page_rows()
        self._cancel_evidence()
        self._cancel_search()
        arcs = tuple(arc for arc in snapshot.arcs if not arc.hidden)[:MAX_ARCS]
        arc_ids = {arc.id for arc in arcs}
        filters_by_event = {
            event_id: (frozenset(variables), frozenset(categories))
            for event_id, variables, categories in snapshot.event_filters
        }
        nodes = [
            GraphNodeSpec(
                id=arc.id,
                kind="container",
                title=arc.title,
                summary=_arc_overview_summary(arc, snapshot),
                detail=f"{len(arc.event_ids)} events • {arc.origin}",
                semantic_levels=frozenset({SemanticLevel.OVERVIEW}),
                variables=frozenset(
                    variable
                    for event_id in arc.event_ids
                    for variable in filters_by_event.get(
                        event_id, (frozenset(), frozenset())
                    )[0]
                ),
                categories=frozenset(
                    category
                    for event_id in arc.event_ids
                    for category in filters_by_event.get(
                        event_id, (frozenset(), frozenset())
                    )[1]
                ),
                expandable=True,
                expanded=arc.id == self._selected_arc,
            )
            for arc in arcs
        ]
        edges = [
            GraphEdgeSpec(edge.source_id, edge.target_id, edge.kind)
            for edge in snapshot.arc_edges
            if edge.source_id in arc_ids and edge.target_id in arc_ids
        ]
        self.canvas.set_slice(nodes, edges, preserve_navigation=True)
        self._set_canvas_level(SemanticLevel.OVERVIEW)
        self.center_stack.setCurrentWidget(self.canvas_page)
        self._selected_event = None
        self._arc_window_start.clear()
        self.visible_count_changed.emit(self.canvas.visible_item_count)
        self.provenance_changed.emit("Accepted story organization")
        self.level_changed.emit(1)
        if arcs:
            self.status_changed.emit("Accepted story overview")
        else:
            self.status_changed.emit(
                "No visible accepted arcs | use a hidden item or Technical map"
            )
        self.selection_context_changed.emit(self.selected_target)

    def show_arc(self, arc_id: str, *, focus_event_id: str | None = None) -> None:
        snapshot = self._snapshot
        if snapshot is None:
            return
        arc = next((item for item in snapshot.arcs if item.id == arc_id), None)
        if arc is None or arc.hidden:
            return
        self._technical_mode = False
        self._cancel_evidence()
        self._cancel_search()
        event_by_id = {event.id: event for event in snapshot.events}
        all_events = [
            event_by_id[event_id]
            for event_id in arc.event_ids
            if event_id in event_by_id and not event_by_id[event_id].hidden
        ]
        if focus_event_id is not None:
            focus_index = next(
                (
                    index
                    for index, event in enumerate(all_events)
                    if event.id == focus_event_id
                ),
                None,
            )
            if focus_index is not None:
                self._arc_window_start[arc_id] = (focus_index // MAX_EVENTS) * MAX_EVENTS
        maximum_start = (
            ((len(all_events) - 1) // MAX_EVENTS) * MAX_EVENTS if all_events else 0
        )
        start = min(self._arc_window_start.get(arc_id, 0), maximum_start)
        self._arc_window_start[arc_id] = start
        events = all_events[start : start + MAX_EVENTS]
        self._update_event_page_rows(arc_id, start, len(all_events))
        event_ids = {event.id for event in events}
        all_event_ids = {event.id for event in all_events}
        facts_by_event: dict[str, list[AttachedFact]] = {}
        for fact in snapshot.facts:
            facts_by_event.setdefault(fact.event_id, []).append(fact)
        edges = [
            edge
            for edge in snapshot.event_edges
            if edge.source_id in event_ids and edge.target_id in event_ids
        ]
        outgoing_kinds: dict[str, set[str]] = {}
        for edge in snapshot.event_edges:
            if edge.source_id in all_event_ids:
                outgoing_kinds.setdefault(edge.source_id, set()).add(edge.kind)
        nodes = []
        layout_nodes = []
        enrichment_by_target = {
            (getattr(value, "target_kind", ""), getattr(value, "target_id", "")): value
            for value in snapshot.enrichments
        }
        filters_by_event = {
            event_id: (frozenset(variables), frozenset(categories))
            for event_id, variables, categories in snapshot.event_filters
        }
        for event in events:
            facts = facts_by_event.get(event.id, [])
            requirements = tuple(fact.expression for fact in facts if fact.fact_kind == "gate")
            effects = tuple(fact.expression for fact in facts if fact.fact_kind == "effect")
            kind = _event_kind(event, outgoing_kinds.get(event.id, set()))
            evidence = tuple(
                SourceEvidence(fact.source_path, fact.start_line, fact.end_line, fact.expression)
                for fact in facts
            )
            enrichment = enrichment_by_target.get(("event", event.id))
            importance = str(getattr(enrichment, "importance", "supporting"))
            characters = tuple(getattr(enrichment, "characters", ()))
            outcomes = tuple(getattr(enrichment, "outcomes", ()))
            warnings = tuple(getattr(enrichment, "warnings", ()))
            variables, categories = filters_by_event.get(
                event.id, (frozenset(), frozenset())
            )
            metadata = [
                f"{len(event.beat_ids)} beats",
                event.origin.title(),
                importance.title(),
            ]
            if characters:
                metadata.append(f"Characters: {', '.join(characters[:3])}")
            if outcomes:
                metadata.append(f"Outcomes: {len(outcomes)}")
            if warnings:
                metadata.append(f"Warnings: {len(warnings)}")
            nodes.append(
                GraphNodeSpec(
                    event.id,
                    kind,
                    event.title,
                    event.summary,
                    " • ".join(metadata),
                    frozenset({SemanticLevel.EVENTS}),
                    requirements,
                    effects,
                    variables=variables,
                    categories=categories,
                    evidence=evidence,
                    expandable=True,
                )
            )
            layout_nodes.append(
                LayoutNode(event.id, event.order, kind, bool(requirements), bool(effects))
            )
        graph_edges = [GraphEdgeSpec(edge.source_id, edge.target_id, edge.kind) for edge in edges]
        layout = layout_story_events(
            LayoutInput(
                tuple(layout_nodes),
                tuple(
                    LayoutEdge(edge.id, edge.source_id, edge.target_id, edge.kind)
                    for edge in edges
                ),
            )
        )
        self.canvas.set_slice(nodes, graph_edges, preserve_navigation=True)
        self.canvas.set_layout_positions(
            {card.id: (card.bounds.x, card.bounds.y) for card in layout.cards}
        )
        self._set_canvas_level(SemanticLevel.EVENTS)
        self.center_stack.setCurrentWidget(self.canvas_page)
        self._selected_arc = arc_id
        if self._selected_event not in event_ids:
            self._selected_event = None
        self.visible_count_changed.emit(self.canvas.visible_item_count)
        self.provenance_changed.emit("Accepted story organization")
        self.level_changed.emit(2)
        self.inspector.summary.setText(arc.summary)
        window_end = start + len(events)
        review_state = "Needs review" if arc.needs_review else "Reviewed"
        self.inspector.details.setText(
            f"Events {start + 1 if events else 0}-{window_end} of {len(all_events)} | "
            f"{arc.origin.title()} | {review_state}"
        )
        self.status_changed.emit(arc.title)
        self.selection_context_changed.emit(self.selected_target)

    def _remove_event_page_rows(self) -> None:
        for index in range(self.navigator.count() - 1, -1, -1):
            item = self.navigator.item(index)
            data = item.data(Qt.ItemDataRole.UserRole)
            if (
                isinstance(data, tuple)
                and data
                and data[0] in {"event-page-previous", "event-page-next"}
            ):
                self.navigator.takeItem(index)

    def _update_event_page_rows(self, arc_id: str, start: int, total: int) -> None:
        self._remove_event_page_rows()
        if start > 0:
            item = QListWidgetItem(f"Previous events | {max(1, start - MAX_EVENTS + 1)}-{start}")
            item.setData(Qt.ItemDataRole.UserRole, ("event-page-previous", arc_id))
            self.navigator.addItem(item)
        if start + MAX_EVENTS < total:
            stop = min(total, start + MAX_EVENTS * 2)
            item = QListWidgetItem(f"Next events | {start + MAX_EVENTS + 1}-{stop}")
            item.setData(Qt.ItemDataRole.UserRole, ("event-page-next", arc_id))
            self.navigator.addItem(item)

    def _page_arc(self, arc_id: str, delta: int) -> None:
        self._arc_window_start[arc_id] = max(
            0, self._arc_window_start.get(arc_id, 0) + delta * MAX_EVENTS
        )
        self.show_arc(arc_id)

    def search(self, query: str) -> bool:
        snapshot = self._snapshot
        term = query.strip().casefold()
        if snapshot is None or not term or not self.viewing_accepted:
            return False
        self._cancel_search()
        for arc in snapshot.arcs:
            if term in f"{arc.title} {_arc_overview_summary(arc, snapshot)}".casefold():
                if arc.hidden:
                    self._show_hidden_target("arc", arc.id)
                    return True
                self.show_overview()
                return self.canvas.focus_search_result(arc.id)
        character_map = dict(snapshot.event_characters)
        enrichment_by_target = {
            (getattr(value, "target_kind", ""), getattr(value, "target_id", "")): value
            for value in snapshot.enrichments
        }
        facts_by_event: dict[str, list[str]] = {}
        for fact in snapshot.facts:
            facts_by_event.setdefault(fact.event_id, []).append(fact.expression)
        claims_by_event: dict[str, list[str]] = {}
        for claim in snapshot.claims:
            if claim.event_id is not None:
                claims_by_event.setdefault(claim.event_id, []).append(claim.text)
        for event in snapshot.events:
            enrichment = enrichment_by_target.get(("event", event.id))
            facts = " ".join(facts_by_event.get(event.id, ()))
            claims = " ".join(claims_by_event.get(event.id, ()))
            enriched = " ".join(
                (
                    *character_map.get(event.id, ()),
                    *tuple(getattr(enrichment, "characters", ())),
                    *tuple(getattr(enrichment, "outcomes", ())),
                    *tuple(getattr(enrichment, "warnings", ())),
                )
            )
            if term in f"{event.title} {event.summary} {facts} {claims} {enriched}".casefold():
                if event.hidden:
                    self._show_hidden_target("event", event.id)
                    return True
                parent_arc = next(
                    (candidate for candidate in snapshot.arcs if event.id in candidate.event_ids),
                    None,
                )
                if parent_arc is not None:
                    self.show_arc(parent_arc.id, focus_event_id=event.id)
                    return self.canvas.focus_search_result(event.id)
        session = self._session
        if session is None:
            return False
        beat_to_event = {
            beat_id: event.id for event in snapshot.events for beat_id in event.beat_ids
        }
        generation = self._search_generation

        def operation(
            cancelled: Callable[[], bool], _progress: Callable[[int, str], None]
        ) -> object:
            with PresentationService.open(session.project_path, cancelled=cancelled) as service:
                after: int | str | None = None
                while True:
                    if cancelled():
                        return None
                    page = service.search(term, after=after, limit=100)
                    for item in page.items:
                        if not isinstance(item, SearchHit):
                            continue
                        event_id = beat_to_event.get(item.node_id)
                        if event_id is None:
                            lineage = service.lineage(item.node_id)
                            event_id = next(
                                (
                                    beat_to_event[node.id]
                                    for node in reversed(lineage)
                                    if node.id in beat_to_event
                                ),
                                None,
                            )
                        if event_id is not None:
                            return event_id
                    if not page.continuation.has_more:
                        return None
                    next_after = page.continuation.next_after
                    if next_after is None or next_after == after:
                        return None
                    after = next_after

        task = WorkerTask(operation, self)
        self._search_task = task
        task.succeeded.connect(
            lambda value, expected=generation, current=task: self._accept_search(
                expected, current, value
            )
        )
        task.failed.connect(
            lambda _error, expected=generation: self._search_failed(expected)
        )
        task.finished.connect(lambda current=task: self._finish_search(current))
        self.busy_changed.emit(True)
        self.status_changed.emit("Searching accepted story evidence")
        task.start()
        return True

    def _accept_search(
        self, generation: int, task: WorkerTask, value: object
    ) -> None:
        if generation != self._search_generation or self._session is None:
            return
        if self._search_task is task:
            self._search_task = None
        if not isinstance(value, str) or self._snapshot is None:
            self.status_changed.emit("No accepted story result")
            return
        event = next(
            (event for event in self._snapshot.events if event.id == value), None
        )
        if event is not None and event.hidden:
            self._show_hidden_target("event", event.id)
            return
        parent_arc = next(
            (arc for arc in self._snapshot.arcs if value in arc.event_ids), None
        )
        if parent_arc is None:
            self.status_changed.emit("Result remains in technical organization")
            return
        if parent_arc.hidden:
            self._show_hidden_target("arc", parent_arc.id)
            return
        self.show_arc(parent_arc.id, focus_event_id=value)
        self.canvas.focus_search_result(value)

    def _search_failed(self, generation: int) -> None:
        if generation == self._search_generation and self._session is not None:
            self.error_occurred.emit("Story search failed safely.")

    def _finish_search(self, task: WorkerTask) -> None:
        if self._search_task is task:
            self._search_task = None
        task.deleteLater()
        self.busy_changed.emit(self.is_busy)

    def restore_story_state(self, arc_id: str, event_id: str, level: int) -> None:
        snapshot = self._snapshot
        if snapshot is None:
            return
        valid_arc_ids = {arc.id for arc in snapshot.arcs if not arc.hidden}
        valid_event_ids = {event.id for event in snapshot.events if not event.hidden}
        valid_arc = arc_id if arc_id in valid_arc_ids else ""
        valid_event = event_id if event_id in valid_event_ids else ""
        if valid_event:
            event_parent = next(
                (arc for arc in snapshot.arcs if valid_event in arc.event_ids), None
            )
            if event_parent is None:
                valid_event = ""
            elif not valid_arc:
                valid_arc = event_parent.id
            elif event_parent.id != valid_arc:
                valid_event = ""
        if level <= 1:
            self.show_overview()
            if valid_arc:
                self._selected_arc = valid_arc
                self.canvas.restore_selection(valid_arc)
            return
        if not valid_arc:
            self.show_overview()
            return
        self.show_arc(valid_arc, focus_event_id=valid_event or None)
        if valid_event:
            self._selected_event = valid_event
            self.canvas.restore_selection(valid_event)
        if level >= 3 and valid_event and self._session is not None:
            self.show_evidence(valid_event)

    def show_evidence(self, event_id: str) -> None:
        snapshot = self._snapshot
        session = self._session
        if snapshot is None or session is None or not self.viewing_accepted:
            return
        event = next((item for item in snapshot.events if item.id == event_id), None)
        if event is None or event.hidden:
            return
        self._selected_event = event_id
        self._cancel_search()
        self._set_canvas_level(SemanticLevel.EVIDENCE)
        self._cancel_evidence()
        generation = self._evidence_generation

        def operation(
            cancelled: Callable[[], bool], _progress: Callable[[int, str], None]
        ) -> object:
            return _load_evidence(session.project_path, event, cancelled)

        task = WorkerTask(operation, self)
        self._evidence_task = task
        task.succeeded.connect(
            lambda value, expected=generation: self._accept_evidence(expected, value)
        )
        task.failed.connect(
            lambda _error, expected=generation: self._evidence_failed(expected)
        )
        task.finished.connect(lambda current=task: self._finish_evidence(current))
        self.busy_changed.emit(True)
        task.start()

    def _accept_evidence(self, generation: int, value: object) -> None:
        if generation == self._evidence_generation and self._session is not None:
            self._evidence_loaded(value)

    def _evidence_failed(self, generation: int) -> None:
        if generation == self._evidence_generation and self._session is not None:
            self.error_occurred.emit(
                "Exact evidence could not be loaded. Retry the selected event."
            )

    @Slot(object)
    def _evidence_loaded(self, value: object) -> None:
        if not isinstance(value, _EvidenceSlice):
            return
        self.evidence_timeline.clear()
        self.inspector.evidence.clear()
        for record in value.records:
            if not isinstance(record, EvidenceRecord):
                continue
            caption = (
                f"{record.kind.title()}  •  {record.source_path}:"
                f"{record.start_line}-{record.end_line}"
            )
            item = QListWidgetItem(f"{caption}\n{record.text}")
            item.setData(Qt.ItemDataRole.UserRole, record)
            item.setData(
                Qt.ItemDataRole.AccessibleTextRole, f"{caption}. {record.text}"
            )
            self.evidence_timeline.addItem(item)
            self.inspector.evidence.addItem(caption)
        self.center_stack.setCurrentWidget(self.evidence_timeline)
        self.level_changed.emit(3)
        self.visible_count_changed.emit(self.evidence_timeline.count())
        suffix = " | truncated at 240 records" if value.truncated else ""
        self.status_changed.emit(f"Exact source evidence{suffix}")
        if self.evidence_timeline.count():
            self.evidence_timeline.setCurrentRow(0)
            self.evidence_timeline.setFocus(Qt.FocusReason.OtherFocusReason)

    def _finish_evidence(self, task: WorkerTask) -> None:
        if self._evidence_task is task:
            self._evidence_task = None
        task.deleteLater()
        self.busy_changed.emit(self.is_busy)

    @Slot(object)
    def _selected(self, value: object) -> None:
        if value is None and self.viewing_accepted:
            self._selected_event = None
            if self.canvas.semantic_level is SemanticLevel.OVERVIEW:
                self._selected_arc = None
            self.selection_context_changed.emit(self.selected_target)
            return
        if (
            not isinstance(value, str)
            or self._snapshot is None
            or not self.viewing_accepted
        ):
            return
        arc = next((item for item in self._snapshot.arcs if item.id == value), None)
        if arc is not None:
            self._selected_arc = value
            self._selected_event = None
            self.inspector.summary.setText(arc.summary)
            self.selection_context_changed.emit(self.selected_target)
            return
        event = next((item for item in self._snapshot.events if item.id == value), None)
        if event is None:
            return
        self._selected_event = value
        self.inspector.summary.setText(event.summary)
        self.inspector.state.clear()
        for fact in self._snapshot.facts:
            if fact.event_id == event.id:
                label = "Requirement" if fact.fact_kind == "gate" else "Effect"
                _add_bounded_item(
                    self.inspector.state, f"{label}  •  {fact.expression}"
                )
        for claim in self._snapshot.claims:
            if claim.event_id == event.id:
                _add_bounded_item(
                    self.inspector.state, f"Interpretation  •  {claim.text}"
                )
        details: list[str] = []
        enrichment = next(
            (
                item
                for item in self._snapshot.enrichments
                if getattr(item, "target_kind", "") == "event"
                and getattr(item, "target_id", "") == event.id
            ),
            None,
        )
        if enrichment is not None:
            for outcome in getattr(enrichment, "outcomes", ()):
                _add_bounded_item(self.inspector.state, f"Outcome  •  {outcome}")
            for warning in getattr(enrichment, "warnings", ()):
                _add_bounded_item(self.inspector.state, f"Warning  •  {warning}")
            characters = tuple(getattr(enrichment, "characters", ()))
            if characters:
                details.append(f"Characters: {', '.join(characters)}")
            details.append(
                f"Importance: {getattr(enrichment, 'importance', 'supporting')}"
            )
        details.extend(
            (
                f"{len(event.beat_ids)} deterministic beats",
                event.origin.title(),
                "Needs review" if event.needs_review else "Reviewed",
            )
        )
        self.inspector.details.setText("  •  ".join(details))
        self.selection_context_changed.emit(self.selected_target)

    @Slot(str, bool)
    def _expanded(self, identifier: str, expanded: bool) -> None:
        if not self.viewing_accepted:
            return
        if not expanded:
            self.show_overview()
        elif self._snapshot and any(arc.id == identifier for arc in self._snapshot.arcs):
            self.show_arc(identifier)
        else:
            self.show_evidence(identifier)

    @Slot(int)
    def _semantic_level_requested(self, value: int) -> None:
        if self._syncing_level or not self.viewing_accepted or self._snapshot is None:
            return
        level = SemanticLevel(value)
        if level is SemanticLevel.OVERVIEW:
            self.show_overview()
            return
        if level is SemanticLevel.EVENTS:
            arc_id = self._selected_arc or (
                next(
                    (arc.id for arc in self._snapshot.arcs if not arc.hidden),
                    None,
                )
            )
            if arc_id is not None:
                self.show_arc(arc_id, focus_event_id=self._selected_event)
            return
        event_id = self._selected_event
        if event_id is None:
            arc = next(
                (arc for arc in self._snapshot.arcs if arc.id == self._selected_arc),
                next(
                    (arc for arc in self._snapshot.arcs if not arc.hidden),
                    None,
                ),
            )
            event_id = (
                next(
                    (
                        event.id
                        for event in self._snapshot.events
                        if event.id in arc.event_ids and not event.hidden
                    ),
                    None,
                )
                if arc is not None
                else None
            )
        if event_id is not None:
            self.show_evidence(event_id)

    def _set_canvas_level(self, level: SemanticLevel) -> None:
        self._syncing_level = True
        try:
            self.canvas.set_semantic_level(level)
        finally:
            self._syncing_level = False

    @Slot(QListWidgetItem)
    def _navigator_activated(self, item: QListWidgetItem) -> None:
        kind, identifier = cast(tuple[str, str], item.data(Qt.ItemDataRole.UserRole))
        if kind == "overview":
            self.accepted_map_requested.emit()
        elif kind == "arc":
            if self._technical_mode:
                self.accepted_map_requested.emit()
            self.show_arc(identifier)
        elif kind == "technical":
            self.technical_map_requested.emit()
        elif kind == "event-page-previous":
            self._page_arc(identifier, -1)
        elif kind == "event-page-next":
            self._page_arc(identifier, 1)
        elif kind in {"hidden-arc", "hidden-event"}:
            self._show_hidden_target(kind.removeprefix("hidden-"), identifier)

    def _show_hidden_target(self, kind: str, identifier: str) -> None:
        snapshot = self._snapshot
        if snapshot is None or kind not in {"arc", "event"}:
            return
        values = snapshot.arcs if kind == "arc" else snapshot.events
        target = next((value for value in values if value.id == identifier), None)
        if target is None or not target.hidden:
            return
        self._technical_mode = False
        if kind == "arc":
            self._selected_arc = identifier
            self._selected_event = None
        else:
            self._selected_event = identifier
            self._selected_arc = next(
                (arc.id for arc in snapshot.arcs if identifier in arc.event_ids), None
            )
        self.canvas.set_slice((), (), preserve_navigation=True)
        self.center_stack.setCurrentWidget(self.canvas_page)
        self.inspector.summary.setText(target.summary)
        self.inspector.details.setText(
            f"Hidden accepted {kind} | use Unhide selected to restore it"
        )
        self.status_changed.emit(f"Hidden accepted {kind}: {target.title}")
        self.visible_count_changed.emit(0)
        self.selection_context_changed.emit(self.selected_target)


class OrganizationUiController(QObject):
    progress_changed = Signal(int, str)
    busy_changed = Signal(bool)
    draft_ready = Signal(str, object)
    organization_changed = Signal()
    organization_outcome = Signal(str)
    review_saved = Signal(str, str, str)
    error_occurred = Signal(str)

    def __init__(
        self,
        provider_factory: Callable[[CodexMode], OrganizationProvider] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._project_path: Path | None = None
        self._task: WorkerTask | None = None
        self._organize_requests = 0
        self._generation = 0
        self._provider_factory = provider_factory or (lambda mode: CodexCliProvider(mode))

    @property
    def is_busy(self) -> bool:
        return self._task is not None

    @property
    def organize_requests(self) -> int:
        return self._organize_requests

    def set_project(self, session: ProjectSession | None) -> None:
        self._generation += 1
        self.cancel()
        self._project_path = None if session is None else session.project_path

    def organize(
        self,
        scope_ids: Sequence[str],
        options: OrganizationOptions,
        *,
        cloud_confirmed: bool = False,
    ) -> bool:
        path = self._project_path
        if path is None or self._task is not None:
            return False
        if options.mode is CodexMode.CODEX_CHATGPT and not cloud_confirmed:
            self.error_occurred.emit("Cloud organization was not confirmed for this run.")
            return False
        consent_run_ids: set[str] = set()

        def confirm_cloud(run_id: str) -> bool:
            if not cloud_confirmed or consent_run_ids:
                return False
            consent_run_ids.add(run_id)
            return True

        def operation(
            cancelled: Callable[[], bool], progress: Callable[[int, str], None]
        ) -> object:
            with Project.open(path) as project:
                workflow = OrganizationWorkflow(
                    project,
                    self._provider_factory,
                )
                return workflow.organize(
                    tuple(scope_ids),
                    options,
                    progress=progress,
                    cancelled=cancelled,
                    confirm_cloud=confirm_cloud,
                )

        started = self._start(operation, self._accept_workflow)
        if started:
            self._organize_requests += 1
        return started

    def review_group(self, draft_id: str, kind: str, identifier: str, decision: str) -> bool:
        return self._project_operation(
            lambda service: service.review_draft_group(
                draft_id,
                cast(Literal["arc", "event"], kind),
                identifier,
                cast(Literal["approved", "rejected"], decision),
            ),
            lambda _value: self.review_saved.emit(kind, identifier, decision),
        )

    def apply_draft(self, draft_id: str) -> bool:
        return self._project_operation(
            lambda service: service.apply_draft(draft_id),
            lambda _value: self._emit_change("applied"),
        )

    def discard_draft(self, draft_id: str) -> bool:
        return self._project_operation(
            lambda service: service.discard_draft(draft_id),
            lambda _value: self._emit_change("discarded"),
        )

    def mutate(self, action: Callable[[StoryOrganizationService], object]) -> bool:
        return self._project_operation(action, lambda _value: self._emit_change("edited"))

    def _emit_change(self, outcome: str) -> None:
        self.organization_outcome.emit(outcome)
        self.organization_changed.emit()

    def cancel(self) -> None:
        if self._task is not None:
            self._task.cancel()

    def _project_operation(
        self,
        action: Callable[[StoryOrganizationService], object],
        accept: Callable[[object], None],
    ) -> bool:
        path = self._project_path
        if path is None or self._task is not None:
            return False

        def operation(
            cancelled: Callable[[], bool], _progress: Callable[[int, str], None]
        ) -> object:
            if cancelled():
                raise OrganizationCancelledError("The story operation was cancelled.")
            with Project.open(path) as project:
                return action(project.organization_service())

        return self._start(operation, accept)

    def _start(
        self,
        operation: Callable[[Callable[[], bool], Callable[[int, str], None]], object],
        accept: Callable[[object], None],
    ) -> bool:
        generation = self._generation
        task = WorkerTask(operation, self)
        self._task = task
        task.progress.connect(
            lambda percent, status, expected=generation: self._progress_if_current(
                expected, percent, status
            )
        )
        task.succeeded.connect(
            lambda value, expected=generation: self._accept_if_current(
                expected, accept, value
            )
        )
        task.failed.connect(
            lambda error, expected=generation: self._error_if_current(expected, error)
        )
        task.finished.connect(lambda current=task: self._finish_task(current))
        self.busy_changed.emit(True)
        task.start()
        return True

    def _progress_if_current(self, generation: int, percent: int, status: str) -> None:
        if generation == self._generation:
            self.progress_changed.emit(percent, status)

    def _accept_if_current(
        self,
        generation: int,
        accept: Callable[[object], None],
        value: object,
    ) -> None:
        if generation == self._generation:
            accept(value)

    def _error_if_current(self, generation: int, error: object) -> None:
        if generation == self._generation:
            self.error_occurred.emit(_safe_operation_error(error))

    @Slot(object)
    def _accept_workflow(self, value: object) -> None:
        if isinstance(value, WorkflowResult):
            self.draft_ready.emit(value.draft_id, value)

    def _finish_task(self, task: WorkerTask) -> None:
        if self._task is task:
            self._task = None
        task.deleteLater()
        self.busy_changed.emit(self.is_busy)


def apply_story_palette(widget: QWidget, *, dark: bool) -> None:
    """Apply the approved restrained Windows palette at runtime."""

    widget.setProperty("storyPaletteApplying", True)
    widget.setProperty("storyPaletteDark", dark)
    raw_zoom = widget.property("applicationZoomPercent")
    zoom = int(raw_zoom) if isinstance(raw_zoom, int) else 100
    metadata_size = round(12 * zoom / 100)
    title_size = round(24 * zoom / 100)
    palette = QPalette(widget.palette())
    if dark:
        palette.setColor(QPalette.ColorRole.Window, QColor("#111820"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#18222D"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#202D39"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#F2F6F8"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#F2F6F8"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#22313F"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#F2F6F8"))
    else:
        palette.setColor(QPalette.ColorRole.Window, QColor("#F4F7F9"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#EEF3F6"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#17212B"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#17212B"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#FFFFFF"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#17212B"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#0891B2"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    try:
        widget.setStyleSheet(
            "QWidget { font-family: 'Segoe UI'; }"
            f"#welcomeEyebrow {{ color: #0891B2; font-size: {metadata_size}px; "
            "font-weight: 700; }"
            f"#welcomeTitle {{ font-size: {title_size}px; font-weight: 650; }}"
            "QTabBar::tab { min-height: 30px; padding: 4px 10px; }"
            "QPushButton { min-height: 30px; padding: 3px 12px; }"
            "QPushButton:focus, QListWidget:focus, QLineEdit:focus, QComboBox:focus {"
            " border: 2px solid #0891B2; }"
        )
        # Stylesheet repolishing may restore its cached palette, so palette is applied last.
        widget.setPalette(palette)
    finally:
        widget.setProperty("storyPaletteApplying", False)


def _safe_operation_error(error: object) -> str:
    if isinstance(error, OrganizationError):
        text = " ".join(str(error).replace("\x00", "").split())
        if text:
            return text[:320]
    return "The operation failed safely. Open Help > Diagnostics for details."


def _load_snapshot(path: Path) -> StorySnapshot:
    with Project.open(path) as project:
        service = project.organization_service()
        arcs = service.arcs(include_hidden=True)
        events = service.events(include_hidden=True)
        pending = service.drafts(status="pending")
        runs = service.runs()
        pending_draft = pending[-1] if pending else None
        matched_run = (
            next(
                (run for run in reversed(runs) if run.id == pending_draft.run_id),
                None,
            )
            if pending_draft is not None
            else (runs[-1] if runs else None)
        )
        enrichment_reader = getattr(service, "enrichments", None)
        enrichments = tuple(enrichment_reader()) if callable(enrichment_reader) else ()
        return StorySnapshot(
            arcs,
            events,
            service.event_edges(),
            service.arc_edges(),
            service.attached_facts(),
            service.claims(),
            pending_draft,
            matched_run,
            service.draft_reviews(pending_draft.id) if pending_draft is not None else (),
            _event_characters(project, events),
            enrichments,
            _event_filter_metadata(project, events),
        )


def _load_evidence(
    path: Path, event: StoryEvent, cancelled: Callable[[], bool]
) -> _EvidenceSlice:
    with PresentationService.open(path, cancelled=cancelled) as presentation:
        records: list[EvidenceRecord] = []
        seen: set[str] = set()
        truncated = False
        for beat_index, beat_id in enumerate(event.beat_ids):
            if cancelled():
                break
            after: str | None = None
            while True:
                if cancelled():
                    return _EvidenceSlice(tuple(records), truncated)
                remaining = MAX_VISIBLE_ITEMS - len(records)
                if remaining <= 0:
                    truncated = True
                    break
                page = presentation.evidence(
                    beat_id, after=after, limit=min(100, remaining)
                )
                for value in page.items:
                    if isinstance(value, EvidenceRecord) and value.id not in seen:
                        seen.add(value.id)
                        records.append(value)
                        if len(records) == MAX_VISIBLE_ITEMS:
                            break
                if len(records) == MAX_VISIBLE_ITEMS:
                    truncated = page.continuation.has_more or beat_index + 1 < len(event.beat_ids)
                    break
                if not page.continuation.has_more:
                    break
                next_after = page.continuation.next_after
                if next_after is None or next_after == after:
                    break
                after = next_after
            if len(records) == MAX_VISIBLE_ITEMS:
                break
        return _EvidenceSlice(tuple(records), truncated)


def _event_kind(event: StoryEvent, edge_kinds: set[str]) -> str:
    for kind in ("choice", "loop", "call", "return", "ending", "unresolved"):
        if any(kind in value for value in edge_kinds):
            return kind
    return "event"


def _arc_overview_summary(arc: StoryArc, snapshot: StorySnapshot) -> str:
    event_ids = set(arc.event_ids)
    character_map = dict(snapshot.event_characters)
    enrichment_by_target = {
        (getattr(value, "target_kind", ""), getattr(value, "target_id", "")): value
        for value in snapshot.enrichments
    }
    arc_enrichment = enrichment_by_target.get(("arc", arc.id))
    enriched_characters = {
        character
        for target in [arc_enrichment]
        if target is not None
        for character in getattr(target, "characters", ())
    }.union(
        character
        for event_id in event_ids
        for character in getattr(
            enrichment_by_target.get(("event", event_id)), "characters", ()
        )
    )
    characters = sorted(
        {name for event_id in event_ids for name in character_map.get(event_id, ())}
        | enriched_characters
    )
    facts = [fact for fact in snapshot.facts if fact.event_id in event_ids]
    requirements = sum(fact.fact_kind == "gate" for fact in facts)
    effects = sum(fact.fact_kind == "effect" for fact in facts)
    claims = [
        claim
        for claim in snapshot.claims
        if claim.arc_id == arc.id or claim.event_id in event_ids
    ]
    outcome_values = {
        outcome
        for target in [arc_enrichment]
        if target is not None
        for outcome in getattr(target, "outcomes", ())
    }.union(
        outcome
        for event_id in event_ids
        for outcome in getattr(
            enrichment_by_target.get(("event", event_id)), "outcomes", ()
        )
    )
    outcomes = len(outcome_values) + sum(claim.kind == "outcome" for claim in claims) + sum(
        edge.kind == "ending" and edge.source_id in event_ids for edge in snapshot.event_edges
    )
    evidence = {
        (fact.source_path, fact.start_line, fact.end_line) for fact in facts
    }.union(evidence_id for claim in claims for evidence_id in claim.evidence_ids)
    character_text = ", ".join(characters[:3]) if characters else "No named speaker"
    importance = getattr(arc_enrichment, "importance", "supporting")
    return (
        f"{arc.summary}  •  Characters: {character_text}  •  "
        f"Requirements {requirements}  •  Effects {effects}  •  "
        f"Outcomes {outcomes}  •  Evidence {len(evidence)}  •  {importance.title()}"
    )


def _event_characters(
    project: Project, events: Sequence[StoryEvent]
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    event_by_beat = {
        beat_id: event.id for event in events for beat_id in event.beat_ids
    }
    characters: dict[str, set[str]] = {}
    beat_ids = sorted(event_by_beat)
    connection = project._require_open()
    for start in range(0, len(beat_ids), 500):
        batch = beat_ids[start : start + 500]
        placeholders = ",".join("?" for _ in batch)
        rows = connection.execute(
            f"""SELECT node_id,payload_json FROM presentation_evidence
                WHERE node_id IN ({placeholders}) ORDER BY sort_key,evidence_id""",
            batch,
        )
        for row in rows:
            event_id = event_by_beat.get(str(row["node_id"]))
            if event_id is None:
                continue
            payload = storage.decode_json(row["payload_json"])
            for name in _speaker_names(payload):
                characters.setdefault(event_id, set()).add(name)
    return tuple(
        (event_id, tuple(sorted(names)))
        for event_id, names in sorted(characters.items())
    )


def _event_filter_metadata(
    project: Project, events: Sequence[StoryEvent]
) -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]:
    event_ids = sorted(event.id for event in events)
    variables: dict[str, set[str]] = {}
    categories: dict[str, set[str]] = {}
    connection = project._require_open()
    for start in range(0, len(event_ids), 500):
        batch = event_ids[start : start + 500]
        placeholders = ",".join("?" for _ in batch)
        rows = connection.execute(
            f"""SELECT m.event_id,f.variable,f.category
                FROM story_event_members m
                JOIN presentation_facts f ON f.node_id=m.beat_id
                WHERE m.event_id IN ({placeholders})
                  AND (f.variable IS NOT NULL OR f.category IS NOT NULL)
                ORDER BY m.event_id,f.sort_key,f.fact_id""",
            batch,
        )
        for row in rows:
            event_id = str(row["event_id"])
            if row["variable"] is not None:
                variables.setdefault(event_id, set()).add(str(row["variable"]))
            if row["category"] is not None:
                categories.setdefault(event_id, set()).add(str(row["category"]))
    return tuple(
        (
            event_id,
            tuple(sorted(variables.get(event_id, set()))),
            tuple(sorted(categories.get(event_id, set()))),
        )
        for event_id in sorted(set(variables) | set(categories))
    )


def _speaker_names(value: object) -> tuple[str, ...]:
    names: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"speaker", "character"} and isinstance(item, str) and item.strip():
                names.add(item.strip())
            elif isinstance(item, (dict, list)):
                names.update(_speaker_names(item))
    elif isinstance(value, list):
        for item in value:
            names.update(_speaker_names(item))
    return tuple(sorted(names))


def _draft_scope(candidate: Mapping[str, object]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    scope = candidate.get("_scope")
    if not isinstance(scope, Mapping):
        return (), ()
    return (
        _string_sequence(scope.get("scope_ids")),
        _string_sequence(scope.get("covered_beat_ids")),
    )


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _bounded_text(value: object, maximum: int) -> str:
    text = (
        str(value)
        .replace("\x00", "")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
    )
    if not text:
        return "No bounded detail supplied"
    return text if len(text) <= maximum else text[: maximum - 3] + "..."


def _review_group_text(
    kind: str,
    identifier: str,
    value: Mapping[str, object],
    claims: Sequence[object],
    decision: str | None,
) -> str:
    members = _string_sequence(
        value.get("event_ids") if kind == "arc" else value.get("beat_ids")
    )
    target_key = "arc_id" if kind == "arc" else "event_id"
    target_claims = [
        claim
        for claim in claims
        if isinstance(claim, Mapping) and claim.get(target_key) == identifier
    ]
    evidence_ids = {
        evidence
        for claim in target_claims
        for evidence in _string_sequence(claim.get("evidence_ids"))
    }
    outcomes = _string_sequence(value.get("outcomes"))
    warnings = _string_sequence(value.get("warnings"))
    state = decision.title() if decision is not None else "Decision pending"
    return (
        f"{kind.title()} | {_bounded_text(value.get('title', identifier), 80)} | {state}\n"
        f"{_bounded_text(value.get('summary'), 160)} | Members {len(members)} | "
        f"Claims {len(target_claims)} | Evidence {len(evidence_ids)} | "
        f"Outcomes {len(outcomes)} | Warnings {len(warnings)}"
    )


def _split_merge_counts(
    current_events: Sequence[StoryEvent], proposed_events: Sequence[Mapping[str, object]]
) -> tuple[int, int]:
    """Calculate membership changes in linear time over deterministic beat membership."""

    current_by_beat = {
        beat_id: index
        for index, event in enumerate(current_events)
        for beat_id in event.beat_ids
    }
    proposed_by_beat = {
        beat_id: index
        for index, event in enumerate(proposed_events)
        for beat_id in _string_sequence(event.get("beat_ids"))
    }
    proposed_per_current: dict[int, set[int]] = {}
    current_per_proposed: dict[int, set[int]] = {}
    for beat_id, current_index in current_by_beat.items():
        proposed_index = proposed_by_beat.get(beat_id)
        if proposed_index is None:
            continue
        proposed_per_current.setdefault(current_index, set()).add(proposed_index)
        current_per_proposed.setdefault(proposed_index, set()).add(current_index)
    return (
        sum(len(values) > 1 for values in proposed_per_current.values()),
        sum(len(values) > 1 for values in current_per_proposed.values()),
    )


def _add_bounded_item(widget: QListWidget, text: str) -> None:
    if widget.count() < MAX_VISIBLE_ITEMS:
        widget.addItem(_bounded_text(text, 320))


def _padded(widget: QWidget) -> QWidget:
    host = QWidget()
    layout = QVBoxLayout(host)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.addWidget(widget)
    return host


__all__ = [
    "MAX_ARCS",
    "MAX_EVENTS",
    "AcceptedStoryPresenter",
    "DraftReviewDialog",
    "InspectorTabs",
    "OrganizationUiController",
    "StorySnapshot",
    "WelcomeWidget",
    "apply_story_palette",
]
