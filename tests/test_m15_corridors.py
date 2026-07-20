from __future__ import annotations

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
