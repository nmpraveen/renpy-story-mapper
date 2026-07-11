from __future__ import annotations

import os
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from renpy_story_mapper.project import Project, create_project
from renpy_story_mapper.ui.graph_canvas import GraphNodeSpec, SemanticLevel
from renpy_story_mapper.ui.main_window import MainWindow

FIXTURE = Path(__file__).parent / "fixtures" / "m04" / "presentation"


def _project(tmp_path: Path) -> Path:
    source = tmp_path / "game"
    shutil.copytree(FIXTURE, source)
    project_path = tmp_path / "story.rsmproj"
    create_project(project_path, source).close()
    return project_path


def _wait_map(qtbot: QtBot, window: MainWindow) -> None:
    qtbot.waitUntil(lambda: not window.map_presenter.is_busy, timeout=5000)


def _nodes(window: MainWindow) -> list[GraphNodeSpec]:
    return [
        item.spec
        for item in window.graph_canvas.scene().items()
        if hasattr(item, "spec") and isinstance(item.spec, GraphNodeSpec)
    ]


def test_default_window_opens_bounded_three_level_map_with_evidence(
    qtbot: QtBot, tmp_path: Path
) -> None:
    project_path = _project(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    assert window.controller.open_project(project_path)
    qtbot.waitUntil(lambda: not window.controller.is_busy, timeout=5000)
    _wait_map(qtbot, window)
    overview = _nodes(window)
    prologue = next(node for node in overview if node.title == "new_prologue")
    assert window.graph_canvas.semantic_level is SemanticLevel.OVERVIEW
    assert len(overview) < window.graph_canvas.max_rendered_items
    assert prologue.expandable

    window.graph_canvas.request_expansion(prologue.id, True)
    qtbot.waitUntil(
        lambda: window.graph_canvas.semantic_level is SemanticLevel.EVENTS
        and not window.map_presenter.is_busy,
        timeout=5000,
    )
    events = _nodes(window)
    assert 1 < len(events) < 80
    assert all(node.semantic_levels == frozenset({SemanticLevel.EVENTS}) for node in events)
    choice = next(node for node in events if node.kind == "choice")
    assert choice.summary.startswith("Choices:")
    assert choice.requirements

    event = events[0]
    window.graph_canvas.request_expansion(event.id, True)
    qtbot.waitUntil(
        lambda: window.graph_canvas.semantic_level is SemanticLevel.EVIDENCE
        and not window.map_presenter.is_busy,
        timeout=5000,
    )
    evidence_nodes = _nodes(window)
    assert 1 <= len(evidence_nodes) <= 4
    assert window.graph_canvas.focus_search_result(evidence_nodes[0].id)
    qtbot.waitUntil(lambda: not window.map_presenter.is_busy, timeout=5000)
    assert window.evidence_list.count() >= 1
    assert "story.rpy:" in window.evidence_list.item(0).text()
    assert window.status_label.text().startswith("Source evidence -")


def test_search_filters_and_durable_overrides_are_wired(
    qtbot: QtBot, tmp_path: Path
) -> None:
    project_path = _project(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.controller.open_project(project_path)
    qtbot.waitUntil(lambda: not window.controller.is_busy, timeout=5000)
    _wait_map(qtbot, window)

    window.search_input.setText("I can help")
    qtbot.keyClick(window.search_input, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: window.graph_canvas.semantic_level is SemanticLevel.EVIDENCE
        and window.graph_canvas.selected_node_id is not None
        and not window.map_presenter.is_busy,
        timeout=5000,
    )
    assert window.evidence_list.count() >= 1

    window.level_one_button.click()
    qtbot.waitUntil(
        lambda: window.graph_canvas.semantic_level is SemanticLevel.OVERVIEW
        and not window.map_presenter.is_busy,
        timeout=5000,
    )
    prologue = next(node for node in _nodes(window) if node.title == "new_prologue")
    assert window.graph_canvas.focus_search_result(prologue.id)
    window.node_name_input.setText("Opening Arc")
    window.rename_node_button.click()
    qtbot.waitUntil(
        lambda: any(node.title == "Opening Arc" for node in _nodes(window))
        and not window.map_presenter.is_busy,
        timeout=5000,
    )

    window.state_variable_input.setText("love")
    window.state_display_input.setText("Affection")
    window.state_category_input.setText("relationship_custom")
    window.update_state_button.click()
    _wait_map(qtbot, window)
    with Project.open(project_path) as project:
        registry = project.payload("state_registry", "authoritative")
        assert isinstance(registry, list)
        love = next(item for item in registry if item["original_name"] == "love")
        assert love["display_name"] == "Affection"
        assert love["category"] == "relationship_custom"

    session = window.controller.session
    assert session is not None
    window.map_presenter.set_project(None)
    window.map_presenter.set_project(session)
    _wait_map(qtbot, window)
    assert any(node.title == "Opening Arc" for node in _nodes(window))

    window.category_filter_input.setText("does_not_exist")
    assert not any(item.isVisible() for item in window.graph_canvas.scene().items())
    window.category_filter_input.clear()


def test_direct_level_three_request_stages_bounded_parent_expansion(
    qtbot: QtBot, tmp_path: Path
) -> None:
    project_path = _project(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.controller.open_project(project_path)
    qtbot.waitUntil(lambda: not window.controller.is_busy, timeout=5000)
    _wait_map(qtbot, window)

    window.level_three_button.click()
    qtbot.waitUntil(
        lambda: window.graph_canvas.semantic_level is SemanticLevel.EVIDENCE
        and bool(_nodes(window))
        and not window.map_presenter.is_busy,
        timeout=5000,
    )
    assert len(_nodes(window)) <= 4
