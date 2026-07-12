"""Windows launcher for the secure local browser interface."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QFileDialog

from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.server import LocalWebServer, start_in_thread


class QtDialogAdapter(QObject):
    """Marshal narrow native file/folder selections onto the Qt UI thread."""

    _requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._result: Path | None = None
        self._requested.connect(self._choose, Qt.ConnectionType.BlockingQueuedConnection)

    def choose_source(self, kind: str) -> Path | None:
        return self._request(kind)

    def choose_open_project(self) -> Path | None:
        return self._request("project_open")

    def choose_save_project(self) -> Path | None:
        return self._request("project_save")

    def _request(self, kind: str) -> Path | None:
        self._result = None
        self._requested.emit(kind)
        return self._result

    @Slot(str)
    def _choose(self, kind: str) -> None:
        if kind == "folder":
            path = QFileDialog.getExistingDirectory(None, "Open Game Folder")
        elif kind in {"archive", "source"}:
            path, _ = QFileDialog.getOpenFileName(
                None, "Open Ren'Py Source", "", "Ren'Py sources (*.rpy *.rpyc *.rpa)"
            )
        elif kind == "project_open":
            path, _ = QFileDialog.getOpenFileName(
                None, "Open Project", "", "Story Mapper projects (*.rsmproj)"
            )
        else:
            path, _ = QFileDialog.getSaveFileName(
                None, "Create Project", "", "Story Mapper projects (*.rsmproj)"
            )
            if path and not path.lower().endswith(".rsmproj"):
                path += ".rsmproj"
        self._result = Path(path) if path else None


class QtShutdownBridge(QObject):
    """Move a loopback shutdown request safely onto the Qt application thread."""

    requested = Signal()

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.requested.connect(app.quit, Qt.ConnectionType.QueuedConnection)

    def request(self) -> None:
        self.requested.emit()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch the private local Story Mapper interface.")
    parser.add_argument("--no-browser", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    instance = QApplication.instance()
    app = instance if isinstance(instance, QApplication) else QApplication(sys.argv[:1])
    dialogs = QtDialogAdapter()
    shutdown_bridge = QtShutdownBridge(app)
    api = ProjectApi(dialogs)
    server = LocalWebServer(
        "127.0.0.1", 0, api, shutdown_callback=shutdown_bridge.request
    )
    thread = start_in_thread(server)
    url = f"http://127.0.0.1:{server.port}/"
    if not args.no_browser:
        webbrowser.open(url, new=1, autoraise=True)

    def shutdown() -> None:
        server.close_service()
        thread.join(timeout=5)

    app.aboutToQuit.connect(shutdown)
    try:
        return app.exec()
    finally:
        if thread.is_alive():
            shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
