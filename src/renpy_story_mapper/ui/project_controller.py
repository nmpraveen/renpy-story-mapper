"""Thread-safe project lifecycle controller for the desktop shell."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast

from PySide6.QtCore import QObject, Signal

from renpy_story_mapper.project import (
    IncompatibleProjectVersionError,
    Project,
    ProjectCancelledError,
    ProjectCorruptionError,
    RefreshReport,
    create_archive_project,
    create_project,
    open_project,
    refresh_archive_project,
    refresh_project,
)
from renpy_story_mapper.ui.workers import CancelCheck, ProgressReporter, WorkerTask

PROJECT_SUFFIX = ".rsmproj"


class LifecycleState(StrEnum):
    EMPTY = "empty"
    BUSY = "busy"
    READY = "ready"


@dataclass(frozen=True)
class ProjectSession:
    project_path: Path
    source_path: Path
    source_kind: str
    source_count: int


class ProjectBackend(Protocol):
    def create(
        self, project_path: Path, source_path: Path, cancel_check: CancelCheck
    ) -> ProjectSession: ...

    def open(self, project_path: Path, cancel_check: CancelCheck) -> ProjectSession: ...

    def refresh(self, session: ProjectSession, cancel_check: CancelCheck) -> RefreshReport: ...


class PresentationService(Protocol):
    """Optional adapter installed by the independently owned presentation task."""

    def set_project(self, session: ProjectSession | None) -> None: ...


class LocalProjectBackend:
    """Adapter over M03's safe static lifecycle API."""

    def create(
        self, project_path: Path, source_path: Path, cancel_check: CancelCheck
    ) -> ProjectSession:
        project = (
            create_archive_project(project_path, source_path, cancel_check=cancel_check)
            if source_path.is_file()
            else create_project(project_path, source_path, cancel_check=cancel_check)
        )
        try:
            return _session_from_project(project)
        finally:
            project.close()

    def open(self, project_path: Path, cancel_check: CancelCheck) -> ProjectSession:
        if cancel_check():
            raise ProjectCancelledError("project operation was cancelled")
        project = open_project(project_path)
        try:
            if cancel_check():
                raise ProjectCancelledError("project operation was cancelled")
            return _session_from_project(project)
        finally:
            project.close()

    def refresh(self, session: ProjectSession, cancel_check: CancelCheck) -> RefreshReport:
        if session.source_kind == "archive":
            return refresh_archive_project(
                session.project_path, session.source_path, cancel_check=cancel_check
            )
        return refresh_project(session.project_path, session.source_path, cancel_check=cancel_check)


class ProjectController(QObject):
    """Own lifecycle state while all storage and analysis happens off the UI thread."""

    state_changed = Signal(str)
    status_changed = Signal(str)
    progress_changed = Signal(int)
    project_changed = Signal(object)
    error_occurred = Signal(str)

    def __init__(
        self, backend: ProjectBackend | None = None, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._backend = backend or LocalProjectBackend()
        self._session: ProjectSession | None = None
        self._task: WorkerTask | None = None
        self._state = LifecycleState.EMPTY

    @property
    def state(self) -> LifecycleState:
        return self._state

    @property
    def session(self) -> ProjectSession | None:
        return self._session

    @property
    def is_busy(self) -> bool:
        return self._task is not None

    def create_project(
        self, source: str | os.PathLike[str], output: str | os.PathLike[str]
    ) -> bool:
        try:
            source_path, project_path = validate_create_paths(source, output)
        except ValueError as exc:
            self.error_occurred.emit(str(exc))
            return False

        def operation(cancelled: CancelCheck, progress: ProgressReporter) -> object:
            progress(5, "Validating")
            result = self._backend.create(project_path, source_path, cancelled)
            progress(100, "Ready")
            return result

        return self._start(operation, "Creating project", self._accept_session)

    def open_project(self, project: str | os.PathLike[str]) -> bool:
        try:
            project_path = validate_project_path(project, must_exist=True)
        except ValueError as exc:
            self.error_occurred.emit(str(exc))
            return False

        def operation(cancelled: CancelCheck, progress: ProgressReporter) -> object:
            progress(10, "Opening project")
            result = self._backend.open(project_path, cancelled)
            progress(100, "Ready")
            return result

        return self._start(operation, "Opening project", self._accept_session)

    def refresh_project(self) -> bool:
        session = self._session
        if session is None:
            self.error_occurred.emit("Open a project first.")
            return False

        def operation(cancelled: CancelCheck, progress: ProgressReporter) -> object:
            progress(5, "Refreshing project")
            result = self._backend.refresh(session, cancelled)
            progress(100, "Ready")
            return result

        return self._start(operation, "Refreshing project", self._accept_refresh)

    def cancel(self) -> None:
        if self._task is not None:
            self.status_changed.emit("Cancelling")
            self._task.cancel()

    def close_project(self) -> bool:
        if self._task is not None:
            self.error_occurred.emit("Cancel the current operation before closing.")
            return False
        self._session = None
        self.project_changed.emit(None)
        self._set_state(LifecycleState.EMPTY)
        self.progress_changed.emit(0)
        self.status_changed.emit("No project open")
        return True

    def _start(
        self,
        operation: Callable[[CancelCheck, ProgressReporter], object],
        status: str,
        accept: Callable[[object], None],
    ) -> bool:
        if self._task is not None:
            self.error_occurred.emit("Another project operation is already running.")
            return False
        task = WorkerTask(operation, self)
        self._task = task
        task.progress.connect(self._on_progress)
        task.succeeded.connect(accept)
        task.failed.connect(self._on_failure)
        task.finished.connect(self._on_finished)
        self._set_state(LifecycleState.BUSY)
        self.status_changed.emit(status)
        self.progress_changed.emit(0)
        task.start()
        return True

    def _accept_session(self, value: object) -> None:
        session = cast(ProjectSession, value)
        self._session = session
        self.project_changed.emit(session)
        self.status_changed.emit("Ready")

    def _accept_refresh(self, value: object) -> None:
        report = cast(RefreshReport, value)
        changed = len(report.parsed_sources)
        self.status_changed.emit("Ready" if changed == 0 else f"Ready - {changed} updated")
        self.project_changed.emit(self._session)

    def _on_progress(self, percent: int, status: str) -> None:
        self.progress_changed.emit(percent)
        self.status_changed.emit(status)

    def _on_failure(self, error: object) -> None:
        exception = cast(BaseException, error)
        if isinstance(exception, ProjectCancelledError):
            self.status_changed.emit("Cancelled")
            return
        self.error_occurred.emit(_safe_error_message(exception))
        self.status_changed.emit("Operation failed")

    def _on_finished(self) -> None:
        task = self._task
        self._task = None
        self._set_state(LifecycleState.READY if self._session is not None else LifecycleState.EMPTY)
        if task is not None:
            task.deleteLater()

    def _set_state(self, state: LifecycleState) -> None:
        self._state = state
        self.state_changed.emit(state.value)


def validate_create_paths(
    source: str | os.PathLike[str], output: str | os.PathLike[str]
) -> tuple[Path, Path]:
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        raise ValueError("The selected game source does not exist.")
    if source_path.is_file() and source_path.suffix.lower() != ".rpa":
        raise ValueError("Select a game folder or an RPA archive.")
    if not source_path.is_dir() and not source_path.is_file():
        raise ValueError("Select a game folder or an RPA archive.")
    project_path = validate_project_path(output, must_exist=False)
    if project_path.exists():
        raise ValueError("The project file already exists.")
    if source_path.is_dir() and _is_within(project_path, source_path):
        raise ValueError("Store the project outside the selected game folder.")
    if source_path.is_file() and project_path.parent == source_path.parent:
        raise ValueError("Store the project outside the archive folder.")
    return source_path, project_path


def validate_project_path(value: str | os.PathLike[str], *, must_exist: bool) -> Path:
    path = Path(value).expanduser()
    if not str(path).strip():
        raise ValueError("Choose a project file.")
    if path.suffix.lower() != PROJECT_SUFFIX:
        raise ValueError(f"Project files must use {PROJECT_SUFFIX}.")
    path = path.resolve()
    if must_exist and not path.is_file():
        raise ValueError("The selected project does not exist.")
    if not must_exist and not path.parent.exists():
        raise ValueError("The project folder does not exist.")
    return path


def _session_from_project(project: Project) -> ProjectSession:
    metadata: Mapping[str, object] = project.metadata()
    source_kind = str(metadata.get("source_kind", ""))
    source_value = (
        metadata.get("source_path")
        if source_kind == "archive"
        else metadata.get("source_root")
    )
    if source_kind not in {"archive", "folder"} or not isinstance(source_value, str):
        raise ProjectCorruptionError("project source metadata is invalid")
    return ProjectSession(project.path, Path(source_value), source_kind, len(project.sources()))


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _safe_error_message(error: BaseException) -> str:
    if isinstance(error, FileExistsError):
        return "The project file already exists."
    if isinstance(error, FileNotFoundError):
        return "A selected source or project file is no longer available."
    if isinstance(error, ProjectCorruptionError):
        return "The project could not be opened safely."
    if isinstance(error, IncompatibleProjectVersionError):
        return "This project was created by an incompatible version."
    if isinstance(error, PermissionError):
        return "Windows denied access to the selected location."
    return "The project operation failed safely."
