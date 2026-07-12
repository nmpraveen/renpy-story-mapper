"""Independent adversarial review coverage for the integrated M07 branch.

Known production defects are strict xfails: they document a bounded reproduction while
keeping the independent-review suite useful until production owners apply a fix.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from renpy_story_mapper.control_flow import analyze_control_flow
from renpy_story_mapper.graph import build_graph
from renpy_story_mapper.organization.contracts import M05_CLOUD_MODEL
from renpy_story_mapper.organization.parallel import SchedulerConfig
from renpy_story_mapper.parser import parse_script
from renpy_story_mapper.project import create_ingested_project
from renpy_story_mapper.route_map import (
    RouteCoverage,
    RouteEdge,
    RouteLaneKind,
    RouteMap,
    RouteNode,
    RouteNodeKind,
    project_route_map,
)
from renpy_story_mapper.semantic import build_semantic_story
from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.contracts import M07_API_ROUTES
from renpy_story_mapper.web.security import redact_message, safe_request_path, valid_origin


class _Dialogs:
    def choose_source(self, _kind: str) -> Path | None:
        return None

    def choose_open_project(self) -> Path | None:
        return None

    def choose_save_project(self) -> Path | None:
        return None


@pytest.fixture
def review_project(tmp_path: Path) -> Path:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_text(
        '''label start:
    menu:
        "Stay":
            "A warm moment."
        "Leave":
            "A quiet exit."
    return
''',
        encoding="utf-8",
    )
    destination = tmp_path / "review.rsmproj"
    create_ingested_project(destination, source).close()
    return destination


def _api(project: Path) -> ProjectApi:
    def forbidden_provider(_scope: object) -> Any:
        raise AssertionError("review must not construct or invoke a provider")

    api = ProjectApi(_Dialogs(), m07_provider_factory=forbidden_provider)
    api._project_path = project
    return api


def test_loopback_and_path_redaction_reject_ambiguous_adversarial_inputs() -> None:
    port = 43127
    assert valid_origin(f"http://127.0.0.1:{port}", port)
    for origin in (
        f"http://localhost:{port}",
        f"http://127.0.0.1:{port}/path",
        f"https://127.0.0.1:{port}",
        f"http://127.0.0.1:{port}@evil.example",
    ):
        assert not valid_origin(origin, port)

    for raw_path in ("/../secret", "/%2e%2e/secret", "/safe%5c..%5csecret", "relative"):
        assert safe_request_path(raw_path) is None
    assert safe_request_path("/api/v1/m07/route-map?ignored=yes") == "/api/v1/m07/route-map"

    message = r"failed at C:\Users\reviewer\private\story.rpy and /home/reviewer/private.db"
    redacted = redact_message(message)
    assert "reviewer" not in redacted
    assert "story.rpy" not in redacted
    assert "private.db" not in redacted


def test_story_analysis_configuration_is_exactly_locked() -> None:
    config = SchedulerConfig()
    assert config.initial_workers == 8
    assert config.maximum_workers == 12
    assert config.maximum_repairs == 2
    assert config.model == M05_CLOUD_MODEL == "gpt-5.6-luna"
    assert config.reasoning_profile == "high"
    assert config.fast_mode is False

    with pytest.raises(ValueError, match="locked"):
        SchedulerConfig(model="gpt-5.6-sol")
    with pytest.raises(ValueError, match="locked"):
        SchedulerConfig(fast_mode=True)
    with pytest.raises(ValueError, match="exactly two"):
        SchedulerConfig(maximum_repairs=3)


@pytest.mark.xfail(
    strict=True,
    reason="backend route-map payload uses 'lines' while packaged browser requires 'edges'",
)
def test_integrated_route_payload_satisfies_packaged_browser_contract(review_project: Path) -> None:
    api = _api(review_project)
    try:
        page = api.dispatch("POST", M07_API_ROUTES["route_map"], {"offset": 0, "limit": 30})
    finally:
        api.close()

    assert isinstance(page, dict)
    assert isinstance(page.get("nodes"), list)
    assert isinstance(page.get("edges"), list)
    assert isinstance(page.get("total_nodes"), int)
    assert len(page["nodes"]) + len(page["edges"]) <= 240


@pytest.mark.xfail(
    strict=True,
    reason="route pagination returns every incident edge and can exceed the 240-item render cap",
)
def test_route_page_never_exceeds_the_hard_render_cap() -> None:
    nodes = tuple(
        RouteNode(
            id=f"node-{index}",
            control_node_id=f"control-{index}",
            kind=RouteNodeKind.MILESTONE,
            title=f"Node {index}",
            lane_id="lane_spine",
            lane_kind=RouteLaneKind.SPINE,
            order=index,
            evidence_ids=(),
        )
        for index in range(30)
    )
    edges = tuple(
        RouteEdge(
            id=f"edge-{index}",
            source_id=nodes[0].id,
            target_id=nodes[(index % 29) + 1].id,
            role="choice",
            lane_id="lane_spine",
            control_edge_ids=(f"control-edge-{index}",),
            control_node_ids=(
                nodes[0].control_node_id,
                nodes[(index % 29) + 1].control_node_id,
            ),
            gate_ids=(),
            effect_ids=(),
            evidence_ids=(),
        )
        for index in range(211)
    )
    route = RouteMap(
        nodes=nodes,
        edges=edges,
        scopes=(),
        coverage=RouteCoverage(30, 30, 0, 0, 0),
    )

    page = route.page()
    assert len(page["nodes"]) + len(page["edges"]) <= 240


@pytest.mark.xfail(
    strict=True,
    reason="browser organization view consumes a different status schema than the backend emits",
)
def test_integrated_organization_status_satisfies_browser_view_contract(
    review_project: Path,
) -> None:
    api = _api(review_project)
    try:
        status = api.dispatch("GET", M07_API_ROUTES["organization"], {})
    finally:
        api.close()

    assert isinstance(status, dict)
    assert status["status"] in {"idle", "running", "cancelled", "partial", "review_ready"}
    assert isinstance(status["scopes"], dict)
    assert isinstance(status["coverage"], dict)
    assert {"used", "budget"} <= status["tokens"].keys()
    assert "assembly_id" in status


@pytest.mark.xfail(
    strict=True,
    reason="persistent route edges receive unrelated edge-lane IDs and lose route identity",
)
def test_persistent_route_edges_preserve_their_route_lane_identity() -> None:
    fixture = Path(__file__).parent / "fixtures" / "m06" / "control_regions.rpy"
    with fixture.open(encoding="utf-8") as stream:
        graph = build_graph(
            [parse_script("m06/control_regions.rpy", stream)], entry_label="terminal_routes"
        )
    semantic = build_semantic_story(graph)
    route = project_route_map(analyze_control_flow(graph, semantic).to_dict(), semantic)

    persistent_nodes = {
        node.id: node.lane_id
        for node in route.nodes
        if node.lane_kind is RouteLaneKind.PERSISTENT
    }
    assert persistent_nodes
    incident = [
        edge
        for edge in route.edges
        if edge.source_id in persistent_nodes or edge.target_id in persistent_nodes
    ]
    assert incident
    for edge in incident:
        endpoint_lanes = {
            persistent_nodes[node_id]
            for node_id in (edge.source_id, edge.target_id)
            if node_id in persistent_nodes
        }
        assert edge.lane_id in endpoint_lanes
