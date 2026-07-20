from __future__ import annotations

from dataclasses import replace

import pytest

from m15_test_support import linear_authority
from renpy_story_mapper.m11_scene_model import AtomKind
from renpy_story_mapper.narrative_map import (
    BoundaryCandidate,
    BoundaryDecision,
    BoundaryDecisionKind,
    BoundaryProviderIdentity,
    BoundarySignal,
    assemble_narrative_events,
    build_boundary_candidates,
    build_narrative_corridors,
    build_narrative_map,
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


def test_day_and_chapter_progression_are_hard_contexts_with_no_boundary_job() -> None:
    canonical, model = linear_authority(
        (
            AtomKind.NARRATION,
            AtomKind.VISUAL_CHANGE,
            AtomKind.NARRATION,
            AtomKind.VISUAL_CHANGE,
            AtomKind.NARRATION,
        ),
        labels=("Prelude", "Scene day", "Day story", "Scene chapter", "Chapter story"),
        source_kinds=("statement", "scene", "statement", "scene", "statement"),
    )

    corridors = build_narrative_corridors(canonical, model)
    events = assemble_narrative_events(corridors)
    build_narrative_map(canonical, events, corridors=corridors)
    day_index = next(
        index for index, item in enumerate(corridors) if "atom-1" in item.ordered_atom_ids
    )
    chapter_index = next(
        index for index, item in enumerate(corridors) if "atom-3" in item.ordered_atom_ids
    )

    assert corridors[day_index].hard_boundary_before
    assert corridors[day_index - 1].hard_boundary_after
    assert corridors[chapter_index].hard_boundary_before
    assert corridors[chapter_index - 1].hard_boundary_after
    assert corridors[day_index].chapter_id is not None
    assert corridors[chapter_index].chapter_id is not None
    assert corridors[day_index].chapter_id != corridors[chapter_index].chapter_id
    assert build_boundary_candidates(corridors) == ()

    left = corridors[day_index - 1]
    right = corridors[day_index]
    injected = BoundaryCandidate(
        left.authority,
        left.corridor_id,
        right.corridor_id,
        (BoundarySignal.NARRATIVE_OBJECTIVE,),
    )
    decision = BoundaryDecision(
        injected,
        BoundaryDecisionKind.MERGE,
        "Injected progression merge must fail closed.",
        1.0,
        BoundaryProviderIdentity(
            "fake",
            "v1",
            "fake",
            "fake",
            "settings",
            "p1",
            "s1",
            "i1",
        ),
    )
    with pytest.raises(ValueError, match="exact adjacent soft candidate"):
        assemble_narrative_events(corridors, (decision,))


def test_progression_context_uses_m10_source_evidence_not_m11_label() -> None:
    canonical, model = linear_authority(
        (AtomKind.NARRATION, AtomKind.VISUAL_CHANGE, AtomKind.NARRATION),
        labels=("Prelude", "Scene room", "Story"),
        source_kinds=("statement", "scene", "statement"),
    )
    ordinary_nodes = tuple(
        replace(
            item,
            attributes={
                "source_kind": ("scene" if index == 1 else "statement"),
                "source_text": ("scene room" if index == 1 else "statement"),
            },
        )
        for index, item in enumerate(canonical.nodes)
    )
    misleading_atoms = tuple(
        replace(item, label="Scene day") if index == 1 else item
        for index, item in enumerate(model.atoms)
    )
    ordinary_canonical = replace(canonical, nodes=ordinary_nodes)
    ordinary_model = replace(
        model,
        binding=replace(model.binding, canonical_hash=ordinary_canonical.authority_hash),
        atoms=misleading_atoms,
    )
    ordinary_corridors = build_narrative_corridors(ordinary_canonical, ordinary_model)
    assert {item.chapter_id for item in ordinary_corridors} == {None}

    day_nodes = tuple(
        replace(
            item,
            attributes={
                **item.attributes,
                "source_text": "scene day with dissolve" if index == 1 else "statement",
            },
        )
        for index, item in enumerate(ordinary_nodes)
    )
    nonsemantic_atoms = tuple(
        replace(item, label="Scene room") if index == 1 else item
        for index, item in enumerate(model.atoms)
    )
    day_canonical = replace(canonical, nodes=day_nodes)
    day_model = replace(
        model,
        binding=replace(model.binding, canonical_hash=day_canonical.authority_hash),
        atoms=nonsemantic_atoms,
    )
    day_corridors = build_narrative_corridors(day_canonical, day_model)
    day_index = next(
        index for index, item in enumerate(day_corridors) if "atom-1" in item.ordered_atom_ids
    )
    assert day_corridors[day_index].chapter_id == "progression:node-1"
    assert day_corridors[day_index].hard_boundary_before
    assert day_corridors[day_index - 1].hard_boundary_after
