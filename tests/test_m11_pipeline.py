from __future__ import annotations

from pathlib import Path

import pytest

import renpy_story_mapper.project_analysis as project_analysis
from renpy_story_mapper.m11_persistence import M11_PHASES, M11Availability
from renpy_story_mapper.m11_scene_projection import scene_model_from_phase_results
from renpy_story_mapper.project import Project, create_ingested_project, refresh_ingested_project
from renpy_story_mapper.storage import canonical_json

FIXTURE = Path(__file__).parent / "fixtures" / "m11" / "human_scenes.rpy"


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    return source


def _mapping(project: Project, collection: str) -> dict[str, object]:
    value = project.payload(collection, "authoritative")
    assert isinstance(value, dict)
    return value


def test_refresh_publishes_exactly_four_current_m11_phases(tmp_path: Path) -> None:
    source = _source(tmp_path)
    with create_ingested_project(tmp_path / "story.rsmproj", source) as project:
        canonical = _mapping(project, "m10_canonical_graph")
        selection = project.m11_persistence().select(canonical)

    assert selection.availability is M11Availability.CURRENT_COMPLETE
    assert selection.phase_results is not None
    assert tuple(selection.phase_results) == M11_PHASES
    model = scene_model_from_phase_results(
        canonical,
        selection.phase_results["story_atoms"],
        selection.phase_results["scene_boundaries"],
        selection.phase_results["scene_assembly"],
    )
    model.validate()
    presentation = selection.phase_results["scene_presentation"]
    assert presentation["binding"] == model.binding.to_dict()
    assert presentation["scene_model_hash"] == model.structural_hash


def test_human_scene_contracts_cover_branches_calls_lanes_chapters_and_loops(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    with create_ingested_project(tmp_path / "contracts.rsmproj", source) as project:
        canonical = _mapping(project, "m10_canonical_graph")
        selection = project.m11_persistence().select(canonical)
        assert selection.phase_results is not None
        model = scene_model_from_phase_results(
            canonical,
            selection.phase_results["story_atoms"],
            selection.phase_results["scene_boundaries"],
            selection.phase_results["scene_assembly"],
        )

    region_by_id = {item["id"]: item for item in canonical["regions"]}
    node_by_id = {item["id"]: item for item in canonical["nodes"]}
    temporary_kinds = {
        "local_detour",
        "optional_detour",
        "reconvergent_route_segment",
    }
    assert any(
        len(arm.scene_ids) >= 2
        for branch in model.temporary_branches
        for arm in branch.arms
    )
    assert any(
        all(not arm.scene_ids for arm in branch.arms)
        for branch in model.temporary_branches
    )
    assert all(
        region_by_id[branch.canonical_region_id]["kind"] in temporary_kinds
        for branch in model.temporary_branches
    )
    assert all(
        lane.canonical_region_id is None
        or region_by_id[lane.canonical_region_id]["kind"]
        in {"persistent_route", "terminal_split"}
        for lane in model.lanes
    )

    occurrences_by_label: dict[str, list[object]] = {}
    for occurrence in model.occurrences:
        label = node_by_id[occurrence.callee_entry_node_id]["label"]
        occurrences_by_label.setdefault(label, []).append(occurrence)
    shared = occurrences_by_label["shared_memory"]
    assert len(shared) >= 3
    assert len({item.lane_id for item in shared}) >= 2
    technical = occurrences_by_label["technical_helper"]
    assert len(technical) == 1
    assert technical[0].collapsed and not technical[0].referenced_atom_ids
    guarded = occurrences_by_label["guarded_memory"]
    assert len(guarded) == 1 and guarded[0].guard_fact_ids

    assert model.loop_hubs
    assert any(hub.return_relationships for hub in model.loop_hubs)
    assert any(hub.partial_order for hub in model.loop_hubs)
    assert any(scene.repeatability.value == "repeatable" for scene in model.scenes)
    assert {chapter.label for chapter in model.chapters} >= {"Story", "Day Two"}
    assert all(
        boundary.canonical_anchor_ids
        and boundary.rule_version
        and boundary.provenance.node_ids
        and len(boundary.reason) <= 500
        for boundary in model.boundaries
    )
    assert len(model.coverage.node_ids) == len(model.atoms)
    assert "source_text" not in model.normalized_bytes().decode("utf-8")


def test_expanded_temporary_arms_have_exclusive_scenes_and_stop_at_rejoin(
    tmp_path: Path,
) -> None:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_text(
        '''label start:
    "Before."
    menu:
        "A":
            scene park
            "A after reset."
        "B":
            "B no reset."
    "After."
''',
        encoding="utf-8",
    )
    with create_ingested_project(tmp_path / "exclusive.rsmproj", source) as project:
        canonical = _mapping(project, "m10_canonical_graph")
        selection = project.m11_persistence().select(canonical)
        assert selection.phase_results is not None
        model = scene_model_from_phase_results(
            canonical,
            selection.phase_results["story_atoms"],
            selection.phase_results["scene_boundaries"],
            selection.phase_results["scene_assembly"],
        )

    branch = model.temporary_branches[0]
    scenes = {scene.id: scene for scene in model.scenes}
    sibling_scene_ids = [set(arm.scene_ids) for arm in branch.arms]
    assert all(sibling_scene_ids)
    assert sibling_scene_ids[0].isdisjoint(sibling_scene_ids[1])
    for arm in branch.arms:
        for scene_id in arm.scene_ids:
            assert set(scenes[scene_id].atom_ids) <= set(arm.atom_ids)
            assert branch.continuation_atom_id not in scenes[scene_id].atom_ids


def test_unrelated_source_procedures_never_share_a_scene(tmp_path: Path) -> None:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_text(
        '''label start:
    "Start."
    return

label unrelated:
    "Unrelated."
    return
''',
        encoding="utf-8",
    )
    with create_ingested_project(tmp_path / "procedures.rsmproj", source) as project:
        canonical = _mapping(project, "m10_canonical_graph")
        selection = project.m11_persistence().select(canonical)
        assert selection.phase_results is not None
        model = scene_model_from_phase_results(
            canonical,
            selection.phase_results["story_atoms"],
            selection.phase_results["scene_boundaries"],
            selection.phase_results["scene_assembly"],
        )

    node_by_atom = {
        atom.id: next(
            node for node in canonical["nodes"] if node["id"] == atom.primary_node_id
        )
        for atom in model.atoms
    }
    assert all(
        len({node_by_atom[atom_id]["label"] for atom_id in scene.atom_ids}) <= 1
        for scene in model.scenes
    )


def test_persistent_boundaries_and_lanes_retain_canonical_region_support(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    with create_ingested_project(tmp_path / "provenance.rsmproj", source) as project:
        canonical = _mapping(project, "m10_canonical_graph")
        selection = project.m11_persistence().select(canonical)
        assert selection.phase_results is not None
        model = scene_model_from_phase_results(
            canonical,
            selection.phase_results["story_atoms"],
            selection.phase_results["scene_boundaries"],
            selection.phase_results["scene_assembly"],
        )

    structural = [
        boundary
        for boundary in model.boundaries
        if boundary.rule_id in {"persistent_lane_entry", "persistent_lane_merge"}
    ]
    assert structural
    assert all(boundary.provenance.region_ids for boundary in structural)
    assert all(
        lane.split_atom_id
        and lane.canonical_region_id in lane.provenance.region_ids
        for lane in model.lanes
        if lane.canonical_region_id is not None
    )


def test_fresh_replay_has_identical_m11_phase_bytes(tmp_path: Path) -> None:
    source = _source(tmp_path)
    paths = (tmp_path / "first.rsmproj", tmp_path / "second.rsmproj")
    for path in paths:
        create_ingested_project(path, source).close()

    results: list[dict[str, bytes]] = []
    for path in paths:
        with Project.open(path) as project:
            canonical = _mapping(project, "m10_canonical_graph")
            selection = project.m11_persistence().select(canonical)
            assert selection.phase_results is not None
            results.append(
                {
                    phase: canonical_json(dict(selection.phase_results[phase]))
                    for phase in M11_PHASES
                }
            )

    assert results[0] == results[1]


def test_failed_new_m11_build_retains_old_publication_and_current_m10(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source(tmp_path)
    project_path = tmp_path / "story.rsmproj"
    create_ingested_project(project_path, source).close()
    story_path = source / "story.rpy"
    story_path.write_text(
        story_path.read_text(encoding="utf-8").replace(
            "The day begins.",
            "The changed day begins.",
        ),
        encoding="utf-8",
    )

    def fail_boundaries(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("injected M11 boundary failure")

    monkeypatch.setattr(project_analysis, "build_scene_boundaries", fail_boundaries)
    with pytest.raises(RuntimeError, match="injected M11"):
        refresh_ingested_project(project_path, source)

    with Project.open(project_path) as project:
        canonical = _mapping(project, "m10_canonical_graph")
        m10_state = _mapping(project, "m10_analysis_state")
        m11_state = project.m11_persistence().analysis_state()
        selection = project.m11_persistence().select(canonical)

    assert m10_state["status"] == "current_complete"
    assert m10_state["source_generation"] == canonical["source_generation"]
    assert m11_state is not None
    working = m11_state["working"]
    assert isinstance(working, dict)
    assert [item["phase"] for item in working["phases"]] == ["story_atoms"]
    assert m11_state["published"] is not None
    assert selection.availability is M11Availability.UNAVAILABLE
    assert selection.reason == "canonical_binding_mismatch"
