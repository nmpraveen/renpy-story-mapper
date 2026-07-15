from __future__ import annotations

from pathlib import Path

import pytest

import renpy_story_mapper.project_analysis as project_analysis
from renpy_story_mapper.m11_persistence import M11_PHASES, M11Availability
from renpy_story_mapper.m11_scene_projection import scene_model_from_phase_results
from renpy_story_mapper.project import Project, create_ingested_project, refresh_ingested_project
from renpy_story_mapper.storage import canonical_json
from renpy_story_mapper.web.scene_api import scene_page

FIXTURE = Path(__file__).parent / "fixtures" / "m11" / "human_scenes.rpy"
OUT_OF_DEFINITION_ORDER = (
    Path(__file__).parent / "fixtures" / "m11" / "out_of_definition_order.rpy"
)


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
        presentation = selection.phase_results["scene_presentation"]

    region_by_id = {item["id"]: item for item in canonical["regions"]}
    node_by_id = {item["id"]: item for item in canonical["nodes"]}
    temporary_kinds = {
        "local_detour",
        "optional_detour",
        "reconvergent_route_segment",
    }
    assert model.temporary_branches
    assert all(branch.arms for branch in model.temporary_branches)
    assert all(
        set(left.atom_ids).isdisjoint(right.atom_ids)
        for branch in model.temporary_branches
        for index, left in enumerate(branch.arms)
        for right in branch.arms[index + 1 :]
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
    scene_by_atom = {
        atom_id: scene.id for scene in model.scenes for atom_id in scene.atom_ids
    }
    atom_by_node = {atom.primary_node_id: atom.id for atom in model.atoms}
    edge_by_id = {item["id"]: item for item in canonical["edges"]}
    scene_flow = [
        item
        for item in presentation["relationships"]
        if item["kind"] == "scene_flow"
    ]
    flow_pairs = {(item["source_id"], item["target_id"]) for item in scene_flow}
    assert all(
        scene_by_atom[atom_by_node[edge_by_id[edge_id]["source_id"]]]
        == relationship["source_id"]
        and scene_by_atom[atom_by_node[edge_by_id[edge_id]["target_id"]]]
        == relationship["target_id"]
        for relationship in scene_flow
        for edge_id in relationship["canonical_edge_ids"]
    )

    def reaches(start: str, target: str, allowed: set[str]) -> bool:
        pending = [start]
        reached: set[str] = set()
        while pending:
            source_id = pending.pop()
            if source_id == target:
                return True
            if source_id in reached:
                continue
            reached.add(source_id)
            pending.extend(
                next_id
                for edge_source, next_id in flow_pairs
                if edge_source == source_id
                and next_id in allowed
                and next_id not in reached
            )
        return False

    for branch in model.temporary_branches:
        continuation_scene = (
            None
            if branch.continuation_atom_id is None
            else scene_by_atom[branch.continuation_atom_id]
        )
        for index, left in enumerate(branch.arms):
            for right in branch.arms[index + 1 :]:
                assert not any(
                    (source_id in left.scene_ids and target_id in right.scene_ids)
                    or (source_id in right.scene_ids and target_id in left.scene_ids)
                    for source_id, target_id in flow_pairs
                )
        if continuation_scene is not None:
            for arm in branch.arms:
                if arm.scene_ids:
                    allowed = {*arm.scene_ids, continuation_scene}
                    assert reaches(arm.scene_ids[-1], continuation_scene, allowed)

    scenes_by_id = {scene.id: scene for scene in model.scenes}
    scene_ids = set(scenes_by_id)
    assert all(
        occurrence.call_atom_id in scenes_by_id[occurrence.scene_id].atom_ids
        and occurrence.id in scenes_by_id[occurrence.scene_id].occurrence_ids
        for occurrence in model.occurrences
    )
    assert all(
        relationship["source_id"] in scene_ids
        and relationship["target_id"] in scene_ids
        for relationship in scene_flow
    )
    for hub in model.loop_hubs:
        hub_scene = scene_by_atom[hub.hub_atom_id]
        assert all(
            (relation.before_scene_id, relation.after_scene_id) in flow_pairs
            for relation in hub.partial_order
        )
        assert all(
            relation.scene_id == hub_scene
            or (relation.scene_id, hub_scene) in flow_pairs
            for relation in hub.return_relationships
        )
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
            "A one."
            "A two."
            "A three."
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
    scene_by_label = {
        node_by_atom[atom_id]["label"]: scene.id
        for scene in model.scenes
        for atom_id in scene.atom_ids
        if node_by_atom[atom_id]["attributes"].get("source_kind") == "statement"
    }
    assert scene_by_label["start"] != scene_by_label["unrelated"]
    unrelated_boundaries = [
        boundary
        for boundary in model.boundaries
        if node_by_atom[boundary.after_atom_id]["label"] == "unrelated"
        and boundary.status.value == "accepted"
    ]
    assert unrelated_boundaries
    assert all(item.strength.value == "hard" for item in unrelated_boundaries)


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
    assert all(boundary.strength.value == "hard" for boundary in structural)
    assert all(boundary.status.value == "accepted" for boundary in structural)
    assert all(boundary.provenance.region_ids for boundary in structural)
    assert all(
        lane.split_atom_id
        and lane.canonical_region_id in lane.provenance.region_ids
        for lane in model.lanes
        if lane.canonical_region_id is not None
    )


def test_resolved_labels_and_routine_visual_changes_can_share_one_human_scene(
    tmp_path: Path,
) -> None:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_text(
        '''label start:
    "Opening."
    scene office
    show eileen happy
    hide eileen
    jump continuation

label continuation:
    show eileen concerned
    "Still talking."
    return
''',
        encoding="utf-8",
    )
    with create_ingested_project(tmp_path / "resolved-label.rsmproj", source) as project:
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
    scene_by_label = {
        node_by_atom[atom_id]["label"]: scene.id
        for scene in model.scenes
        for atom_id in scene.atom_ids
        if node_by_atom[atom_id]["attributes"].get("source_kind") == "statement"
    }
    assert scene_by_label["start"] == scene_by_label["continuation"]
    routine = [item for item in model.boundaries if item.rule_id == "routine_visual_change"]
    scene_candidates = [
        item for item in model.boundaries if item.rule_id == "scene_reset_candidate"
    ]
    continued = [
        item for item in model.boundaries if item.rule_id == "resolved_label_continuation"
    ]
    assert len(routine) == 3
    assert len(scene_candidates) == 1
    assert continued
    assert all(item.strength.value == "weak" for item in (*routine, *continued))
    assert all(item.status.value == "rejected" for item in (*routine, *continued))
    assert all(item.provenance.edge_ids for item in continued)
    assert scene_candidates[0].strength.value == "strong"
    assert scene_candidates[0].status.value == "rejected"


def test_proven_location_transition_reinforces_scene_reset(tmp_path: Path) -> None:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_text(
        '''label start:
    "Before."
    $ location = "park"
    scene park
    "After."
    return
''',
        encoding="utf-8",
    )
    with create_ingested_project(tmp_path / "location.rsmproj", source) as project:
        canonical = _mapping(project, "m10_canonical_graph")
        selection = project.m11_persistence().select(canonical)
        assert selection.phase_results is not None
        model = scene_model_from_phase_results(
            canonical,
            selection.phase_results["story_atoms"],
            selection.phase_results["scene_boundaries"],
            selection.phase_results["scene_assembly"],
        )

    transitions = [
        item
        for item in model.boundaries
        if item.rule_id == "reinforced_location_transition"
    ]
    assert len(transitions) == 1
    assert transitions[0].strength.value == "strong"
    assert transitions[0].status.value == "accepted"
    assert transitions[0].provenance.fact_ids


def test_pending_boundary_evidence_does_not_cross_temporary_arms(tmp_path: Path) -> None:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_text(
        '''label start:
    menu:
        "Move":
            $ location = "park"
            "Moved."
        "Stay":
            scene bedroom
            "Stayed."
    "Together again."
''',
        encoding="utf-8",
    )
    with create_ingested_project(tmp_path / "scoped-signals.rsmproj", source) as project:
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
    bedroom_atom_id = next(
        atom_id
        for atom_id, node in node_by_atom.items()
        if node["attributes"].get("source_text") == "scene bedroom"
    )
    boundary = next(item for item in model.boundaries if item.after_atom_id == bedroom_atom_id)
    assert boundary.rule_id == "scene_reset_candidate"
    assert boundary.strength.value == "strong"
    assert boundary.status.value == "rejected"


def test_unresolved_m10_transfers_remain_hard_scene_boundaries(tmp_path: Path) -> None:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_text(
        '''label start:
    "Before."
    jump expression destination

label fallback:
    "Fallback."
    return
''',
        encoding="utf-8",
    )
    with create_ingested_project(tmp_path / "unresolved.rsmproj", source) as project:
        canonical = _mapping(project, "m10_canonical_graph")
        selection = project.m11_persistence().select(canonical)
        assert selection.phase_results is not None
        model = scene_model_from_phase_results(
            canonical,
            selection.phase_results["story_atoms"],
            selection.phase_results["scene_boundaries"],
            selection.phase_results["scene_assembly"],
        )

    unresolved = [item for item in model.boundaries if item.rule_id == "unresolved_safety"]
    assert unresolved
    assert all(item.status.value == "accepted" for item in unresolved)
    assert all(item.strength.value == "hard" for item in unresolved)
    assert any(item.provenance.edge_ids for item in unresolved)


def test_canonical_edges_order_scenes_and_project_scene_flow(tmp_path: Path) -> None:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(OUT_OF_DEFINITION_ORDER.read_bytes())
    with create_ingested_project(tmp_path / "story-order.rsmproj", source) as project:
        canonical = _mapping(project, "m10_canonical_graph")
        selection = project.m11_persistence().select(canonical)
        assert selection.phase_results is not None
        model = scene_model_from_phase_results(
            canonical,
            selection.phase_results["story_atoms"],
            selection.phase_results["scene_boundaries"],
            selection.phase_results["scene_assembly"],
        )
        presentation = selection.phase_results["scene_presentation"]

    node_by_atom = {
        atom.id: next(
            node for node in canonical["nodes"] if node["id"] == atom.primary_node_id
        )
        for atom in model.atoms
    }
    narrative_labels = [
        node_by_atom[atom.id]["label"]
        for atom in model.atoms
        if node_by_atom[atom.id]["attributes"].get("source_kind") == "statement"
    ]
    assert narrative_labels == ["start", "later", "ending"]
    displayed_scenes = [
        scene
        for scene in sorted(model.scenes, key=lambda item: item.ordinal)
        if not scene.definition_only
        and any(
            node_by_atom[atom_id]["attributes"].get("source_kind") == "statement"
            for atom_id in scene.atom_ids
        )
    ]
    assert [
        next(
            node_by_atom[atom_id]["label"]
            for atom_id in scene.atom_ids
            if node_by_atom[atom_id]["attributes"].get("source_kind") == "statement"
        )
        for scene in displayed_scenes
    ] == ["start", "later", "ending"]
    flows = [
        item for item in presentation["relationships"] if item["kind"] == "scene_flow"
    ]
    assert flows
    assert all(item["canonical_edge_ids"] for item in flows)
    assert len({(item["source_id"], item["target_id"]) for item in flows}) == len(flows)
    page = scene_page(
        model.normalized_dict(),
        presentation,
        current_source_generation=model.binding.source_generation,
        current_canonical_hash=model.binding.canonical_hash,
    )
    assert any(item["kind"] == "scene_flow" for item in page["relationships"])


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
