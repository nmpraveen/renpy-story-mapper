"""Focused loopback/API contracts for the integrated M07 workflow."""

from __future__ import annotations

import http.client
import json
import threading
import time
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

import pytest

from renpy_story_mapper import storage
from renpy_story_mapper.organization.contracts import (
    M05_CLOUD_MODEL,
    CodexMode,
    InterpretationClaim,
    OrganizationChunkResult,
    OrganizationGroup,
    ProviderExecutionMetadata,
    ProviderState,
    ProviderStatus,
)
from renpy_story_mapper.organization.errors import OrganizationCancelledError
from renpy_story_mapper.organization.parallel import BudgetPolicy, RouteScope
from renpy_story_mapper.project import PayloadRecord, Project, create_ingested_project
from renpy_story_mapper.web.api import ApiProblem, ProjectApi
from renpy_story_mapper.web.contracts import M07_API_ROUTES
from renpy_story_mapper.web.security import SessionSecurity
from renpy_story_mapper.web.server import LocalWebServer, start_in_thread


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


def _scope_ids(project: Path) -> list[str]:
    with Project.open(project) as opened:
        route = opened.payload("m07_route_map", "authoritative")
    assert isinstance(route, dict)
    scopes = route["scopes"]
    assert isinstance(scopes, list) and scopes
    return [str(item["id"]) for item in scopes]


def _prepare(api: ProjectApi, project: Path, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"scope_ids": _scope_ids(project)}
    body.update(overrides)
    prepared = api.dispatch("POST", M07_API_ROUTES["prepare"], body)
    assert isinstance(prepared, dict)
    return prepared


def _start_body(prepared: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    body = {
        "run_id": prepared["run_id"],
        "confirm_cloud": True,
        "scope_ids": prepared["scope_ids"],
        "window_ids": prepared["window_ids"],
        "selection_hash": prepared["selection_hash"],
        "authority_hash": prepared["authority_hash"],
        "recovered_source_acknowledgement": prepared["recovered_source_acknowledgement"],
        "model": prepared["model"],
        "budgets": prepared["budgets"],
    }
    body.update(overrides)
    return body


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
        assert route["total_nodes"] == route["totals"]["nodes"]
        assert route["total_nodes"] >= len(route["nodes"])
        assert route["edges"]
        assert len(route["edges"]) <= 180
        assert len(route["nodes"]) + len(route["edges"]) <= 240
        assert route["lanes"]
        serialized = str(route)
        assert str(m07_project.parent) not in serialized

        edge = next(item for item in route["edges"] if item["evidence_ids"])
        detail = api.dispatch("POST", M07_API_ROUTES["detail"], {"element_id": edge["id"]})
        assert isinstance(detail, dict)
        assert detail["level"] == "detail_evidence"
        assert detail["back_target"] == "route_map"
        assert detail["predecessor_ids"] and detail["successor_ids"]
        assert "gates" in detail and "effects" in detail
        assert detail["evidence"]
        for record in detail["evidence"]:
            source = record["source"]
            if isinstance(source, dict):
                assert record["start_line"] == source["start"]["line"]
                assert record["end_line"] == source["end"]["line"]
                assert record["line_basis"]
                assert record["provenance"] is not None
        assert str(m07_project.parent) not in str(detail)
    finally:
        api.close()


def test_route_page_stably_caps_high_fanout_edges(m07_project: Path) -> None:
    nodes = [
        {
            "id": f"node-{index:02d}",
            "title": f"Node {index}",
            "lane_id": "spine",
            "lane_kind": "spine",
            "order": index,
            "evidence_ids": [],
        }
        for index in range(30)
    ]
    edges = [
        {
            "id": f"edge-{index:03d}",
            "source_id": "node-00",
            "target_id": f"node-{(index % 29) + 1:02d}",
            "evidence_ids": [],
            "gate_ids": [],
            "effect_ids": [],
            "source_file": str(m07_project.parent / "private" / "story.rpy"),
        }
        for index in range(300)
    ]
    with Project.open(m07_project) as project:
        sources = tuple(item.path for item in project.sources())
        project.write_payloads(
            [
                PayloadRecord(
                    "m07_route_map",
                    "authoritative",
                    {
                        "schema_version": 1,
                        "nodes": nodes,
                        "edges": edges,
                        "scopes": [],
                        "coverage": {
                            "control_nodes": 30,
                            "visible_nodes": 30,
                            "technical_nodes": 0,
                            "unresolved_nodes": 0,
                            "corridor_count": 0,
                        },
                        "initial_node_ids": [item["id"] for item in nodes],
                        "evidence": [],
                    },
                    sources,
                )
            ]
        )
    api = _api(m07_project, [])
    static_root = Path(__file__).parents[1] / "src" / "renpy_story_mapper" / "web" / "static"
    server = LocalWebServer(
        "127.0.0.1",
        0,
        api,
        static_root=static_root,
        security=SessionSecurity("m07-session", "m07-csrf"),
    )
    thread = start_in_thread(server)
    try:
        status, first = _http_request(server, "POST", M07_API_ROUTES["route_map"], {})
        assert status == 200
        status, repeated = _http_request(server, "POST", M07_API_ROUTES["route_map"], {})
        assert status == 200
        assert first == repeated
        assert first["total_nodes"] == 30
        assert first["total_edges"] == 300
        assert first["page_edge_total"] == 300
        assert len(first["nodes"]) == 30
        assert len(first["edges"]) == 180
        assert first["item_count"] == 210
        assert first["edge_next_offset"] == 180
        assert first["overflow"]["has_more_edges"] is True
        assert str(m07_project.parent) not in str(first)

        status, second = _http_request(
            server,
            "POST",
            M07_API_ROUTES["route_map"],
            {"edge_offset": first["edge_next_offset"], "edge_limit": 180},
        )
        assert status == 200
        assert second["edge_offset"] == 180
        assert second["edge_next_offset"] is None
        assert second["overflow"]["has_more_edges"] is False
        assert second["overflow"]["edges_remaining"] == 0
        assert len(second["edges"]) == 120
        assert {item["id"] for item in first["edges"]}.isdisjoint(
            item["id"] for item in second["edges"]
        )
        assert [item["id"] for item in second["nodes"]] == [item["id"] for item in first["nodes"]]
    finally:
        server.close_service()
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_provider_free_exact_window_resolve_rejects_unsafe_selections(
    m07_project: Path,
) -> None:
    constructed: list[tuple[int, str]] = []
    api = _api(m07_project, constructed)
    with Project.open(m07_project) as project:
        route = project.payload("m07_route_map", "authoritative")
        before = project.authoritative_bytes()
    assert isinstance(route, dict)
    nodes = sorted(route["nodes"], key=lambda item: item["order"])
    node_ids = [str(item["id"]) for item in nodes]
    edge_pairs = {
        frozenset((str(item["source_id"]), str(item["target_id"]))) for item in route["edges"]
    }
    disconnected = next(
        (list(pair) for pair in combinations(node_ids, 2) if frozenset(pair) not in edge_pairs),
        None,
    )
    try:
        explicit = api.dispatch(
            "POST", M07_API_ROUTES["window_resolve"], {"node_ids": [node_ids[0]]}
        )
        assert isinstance(explicit, dict)
        assert set(explicit) == {"window", "selection_request"}
        assert explicit["window"]["selection_kind"] == "node_ids"
        assert explicit["window"]["node_ids"] == [node_ids[0]]
        assert explicit["selection_request"]["expected"]["id"] == explicit["window"]["id"]
        assert (
            explicit["selection_request"]["expected"]["input_hash"]
            == explicit["window"]["input_hash"]
        )

        anchored = api.dispatch(
            "POST",
            M07_API_ROUTES["window_resolve"],
            {"entry_node_id": node_ids[-1], "exit_node_id": node_ids[-1]},
        )
        assert anchored["window"]["selection_kind"] == "anchors"
        assert anchored["selection_request"]["entry_node_id"] == node_ids[-1]
        assert anchored["selection_request"]["exit_node_id"] == node_ids[-1]

        invalid = (
            {"node_ids": [node_ids[0], node_ids[0]]},
            {"node_ids": node_ids},
            {"node_ids": [r"C:\private\secret\story.rpy"]},
        )
        for selection in invalid:
            with pytest.raises(ApiProblem) as problem:
                api.dispatch("POST", M07_API_ROUTES["window_resolve"], selection)
            assert problem.value.status == 400
            assert "private" not in str(problem.value).casefold()
            assert "secret" not in str(problem.value).casefold()
        if disconnected is not None:
            with pytest.raises(ApiProblem):
                api.dispatch(
                    "POST",
                    M07_API_ROUTES["window_resolve"],
                    {"node_ids": disconnected},
                )
        with pytest.raises(ValueError, match="unsupported fields"):
            api.dispatch(
                "POST",
                M07_API_ROUTES["window_resolve"],
                {"node_ids": [node_ids[0]], "arbitrary": True},
            )
        assert constructed == []
    finally:
        api.close()
    with Project.open(m07_project) as project:
        assert project.authoritative_bytes() == before


def test_window_resolve_rejects_oversize_selection(m07_project: Path) -> None:
    nodes = [
        {
            "id": f"bounded-node-{index:03d}",
            "title": f"Node {index}",
            "lane_id": "spine",
            "lane_kind": "spine",
            "order": index,
            "evidence_ids": [],
        }
        for index in range(66)
    ]
    edges = [
        {
            "id": f"bounded-edge-{index:03d}",
            "source_id": nodes[index]["id"],
            "target_id": nodes[index + 1]["id"],
            "evidence_ids": [],
            "gate_ids": [],
            "effect_ids": [],
        }
        for index in range(65)
    ]
    with Project.open(m07_project) as project:
        project.write_payloads(
            [
                PayloadRecord(
                    "m07_route_map",
                    "authoritative",
                    {
                        "schema_version": 1,
                        "nodes": nodes,
                        "edges": edges,
                        "scopes": [],
                        "coverage": {},
                        "initial_node_ids": [nodes[0]["id"]],
                        "evidence": [],
                    },
                    tuple(item.path for item in project.sources()),
                )
            ]
        )
    api = _api(m07_project, [])
    try:
        with pytest.raises(ApiProblem) as problem:
            api.dispatch(
                "POST",
                M07_API_ROUTES["window_resolve"],
                {"node_ids": [str(item["id"]) for item in nodes[:65]]},
            )
        assert problem.value.status == 400
    finally:
        api.close()


def test_exact_window_prepare_status_and_tampered_start_are_provider_free(
    m07_project: Path,
) -> None:
    constructed: list[tuple[int, str]] = []
    api = _api(m07_project, constructed)
    with Project.open(m07_project) as project:
        route = project.payload("m07_route_map", "authoritative")
    assert isinstance(route, dict)
    node_id = str(min(route["nodes"], key=lambda item: item["order"])["id"])
    try:
        resolved = api.dispatch("POST", M07_API_ROUTES["window_resolve"], {"node_ids": [node_id]})
        prepared = api.dispatch(
            "POST",
            M07_API_ROUTES["prepare"],
            {"window_requests": [resolved["selection_request"]]},
        )
        assert isinstance(prepared, dict)
        assert prepared["scope_ids"] == []
        assert prepared["window_ids"] == [resolved["window"]["id"]]
        assert prepared["windows"] == [resolved["window"]]
        assert prepared["selected_counts"]["work_units"] == 1
        assert prepared["selected_counts"]["windows"] == 1
        assert prepared["selected_counts"]["nodes"] == len(resolved["window"]["node_ids"])
        assert prepared["selected_counts"]["boundary_edges"] == len(
            resolved["window"]["boundary_edge_ids"]
        )
        assert prepared["selected_counts"]["evidence"] == len(resolved["window"]["evidence_ids"])
        assert prepared["selected_counts"]["facts"] == len(resolved["window"]["fact_ids"])
        assert prepared["cached"] == prepared["validated"] == 0
        assert (
            prepared["recovered_source_acknowledgement"]
            == prepared["source_coverage"]["coverage_token"]
        )
        assert str(m07_project.parent) not in json.dumps(prepared)

        status = api.dispatch("GET", M07_API_ROUTES["organization"], {})
        assert status["window_ids"] == prepared["window_ids"]
        assert status["selection_hash"] == prepared["selection_hash"]
        assert status["prepared_authority_hash"] == prepared["authority_hash"]
        assert (
            status["recovered_source_acknowledgement"]
            == prepared["recovered_source_acknowledgement"]
        )
        assert status["model"] == prepared["model"]
        assert status["budgets"] == prepared["budgets"]
        assert status["selected_counts"] == prepared["selected_counts"]
        assert str(m07_project.parent) not in json.dumps(status)

        with pytest.raises(ValueError, match="cannot be empty"):
            api.dispatch(
                "POST",
                M07_API_ROUTES["start"],
                _start_body(prepared, scope_ids=[], window_ids=[]),
            )
        missing = _start_body(prepared)
        missing.pop("model")
        with pytest.raises(ValueError, match="missing required fields"):
            api.dispatch("POST", M07_API_ROUTES["start"], missing)
        with pytest.raises(ValueError, match="unsupported fields"):
            api.dispatch(
                "POST",
                M07_API_ROUTES["start"],
                {**_start_body(prepared), "refresh_consent": True},
            )
        with pytest.raises(ValueError, match="selection_hash"):
            api.dispatch(
                "POST",
                M07_API_ROUTES["start"],
                _start_body(prepared, selection_hash="0" * 64),
            )
        with pytest.raises(ValueError, match="stale"):
            api.dispatch("POST", M07_API_ROUTES["start"], _start_body(prepared))
        assert constructed == []
    finally:
        api.close()


def test_window_http_json_shape_rejections_and_path_redaction(m07_project: Path) -> None:
    constructed: list[tuple[int, str]] = []
    api = _api(m07_project, constructed)
    with Project.open(m07_project) as project:
        route = project.payload("m07_route_map", "authoritative")
    assert isinstance(route, dict)
    node_id = str(min(route["nodes"], key=lambda item: item["order"])["id"])
    static_root = Path(__file__).parents[1] / "src" / "renpy_story_mapper" / "web" / "static"
    server = LocalWebServer(
        "127.0.0.1",
        0,
        api,
        static_root=static_root,
        security=SessionSecurity("m07-session", "m07-csrf"),
    )
    thread = start_in_thread(server)
    try:
        status, resolved = _http_request(
            server,
            "POST",
            M07_API_ROUTES["window_resolve"],
            {"node_ids": [node_id]},
        )
        assert status == 200
        assert set(resolved) == {"window", "selection_request"}
        assert set(resolved["window"]) == {
            "schema_version",
            "id",
            "selection_kind",
            "entry_node_id",
            "exit_node_id",
            "node_ids",
            "internal_edge_ids",
            "boundary_node_ids",
            "boundary_edge_ids",
            "evidence_ids",
            "fact_ids",
            "input_hash",
            "authority_hash",
        }
        assert str(m07_project.parent) not in json.dumps(resolved)

        status, empty = _http_request(server, "POST", M07_API_ROUTES["prepare"], {})
        assert status == 400
        assert empty == {
            "error": {
                "code": "m07_selection_required",
                "message": "Select at least one bounded route scope or narrative window.",
            }
        }
        status, unknown = _http_request(
            server,
            "POST",
            M07_API_ROUTES["window_resolve"],
            {"node_ids": [r"C:\private\secret\story.rpy"]},
        )
        assert status == 400
        assert unknown["error"]["code"] == "m07_bounded_window_invalid"
        assert "private" not in json.dumps(unknown).casefold()
        assert "secret" not in json.dumps(unknown).casefold()

        tampered = json.loads(json.dumps(resolved["selection_request"]))
        tampered["expected"]["input_hash"] = "0" * 64
        status, rejected = _http_request(
            server,
            "POST",
            M07_API_ROUTES["prepare"],
            {"window_requests": [tampered]},
        )
        assert status == 400
        assert rejected["error"]["code"] == "m07_bounded_window_invalid"

        status, unknown_scope = _http_request(
            server,
            "POST",
            M07_API_ROUTES["prepare"],
            {"scope_ids": ["scope_unknown"]},
        )
        assert status == 400
        assert unknown_scope["error"]["code"] == "invalid_request"

        with Project.open(m07_project) as project:
            changed_route = project.payload("m07_route_map", "authoritative")
            assert isinstance(changed_route, dict)
            changed_route["coverage"] = {**changed_route["coverage"], "stale_probe": 1}
            project.write_payloads(
                [
                    PayloadRecord(
                        "m07_route_map",
                        "authoritative",
                        changed_route,
                        tuple(item.path for item in project.sources()),
                    )
                ]
            )
        status, stale = _http_request(
            server,
            "POST",
            M07_API_ROUTES["prepare"],
            {"window_requests": [resolved["selection_request"]]},
        )
        assert status == 400
        assert stale["error"]["code"] == "m07_bounded_window_invalid"
        assert constructed == []
    finally:
        server.close_service()
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_prepare_is_provider_free_and_missing_or_stale_consent_is_rejected(
    m07_project: Path,
) -> None:
    constructed: list[tuple[int, str]] = []
    api = _api(m07_project, constructed)
    try:
        api.dispatch("GET", M07_API_ROUTES["organization"], {})
        prepared = _prepare(api, m07_project)
        assert prepared["model"] == {
            "id": "gpt-5.6-luna",
            "reasoning": "high",
            "fast_mode": False,
        }
        assert prepared["scopes"] > 0
        assert prepared["cached"] == 0
        assert prepared["budgets"] == {
            "soft_seconds": 600,
            "hard_seconds": 900,
            "soft_tokens": 1_500_000,
            "hard_tokens": 2_000_000,
            "hard_calls": 48,
        }
        assert len(prepared["run_id"]) > 32
        assert constructed == []

        with pytest.raises(ValueError, match="confirmation"):
            api.dispatch(
                "POST",
                M07_API_ROUTES["start"],
                _start_body(prepared, confirm_cloud=False),
            )
        with pytest.raises(ValueError, match="stale"):
            api.dispatch(
                "POST",
                M07_API_ROUTES["start"],
                _start_body(prepared, run_id="m07_stale"),
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
        prepared = _prepare(api, m07_project, hard_calls=1, hard_tokens=100_000)
        started = api.dispatch(
            "POST",
            M07_API_ROUTES["start"],
            _start_body(prepared),
        )
        assert isinstance(started, dict)
        assert started["status"] == "running"
        assert "scopes" in started and "coverage" in started and "tokens" in started
        terminal = _wait(api)
        assert terminal["state"] == "completed"
        assert calls and all(thread_id != threading.get_ident() for thread_id, _ in calls)

        status = api.dispatch("GET", M07_API_ROUTES["organization"], {})
        assert isinstance(status, dict)
        assert status["calls"] == 1
        assert status["tokens"]["used"] == 25
        assert status["tokens"]["total"] == 25
        assert status["coverage"] == {
            "ai": status["ai_coverage"],
            "technical": status["technical_coverage"],
        }
        assert 0 <= status["ai_coverage"] <= status["technical_coverage"] <= 1
        assert status["partial"] is True
        assert status["assemblies"]
        assembly = status["assembly"]
        assert assembly["assembly_id"] == status["assemblies"][0]["assembly_id"]
        assert status["assembly_id"] == assembly["assembly_id"]
        assert assembly["generation"] == status["authority_hash"]
        assert assembly["payload"]["items"]
        assert all(
            "correction" in item and "pinned" in item for item in assembly["payload"]["items"]
        )
        provider_item = next(
            item
            for item in assembly["payload"]["items"]
            if isinstance(item.get("result"), dict)
            and isinstance(item["result"].get("organization_result"), dict)
        )
        assert "claims" in provider_item["result"]["organization_result"]["groups"][0]
        applied = api.dispatch(
            "POST",
            M07_API_ROUTES["assembly_apply"],
            {"assembly_id": assembly["assembly_id"]},
        )
        assert applied["status"] == "applied"
        assert applied["assembly_id"] == assembly["assembly_id"]
        after = api.dispatch("POST", M07_API_ROUTES["route_map"], {})
        assert after["authority_hash"] == before["authority_hash"]
        assert after["applied_assembly"]["assembly_id"] == assembly["assembly_id"]
    finally:
        api.close()


def test_close_reopen_replay_uses_zero_provider_calls(m07_project: Path) -> None:
    calls: list[tuple[int, str]] = []
    first = _api(m07_project, calls)
    prepared = _prepare(first, m07_project)
    first.dispatch(
        "POST",
        M07_API_ROUTES["start"],
        _start_body(prepared),
    )
    assert _wait(first)["state"] == "completed"
    first.close()
    first_count = len(calls)
    assert first_count > 0

    second = _api(m07_project, calls)
    try:
        prepared = _prepare(second, m07_project)
        second.dispatch(
            "POST",
            M07_API_ROUTES["start"],
            _start_body(prepared),
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
        prepared = _prepare(api, m07_project)
        api.dispatch(
            "POST",
            M07_API_ROUTES["start"],
            _start_body(prepared),
        )
        assert blocking.wait(timeout=3)
        cancelling = api.dispatch("POST", M07_API_ROUTES["cancel"], {})
        # Keep the packaged app's polling loop alive until durable cancellation is visible.
        assert cancelling["status"] == "running"
        assert cancelling["stage"] == "cancelling"
        assert "scopes" in cancelling and "coverage" in cancelling
        assert _wait(api)["state"] == "cancelled"
        cancelled = api.dispatch("GET", M07_API_ROUTES["organization"], {})
        assert cancelled["status"] == "cancelled"
        assert cancelled["scope_counts"]["cancelled"] > 0
        assert "private provider detail" not in str(cancelled)

        with pytest.raises(ValueError, match="stale"):
            api.dispatch(
                "POST",
                M07_API_ROUTES["start"],
                _start_body(prepared),
            )
        use_blocking = False
        resumed = _prepare(api, m07_project)
        api.dispatch(
            "POST",
            M07_API_ROUTES["start"],
            _start_body(resumed),
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
                "POST",
                M07_API_ROUTES["prepare"],
                {
                    "scope_ids": _scope_ids(m07_project),
                    "soft_seconds": 20,
                    "hard_seconds": 10,
                },
            )
        with pytest.raises(ApiProblem) as empty:
            api.dispatch("POST", M07_API_ROUTES["prepare"], {})
        assert empty.value.status == 400
        assert empty.value.code == "m07_selection_required"
        with pytest.raises(Exception) as detail_error:
            api.dispatch("POST", M07_API_ROUTES["detail"], {"element_id": "C:\\secret\\story.rpy"})
        assert "secret" not in str(detail_error.value).casefold()
    finally:
        api.close()


def test_contract_constants_are_exact() -> None:
    assert M07_API_ROUTES == {
        "route_map": "/api/v1/m07/route-map",
        "route_search": "/api/v1/m07/route-search",
        "detail": "/api/v1/m07/detail",
        "window_resolve": "/api/v1/m07/bounded-window/resolve",
        "organization": "/api/v1/m07/organization",
        "prepare": "/api/v1/m07/organization/prepare",
        "start": "/api/v1/m07/organization/start",
        "cancel": "/api/v1/m07/organization/cancel",
        "source_acknowledge": "/api/v1/m07/source-coverage/acknowledge",
        "scope_override": "/api/v1/m07/scope/override",
        "assembly_apply": "/api/v1/m07/assembly/apply",
        "assembly_discard": "/api/v1/m07/assembly/discard",
    }


def test_source_coverage_block_acknowledgement_and_last_moment_guard(
    m07_project: Path,
) -> None:
    calls: list[tuple[int, str]] = []
    api = _api(m07_project, calls)
    try:
        with Project.open(m07_project) as project:
            project._require_open().execute(
                """INSERT OR REPLACE INTO source_coverage(
                   singleton,complete,partial_allowed,ai_transmission_blocked,
                   acknowledged,warning,updated_utc) VALUES (1,0,1,1,0,?,?)""",
                ("Recovered sources are incomplete.", storage.utc_now()),
            )
        with pytest.raises(ValueError, match="blocked"):
            _prepare(api, m07_project)

        status = api.dispatch("GET", M07_API_ROUTES["organization"], {})
        coverage = status["source_coverage"]
        with pytest.raises(ValueError, match="stale"):
            api.dispatch(
                "POST",
                M07_API_ROUTES["source_acknowledge"],
                {"acknowledge": True, "coverage_token": "0" * 64},
            )
        acknowledged = api.dispatch(
            "POST",
            M07_API_ROUTES["source_acknowledge"],
            {"acknowledge": True, "coverage_token": coverage["coverage_token"]},
        )
        assert acknowledged["acknowledged"] is True
        assert acknowledged["ai_transmission_blocked"] is False

        prepared = _prepare(api, m07_project)
        with Project.open(m07_project) as project:
            project._require_open().execute(
                """UPDATE source_coverage SET acknowledged=0,ai_transmission_blocked=1,
                   updated_utc=? WHERE singleton=1""",
                (storage.utc_now(),),
            )
        with pytest.raises(ValueError, match="blocked"):
            api.dispatch(
                "POST",
                M07_API_ROUTES["start"],
                _start_body(prepared),
            )
        assert calls == []
    finally:
        api.close()


def test_start_budget_and_route_generation_are_exact_and_single_use(
    m07_project: Path,
) -> None:
    calls: list[tuple[int, str]] = []
    api = _api(m07_project, calls)
    try:
        prepared = _prepare(api, m07_project)
        with pytest.raises(ValueError, match="scope_ids"):
            api.dispatch(
                "POST",
                M07_API_ROUTES["start"],
                _start_body(
                    prepared,
                    scope_ids=[*prepared["scope_ids"], "scope_invented"],
                ),
            )
        with pytest.raises(ValueError, match="stale"):
            api.dispatch(
                "POST",
                M07_API_ROUTES["start"],
                _start_body(prepared),
            )
        assert calls == []

        prepared = _prepare(api, m07_project)
        mismatched = dict(prepared["budgets"])
        mismatched["hard_calls"] = int(mismatched["hard_calls"]) - 1
        with pytest.raises(ValueError, match="does not match"):
            api.dispatch(
                "POST",
                M07_API_ROUTES["start"],
                _start_body(prepared, budgets=mismatched),
            )
        with pytest.raises(ValueError, match="stale"):
            api.dispatch(
                "POST",
                M07_API_ROUTES["start"],
                _start_body(prepared),
            )

        prepared = _prepare(api, m07_project)
        with Project.open(m07_project) as project:
            route = project.payload("m07_route_map", "authoritative")
            assert isinstance(route, dict)
            route["schema_version"] = 2
            project.write_payloads(
                [
                    PayloadRecord(
                        "m07_route_map",
                        "authoritative",
                        route,
                        tuple(item.path for item in project.sources()),
                    )
                ]
            )
        with pytest.raises(ValueError, match="changed after preparation"):
            api.dispatch(
                "POST",
                M07_API_ROUTES["start"],
                _start_body(prepared),
            )
        assert calls == []
    finally:
        api.close()


def test_route_search_cursor_is_bounded_and_query_generation_bound(m07_project: Path) -> None:
    api = _api(m07_project, [])
    try:
        route = api.dispatch("POST", M07_API_ROUTES["route_map"], {})
        title = route["nodes"][0]["title"]
        query = str(title).split()[0]
        result = api.dispatch("POST", M07_API_ROUTES["route_search"], {"query": query, "limit": 1})
        assert len(result["items"]) <= 1
        assert result["total_matches"] >= len(result["items"])
        cursor = result["continuation"] or "m07s_stale_cursor_1"
        with pytest.raises(ValueError, match="mismatched"):
            api.dispatch(
                "POST",
                M07_API_ROUTES["route_search"],
                {"query": query + "x", "after": cursor, "limit": 1},
            )
    finally:
        api.close()


def test_applied_overlay_and_draft_are_rejected_after_route_refresh(m07_project: Path) -> None:
    calls: list[tuple[int, str]] = []
    api = _api(m07_project, calls)
    try:
        prepared = _prepare(api, m07_project, hard_calls=1)
        api.dispatch(
            "POST",
            M07_API_ROUTES["start"],
            _start_body(prepared),
        )
        assert _wait(api)["state"] == "completed"
        status = api.dispatch("GET", M07_API_ROUTES["organization"], {})
        assembly_id = status["assembly_id"]
        api.dispatch("POST", M07_API_ROUTES["assembly_apply"], {"assembly_id": assembly_id})

        with Project.open(m07_project) as project:
            route = project.payload("m07_route_map", "authoritative")
            assert isinstance(route, dict)
            route["schema_version"] = 2
            project.write_payloads(
                [
                    PayloadRecord(
                        "m07_route_map",
                        "authoritative",
                        route,
                        tuple(item.path for item in project.sources()),
                    )
                ]
            )
        refreshed = api.dispatch("POST", M07_API_ROUTES["route_map"], {})
        assert refreshed["applied_assembly"] is None
        assert refreshed["organization_coverage"]["total"] == 0
        with pytest.raises(Exception) as stale:
            api.dispatch("POST", M07_API_ROUTES["assembly_apply"], {"assembly_id": assembly_id})
        assert getattr(stale.value, "status", None) == 409
        after = api.dispatch("GET", M07_API_ROUTES["organization"], {})
        assert after["assemblies"] == []
    finally:
        api.close()


def test_applied_detail_exposes_evidence_claims_corrections_and_pins(
    m07_project: Path,
) -> None:
    calls: list[tuple[int, str]] = []

    class ClaimProvider(_MockProvider):
        def organize(self, request: Any, progress: Any, cancelled: Any) -> OrganizationChunkResult:
            base = super().organize(request, progress, cancelled)
            evidence_ids = tuple(sorted(request.constraints.evidence_ids))
            claims = (
                (InterpretationClaim("Evidence-backed route claim.", (evidence_ids[0],)),)
                if evidence_ids
                else ()
            )
            group = base.groups[0]
            replaced = OrganizationGroup(
                group.id,
                group.title,
                group.summary,
                group.member_ids,
                group.characters,
                group.importance,
                group.outcomes,
                group.promoted_fact_ids,
                claims,
                group.warnings,
            )
            raw = dict(base.raw_normalized)
            groups = list(raw["groups"])
            groups[0] = {
                **groups[0],
                "claims": [
                    {"text": claim.text, "evidence_ids": list(claim.evidence_ids)}
                    for claim in claims
                ],
            }
            raw["groups"] = groups
            return OrganizationChunkResult(
                base.stage,
                (replaced,),
                base.ungrouped_ids,
                raw,
                metadata=base.metadata,
            )

    api = ProjectApi(_Dialogs(), m07_provider_factory=lambda scope: ClaimProvider(scope, calls))
    api._project_path = m07_project
    try:
        prepared = _prepare(api, m07_project)
        api.dispatch(
            "POST",
            M07_API_ROUTES["start"],
            _start_body(prepared),
        )
        assert _wait(api)["state"] == "completed"
        assembly = api.dispatch(
            "POST",
            M07_API_ROUTES["scope_override"],
            {
                "scope_id": prepared["scope_ids"][0],
                "authority_hash": prepared["authority_hash"],
                "correction": {"title": "Pinned corrected title"},
                "pinned": True,
            },
        )
        review = api.dispatch("GET", M07_API_ROUTES["organization"], {})
        assert review["assembly"]["assembly_id"] == assembly["assembly_id"]
        reviewed_scope = next(
            item
            for item in review["assembly"]["payload"]["items"]
            if item["scope_id"] == prepared["scope_ids"][0]
        )
        assert reviewed_scope["correction"] == {"title": "Pinned corrected title"}
        assert reviewed_scope["pinned"] is True
        reviewed_groups = reviewed_scope["result"]["organization_result"]["groups"]
        assert all(claim["evidence_ids"] for claim in reviewed_groups[0]["claims"])
        api.dispatch(
            "POST",
            M07_API_ROUTES["assembly_apply"],
            {"assembly_id": assembly["assembly_id"]},
        )
        with Project.open(m07_project) as project:
            route = project.payload("m07_route_map", "authoritative")
            assert isinstance(route, dict)
            first_scope = next(
                item for item in route["scopes"] if item["id"] == prepared["scope_ids"][0]
            )
            node_id = first_scope["node_ids"][0]
        detail = api.dispatch("POST", M07_API_ROUTES["detail"], {"element_id": node_id})
        interpretation = detail["element"]["interpretation"]
        assert detail["element"]["title"] == "Pinned corrected title"
        assert interpretation["pinned"] is True
        assert interpretation["correction"] == {"title": "Pinned corrected title"}
        assert all(claim["evidence_ids"] for claim in interpretation["claims"])

        applied_route = api.dispatch("POST", M07_API_ROUTES["route_map"], {})
        discard_draft = api.dispatch(
            "POST",
            M07_API_ROUTES["scope_override"],
            {
                "scope_id": prepared["scope_ids"][0],
                "authority_hash": prepared["authority_hash"],
                "correction": {"title": "Discard this draft"},
                "pinned": False,
            },
        )
        discarded = api.dispatch(
            "POST",
            M07_API_ROUTES["assembly_discard"],
            {"assembly_id": discard_draft["assembly_id"]},
        )
        assert discarded["discarded_assembly"]["status"] == "superseded"
        unchanged_route = api.dispatch("POST", M07_API_ROUTES["route_map"], {})
        assert unchanged_route["applied_assembly"] == applied_route["applied_assembly"]
        assert unchanged_route["nodes"] == applied_route["nodes"]
        with pytest.raises(Exception) as repeated:
            api.dispatch(
                "POST",
                M07_API_ROUTES["assembly_discard"],
                {"assembly_id": discard_draft["assembly_id"]},
            )
        assert getattr(repeated.value, "status", None) == 409
        with pytest.raises(Exception) as unknown:
            api.dispatch(
                "POST",
                M07_API_ROUTES["assembly_discard"],
                {"assembly_id": "assembly_unknown"},
            )
        assert getattr(unknown.value, "status", None) == 404
    finally:
        api.close()


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


def _http_request(
    server: LocalWebServer,
    method: str,
    path: str,
    body: object | None = None,
) -> tuple[int, dict[str, Any]]:
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    headers = {
        "Host": f"127.0.0.1:{server.port}",
        "Accept": "application/json",
        "X-RSM-Session": "m07-session",
    }
    payload = None
    if method != "GET":
        headers.update(
            {
                "Content-Type": "application/json",
                "Origin": f"http://127.0.0.1:{server.port}",
                "X-RSM-CSRF": "m07-csrf",
            }
        )
        payload = json.dumps({} if body is None else body).encode()
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    result = json.loads(response.read())
    connection.close()
    return response.status, result


def _assert_browser_organization(value: dict[str, Any]) -> None:
    assert isinstance(value["status"], str)
    assert set(value["scopes"]) >= {"total", "pending", "validated", "fallback"}
    assert set(value["coverage"]) == {"ai", "technical"}
    assert set(value["tokens"]) >= {"used", "budget", "input", "output"}
    assert "calls" in value and "eta" in value and "partial" in value
    assert "assembly_id" in value
    assert "assembly" in value
    assert value["model"] == {
        "id": "gpt-5.6-luna",
        "reasoning": "high",
        "fast_mode": False,
    }
    assert set(value["budgets"]) == {
        "soft_seconds",
        "hard_seconds",
        "soft_tokens",
        "hard_tokens",
        "hard_calls",
    }
    assert all(isinstance(item, int) and item > 0 for item in value["budgets"].values())
    assert set(value["selected_counts"]) == {
        "work_units",
        "deterministic_scopes",
        "windows",
        "nodes",
        "internal_edges",
        "boundary_nodes",
        "boundary_edges",
        "evidence",
        "facts",
    }
    assert "cached" in value and "validated" in value


def test_local_server_emits_packaged_route_and_organization_shapes(
    m07_project: Path,
) -> None:
    calls: list[tuple[int, str]] = []
    api = _api(m07_project, calls)
    static_root = Path(__file__).parents[1] / "src" / "renpy_story_mapper" / "web" / "static"
    server = LocalWebServer(
        "127.0.0.1",
        0,
        api,
        static_root=static_root,
        security=SessionSecurity("m07-session", "m07-csrf"),
    )
    thread = start_in_thread(server)
    try:
        status, route = _http_request(server, "POST", M07_API_ROUTES["route_map"], {})
        assert status == 200
        assert route["total_nodes"] >= len(route["nodes"])
        assert "edges" in route and "lines" not in route
        assert len(route["nodes"]) <= 30
        assert len(route["edges"]) <= 180
        assert len(route["nodes"]) + len(route["edges"]) <= 240

        status, organization = _http_request(server, "GET", M07_API_ROUTES["organization"])
        assert status == 200
        _assert_browser_organization(organization)
        assert organization["status"] == "idle"
        assert calls == []

        status, prepared = _http_request(
            server,
            "POST",
            M07_API_ROUTES["prepare"],
            {"scope_ids": _scope_ids(m07_project)},
        )
        assert status == 200
        assert set(prepared) == {
            "run_id",
            "scopes",
            "scope_ids",
            "window_ids",
            "windows",
            "selected_counts",
            "cached",
            "validated",
            "model",
            "budgets",
            "authority_hash",
            "selection_hash",
            "recovered_source_acknowledgement",
            "source_coverage",
            "requires_confirm_cloud",
        }
        assert prepared["scopes"] > 0
        assert prepared["cached"] == 0
        assert prepared["budgets"] == {
            "soft_seconds": 600,
            "hard_seconds": 900,
            "soft_tokens": 1_500_000,
            "hard_tokens": 2_000_000,
            "hard_calls": 48,
        }
        assert calls == []

        status, running = _http_request(
            server,
            "POST",
            M07_API_ROUTES["start"],
            _start_body(prepared),
        )
        assert status == 200
        _assert_browser_organization(running)
        assert running["status"] == "running"

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            _status, task = _http_request(server, "GET", "/api/v1/analysis/progress")
            if task.get("state") in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("integrated organization did not finish")
        status, review = _http_request(server, "GET", M07_API_ROUTES["organization"])
        assert status == 200
        _assert_browser_organization(review)
        assert review["status"] in {"review", "partial"}
        assert review["assembly_id"]

        status, applied = _http_request(
            server,
            "POST",
            M07_API_ROUTES["assembly_apply"],
            {"assembly_id": review["assembly_id"]},
        )
        assert status == 200
        _assert_browser_organization(applied)
        assert applied["status"] == "applied"
        assert applied["assembly_id"] == review["assembly_id"]
    finally:
        server.close_service()
        thread.join(timeout=5)
        assert not thread.is_alive()
