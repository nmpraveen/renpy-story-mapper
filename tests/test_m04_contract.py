from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from renpy_story_mapper import storage
from renpy_story_mapper.presentation import (
    EvidenceRecord,
    FactRecord,
    PresentationLevel,
    PresentationRequest,
    PresentationService,
    SearchHit,
    rebuild_presentation_index,
)
from renpy_story_mapper.project import Project, create_project, refresh_project
from renpy_story_mapper.ui.graph_canvas import GraphCanvas, GraphNodeSpec, SemanticLevel
from renpy_story_mapper.ui.main_window import MainWindow

FIXTURE = Path(__file__).parent / "fixtures" / "m04" / "presentation"


def _create_project(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "game"
    shutil.copytree(FIXTURE, source)
    project_path = tmp_path / "story.rsmproj"
    create_project(project_path, source).close()
    return project_path, source


def _nodes(window: MainWindow) -> list[GraphNodeSpec]:
    return [
        item.spec
        for item in window.graph_canvas.scene().items()
        if hasattr(item, "spec") and isinstance(item.spec, GraphNodeSpec)
    ]


def _wait_for_map(qtbot: QtBot, window: MainWindow) -> None:
    qtbot.waitUntil(
        lambda: not window.controller.is_busy and not window.map_presenter.is_busy,
        timeout=5000,
    )


def test_default_gui_wiring_uses_bounded_three_level_queries_without_snapshot(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_path, _ = _create_project(tmp_path)

    def reject_snapshot(_project: Project) -> object:
        raise AssertionError("the M04 UI must not materialize Project.snapshot")

    monkeypatch.setattr(Project, "snapshot", reject_snapshot)
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.controller.open_project(project_path)
    _wait_for_map(qtbot, window)
    overview = _nodes(window)
    prologue = next(node for node in overview if node.title == "new_prologue")
    assert window.graph_canvas.semantic_level is SemanticLevel.OVERVIEW
    assert 0 < len(overview) < window.graph_canvas.max_rendered_items
    assert prologue.expandable

    assert window.graph_canvas.focus_search_result(prologue.id)
    window.level_two_button.click()
    _wait_for_map(qtbot, window)
    events = _nodes(window)
    assert window.graph_canvas.semantic_level is SemanticLevel.EVENTS
    assert events and {node.semantic_levels for node in events} == {
        frozenset({SemanticLevel.EVENTS})
    }
    choice = next(node for node in events if node.kind == "choice")
    assert "Offer help" in choice.summary and "Walk away" in choice.summary
    assert "Ian Charisma > 0" in choice.requirements
    assert {"Love += 1", 'Route Flag = "helper"', "Money -= 10"} <= set(choice.effects)

    window.search_input.setText("I can help")
    qtbot.keyClick(window.search_input, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: window.graph_canvas.semantic_level is SemanticLevel.EVIDENCE
        and window.graph_canvas.selected_node_id is not None
        and not window.map_presenter.is_busy,
        timeout=5000,
    )
    evidence = _nodes(window)
    assert 0 < len(evidence) <= 4
    assert window.evidence_list.count() > 0
    assert "story.rpy:" in window.evidence_list.item(0).text()


def test_search_hidden_renamed_nodes_lineage_and_durable_overrides(tmp_path: Path) -> None:
    project_path, source = _create_project(tmp_path)
    with PresentationService.open(project_path) as service:
        overview = service.view(PresentationRequest(PresentationLevel.OVERVIEW))
        prologue = next(node for node in overview.nodes if node.name == "new_prologue")
        event = service.view(
            PresentationRequest(PresentationLevel.EVENT, parent_ids=(prologue.id,))
        ).nodes[0]
        beat = service.view(
            PresentationRequest(PresentationLevel.EVIDENCE, parent_ids=(event.id,))
        ).nodes[0]
        assert [node.level for node in service.lineage(beat.id)] == [
            PresentationLevel.OVERVIEW,
            PresentationLevel.EVENT,
            PresentationLevel.EVIDENCE,
        ]

        service.rename_node(prologue.id, "Opening Arc")
        renamed = cast(
            tuple[SearchHit, ...],
            service.search("Opening Arc", fields=("label",)).items,
        )
        assert any(hit.node_id == prologue.id for hit in renamed)
        assert not service.search("new_prologue", fields=("label",)).items
        service.set_hidden(prologue.id, True)
        assert not service.search("Opening Arc", fields=("label",)).items
        assert not service.lineage(prologue.id)
        service.set_hidden(prologue.id, False)

        service.update_state_variable(
            "love", display_name="Affection", category="relationship_custom"
        )
        filtered = cast(
            tuple[FactRecord, ...],
            service.facts(kind="effect", variable="love", category="relationship_custom").items,
        )
        assert filtered and filtered[0].expression == "love += 1"

    refresh_project(project_path, source)
    with PresentationService.open(project_path) as reopened:
        visible = reopened.view(PresentationRequest(PresentationLevel.OVERVIEW)).nodes
        assert next(node for node in visible if node.id == prologue.id).name == "Opening Arc"
        variable = next(
            item
            for item in reopened.state_variables().items
            if getattr(item, "original_name", None) == "love"
        )
        assert variable.display_name == "Affection"
        assert variable.category == "relationship_custom"


def test_independent_expansion_collapse_and_canvas_filters(
    qtbot: QtBot, tmp_path: Path
) -> None:
    project_path, _ = _create_project(tmp_path)
    with PresentationService.open(project_path) as service:
        roots = service.view(PresentationRequest(PresentationLevel.OVERVIEW)).nodes
        expandable = tuple(node for node in roots if node.expandable)
        assert len(expandable) >= 2
        first, second = expandable[:2]
        both = service.view(
            PresentationRequest(PresentationLevel.EVENT, expanded_ids=(first.id, second.id))
        ).nodes
        only_second = service.view(
            PresentationRequest(
                PresentationLevel.EVENT,
                expanded_ids=(first.id, second.id),
                collapsed_ids=(first.id,),
            )
        ).nodes
        assert {node.parent_id for node in both} == {first.id, second.id}
        assert {node.parent_id for node in only_second} == {second.id}

    canvas = GraphCanvas(max_rendered_items=8)
    qtbot.addWidget(canvas)
    canvas.set_semantic_level(SemanticLevel.EVENTS)
    canvas.set_slice(
        (
            GraphNodeSpec("technical", "technical", "Technical"),
            GraphNodeSpec("unresolved", "unresolved", "Unresolved"),
            GraphNodeSpec(
                "love",
                "effect",
                "Love",
                variables=frozenset({"love"}),
                categories=frozenset({"relationship"}),
            ),
            GraphNodeSpec(
                "money",
                "effect",
                "Money",
                variables=frozenset({"money"}),
                categories=frozenset({"resource"}),
            ),
        ),
        (),
    )

    def visible() -> set[str]:
        return {
            item.spec.id
            for item in canvas.scene().items()
            if hasattr(item, "spec")
            and isinstance(item.spec, GraphNodeSpec)
            and item.isVisible()
        }

    canvas.set_kind_visible("technical", False)
    canvas.set_kind_visible("unresolved", False)
    assert visible() == {"love", "money"}
    canvas.set_variable_filter({"love"})
    assert visible() == {"love"}
    canvas.set_variable_filter(())
    canvas.set_category_filter({"resource"})
    assert visible() == {"money"}


def test_exact_choice_evidence_and_filter_metadata_are_source_linked(tmp_path: Path) -> None:
    project_path, _ = _create_project(tmp_path)
    with PresentationService.open(project_path) as service:
        choice_hit = cast(
            SearchHit,
            service.search("Offer help", fields=("choice",), limit=1).items[0],
        )
        lineage = service.lineage(choice_hit.node_id)
        assert len(lineage) == 3
        evidence = cast(
            tuple[EvidenceRecord, ...], service.evidence(choice_hit.node_id).items
        )
        assert evidence
        assert all(item.source_path == "story.rpy" for item in evidence)
        assert any(item.start_line == 10 and "Offer help" in item.text for item in evidence)

        gate = cast(
            FactRecord,
            service.facts(kind="gate", variable="ian_charisma", limit=1).items[0],
        )
        effect = cast(
            FactRecord,
            service.facts(kind="effect", variable="love", limit=1).items[0],
        )
        assert (gate.status, gate.source_path, gate.start_line) == (
            "proven",
            "story.rpy",
            11,
        )
        assert (effect.status, effect.source_path, effect.start_line) == (
            "proven",
            "story.rpy",
            12,
        )
        assert gate.node_id is not None and effect.node_id is not None


def test_variable_display_override_is_presented_in_choice_badges(
    qtbot: QtBot, tmp_path: Path
) -> None:
    project_path, _ = _create_project(tmp_path)
    with Project.open(project_path) as project:
        project.update_state_variable("love", display_name="Affection")

    window = MainWindow()
    qtbot.addWidget(window)
    assert window.controller.open_project(project_path)
    _wait_for_map(qtbot, window)
    prologue = next(node for node in _nodes(window) if node.title == "new_prologue")
    assert window.graph_canvas.focus_search_result(prologue.id)
    window.level_two_button.click()
    _wait_for_map(qtbot, window)
    choice = next(node for node in _nodes(window) if node.kind == "choice")
    assert "Affection += 1" in choice.effects


def test_presentation_rebuild_cancellation_rolls_back_consistently(tmp_path: Path) -> None:
    project_path, _ = _create_project(tmp_path)
    with Project.open(project_path) as project:
        connection = project._require_open()
        generation = str(
            connection.execute(
                "SELECT generation FROM presentation_index_state WHERE singleton=1"
            ).fetchone()[0]
        )
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "presentation_nodes",
                "presentation_edges",
                "presentation_evidence",
                "presentation_search",
                "presentation_facts",
            )
        }
        calls = 0

        def cancel_during_rebuild() -> bool:
            nonlocal calls
            calls += 1
            return calls >= 3

        with pytest.raises(storage.ProjectOperationCancelled):
            rebuild_presentation_index(project, cancelled=cancel_during_rebuild)

        assert (
            str(
                connection.execute(
                    "SELECT generation FROM presentation_index_state WHERE singleton=1"
                ).fetchone()[0]
            )
            == generation
        )
        assert counts == {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in counts
        }


def test_migration_has_required_indexes_and_visible_node_lookup_is_index_bounded(
    tmp_path: Path,
) -> None:
    project_path, _ = _create_project(tmp_path)
    with Project.open(project_path) as project:
        connection = project._require_open()
        indexes = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='index'"
            )
        }
        assert {
            "presentation_nodes_parent_idx",
            "presentation_nodes_parent_lookup_idx",
            "presentation_edges_level_idx",
            "presentation_edges_source_idx",
            "presentation_evidence_node_idx",
            "presentation_search_normalized_idx",
            "presentation_facts_filter_idx",
            "presentation_facts_node_idx",
        } <= indexes

        plan = connection.execute(
            """EXPLAIN QUERY PLAN
            SELECT n.*,
                   (SELECT COUNT(*) FROM presentation_nodes c
                    WHERE c.parent_id=n.node_id) AS child_count
            FROM presentation_nodes n
            WHERE n.level=?
            ORDER BY n.sort_key,n.node_id LIMIT ?""",
            (int(PresentationLevel.EVIDENCE), 81),
        ).fetchall()
        details = tuple(str(row[3]) for row in plan)
        assert not any("SCAN c" in detail for detail in details), details


def test_level_round_trip_restores_selection_for_the_previous_level(
    qtbot: QtBot, tmp_path: Path
) -> None:
    project_path, _ = _create_project(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.controller.open_project(project_path)
    _wait_for_map(qtbot, window)

    prologue = next(node for node in _nodes(window) if node.title == "new_prologue")
    assert window.graph_canvas.focus_search_result(prologue.id)
    window.level_two_button.click()
    _wait_for_map(qtbot, window)
    event = _nodes(window)[0]
    assert window.graph_canvas.focus_search_result(event.id)

    window.level_one_button.click()
    _wait_for_map(qtbot, window)
    assert window.graph_canvas.selected_node_id == prologue.id


def test_descendant_queries_use_point_lookups_instead_of_full_index_scans(
    tmp_path: Path,
) -> None:
    project_path, _ = _create_project(tmp_path)
    with PresentationService.open(project_path) as service:
        root = next(
            node
            for node in service.view(PresentationRequest(PresentationLevel.OVERVIEW)).nodes
            if node.name == "new_prologue"
        )
        connection = service._project._require_open()
        evidence_plan = connection.execute(
            """EXPLAIN QUERY PLAN
            WITH RECURSIVE descendants(node_id, depth) AS (
              SELECT ?, 0
              UNION ALL
              SELECT n.node_id, d.depth + 1 FROM presentation_nodes n
              JOIN descendants d ON n.parent_id=d.node_id WHERE d.depth < 2
            )
            SELECT e.* FROM descendants d
            CROSS JOIN presentation_evidence e INDEXED BY presentation_evidence_node_idx
              ON e.node_id=d.node_id
            ORDER BY e.sort_key,e.evidence_id LIMIT ?""",
            (root.id, 26),
        ).fetchall()
        fact_plan = connection.execute(
            """EXPLAIN QUERY PLAN
            WITH RECURSIVE descendants(node_id, depth) AS (
              SELECT ?, 0
              UNION ALL
              SELECT n.node_id, d.depth + 1 FROM presentation_nodes n
              JOIN descendants d ON n.parent_id=d.node_id WHERE d.depth < 2
            )
            SELECT f.* FROM descendants d
            CROSS JOIN presentation_facts f INDEXED BY presentation_facts_node_idx
              ON f.node_id=d.node_id
            ORDER BY f.sort_key,f.fact_id LIMIT ?""",
            (root.id, 26),
        ).fetchall()
        evidence_details = tuple(str(row[3]) for row in evidence_plan)
        fact_details = tuple(str(row[3]) for row in fact_plan)
        assert any(
            "SEARCH e USING INDEX presentation_evidence_node_idx (node_id=?)" in detail
            for detail in evidence_details
        ), evidence_details
        assert any(
            "SEARCH f USING INDEX presentation_facts_node_idx (node_id=?)" in detail
            for detail in fact_details
        ), fact_details


def test_choice_outcome_walk_uses_source_edge_and_fact_point_lookups(
    tmp_path: Path,
) -> None:
    project_path, _ = _create_project(tmp_path)
    with PresentationService.open(project_path) as service:
        root = next(
            node
            for node in service.view(PresentationRequest(PresentationLevel.OVERVIEW)).nodes
            if node.name == "new_prologue"
        )
        choice = next(
            node
            for node in service.view(
                PresentationRequest(PresentationLevel.EVENT, parent_ids=(root.id,))
            ).nodes
            if node.kind == "choice_group"
        )
        records = cast(
            tuple[FactRecord, ...], service.choice_outcome_facts(choice.id).items
        )
        assert {
            "ian_charisma > 0",
            "love += 1",
            'route_flag = "helper"',
            "money -= 10",
        } <= {record.expression for record in records}

        plan = service._project._require_open().execute(
            """EXPLAIN QUERY PLAN
            WITH RECURSIVE context(scene_id) AS (
              SELECT parent_id FROM presentation_nodes
              WHERE node_id=? AND level=2 AND kind='choice_group'
            ), walk(node_id) AS (
              SELECT node_id FROM presentation_nodes
              WHERE parent_id=? AND level=3 AND kind='choice'
              UNION
              SELECT e.target_id FROM walk w
              JOIN presentation_nodes current ON current.node_id=w.node_id
              CROSS JOIN presentation_edges e INDEXED BY presentation_edges_source_idx
                ON e.level=3 AND e.source_id=w.node_id
              JOIN presentation_nodes target ON target.node_id=e.target_id
              JOIN presentation_nodes target_event ON target_event.node_id=target.parent_id
              JOIN context c ON target_event.parent_id=c.scene_id
              WHERE current.kind NOT IN ('jump','return','module_end','ending')
              LIMIT 512
            )
            SELECT DISTINCT f.* FROM presentation_facts f
            JOIN walk w ON w.node_id=f.node_id
            ORDER BY f.sort_key,f.fact_id LIMIT ?""",
            (choice.id, choice.id, 51),
        ).fetchall()
        details = tuple(str(row[3]) for row in plan)
        assert any(
            "SEARCH e USING COVERING INDEX presentation_edges_source_idx "
            "(level=? AND source_id=?)" in detail
            for detail in details
        ), details
        assert any(
            "SEARCH f USING INDEX presentation_facts_node_idx (node_id=?)" in detail
            for detail in details
        ), details
