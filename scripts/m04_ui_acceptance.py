"""Exercise the real M04 Qt integration against an indexed project on Windows."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Callable
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from renpy_story_mapper.ui.graph_canvas import GraphNodeSpec, SemanticLevel
from renpy_story_mapper.ui.main_window import MainWindow


def _wait(application: QApplication, predicate: Callable[[], bool], timeout: float = 30.0) -> None:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        application.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise TimeoutError("Windows UI acceptance condition timed out")


def _nodes(window: MainWindow) -> list[GraphNodeSpec]:
    return [
        item.spec
        for item in window.graph_canvas.scene().items()
        if hasattr(item, "spec") and isinstance(item.spec, GraphNodeSpec)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    project_path = args.project.resolve()
    if not project_path.is_file():
        parser.error(f"project does not exist: {project_path}")

    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    started = time.perf_counter()
    assert window.controller.open_project(project_path)
    _wait(
        application,
        lambda: not window.controller.is_busy
        and not window.map_presenter.is_busy
        and bool(_nodes(window)),
    )
    open_seconds = time.perf_counter() - started
    overview = _nodes(window)
    assert window.graph_canvas.semantic_level is SemanticLevel.OVERVIEW
    assert 0 < len(overview) <= 80
    overview_rendered_items = window.graph_canvas.rendered_item_count

    search_started = time.perf_counter()
    window.search_input.setText("new_prologue")
    window.search_input.returnPressed.emit()
    _wait(
        application,
        lambda: not window.map_presenter.is_busy
        and {node.title for node in _nodes(window)} == {"new_prologue"},
    )
    search_seconds = time.perf_counter() - search_started
    prologue = _nodes(window)[0]
    assert prologue.expandable
    assert window.graph_canvas.selected_node_id == prologue.id

    window.level_two_button.click()
    _wait(
        application,
        lambda: not window.map_presenter.is_busy
        and window.graph_canvas.semantic_level is SemanticLevel.EVENTS
        and len(_nodes(window)) == 49,
    )
    events = _nodes(window)
    choice = next(node for node in events if node.kind == "choice")
    assert choice.requirements and choice.effects
    assert window.graph_canvas.focus_search_result(choice.id)

    window.level_three_button.click()
    _wait(
        application,
        lambda: not window.map_presenter.is_busy
        and window.graph_canvas.semantic_level is SemanticLevel.EVIDENCE
        and 0 < len(_nodes(window)) <= 4,
    )
    evidence_nodes = _nodes(window)
    assert window.graph_canvas.focus_search_result(evidence_nodes[0].id)
    _wait(
        application,
        lambda: not window.map_presenter.is_busy and window.evidence_list.count() > 0,
    )
    assert ":" in window.evidence_list.item(0).text()

    result = {
        "project_path": str(project_path),
        "open_to_overview_seconds": round(open_seconds, 3),
        "overview_nodes": len(overview),
        "overview_rendered_items": overview_rendered_items,
        "off_page_search_seconds": round(search_seconds, 3),
        "focused_title": prologue.title,
        "event_nodes": len(events),
        "choice_requirements": len(choice.requirements),
        "choice_effects": len(choice.effects),
        "evidence_nodes": len(evidence_nodes),
        "evidence_rendered_items": window.graph_canvas.rendered_item_count,
        "evidence_records": window.evidence_list.count(),
        "status": window.status_label.text(),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    window.controller.close_project()
    window.close()
    application.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
