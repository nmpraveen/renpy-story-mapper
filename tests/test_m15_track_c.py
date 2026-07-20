from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from renpy_story_mapper.project import Project, create_ingested_project
from renpy_story_mapper.web.api import ApiProblem, ProjectApi
from renpy_story_mapper.web.state import UserStateStore

FIXTURE = Path(__file__).parent / "fixtures" / "linear.rpy"
CONTROL_REGIONS = Path(__file__).parent / "fixtures" / "m06" / "control_regions.rpy"
STATIC = Path(__file__).parents[1] / "src" / "renpy_story_mapper" / "web" / "static"


@dataclass
class _Dialogs:
    def choose_source(self, _kind: str) -> None:
        return None

    def choose_open_project(self) -> None:
        return None

    def choose_save_project(self) -> None:
        return None


def _project(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    project_path = tmp_path / "story.rsmproj"
    create_ingested_project(project_path, source).close()
    return source, project_path


def _api(tmp_path: Path, source: Path, project_path: Path) -> ProjectApi:
    api = ProjectApi(_Dialogs(), state_store=UserStateStore(tmp_path / "state.json"))
    api._retain_project_path(project_path, source)
    return api


def test_m15_bootstrap_and_map_are_read_only_bounded_and_provider_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, project_path = _project(tmp_path)
    api = _api(tmp_path, source, project_path)

    def prohibited(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("normal Narrative Map reads cannot solve routes or submit providers")

    monkeypatch.setattr(api, "_m12_solve", prohibited)
    try:
        bootstrap = api.dispatch("GET", "/api/v1/bootstrap", {})
        assert bootstrap["routes"]["m15"] == {
            "map": "/api/v1/m15/narrative-map",
            "detail": "/api/v1/m15/detail",
        }
        page = api.dispatch(
            "POST",
            "/api/v1/m15/narrative-map",
            {"query": None, "focus": None},
        )
        assert page["schema"] == "m15-narrative-map-page-v1"
        assert page["status"] == "available"
        assert page["level"] == "narrative_map"
        assert page["presentation_levels"] == ["narrative_map", "detail_evidence"]
        assert page["provider_calls"] == 0
        assert page["m12_requests"] == 0
        assert len(page["nodes"]) <= 120
        assert len(page["edges"]) <= 360
        assert page["nodes"]
        assert all(item["navigation"]["mode"] == "detail_evidence" for item in page["nodes"])
        assert all(item["authority_edge_ids"] for item in page["edges"])
        node_ids = {item["id"] for item in page["nodes"]}
        assert all(
            item["source_id"] in node_ids and item["target_id"] in node_ids
            for item in page["edges"]
        )
    finally:
        api.close()


def test_narrative_map_delivers_technical_nodes_and_complete_connectors(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "game"
    source_dir.mkdir()
    (source_dir / "story.rpy").write_bytes(CONTROL_REGIONS.read_bytes())
    project_path = tmp_path / "control-regions.rsmproj"
    create_ingested_project(project_path, source_dir).close()
    api = _api(tmp_path, source_dir, project_path)
    try:
        page = api.dispatch("POST", "/api/v1/m15/narrative-map", {})
        technical = [
            item for item in page["nodes"] if item["kind"] == "technical_coverage"
        ]
        assert technical
        node_ids = {item["id"] for item in page["nodes"]}
        assert len(page["edges"]) == page["total_edges"]
        assert all(
            item["source_id"] in node_ids and item["target_id"] in node_ids
            for item in page["edges"]
        )
        for item in technical:
            detail = api.dispatch(
                "POST", "/api/v1/m15/detail", {"element_id": item["id"]}
            )
            assert detail["element"]["id"] == item["id"]
            assert detail["evidence"]
    finally:
        api.close()


def test_every_narrative_map_element_opens_exact_bounded_detail(tmp_path: Path) -> None:
    source, project_path = _project(tmp_path)
    api = _api(tmp_path, source, project_path)
    try:
        page = api.dispatch("POST", "/api/v1/m15/narrative-map", {})
        element_ids = [item["id"] for item in page["nodes"]]
        element_ids.extend(item["id"] for item in page["edges"])
        for element_id in element_ids:
            detail = api.dispatch(
                "POST",
                "/api/v1/m15/detail",
                {"element_id": element_id},
            )
            assert detail["status"] == "available"
            assert detail["level"] == "detail_evidence"
            assert detail["element"]["id"] == element_id
            assert len(detail["evidence"]) <= 60
            assert detail["evidence"]
            for record in detail["evidence"]:
                assert record["source"]["path"]
                assert record["source"]["start"]["line"] >= 1
                assert str(record["line_basis"]).startswith(
                    ("physical_", "reconstructed_")
                )
    finally:
        api.close()


def test_project_without_current_narrative_map_has_labelled_safe_fallback(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    with Project.open(project_path) as project:
        project._require_open().execute(
            "DELETE FROM payloads WHERE collection='m11_analysis_state'"
        )
    api = _api(tmp_path, source, project_path)
    try:
        page = api.dispatch("POST", "/api/v1/m15/narrative-map", {})
        assert page["status"] == "unavailable"
        assert page["fallback"] == {
            "label": "Deterministic inspection fallback",
            "route": "/api/v1/m10/inspection-map",
            "view": "simplified",
        }
        with pytest.raises(ApiProblem, match="Narrative Map element"):
            api.dispatch(
                "POST",
                "/api/v1/m15/detail",
                {"element_id": "missing"},
            )
    finally:
        api.close()


def test_normal_browser_uses_narrative_map_and_retires_legacy_surfaces() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    api = (STATIC / "api.js").read_text(encoding="utf-8")
    contract = (STATIC / "contract.js").read_text(encoding="utf-8")

    for forbidden in (
        'id="routePanel"',
        'id="solveRoute"',
        "How do I reach this?",
        "Reach this scene",
        "AI Story Map",
        'id="organizeButton"',
        'id="organizationPanel"',
        'id="sceneMapButton"',
        'id="technicalMapButton"',
    ):
        assert forbidden not in html
    for forbidden in (
        "state.aiPage",
        "api.solveRoute(",
        "api.routeDestinations(",
        "api.prepareOrganization(",
        "api.startOrganization(",
    ):
        assert forbidden not in app
    assert 'narrativeMap: "/api/v1/m15/narrative-map"' in contract
    assert 'narrativeDetail: "/api/v1/m15/detail"' in contract
    assert "api.narrativeMap(" in app
    assert "api.narrativeDetail(" in app
    assert "async narrativeMap(" in api
    assert "async narrativeDetail(" in api
    assert 'id="advancedViews"' in html
    assert 'id="technicalToggle"' in html
    assert 'id="unresolvedToggle"' in html


def test_m13_stored_m12_citation_reader_remains_packaged() -> None:
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    api = (STATIC / "api.js").read_text(encoding="utf-8")

    assert 'navigation.mode === "m12_result"' in app
    assert 'openDetail(navigation.element_id, true, "scenes")' in app
    assert 'switchMode("scenes")' not in app
    assert "api.sceneDetail(elementId)" in app
    assert "api.routeResult(navigation.request_identity)" in app
    assert "async routeResult(requestIdentity)" in api
    assert 'const M12_ROUTE_KEYS = Object.freeze(["destinations", "solve", "result"]);' in api
