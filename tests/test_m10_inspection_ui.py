from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

import renpy_story_mapper.project_analysis as project_analysis
from renpy_story_mapper.project import (
    PayloadRecord,
    Project,
    create_ingested_project,
    refresh_ingested_project,
)
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


def _large_project(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "large-game"
    source.mkdir()
    lines = ["label start:\n"]
    lines.extend(f'    "Scene {index:02d} unique text."\n' for index in range(45))
    lines.extend(
        [
            "    return\n",
            "\n",
            "label hidden_label:\n",
            '    "Hidden label content."\n',
            "    return\n",
        ]
    )
    (source / "story.rpy").write_text("".join(lines), encoding="utf-8")
    project_path = tmp_path / "large-story.rsmproj"
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


def test_opaque_creator_python_has_explicit_preserved_not_executed_status(
    tmp_path: Path,
) -> None:
    _, project_path = _project(tmp_path)
    projection, canonical, state = _payloads(project_path)
    page = inspection_page(
        projection,
        canonical,
        state,
        view="canonical",
        offset=0,
        limit=30,
        edge_offset=0,
        edge_limit=180,
    )
    opaque = next(item for item in page["nodes"] if item["source_kind"] == "opaque")

    assert opaque["unsupported_status"] == (
        "Unsupported creator Python · preserved, not executed"
    )
    assert opaque["summary"] == opaque["unsupported_status"]
    assert opaque["unresolved"] is False


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


def test_whole_graph_search_and_exact_focus_open_the_bounded_target_page(
    tmp_path: Path,
) -> None:
    source, project_path = _large_project(tmp_path)
    with Project.open(project_path) as project:
        canonical = project.payload("m10_canonical_graph", "authoritative")
    assert isinstance(canonical, dict)
    target = next(
        item
        for item in canonical["nodes"]
        if item["attributes"].get("source_text") == '"Scene 44 unique text."'
    )

    api = ProjectApi(_Dialogs(), state_store=UserStateStore(tmp_path / "state.json"))
    try:
        api._retain_project_path(project_path, source)

        def page(**extra: object) -> dict[str, object]:
            value = api.dispatch(
                "POST",
                "/api/v1/m10/inspection-map",
                {
                    "view": "canonical",
                    "offset": 0,
                    "limit": 30,
                    "edge_offset": 0,
                    "edge_limit": 180,
                    **extra,
                },
            )
            assert isinstance(value, dict)
            return value

        searched = page(query="Scene 44 unique text")
        assert searched["offset"] >= 30
        assert searched["search"]["focus"]["element_id"] == target["id"]
        assert target["id"] in {item["id"] for item in searched["nodes"]}

        for exact in (target["id"], target["graph_node_id"], "hidden_label"):
            focused = page(focus=exact)
            focus = focused["search"]["focus"]
            assert focus["offset"] == focused["offset"]
            assert focus["element_id"] in {item["id"] for item in focused["nodes"]}

        by_location = page(query="story.rpy:46")
        assert by_location["search"]["total_matches"] >= 1
    finally:
        api.close()


def test_region_fact_evidence_and_proof_details_are_directly_inspectable(
    tmp_path: Path,
) -> None:
    _, project_path = _project(tmp_path)
    projection, canonical, state = _payloads(project_path)
    for expression, field_kinds in (
        ("ready", ("condition", "guard")),
        ("trust += 1", ("fact",)),
    ):
        search_page = inspection_page(
            projection,
            canonical,
            state,
            view="canonical",
            offset=0,
            limit=30,
            edge_offset=0,
            edge_limit=180,
            query=expression,
        )
        assert any(
            any(
                field_kind in item["field"] or field_kind == item["record_kind"]
                for field_kind in field_kinds
            )
            for item in search_page["search"]["matches"]
        )
    region_id = projection["regions"][0]["canonical_region_id"]
    detail = inspection_detail(
        projection,
        canonical,
        state,
        view="simplified",
        element_id=region_id,
    )

    region = detail["region"]
    assert detail["element"]["kind"] == "branch_region"
    assert region["classification"]
    assert region["split_node_id"]
    assert "merge_node_id" in region
    assert region["ordered_arms"]
    assert all(
        "member_count" in arm
        and "gate_facts" in arm
        and "effect_facts" in arm
        and "terminal_summary" in arm
        for arm in region["ordered_arms"]
    )
    assert "persistence_reasons" in region
    assert "unresolved_arm_count" in region
    assert region["terminal_summaries"]
    assert region["origins"]
    assert detail["proofs"]
    assert detail["canonical_escape_ids"]
    ready_arm = next(
        arm
        for projected_region in projection["regions"]
        for arm in inspection_detail(
            projection,
            canonical,
            state,
            view="simplified",
            element_id=projected_region["canonical_region_id"],
        )["region"]["ordered_arms"]
        if arm.get("predicate", {}).get("expression") == "ready"
    )
    assert ready_arm["predicate"]["kind"] == "menu_choice"
    assert ready_arm["predicate"]["polarity"] == "positive"
    assert ready_arm["predicate"]["requirement_fact_ids"]

    arm_expressions = {
        str(fact["expression"])
        for projected_region in projection["regions"]
        for arm in inspection_detail(
            projection,
            canonical,
            state,
            view="simplified",
            element_id=projected_region["canonical_region_id"],
        )["region"]["ordered_arms"]
        for fact in arm["facts"]
    }
    assert "trust += 1" in arm_expressions

    proof_detail = inspection_detail(
        projection,
        canonical,
        state,
        view="simplified",
        element_id=detail["proofs"][0]["id"],
    )
    assert proof_detail["element"]["kind"] == "proof"
    assert proof_detail["proofs"][0]["explanation"]

    outcome = next(item for item in projection["nodes"] if item["title"] == "Help")
    outcome_detail = inspection_detail(
        projection,
        canonical,
        state,
        view="simplified",
        element_id=outcome["id"],
    )
    assert outcome_detail["regions"]
    assert outcome_detail["proofs"]
    assert {item["kind"] for item in outcome_detail["linked_records"]} >= {
        "region",
        "evidence",
        "proof",
    }
    fact = outcome_detail["facts"][0]
    fact_detail = inspection_detail(
        projection,
        canonical,
        state,
        view="simplified",
        element_id=fact["id"],
    )
    assert fact_detail["element"]["kind"] == "fact"
    assert fact_detail["evidence"]


def test_canonical_api_survives_initial_simplified_projection_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    project_path = tmp_path / "partial.rsmproj"

    def fail_projection(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("injected simplified projection failure")

    monkeypatch.setattr(project_analysis, "project_inspection_graph", fail_projection)
    with pytest.raises(RuntimeError, match="injected simplified"):
        create_ingested_project(project_path, source)

    api = ProjectApi(_Dialogs(), state_store=UserStateStore(tmp_path / "state.json"))
    try:
        api._retain_project_path(project_path, source)
        canonical = api.dispatch(
            "POST",
            "/api/v1/m10/inspection-map",
            {
                "view": "canonical",
                "offset": 0,
                "limit": 30,
                "edge_offset": 0,
                "edge_limit": 180,
            },
        )
        assert canonical["status"] == "available"
        assert canonical["nodes"]
        assert canonical["generation_status"]["failure"]["phase"] == "simplified_projection"
        detail = api.dispatch(
            "POST",
            "/api/v1/m10/detail",
            {
                "view": "canonical",
                "element_id": canonical["nodes"][0]["id"],
            },
        )
        assert detail["canonical_records"]

        simplified = api.dispatch(
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
        assert simplified["status"] == "unavailable"
        assert simplified["reason"] == "projection_missing"
        assert simplified["generation_status"]["failure"]["phase"] == "simplified_projection"
    finally:
        api.close()


def test_stale_projection_is_never_composed_with_newer_canonical_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, project_path = _project(tmp_path)
    with Project.open(project_path) as project:
        old_projection = project.payload("m10_inspection_projection", "authoritative")
    assert isinstance(old_projection, dict)
    stale_outcome = next(item for item in old_projection["nodes"] if item["title"] == "Help")

    (source / "story.rpy").write_text(
        FIXTURE.read_text(encoding="utf-8").replace('"Help"', '"Assist"'),
        encoding="utf-8",
    )

    def fail_projection(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("injected simplified projection failure")

    monkeypatch.setattr(project_analysis, "project_inspection_graph", fail_projection)
    with pytest.raises(RuntimeError, match="injected simplified"):
        refresh_ingested_project(project_path, source)

    api = ProjectApi(_Dialogs(), state_store=UserStateStore(tmp_path / "state.json"))
    try:
        api._retain_project_path(project_path, source)
        canonical = api.dispatch(
            "POST",
            "/api/v1/m10/inspection-map",
            {
                "view": "canonical",
                "offset": 0,
                "limit": 30,
                "edge_offset": 0,
                "edge_limit": 180,
            },
        )
        assert canonical["status"] == "available"
        assert canonical["generation_status"]["freshness"] == "current"

        simplified = api.dispatch(
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
        assert simplified["status"] == "unavailable"
        assert simplified["reason"] == "projection_generation_mismatch"

        stale_detail = api.dispatch(
            "POST",
            "/api/v1/m10/detail",
            {"view": "simplified", "element_id": stale_outcome["id"]},
        )
        assert stale_detail["status"] == "unavailable"
        assert "canonical_records" not in stale_detail
    finally:
        api.close()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", 999, "incompatible M10 generation state"),
        ("canonical_hash", "0" * 64, "does not bind the canonical graph"),
    ],
)
def test_m10_api_rejects_unbound_analysis_state(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    source, project_path = _project(tmp_path)
    with Project.open(project_path) as project:
        state = project.payload("m10_analysis_state", "authoritative")
        assert isinstance(state, dict)
        project.write_payloads(
            (
                PayloadRecord(
                    "m10_analysis_state",
                    "authoritative",
                    {**state, field: value},
                ),
            )
        )

    api = ProjectApi(_Dialogs(), state_store=UserStateStore(tmp_path / "state.json"))
    try:
        api._retain_project_path(project_path, source)
        with pytest.raises(ValueError, match=message):
            api.dispatch(
                "POST",
                "/api/v1/m10/inspection-map",
                {
                    "view": "canonical",
                    "offset": 0,
                    "limit": 30,
                    "edge_offset": 0,
                    "edge_limit": 180,
                },
            )
    finally:
        api.close()


def test_failed_refresh_reports_coherent_last_known_good_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, project_path = _project(tmp_path)
    (source / "story.rpy").write_text(
        FIXTURE.read_text(encoding="utf-8").replace("Trust changed.", "Trust changed now."),
        encoding="utf-8",
    )

    def fail_route(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("injected route projection failure")

    monkeypatch.setattr(project_analysis, "project_route_map", fail_route)
    with pytest.raises(RuntimeError, match="injected route"):
        refresh_ingested_project(project_path, source)

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
        status = page["generation_status"]
        assert page["status"] == "available"
        assert status["freshness"] == "stale"
        assert status["last_known_good"] is True
        assert status["failure"]["phase"] == "route_map"
        assert status["failure"]["code"]
        assert status["completed_phases"]
    finally:
        api.close()


def test_failure_before_canonical_graph_returns_bounded_partial_analysis_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    project_path = tmp_path / "early-partial.rsmproj"

    def fail_control(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("injected control failure")

    monkeypatch.setattr(project_analysis, "analyze_control_flow", fail_control)
    with pytest.raises(RuntimeError, match="injected control"):
        create_ingested_project(project_path, source)

    api = ProjectApi(_Dialogs(), state_store=UserStateStore(tmp_path / "state.json"))
    try:
        api._retain_project_path(project_path, source)
        result = api.dispatch(
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
        status = result["generation_status"]
        assert result["status"] == "unavailable"
        assert status["failure"]["phase"] == "control_flow"
        assert status["canonical_availability"] == "none"
        assert status["completed_phases"] == [
            "source_inventory",
            "parse",
            "graph",
            "semantic_state",
        ]
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


def test_packaged_ui_enters_retained_workspace_and_persists_failure_context() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")

    assert 'id="analysisFailureBanner"' in html
    assert "enterAvailableWorkspace" in app
    assert "completed_phases" in app
    assert "last_known_good" in app
    assert "inspectionCurrent" in app and "canonicalCurrent" in app
    assert "comparison.default_view" not in app
    assert "searchM10WholeGraph" in app
    assert "renderInspectionDerivations" in app
