from __future__ import annotations

import shutil
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import pytest

import renpy_story_mapper.organization.chunking as chunking_module
from renpy_story_mapper import storage
from renpy_story_mapper.organization.contracts import (
    CodexMode,
    OrganizationConstraints,
    OrganizationRequest,
    OrganizationStage,
    ProviderState,
    ProviderStatus,
)
from renpy_story_mapper.organization.errors import (
    InvalidProviderOutputError,
    OrganizationCancelledError,
    ProviderTimeoutError,
)
from renpy_story_mapper.organization.validation import validate_result
from renpy_story_mapper.organization_workflow import (
    OrganizationOptions,
    OrganizationWorkflow,
    _collapsed_event_connectivity,
    _complete_prompt_chars,
    _deterministic_fallback_result,
    _EventCandidate,
    _provider_kind,
    _reconcile_events,
    _reconcile_scene_events,
    collect_organization_input,
    resolve_organization_scopes,
)
from renpy_story_mapper.presentation import (
    Continuation,
    EvidenceRecord,
    FactRecord,
    PresentationEdge,
    PresentationLevel,
    PresentationNode,
    PresentationPage,
    PresentationService,
)
from renpy_story_mapper.project import Project, create_project

FIXTURE = Path(__file__).parent / "fixtures" / "m04" / "presentation"


def _create(tmp_path: Path) -> Path:
    source = tmp_path / "game"
    shutil.copytree(FIXTURE, source)
    project_path = tmp_path / "story.rsmproj"
    create_project(project_path, source).close()
    return project_path


def test_bulk_evidence_and_facts_are_exact_indexed_and_noise_independent(
    tmp_path: Path,
) -> None:
    project_path = _create(tmp_path)
    with PresentationService.open(project_path) as service:
        connection = service._project._require_open()
        count = 10_000
        node_rows = [
            (
                f"scale-beat-{index:05d}",
                3,
                "scale-event",
                f"8{index:011d}",
                "narrative",
                f"Scale beat {index}",
                "scale.rpy",
                index + 1,
                index + 1,
                0,
                storage.canonical_json({"source_text": f"Scale beat {index}"}),
            )
            for index in range(count)
        ]
        evidence_rows = [
            (
                f"scale-evidence-{index:05d}",
                f"scale-beat-{index:05d}",
                f"8{index:011d}",
                "narrative",
                "scale.rpy",
                index + 1,
                index + 1,
                f"Evidence {index}",
                storage.canonical_json({"ordinal": index}),
            )
            for index in range(count)
        ]
        fact_rows = [
            (
                f"scale-fact-{index:05d}",
                f"scale-beat-{index:05d}",
                "gate",
                "flag",
                "story",
                "resolved",
                f"flag == {index}",
                "scale.rpy",
                index + 1,
                index + 1,
                f"8{index:011d}",
                storage.canonical_json({"normalized_value": index}),
            )
            for index in range(count)
        ]
        edge_rows = [
            (
                f"scale-edge-{index:05d}",
                3,
                f"scale-beat-{index:05d}",
                f"scale-beat-{index + 1:05d}",
                f"8{index:011d}",
                "flow",
                storage.canonical_json({"ordinal": index}),
            )
            for index in range(600)
        ]
        with storage.transaction(connection):
            connection.executemany(
                "INSERT INTO presentation_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                node_rows,
            )
            connection.executemany(
                "INSERT INTO presentation_evidence VALUES (?,?,?,?,?,?,?,?,?)",
                evidence_rows,
            )
            connection.executemany(
                "INSERT INTO presentation_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                fact_rows,
            )
            connection.executemany(
                "INSERT INTO presentation_edges VALUES (?,?,?,?,?,?,?)", edge_rows
            )

        selected = (
            "scale-beat-00017",
            "scale-beat-05000",
            "scale-beat-09999",
        )
        started = time.perf_counter()
        evidence = service.evidence_for_nodes(selected)
        facts = service.facts_for_nodes(selected)
        elapsed = time.perf_counter() - started

        assert tuple(record.node_id for record in evidence) == selected
        assert tuple(record.node_id for record in facts) == selected
        assert elapsed < 5.0

        connection.execute(
            "CREATE TEMP TABLE scale_selected(node_id TEXT PRIMARY KEY) WITHOUT ROWID"
        )
        connection.executemany(
            "INSERT INTO scale_selected VALUES (?)", ((node_id,) for node_id in selected)
        )
        evidence_plan = connection.execute(
            """EXPLAIN QUERY PLAN SELECT evidence.* FROM scale_selected selected
               CROSS JOIN presentation_evidence evidence
                 INDEXED BY presentation_evidence_node_idx
                 ON evidence.node_id=selected.node_id
               ORDER BY evidence.sort_key,evidence.evidence_id"""
        ).fetchall()
        fact_plan = connection.execute(
            """EXPLAIN QUERY PLAN SELECT fact.* FROM scale_selected selected
               CROSS JOIN presentation_facts fact INDEXED BY presentation_facts_node_idx
                 ON fact.node_id=selected.node_id
               ORDER BY fact.sort_key,fact.fact_id"""
        ).fetchall()
        connection.execute("DROP TABLE scale_selected")
        assert any("presentation_evidence_node_idx" in str(row[3]) for row in evidence_plan)
        assert any("presentation_facts_node_idx" in str(row[3]) for row in fact_plan)

        with pytest.raises(ValueError, match="unknown Level-3"):
            service.evidence_for_nodes((*selected, "missing-beat"))
        with pytest.raises(ValueError, match="unknown Level-3"):
            service.facts_for_nodes((*selected, "missing-beat"))
        with pytest.raises(ValueError, match="non-empty strings"):
            service.evidence_for_nodes((selected[0], 7))  # type: ignore[arg-type]
        assert connection.execute(
            """SELECT 1 FROM sqlite_temp_schema
               WHERE name IN ('selected_presentation_evidence_nodes',
                              'selected_presentation_fact_nodes')"""
        ).fetchone() is None

        all_node_ids = tuple(row[0] for row in node_rows)
        checks = 0

        def cancel_evidence() -> bool:
            nonlocal checks
            checks += 1
            return checks >= 3

        with pytest.raises(storage.ProjectOperationCancelled):
            service.evidence_for_nodes(all_node_ids, cancelled=cancel_evidence)
        checks = 0
        with pytest.raises(storage.ProjectOperationCancelled):
            service.facts_for_nodes(all_node_ids, cancelled=cancel_evidence)
        edge_scan_started = False

        def trace_edge_scan(statement: str) -> None:
            nonlocal edge_scan_started
            if "FROM selected_presentation_nodes source" in statement:
                edge_scan_started = True

        def cancel_edges_during_scan() -> bool:
            return edge_scan_started

        connection.set_trace_callback(trace_edge_scan)
        try:
            with pytest.raises(storage.ProjectOperationCancelled):
                service.edges_for_nodes(
                    PresentationLevel.EVIDENCE,
                    all_node_ids,
                    cancelled=cancel_edges_during_scan,
                )
        finally:
            connection.set_trace_callback(None)
        assert edge_scan_started
        assert connection.execute(
            """SELECT 1 FROM sqlite_temp_schema
               WHERE name IN ('selected_presentation_evidence_nodes',
                              'selected_presentation_fact_nodes',
                              'selected_presentation_nodes')"""
        ).fetchone() is None


class _PagedOverviewPresentation:
    def __init__(self, count: int) -> None:
        self.count = count
        self.calls = 0

    def view(self, request: Any) -> PresentationPage:
        assert request.level is PresentationLevel.OVERVIEW
        self.calls += 1
        start = 0 if request.after is None else int(request.after)
        stop = min(self.count, start + 80)
        nodes = tuple(
            PresentationNode(
                f"scope-{index:03d}",
                PresentationLevel.OVERVIEW,
                None,
                "label",
                f"Scope {index}",
                "story.rpy",
                index + 1,
                index + 1,
                False,
                True,
                1,
                {},
            )
            for index in range(start, stop)
        )
        return PresentationPage(
            nodes,
            (),
            Continuation(len(nodes), stop < self.count, str(stop) if stop < self.count else None),
            Continuation(0, False, None),
        )


class _PresentationProject:
    def __init__(self, presentation: Any) -> None:
        self.presentation = presentation

    def presentation_service(self) -> Any:
        return self.presentation


def test_empty_scope_selection_resolves_every_visible_overview_page() -> None:
    presentation = _PagedOverviewPresentation(181)
    project = _PresentationProject(presentation)

    resolved = resolve_organization_scopes(
        cast(Project, project), (), lambda: False
    )

    assert resolved == tuple(f"scope-{index:03d}" for index in range(181))
    assert presentation.calls == 3
    assert resolve_organization_scopes(
        cast(Project, project), ("scope-090",), lambda: False
    ) == ("scope-090",)
    assert presentation.calls == 3


class _LocalSyntheticProvider:
    def __init__(self) -> None:
        self.requests: list[OrganizationRequest] = []

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            ProviderState.READY,
            "synthetic-codex",
            "test",
            model_identifier="synthetic-local-model",
        )

    def organize(
        self,
        request: OrganizationRequest,
        _progress: Any,
        _cancelled: Any,
    ) -> Any:
        self.requests.append(request)
        members = list(request.constraints.ordered_member_ids)
        groups = []
        if members:
            groups.append(
                {
                    "id": f"{request.stage.value}-group",
                    "title": f"{request.stage.value.title()} group",
                    "summary": "Synthetic full-game organization.",
                    "member_ids": members,
                    "characters": [],
                    "importance": "supporting",
                    "outcomes": [],
                    "promoted_fact_ids": [],
                    "claims": [],
                    "warnings": [],
                }
            )
        return validate_result(
            {
                "stage": request.stage.value,
                "groups": groups,
                "ungrouped_ids": [],
            },
            request,
        )

    def cancel(self) -> None:
        pass


class _RejectingStageProvider(_LocalSyntheticProvider):
    def __init__(self, rejected_stage: OrganizationStage) -> None:
        super().__init__()
        self.rejected_stage = rejected_stage

    def organize(
        self,
        request: OrganizationRequest,
        progress: Any,
        cancelled: Any,
    ) -> Any:
        if request.stage is self.rejected_stage:
            self.requests.append(request)
            raise InvalidProviderOutputError(
                "The organizer returned invalid structured output twice."
            )
        return super().organize(request, progress, cancelled)


def test_workflow_empty_scope_runs_full_game_and_persists_only_covered_scopes(
    tmp_path: Path,
) -> None:
    project_path = _create(tmp_path)
    with Project.open(project_path) as project:
        all_scopes = resolve_organization_scopes(project, (), lambda: False)
        beats, _ = collect_organization_input(project, all_scopes, lambda: False)
        expected_scopes = tuple(dict.fromkeys(beat.scene_id for beat in beats))
        provider = _LocalSyntheticProvider()

        result = OrganizationWorkflow(project, lambda _mode: provider).organize(
            (),
            OrganizationOptions(mode=CodexMode.CODEX_LMSTUDIO, model=None),
            progress=lambda _percent, _status: None,
            cancelled=lambda: False,
        )

        draft = next(
            item
            for item in project.organization_service().drafts(status="pending")
            if item.id == result.draft_id
        )
        assert isinstance(draft.candidate, dict)
        scope = draft.candidate["_scope"]
        assert isinstance(scope, dict)
        assert tuple(scope["scope_ids"]) == expected_scopes
        assert expected_scopes
        assert set(expected_scopes).issubset(all_scopes)
        assert {request.stage for request in provider.requests} == {
            OrganizationStage.EVENTS,
            OrganizationStage.ARCS,
        }


@pytest.mark.parametrize(
    "rejected_stage",
    [
        OrganizationStage.EVENTS,
        OrganizationStage.RECONCILE,
        OrganizationStage.ARCS,
    ],
)
def test_twice_invalid_provider_chunk_is_recorded_as_deterministic_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rejected_stage: OrganizationStage,
) -> None:
    if rejected_stage is OrganizationStage.RECONCILE:
        monkeypatch.setattr(chunking_module, "MAX_ASSIGNED_BEATS", 1)
    project_path = _create(tmp_path)
    with Project.open(project_path) as project:
        provider = _RejectingStageProvider(rejected_stage)

        result = OrganizationWorkflow(project, lambda _mode: provider).organize(
            (),
            OrganizationOptions(mode=CodexMode.CODEX_LMSTUDIO, model=None),
            progress=lambda _percent, _status: None,
            cancelled=lambda: False,
        )

        run = next(
            item
            for item in project.organization_service().runs()
            if item.id == result.run_id
        )
        rejected = [
            chunk
            for chunk in project.organization_service().chunks(result.run_id)
            if chunk.status == "rejected"
        ]
        assert run.status == "completed"
        assert rejected
        assert all(chunk.cache_state == "bypassed" for chunk in rejected)
        assert all(chunk.cache_key is None for chunk in rejected)
        for chunk in rejected:
            assert isinstance(chunk.result, dict)
            assert chunk.result["stage"] == rejected_stage.value
            assert chunk.result["groups"] == []
            assert chunk.result["ungrouped_ids"]
        draft = next(
            item
            for item in project.organization_service().drafts(status="pending")
            if item.id == result.draft_id
        )
        assert isinstance(draft.candidate, dict)


def test_non_validation_provider_failure_still_aborts_without_draft(
    tmp_path: Path,
) -> None:
    class TimeoutProvider(_LocalSyntheticProvider):
        def organize(
            self,
            request: OrganizationRequest,
            progress: Any,
            cancelled: Any,
        ) -> Any:
            del request, progress, cancelled
            raise ProviderTimeoutError("The organizer timed out safely.")

    project_path = _create(tmp_path)
    with Project.open(project_path) as project:
        with pytest.raises(ProviderTimeoutError):
            OrganizationWorkflow(project, lambda _mode: TimeoutProvider()).organize(
                (),
                OrganizationOptions(mode=CodexMode.CODEX_LMSTUDIO, model=None),
                progress=lambda _percent, _status: None,
                cancelled=lambda: False,
            )
        assert project.organization_service().drafts(status="pending") == ()
        assert project.organization_service().runs()[-1].status == "failed"


class _BulkCollectionPresentation:
    events_per_scope = 2

    def __init__(self) -> None:
        self.parent_widths: list[tuple[PresentationLevel, int]] = []
        self.bulk_calls: list[tuple[str, int]] = []

    def view(self, request: Any) -> PresentationPage:
        parents = tuple(request.parent_ids)
        self.parent_widths.append((request.level, len(parents)))
        if request.level is PresentationLevel.EVENT:
            nodes = tuple(
                PresentationNode(
                    f"event-{scope}-{event_number}",
                    PresentationLevel.EVENT,
                    scope,
                    "structural_group",
                    f"Event {scope} {event_number}",
                    "story.rpy",
                    int(scope.rsplit("-", 1)[1]) * self.events_per_scope
                    + event_number
                    + 1,
                    int(scope.rsplit("-", 1)[1]) * self.events_per_scope
                    + event_number
                    + 1,
                    False,
                    True,
                    1,
                    {},
                )
                for scope in parents
                for event_number in range(self.events_per_scope)
            )
        else:
            nodes = tuple(
                PresentationNode(
                    f"beat-{event_id}",
                    PresentationLevel.EVIDENCE,
                    event_id,
                    "narrative",
                    f"Beat {event_id}",
                    "story.rpy",
                    index + 1,
                    index + 1,
                    False,
                    False,
                    0,
                    {"source_text": f"Beat {event_id}"},
                )
                for index, event_id in enumerate(parents)
            )
        if nodes:
            nodes = (*nodes, nodes[-1])
        return PresentationPage(
            nodes,
            (),
            Continuation(len(nodes), False, None),
            Continuation(0, False, None),
        )

    def edges_for_nodes(
        self,
        _level: PresentationLevel,
        _node_ids: Sequence[str],
        **_kwargs: object,
    ) -> tuple[PresentationEdge, ...]:
        return ()

    def evidence_for_nodes(
        self, node_ids: Sequence[str], **_kwargs: object
    ) -> tuple[EvidenceRecord, ...]:
        self.bulk_calls.append(("evidence", len(node_ids)))
        return ()

    def facts_for_nodes(
        self, node_ids: Sequence[str], **_kwargs: object
    ) -> tuple[FactRecord, ...]:
        self.bulk_calls.append(("facts", len(node_ids)))
        return ()


def test_collection_batches_canonical_scale_parents_and_preserves_chronology() -> None:
    presentation = _BulkCollectionPresentation()
    scope_count = 2_653
    scopes = tuple(f"scope-{index:04d}" for index in range(scope_count))

    beats, facts = collect_organization_input(
        cast(Project, _PresentationProject(presentation)), scopes, lambda: False
    )

    beat_count = scope_count * presentation.events_per_scope
    assert len(beats) == beat_count
    assert facts == ()
    expected_scenes = tuple(
        scope
        for scope in scopes
        for _event_number in range(presentation.events_per_scope)
    )
    expected_beats = tuple(
        f"beat-event-{scope}-{event_number}"
        for scope in scopes
        for event_number in range(presentation.events_per_scope)
    )
    assert tuple(beat.scene_id for beat in beats) == expected_scenes
    assert tuple(beat.id for beat in beats) == expected_beats
    event_calls = [
        width
        for level, width in presentation.parent_widths
        if level is PresentationLevel.EVENT
    ]
    evidence_calls = [
        width
        for level, width in presentation.parent_widths
        if level is PresentationLevel.EVIDENCE
    ]
    assert len(event_calls) > 1
    assert len(evidence_calls) > 1
    assert max((*event_calls, *evidence_calls)) <= 400
    assert sum(event_calls) == scope_count
    assert sum(evidence_calls) == beat_count
    assert presentation.bulk_calls == [
        ("evidence", beat_count),
        ("facts", beat_count),
    ]


def _candidate(index: int, *, outcomes: int = 5) -> _EventCandidate:
    return _EventCandidate(
        f"event-{index:04d}",
        f"Event {index}",
        "S" * 320,
        (f"beat-{index:04d}-a", f"beat-{index:04d}-b"),
        (),
        "supporting",
        tuple(f"{value:02d}-" + "O" * 317 for value in range(outcomes)),
        (),
        (),
        (),
    )


def _grouped_result(
    request: OrganizationRequest,
    *,
    leave_last_ungrouped: bool = False,
) -> Any:
    members = list(request.constraints.ordered_member_ids)
    ungrouped = [members.pop()] if leave_last_ungrouped and members else []
    groups = [members[index : index + 2] for index in range(0, len(members), 2)]
    return validate_result(
        {
            "stage": OrganizationStage.RECONCILE.value,
            "groups": [
                {
                    "id": f"group-{index}",
                    "title": "Reconciled event",
                    "summary": "Bounded reconciliation.",
                    "member_ids": membership,
                    "characters": [],
                    "importance": "supporting",
                    "outcomes": [],
                    "promoted_fact_ids": [],
                    "claims": [],
                    "warnings": [],
                }
                for index, membership in enumerate(groups)
            ],
            "ungrouped_ids": ungrouped,
        },
        request,
    )


def _stage_one_chunk(
    index: int,
    *,
    scene: str = "scene",
    outgoing: tuple[str, ...] = (),
) -> tuple[OrganizationRequest, Any]:
    beat_id = f"beat-{index}"
    request = OrganizationRequest(
        "run",
        f"events-{index}",
        "scope",
        OrganizationStage.EVENTS,
        {
            "scene_id": scene,
            "beats": [
                {
                    "id": beat_id,
                    "context_only": False,
                    "adjacent_ids": list(outgoing),
                }
            ],
        },
        OrganizationConstraints((beat_id,), frozenset({beat_id})),
    )
    result = validate_result(
        {
            "stage": OrganizationStage.EVENTS.value,
            "groups": [
                {
                    "id": f"event-{index}",
                    "title": f"Event {index}",
                    "summary": "Validated Stage-1 event.",
                    "member_ids": [beat_id],
                    "characters": [],
                    "importance": "supporting",
                    "outcomes": [],
                    "promoted_fact_ids": [],
                    "claims": [],
                    "warnings": [],
                }
            ],
            "ungrouped_ids": [],
        },
        request,
    )
    return request, result


def test_single_stage_one_chunk_skips_redundant_stage_two_call() -> None:
    stage_one = (_stage_one_chunk(1),)

    events, ungrouped, connectivity = _reconcile_events(
        "run",
        stage_one,
        lambda *_args: pytest.fail("single-chunk scene reached Stage 2"),
    )

    assert len(events) == 1
    assert events[0].beat_ids == ("beat-1",)
    assert ungrouped == set()
    assert connectivity == []


def test_multiple_stage_one_chunks_still_run_stage_two() -> None:
    calls: list[OrganizationRequest] = []

    def execute(request: OrganizationRequest, _percent: int, _label: str) -> Any:
        calls.append(request)
        return _grouped_result(request)

    events, ungrouped, _connectivity = _reconcile_events(
        "run",
        (
            _stage_one_chunk(1, outgoing=("beat-2",)),
            _stage_one_chunk(2),
        ),
        execute,
    )

    assert len(calls) == 1
    assert calls[0].stage is OrganizationStage.RECONCILE
    assert tuple(beat for event in events for beat in event.beat_ids) == (
        "beat-1",
        "beat-2",
    )
    assert ungrouped == set()


def test_collapsed_connectivity_traverses_technical_branches_and_cycles() -> None:
    events = [
        _EventCandidate("event-a", "A", "", ("beat-a",), (), "supporting", (), (), (), ()),
        _EventCandidate("event-b", "B", "", ("beat-b",), (), "supporting", (), (), (), ()),
        _EventCandidate("event-c", "C", "", ("beat-c",), (), "supporting", (), (), (), ()),
    ]
    adjacency = {
        "beat-a": ("technical-1",),
        "technical-1": ("beat-b", "technical-2"),
        "technical-2": ("technical-1", "beat-c"),
        "beat-b": (),
        "beat-c": (),
    }

    assert _collapsed_event_connectivity(events, adjacency) == [
        {"source": "event-a", "target": "event-b", "kind": "flow"},
        {"source": "event-a", "target": "event-c", "kind": "flow"},
    ]


@pytest.mark.parametrize("stage", list(OrganizationStage))
def test_deterministic_fallback_result_never_contains_provider_groups(
    stage: OrganizationStage,
) -> None:
    request = OrganizationRequest(
        "run",
        "chunk",
        "scope",
        stage,
        {},
        OrganizationConstraints(("member-a", "member-b"), frozenset({"member-a"})),
    )

    result = _deterministic_fallback_result(request)

    assert result.stage is stage
    assert result.groups == ()
    assert result.ungrouped_ids == ("member-a", "member-b")
    assert result.attempts == 2


def test_provider_kind_preserves_non_narrative_command_classification() -> None:
    command = PresentationNode(
        "beat",
        PresentationLevel.EVIDENCE,
        "event",
        "show",
        "show bg street",
        "story.rpy",
        1,
        1,
        False,
        False,
        0,
        {},
    )

    assert _provider_kind(command) == "show"


def test_stage_two_recursively_bounds_complete_prompts_and_reconciles_boundaries() -> None:
    source = [_candidate(index) for index in range(240)]
    requests: list[OrganizationRequest] = []

    def execute(request: OrganizationRequest, _percent: int, _label: str) -> Any:
        requests.append(request)
        return _grouped_result(request)

    reconciled, ungrouped = _reconcile_scene_events(
        "run", "scene", source, execute, progress_percent=50
    )

    expected_beats = tuple(beat for event in source for beat in event.beat_ids)
    actual_beats = tuple(beat for event in reconciled for beat in event.beat_ids)
    assert len(requests) > 2
    assert any(":d1:" in request.chunk_id for request in requests)
    assert all(_complete_prompt_chars(request) <= 48_000 for request in requests)
    assert actual_beats == expected_beats
    assert ungrouped == set()


def test_stage_two_no_progress_keeps_explicit_ungrouped_members_exact() -> None:
    source = [_candidate(index) for index in range(120)]
    requests: list[OrganizationRequest] = []

    def execute(request: OrganizationRequest, _percent: int, _label: str) -> Any:
        requests.append(request)
        return _grouped_result(request, leave_last_ungrouped=True)

    reconciled, ungrouped = _reconcile_scene_events(
        "run", "scene", source, execute, progress_percent=50
    )

    expected = {beat for event in source for beat in event.beat_ids}
    grouped = [beat for event in reconciled for beat in event.beat_ids]
    assert ungrouped
    assert not (set(grouped) & ungrouped)
    assert set(grouped) | ungrouped == expected
    assert len(grouped) == len(set(grouped))
    assert all(_complete_prompt_chars(request) <= 48_000 for request in requests)


def test_stage_two_partition_is_cancellable_before_provider_execution() -> None:
    source = [_candidate(index) for index in range(120)]
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 5

    with pytest.raises(OrganizationCancelledError):
        _reconcile_scene_events(
            "run",
            "scene",
            source,
            lambda *_args: pytest.fail("cancelled partition reached provider"),
            progress_percent=50,
            cancelled=cancelled,
        )
