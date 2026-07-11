"""Capture deterministic M05 Windows UI states for an explicitly supplied project.

The harness never discovers or opens a game/archive path.  Its caller must provide an existing
``.rsmproj`` file and an output directory outside the game source.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from renpy_story_mapper.ui.main_window import MainWindow


def _wait(application: QApplication, predicate: object, timeout: float = 30.0) -> None:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        application.processEvents()
        if callable(predicate) and predicate():
            return
        QTest.qWait(20)
    raise TimeoutError("The M05 UI did not reach the requested state in time.")


def _capture(widget: QWidget, path: Path) -> dict[str, object]:
    widget.repaint()
    QApplication.processEvents()
    image = widget.grab()
    if not image.save(str(path), "PNG"):
        raise OSError(f"Could not save UI screenshot: {path}")
    return {"path": str(path), "width": image.width(), "height": image.height()}


def run(project: Path, output: Path) -> dict[str, object]:
    project = project.resolve()
    output = output.resolve()
    if not project.is_file() or project.suffix.casefold() != ".rsmproj":
        raise ValueError("--project must be an existing .rsmproj file")
    output.mkdir(parents=True, exist_ok=True)
    application = QApplication.instance() or QApplication(sys.argv[:1])
    window = MainWindow()
    window.resize(1440, 900)
    window.show()
    _wait(application, lambda: window.isVisible())
    captures: dict[str, object] = {
        "welcome": _capture(window, output / "welcome.png")
    }
    provider_requests_before = window.organization_controller.organize_requests

    if not window.controller.open_project(project):
        raise RuntimeError("The explicit project could not be queued for opening.")
    _wait(
        application,
        lambda: (
            window.controller.session is not None
            and not window.controller.is_busy
            and not window.map_presenter.is_busy
            and not window.accepted_presenter.is_busy
        ),
        timeout=60.0,
    )
    captures["arc_overview"] = _capture(window, output / "arc-overview.png")

    snapshot = window.accepted_presenter._snapshot
    if snapshot is not None and snapshot.arcs:
        arc = snapshot.arcs[0]
        window.accepted_presenter.show_arc(arc.id)
        _wait(application, lambda: window.graph_canvas.rendered_node_ids != ())
        captures["event_branch"] = _capture(window, output / "event-branch.png")
        if arc.event_ids:
            window.accepted_presenter.show_evidence(arc.event_ids[0])
            _wait(application, lambda: not window.accepted_presenter.is_busy)
            captures["exact_evidence"] = _capture(
                window, output / "exact-evidence.png"
            )
    if window._review_dialog is None:
        raise AssertionError(
            "The supplied synthetic project must contain a pending draft for AI review capture."
        )
    _wait(application, lambda: window._review_dialog is not None)
    captures["ai_review"] = _capture(window._review_dialog, output / "ai-review.png")

    required = {"welcome", "arc_overview", "event_branch", "ai_review", "exact_evidence"}
    missing = required - set(captures)
    if missing:
        raise AssertionError(f"Required M05 screenshot states are missing: {sorted(missing)!r}")
    if window.graph_canvas.rendered_item_count > 240:
        raise AssertionError("The M05 rendered-item safety cap was exceeded.")
    provider_requests_after = window.organization_controller.organize_requests
    if provider_requests_after != provider_requests_before:
        raise AssertionError("Opening and navigating an accepted project invoked a provider.")

    results = {
        "project": str(project),
        "output": str(output),
        "captures": captures,
        "rendered_items": getattr(window.graph_canvas, "rendered_item_count", 0),
        "semantic_level": int(window.graph_canvas.semantic_level),
        "provider_invoked_on_open": provider_requests_after != provider_requests_before,
    }
    (output / "ui-acceptance.json").write_text(
        json.dumps(results, indent=2, sort_keys=True), encoding="utf-8"
    )
    window.close()
    application.processEvents()
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.project, arguments.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
