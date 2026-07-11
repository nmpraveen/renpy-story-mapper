from __future__ import annotations

import os
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QLabel
from pytestqt.qtbot import QtBot

from renpy_story_mapper.project import Project, ProjectCancelledError, RefreshReport, create_project
from renpy_story_mapper.ui.main_window import MainWindow
from renpy_story_mapper.ui.project_controller import (
    LifecycleState,
    LocalProjectBackend,
    ProjectController,
    ProjectSession,
    validate_create_paths,
    validate_project_path,
)

FIXTURE = Path(__file__).parent / "fixtures" / "m04" / "ui"


class FakeBackend:
    def __init__(self) -> None:
        self.thread_ids: list[int] = []
        self.refresh_started = threading.Event()

    def create(
        self, project_path: Path, source_path: Path, cancel_check: object
    ) -> ProjectSession:
        del cancel_check
        self.thread_ids.append(threading.get_ident())
        return ProjectSession(project_path, source_path, "folder", 1)

    def open(self, project_path: Path, cancel_check: object) -> ProjectSession:
        del cancel_check
        self.thread_ids.append(threading.get_ident())
        return ProjectSession(project_path, project_path.parent / "game", "folder", 1)

    def refresh(self, session: ProjectSession, cancel_check: object) -> RefreshReport:
        self.thread_ids.append(threading.get_ident())
        self.refresh_started.set()
        check = cast(Callable[[], bool], cancel_check)
        while not check():
            time.sleep(0.005)
        raise ProjectCancelledError("cancelled")


class FailingBackend(FakeBackend):
    def open(self, project_path: Path, cancel_check: object) -> ProjectSession:
        del project_path, cancel_check
        raise RuntimeError("secret fixture dialogue must not escape")


class PresentationRecorder:
    def __init__(self) -> None:
        self.sessions: list[ProjectSession | None] = []

    def set_project(self, session: ProjectSession | None) -> None:
        self.sessions.append(session)


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    destination = tmp_path / "game"
    shutil.copytree(FIXTURE, destination)
    return destination


def wait_idle(qtbot: QtBot, controller: ProjectController) -> None:
    qtbot.waitUntil(lambda: not controller.is_busy, timeout=5000)


def test_create_runs_off_ui_thread_and_reaches_ready(
    qtbot: QtBot, source_tree: Path, tmp_path: Path
) -> None:
    backend = FakeBackend()
    controller = ProjectController(backend)
    statuses: list[str] = []
    controller.status_changed.connect(statuses.append)

    assert controller.create_project(source_tree, tmp_path / "story.rsmproj")
    assert controller.state is LifecycleState.BUSY
    wait_idle(qtbot, controller)

    assert controller.state is LifecycleState.READY
    assert controller.session is not None
    assert backend.thread_ids == [backend.thread_ids[0]]
    assert backend.thread_ids[0] != threading.get_ident()
    assert "Ready" in statuses


def test_refresh_cancellation_preserves_current_session(
    qtbot: QtBot, source_tree: Path, tmp_path: Path
) -> None:
    backend = FakeBackend()
    controller = ProjectController(backend)
    assert controller.create_project(source_tree, tmp_path / "story.rsmproj")
    wait_idle(qtbot, controller)
    original = controller.session

    assert controller.refresh_project()
    qtbot.waitUntil(backend.refresh_started.is_set, timeout=2000)
    controller.cancel()
    wait_idle(qtbot, controller)

    assert controller.state is LifecycleState.READY
    assert controller.session == original


def test_failure_is_sanitized_and_recovers_to_empty(qtbot: QtBot, tmp_path: Path) -> None:
    project_path = tmp_path / "existing.rsmproj"
    project_path.write_bytes(b"placeholder")
    controller = ProjectController(FailingBackend())
    errors: list[str] = []
    controller.error_occurred.connect(errors.append)

    assert controller.open_project(project_path)
    wait_idle(qtbot, controller)

    assert errors == ["The project operation failed safely."]
    assert "secret" not in errors[0]
    assert controller.state is LifecycleState.EMPTY


def test_source_and_output_validation_is_read_only(source_tree: Path, tmp_path: Path) -> None:
    source_file = source_tree / "story.rpy"
    before = (source_file.read_bytes(), source_file.stat().st_mtime_ns)
    with pytest.raises(ValueError, match="outside the selected game folder"):
        validate_create_paths(source_tree, source_tree / "map.rsmproj")

    archive = tmp_path / "scripts.rpa"
    archive.write_bytes(b"fixture only")
    with pytest.raises(ValueError, match="outside the archive folder"):
        validate_create_paths(archive, tmp_path / "map.rsmproj")
    with pytest.raises(ValueError, match="RPA archive"):
        validate_create_paths(source_file, tmp_path / "map.rsmproj")
    assert before == (source_file.read_bytes(), source_file.stat().st_mtime_ns)


def test_project_path_requires_extension_and_existing_parent(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\.rsmproj"):
        validate_project_path(tmp_path / "story.sqlite", must_exist=False)
    with pytest.raises(ValueError, match="folder does not exist"):
        validate_project_path(tmp_path / "missing" / "story.rsmproj", must_exist=False)


def test_real_create_open_never_uses_snapshot(
    monkeypatch: pytest.MonkeyPatch, source_tree: Path, tmp_path: Path
) -> None:
    project_path = tmp_path / "story.rsmproj"
    project = create_project(project_path, source_tree)
    project.close()

    def reject_snapshot(_project: Project) -> object:
        raise AssertionError("UI open must remain lightweight")

    monkeypatch.setattr(Project, "snapshot", reject_snapshot)
    backend = LocalProjectBackend()
    session = backend.open(project_path, lambda: False)
    assert session.source_count == 1
    assert session.source_path == source_tree.resolve()


def test_main_window_exposes_shell_regions_and_replaceable_hooks(
    qtbot: QtBot, source_tree: Path, tmp_path: Path
) -> None:
    controller = ProjectController(FakeBackend())
    presentation = PresentationRecorder()
    window = MainWindow(controller, presentation)
    qtbot.addWidget(window)

    for object_name in (
        "graphHost",
        "storySearch",
        "sourceEvidenceInspector",
        "diagnosticsDock",
        "userOverridesHost",
    ):
        assert window.findChild(object, object_name) is not None
    replacement = QLabel("Graph implementation")
    window.set_graph_widget(replacement)
    assert window.findChild(QLabel, "graphCanvas") is replacement

    assert controller.create_project(source_tree, tmp_path / "story.rsmproj")
    wait_idle(qtbot, controller)
    assert presentation.sessions[-1] == controller.session
    assert window.refresh_button.isEnabled()
    assert controller.close_project()
    assert presentation.sessions[-1] is None
    assert not window.refresh_button.isEnabled()


def test_worker_uses_qthread_not_application_thread(
    qtbot: QtBot, source_tree: Path, tmp_path: Path
) -> None:
    backend = FakeBackend()
    controller = ProjectController(backend)
    application = QApplication.instance()
    assert application is not None
    assert QThread.currentThread() is application.thread()
    assert controller.create_project(source_tree, tmp_path / "story.rsmproj")
    wait_idle(qtbot, controller)
    assert backend.thread_ids[0] != threading.get_ident()


def test_window_close_waits_for_background_cancellation(
    qtbot: QtBot, source_tree: Path, tmp_path: Path
) -> None:
    backend = FakeBackend()
    controller = ProjectController(backend)
    window = MainWindow(controller)
    qtbot.addWidget(window)
    window.show()
    assert controller.create_project(source_tree, tmp_path / "story.rsmproj")
    wait_idle(qtbot, controller)
    assert controller.refresh_project()
    qtbot.waitUntil(backend.refresh_started.is_set, timeout=2000)

    assert not window.close()
    assert window.isVisible()
    qtbot.waitUntil(lambda: not controller.is_busy, timeout=5000)
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=5000)
