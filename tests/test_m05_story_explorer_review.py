from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QApplication,
    QListWidget,
    QMessageBox,
    QStackedWidget,
    QWidget,
)
from pytestqt.qtbot import QtBot
from scripts.m05_ui_acceptance import _file_backed_settings

from renpy_story_mapper.organization import CodexMode
from renpy_story_mapper.presentation import EvidenceRecord
from renpy_story_mapper.project import create_project
from renpy_story_mapper.story_organization import (
    DraftReview,
    OrganizationDraft,
    StoryArc,
    StoryEdge,
    StoryEvent,
)
from renpy_story_mapper.ui import story_explorer
from renpy_story_mapper.ui.graph_canvas import (
    GraphCanvas,
    GraphNodeSpec,
    SemanticLevel,
    semantic_kind_label,
)
from renpy_story_mapper.ui.main_window import MainWindow
from renpy_story_mapper.ui.organization_workflow import OrganizationOptions
from renpy_story_mapper.ui.project_controller import ProjectSession
from renpy_story_mapper.ui.story_explorer import (
    AcceptedStoryPresenter,
    DraftReviewDialog,
    InspectorTabs,
    StorySnapshot,
)

FIXTURE = Path(__file__).parent / "fixtures" / "m05" / "organization"


def _window(qtbot: QtBot, settings_path: Path) -> MainWindow:
    window = MainWindow(
        settings=QSettings(str(settings_path), QSettings.Format.IniFormat)
    )
    qtbot.addWidget(window)
    return window


def test_acceptance_harness_settings_are_explicit_file_backed(
    tmp_path: Path,
) -> None:
    settings_root = tmp_path / "disposable-settings"
    settings_root.mkdir()
    settings = _file_backed_settings(settings_root)
    settings_file = Path(settings.fileName()).resolve()

    assert settings.format() == QSettings.Format.IniFormat
    assert settings_file == (settings_root / "m05-ui-acceptance.ini").resolve()
    assert settings_file.is_relative_to(settings_root.resolve())
    settings.setValue("recentProjects", ["synthetic-project"])
    settings.sync()
    assert settings.status() == QSettings.Status.NoError
    assert settings_file.is_file()


def _presenter(qtbot: QtBot) -> tuple[
    AcceptedStoryPresenter, GraphCanvas, QListWidget, InspectorTabs, QListWidget
]:
    canvas = GraphCanvas()
    navigator = QListWidget()
    inspector = InspectorTabs()
    stack = QStackedWidget()
    stack.addWidget(canvas)
    evidence = QListWidget()
    stack.addWidget(evidence)
    for widget in (canvas, navigator, inspector, stack):
        qtbot.addWidget(widget)
    return (
        AcceptedStoryPresenter(canvas, navigator, inspector, stack, evidence),
        canvas,
        navigator,
        inspector,
        evidence,
    )


def test_no_explicit_scope_means_full_game_and_selection_remains_exact(
    qtbot: QtBot, tmp_path: Path,
) -> None:
    window = _window(qtbot, tmp_path / "full-game.ini")
    window.map_presenter._last_nodes[SemanticLevel.OVERVIEW] = (
        "loaded-page-a",
        "loaded-page-b",
    )
    captured: list[tuple[str, ...]] = []

    def organize(
        scopes: object, _options: object, *, cloud_confirmed: bool = False
    ) -> bool:
        del cloud_confirmed
        captured.append(tuple(scopes))  # type: ignore[arg-type]
        return True

    window.organization_controller.organize = organize  # type: ignore[method-assign]
    window._organize(OrganizationOptions(mode=CodexMode.CODEX_LMSTUDIO, model=None))
    assert captured == [()]
    assert "full game" in window.status_label.text().lower()

    window.map_presenter._selected_by_level[SemanticLevel.OVERVIEW] = "selected-scope"
    window._organize(OrganizationOptions(mode=CodexMode.CODEX_LMSTUDIO, model=None))
    assert captured[-1] == ("selected-scope",)
    assert "selected scope" in window.status_label.text().lower()
    window.map_presenter._selected_by_level[SemanticLevel.OVERVIEW] = "different-scope"
    window._retry_organization()
    assert captured[-1] == ("selected-scope",)
    window.map_presenter._selection_changed(None)
    assert window.map_presenter.selected_overview_scope_ids == ()


def test_partial_accepted_story_keeps_first_class_technical_map(
    qtbot: QtBot, tmp_path: Path,
) -> None:
    window = _window(qtbot, tmp_path / "technical-map.ini")
    window.set_application_zoom(200)
    welcome_title = window.welcome_page.findChild(QWidget, "welcomeTitle")
    assert welcome_title is not None
    assert welcome_title.font().pixelSize() >= 48
    window.set_application_zoom(100)
    arc = StoryArc(
        "arc", "Accepted arc", "Only one scope is organized", 0, "ai", False,
        False, "approved", False, ("event",)
    )
    event = StoryEvent(
        "event", "Accepted event", "Accepted", 0, "ai", False, False,
        "approved", False, ("beat",)
    )
    window.accepted_presenter._loaded(
        StorySnapshot((arc,), (event,), (), (), (), (), None, None)
    )

    navigator_text = [
        window.navigator.item(index).text() for index in range(window.navigator.count())
    ]
    assert "Technical map / unorganized scopes" in navigator_text
    assert window.accepted_presenter.viewing_accepted
    assert window.map_presenter._render_suppressed

    window.technical_filter.setChecked(True)
    assert not window.accepted_presenter.viewing_accepted
    assert not window.map_presenter._render_suppressed
    assert window._accepted_target() is None
    assert "Technical" in window.breadcrumb_label.text()

    window.technical_filter.setChecked(False)
    assert window.accepted_presenter.viewing_accepted
    assert window.map_presenter._render_suppressed
    assert window.graph_canvas.rendered_node_ids == ("arc",)


def test_scoped_review_is_bounded_paged_and_excludes_uncovered_state(
    qtbot: QtBot, tmp_path: Path,
) -> None:
    parent = _window(qtbot, tmp_path / "review.ini")
    proposed_events = [
        {
            "id": f"event-{index:03d}",
            "title": f"Event {index}",
            "summary": "A bounded proposed summary",
            "beat_ids": [f"beat-{index:03d}"],
            "outcomes": ["Route changes"] if index == 0 else [],
            "warnings": ["Interpretation"] if index == 0 else [],
        }
        for index in range(241)
    ]
    candidate = {
        "_scope": {"scope_ids": ["scope-a"], "covered_beat_ids": ["beat-covered"]},
        "selected_beat_ids": ["beat-covered"],
        "arcs": [],
        "events": proposed_events,
        "claims": [
            {
                "event_id": "event-000",
                "arc_id": None,
                "text": "Interpretation",
                "evidence_ids": ["evidence-1"],
            }
        ],
        "ungrouped_beat_ids": [],
    }
    draft = OrganizationDraft("draft", "run", "generation", "pending", candidate, "utc", None)
    covered = StoryEvent(
        "covered", "Covered current", "", 0, "ai", False, False, "approved", False,
        ("beat-covered",)
    )
    outside = StoryEvent(
        "outside", "Outside untouched", "", 1, "ai", False, False, "approved", False,
        ("beat-outside",)
    )
    dialog = DraftReviewDialog(draft, None, (), (covered, outside), (), parent)
    qtbot.addWidget(dialog)

    assert dialog.groups.count() == 240
    assert dialog.comparison.count() <= 240
    assert "1 container" in dialog.scope_summary.text()
    assert "Outside untouched" not in [
        dialog.comparison.item(index).text()
        for index in range(dialog.comparison.count())
    ]
    first = dialog.groups.item(0).text()
    assert "Members 1" in first
    assert "Claims 1" in first
    assert "Evidence 1" in first
    assert "Outcomes 1" in first
    assert "Warnings 1" in first
    assert "Decision pending" in first
    dialog.next_groups.click()
    assert dialog.groups.count() == 1
    assert "241-241 of 241" in dialog.group_page_status.text()


def test_review_combo_preserves_an_existing_rejection(
    qtbot: QtBot, tmp_path: Path
) -> None:
    parent = _window(qtbot, tmp_path / "decision.ini")
    candidate = {
        "arcs": [],
        "events": [
            {
                "id": "event",
                "title": "Candidate",
                "summary": "Candidate summary",
                "beat_ids": ["beat"],
            }
        ],
        "claims": [],
        "ungrouped_beat_ids": [],
    }
    draft = OrganizationDraft("draft", "run", "generation", "pending", candidate, "utc", None)
    review = DraftReview("draft", "event", "event", "rejected", "utc")
    dialog = DraftReviewDialog(draft, None, (), (), (review,), parent)
    qtbot.addWidget(dialog)
    saved: list[str] = []
    dialog.review_requested.connect(
        lambda _kind, _identifier, decision: saved.append(decision)
    )

    dialog.groups.setCurrentRow(0)
    assert dialog.decision.currentText() == "Reject"
    dialog._save()
    assert saved == ["rejected"]


def test_split_merge_review_metrics_are_linear_at_full_game_scale() -> None:
    current = tuple(
        StoryEvent(
            f"current-{index}", "Current", "", index, "ai", False, False,
            "approved", False, (f"beat-{index}",)
        )
        for index in range(10_000)
    )
    proposed = tuple(
        {"id": f"proposed-{index}", "beat_ids": [f"beat-{index}"]}
        for index in range(10_000)
    )
    started = time.perf_counter()
    assert story_explorer._split_merge_counts(current, proposed) == (0, 0)
    assert time.perf_counter() - started < 1.0


def test_event_windowing_reaches_results_after_first_thirty_and_keeps_filters(
    qtbot: QtBot,
) -> None:
    presenter, canvas, _navigator, _inspector, _evidence = _presenter(qtbot)
    events = tuple(
        StoryEvent(
            f"event-{index:02d}",
            f"Event {index}",
            "late unique result" if index == 34 else "Ordinary",
            index,
            "ai",
            False,
            False,
            "approved",
            False,
            (f"beat-{index:02d}",),
        )
        for index in range(35)
    )
    arc = StoryArc(
        "arc", "Long arc", "Overview", 0, "ai", False, False, "approved", False,
        tuple(event.id for event in events)
    )
    presenter._snapshot = StorySnapshot(
        (arc,),
        events,
        (StoryEdge("boundary", "event-29", "event-30", "choice", ("edge",)),),
        (),
        (),
        (),
        None,
        None,
        event_filters=(("event-34", ("love",), ("relationship",)),),
    )
    presenter._active = True

    presenter.show_arc("arc")
    assert len(canvas.rendered_node_ids) == 30
    assert "event-34" not in canvas.rendered_node_ids
    assert canvas._node_items["event-29"].spec.kind == "choice"
    assert presenter.search("late unique result")
    assert canvas.rendered_node_ids == tuple(f"event-{index:02d}" for index in range(30, 35))
    assert canvas.selected_node_id == "event-34"
    spec = canvas._node_items["event-34"].spec
    assert spec.variables == frozenset({"love"})
    assert spec.categories == frozenset({"relationship"})
    assert canvas.rendered_item_count <= 240
    canvas.set_variable_filter(("missing-variable",))
    assert canvas.selected_node_id is None
    assert presenter.selected_target is None
    canvas.set_variable_filter(())
    canvas.set_category_filter(("relationship",))
    presenter.show_overview()
    assert canvas._node_items["arc"].isVisible()
    assert canvas.visible_item_count == 1


def test_hidden_accepted_group_has_view_and_unhide_correction_path(
    qtbot: QtBot, tmp_path: Path,
) -> None:
    window = _window(qtbot, tmp_path / "hidden.ini")
    visible = StoryArc(
        "visible", "Visible", "", 0, "ai", False, False, "approved", False, ()
    )
    hidden = StoryArc(
        "hidden", "Hidden route", "Hidden", 1, "ai", True, True, "rejected", False,
        ("hidden-event",)
    )
    hidden_event = StoryEvent(
        "hidden-event", "Hidden scene", "Hidden event", 1, "ai", False, True,
        "rejected", False, ("hidden-beat",)
    )
    window.accepted_presenter._loaded(
        StorySnapshot((visible, hidden), (hidden_event,), (), (), (), (), None, None)
    )
    hidden_item = next(
        window.navigator.item(index)
        for index in range(window.navigator.count())
        if window.navigator.item(index).data(Qt.ItemDataRole.UserRole)
        == ("hidden-arc", "hidden")
    )
    window.accepted_presenter._navigator_activated(hidden_item)

    assert window._accepted_target() == ("arc", "hidden")
    assert window.hide_node_button.text() == "Unhide selected"
    assert window.pin_node_button.text() == "Unpin selected"
    assert window.reject_node_button.text() == "Rejected"
    assert not window.reject_node_button.isEnabled()
    assert not window.reset_node_name_button.isEnabled()
    window.accepted_presenter._session = ProjectSession(
        tmp_path / "project.rsmproj", tmp_path, "folder", 1
    )
    window.accepted_presenter._accept_search(
        window.accepted_presenter._search_generation,
        None,  # type: ignore[arg-type]
        "hidden-event",
    )
    assert window._accepted_target() == ("event", "hidden-event")
    assert window.hide_node_button.text() == "Unhide selected"


def test_accepted_search_never_falls_through_and_errors_offer_inline_recovery(
    qtbot: QtBot, tmp_path: Path,
) -> None:
    window = _window(qtbot, tmp_path / "errors.ini")
    arc = StoryArc(
        "arc", "Accepted", "", 0, "ai", False, False, "approved", False, ("event",)
    )
    event = StoryEvent(
        "event", "Known", "", 0, "ai", False, False, "approved", False, ("beat",)
    )
    window.accepted_presenter._loaded(
        StorySnapshot((arc,), (event,), (), (), (), (), None, None)
    )
    technical_searches: list[str] = []
    window.map_presenter.search = technical_searches.append  # type: ignore[method-assign]
    window.search_input.setText("not in accepted story")
    window._search_story()
    assert technical_searches == []

    window._show_error("Project could not be opened safely.")
    assert window.recovery_button.text() == "Open Project"
    assert not window.recovery_button.isHidden()
    assert not any(
        isinstance(widget, QMessageBox) for widget in QApplication.topLevelWidgets()
    )
    window.map_presenter._task_status = "Searching map"
    window.map_presenter._failure(RuntimeError("synthetic failure"))
    assert window.recovery_button.text() == "Retry search"
    retried: list[str] = []
    window.accepted_presenter.reload = lambda: retried.append("accepted")  # type: ignore[method-assign]
    window._show_presentation_error("The story view failed safely.")
    assert window.recovery_button.text() == "Retry accepted story"
    window.recovery_button.click()
    assert retried == ["accepted"]


def test_evidence_review_and_navigator_lists_never_exceed_240(qtbot: QtBot) -> None:
    presenter, _canvas, navigator, inspector, evidence = _presenter(qtbot)
    records = tuple(
        EvidenceRecord(
            f"evidence-{index}",
            "beat",
            "dialogue",
            "story.rpy",
            index + 1,
            index + 1,
            f"Line {index}",
            {},
        )
        for index in range(240)
    )
    statuses: list[str] = []
    presenter.status_changed.connect(statuses.append)
    presenter._evidence_loaded(story_explorer._EvidenceSlice(records, True))
    assert evidence.count() == 240
    assert inspector.evidence.count() == 240
    assert evidence.currentItem() is not None
    assert "truncated" in statuses[-1]

    arcs = tuple(
        StoryArc(
            f"arc-{index}", f"Arc {index}", "", index, "ai", False, index > 0,
            "approved", False, ()
        )
        for index in range(260)
    )
    presenter._snapshot = StorySnapshot(arcs, (), (), (), (), (), None, None)
    presenter._active = True
    presenter._populate_navigator()
    assert navigator.count() <= 240
    assert any(
        "truncated" in navigator.item(index).text().lower()
        for index in range(navigator.count())
    )


def test_pending_draft_uses_its_own_run_metadata(tmp_path: Path) -> None:
    project_path = tmp_path / "runs.rsmproj"
    with create_project(project_path, FIXTURE) as project:
        service = project.organization_service()
        pending_run = service.create_run(
            provider_mode="codex_lmstudio",
            model_profile="balanced",
            model_fingerprint="pending-model",
            prompt_version="prompt-v1",
            output_schema_version="schema-v1",
            generation="generation",
            run_id="pending-run",
        )
        service.finish_run(pending_run, "completed", elapsed_ms=1)
        all_beats = [
            str(row[0])
            for row in project._require_open().execute(
                "SELECT node_id FROM presentation_nodes WHERE level=3 ORDER BY sort_key,node_id"
            )
        ]
        service.create_draft(
            pending_run,
            "generation",
            {
                "arcs": [],
                "events": [],
                "claims": [],
                "ungrouped_beat_ids": all_beats,
            },
        )
        newer_run = service.create_run(
            provider_mode="codex_lmstudio",
            model_profile="balanced",
            model_fingerprint="wrong-model",
            prompt_version="prompt-v1",
            output_schema_version="schema-v1",
            generation="generation",
            run_id="newer-run",
        )
        service.finish_run(newer_run, "failed", elapsed_ms=1)

    snapshot = story_explorer._load_snapshot(project_path)
    assert snapshot.pending_draft is not None
    assert snapshot.pending_draft.run_id == "pending-run"
    assert snapshot.latest_run is not None
    assert snapshot.latest_run.id == "pending-run"
    assert snapshot.latest_run.model_fingerprint == "pending-model"


def test_graph_cards_scale_geometry_and_show_semantic_labels_at_200_percent(
    qtbot: QtBot,
) -> None:
    canvas = GraphCanvas()
    qtbot.addWidget(canvas)
    canvas.set_slice(
        (
            GraphNodeSpec("a", "choice", "A choice"),
            GraphNodeSpec("b", "gate", "A requirement"),
        ),
        (),
    )
    canvas.set_application_zoom(200)
    first = canvas._node_items["a"]
    second = canvas._node_items["b"]
    assert first.boundingRect().width() == 520
    assert first.boundingRect().height() == 316
    assert not first.sceneBoundingRect().intersects(second.sceneBoundingRect())
    assert semantic_kind_label("choice") == "CHOICE"
    assert semantic_kind_label("gate") == "REQUIREMENT"
