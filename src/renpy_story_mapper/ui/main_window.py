"""Minimal main window and extension regions for the Windows story map."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from renpy_story_mapper.ui.project_controller import (
    LifecycleState,
    PresentationService,
    ProjectController,
    ProjectSession,
)


class MainWindow(QMainWindow):
    """Project lifecycle shell with stable hooks for independently owned M04 widgets."""

    def __init__(
        self,
        controller: ProjectController | None = None,
        presentation_service: PresentationService | None = None,
    ) -> None:
        super().__init__()
        self.controller = controller or ProjectController(parent=self)
        self._presentation_service = presentation_service
        self._close_when_idle = False
        self.setWindowTitle("Ren'Py Story Mapper")
        self.resize(1280, 800)
        self._build_toolbar()
        self._build_center()
        self._build_docks()
        self._connect_controller()
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
        self.cancel_button.clicked.connect(self.controller.cancel)

    def _build_center(self) -> None:
        center = QWidget(self)
        layout = QVBoxLayout(center)
        filters = QHBoxLayout()
        self.search_input = QLineEdit(center)
        self.search_input.setObjectName("storySearch")
        self.search_input.setPlaceholderText("Search")
        self.technical_filter = QCheckBox("Technical", center)
        self.technical_filter.setObjectName("technicalFilter")
        self.unresolved_filter = QCheckBox("Unresolved", center)
        self.unresolved_filter.setObjectName("unresolvedFilter")
        filters.addWidget(self.search_input, 1)
        filters.addWidget(self.technical_filter)
        filters.addWidget(self.unresolved_filter)
        layout.addLayout(filters)

        self.graph_host = QWidget(center)
        self.graph_host.setObjectName("graphHost")
        self.graph_layout = QVBoxLayout(self.graph_host)
        graph_placeholder = QLabel("Story map", self.graph_host)
        graph_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.graph_layout.addWidget(graph_placeholder)
        splitter = QSplitter(Qt.Orientation.Horizontal, center)
        splitter.addWidget(self.graph_host)
        self.evidence_list = QListWidget(splitter)
        self.evidence_list.setObjectName("sourceEvidenceInspector")
        splitter.addWidget(self.evidence_list)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        status = QHBoxLayout()
        self.status_label = QLabel("No project open", center)
        self.status_label.setObjectName("projectStatus")
        self.progress_bar = QProgressBar(center)
        self.progress_bar.setObjectName("projectProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        status.addWidget(self.status_label, 1)
        status.addWidget(self.progress_bar)
        layout.addLayout(status)
        self.setCentralWidget(center)

    def _build_docks(self) -> None:
        diagnostics = QDockWidget("Diagnostics", self)
        diagnostics.setObjectName("diagnosticsDock")
        self.diagnostics_list = QListWidget(diagnostics)
        self.diagnostics_list.setObjectName("diagnosticsLog")
        diagnostics.setWidget(self.diagnostics_list)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, diagnostics)

        overrides = QDockWidget("Overrides", self)
        overrides.setObjectName("overridesDock")
        self.overrides_host = QWidget(overrides)
        self.overrides_host.setObjectName("userOverridesHost")
        overrides.setWidget(self.overrides_host)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, overrides)

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
        busy = state == LifecycleState.BUSY.value
        ready = state == LifecycleState.READY.value
        self.select_source_button.setEnabled(not busy)
        self.select_archive_button.setEnabled(not busy)
        self.open_button.setEnabled(not busy)
        self.refresh_button.setEnabled(ready)
        self.close_button.setEnabled(ready)
        self.cancel_button.setEnabled(busy)
        self.search_input.setEnabled(ready)

    @Slot(str)
    def _complete_pending_close(self, state: str) -> None:
        if self._close_when_idle and state != LifecycleState.BUSY.value:
            self._close_when_idle = False
            QTimer.singleShot(0, self.close)

    @Slot(object)
    def _project_changed(self, value: object) -> None:
        if isinstance(value, ProjectSession):
            self.setWindowTitle(f"{value.project_path.stem} - Ren'Py Story Mapper")
        else:
            self.setWindowTitle("Ren'Py Story Mapper")
        if self._presentation_service is not None:
            self._presentation_service.set_project(
                value if isinstance(value, ProjectSession) else None
            )

    @Slot(str)
    def _show_error(self, message: str) -> None:
        self.diagnostics_list.addItem(message)
        QMessageBox.warning(self, "Ren'Py Story Mapper", message)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.controller.is_busy:
            self._close_when_idle = True
            self.controller.cancel()
            event.ignore()
            return
        super().closeEvent(event)
