"""Arc-first Windows Story Explorer shell."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Literal, cast

from PySide6.QtCore import QDateTime, QEvent, QSettings, Qt, QTimer, Slot
from PySide6.QtGui import QAction, QCloseEvent, QGuiApplication, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from renpy_story_mapper.organization import CodexMode
from renpy_story_mapper.ui.graph_canvas import SemanticLevel
from renpy_story_mapper.ui.organization_workflow import OrganizationOptions
from renpy_story_mapper.ui.project_controller import (
    LifecycleState,
    PresentationService,
    ProjectController,
    ProjectSession,
)
from renpy_story_mapper.ui.story_explorer import (
    AcceptedStoryPresenter,
    DraftReviewDialog,
    InspectorTabs,
    OrganizationUiController,
    WelcomeWidget,
    apply_story_palette,
)


class MainWindow(QMainWindow):
    """Windows project lifecycle plus the arc-first Story Explorer workspace."""

    def __init__(
        self,
        controller: ProjectController | None = None,
        presentation_service: PresentationService | None = None,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__()
        self.controller = controller or ProjectController(parent=self)
        self._presentation_service = presentation_service
        self._presentation_busy = False
        self._close_when_idle = False
        self._review_dialog: DraftReviewDialog | None = None
        self._current_project_path: str | None = None
        self._last_organization_options: OrganizationOptions | None = None
        self._last_organization_scopes: tuple[str, ...] = ()
        self._organization_started_at: float | None = None
        self._organization_status = ""
        self._recovery_callback: Callable[[], None] | None = None
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(250)
        self._elapsed_timer.timeout.connect(self._update_elapsed_status)
        self._settings = (
            settings if settings is not None else QSettings("RenPyStoryMapper", "StoryMapper")
        )
        self.setWindowTitle("Ren'Py Story Mapper")
        self.resize(1280, 800)
        self._build_toolbar()
        self._build_center()
        self._build_docks()
        if presentation_service is None:
            self._install_default_story_map()
        self._connect_controller()
        self._restore_preferences()
        apply_story_palette(self, dark=_is_dark_palette())
        self._apply_state(LifecycleState.EMPTY.value)

    def set_graph_widget(self, widget: QWidget) -> None:
        """Replace the graph hook without coupling the shell to its implementation."""
        old = self.graph_layout.takeAt(0)
        old_widget = None if old is None else old.widget()
        if old_widget is not None:
            old_widget.setParent(None)
        widget.setObjectName("graphCanvas")
        self.graph_layout.addWidget(widget)

    def set_presentation_service(self, service: PresentationService | None) -> None:
        """Install a presentation adapter without importing its unfinished implementation."""
        self._presentation_service = service
        service_session = self.controller.session
        if service is not None:
            service.set_project(service_session)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Project", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.select_source_button = QPushButton("Folder", self)
        self.select_source_button.setObjectName("newProjectButton")
        self.select_archive_button = QPushButton("Archive", self)
        self.select_archive_button.setObjectName("newArchiveProjectButton")
        self.open_button = QPushButton("Open", self)
        self.open_button.setObjectName("openProjectButton")
        self.refresh_button = QPushButton("Refresh", self)
        self.refresh_button.setObjectName("refreshProjectButton")
        self.close_button = QPushButton("Close", self)
        self.close_button.setObjectName("closeProjectButton")
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setObjectName("cancelOperationButton")
        for button in (
            self.select_source_button,
            self.select_archive_button,
            self.open_button,
            self.refresh_button,
            self.close_button,
            self.cancel_button,
        ):
            toolbar.addWidget(button)
        self.select_source_button.clicked.connect(self._choose_new_project)
        self.select_archive_button.clicked.connect(self._choose_new_archive_project)
        self.open_button.clicked.connect(self._choose_existing_project)
        self.refresh_button.clicked.connect(self.controller.refresh_project)
        self.close_button.clicked.connect(self.controller.close_project)
        self.cancel_button.clicked.connect(self._cancel_operations)

        help_menu = self.menuBar().addMenu("Help")
        self.diagnostics_action = QAction("Diagnostics", self)
        self.diagnostics_action.setCheckable(True)
        help_menu.addAction(self.diagnostics_action)
        edit_menu = self.menuBar().addMenu("Edit")
        self.corrections_action = QAction("Selected story item…", self)
        self.corrections_action.setCheckable(True)
        edit_menu.addAction(self.corrections_action)

    def _build_center(self) -> None:
        self.page_stack = QStackedWidget(self)
        self.page_stack.setObjectName("applicationPages")
        self.welcome_page = WelcomeWidget(self.page_stack)
        self.page_stack.addWidget(self.welcome_page)
        self.workspace_page = QWidget(self.page_stack)
        self.workspace_page.setObjectName("storyWorkspace")
        layout = QVBoxLayout(self.workspace_page)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self.command_bar = QHBoxLayout()
        self.project_name_label = QLabel("Story Mapper", self.workspace_page)
        self.project_name_label.setObjectName("projectName")
        self.breadcrumb_label = QLabel("Overview", self.workspace_page)
        self.breadcrumb_label.setObjectName("storyBreadcrumb")
        self.search_input = QLineEdit(self.workspace_page)
        self.search_input.setObjectName("storySearch")
        self.search_input.setPlaceholderText("Search story")
        self.search_input.setAccessibleName("Search the story map")
        self.filter_button = QPushButton("Filters", self.workspace_page)
        self.filter_button.setObjectName("filterMenuButton")
        self.view_button = QPushButton("View", self.workspace_page)
        self.view_button.setObjectName("viewMenuButton")
        self.organize_button = QPushButton("Organize Story", self.workspace_page)
        self.organize_button.setObjectName("organizeStoryButton")
        for widget in (
            self.project_name_label,
            self.breadcrumb_label,
            self.search_input,
            self.filter_button,
            self.view_button,
            self.organize_button,
        ):
            self.command_bar.addWidget(widget)
        self.command_bar.setStretchFactor(self.search_input, 1)
        layout.addLayout(self.command_bar)

        self.technical_filter = QCheckBox(
            "Technical map / unorganized scopes", self.workspace_page
        )
        self.technical_filter.setObjectName("technicalFilter")
        self.unresolved_filter = QCheckBox("Unresolved behavior", self.workspace_page)
        self.unresolved_filter.setObjectName("unresolvedFilter")
        self.variable_filter_input = QLineEdit(self.workspace_page)
        self.variable_filter_input.setObjectName("variableFilter")
        self.variable_filter_input.setPlaceholderText("Variable")
        self.category_filter_input = QLineEdit(self.workspace_page)
        self.category_filter_input.setObjectName("categoryFilter")
        self.category_filter_input.setPlaceholderText("Category")

        self.filter_menu = QMenu(self)
        filter_host = QWidget(self.filter_menu)
        filter_layout = QFormLayout(filter_host)
        filter_layout.setContentsMargins(10, 8, 10, 8)
        filter_layout.addRow("Variable", self.variable_filter_input)
        filter_layout.addRow("Category", self.category_filter_input)
        filter_widget_action = QWidgetAction(self.filter_menu)
        filter_widget_action.setDefaultWidget(filter_host)
        self.filter_menu.addAction(filter_widget_action)
        self.filter_button.setMenu(self.filter_menu)
        self.view_menu = QMenu(self)
        technical_action = QWidgetAction(self.view_menu)
        technical_action.setDefaultWidget(self.technical_filter)
        unresolved_action = QWidgetAction(self.view_menu)
        unresolved_action.setDefaultWidget(self.unresolved_filter)
        self.view_menu.addAction(technical_action)
        self.view_menu.addAction(unresolved_action)
        self.view_button.setMenu(self.view_menu)

        self.navigator = QListWidget(self.workspace_page)
        self.navigator.setObjectName("projectNavigator")
        self.navigator.setAccessibleName("Project and story navigator")
        self.navigator.setMinimumWidth(240)
        self.navigator.setMaximumWidth(340)
        self.graph_host = QWidget(self.workspace_page)
        self.graph_host.setObjectName("graphHost")
        self.graph_layout = QVBoxLayout(self.graph_host)
        graph_placeholder = QLabel("Story map", self.graph_host)
        graph_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.graph_layout.addWidget(graph_placeholder)
        self.center_stack = QStackedWidget(self.workspace_page)
        self.center_stack.setObjectName("semanticCenter")
        self.center_stack.addWidget(self.graph_host)
        self.evidence_timeline = QListWidget(self.center_stack)
        self.evidence_timeline.setObjectName("evidenceTimeline")
        self.evidence_timeline.setAccessibleName("Exact story evidence timeline")
        self.center_stack.addWidget(self.evidence_timeline)
        self.inspector = InspectorTabs(self.workspace_page)
        self.inspector.setMinimumWidth(320)
        self.inspector.setMaximumWidth(460)
        self.evidence_list = self.inspector.evidence
        splitter = QSplitter(Qt.Orientation.Horizontal, self.workspace_page)
        splitter.setObjectName("storyWorkspaceSplitter")
        splitter.addWidget(self.navigator)
        splitter.addWidget(self.center_stack)
        splitter.addWidget(self.inspector)
        splitter.setSizes([280, 720, 360])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        layout.addWidget(splitter, 1)

        status = QHBoxLayout()
        self.level_status = QLabel("Level 1", self.workspace_page)
        self.level_status.setObjectName("semanticLevelStatus")
        self.visible_count_status = QLabel("0 visible", self.workspace_page)
        self.visible_count_status.setObjectName("visibleItemStatus")
        self.provenance_status = QLabel("Technical organization", self.workspace_page)
        self.provenance_status.setObjectName("organizationProvenance")
        self.status_label = QLabel("No project open", self.workspace_page)
        self.status_label.setObjectName("projectStatus")
        self.progress_bar = QProgressBar(self.workspace_page)
        self.progress_bar.setObjectName("projectProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self.recovery_button = QPushButton("Retry", self.workspace_page)
        self.recovery_button.setObjectName("recoveryAction")
        self.recovery_button.setAccessibleName("Retry the last story operation")
        self.recovery_button.hide()
        self.recovery_button.clicked.connect(self._run_recovery)
        status.addWidget(self.level_status)
        status.addWidget(self.visible_count_status)
        status.addWidget(self.provenance_status)
        status.addWidget(self.status_label, 1)
        status.addWidget(self.recovery_button)
        status.addWidget(self.progress_bar)
        layout.addLayout(status)
        self.page_stack.addWidget(self.workspace_page)
        self.setCentralWidget(self.page_stack)
        self.page_stack.setCurrentWidget(self.welcome_page)
        self.welcome_page.open_folder.connect(self._choose_new_project)
        self.welcome_page.open_archive.connect(self._choose_new_archive_project)
        self.welcome_page.open_project.connect(self._choose_existing_project)
        self.welcome_page.recent_selected.connect(self.controller.open_project)

    def _build_docks(self) -> None:
        diagnostics = QDockWidget("Diagnostics", self)
        diagnostics.setObjectName("diagnosticsDock")
        self.diagnostics_list = QListWidget(diagnostics)
        self.diagnostics_list.setObjectName("diagnosticsLog")
        diagnostics.setWidget(self.diagnostics_list)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, diagnostics)
        diagnostics.hide()
        self.diagnostics_action.toggled.connect(diagnostics.setVisible)
        diagnostics.visibilityChanged.connect(self.diagnostics_action.setChecked)

        overrides = QDockWidget("Overrides", self)
        overrides.setObjectName("overridesDock")
        self.overrides_host = QWidget(overrides)
        self.overrides_host.setObjectName("userOverridesHost")
        override_form = QFormLayout(self.overrides_host)
        self.node_name_input = QLineEdit(self.overrides_host)
        self.node_name_input.setObjectName("nodeNameOverride")
        self.rename_node_button = QPushButton("Rename", self.overrides_host)
        self.rename_node_button.setObjectName("renameNodeButton")
        self.reset_node_name_button = QPushButton("Reset name", self.overrides_host)
        self.reset_node_name_button.setObjectName("resetNodeNameButton")
        self.hide_node_button = QPushButton("Hide selected", self.overrides_host)
        self.hide_node_button.setObjectName("hideNodeButton")
        self.state_variable_input = QLineEdit(self.overrides_host)
        self.state_variable_input.setObjectName("stateVariableName")
        self.state_display_input = QLineEdit(self.overrides_host)
        self.state_display_input.setObjectName("stateVariableDisplayName")
        self.state_category_input = QLineEdit(self.overrides_host)
        self.state_category_input.setObjectName("stateVariableCategory")
        self.update_state_button = QPushButton("Update variable", self.overrides_host)
        self.update_state_button.setObjectName("updateStateVariableButton")
        override_form.addRow("Node name", self.node_name_input)
        override_form.addRow(self.rename_node_button)
        override_form.addRow(self.reset_node_name_button)
        override_form.addRow(self.hide_node_button)
        override_form.addRow("Variable", self.state_variable_input)
        override_form.addRow("Display", self.state_display_input)
        override_form.addRow("Category", self.state_category_input)
        override_form.addRow(self.update_state_button)
        overrides.setWidget(self.overrides_host)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, overrides)
        self.pin_node_button = QPushButton("Pin / unpin", self.overrides_host)
        self.pin_node_button.setObjectName("pinNodeButton")
        self.approve_node_button = QPushButton("Approve", self.overrides_host)
        self.approve_node_button.setObjectName("approveNodeButton")
        self.reject_node_button = QPushButton("Reject", self.overrides_host)
        self.reject_node_button.setObjectName("rejectNodeButton")
        self.split_boundary_input = QComboBox(self.overrides_host)
        self.split_boundary_input.setObjectName("splitBoundaryBeat")
        self.split_boundary_input.setAccessibleName("Split boundary")
        self.split_event_button = QPushButton("Split event", self.overrides_host)
        self.split_event_button.setObjectName("splitEventButton")
        self.merge_target_input = QComboBox(self.overrides_host)
        self.merge_target_input.setObjectName("mergeTargetEvent")
        self.merge_target_input.setAccessibleName("Adjacent event to merge")
        self.merge_event_button = QPushButton("Merge events", self.overrides_host)
        self.merge_event_button.setObjectName("mergeEventButton")
        self.move_target_input = QComboBox(self.overrides_host)
        self.move_target_input.setObjectName("moveTargetArc")
        self.move_target_input.setAccessibleName("Target story arc")
        self.move_event_button = QPushButton("Move event", self.overrides_host)
        self.move_event_button.setObjectName("moveEventButton")
        for widget in (
            self.pin_node_button,
            self.approve_node_button,
            self.reject_node_button,
            self.split_boundary_input,
            self.split_event_button,
            self.merge_target_input,
            self.merge_event_button,
            self.move_target_input,
            self.move_event_button,
        ):
            override_form.addRow(widget)
        overrides.hide()
        self.corrections_action.toggled.connect(overrides.setVisible)
        overrides.visibilityChanged.connect(self.corrections_action.setChecked)

    def _install_default_story_map(self) -> None:
        from renpy_story_mapper.ui.graph_canvas import GraphCanvas
        from renpy_story_mapper.ui.presentation_adapter import StoryMapPresenter

        self.graph_canvas = GraphCanvas(self.graph_host)
        self.map_presenter = StoryMapPresenter(
            self.graph_canvas, self.evidence_list, self.diagnostics_list, self
        )
        self.set_graph_widget(self.graph_canvas)
        self.set_presentation_service(self.map_presenter)
        self.accepted_presenter = AcceptedStoryPresenter(
            self.graph_canvas,
            self.navigator,
            self.inspector,
            self.center_stack,
            self.evidence_timeline,
            self,
            canvas_page=self.graph_host,
        )
        self.organization_controller = OrganizationUiController(parent=self)

        self.back_button = QPushButton("Back", self)
        self.back_button.setObjectName("mapBackButton")
        self.level_one_button = QPushButton("Level 1", self)
        self.level_one_button.setObjectName("levelOneButton")
        self.level_two_button = QPushButton("Level 2", self)
        self.level_two_button.setObjectName("levelTwoButton")
        self.level_three_button = QPushButton("Level 3", self)
        self.level_three_button.setObjectName("levelThreeButton")
        self.fit_button = QPushButton("Fit", self)
        self.fit_button.setObjectName("fitStoryButton")
        for button in (
            self.back_button,
            self.level_one_button,
            self.level_two_button,
            self.level_three_button,
            self.fit_button,
        ):
            button.setAccessibleName(button.text())
            self.command_bar.insertWidget(self.command_bar.count() - 4, button)
        self.back_button.clicked.connect(self._go_back)
        self.level_one_button.clicked.connect(self._show_level_one)
        self.level_two_button.clicked.connect(self._show_level_two)
        self.level_three_button.clicked.connect(self._show_level_three)
        self.fit_button.clicked.connect(self.graph_canvas.fit_all)
        self.search_input.returnPressed.connect(self._search_story)
        self.technical_filter.toggled.connect(self._toggle_technical_view)
        self.unresolved_filter.toggled.connect(
            lambda visible: self.graph_canvas.set_kind_visible("unresolved", visible)
        )
        self.graph_canvas.set_kind_visible("unresolved", False)
        self.variable_filter_input.textChanged.connect(
            lambda value: self.graph_canvas.set_variable_filter(
                (value.strip(),) if value.strip() else ()
            )
        )
        self.category_filter_input.textChanged.connect(
            lambda value: self.graph_canvas.set_category_filter(
                (value.strip(),) if value.strip() else ()
            )
        )
        self.rename_node_button.clicked.connect(
            lambda: self.map_presenter.rename_selected(self.node_name_input.text())
        )
        self.reset_node_name_button.clicked.connect(self.map_presenter.reset_selected_name)
        self.hide_node_button.clicked.connect(self.map_presenter.hide_selected)
        self.update_state_button.clicked.connect(
            lambda: self.map_presenter.update_state_variable(
                self.state_variable_input.text(),
                self.state_display_input.text(),
                self.state_category_input.text(),
            )
        )
        self.map_presenter.status_changed.connect(self.status_label.setText)
        self.map_presenter.error_occurred.connect(self._show_presentation_error)
        self.map_presenter.busy_changed.connect(self._presentation_busy_changed)
        self.map_presenter.visible_count_changed.connect(
            lambda count: self.visible_count_status.setText(f"{count} visible")
        )
        self.accepted_presenter.status_changed.connect(self.status_label.setText)
        self.accepted_presenter.error_occurred.connect(self._show_presentation_error)
        self.accepted_presenter.busy_changed.connect(self._presentation_busy_changed)
        self.accepted_presenter.visible_count_changed.connect(
            lambda count: self.visible_count_status.setText(f"{count} visible")
        )
        self.accepted_presenter.provenance_changed.connect(self.provenance_status.setText)
        self.accepted_presenter.level_changed.connect(
            lambda level: self.level_status.setText(f"Level {level}")
        )
        self.accepted_presenter.pending_draft_changed.connect(self._show_review)
        self.accepted_presenter.ready.connect(self._accepted_story_ready)
        self.accepted_presenter.technical_map_requested.connect(self._show_technical_map)
        self.accepted_presenter.accepted_map_requested.connect(self._show_accepted_map)
        self.accepted_presenter.selection_context_changed.connect(
            self._refresh_correction_choices
        )
        self.organization_controller.set_project(self.controller.session)
        self.organization_controller.progress_changed.connect(self._organization_progress)
        self.organization_controller.busy_changed.connect(self._presentation_busy_changed)
        self.organization_controller.busy_changed.connect(self._organization_busy_changed)
        self.organization_controller.error_occurred.connect(self._show_organization_error)
        self.organization_controller.draft_ready.connect(self._draft_ready)
        self.organization_controller.organization_outcome.connect(self._reload_story)

        organize_menu = QMenu(self.organize_button)
        local_action = organize_menu.addAction("Local • LM Studio")
        cloud_action = organize_menu.addAction("Cloud • ChatGPT")
        local_action.triggered.connect(
            lambda: self._organize(OrganizationOptions(mode=CodexMode.CODEX_LMSTUDIO))
        )
        cloud_action.triggered.connect(
            lambda: self._organize(OrganizationOptions(mode=CodexMode.CODEX_CHATGPT))
        )
        self.organize_button.setMenu(organize_menu)
        self.rename_node_button.clicked.disconnect()
        self.rename_node_button.clicked.connect(self._rename_selected)
        self.reset_node_name_button.clicked.disconnect()
        self.reset_node_name_button.clicked.connect(self._reset_selected_name)
        self.hide_node_button.clicked.disconnect()
        self.hide_node_button.clicked.connect(self._hide_selected)
        self.pin_node_button.clicked.connect(self._pin_selected)
        self.approve_node_button.clicked.connect(lambda: self._approve_selected("approved"))
        self.reject_node_button.clicked.connect(lambda: self._approve_selected("rejected"))
        self.split_event_button.clicked.connect(self._split_selected)
        self.merge_event_button.clicked.connect(self._merge_selected)
        self.move_event_button.clicked.connect(self._move_selected)
        self.graph_canvas.selection_changed.connect(self._refresh_correction_choices)
        self.graph_canvas.filters_changed.connect(
            lambda _variables, _categories: self.visible_count_status.setText(
                f"{self.graph_canvas.visible_item_count} visible"
            )
        )

    @Slot(bool)
    def _toggle_technical_view(self, visible: bool) -> None:
        self.map_presenter.set_include_technical(visible)
        if not self.accepted_presenter.active:
            return
        if visible:
            self._show_technical_map()
        else:
            self._show_accepted_map()

    @Slot()
    def _show_technical_map(self) -> None:
        if not self.accepted_presenter.active:
            self.map_presenter.set_render_suppressed(False)
            return
        if not self.technical_filter.isChecked():
            self.technical_filter.blockSignals(True)
            self.technical_filter.setChecked(True)
            self.technical_filter.blockSignals(False)
        self.accepted_presenter.enter_technical_mode()
        self.map_presenter.set_include_technical(True)
        self.map_presenter.show_overview()
        self.map_presenter.set_render_suppressed(False)
        self.breadcrumb_label.setText("Technical map")
        self._refresh_correction_choices(None)

    @Slot()
    def _show_accepted_map(self) -> None:
        if not self.accepted_presenter.active:
            return
        if self.technical_filter.isChecked():
            self.technical_filter.blockSignals(True)
            self.technical_filter.setChecked(False)
            self.technical_filter.blockSignals(False)
        self.map_presenter.set_render_suppressed(True)
        self.map_presenter.set_include_technical(False)
        self.accepted_presenter.enter_accepted_mode()
        self.breadcrumb_label.setText("Accepted overview")
        self._refresh_correction_choices(None)

    @Slot()
    def _go_back(self) -> None:
        if self.accepted_presenter.viewing_accepted:
            self._show_accepted_map()
            self.breadcrumb_label.setText("Overview")
        else:
            self.map_presenter.go_up()

    @Slot()
    def _show_level_one(self) -> None:
        if self.accepted_presenter.viewing_accepted:
            self._show_accepted_map()
        else:
            self.graph_canvas.set_semantic_level(SemanticLevel.OVERVIEW)

    @Slot()
    def _show_level_two(self) -> None:
        if self.accepted_presenter.viewing_accepted and self.accepted_presenter.selected_arc_id:
            self.accepted_presenter.show_arc(self.accepted_presenter.selected_arc_id)
        else:
            self.graph_canvas.set_semantic_level(SemanticLevel.EVENTS)

    @Slot()
    def _show_level_three(self) -> None:
        if self.accepted_presenter.viewing_accepted and self.accepted_presenter.selected_event_id:
            self.accepted_presenter.show_evidence(self.accepted_presenter.selected_event_id)
        else:
            self.graph_canvas.set_semantic_level(SemanticLevel.EVIDENCE)
            self.graph_canvas.request_selected_evidence()

    @Slot()
    def _search_story(self) -> None:
        query = self.search_input.text()
        if self.accepted_presenter.viewing_accepted:
            self.accepted_presenter.search(query)
            return
        self.map_presenter.search(query)

    def _organize(self, options: OrganizationOptions) -> None:
        scopes = (
            self.map_presenter.selected_overview_scope_ids
            if not self.accepted_presenter.viewing_accepted
            else ()
        )
        self._begin_organization(tuple(scopes), options)

    def _begin_organization(
        self, scopes: tuple[str, ...], options: OrganizationOptions
    ) -> None:
        scope_label = "selected scope" if scopes else "full game"
        cloud_confirmed = False
        if options.mode is CodexMode.CODEX_CHATGPT:
            result = QMessageBox.question(
                self,
                "Send story evidence to ChatGPT?",
                f"This run sends {scope_label} story evidence to the cloud organizer. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            cloud_confirmed = result == QMessageBox.StandardButton.Yes
            if not cloud_confirmed:
                return
        self._last_organization_options = options
        self._last_organization_scopes = scopes
        self._clear_recovery()
        self.status_label.setText(f"Organizing {scope_label}")
        self.organization_controller.organize(scopes, options, cloud_confirmed=cloud_confirmed)

    @Slot(int, str)
    def _organization_progress(self, percent: int, status: str) -> None:
        self.progress_bar.setValue(percent)
        self._organization_status = status
        self._update_elapsed_status()

    @Slot(bool)
    def _organization_busy_changed(self, busy: bool) -> None:
        if busy:
            self._organization_started_at = time.perf_counter()
            self._elapsed_timer.start()
        else:
            self._elapsed_timer.stop()
            self._organization_started_at = None

    @Slot()
    def _update_elapsed_status(self) -> None:
        started = self._organization_started_at
        if started is None:
            if self._organization_status:
                self.status_label.setText(self._organization_status)
            return
        elapsed = time.perf_counter() - started
        self.status_label.setText(f"{self._organization_status}  •  {elapsed:.1f}s")

    @Slot()
    def _retry_organization(self) -> None:
        options = self._last_organization_options
        if options is not None:
            self._begin_organization(self._last_organization_scopes, options)

    @Slot(str, object)
    def _draft_ready(self, _draft_id: str, _result: object) -> None:
        self.status_label.setText("Draft ready for review")
        self.accepted_presenter.set_project(self.controller.session)

    @Slot()
    def _accepted_story_ready(self) -> None:
        suppress = getattr(self.map_presenter, "set_render_suppressed", None)
        if callable(suppress):
            suppress(self.accepted_presenter.active and not self.technical_filter.isChecked())
        if self.accepted_presenter.active and self.technical_filter.isChecked():
            self._show_technical_map()
        else:
            self._restore_story_navigation()
        self._clear_recovery()

    @Slot(object, object, object)
    def _show_review(self, draft: object, run: object, snapshot: object) -> None:
        from renpy_story_mapper.story_organization import OrganizationDraft, OrganizationRun
        from renpy_story_mapper.ui.story_explorer import StorySnapshot

        if not isinstance(draft, OrganizationDraft) or not isinstance(snapshot, StorySnapshot):
            return
        run_value = run if isinstance(run, OrganizationRun) else None
        dialog = DraftReviewDialog(
            draft,
            run_value,
            snapshot.arcs,
            snapshot.events,
            snapshot.draft_reviews,
            self,
        )
        self._review_dialog = dialog
        dialog.review_requested.connect(
            lambda kind, identifier, decision: self.organization_controller.review_group(
                draft.id, kind, identifier, decision
            )
        )
        self.organization_controller.review_saved.connect(dialog.confirm_review)
        dialog.apply_requested.connect(self.organization_controller.apply_draft)
        dialog.discard_requested.connect(self.organization_controller.discard_draft)
        self.organization_controller.organization_changed.connect(dialog.accept)
        dialog.show()

    @Slot(str)
    def _reload_story(self, outcome: str) -> None:
        if self._current_project_path is not None and outcome in {"applied", "edited"}:
            self._settings.setValue(
                f"recent/{self._current_project_path}/organization", "Accepted AI"
            )
            self._refresh_recent_projects()
        self.accepted_presenter.set_project(self.controller.session)

    def _accepted_target(self) -> tuple[Literal["arc", "event"], str] | None:
        value = self.accepted_presenter.selected_target
        if not self.accepted_presenter.active or value is None:
            return None
        return cast(tuple[Literal["arc", "event"], str], value)

    @Slot()
    def _rename_selected(self) -> None:
        target = self._accepted_target()
        title = self.node_name_input.text().strip()
        if target is None:
            self.map_presenter.rename_selected(title)
            return
        if title:
            kind, identifier = target
            self.organization_controller.mutate(
                lambda service: service.rename(kind, identifier, title)
            )

    @Slot()
    def _reset_selected_name(self) -> None:
        if self._accepted_target() is None:
            self.map_presenter.reset_selected_name()

    @Slot()
    def _hide_selected(self) -> None:
        target = self._accepted_target()
        if target is None:
            self.map_presenter.hide_selected()
            return
        kind, identifier = target
        hidden = not self.accepted_presenter.selected_hidden
        self.organization_controller.mutate(
            lambda service: service.set_hidden(kind, identifier, hidden)
        )

    @Slot()
    def _pin_selected(self) -> None:
        target = self._accepted_target()
        if target is None:
            return
        kind, identifier = target
        pinned = not self.accepted_presenter.selected_pinned
        self.organization_controller.mutate(
            lambda service: service.set_pinned(kind, identifier, pinned)
        )

    def _approve_selected(self, state: Literal["approved", "rejected"]) -> None:
        target = self._accepted_target()
        if target is None:
            return
        kind, identifier = target
        self.organization_controller.mutate(
            lambda service: service.set_approval(kind, identifier, state)
        )

    @Slot()
    def _split_selected(self) -> None:
        target = self._accepted_target()
        boundary = self.split_boundary_input.currentData()
        title = self.node_name_input.text().strip() or "Split event"
        if target is None or target[0] != "event" or not isinstance(boundary, str):
            return
        self.organization_controller.mutate(
            lambda service: service.split_event(target[1], boundary, new_title=title)
        )

    @Slot()
    def _merge_selected(self) -> None:
        target = self._accepted_target()
        other = self.merge_target_input.currentData()
        title = self.node_name_input.text().strip() or "Merged event"
        if target is None or target[0] != "event" or not isinstance(other, str):
            return
        self.organization_controller.mutate(
            lambda service: service.merge_events(target[1], other, title=title)
        )

    @Slot()
    def _move_selected(self) -> None:
        target = self._accepted_target()
        arc_id = self.move_target_input.currentData()
        if target is None or target[0] != "event" or not isinstance(arc_id, str):
            return
        self.organization_controller.mutate(
            lambda service: service.move_event(target[1], arc_id, 0)
        )

    @Slot(object)
    def _refresh_correction_choices(self, _selection: object) -> None:
        for combo in (
            self.split_boundary_input,
            self.merge_target_input,
            self.move_target_input,
        ):
            combo.clear()
        target = self._accepted_target()
        if target is None:
            technical_target = (
                not self.accepted_presenter.viewing_accepted
                and self.graph_canvas.selected_node_id is not None
            )
            self.rename_node_button.setEnabled(technical_target)
            self.reset_node_name_button.setEnabled(technical_target)
            self.reset_node_name_button.setToolTip("Reset the deterministic presentation name")
            self.hide_node_button.setEnabled(technical_target)
            self.hide_node_button.setText("Hide selected")
            self.pin_node_button.setText("Pin selected")
            self.pin_node_button.setEnabled(False)
            self.approve_node_button.setText("Approve")
            self.approve_node_button.setEnabled(False)
            self.reject_node_button.setText("Reject")
            self.reject_node_button.setEnabled(False)
            self.split_event_button.setEnabled(False)
            self.merge_event_button.setEnabled(False)
            self.move_event_button.setEnabled(False)
            return
        self.rename_node_button.setEnabled(True)
        self.reset_node_name_button.setEnabled(False)
        self.reset_node_name_button.setToolTip(
            "Accepted AI titles can be renamed; their original title is not overwritten by Reset."
        )
        hidden = self.accepted_presenter.selected_hidden
        self.hide_node_button.setText("Unhide selected" if hidden else "Hide selected")
        self.hide_node_button.setEnabled(True)
        pinned = self.accepted_presenter.selected_pinned
        self.pin_node_button.setText("Unpin selected" if pinned else "Pin selected")
        self.pin_node_button.setEnabled(True)
        approval = self.accepted_presenter.selected_approval_state
        self.approve_node_button.setText("Approved" if approval == "approved" else "Approve")
        self.approve_node_button.setEnabled(approval != "approved")
        self.reject_node_button.setText("Rejected" if approval == "rejected" else "Reject")
        self.reject_node_button.setEnabled(approval != "rejected")
        boundaries, siblings, arcs = self.accepted_presenter.correction_choices()
        for identifier, label in boundaries:
            self.split_boundary_input.addItem(label, identifier)
        for identifier, label in siblings:
            self.merge_target_input.addItem(label, identifier)
        for identifier, label in arcs:
            self.move_target_input.addItem(label, identifier)
        is_event = target[0] == "event" and not hidden
        self.split_event_button.setEnabled(is_event and bool(boundaries))
        self.merge_event_button.setEnabled(is_event and bool(siblings))
        self.move_event_button.setEnabled(is_event and bool(arcs))

    def _connect_controller(self) -> None:
        self.controller.state_changed.connect(self._apply_state)
        self.controller.state_changed.connect(self._complete_pending_close)
        self.controller.status_changed.connect(self.status_label.setText)
        self.controller.progress_changed.connect(self.progress_bar.setValue)
        self.controller.project_changed.connect(self._project_changed)
        self.controller.error_occurred.connect(self._show_error)

    @Slot()
    def _choose_new_project(self) -> None:
        source = QFileDialog.getExistingDirectory(self, "Select game folder")
        if not source:
            return
        self._choose_project_output(source)

    @Slot()
    def _choose_new_archive_project(self) -> None:
        source, _ = QFileDialog.getOpenFileName(
            self, "Select scripts.rpa", "", "Ren'Py archive (*.rpa)"
        )
        if not source:
            return
        self._choose_project_output(source)

    def _choose_project_output(self, source: str) -> None:
        output, _ = QFileDialog.getSaveFileName(
            self, "Create project", "", "Story Mapper project (*.rsmproj)"
        )
        if output:
            self.controller.create_project(source, output)

    @Slot()
    def _choose_existing_project(self) -> None:
        project, _ = QFileDialog.getOpenFileName(
            self, "Open project", "", "Story Mapper project (*.rsmproj)"
        )
        if project:
            self.controller.open_project(project)

    @Slot(str)
    def _apply_state(self, state: str) -> None:
        busy = state == LifecycleState.BUSY.value or self._presentation_busy
        ready = state == LifecycleState.READY.value
        self.select_source_button.setEnabled(not busy)
        self.select_archive_button.setEnabled(not busy)
        self.open_button.setEnabled(not busy)
        self.refresh_button.setEnabled(ready)
        self.close_button.setEnabled(ready)
        self.cancel_button.setEnabled(busy)
        self.search_input.setEnabled(ready)
        self.variable_filter_input.setEnabled(ready)
        self.category_filter_input.setEnabled(ready)
        if hasattr(self, "organize_button"):
            self.organize_button.setEnabled(ready and not busy)
        if hasattr(self, "corrections_action"):
            self.corrections_action.setEnabled(ready and not busy)

    @Slot(bool)
    def _presentation_busy_changed(self, busy: bool) -> None:
        active = [busy]
        for value in (
            self._presentation_service,
            getattr(self, "accepted_presenter", None),
            getattr(self, "organization_controller", None),
        ):
            if value is not None:
                active.append(bool(getattr(value, "is_busy", False)))
        self._presentation_busy = any(active)
        self._apply_state(self.controller.state.value)
        if self._close_when_idle and not self._presentation_busy and not self.controller.is_busy:
            self._close_when_idle = False
            QTimer.singleShot(0, self.close)

    @Slot()
    def _cancel_operations(self) -> None:
        self.controller.cancel()
        cancel = getattr(self._presentation_service, "cancel", None)
        if callable(cancel):
            cancel()
        if hasattr(self, "accepted_presenter"):
            self.accepted_presenter.cancel()
        if hasattr(self, "organization_controller"):
            self.organization_controller.cancel()

    @Slot(str)
    def _complete_pending_close(self, state: str) -> None:
        if (
            self._close_when_idle
            and state != LifecycleState.BUSY.value
            and not self._presentation_busy
        ):
            self._close_when_idle = False
            QTimer.singleShot(0, self.close)

    @Slot(object)
    def _project_changed(self, value: object) -> None:
        self._clear_recovery()
        if self._current_project_path is not None:
            self._save_story_navigation()
        if isinstance(value, ProjectSession):
            self.setWindowTitle(f"{value.project_path.stem} - Ren'Py Story Mapper")
            self.project_name_label.setText(value.project_path.stem)
            self.page_stack.setCurrentWidget(self.workspace_page)
            self._remember_project(value)
            self._current_project_path = str(value.project_path)
        else:
            self.setWindowTitle("Ren'Py Story Mapper")
            self.project_name_label.setText("Story Mapper")
            self.page_stack.setCurrentWidget(self.welcome_page)
            self._current_project_path = None
        session = value if isinstance(value, ProjectSession) else None
        presentation_session = None if self._close_when_idle else session
        if self._presentation_service is not None:
            if hasattr(self, "map_presenter"):
                self.map_presenter.set_include_technical(
                    self.technical_filter.isChecked()
                )
            self._presentation_service.set_project(presentation_session)
        if hasattr(self, "accepted_presenter"):
            self.accepted_presenter.set_project(presentation_session)
        if hasattr(self, "organization_controller"):
            self.organization_controller.set_project(presentation_session)

    @Slot(str)
    def _show_error(self, message: str) -> None:
        self._show_contextual_error(message)
        self._set_recovery("Open Project", self._choose_existing_project)

    @Slot(str)
    def _show_organization_error(self, message: str) -> None:
        self._show_contextual_error(message)
        self._set_recovery("Retry organization", self._retry_organization)

    @Slot(str)
    def _show_presentation_error(self, message: str) -> None:
        self._show_contextual_error(message)
        normalized = message.casefold()
        if "story view" in normalized:
            self._set_recovery("Retry accepted story", self.accepted_presenter.reload)
        elif "search" in normalized:
            self._set_recovery("Retry search", self._search_story)
        elif (
            self.accepted_presenter.viewing_accepted
            and self.accepted_presenter.selected_event_id is not None
        ):
            event_id = self.accepted_presenter.selected_event_id
            self._set_recovery(
                "Retry evidence", lambda: self.accepted_presenter.show_evidence(event_id)
            )
        elif self.accepted_presenter.active:
            self._set_recovery("Open technical map", self._show_technical_map)
        else:
            self._set_recovery("Retry map", self.map_presenter.reload)

    @Slot(str)
    def _show_contextual_error(self, message: str) -> None:
        self.diagnostics_list.addItem(message)
        self.status_label.setText(message)
        self.recovery_button.show()

    def _set_recovery(self, label: str, callback: Callable[[], None]) -> None:
        self._recovery_callback = callback
        self.recovery_button.setText(label)
        self.recovery_button.setAccessibleName(label)
        self.recovery_button.show()

    def _clear_recovery(self) -> None:
        self._recovery_callback = None
        self.recovery_button.hide()

    @Slot()
    def _run_recovery(self) -> None:
        callback = self._recovery_callback
        self._clear_recovery()
        if callback is not None:
            callback()

    def _remember_project(self, session: ProjectSession) -> None:
        path = str(session.project_path)
        raw_value = self._settings.value("recentProjects", [])
        raw = raw_value if isinstance(raw_value, list) else []
        recent = [str(value) for value in raw if str(value) != path]
        recent.insert(0, path)
        self._settings.setValue("recentProjects", recent[:8])
        self._settings.setValue(f"recent/{path}/sourceKind", session.source_kind)
        self._settings.setValue(
            f"recent/{path}/opened", QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm")
        )
        self._refresh_recent_projects()

    def _refresh_recent_projects(self) -> None:
        raw_value = self._settings.value("recentProjects", [])
        raw = raw_value if isinstance(raw_value, list) else []
        values: list[tuple[str, str, str, str]] = []
        for path in (str(value) for value in raw):
            kind = str(self._settings.value(f"recent/{path}/sourceKind", "project"))
            opened = str(self._settings.value(f"recent/{path}/opened", "Previously opened"))
            organization = str(
                self._settings.value(f"recent/{path}/organization", "Deterministic")
            )
            values.append((path, kind, opened, organization))
        self.welcome_page.set_recent_projects(values)

    def _restore_preferences(self) -> None:
        self.variable_filter_input.setText(str(self._settings.value("filter/variable", "")))
        self.category_filter_input.setText(str(self._settings.value("filter/category", "")))
        self.technical_filter.setChecked(
            str(self._settings.value("view/technical", "false")).lower() == "true"
        )
        self.unresolved_filter.setChecked(
            str(self._settings.value("view/unresolved", "false")).lower() == "true"
        )
        self._refresh_recent_projects()

    @Slot()
    def _save_story_navigation(self) -> None:
        path = self._current_project_path
        if path is None or not hasattr(self, "accepted_presenter"):
            return
        scale, center_x, center_y = self.graph_canvas.navigation_state()
        self._settings.setValue(
            f"navigation/{path}/arc", self.accepted_presenter.selected_arc_id or ""
        )
        self._settings.setValue(
            f"navigation/{path}/event", self.accepted_presenter.selected_event_id or ""
        )
        self._settings.setValue(f"navigation/{path}/level", int(self.graph_canvas.semantic_level))
        self._settings.setValue(f"navigation/{path}/scale", scale)
        self._settings.setValue(f"navigation/{path}/centerX", center_x)
        self._settings.setValue(f"navigation/{path}/centerY", center_y)

    @Slot()
    def _restore_story_navigation(self) -> None:
        path = self._current_project_path
        if path is None or not self.accepted_presenter.active:
            return
        arc_id = str(self._settings.value(f"navigation/{path}/arc", ""))
        event_id = str(self._settings.value(f"navigation/{path}/event", ""))
        level = max(
            1,
            min(3, int(str(self._settings.value(f"navigation/{path}/level", 1)))),
        )
        self.accepted_presenter.restore_story_state(arc_id, event_id, level)
        scale = float(str(self._settings.value(f"navigation/{path}/scale", 1.0)))
        center_x = float(str(self._settings.value(f"navigation/{path}/centerX", 0.0)))
        center_y = float(str(self._settings.value(f"navigation/{path}/centerY", 0.0)))
        self.graph_canvas.restore_navigation_state(scale, center_x, center_y)

    def set_application_zoom(self, percent: int) -> None:
        if percent < 100 or percent > 200:
            raise ValueError("Application zoom must be between 100 and 200 percent.")
        font = self.font()
        font.setPixelSize(round(14 * percent / 100))
        self.setFont(font)
        self.setProperty("applicationZoomPercent", percent)
        apply_story_palette(self, dark=bool(self.property("storyPaletteDark")))
        if hasattr(self, "graph_canvas"):
            self.graph_canvas.set_application_zoom(percent)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if bool(self.property("storyPaletteApplying")):
            return
        if event.type() == QEvent.Type.PaletteChange:
            requested = self.property("storyPaletteDark")
            current_dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
            if isinstance(requested, bool) and requested == current_dark:
                return
            apply_story_palette(self, dark=_is_dark_palette())
        elif event.type() == QEvent.Type.ApplicationPaletteChange:
            apply_story_palette(self, dark=_is_dark_palette())

    def closeEvent(self, event: QCloseEvent) -> None:
        presentation_busy = bool(getattr(self._presentation_service, "is_busy", False)) or bool(
            getattr(getattr(self, "accepted_presenter", None), "is_busy", False)
        ) or bool(getattr(getattr(self, "organization_controller", None), "is_busy", False))
        if self.controller.is_busy or presentation_busy:
            self._close_when_idle = True
            self._cancel_operations()
            event.ignore()
            return
        self._settings.setValue("filter/variable", self.variable_filter_input.text())
        self._settings.setValue("filter/category", self.category_filter_input.text())
        self._settings.setValue("view/technical", self.technical_filter.isChecked())
        self._settings.setValue("view/unresolved", self.unresolved_filter.isChecked())
        self._save_story_navigation()
        super().closeEvent(event)


def _is_dark_palette() -> bool:
    color = QGuiApplication.palette().color(QPalette.ColorRole.Window)
    return color.lightness() < 128
