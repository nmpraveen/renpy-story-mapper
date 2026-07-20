from __future__ import annotations

from dataclasses import replace

from m15_test_support import linear_authority
from renpy_story_mapper.m11_scene_model import AtomKind
from renpy_story_mapper.narrative_map import (
    BoundarySignal,
    build_narrative_corridors,
)


def test_linear_dialogue_and_frequent_pose_changes_stay_one_corridor() -> None:
    canonical, model = linear_authority(
        (
            AtomKind.NARRATION,
            AtomKind.VISUAL_CHANGE,
            AtomKind.VISUAL_CHANGE,
            AtomKind.DIALOGUE,
        ),
        labels=("Opening", "Scene room pose one", "Scene room pose two", "Continue"),
        source_kinds=("statement", "scene", "scene", "statement"),
    )

    corridors = build_narrative_corridors(canonical, model)

    assert len(corridors) == 1
    assert corridors[0].ordered_atom_ids == tuple(item.id for item in model.atoms)
    assert corridors[0].technical_atom_ids == ("atom-1", "atom-2")
    assert corridors[0].soft_boundary_signals == ()


def test_only_stable_visual_family_change_emits_a_soft_candidate() -> None:
    canonical, model = linear_authority(
        (
            AtomKind.NARRATION,
            AtomKind.VISUAL_CHANGE,
            AtomKind.VISUAL_CHANGE,
            AtomKind.NARRATION,
            AtomKind.VISUAL_CHANGE,
            AtomKind.VISUAL_CHANGE,
            AtomKind.NARRATION,
        ),
        labels=(
            "Begin",
            "Scene office pose one",
            "Scene office pose two",
            "Transition",
            "Scene kitchen pose one",
            "Scene kitchen pose two",
            "Continue",
        ),
        source_kinds=("statement", "scene", "scene", "statement", "scene", "scene", "statement"),
    )

    corridors = build_narrative_corridors(canonical, model)

    assert len(corridors) == 2
    assert corridors[1].soft_boundary_signals == (BoundarySignal.VISUAL_FAMILY,)
    assert {atom for item in corridors for atom in item.ordered_atom_ids} == {
        atom.id for atom in model.atoms
    }


def test_terminal_and_unresolved_transfers_are_isolated_hard_boundaries() -> None:
    canonical, model = linear_authority(
        (AtomKind.NARRATION, AtomKind.UNRESOLVED, AtomKind.TERMINAL)
    )

    corridors = build_narrative_corridors(canonical, model)

    assert len(corridors) == 3
    assert corridors[1].hard_boundary_before and corridors[1].hard_boundary_after
    assert corridors[2].hard_boundary_before and corridors[2].hard_boundary_after


def test_m11_scene_lane_and_chapter_membership_are_not_topology_authority() -> None:
    canonical, model = linear_authority((AtomKind.NARRATION, AtomKind.DIALOGUE))
    altered_lane_id = "m11-lane-must-not-own-topology"
    altered_chapter_id = "m11-chapter-must-not-own-topology"
    altered_scene = replace(
        model.scenes[0],
        chapter_id=altered_chapter_id,
        lane_id=altered_lane_id,
    )
    altered_lane = replace(model.lanes[0], id=altered_lane_id)
    altered_chapter = replace(
        model.chapters[0],
        id=altered_chapter_id,
        lane_ids=(altered_lane_id,),
    )
    altered_model = replace(
        model,
        scenes=(altered_scene,),
        lanes=(altered_lane,),
        chapters=(altered_chapter,),
    )

    corridors = build_narrative_corridors(canonical, altered_model)

    assert {item.chapter_id for item in corridors} == {None}
    assert {item.lane_id for item in corridors} == {"lane_story_spine"}
