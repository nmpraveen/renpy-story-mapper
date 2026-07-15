from __future__ import annotations

from pathlib import Path

from renpy_story_mapper.m11_correction_service import apply_correction_overlay
from renpy_story_mapper.m11_persistence import M11Availability
from renpy_story_mapper.m11_scene_model import (
    BoundaryStrength,
    Correction,
    CorrectionOperation,
    CorrectionOverlay,
    CorrectionStatus,
    DecisionStatus,
    stable_m11_id,
)
from renpy_story_mapper.m11_scene_projection import (
    build_scene_model,
    correction_overlay_from_mapping,
)
from renpy_story_mapper.project import create_ingested_project

FIXTURE = Path(__file__).parent / "fixtures" / "m11" / "human_scenes.rpy"


def _canonical(tmp_path: Path) -> dict[str, object]:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    with create_ingested_project(tmp_path / "story.rsmproj", source) as project:
        value = project.payload("m10_canonical_graph", "authoritative")
    assert isinstance(value, dict)
    return value


def test_minimal_split_correction_changes_only_the_target_boundary(tmp_path: Path) -> None:
    canonical = _canonical(tmp_path)
    base = build_scene_model(canonical)
    scene_by_atom = {atom_id: scene for scene in base.scenes for atom_id in scene.atom_ids}
    target = next(
        boundary
        for boundary in base.boundaries
        if boundary.status is DecisionStatus.REJECTED
        and boundary.before_atom_id is not None
        and scene_by_atom[boundary.after_atom_id].atom_ids.index(boundary.after_atom_id) > 0
    )
    correction = Correction(
        stable_m11_id("correction", "split", target.after_atom_id),
        CorrectionOperation.SPLIT_BEFORE_ATOM,
        CorrectionStatus.APPLIED,
        target.after_atom_id,
        target.id,
        (),
        base.binding,
        "Reviewer confirmed a human scene break.",
    )
    overlay = CorrectionOverlay(base.binding, (correction,))

    corrected = build_scene_model(canonical, overlay)
    corrected_boundary = next(
        item for item in corrected.boundaries if item.id == target.id
    )

    assert len(corrected.scenes) == len(base.scenes) + 1
    assert corrected_boundary.status is DecisionStatus.ACCEPTED
    assert corrected_boundary.strength is BoundaryStrength.HARD
    assert corrected_boundary.rule_id == "correction_split"
    assert corrected.correction_overlay == overlay


def test_minimal_merge_correction_uses_exact_adjacent_scene_anchors(tmp_path: Path) -> None:
    canonical = _canonical(tmp_path)
    base = build_scene_model(canonical)
    scene_by_atom = {atom_id: scene for scene in base.scenes for atom_id in scene.atom_ids}
    target = next(
        boundary
        for boundary in base.boundaries
        if boundary.status is DecisionStatus.ACCEPTED
        and boundary.before_atom_id is not None
        and scene_by_atom[boundary.before_atom_id].id
        != scene_by_atom[boundary.after_atom_id].id
        and scene_by_atom[boundary.before_atom_id].lane_id
        == scene_by_atom[boundary.after_atom_id].lane_id
    )
    anchors = (
        scene_by_atom[target.before_atom_id].id,
        scene_by_atom[target.after_atom_id].id,
    )
    correction = Correction(
        stable_m11_id("correction", "merge", target.id),
        CorrectionOperation.MERGE_ADJACENT_SCENES,
        CorrectionStatus.APPLIED,
        None,
        target.id,
        anchors,
        base.binding,
        "Reviewer confirmed these adjacent scenes are one scene.",
    )
    mapping = CorrectionOverlay(base.binding, (correction,)).to_dict()
    overlay = correction_overlay_from_mapping(mapping)

    corrected = build_scene_model(canonical, overlay)
    corrected_boundary = next(
        item for item in corrected.boundaries if item.id == target.id
    )

    assert len(corrected.scenes) == len(base.scenes) - 1
    assert corrected_boundary.status is DecisionStatus.REJECTED
    assert corrected_boundary.strength is BoundaryStrength.WEAK
    assert corrected_boundary.rule_id == "correction_merge"
    assert overlay.to_dict() == mapping


def test_non_applied_correction_is_durable_but_does_not_change_projection(
    tmp_path: Path,
) -> None:
    canonical = _canonical(tmp_path)
    base = build_scene_model(canonical)
    target = next(item for item in base.boundaries if item.before_atom_id is not None)
    correction = Correction(
        stable_m11_id("correction", "orphaned", target.after_atom_id),
        CorrectionOperation.SPLIT_BEFORE_ATOM,
        CorrectionStatus.ORPHANED,
        target.after_atom_id,
        target.id,
        (),
        base.binding,
        "Retained for review but not applied.",
    )

    projected = build_scene_model(canonical, CorrectionOverlay(base.binding, (correction,)))

    assert len(projected.scenes) == len(base.scenes)
    assert projected.correction_overlay is not None
    assert projected.correction_overlay.corrections[0].status is CorrectionStatus.ORPHANED


def test_correction_service_republishes_only_assembly_and_presentation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "service-game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    with create_ingested_project(tmp_path / "service.rsmproj", source) as project:
        canonical = project.payload("m10_canonical_graph", "authoritative")
        assert isinstance(canonical, dict)
        base = build_scene_model(canonical)
        scene_by_atom = {
            atom_id: scene for scene in base.scenes for atom_id in scene.atom_ids
        }
        target = next(
            boundary
            for boundary in base.boundaries
            if boundary.status is DecisionStatus.REJECTED
            and boundary.before_atom_id is not None
            and scene_by_atom[boundary.after_atom_id].atom_ids.index(boundary.after_atom_id)
            > 0
        )
        correction = Correction(
            stable_m11_id("correction", "service", target.after_atom_id),
            CorrectionOperation.SPLIT_BEFORE_ATOM,
            CorrectionStatus.APPLIED,
            target.after_atom_id,
            target.id,
            (),
            base.binding,
            "Persist a minimal reviewer split.",
        )
        overlay = CorrectionOverlay(base.binding, (correction,))

        publication, corrected = apply_correction_overlay(project, canonical, overlay)
        selected = project.m11_persistence().select(canonical)

        assert publication.reused is False
        assert len(corrected.scenes) == len(base.scenes) + 1
        assert selected.availability is M11Availability.CURRENT_COMPLETE
        assert selected.phase_results is not None
        assert selected.phase_results["scene_assembly"]["correction_overlay"] == overlay.to_dict()
        assert project.m11_persistence().corrections(canonical) == overlay.to_dict()

        changes = project._require_open().total_changes
        reused, same_model = apply_correction_overlay(project, canonical, overlay)
        assert reused.reused is True
        assert same_model.structural_hash == corrected.structural_hash
        assert project._require_open().total_changes == changes
