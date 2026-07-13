"""Windows launcher for the secure local browser interface."""

from __future__ import annotations

import argparse
import sys
import webbrowser

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.picker import QtDialogAdapter
from renpy_story_mapper.web.server import LocalWebServer, start_in_thread


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
