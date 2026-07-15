from __future__ import annotations

from pathlib import Path

import pytest

import renpy_story_mapper.presentation as presentation
import renpy_story_mapper.project_analysis as project_analysis
from renpy_story_mapper.project import (
    PayloadRecord,
    Project,
    create_ingested_project,
    refresh_ingested_project,
)
from renpy_story_mapper.storage import canonical_json

FIXTURE = Path(__file__).parent / "fixtures" / "m10" / "canonical_constructs.rpy"


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    return source


def _payload(project: Project, collection: str) -> dict[str, object]:
    value = project.payload(collection, "authoritative")
    assert isinstance(value, dict)
    return value


def test_successful_analysis_persists_one_generation_and_phase_progress(tmp_path: Path) -> None:
    source = _source(tmp_path)
    progress: list[tuple[str, int]] = []
    with create_ingested_project(
        tmp_path / "story.rsmproj",
        source,
        progress=lambda phase, percent: progress.append((phase, percent)),
    ) as project:
        state = _payload(project, "m10_analysis_state")
        canonical = _payload(project, "m10_canonical_graph")

    assert state["status"] == "current_complete"
    assert state["canonical_availability"] == "current_complete"
    assert state["simplified_availability"] == "current_complete"
    assert state["source_generation"] == canonical["source_generation"]
    assert {item["source_generation"] for item in state["phases"]} == {state["source_generation"]}
    assert [item["phase"] for item in state["phases"]] == [
        "source_inventory",
        "parse",
        "graph",
        "semantic_state",
        "control_flow",
        "route_map",
        "canonical_graph",
        "simplified_projection",
        "inspection_projection",
    ]
    assert all(
        isinstance(item["duration_seconds"], (int, float))
        and item["duration_seconds"] >= 0
        for item in state["phases"]
    )
    assert progress == [
        ("source_inventory", 5),
        ("parse", 20),
        ("graph", 35),
        ("semantic_state", 50),
        ("control_flow", 65),
        ("route_map", 75),
        ("canonical_graph", 85),
        ("simplified_projection", 92),
        ("inspection_projection", 96),
        ("story_atoms", 97),
        ("scene_boundaries", 98),
        ("scene_assembly", 99),
        ("scene_presentation", 99),
        ("complete", 100),
    ]


def test_operational_phase_timings_do_not_change_canonical_structural_bytes(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    first_path = tmp_path / "first.rsmproj"
    second_path = tmp_path / "second.rsmproj"
    create_ingested_project(first_path, source).close()
    create_ingested_project(second_path, source).close()

    with Project.open(first_path) as first, Project.open(second_path) as second:
        first_canonical = _payload(first, "m10_canonical_graph")
        second_canonical = _payload(second, "m10_canonical_graph")
        first_state = _payload(first, "m10_analysis_state")
        second_state = _payload(second, "m10_analysis_state")

    assert canonical_json(first_canonical) == canonical_json(second_canonical)
    assert all("duration_seconds" in item for item in first_state["phases"])
    assert all("duration_seconds" in item for item in second_state["phases"])


def test_coherent_unchanged_refresh_reuses_every_analysis_phase_without_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    project_path = tmp_path / "story.rsmproj"
    create_ingested_project(project_path, source).close()
    before_database = project_path.read_bytes()
    with Project.open(project_path) as project:
        before_canonical = _payload(project, "m10_canonical_graph")
        before_projection = _payload(project, "m10_inspection_projection")

    def unexpected_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("unchanged refresh called an expensive phase or backup")

    for name in (
        "build_graph",
        "build_semantic_story",
        "extract_state",
        "analyze_control_flow",
        "project_route_map",
        "build_canonical_graph",
        "project_inspection_graph",
    ):
        monkeypatch.setattr(project_analysis, name, unexpected_call)
    monkeypatch.setattr(presentation, "rebuild_presentation_index", unexpected_call)
    monkeypatch.setattr(Project, "backup", unexpected_call)
    progress: list[tuple[str, int]] = []

    report = refresh_ingested_project(
        project_path,
        source,
        progress=lambda phase, percent: progress.append((phase, percent)),
    )

    assert report.parsed_sources == ()
    assert report.reused_sources == ("game/story.rpy",)
    assert report.invalidated_sources == ()
    assert report.removed_sources == ()
    assert report.reused_phases == project_analysis.REUSABLE_ANALYSIS_PHASES
    assert progress == [("complete", 100)]
    assert project_path.read_bytes() == before_database
    with Project.open(project_path) as project:
        assert _payload(project, "m10_canonical_graph") == before_canonical
        assert _payload(project, "m10_inspection_projection") == before_projection


def test_unchanged_refresh_recomputes_when_analysis_state_is_not_current_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    project_path = tmp_path / "story.rsmproj"
    create_ingested_project(project_path, source).close()
    with Project.open(project_path) as project:
        state = _payload(project, "m10_analysis_state")
        state["status"] = "failed"
        project.write_payloads((PayloadRecord("m10_analysis_state", "authoritative", state),))

    def expected_recomputation(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("coherence failure must not use the unchanged fast path")

    monkeypatch.setattr(project_analysis, "build_graph", expected_recomputation)

    with pytest.raises(AssertionError, match="coherence failure"):
        refresh_ingested_project(project_path, source)


def test_failed_new_route_phase_keeps_last_good_canonical_graph_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    project_path = tmp_path / "story.rsmproj"
    create_ingested_project(project_path, source).close()
    with Project.open(project_path) as project:
        old_canonical = _payload(project, "m10_canonical_graph")
        old_projection = _payload(project, "m10_inspection_projection")
    (source / "story.rpy").write_text(
        FIXTURE.read_text(encoding="utf-8").replace("Trust changed.", "Trust changed now."),
        encoding="utf-8",
    )

    def fail_route(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("injected route projection failure")

    monkeypatch.setattr(project_analysis, "project_route_map", fail_route)
    with pytest.raises(RuntimeError, match="injected route"):
        refresh_ingested_project(project_path, source)

    with Project.open(project_path) as project:
        state = _payload(project, "m10_analysis_state")
        canonical = _payload(project, "m10_canonical_graph")
        projection = _payload(project, "m10_inspection_projection")
        assert project.payload("m01_graph", "authoritative") is not None
        assert project.payload("m06_control_flow", "authoritative") is not None
        assert project.payload("m07_route_map", "authoritative") is None
    assert canonical == old_canonical
    assert projection == old_projection
    assert state["status"] == "failed"
    assert state["canonical_availability"] == "stale"
    assert state["simplified_availability"] == "stale"
    assert state["failure"]["phase"] == "route_map"
    assert state["failure"]["duration_seconds"] >= 0
    assert state["source_generation"] != canonical["source_generation"]
    assert {item["source_generation"] for item in state["phases"]} == {state["source_generation"]}


def test_failed_simplified_projection_keeps_new_canonical_and_old_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    project_path = tmp_path / "story.rsmproj"
    create_ingested_project(project_path, source).close()
    with Project.open(project_path) as project:
        old_projection = _payload(project, "m10_inspection_projection")
    (source / "story.rpy").write_text(
        FIXTURE.read_text(encoding="utf-8").replace(
            "Trust changed.", "Trust changed before projection."
        ),
        encoding="utf-8",
    )

    def fail_projection(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("injected simplified projection failure")

    monkeypatch.setattr(project_analysis, "project_inspection_graph", fail_projection)
    with pytest.raises(RuntimeError, match="injected simplified"):
        refresh_ingested_project(project_path, source)

    with Project.open(project_path) as project:
        state = _payload(project, "m10_analysis_state")
        canonical = _payload(project, "m10_canonical_graph")
        projection = _payload(project, "m10_inspection_projection")
    assert state["status"] == "failed"
    assert state["canonical_availability"] == "current_complete"
    assert state["simplified_availability"] == "unavailable"
    assert state["failure"]["phase"] == "simplified_projection"
    assert state["failure"]["duration_seconds"] >= 0
    assert canonical["source_generation"] == state["source_generation"]
    assert projection == old_projection
    assert projection["source_generation"] != state["source_generation"]


def test_failed_later_projection_keeps_current_canonical_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    project_path = tmp_path / "story.rsmproj"
    create_ingested_project(project_path, source).close()
    (source / "story.rpy").write_text(
        FIXTURE.read_text(encoding="utf-8").replace("Trust changed.", "Trust changed later."),
        encoding="utf-8",
    )

    def fail_projection(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected inspection failure")

    monkeypatch.setattr(presentation, "rebuild_presentation_index", fail_projection)
    with pytest.raises(RuntimeError, match="injected inspection"):
        refresh_ingested_project(project_path, source)

    with Project.open(project_path) as project:
        state = _payload(project, "m10_analysis_state")
        canonical = _payload(project, "m10_canonical_graph")
    assert state["status"] == "failed"
    assert state["canonical_availability"] == "current_complete"
    assert state["simplified_availability"] == "current_complete"
    assert state["failure"]["phase"] == "inspection_projection"
    assert state["failure"]["duration_seconds"] >= 0
    assert state["source_generation"] == canonical["source_generation"]


def test_failed_initial_analysis_retains_current_partial_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    project_path = tmp_path / "partial.rsmproj"

    def fail_control(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("injected control failure")

    monkeypatch.setattr(project_analysis, "analyze_control_flow", fail_control)
    with pytest.raises(RuntimeError, match="injected control"):
        create_ingested_project(project_path, source)

    assert project_path.is_file()
    with Project.open(project_path) as project:
        state = _payload(project, "m10_analysis_state")
        assert project.payload("m01_graph", "authoritative") is not None
        assert project.payload("m02_semantic", "authoritative") is not None
        assert project.payload("m10_canonical_graph", "authoritative") is None
    assert state["status"] == "failed"
    assert state["canonical_availability"] == "none"
    assert state["simplified_availability"] == "none"
    assert state["failure"]["phase"] == "control_flow"
    assert state["failure"]["duration_seconds"] >= 0
