"""GUI entry point for Ren'Py Story Mapper."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from renpy_story_mapper.ui.main_window import MainWindow


def main(argv: Sequence[str] | None = None) -> int:
    application = QApplication(list(argv) if argv is not None else sys.argv)
    application.setApplicationName("Ren'Py Story Mapper")
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
