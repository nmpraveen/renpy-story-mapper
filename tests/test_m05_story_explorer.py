from __future__ import annotations

import os
import shutil
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QListWidget, QMessageBox, QStackedWidget
from pytestqt.qtbot import QtBot

from renpy_story_mapper.organization import CodexMode
from renpy_story_mapper.organization.contracts import (
    OrganizationChunkResult,
    OrganizationConstraints,
    OrganizationGroup,
    OrganizationRequest,
    OrganizationStage,
    ProviderExecutionMetadata,
    ProviderState,
)
from renpy_story_mapper.organization.errors import ConsentRequiredError, OrganizationError
from renpy_story_mapper.presentation import (
    Continuation,
    EvidenceRecord,
    PresentationEdge,
    PresentationLevel,
    PresentationNode,
    PresentationPage,
    PresentationRequest,
    ResultPage,
)
from renpy_story_mapper.presentation import (
    FactRecord as PresentationFactRecord,
)
from renpy_story_mapper.project import Project, create_project
from renpy_story_mapper.story_organization import (
    OrganizationDraft,
    OrganizationRun,
    StoryArc,
    StoryEdge,
    StoryEvent,
)
from renpy_story_mapper.ui.graph_canvas import GraphCanvas, SemanticLevel
from renpy_story_mapper.ui.main_window import MainWindow
from renpy_story_mapper.ui.organization_workflow import (
    OrganizationOptions,
    OrganizationWorkflow,
    _candidate_payload,
    _complete_prompt_chars,
    _EventCandidate,
    _node_story_text,
    _organize_arcs,
    _paged_evidence,
    _paged_facts,
    _paged_view,
    _reconcile_events,
    _request_member_characters,
    collect_organization_input,
)
from renpy_story_mapper.ui.story_explorer import (
    AcceptedStoryPresenter,
    DraftReviewDialog,
    InspectorTabs,
    StorySnapshot,
    WelcomeWidget,
    apply_story_palette,
)

FIXTURE = Path(__file__).parent / "fixtures" / "m05" / "organization"


def test_candidate_payload_intersects_characters_with_exact_member_evidence() -> None:
    event = _EventCandidate(
        id="event-a",
        title="Evidence-bound event",
        summary="Only Mira speaks in the final member set.",
        beat_ids=("beat-a",),
        characters=("jonas", "mira"),
        importance="major",
        outcomes=(),
        fact_ids=(),
        claims=(),
        warnings=(),
        allowed_character_names=("mira",),
    )
    arc = OrganizationGroup(
        id="arc-a",
        title="Evidence-bound arc",
        summary="The arc inherits only supported characters.",
        member_ids=("event-a",),
        characters=("jonas", "mira"),
        importance="major",
        outcomes=(),
        promoted_fact_ids=(),
        claims=(),
        warnings=(),
    )
    arcs = OrganizationChunkResult(
        OrganizationStage.ARCS,
        (arc,),
        (),
        {"stage": "arcs", "groups": [], "ungrouped_ids": []},
    )

    candidate = _candidate_payload((event,), set(), arcs)
    assert candidate["events"][0]["characters"] == ["mira"]  # type: ignore[index]
    assert candidate["arcs"][0]["characters"] == ["mira"]  # type: ignore[index]


def test_stage_one_character_evidence_is_scoped_to_exact_group_members() -> None:
    request = OrganizationRequest(
        run_id="run",
        chunk_id="chunk",
        scope_id="scene",
        stage=OrganizationStage.EVENTS,
        payload={
            "beats": [
                {"id": "beat-a", "speaker": "mira", "speakers": ["mira"]},
                {"id": "beat-b", "speaker": "jonas", "speakers": ["jonas"]},
            ]
        },
        constraints=OrganizationConstraints(
            ordered_member_ids=("beat-a", "beat-b"),
            required_member_ids=frozenset({"beat-a", "beat-b"}),
            character_names=frozenset({"mira", "jonas"}),
        ),
    )

    assert _request_member_characters(request, ("beat-a",)) == ("mira",)


class _FakePresentation:
    def __init__(self) -> None:
        self.evidence_calls: list[tuple[str, ...]] = []

    def view(self, request: object, *, selected_id: str | None = None) -> PresentationPage:
        del selected_id
        assert hasattr(request, "level")
        level = request.level
        parents = tuple(request.parent_ids)
        after = request.after
        if level is PresentationLevel.EVENT:
            scope = parents[0]
            groups = (
                PresentationNode(
                    f"{scope}-g1",
                    level,
                    scope,
                    "group",
                    "Group 1",
                    None,
                    None,
                    None,
                    True,
                    True,
                    0,
                    {},
                ),
                PresentationNode(
                    f"{scope}-g2",
                    level,
                    scope,
                    "group",
                    "Group 2",
                    None,
                    None,
                    None,
                    True,
                    True,
                    0,
                    {},
                ),
            )
            return PresentationPage(
                groups,
                (),
                Continuation(2, False, None),
                Continuation(0, False, None),
            )
        self.evidence_calls.append(parents)
        scope = parents[0].rsplit("-g", 1)[0]
        count = 300
        start = 0 if after is None else int(after)
        stop = min(count, start + 250)
        nodes = tuple(
            PresentationNode(
                f"{scope}-beat-{index:03d}",
                level,
                parents[index % 2],
                "narrative",
                f"Beat {index}",
                "story.rpy",
                index + 1,
                index + 1,
                False,
                False,
                0,
                {"source_text": f"Beat {index}"},
            )
            for index in range(start, stop)
        )
        edges = tuple(
            PresentationEdge(
                f"{scope}-edge-{index:03d}",
                level,
                f"{scope}-beat-{index:03d}",
                f"{scope}-beat-{index + 1:03d}",
                "flow",
                {},
            )
            for index in range(start, max(start, stop - 1))
        )
        return PresentationPage(
            nodes,
            edges,
            Continuation(len(nodes), stop < count, str(stop) if stop < count else None),
            Continuation(len(edges), False, None),
        )

    def evidence(self, _node_id: str, *, after: str | None = None, limit: int = 25) -> ResultPage:
        del after, limit
        return ResultPage((), Continuation(0, False, None))

    def edges_for_nodes(
        self, level: PresentationLevel, node_ids: tuple[str, ...]
    ) -> tuple[PresentationEdge, ...]:
        selected = set(node_ids)
        return tuple(
            PresentationEdge(
                f"edge-{source}",
                level,
                source,
                target,
                "flow",
                {},
            )
            for source, target in pairwise(node_ids)
            if source.rsplit("-beat-", 1)[0] == target.rsplit("-beat-", 1)[0]
            and source in selected
            and target in selected
        )

    def facts(self, **_kwargs: object) -> ResultPage:
        return ResultPage((), Continuation(0, False, None))


class _FakeProject:
    def __init__(self, presentation: _FakePresentation) -> None:
        self._presentation = presentation

    def presentation_service(self) -> _FakePresentation:
        return self._presentation


class _Provider:
    def __init__(self) -> None:
        self.requests: list[OrganizationRequest] = []
        self.cancelled = False
        self.model_override: str | None = None

    def set_model_override(self, model_identifier: str | None) -> None:
        self.model_override = model_identifier

    def status(self) -> Any:
        return SimpleNamespace(
            state=ProviderState.READY,
            executable="synthetic-codex",
            cli_version="test",
            message="",
            model_identifier=self.model_override or "synthetic-model",
        )

    def organize(self, request: OrganizationRequest, progress: Any, cancelled: Any) -> Any:
        self.requests.append(request)
        assert not cancelled()
        progress(50, request.stage.value)
        result = _validated_result(request, list(request.constraints.ordered_member_ids))
        return replace(
            result,
            metadata=ProviderExecutionMetadata(
                CodexMode.CODEX_LMSTUDIO,
                self.model_override or "synthetic-model",
                "test",
                1,
                "a" * 64,
                "b" * 64,
            ),
        )

    def cancel(self) -> None:
        self.cancelled = True


class _PreflightProvider:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.override: str | None = None

    def set_model_override(self, model: str) -> None:
        self.events.append(f"override:{model}")
        self.override = model

    def status(self) -> Any:
        self.events.append("status")
        return SimpleNamespace(
            state=ProviderState.READY,
            executable="codex",
            message="",
            model_identifier=self.override,
        )

    def organize(self, request: OrganizationRequest, progress: Any, cancelled: Any) -> Any:
        raise AssertionError("preflight test must stop before organization")

    def cancel(self) -> None:
        pass


class _StopAfterPreflightProject:
    def organization_service(self) -> Any:
        raise RuntimeError("preflight complete")


def _validated_result(request: OrganizationRequest, members: list[str]) -> Any:
    from renpy_story_mapper.organization.validation import validate_result

    if request.stage.value == "events" and len(members) > 1:
        midpoint = max(1, len(members) // 2)
        memberships = [members[:midpoint], members[midpoint:]]
    elif request.stage.value == "reconcile":
        memberships = [[member] for member in members]
    else:
        memberships = [members] if members else []
    payload = {
        "stage": request.stage.value,
        "groups": [
            {
                "id": f"{request.stage.value}-group-{index}",
                "title": f"{request.stage.value.title()} group",
                "summary": "Synthetic validated organization.",
                "member_ids": membership,
                "characters": [],
                "importance": "supporting",
                "outcomes": [],
                "promoted_fact_ids": [],
                "claims": [],
                "warnings": [],
            }
            for index, membership in enumerate(memberships)
        ],
        "ungrouped_ids": [],
    }
    return validate_result(payload, request)


def _create_project(tmp_path: Path) -> Path:
    source = tmp_path / "game"
    shutil.copytree(FIXTURE, source)
    path = tmp_path / "story.rsmproj"
    create_project(path, source).close()
    return path


def test_explicit_model_override_is_applied_before_status_discovery() -> None:
    provider = _PreflightProvider()
    workflow = OrganizationWorkflow(  # type: ignore[arg-type]
        _StopAfterPreflightProject(),
        lambda _mode: provider,  # type: ignore[return-value]
    )

    with pytest.raises(RuntimeError, match="preflight complete"):
        workflow.organize(
            ("scope",),
            OrganizationOptions(model="explicit-model"),
            progress=lambda _percent, _status: None,
            cancelled=lambda: False,
            confirm_cloud=lambda _run_id: True,
        )

    assert provider.events == ["override:explicit-model", "status"]


def test_provider_missing_state_fails_before_project_or_cache_access() -> None:
    provider = _PreflightProvider()

    def missing_status() -> Any:
        provider.events.append("status")
        return SimpleNamespace(
            state=ProviderState.MISSING,
            executable="codex",
            message="LM Studio endpoint is unavailable.",
            model_identifier=None,
        )

    provider.status = missing_status  # type: ignore[method-assign]
    workflow = OrganizationWorkflow(  # type: ignore[arg-type]
        _StopAfterPreflightProject(),
        lambda _mode: provider,  # type: ignore[return-value]
    )

    with pytest.raises(OrganizationError, match="LM Studio endpoint is unavailable"):
        workflow.organize(
            ("scope",),
            OrganizationOptions(),
            progress=lambda _percent, _status: None,
            cancelled=lambda: False,
            confirm_cloud=lambda _run_id: True,
        )

    assert provider.events == ["override:gpt-5.6-luna", "status"]


def test_cloud_requires_fresh_consent_before_provider_creation() -> None:
    provider_creations: list[CodexMode] = []
    consent_run_ids: list[str] = []
    workflow = OrganizationWorkflow(  # type: ignore[arg-type]
        _StopAfterPreflightProject(),
        lambda mode: provider_creations.append(mode),  # type: ignore[return-value]
    )

    def decline(run_id: str) -> bool:
        consent_run_ids.append(run_id)
        return False

    for _ in range(2):
        with pytest.raises(ConsentRequiredError):
            workflow.organize(
                ("scope",),
                OrganizationOptions(mode=CodexMode.CODEX_CHATGPT),
                progress=lambda _percent, _status: None,
                cancelled=lambda: False,
                confirm_cloud=decline,
            )

    assert len(set(consent_run_ids)) == 2
    assert provider_creations == []


def test_collection_pages_multiple_scopes_as_overview_scenes_and_keeps_cross_group_edges() -> None:
    presentation = _FakePresentation()
    beats, _facts = collect_organization_input(
        _FakeProject(presentation),  # type: ignore[arg-type]
        ("scope-z", "scope-a"),
        lambda: False,
    )
    assert len(beats) == 600
    assert [beat.scene_id for beat in beats[:300]] == ["scope-z"] * 300
    assert [beat.scene_id for beat in beats[300:]] == ["scope-a"] * 300
    assert presentation.evidence_calls[0] == ("scope-z-g1", "scope-z-g2")
    cross_group = beats[0].outgoing_ids
    assert cross_group == ("scope-z-beat-001",)
    assert beats[0].scene_id == beats[1].scene_id == "scope-z"


def test_view_paging_exhausts_node_and_edge_continuations_without_duplicates() -> None:
    class Presentation:
        def view(self, request: PresentationRequest) -> PresentationPage:
            start = 0 if request.after is None else int(request.after)
            stop = min(300, start + 250)
            nodes = tuple(
                PresentationNode(
                    f"node-{index}",
                    request.level,
                    "scope",
                    "narrative",
                    f"Node {index}",
                    "story.rpy",
                    index + 1,
                    index + 1,
                    False,
                    False,
                    0,
                    {},
                )
                for index in range(start, stop)
            )
            edge_total = 600 if start == 0 else 520
            edge_start = 0 if request.edge_after is None else int(request.edge_after)
            edge_stop = min(edge_total, edge_start + 500)
            edges = tuple(
                PresentationEdge(
                    f"page-{start}-edge-{index}",
                    request.level,
                    nodes[index % len(nodes)].id,
                    nodes[(index + 1) % len(nodes)].id,
                    "flow",
                    {},
                )
                for index in range(edge_start, edge_stop)
            )
            return PresentationPage(
                nodes,
                edges,
                Continuation(len(nodes), stop < 300, str(stop) if stop < 300 else None),
                Continuation(
                    len(edges),
                    edge_stop < edge_total,
                    str(edge_stop) if edge_stop < edge_total else None,
                ),
            )

    nodes, edges = _paged_view(  # type: ignore[arg-type]
        Presentation(), PresentationLevel.EVIDENCE, ("scope",), lambda: False
    )

    assert len(nodes) == 300
    assert len({node.id for node in nodes}) == 300
    assert len(edges) == 1_120
    assert len({edge.id for edge in edges}) == 1_120


def test_evidence_and_fact_paging_exhausts_more_than_one_hundred_rows() -> None:
    class Presentation:
        def evidence(self, node_id: str, *, after: str | None, limit: int) -> ResultPage:
            start = 0 if after is None else int(after)
            stop = min(150, start + limit)
            items = tuple(
                EvidenceRecord(
                    f"evidence-{index}",
                    node_id,
                    "dialogue",
                    "story.rpy",
                    index + 1,
                    index + 1,
                    f"Line {index}",
                    {},
                )
                for index in range(start, stop)
            )
            return ResultPage(
                items,
                Continuation(len(items), stop < 150, str(stop) if stop < 150 else None),
            )

        def facts(self, **kwargs: object) -> ResultPage:
            after = kwargs.get("after")
            limit = int(kwargs.get("limit", 100))
            start = 0 if after is None else int(str(after))
            stop = min(150, start + limit)
            items = tuple(
                PresentationFactRecord(
                    f"fact-{index}",
                    "beat",
                    "gate",
                    "flag",
                    None,
                    "resolved",
                    f"flag == {index}",
                    "story.rpy",
                    index + 1,
                    index + 1,
                    {},
                )
                for index in range(start, stop)
            )
            return ResultPage(
                items,
                Continuation(len(items), stop < 150, str(stop) if stop < 150 else None),
            )

    presentation = Presentation()
    evidence = _paged_evidence(presentation, "beat", lambda: False)  # type: ignore[arg-type]
    facts = _paged_facts(presentation, "beat", lambda: False)  # type: ignore[arg-type]

    assert len(evidence) == 150
    assert len(facts) == 150
    assert len({record.id for record in evidence}) == 150
    assert len({record.id for record in facts}) == 150


def test_cache_rerun_uses_no_provider_and_persists_scene_scopes(tmp_path: Path) -> None:
    path = _create_project(tmp_path)
    with Project.open(path) as project:
        overview = project.presentation_service().view(
            PresentationRequest(PresentationLevel.OVERVIEW, node_limit=12, edge_limit=24)
        )
        scope = overview.nodes[0].id
        first = _Provider()
        result = OrganizationWorkflow(project, lambda _mode: first).organize(
            (scope,),
            OrganizationOptions(
                mode=CodexMode.CODEX_LMSTUDIO, model_profile="balanced", model=None
            ),
            progress=lambda _percent, _status: None,
            cancelled=lambda: False,
        )
        assert result.provider_calls == len(first.requests) > 0
        assert {request.stage.value for request in first.requests} == {
            "events",
            "arcs",
        }
        arc_payload = next(
            request.payload for request in first.requests if request.stage.value == "arcs"
        )
        assert "text" not in str(arc_payload).casefold()
        assert arc_payload["local_connectivity"]
        chunks = project.organization_service().chunks(result.run_id)
        stage_one_count = sum(request.stage.value == "events" for request in first.requests)
        assert {chunk.reconciliation_scope for chunk in chunks[:stage_one_count]} == {scope}
        run = next(
            value
            for value in project.organization_service().runs()
            if value.id == result.run_id
        )
        assert run.model_fingerprint == "synthetic-model"

        second = _Provider()
        cached = OrganizationWorkflow(project, lambda _mode: second).organize(
            (scope,),
            OrganizationOptions(
                mode=CodexMode.CODEX_LMSTUDIO, model_profile="balanced", model=None
            ),
            progress=lambda _percent, _status: None,
            cancelled=lambda: False,
        )
        assert cached.provider_calls == 0
        assert cached.cache_hits == len(first.requests)
        assert second.requests == []


def test_inconsistent_effective_model_fails_run_without_draft(tmp_path: Path) -> None:
    class Provider(_Provider):
        def organize(
            self, request: OrganizationRequest, progress: Any, cancelled: Any
        ) -> Any:
            result = super().organize(request, progress, cancelled)
            if len(self.requests) > 1:
                assert result.metadata is not None
                result = replace(
                    result,
                    metadata=replace(result.metadata, model_identifier="different-model"),
                )
            return result

    path = _create_project(tmp_path)
    with Project.open(path) as project:
        scope = project.presentation_service().view(
            PresentationRequest(PresentationLevel.OVERVIEW, node_limit=12, edge_limit=24)
        ).nodes[0].id
        provider = Provider()

        with pytest.raises(OrganizationError, match="inconsistent model identifiers"):
            OrganizationWorkflow(project, lambda _mode: provider).organize(
                (scope,),
                    OrganizationOptions(),
                    progress=lambda _percent, _status: None,
                    cancelled=lambda: False,
                    confirm_cloud=lambda _run_id: True,
            )

        assert project.organization_service().drafts(status="pending") == ()
        assert project.organization_service().runs()[-1].status == "failed"


def test_late_cancellation_discards_pending_draft_and_marks_run_cancelled(
    tmp_path: Path,
) -> None:
    path = _create_project(tmp_path)
    with Project.open(path) as project:
        service = project.organization_service()
        cancelled = [False]

        class ServiceProxy:
            def __getattr__(self, name: str) -> Any:
                return getattr(service, name)

            def create_scoped_draft(self, *args: object, **kwargs: object) -> str:
                draft_id = service.create_scoped_draft(*args, **kwargs)  # type: ignore[attr-defined]
                cancelled[0] = True
                return draft_id

        class ProjectProxy:
            def presentation_service(self) -> Any:
                return project.presentation_service()

            def organization_service(self) -> Any:
                return ServiceProxy()

            def sources(self) -> Any:
                return project.sources()

        scope = project.presentation_service().view(
            PresentationRequest(PresentationLevel.OVERVIEW, node_limit=12, edge_limit=24)
        ).nodes[0].id

        with pytest.raises(OrganizationError, match="cancelled"):
            OrganizationWorkflow(  # type: ignore[arg-type]
                ProjectProxy(), lambda _mode: _Provider()
            ).organize(
                (scope,),
                    OrganizationOptions(),
                    progress=lambda _percent, _status: None,
                    cancelled=lambda: cancelled[0],
                    confirm_cloud=lambda _run_id: True,
            )

        assert service.drafts(status="pending") == ()
        assert service.runs()[-1].status == "cancelled"


def test_late_finish_failure_discards_pending_draft_and_marks_run_failed(
    tmp_path: Path,
) -> None:
    path = _create_project(tmp_path)
    with Project.open(path) as project:
        service = project.organization_service()

        class ServiceProxy:
            def __getattr__(self, name: str) -> Any:
                return getattr(service, name)

            def finish_run(self, run_id: str, status: str, **kwargs: object) -> None:
                if status == "completed":
                    raise RuntimeError("injected late failure")
                service.finish_run(run_id, status, **kwargs)  # type: ignore[arg-type]

        class ProjectProxy:
            def presentation_service(self) -> Any:
                return project.presentation_service()

            def organization_service(self) -> Any:
                return ServiceProxy()

            def sources(self) -> Any:
                return project.sources()

        scope = project.presentation_service().view(
            PresentationRequest(PresentationLevel.OVERVIEW, node_limit=12, edge_limit=24)
        ).nodes[0].id

        with pytest.raises(RuntimeError, match="injected late failure"):
            OrganizationWorkflow(  # type: ignore[arg-type]
                ProjectProxy(), lambda _mode: _Provider()
            ).organize(
                (scope,),
                    OrganizationOptions(),
                    progress=lambda _percent, _status: None,
                    cancelled=lambda: False,
                    confirm_cloud=lambda _run_id: True,
            )

        assert service.drafts(status="pending") == ()
        assert service.runs()[-1].status == "failed"


def test_welcome_workspace_accessibility_and_application_zoom(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    assert isinstance(window.page_stack.currentWidget(), WelcomeWidget)
    assert window.welcome_page.folder_button.accessibleName()
    assert window.navigator.accessibleName()
    assert window.inspector.accessibleName()
    assert window.evidence_timeline.accessibleName()
    window.set_application_zoom(200)
    assert window.font().pixelSize() == 28
    apply_story_palette(window, dark=True)
    assert window.palette().color(QPalette.ColorRole.Window).lightness() < 128


def test_organize_action_uses_full_game_when_no_scope_is_explicitly_selected(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.map_presenter._last_nodes[SemanticLevel.OVERVIEW] = ("overview-scope",)
    captured: list[tuple[tuple[str, ...], OrganizationOptions, bool]] = []

    def organize(scopes: Any, _options: Any, *, cloud_confirmed: bool = False) -> bool:
        captured.append((tuple(scopes), _options, cloud_confirmed))
        return True

    window.organization_controller.organize = organize  # type: ignore[method-assign]
    window.organize_button.setEnabled(True)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    window.organize_button.click()
    assert len(captured) == 1
    scopes, options, confirmed = captured[0]
    assert scopes == ()
    assert options.mode is CodexMode.CODEX_CHATGPT
    assert options.model == "gpt-5.6-luna"
    assert options.model_profile == "high"
    assert confirmed
    assert window.organize_button.menu() is None


def test_accepted_semantic_level_changes_reload_correct_slices(qtbot: QtBot) -> None:
    canvas = GraphCanvas()
    navigator = QListWidget()
    inspector = InspectorTabs()
    stack = QStackedWidget()
    stack.addWidget(canvas)
    evidence = QListWidget()
    stack.addWidget(evidence)
    for widget in (canvas, navigator, inspector, stack):
        qtbot.addWidget(widget)
    presenter = AcceptedStoryPresenter(canvas, navigator, inspector, stack, evidence)
    arc = StoryArc(
        "arc", "Opening", "Overview", 0, "ai", False, False, "approved", False, ("event",)
    )
    event = StoryEvent(
        "event", "Choice", "Choose", 0, "ai", False, False, "approved", False, ("beat",)
    )
    presenter._snapshot = StorySnapshot(
        (arc,),
        (event,),
        (StoryEdge("edge", "event", "event", "loop", ("l3:edge",)),),
        (),
        (),
        (),
        None,
        None,
    )
    presenter._active = True
    presenter.show_overview()
    assert canvas.rendered_node_ids == ("arc",)
    canvas.set_semantic_level(SemanticLevel.EVENTS)
    assert canvas.rendered_node_ids == ("event",)
    canvas.set_semantic_level(SemanticLevel.OVERVIEW)
    assert canvas.rendered_node_ids == ("arc",)
    assert canvas.rendered_item_count <= 240


def test_first_pending_draft_is_announced_without_accepted_arcs(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    candidate = {
        "arcs": [
            {
                "id": "arc",
                "title": "Opening",
                "summary": "Opening arc",
                "event_ids": ["event"],
            }
        ],
        "events": [
            {
                "id": "event",
                "title": "Arrival",
                "summary": "The story begins",
                "beat_ids": ["beat"],
            }
        ],
        "claims": [],
        "ungrouped_beat_ids": [],
    }
    draft = OrganizationDraft("draft", "run", "generation", "pending", candidate, "utc", None)
    snapshot = StorySnapshot((), (), (), (), (), (), draft, None)
    applied: list[str] = []

    def review(_draft: str, kind: str, identifier: str, decision: str) -> bool:
        window.organization_controller.review_saved.emit(kind, identifier, decision)
        return True

    window.organization_controller.review_group = review  # type: ignore[method-assign]
    window.organization_controller.apply_draft = (  # type: ignore[method-assign]
        lambda draft_id: applied.append(draft_id) is None
    )
    window.accepted_presenter._loaded(snapshot)

    dialog = window._review_dialog
    assert isinstance(dialog, DraftReviewDialog)
    assert not window.accepted_presenter.active
    assert not dialog.apply_button.isEnabled()
    for row in range(dialog.groups.count()):
        dialog.groups.setCurrentRow(row)
        dialog._save()
    assert dialog.apply_button.isEnabled()
    dialog.apply_button.click()
    assert applied == ["draft"]


def test_review_comparison_reports_split_merge_and_effective_model(qtbot: QtBot) -> None:
    parent = MainWindow()
    qtbot.addWidget(parent)
    candidate = {
        "arcs": [
            {
                "id": "new-arc",
                "title": "Proposed",
                "summary": "Proposed arc",
                "event_ids": ["new-a", "new-b"],
            }
        ],
        "events": [
            {
                "id": "new-a",
                "title": "Part one",
                "summary": "Split first",
                "beat_ids": ["a"],
            },
            {
                "id": "new-b",
                "title": "Part two",
                "summary": "Merged rest",
                "beat_ids": ["b", "c", "d"],
            },
        ],
        "claims": [],
        "ungrouped_beat_ids": [],
    }
    draft = OrganizationDraft("draft", "run", "generation", "pending", candidate, "utc", None)
    run = OrganizationRun(
        "run",
        "codex_lmstudio",
        "balanced",
        "resolved-model-id",
        "prompt-v1",
        "schema-v1",
        "generation",
        "completed",
        "utc",
        "utc",
        1250,
        {"cache_hits": 2, "provider_calls": 0},
        None,
    )
    current = (
        StoryEvent("old-a", "Old A", "", 0, "ai", False, False, "approved", False, ("a", "b")),
        StoryEvent("old-b", "Old B", "", 1, "ai", False, False, "approved", False, ("c", "d")),
    )

    dialog = DraftReviewDialog(draft, run, (), current, (), parent)
    qtbot.addWidget(dialog)

    assert "Split 1" in dialog.comparison_summary.text()
    assert "Merged 1" in dialog.comparison_summary.text()
    assert "resolved-model-id" in dialog.provider_metadata.text()
    assert "Profile: balanced" in dialog.provider_metadata.text()
    assert "Cache hits: 2" in dialog.provider_metadata.text()


def test_restore_story_state_respects_saved_level_and_valid_ids(qtbot: QtBot) -> None:
    canvas = GraphCanvas()
    navigator = QListWidget()
    inspector = InspectorTabs()
    stack = QStackedWidget()
    stack.addWidget(canvas)
    evidence = QListWidget()
    stack.addWidget(evidence)
    for widget in (canvas, navigator, inspector, stack):
        qtbot.addWidget(widget)
    presenter = AcceptedStoryPresenter(canvas, navigator, inspector, stack, evidence)
    arc = StoryArc(
        "arc", "Opening", "Overview", 0, "ai", False, False, "approved", False, ("event",)
    )
    event = StoryEvent(
        "event", "Choice", "Choose", 0, "ai", False, False, "approved", False, ("beat",)
    )
    other_arc = StoryArc(
        "other-arc",
        "Elsewhere",
        "Other overview",
        1,
        "ai",
        False,
        False,
        "approved",
        False,
        ("other-event",),
    )
    other_event = StoryEvent(
        "other-event",
        "Elsewhere event",
        "Other event",
        1,
        "ai",
        False,
        False,
        "approved",
        False,
        ("other-beat",),
    )
    presenter._snapshot = StorySnapshot(
        (arc, other_arc), (event, other_event), (), (), (), (), None, None
    )
    presenter._active = True

    presenter.restore_story_state("arc", "event", 1)
    assert canvas.semantic_level is SemanticLevel.OVERVIEW
    assert canvas.rendered_node_ids == ("arc", "other-arc")
    presenter.restore_story_state("arc", "event", 2)
    assert canvas.semantic_level is SemanticLevel.EVENTS
    assert canvas.rendered_node_ids == ("event",)
    captured: list[str] = []
    presenter._session = object()  # type: ignore[assignment]
    presenter.show_evidence = captured.append  # type: ignore[method-assign]
    presenter.restore_story_state("arc", "event", 3)
    assert captured == ["event"]
    presenter.restore_story_state("missing", "missing", 2)
    assert canvas.semantic_level is SemanticLevel.OVERVIEW
    presenter.restore_story_state("arc", "other-event", 2)
    assert canvas.semantic_level is SemanticLevel.EVENTS
    assert canvas.rendered_node_ids == ("event",)
    assert presenter.selected_event_id is None

    presenter.set_project(None)
    assert presenter.selected_arc_id is None
    assert presenter.selected_event_id is None
    assert canvas.rendered_node_ids == ()


def test_choice_input_keeps_all_explicit_captions_conditions_and_speakers() -> None:
    node = PresentationNode(
        "beat",
        PresentationLevel.EVIDENCE,
        "group",
        "choice",
        "Choice",
        "story.rpy",
        10,
        14,
        False,
        False,
        0,
        {
            "content": [
                {"speaker": "Alice", "text": "Choose."},
                {"speaker": "Bob", "text": "Carefully."},
            ],
            "choices": [
                {
                    "caption": "Take the path",
                    "condition": "trust >= 2",
                    "speaker": "Cara",
                },
                {"caption": "Stay behind", "condition": "not ready"},
            ],
            "branches": [
                {"condition": "flag", "content": [{"character": "Dan"}]},
                {"condition": "not flag"},
            ],
            "condition": "chapter == 1",
        },
    )

    text, speaker, speaker_names, condition = _node_story_text(node, ())

    assert speaker == "Alice"
    assert speaker_names == ("Alice", "Bob", "Cara", "Dan")
    for expected in (
        "Alice",
        "Bob",
        "Take the path",
        "Stay behind",
    ):
        assert expected in text
    assert condition == "trust >= 2\nnot ready\nflag\nnot flag\nchapter == 1"


def test_arc_stage_batches_large_event_sets_and_reconciles_membership() -> None:
    events = [
        _EventCandidate(
            f"event-{index:03d}",
            f"Event {index}",
            "Bounded summary",
            (f"beat-{index:03d}",),
            (),
            "supporting",
            (),
            (),
            (),
            (),
        )
        for index in range(121)
    ]
    requests: list[OrganizationRequest] = []

    def execute(request: OrganizationRequest, _percent: int, _label: str) -> Any:
        requests.append(request)
        return _validated_result(request, list(request.constraints.ordered_member_ids))

    result = _organize_arcs("run", events, [], execute)

    assert len(requests) == 3
    assert all(_complete_prompt_chars(request) <= 48_000 for request in requests)
    assert len(result.groups) == 1
    assert result.groups[0].member_ids == tuple(event.id for event in events)


def test_arc_stage_recursively_bounds_second_level_reconciliation() -> None:
    events = [
        _EventCandidate(
            f"event-{index:04d}",
            f"Event {index}",
            "S" * 320,
            (f"beat-{index:04d}",),
            (),
            "supporting",
            (),
            (),
            (),
            (),
        )
        for index in range(2_401)
    ]
    requests: list[OrganizationRequest] = []
    large_outcomes = tuple(f"{index:02d}-" + "O" * 316 for index in range(20))

    def execute(request: OrganizationRequest, _percent: int, _label: str) -> Any:
        requests.append(request)
        result = _validated_result(request, list(request.constraints.ordered_member_ids))
        groups = tuple(
            replace(group, summary="R" * 320, outcomes=large_outcomes)
            for group in result.groups
        )
        return replace(result, groups=groups)

    result = _organize_arcs("run", events, [], execute)

    assert len(requests) > 22
    assert all(_complete_prompt_chars(request) <= 48_000 for request in requests)
    assert result.groups[0].member_ids == tuple(event.id for event in events)


def test_single_arc_batch_recurses_until_overview_is_at_most_twelve_groups() -> None:
    events = [
        _EventCandidate(
            f"event-{index:03d}",
            f"Event {index}",
            "Summary",
            (f"beat-{index:03d}",),
            (),
            "supporting",
            (),
            (),
            (),
            (),
        )
        for index in range(30)
    ]
    requests: list[OrganizationRequest] = []

    def execute(request: OrganizationRequest, _percent: int, _label: str) -> Any:
        requests.append(request)
        members = list(request.constraints.ordered_member_ids)
        base = _validated_result(request, members)
        if len(members) <= 12:
            return base
        template = base.groups[0]
        groups = tuple(
            replace(
                template,
                id=f"paired-{index}",
                member_ids=tuple(members[index : index + 2]),
            )
            for index in range(0, len(members), 2)
        )
        return replace(base, groups=groups)

    result = _organize_arcs("run", events, [], execute)

    assert len(requests) == 2
    assert len(result.groups) == 8
    assert tuple(
        member for group in result.groups for member in group.member_ids
    ) == tuple(event.id for event in events)
    assert all(_complete_prompt_chars(request) <= 48_000 for request in requests)


def test_arc_reconciliation_no_progress_falls_back_without_hidden_extra_arcs() -> None:
    events = [
        _EventCandidate(
            f"event-{index:03d}",
            f"Event {index}",
            "Summary",
            (f"beat-{index:03d}",),
            (),
            "supporting",
            (),
            (),
            (),
            (),
        )
        for index in range(20)
    ]
    requests: list[OrganizationRequest] = []

    def execute(request: OrganizationRequest, _percent: int, _label: str) -> Any:
        requests.append(request)
        members = list(request.constraints.ordered_member_ids)
        base = _validated_result(request, members)
        template = base.groups[0]
        groups = tuple(
            replace(template, id=f"singleton-{index}", member_ids=(member,))
            for index, member in enumerate(members)
        )
        return replace(base, groups=groups)

    result = _organize_arcs("run", events, [], execute)

    assert len(requests) == 1
    assert result.groups == ()
    assert result.ungrouped_ids == tuple(event.id for event in events)


def test_all_ungrouped_arc_batches_remain_explicit_fallback() -> None:
    events = [
        _EventCandidate(
            f"event-{index:03d}",
            f"Event {index}",
            "Summary",
            (f"beat-{index:03d}",),
            (),
            "supporting",
            (),
            (),
            (),
            (),
        )
        for index in range(121)
    ]
    requests: list[OrganizationRequest] = []

    def execute(request: OrganizationRequest, _percent: int, _label: str) -> Any:
        requests.append(request)
        result = _validated_result(request, list(request.constraints.ordered_member_ids))
        ungrouped = tuple(request.constraints.ordered_member_ids)
        return replace(
            result,
            groups=(),
            ungrouped_ids=ungrouped,
            raw_normalized={
                "stage": request.stage.value,
                "groups": [],
                "ungrouped_ids": list(ungrouped),
            },
        )

    result = _organize_arcs("run", events, [], execute)

    assert len(requests) == 2
    assert result.groups == ()
    assert result.ungrouped_ids == tuple(event.id for event in events)


def test_all_ungrouped_event_scope_skips_empty_reconciliation_and_arc_calls() -> None:
    request = OrganizationRequest(
        "run",
        "chunk",
        "scope",
        OrganizationStage.EVENTS,
        {"scene_id": "scene", "beats": []},
        OrganizationConstraints(("beat",), frozenset({"beat"})),
    )
    result = OrganizationChunkResult(
        OrganizationStage.EVENTS,
        (),
        ("beat",),
        {"stage": "events", "groups": [], "ungrouped_ids": ["beat"]},
    )

    def execute(*_args: object) -> Any:
        raise AssertionError("An empty provider request must not be made")

    events, ungrouped, connectivity = _reconcile_events(
        "run", ((request, result),), execute
    )
    arcs = _organize_arcs("run", events, connectivity, execute)

    assert events == []
    assert ungrouped == {"beat"}
    assert connectivity == []
    assert arcs.groups == ()
    assert arcs.ungrouped_ids == ()


def test_accepted_event_enrichment_is_visible_in_card_and_inspector(qtbot: QtBot) -> None:
    canvas = GraphCanvas()
    navigator = QListWidget()
    inspector = InspectorTabs()
    stack = QStackedWidget()
    stack.addWidget(canvas)
    evidence = QListWidget()
    stack.addWidget(evidence)
    for widget in (canvas, navigator, inspector, stack):
        qtbot.addWidget(widget)
    presenter = AcceptedStoryPresenter(canvas, navigator, inspector, stack, evidence)
    arc = StoryArc(
        "arc", "Opening", "Overview", 0, "ai", False, False, "approved", False, ("event",)
    )
    event = StoryEvent(
        "event", "Choice", "Choose", 0, "ai", False, False, "approved", False, ("beat",)
    )
    enrichment = SimpleNamespace(
        target_kind="event",
        target_id="event",
        characters=("Alice", "Bob"),
        importance="major",
        outcomes=("A route opens",),
        promoted_fact_ids=(),
        warnings=("Interpretive title",),
    )
    presenter._snapshot = StorySnapshot(
        (arc,), (event,), (), (), (), (), None, None, enrichments=(enrichment,)
    )
    presenter._active = True

    presenter.show_arc("arc")
    detail = canvas._node_items["event"].spec.detail
    presenter._selected("event")

    assert "Major" in detail
    assert "Characters: Alice, Bob" in detail
    assert "Outcomes: 1" in detail
    assert "Outcome  •  A route opens" in [
        inspector.state.item(index).text() for index in range(inspector.state.count())
    ]
    assert "Warning  •  Interpretive title" in [
        inspector.state.item(index).text() for index in range(inspector.state.count())
    ]
    assert "Importance: major" in inspector.details.text()
    assert presenter.search("alice")
    assert canvas.rendered_node_ids == ("arc",)
