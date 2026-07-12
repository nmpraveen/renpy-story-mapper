"""Capture deterministic M05 Windows UI states for an explicitly supplied project.

The harness never discovers or opens a game/archive path.  Its caller must provide an existing
``.rsmproj`` file and an output directory outside the game source.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QWidget

from renpy_story_mapper.ui.main_window import MainWindow


def _wait(application: QApplication, predicate: object, timeout: float = 30.0) -> None:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        application.processEvents()
        if callable(predicate) and predicate():
            return
        time.sleep(0.02)
    raise TimeoutError("The M05 UI did not reach the requested state in time.")


def _capture(widget: QWidget, path: Path) -> dict[str, object]:
    widget.repaint()
    QApplication.processEvents()
    image = widget.grab()
    if not image.save(str(path), "PNG"):
        raise OSError(f"Could not save UI screenshot: {path}")
    return {"path": str(path), "width": image.width(), "height": image.height()}


def _file_backed_settings(settings_root: Path) -> QSettings:
    root = settings_root.resolve()
    settings = QSettings(
        str(root / "m05-ui-acceptance.ini"), QSettings.Format.IniFormat
    )
    actual_file = Path(settings.fileName()).resolve()
    if settings.format() != QSettings.Format.IniFormat:
        raise AssertionError("The M05 UI harness settings are not INI-backed.")
    if not actual_file.is_relative_to(root):
        raise AssertionError("The M05 UI harness settings escaped the disposable root.")
    return settings


def _run_ui(
    project: Path,
    output: Path,
    settings_root: Path,
    settings: QSettings,
) -> dict[str, object]:
    project = project.resolve()
    output = output.resolve()
    if not project.is_file() or project.suffix.casefold() != ".rsmproj":
        raise ValueError("--project must be an existing .rsmproj file")
    output.mkdir(parents=True, exist_ok=True)
    application = QApplication.instance() or QApplication(sys.argv[:1])
    settings_file = Path(settings.fileName()).resolve()
    if settings.format() != QSettings.Format.IniFormat:
        raise AssertionError("The supplied M05 UI settings are not INI-backed.")
    if not settings_file.is_relative_to(settings_root):
        raise AssertionError("The supplied M05 UI settings escaped the disposable root.")
    window = MainWindow(settings=settings)
    window.resize(1440, 900)
    window.show()
    _wait(application, lambda: window.isVisible())
    captures: dict[str, object] = {
        "welcome": _capture(window, output / "welcome.png")
    }
    window.set_application_zoom(200)
    application.processEvents()
    welcome_title = window.welcome_page.findChild(QWidget, "welcomeTitle")
    if welcome_title is None or welcome_title.font().pixelSize() < 48:
        raise AssertionError("Welcome typography did not scale to 200%.")
    captures["welcome_zoom_200"] = _capture(
        window, output / "welcome-zoom-200.png"
    )
    window.set_application_zoom(100)
    application.processEvents()
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
    if not window.accepted_presenter.active:
        raise AssertionError("The acceptance project must contain accepted story organization.")
    window._show_accepted_map()
    _wait(
        application,
        lambda: (
            window.graph_canvas.semantic_level.value == 1
            and bool(window.graph_canvas.rendered_node_ids)
        ),
    )
    if window.center_stack.currentWidget() is not window.graph_host:
        raise AssertionError("Accepted overview did not use the semantic map center.")
    captures["arc_overview"] = _capture(window, output / "arc-overview.png")

    snapshot = window.accepted_presenter._snapshot
    evidence_ready = False
    if snapshot is not None and snapshot.arcs:
        arc = next((item for item in snapshot.arcs if not item.hidden), snapshot.arcs[0])
        window.accepted_presenter.show_arc(arc.id)
        _wait(
            application,
            lambda: (
                window.graph_canvas.semantic_level.value == 2
                and bool(window.graph_canvas.rendered_node_ids)
            ),
        )
        captures["event_branch"] = _capture(window, output / "event-branch.png")
        window.set_application_zoom(200)
        application.processEvents()
        card_bounds = [
            item.boundingRect() for item in window.graph_canvas._node_items.values()
        ]
        if not card_bounds or any(
            bounds.width() < 520 or bounds.height() < 316 for bounds in card_bounds
        ):
            raise AssertionError("Graph cards did not scale their geometry safely at 200%.")
        window.graph_canvas.fit_all()
        captures["zoom_200"] = _capture(window, output / "zoom-200.png")
        window.set_application_zoom(100)
        application.processEvents()
        for event_id in arc.event_ids:
            window.accepted_presenter.show_evidence(event_id)
            _wait(application, lambda: not window.accepted_presenter.is_busy)
            if window.evidence_timeline.count() > 0:
                current = window.evidence_timeline.currentItem()
                if current is None or not current.text().strip():
                    raise AssertionError("Exact evidence did not expose a current readable record.")
                evidence_ready = True
                captures["exact_evidence"] = _capture(
                    window, output / "exact-evidence.png"
                )
                break
    if not evidence_ready:
        raise AssertionError("No nonempty exact-evidence state was available for capture.")
    _wait(application, lambda: window._review_dialog is not None)
    if window._review_dialog is None:
        raise AssertionError(
            "The supplied synthetic project must contain a pending draft for AI review capture."
        )
    window._review_dialog.show()
    _wait(
        application,
        lambda: (
            window._review_dialog is not None and window._review_dialog.isVisible()
        ),
    )
    captures["ai_review"] = _capture(window._review_dialog, output / "ai-review.png")

    required = {"welcome", "arc_overview", "event_branch", "ai_review", "exact_evidence"}
    missing = required - set(captures)
    if missing:
        raise AssertionError(f"Required M05 screenshot states are missing: {sorted(missing)!r}")
    if window.graph_canvas.rendered_item_count > 240:
        raise AssertionError("The M05 rendered-item safety cap was exceeded.")
    for name, widget in (
        ("evidence timeline", window.evidence_timeline),
        ("evidence inspector", window.inspector.evidence),
        ("review comparison", window._review_dialog.comparison),
        ("review groups", window._review_dialog.groups),
    ):
        if widget.count() > 240:
            raise AssertionError(f"The {name} exceeded the 240-item safety cap.")
    provider_requests_after = window.organization_controller.organize_requests
    if provider_requests_after != provider_requests_before:
        raise AssertionError("Opening and navigating an accepted project invoked a provider.")
    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        raise OSError("The disposable M05 UI settings could not be synchronized.")

    results = {
        "project": str(project),
        "output": str(output),
        "captures": captures,
        "rendered_items": getattr(window.graph_canvas, "rendered_item_count", 0),
        "semantic_level": int(window.graph_canvas.semantic_level),
        "provider_invoked_on_open": provider_requests_after != provider_requests_before,
        "settings_format": settings.format().name,
        "settings_file": str(settings_file),
        "settings_root": str(settings_root),
        "exact_evidence_current": window.evidence_timeline.currentItem().text(),
    }
    (output / "ui-acceptance.json").write_text(
        json.dumps(results, indent=2, sort_keys=True), encoding="utf-8"
    )
    window.close()
    application.processEvents()
    return results


def run(project: Path, output: Path) -> dict[str, object]:
    """Run with a disposable INI settings namespace, never the user's real preferences."""

    with tempfile.TemporaryDirectory(prefix="rsm-m05-settings-") as temporary:
        settings_root = Path(temporary).resolve()
        settings = _file_backed_settings(settings_root)
        return _run_ui(project, output, settings_root, settings)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.project, arguments.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
