"""Independent M07.1 regression evidence for unresolved acceptance defects."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from renpy_story_mapper.m07_workflow import M07WorkflowService, _ValidatingProvider
from renpy_story_mapper.organization.contracts import (
    M05_CLOUD_MODEL,
    OrganizationChunkResult,
    OrganizationConstraints,
    OrganizationGroup,
    OrganizationRequest,
    OrganizationStage,
    ProviderAttemptUsage,
    serialize_organization_prompt,
)
from renpy_story_mapper.organization.parallel import (
    BudgetPolicy,
    InMemoryCheckpointSink,
    ParallelOrganizationScheduler,
    RouteScope,
    SchedulerConfig,
)
from renpy_story_mapper.project import PayloadRecord, Project, create_ingested_project


def _request() -> OrganizationRequest:
    return OrganizationRequest(
        run_id="review-run",
        chunk_id="review-chunk",
        scope_id="review-scope",
        stage=OrganizationStage.EVENTS,
        payload={"nodes": [{"id": "node-1"}]},
        constraints=OrganizationConstraints(
            ordered_member_ids=("node-1",),
            required_member_ids=frozenset({"node-1"}),
        ),
        cloud_consent_run_id="review-run",
        model=M05_CLOUD_MODEL,
    )


def _result() -> OrganizationChunkResult:
    group = OrganizationGroup(
        id="group-1",
        title="Review",
        summary="Validated review result.",
        member_ids=("node-1",),
        characters=(),
        importance="supporting",
        outcomes=(),
        promoted_fact_ids=(),
        claims=(),
        warnings=(),
    )
    raw = {
        "stage": "events",
        "groups": [
            {
                "id": group.id,
                "title": group.title,
                "summary": group.summary,
                "member_ids": list(group.member_ids),
                "characters": [],
                "importance": group.importance,
                "outcomes": [],
                "promoted_fact_ids": [],
                "claims": [],
                "warnings": [],
            }
        ],
        "ungrouped_ids": [],
    }
    return OrganizationChunkResult(OrganizationStage.EVENTS, (group,), (), raw)


def test_hard_token_budget_rejects_an_attempt_that_can_report_above_its_reservation() -> None:
    class Provider:
        def __init__(self) -> None:
            self.gate: Any = None
            self.observer: Any = None

        def set_attempt_gate(self, gate: Any) -> None:
            self.gate = gate

        def set_attempt_observer(self, observer: Any) -> None:
            self.observer = observer

        def set_maximum_output_bytes(self, _maximum: int) -> None:
            return

        def status(self) -> Any:
            raise AssertionError("not used")

        def cancel(self) -> None:
            return

        def organize(self, request: Any, _progress: Any, _cancelled: Any) -> Any:
            prompt = serialize_organization_prompt(request, repair=False).encode("utf-8")
            assert self.gate(prompt)
            self.observer(ProviderAttemptUsage(1, 1, "validated", 100_000, 1))
            return _result()

    budget = BudgetPolicy(hard_calls=1, hard_tokens=70_000, hard_seconds=30)
    outcome = ParallelOrganizationScheduler(
        lambda _scope: Provider(),
        InMemoryCheckpointSink(),
        SchedulerConfig(initial_workers=1, budget=budget),
    ).run((RouteScope(0, _request()),), consent_run_id="review-run")

    assert outcome.progress.input_tokens + outcome.progress.output_tokens <= 70_000


def test_transmission_guard_runs_before_every_provider_attempt() -> None:
    blocked = False
    guard_calls = 0
    transmissions = 0

    def guard() -> None:
        nonlocal guard_calls
        guard_calls += 1
        if blocked:
            raise ValueError("recovered-source transmission is now blocked")

    class RepairingProvider:
        def status(self) -> Any:
            raise AssertionError("not used")

        def cancel(self) -> None:
            return

        def organize(self, _request: Any, _progress: Any, _cancelled: Any) -> Any:
            nonlocal blocked, transmissions
            transmissions += 1
            blocked = True
            transmissions += 1
            return _result()

    wrapped = _ValidatingProvider(RepairingProvider(), guard)
    wrapped.organize(_request(), lambda _percent, _status: None, lambda: False)

    assert guard_calls == transmissions


def _branching_project(tmp_path: Path) -> Path:
    source = tmp_path / "game" / "routes.rpy"
    source.parent.mkdir()
    choices = "\n".join(
        f'        "Route {index:02d}":\n            jump ending_{index:02d}'
        for index in range(16)
    )
    endings = "\n\n".join(
        f'label ending_{index:02d}:\n    "Ending {index:02d}."\n    return'
        for index in range(16)
    )
    source.write_text(f"label start:\n    menu:\n{choices}\n\n{endings}\n", encoding="utf-8")
    project_path = tmp_path / "review.rsmproj"
    create_ingested_project(project_path, source.parent).close()
    return project_path


def test_every_detail_evidence_record_has_a_qualified_source_line(tmp_path: Path) -> None:
    service = M07WorkflowService(_branching_project(tmp_path), lambda _scope: None)  # type: ignore[arg-type,return-value]
    page = service.route_map(limit=30, edge_limit=180)
    missing: list[str] = []
    for element in [*page["nodes"], *page["edges"]]:  # type: ignore[misc]
        detail = service.detail(str(element["id"]))
        for evidence in detail["evidence"]:  # type: ignore[union-attr]
            if not (
                evidence.get("source_path")
                and isinstance(evidence.get("start_line"), int)
                and evidence.get("line_basis")
            ):
                missing.append(str(evidence.get("id")))

    assert missing == []


def test_route_page_does_not_expand_all_off_page_lanes(tmp_path: Path) -> None:
    project_path = _branching_project(tmp_path)
    with Project.open(project_path) as project:
        route = project.payload("m07_route_map", "authoritative")
        assert isinstance(route, dict)
        template = route["nodes"][0]  # type: ignore[index]
        route["nodes"] = [
            {
                **deepcopy(template),
                "id": f"node-{index}",
                "order": index,
                "lane_id": f"lane-{index}",
                "lane_kind": "persistent",
            }
            for index in range(500)
        ]
        route["edges"] = []
        route["scopes"] = []
        route["initial_node_ids"] = [f"node-{index}" for index in range(30)]
        project.write_payloads(
            (
                PayloadRecord(
                    "m07_route_map",
                    "authoritative",
                    route,
                    tuple(source.path for source in project.sources()),
                ),
            )
        )

    page = M07WorkflowService(project_path, lambda _scope: None).route_map(limit=30)  # type: ignore[arg-type,return-value]
    assert len(page["lanes"]) <= len(page["nodes"])  # type: ignore[arg-type]
