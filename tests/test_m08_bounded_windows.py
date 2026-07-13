"""M08 bounded narrative-window and exact subset-consent backend contracts."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from renpy_story_mapper import storage
from renpy_story_mapper.bounded_window import (
    BoundedWindowError,
    WindowLimits,
    build_bounded_narrative_window,
    build_window_from_request,
)
from renpy_story_mapper.m07_workflow import M07WorkflowService, PreparedRunError
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
from renpy_story_mapper.project import PayloadRecord, Project, create_ingested_project


def _route_payload(*, fact_ids: bool = True) -> dict[str, object]:
    node_lanes = ("spine", "spine", "detour", "persistent", "spine", "spine")
    nodes = [
        {
            "id": f"node-{ordinal}",
            "control_node_id": f"control-{ordinal}",
            "kind": "milestone",
            "title": f"Node {ordinal}",
            "lane_id": f"lane-{node_lanes[ordinal]}",
            "lane_kind": node_lanes[ordinal],
            "order": ordinal,
            "evidence_ids": [f"node-evidence-{ordinal}"],
            "region_ids": [],
            "terminal_kind": None,
            "unresolved": False,
        }
        for ordinal in range(6)
    ]
    endpoints = ((0, 1), (1, 2), (1, 3), (2, 4), (3, 4), (4, 5))
    edges = [
        {
            "id": f"edge-{ordinal}",
            "source_id": f"node-{source}",
            "target_id": f"node-{target}",
            "role": "choice" if ordinal in {1, 2} else "corridor",
            "lane_id": "lane-persistent" if ordinal in {2, 4} else "lane-spine",
            "control_edge_ids": [f"control-edge-{ordinal}"],
            "control_node_ids": [f"control-{source}", f"control-{target}"],
            "gate_ids": [f"gate-{ordinal}"] if fact_ids else [],
            "effect_ids": [f"effect-{ordinal}"] if fact_ids else [],
            "evidence_ids": [f"edge-evidence-{ordinal}"],
            "technical_hops": 0,
            "proven_merge": target == 4,
        }
        for ordinal, (source, target) in enumerate(endpoints)
    ]
    evidence = [
        {
            "id": f"node-evidence-{ordinal}",
            "kind": "beat",
            "source": None,
            "text": f"Node evidence {ordinal}",
            "payload": {"ordinal": ordinal},
        }
        for ordinal in range(6)
    ] + [
        {
            "id": f"edge-evidence-{ordinal}",
            "kind": "transition",
            "source": None,
            "text": f"Edge evidence {ordinal}",
            "payload": {"ordinal": ordinal},
        }
        for ordinal in range(6)
    ]

    def scope(
        scope_id: str, ordinal: int, node_ids: list[str], edge_ids: list[str]
    ) -> dict[str, object]:
        evidence_ids = sorted(
            {
                *(f"node-evidence-{item.split('-')[1]}" for item in node_ids),
                *(f"edge-evidence-{item.split('-')[1]}" for item in edge_ids),
            }
        )
        material = {
            "node_ids": node_ids,
            "edge_ids": edge_ids,
            "evidence_ids": evidence_ids,
        }
        return {
            "id": scope_id,
            "ordinal": ordinal,
            "lane_id": f"lane-{ordinal}",
            **material,
            "input_hash": hashlib.sha256(storage.canonical_json(material)).hexdigest(),
        }

    return {
        "schema_version": 1,
        "presentation_levels": ["route_map", "detail_evidence"],
        "initial_node_limit": 30,
        "initial_node_ids": [item["id"] for item in nodes],
        "page_limits": {"nodes": 30, "edges": 180, "items": 240},
        "nodes": nodes,
        "edges": edges,
        "scopes": [
            scope("scope-entry", 0, ["node-0", "node-1"], ["edge-0", "edge-1", "edge-2"]),
            scope(
                "scope-branches",
                1,
                ["node-2", "node-3", "node-4", "node-5"],
                ["edge-1", "edge-2", "edge-3", "edge-4", "edge-5"],
            ),
        ],
        "coverage": {
            "control_nodes": 6,
            "visible_nodes": 6,
            "technical_nodes": 0,
            "unresolved_nodes": 0,
            "corridor_count": 4,
        },
        "evidence": evidence,
    }


def test_anchor_window_preserves_reconverging_detour_persistent_route_and_exact_evidence() -> None:
    route = _route_payload()
    authority_before = hashlib.sha256(storage.canonical_json(route)).hexdigest()
    window = build_bounded_narrative_window(
        route, entry_node_id="node-1", exit_node_id="node-4"
    )

    assert window.node_ids == ("node-1", "node-2", "node-3", "node-4")
    assert window.internal_edge_ids == ("edge-1", "edge-2", "edge-3", "edge-4")
    assert window.boundary_node_ids == ("node-0", "node-5")
    assert window.boundary_edge_ids == ("edge-0", "edge-5")
    assert window.evidence_ids == tuple(
        sorted(
            {
                *(f"node-evidence-{ordinal}" for ordinal in (1, 2, 3, 4)),
                *(f"edge-evidence-{ordinal}" for ordinal in range(6)),
            }
        )
    )
    assert window.fact_ids == tuple(
        sorted(
            {
                *(f"gate-{ordinal}" for ordinal in range(6)),
                *(f"effect-{ordinal}" for ordinal in range(6)),
            }
        )
    )
    assert window.authority_hash == authority_before
    assert hashlib.sha256(storage.canonical_json(route)).hexdigest() == authority_before
    assert build_window_from_request(route, window.selection_request()) == window


def test_exact_window_rejects_unknown_duplicate_disconnected_drift_and_incomplete_route() -> None:
    route = _route_payload()
    window = build_bounded_narrative_window(route, node_ids=("node-1", "node-2"))
    assert window.internal_edge_ids == ("edge-1",)
    assert window.boundary_node_ids == ("node-0", "node-3", "node-4")
    assert window.boundary_edge_ids == ("edge-0", "edge-2", "edge-3")

    with pytest.raises(BoundedWindowError, match="duplicate"):
        build_bounded_narrative_window(route, node_ids=("node-1", "node-1"))
    with pytest.raises(BoundedWindowError, match="unknown"):
        build_bounded_narrative_window(route, node_ids=("node-unknown",))
    with pytest.raises(BoundedWindowError, match="disconnected"):
        build_bounded_narrative_window(route, node_ids=("node-0", "node-5"))

    request = window.selection_request()
    expected = dict(request["expected"])
    expected["internal_edge_ids"] = []
    request["expected"] = expected
    with pytest.raises(BoundedWindowError, match="drifted"):
        build_window_from_request(route, request)

    incomplete = copy.deepcopy(route)
    incomplete["evidence"] = list(incomplete["evidence"])[1:]
    with pytest.raises(BoundedWindowError, match="unknown evidence"):
        build_bounded_narrative_window(incomplete, node_ids=("node-1", "node-2"))


def test_window_rejects_empty_global_oversize_and_incomplete_expectations() -> None:
    route = _route_payload()
    with pytest.raises(BoundedWindowError, match="cannot be empty"):
        build_bounded_narrative_window(route)
    with pytest.raises(BoundedWindowError, match="full route map"):
        build_bounded_narrative_window(
            route, node_ids=tuple(f"node-{ordinal}" for ordinal in range(6))
        )
    with pytest.raises(BoundedWindowError, match="nodes limit"):
        build_bounded_narrative_window(
            route,
            node_ids=("node-1", "node-2"),
            limits=WindowLimits(max_nodes=1),
        )
    with pytest.raises(BoundedWindowError, match="complete expected"):
        build_bounded_narrative_window(
            route,
            node_ids=("node-1", "node-2"),
            require_expected=True,
        )
    with pytest.raises(BoundedWindowError, match="incomplete"):
        build_bounded_narrative_window(
            route,
            node_ids=("node-1", "node-2"),
            expected={"id": "bounded_window_incomplete"},
        )


@pytest.fixture
def bounded_project(tmp_path: Path) -> Path:
    source = tmp_path / "game" / "story.rpy"
    source.parent.mkdir()
    source.write_text('label start:\n    "Static source."\n    return\n', encoding="utf-8")
    destination = tmp_path / "bounded.rsmproj"
    with create_ingested_project(destination, source.parent) as project:
        project.write_payloads(
            [
                PayloadRecord(
                    "m07_route_map",
                    "authoritative",
                    _route_payload(fact_ids=False),
                    tuple(item.path for item in project.sources()),
                )
            ]
        )
    return destination


class _Provider:
    def __init__(self, scope: RouteScope, requests: list[Any]) -> None:
        self._scope = scope
        self._requests = requests

    def status(self) -> ProviderStatus:
        return ProviderStatus(ProviderState.READY, "mock", model_identifier=M05_CLOUD_MODEL)

    def organize(self, request: Any, progress: Any, cancelled: Callable[[], bool]) -> Any:
        del progress
        assert request is self._scope.request or request.scope_id == self._scope.request.scope_id
        assert not cancelled()
        self._requests.append(request)
        members = tuple(request.constraints.ordered_member_ids)
        group = OrganizationGroup(
            id=f"group-{request.scope_id}",
            title="Bounded interpretation",
            summary="Exact bounded evidence.",
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
                1,
                "a" * 64,
                "b" * 64,
                10,
                2,
            ),
        )

    def cancel(self) -> None:
        return


def _route(project_path: Path) -> dict[str, object]:
    with Project.open(project_path) as project:
        value = project.payload("m07_route_map", "authoritative")
    assert isinstance(value, dict)
    return value


def _strict_authorize(
    service: M07WorkflowService, prepared: Mapping[str, Any], budget: BudgetPolicy
) -> Any:
    return service.authorize_start(
        str(prepared["run_id"]),
        confirm_cloud=True,
        scope_ids=tuple(prepared["scope_ids"]),
        window_ids=tuple(prepared["window_ids"]),
        budget=budget,
        selection_hash=str(prepared["selection_hash"]),
        authority_hash=str(prepared["authority_hash"]),
        recovered_source_acknowledgement=str(
            prepared["recovered_source_acknowledgement"]
        ),
        model=prepared["model"],
    )


def test_window_consent_exact_payload_zero_call_replay_and_authority_unchanged(
    bounded_project: Path,
) -> None:
    requests: list[Any] = []
    constructions: list[str] = []

    def factory(scope: RouteScope) -> _Provider:
        constructions.append(scope.request.scope_id)
        return _Provider(scope, requests)

    service = M07WorkflowService(bounded_project, factory)
    route = _route(bounded_project)
    authority_before = hashlib.sha256(storage.canonical_json(route)).hexdigest()
    window = build_bounded_narrative_window(
        route, entry_node_id="node-1", exit_node_id="node-4"
    )
    budget = BudgetPolicy(hard_calls=2, hard_tokens=100_000, hard_seconds=30)

    prepared = service.prepare(
        scope_ids=(), budget=budget, window_requests=(window.selection_request(),)
    )
    assert constructions == []
    assert prepared["window_ids"] == [window.id]
    assert prepared["windows"] == [window.to_dict()]
    with pytest.raises(PreparedRunError, match="selection_hash"):
        service.authorize_start(
            str(prepared["run_id"]),
            confirm_cloud=True,
            scope_ids=(),
            window_ids=(window.id,),
            budget=budget,
            selection_hash="0" * 64,
            authority_hash=str(prepared["authority_hash"]),
            recovered_source_acknowledgement=str(
                prepared["recovered_source_acknowledgement"]
            ),
            model=prepared["model"],
        )

    prepared = service.prepare(
        scope_ids=(), budget=budget, window_requests=(window.selection_request(),)
    )
    result = service.run_prepared(
        _strict_authorize(service, prepared, budget), cancelled=lambda: False
    )
    assert result["progress"]["scope_counts"]["validated"] == 1
    assert len(requests) == len(constructions) == 1
    request = requests[0]
    assert tuple(item["id"] for item in request.payload["nodes"]) == window.node_ids
    assert tuple(item["id"] for item in request.payload["edges"]) == window.internal_edge_ids
    assert tuple(item["id"] for item in request.payload["boundary_nodes"]) == (
        window.boundary_node_ids
    )
    assert tuple(item["id"] for item in request.payload["boundary_edges"]) == (
        window.boundary_edge_ids
    )
    assert tuple(item["id"] for item in request.payload["evidence"]) == window.evidence_ids

    replay = service.prepare(
        scope_ids=(), budget=budget, window_requests=(window.selection_request(),)
    )
    replay_result = service.run_prepared(
        _strict_authorize(service, replay, budget), cancelled=lambda: False
    )
    assert replay_result["progress"]["scope_counts"]["validated"] == 1
    assert len(requests) == len(constructions) == 1
    assert hashlib.sha256(storage.canonical_json(_route(bounded_project))).hexdigest() == (
        authority_before
    )


def test_subset_scope_consent_cancel_resume_and_stale_route_rejection(
    bounded_project: Path,
) -> None:
    requests: list[Any] = []
    service = M07WorkflowService(
        bounded_project,
        lambda scope: _Provider(scope, requests),
    )
    budget = BudgetPolicy(hard_calls=2, hard_tokens=100_000, hard_seconds=30)

    subset = service.prepare(scope_ids=("scope-entry",), budget=budget)
    assert subset["scope_ids"] == ["scope-entry"]
    with pytest.raises(PreparedRunError, match="exact subset"):
        service.authorize_start(
            str(subset["run_id"]),
            confirm_cloud=True,
            scope_ids=("scope-entry",),
            budget=budget,
        )

    subset = service.prepare(scope_ids=("scope-entry",), budget=budget)
    cancelled = service.run_prepared(
        _strict_authorize(service, subset, budget), cancelled=lambda: True
    )
    assert cancelled["progress"]["scope_counts"]["cancelled"] == 1
    assert requests == []

    resumed = service.prepare(scope_ids=("scope-entry",), budget=budget)
    completed = service.run_prepared(
        _strict_authorize(service, resumed, budget), cancelled=lambda: False
    )
    assert completed["progress"]["scope_counts"]["validated"] == 1
    assert len(requests) == 1

    stale = service.prepare(scope_ids=("scope-entry",), budget=budget)
    with Project.open(bounded_project) as project:
        route = project.payload("m07_route_map", "authoritative")
        assert isinstance(route, dict)
        coverage = dict(route["coverage"])
        coverage["control_nodes"] = 7
        route["coverage"] = coverage
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
    with pytest.raises(PreparedRunError, match="changed after preparation"):
        _strict_authorize(service, stale, budget)
    assert len(requests) == 1


def test_prepare_rejects_omitted_and_oversize_complete_scope_without_provider(
    bounded_project: Path,
) -> None:
    constructed = False

    def factory(_scope: RouteScope) -> Any:
        nonlocal constructed
        constructed = True
        raise AssertionError("prepare must not construct a provider")

    service = M07WorkflowService(bounded_project, factory)
    budget = BudgetPolicy(hard_calls=1, hard_tokens=100_000, hard_seconds=30)
    with pytest.raises(ValueError, match="explicit"):
        service.prepare(scope_ids=(), budget=budget)
    assert constructed is False

    with Project.open(bounded_project) as project:
        route = project.payload("m07_route_map", "authoritative")
        assert isinstance(route, dict)
        scopes = list(route["scopes"])
        oversized = dict(scopes[0])
        oversized["node_ids"] = [f"invented-{ordinal}" for ordinal in range(65)]
        scopes[0] = oversized
        route["scopes"] = scopes
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
    with pytest.raises(ValueError, match="exceeds bounded nodes"):
        service.prepare(scope_ids=("scope-entry",), budget=budget)
    assert constructed is False


def test_cancelled_companion_window_retries_without_replaying_validated_partial(
    bounded_project: Path,
) -> None:
    route = _route(bounded_project)
    first = build_bounded_narrative_window(route, node_ids=("node-0", "node-1"))
    second = build_bounded_narrative_window(route, node_ids=("node-4", "node-5"))
    constructions: list[str] = []
    requests: list[Any] = []
    cancelling_phase = True

    class CoordinatedProvider(_Provider):
        def organize(self, request: Any, progress: Any, cancelled: Callable[[], bool]) -> Any:
            if cancelling_phase and request.scope_id == second.id:
                raise OrganizationCancelledError("cancelled by test")
            return super().organize(request, progress, cancelled)

    def factory(scope: RouteScope) -> CoordinatedProvider:
        constructions.append(scope.request.scope_id)
        return CoordinatedProvider(scope, requests)

    service = M07WorkflowService(bounded_project, factory)
    budget = BudgetPolicy(hard_calls=4, hard_tokens=1_000_000, hard_seconds=30)
    window_requests = (first.selection_request(), second.selection_request())
    prepared = service.prepare(
        scope_ids=(), budget=budget, window_requests=window_requests
    )
    partial = service.run_prepared(
        _strict_authorize(service, prepared, budget), cancelled=lambda: False
    )
    counts = partial["progress"]["scope_counts"]
    assert counts["validated"] == 1
    assert counts["cancelled"] == 1
    assert [request.scope_id for request in requests] == [first.id]

    cancelling_phase = False
    resumed = service.prepare(
        scope_ids=(), budget=budget, window_requests=window_requests
    )
    complete = service.run_prepared(
        _strict_authorize(service, resumed, budget), cancelled=lambda: False
    )
    assert complete["progress"]["scope_counts"]["validated"] == 2
    assert [request.scope_id for request in requests] == [first.id, second.id]
    assert constructions.count(first.id) == 1
    assert constructions.count(second.id) == 2
