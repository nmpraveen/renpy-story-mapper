from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from renpy_story_mapper.project import Project, create_ingested_project
from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.inspection_api import inspection_detail, inspection_page
from renpy_story_mapper.web.state import UserStateStore

FIXTURE = Path(__file__).parent / "fixtures" / "m10" / "canonical_constructs.rpy"
STATIC = Path(__file__).resolve().parents[1] / "src" / "renpy_story_mapper" / "web" / "static"


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


def _payloads(project_path: Path) -> tuple[dict[str, object], ...]:
    with Project.open(project_path) as project:
        values = (
            project.payload("m10_inspection_projection", "authoritative"),
            project.payload("m10_canonical_graph", "authoritative"),
            project.payload("m10_analysis_state", "authoritative"),
        )
    assert all(isinstance(item, dict) for item in values)
    return values  # type: ignore[return-value]


@pytest.mark.parametrize("view", ["simplified", "canonical"])
def test_m10_pages_are_generation_labeled_and_hard_bounded(tmp_path: Path, view: str) -> None:
    _, project_path = _project(tmp_path)
    projection, canonical, state = _payloads(project_path)
    page = inspection_page(
        projection,
        canonical,
        state,
        view=view,
        offset=0,
        limit=3,
        edge_offset=0,
        edge_limit=4,
    )

    assert page["view"] == view
    assert page["generation_status"]["freshness"] == "current"
    assert len(page["nodes"]) <= 3
    assert len(page["edges"]) <= 4
    assert page["limit"] == 3
    assert page["edge_limit"] == 4
    assert len(str(page["authority_hash"])) == 64

    with pytest.raises(ValueError, match="node limit"):
        inspection_page(
            projection,
            canonical,
            state,
            view=view,
            offset=0,
            limit=31,
            edge_offset=0,
            edge_limit=4,
        )


def test_simplified_detail_has_evidence_and_direct_canonical_focus(tmp_path: Path) -> None:
    _, project_path = _project(tmp_path)
    projection, canonical, state = _payloads(project_path)
    outcome = next(item for item in projection["nodes"] if item["title"] == "Help")
    detail = inspection_detail(
        projection,
        canonical,
        state,
        view="simplified",
        element_id=outcome["id"],
    )

    assert detail["element"]["title"] == "Help"
    assert detail["canonical_escape_ids"]
    assert detail["canonical_focus_id"] in detail["canonical_escape_ids"]
    assert isinstance(detail["canonical_focus_offset"], int)
    assert detail["canonical_records"]
    assert detail["evidence"]
    assert detail["requirements"][0]["expression"] == "ready"
    assert len(detail["evidence"]) <= 60


def test_project_api_exposes_bounded_m10_map_and_detail(tmp_path: Path) -> None:
    source, project_path = _project(tmp_path)
    api = ProjectApi(_Dialogs(), state_store=UserStateStore(tmp_path / "state.json"))
    try:
        api._retain_project_path(project_path, source)
        page = api.dispatch(
            "POST",
            "/api/v1/m10/inspection-map",
            {
                "view": "simplified",
                "offset": 0,
                "limit": 30,
                "edge_offset": 0,
                "edge_limit": 180,
            },
        )
        assert isinstance(page, dict)
        outcome = next(item for item in page["nodes"] if item["kind"] == "choice_outcome")
        detail = api.dispatch(
            "POST",
            "/api/v1/m10/detail",
            {"view": "simplified", "element_id": outcome["id"]},
        )
        assert detail["canonical_focus_id"]
    finally:
        api.close()


def test_packaged_ui_has_bounded_inspection_and_canonical_escape() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    graph = (STATIC / "graph.js").read_text(encoding="utf-8")
    contract = (STATIC / "contract.js").read_text(encoding="utf-8")

    assert 'id="inspectionMapButton"' in html
    assert 'id="canonicalMapButton"' in html
    assert 'id="canonicalEscapeButton"' in html
    assert 'id="generationStatus"' in html
    assert "api.inspectionMap" in app and "api.inspectionDetail" in app
    assert "canonical_focus_offset" in app
    assert 'inspectionMap: "/api/v1/m10/inspection-map"' in contract
    assert "nodes: 30" in contract and "edges: 180" in contract
    assert "bezierCurveTo" in graph
    assert "forceSimulation" not in graph and "requestAnimationFrame" not in graph
