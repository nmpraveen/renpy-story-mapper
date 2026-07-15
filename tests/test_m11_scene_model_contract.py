from __future__ import annotations

from dataclasses import replace

import pytest

from renpy_story_mapper.m11_scene_model import (
    M11_ATOM_RULE_VERSION,
    M11_BOUNDARY_RULE_VERSION,
    M11_SCENE_MODEL_SCHEMA,
    AtomKind,
    BoundaryDecision,
    BoundaryStrength,
    CanonicalBinding,
    CanonicalCoverage,
    Chapter,
    Correction,
    CorrectionOperation,
    CorrectionOverlay,
    CorrectionStatus,
    CoverageCollection,
    CoverageDisposition,
    CoverageEntry,
    DecisionStatus,
    LaneKind,
    PersistentLane,
    Provenance,
    Scene,
    SceneModel,
    SceneRepeatability,
    StoryAtom,
)


def _model(*, operational: dict[str, object] | None = None) -> SceneModel:
    binding = CanonicalBinding("generation", "m10-canonical-graph-v1", "a" * 64)
    provenance = Provenance(node_ids=("node-1",), evidence_ids=("evidence-1",))
    atom = StoryAtom(
        "atom-1",
        AtomKind.DIALOGUE,
        "node-1",
        "start",
        True,
        M11_ATOM_RULE_VERSION,
        provenance,
        source_kind="statement",
        speaker="narrator",
        source_order=("story.rpy", 2, 4, "node-1"),
    )
    boundary = BoundaryDecision(
        "boundary-1",
        None,
        atom.id,
        BoundaryStrength.HARD,
        DecisionStatus.ACCEPTED,
        M11_BOUNDARY_RULE_VERSION,
        ("node-1",),
        provenance,
        "The entry narrative atom begins the deterministic scene draft.",
        "entry_root",
    )
    scene = Scene(
        "scene-1",
        "chapter-1",
        "lane-spine",
        "Story · Scene 1",
        0,
        (atom.id,),
        (),
        (),
        SceneRepeatability.ONCE,
        None,
        boundary.id,
        False,
        provenance,
    )
    lane = PersistentLane(
        "lane-spine",
        LaneKind.SPINE,
        None,
        None,
        None,
        (scene.id,),
        None,
        None,
        provenance,
    )
    chapter = Chapter(
        "chapter-1",
        "Story",
        0,
        (lane.id,),
        (scene.id,),
        boundary.id,
        provenance,
    )
    coverage = CanonicalCoverage(
        ("node-1",),
        (),
        (),
        (),
        (
            CoverageEntry(
                CoverageCollection.NODE,
                "node-1",
                CoverageDisposition.ATOM_OWNED,
                atom.id,
                (),
                "The canonical node has exactly one deterministic atom owner.",
            ),
        ),
    )
    return SceneModel(
        binding,
        (atom,),
        (boundary,),
        (scene,),
        (),
        (),
        (lane,),
        (chapter,),
        (),
        coverage,
        operational_metadata=operational,
    )


def test_scene_model_validates_and_operational_metadata_does_not_change_hash() -> None:
    first = _model(operational={"duration_seconds": 1.0, "run_id": "first"})
    second = _model(operational={"duration_seconds": 99.0, "run_id": "second"})

    first.validate()
    second.validate()
    assert first.structural_hash == second.structural_hash
    assert first.normalized_bytes() == second.normalized_bytes()
    assert first.normalized_dict()["schema"] == M11_SCENE_MODEL_SCHEMA
    assert "operational_metadata" not in first.normalized_dict()
    assert first.to_dict()["operational_metadata"] == {
        "duration_seconds": 1.0,
        "run_id": "first",
    }
    assert b"source_text" not in first.normalized_bytes()


def test_scene_model_rejects_lost_canonical_coverage() -> None:
    model = _model()
    broken = replace(model, coverage=replace(model.coverage, entries=()))

    with pytest.raises(ValueError, match="needs one coverage entry"):
        broken.validate()


def test_scene_model_rejects_duplicate_atom_scene_ownership() -> None:
    model = _model()
    first_scene = model.scenes[0]
    second_boundary = replace(
        model.boundaries[0],
        id="boundary-2",
        before_atom_id=first_scene.atom_ids[0],
    )
    second_scene = replace(
        first_scene,
        id="scene-2",
        ordinal=1,
        boundary_id=second_boundary.id,
    )
    lane = replace(model.lanes[0], scene_ids=(first_scene.id, second_scene.id))
    chapter = replace(model.chapters[0], scene_ids=(first_scene.id, second_scene.id))
    broken = replace(
        model,
        boundaries=(*model.boundaries, second_boundary),
        scenes=(*model.scenes, second_scene),
        lanes=(lane,),
        chapters=(chapter,),
    )

    with pytest.raises(ValueError, match="belongs to more than one scene"):
        broken.validate()


@pytest.mark.parametrize(
    "atom_ids",
    [
        ("atom-1", "atom-1"),
        ("atom-missing",),
    ],
)
def test_scene_reference_validation_rejects_duplicates_and_unknowns(
    atom_ids: tuple[str, ...],
) -> None:
    model = _model()
    broken = replace(model, scenes=(replace(model.scenes[0], atom_ids=atom_ids),))

    with pytest.raises(ValueError, match="scene scene-1 atom references are invalid"):
        broken.validate()


def test_boundary_contract_records_strength_status_rules_anchors_and_reason() -> None:
    boundary = _model().boundaries[0].to_dict()

    assert boundary["strength"] == "hard"
    assert boundary["status"] == "accepted"
    assert boundary["rule_version"] == M11_BOUNDARY_RULE_VERSION
    assert boundary["canonical_anchor_ids"] == ["node-1"]
    assert boundary["reason"]
    assert boundary["provenance"]["node_ids"] == ["node-1"]


def test_correction_overlay_is_exactly_bound_and_limited_to_split_or_merge() -> None:
    model = _model()
    correction = Correction(
        "correction-1",
        CorrectionOperation.SPLIT_BEFORE_ATOM,
        CorrectionStatus.APPLIED,
        "atom-1",
        None,
        (),
        model.binding,
        "The user confirmed a scene boundary before this canonical atom.",
    )
    corrected = replace(
        model,
        correction_overlay=CorrectionOverlay(model.binding, (correction,)),
    )
    corrected.validate()

    wrong_binding = replace(model.binding, canonical_hash="b" * 64)
    broken = replace(
        corrected,
        correction_overlay=CorrectionOverlay(wrong_binding, (correction,)),
    )
    with pytest.raises(ValueError, match="binding does not match"):
        broken.validate()
