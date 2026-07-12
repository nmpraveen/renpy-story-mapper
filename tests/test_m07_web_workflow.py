"""Focused loopback/API contracts for the integrated M07 workflow."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from renpy_story_mapper.organization.contracts import (
    M05_CLOUD_MODEL,
    CodexMode,
    OrganizationChunkResult,
    OrganizationGroup,
    ProviderExecutionMetadata,
    ProviderState,
    ProviderStatus,
)
from renpy_story_mapper.organization.errors import OrganizationCancelledError
from renpy_story_mapper.organization.parallel import BudgetPolicy, RouteScope
from renpy_story_mapper.project import Project, create_ingested_project
from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.contracts import M07_API_ROUTES


@dataclass
class _Dialogs:
    def choose_source(self, _kind: str) -> Path | None:
        return None

    def choose_open_project(self) -> Path | None:
        return None

    def choose_save_project(self) -> Path | None:
        return None


class _MockProvider:
    def __init__(self, scope: RouteScope, calls: list[tuple[int, str]]) -> None:
        self._scope = scope
        self._calls = calls

    def status(self) -> ProviderStatus:
        return ProviderStatus(ProviderState.READY, "mock", model_identifier=M05_CLOUD_MODEL)

    def organize(self, request: Any, progress: Any, cancelled: Any) -> OrganizationChunkResult:
        del progress
        assert request.model == M05_CLOUD_MODEL
        assert request.cloud_consent_run_id == request.run_id
        assert not cancelled()
        self._calls.append((threading.get_ident(), request.scope_id))
        members = tuple(request.constraints.ordered_member_ids)
        group = OrganizationGroup(
            id=f"group_{request.scope_id}",
            title=f"Named {request.scope_id}",
            summary="Evidence-bounded interpretation.",
            member_ids=members,
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
                    "member_ids": list(members),
                    "characters": [],
                    "importance": "supporting",
                    "outcomes": [],
                    "promoted_fact_ids": [],
                    "claims": [],
                    "warnings": [],
                }
            ],
            "ungrouped_ids": [],
        }
        return OrganizationChunkResult(
            request.stage,
            (group,),
            (),
            raw,
            metadata=ProviderExecutionMetadata(
                CodexMode.CODEX_CHATGPT,
                M05_CLOUD_MODEL,
                "mock",
                5,
                "a" * 64,
                "b" * 64,
                20,
                5,
            ),
        )

    def cancel(self) -> None:
        return


@pytest.fixture
def m07_project(tmp_path: Path) -> Path:
    source = tmp_path / "game" / "story.rpy"
    source.parent.mkdir()
    source.write_text(
        """label start:
    $ love = 0
    menu:
        "Stay" if love >= 0:
            $ love += 1
            "A warm moment."
        "Leave":
            "A quiet exit."
    "Together again."
    return
""",
        encoding="utf-8",
    )
    destination = tmp_path / "story.rsmproj"
    create_ingested_project(destination, source.parent).close()
    return destination


def _api(project: Path, calls: list[tuple[int, str]]) -> ProjectApi:
    api = ProjectApi(_Dialogs(), m07_provider_factory=lambda scope: _MockProvider(scope, calls))
    api._project_path = project
    return api


def _wait(api: ProjectApi) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        task = api.dispatch("GET", "/api/v1/analysis/progress", {})
        assert isinstance(task, dict)
        if task.get("state") in {"completed", "failed", "cancelled"}:
            return task
        time.sleep(0.01)
    raise AssertionError("background organization did not finish")


def test_route_paging_detail_evidence_and_path_redaction(m07_project: Path) -> None:
    api = _api(m07_project, [])
    try:
        route = api.dispatch("POST", M07_API_ROUTES["route_map"], {"limit": 30})
        assert isinstance(route, dict)
        assert route["level"] == "route_map"
        assert len(route["nodes"]) <= 30
        assert len(route["initial_node_ids"]) <= 30
        assert route["totals"]["nodes"] >= len(route["nodes"])
        assert route["lines"]
        assert route["lanes"]
        serialized = str(route)
        assert str(m07_project.parent) not in serialized

        edge = next(item for item in route["lines"] if item["evidence_ids"])
        detail = api.dispatch("POST", M07_API_ROUTES["detail"], {"element_id": edge["id"]})
        assert isinstance(detail, dict)
        assert detail["level"] == "detail_evidence"
        assert detail["back_target"] == "route_map"
        assert detail["predecessor_ids"] and detail["successor_ids"]
        assert "gates" in detail and "effects" in detail
        assert detail["evidence"]
        assert str(m07_project.parent) not in str(detail)
    finally:
        api.close()


def test_prepare_is_provider_free_and_missing_or_stale_consent_is_rejected(
    m07_project: Path,
) -> None:
    constructed: list[tuple[int, str]] = []
    api = _api(m07_project, constructed)
    try:
        api.dispatch("GET", M07_API_ROUTES["organization"], {})
        prepared = api.dispatch("POST", M07_API_ROUTES["prepare"], {})
        assert isinstance(prepared, dict)
        assert prepared["model"] == {
            "id": "gpt-5.6-luna",
            "reasoning": "high",
            "fast_mode": False,
        }
        assert len(prepared["run_id"]) > 32
        assert constructed == []

        with pytest.raises(ValueError, match="confirmation"):
            api.dispatch(
                "POST",
                M07_API_ROUTES["start"],
                {"run_id": prepared["run_id"], "confirm_cloud": False},
            )
        with pytest.raises(ValueError, match="stale"):
            api.dispatch(
                "POST",
                M07_API_ROUTES["start"],
                {"run_id": "m07_stale", "confirm_cloud": True},
            )
        assert constructed == []
    finally:
        api.close()


def test_start_progress_partial_apply_and_authority_hash_unchanged(m07_project: Path) -> None:
    calls: list[tuple[int, str]] = []
    api = _api(m07_project, calls)
    try:
        before = api.dispatch("POST", M07_API_ROUTES["route_map"], {})
        assert isinstance(before, dict)
        prepared = api.dispatch(
            "POST",
            M07_API_ROUTES["prepare"],
            {"hard_calls": 1, "hard_tokens": 100_000},
        )
        assert isinstance(prepared, dict)
        started = api.dispatch(
            "POST",
            M07_API_ROUTES["start"],
            {"run_id": prepared["run_id"], "confirm_cloud": True},
        )
        assert isinstance(started, dict)
        terminal = _wait(api)
        assert terminal["state"] == "completed"
        assert calls and all(thread_id != threading.get_ident() for thread_id, _ in calls)

        status = api.dispatch("GET", M07_API_ROUTES["organization"], {})
        assert isinstance(status, dict)
        assert status["calls"] == 1
        assert status["tokens"]["total"] == 25
        assert 0 <= status["ai_coverage"] <= status["technical_coverage"] <= 1
        assert status["partial"] is True
        assert status["assemblies"]
        assembly = status["assemblies"][0]
        applied = api.dispatch(
            "POST",
            M07_API_ROUTES["assembly_apply"],
            {"assembly_id": assembly["assembly_id"]},
        )
        assert applied["status"] == "applied"
        after = api.dispatch("POST", M07_API_ROUTES["route_map"], {})
        assert after["authority_hash"] == before["authority_hash"]
        assert after["applied_assembly"]["assembly_id"] == assembly["assembly_id"]
    finally:
        api.close()


def test_close_reopen_replay_uses_zero_provider_calls(m07_project: Path) -> None:
    calls: list[tuple[int, str]] = []
    first = _api(m07_project, calls)
    prepared = first.dispatch("POST", M07_API_ROUTES["prepare"], {})
    first.dispatch(
        "POST",
        M07_API_ROUTES["start"],
        {"run_id": prepared["run_id"], "confirm_cloud": True},
    )
    assert _wait(first)["state"] == "completed"
    first.close()
    first_count = len(calls)
    assert first_count > 0

    second = _api(m07_project, calls)
    try:
        prepared = second.dispatch("POST", M07_API_ROUTES["prepare"], {})
        second.dispatch(
            "POST",
            M07_API_ROUTES["start"],
            {"run_id": prepared["run_id"], "confirm_cloud": True},
        )
        assert _wait(second)["state"] == "completed"
        assert len(calls) == first_count
        status = second.dispatch("GET", M07_API_ROUTES["organization"], {})
        assert status["scope_counts"]["validated"] == status["scope_counts"]["total"]
    finally:
        second.close()


def test_cancel_preserves_scopes_and_resume_requires_fresh_prepare(
    m07_project: Path,
) -> None:
    calls: list[tuple[int, str]] = []
    blocking = threading.Event()

    class BlockingProvider(_MockProvider):
        def organize(self, request: Any, progress: Any, cancelled: Any) -> OrganizationChunkResult:
            blocking.set()
            while not cancelled():
                time.sleep(0.005)
            raise OrganizationCancelledError("private provider detail")

    use_blocking = True

    def factory(scope: RouteScope) -> _MockProvider:
        if use_blocking:
            return BlockingProvider(scope, calls)
        return _MockProvider(scope, calls)

    api = ProjectApi(_Dialogs(), m07_provider_factory=factory)
    api._project_path = m07_project
    try:
        prepared = api.dispatch("POST", M07_API_ROUTES["prepare"], {})
        api.dispatch(
            "POST",
            M07_API_ROUTES["start"],
            {"run_id": prepared["run_id"], "confirm_cloud": True},
        )
        assert blocking.wait(timeout=3)
        api.dispatch("POST", M07_API_ROUTES["cancel"], {})
        assert _wait(api)["state"] == "cancelled"
        cancelled = api.dispatch("GET", M07_API_ROUTES["organization"], {})
        assert cancelled["scope_counts"]["cancelled"] > 0
        assert "private provider detail" not in str(cancelled)

        with pytest.raises(ValueError, match="stale"):
            api.dispatch(
                "POST",
                M07_API_ROUTES["start"],
                {"run_id": prepared["run_id"], "confirm_cloud": True},
            )
        use_blocking = False
        resumed = api.dispatch("POST", M07_API_ROUTES["prepare"], {})
        api.dispatch(
            "POST",
            M07_API_ROUTES["start"],
            {"run_id": resumed["run_id"], "confirm_cloud": True},
        )
        assert _wait(api)["state"] == "completed"
        status = api.dispatch("GET", M07_API_ROUTES["organization"], {})
        assert status["scope_counts"]["validated"] == status["scope_counts"]["total"]
    finally:
        api.close()


def test_malformed_inputs_and_unknown_ids_are_sanitized(m07_project: Path) -> None:
    api = _api(m07_project, [])
    try:
        with pytest.raises(ValueError):
            api.dispatch("POST", M07_API_ROUTES["route_map"], {"limit": 31})
        with pytest.raises(ValueError):
            api.dispatch(
                "POST", M07_API_ROUTES["prepare"], {"soft_seconds": 20, "hard_seconds": 10}
            )
        with pytest.raises(Exception) as detail_error:
            api.dispatch("POST", M07_API_ROUTES["detail"], {"element_id": "C:\\secret\\story.rpy"})
        assert "secret" not in str(detail_error.value).casefold()
    finally:
        api.close()


def test_contract_constants_are_exact() -> None:
    assert M07_API_ROUTES == {
        "route_map": "/api/v1/m07/route-map",
        "detail": "/api/v1/m07/detail",
        "organization": "/api/v1/m07/organization",
        "prepare": "/api/v1/m07/organization/prepare",
        "start": "/api/v1/m07/organization/start",
        "cancel": "/api/v1/m07/organization/cancel",
        "assembly_apply": "/api/v1/m07/assembly/apply",
    }


def test_durable_status_reopens_without_constructing_provider(m07_project: Path) -> None:
    with Project.open(m07_project) as project:
        before = project.authoritative_bytes()
    calls: list[tuple[int, str]] = []
    api = _api(m07_project, calls)
    try:
        status = api.dispatch("GET", M07_API_ROUTES["organization"], {})
        assert status["scope_counts"]["total"] > 0
        assert calls == []
    finally:
        api.close()
    with Project.open(m07_project) as project:
        assert project.authoritative_bytes() == before


def test_budget_object_is_bounded_by_scheduler_contract() -> None:
    budget = BudgetPolicy(hard_calls=1, hard_tokens=1)
    assert budget.hard_calls == 1
