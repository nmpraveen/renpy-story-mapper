from __future__ import annotations

import hashlib
from pathlib import Path

from renpy_story_mapper.m11_scene_projection import scene_model_from_phase_results
from renpy_story_mapper.project import Project, create_ingested_project

FIXTURE = Path(__file__).parent / "fixtures" / "m12" / "route_targets.rpy"


def _mapping(project: Project, collection: str) -> dict[str, object]:
    value = project.payload(collection, "authoritative")
    assert isinstance(value, dict)
    return value


def test_route_fixture_exposes_m10_start_state_targets_and_m11_contexts(
    tmp_path: Path,
) -> None:
    fixture_before = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    source = tmp_path / "game"
    source.mkdir()
    (source / "route_targets.rpy").write_bytes(FIXTURE.read_bytes())

    with create_ingested_project(tmp_path / "routes.rsmproj", source) as project:
        canonical = _mapping(project, "m10_canonical_graph")
        selection = project.m11_persistence().select(canonical)
        assert selection.phase_results is not None
        model = scene_model_from_phase_results(
            canonical,
            selection.phase_results["story_atoms"],
            selection.phase_results["scene_boundaries"],
            selection.phase_results["scene_assembly"],
        )

    nodes = {str(item["id"]): item for item in canonical["nodes"]}
    facts = canonical["facts"]
    roots = [
        item
        for item in nodes.values()
        if item["attributes"].get("reachability_witness", {}).get("kind") == "root"
    ]
    assert roots
    assert all(item["proof_ids"] for item in roots)
    assert any(
        item["kind"] == "effect"
        and item["status"] == "proven"
        and item["attributes"].get("original_expression") == "score += 1"
        for item in facts
    )
    assert any(
        item["kind"] == "requirement"
        and item["status"] == "proven"
        and item["attributes"].get("original_expression") == "score >= 3"
        for item in facts
    )
    assert any(item["kind"] == "terminal" for item in nodes.values())
    assert any(item["kind"] == "unresolved" for item in nodes.values())

    shared_entry_ids = {
        node_id for node_id, item in nodes.items() if item["label"] == "shared_memory"
    }
    shared_occurrences = [
        item for item in model.occurrences if item.callee_entry_node_id in shared_entry_ids
    ]
    assert len(shared_occurrences) >= 3
    occurrence_contexts = {
        (item.call_atom_id, item.scene_id, item.lane_id) for item in shared_occurrences
    }
    assert len(occurrence_contexts) == len(shared_occurrences)
    assert all(item.provenance.node_ids and item.provenance.edge_ids for item in shared_occurrences)
    assert any(item.canonical_region_id is not None for item in model.lanes)
    assert model.loop_hubs
    assert any(scene.repeatability.value == "repeatable" for scene in model.scenes)
    assert any(scene.definition_only for scene in model.scenes)
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == fixture_before
