"""Narrow native Windows picker boundary for the local browser product."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QFileDialog

_SOURCE_KINDS = frozenset({"folder", "archive", "source"})
_PICKER_KINDS = _SOURCE_KINDS | {"project_open", "project_save"}


class QtDialogAdapter(QObject):
    """Marshal allow-listed native selections onto the Qt UI thread.

    Paths never cross the HTTP boundary. ``ProjectApi`` converts successful selections into
    short-lived opaque identifiers before returning a response to browser JavaScript.
    """

    _requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._result: Path | None = None
        self._requested.connect(self._choose, Qt.ConnectionType.BlockingQueuedConnection)

    def choose_source(self, kind: str) -> Path | None:
        if kind not in _SOURCE_KINDS:
            raise ValueError("unsupported source picker kind")
        return self._request(kind)

    def choose_open_project(self) -> Path | None:
        return self._request("project_open")

    def choose_save_project(self) -> Path | None:
        return self._request("project_save")

    def _request(self, kind: str) -> Path | None:
        if kind not in _PICKER_KINDS:
            raise ValueError("unsupported picker kind")
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
        elif kind == "project_save":
            path, _ = QFileDialog.getSaveFileName(
                None, "Create Project", "", "Story Mapper projects (*.rsmproj)"
            )
            if path and not path.lower().endswith(".rsmproj"):
                path += ".rsmproj"
        else:
            raise ValueError("unsupported picker kind")
        self._result = Path(path) if path else None
