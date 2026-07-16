from __future__ import annotations

import math
from types import SimpleNamespace
from typing import cast

from renpy_story_mapper.narrative.contracts import CostConfidence, RunEstimate
from renpy_story_mapper.narrative.preparation import PreparedSceneRun
from renpy_story_mapper.narrative.projection import M13_CHARACTER_PARTICIPATION_VERSION
from renpy_story_mapper.narrative.sizing import _fan_in_estimate, estimate_complete_run


def test_fan_in_estimate_counts_every_reduction_level() -> None:
    estimate = _fan_in_estimate(1_000)

    assert estimate.logical_jobs == 46
    assert estimate.root_count == 2
    assert estimate.input_child_units == 1_044


def test_complete_run_sizing_includes_large_higher_level_reduction_tree() -> None:
    scene_count = 1_000
    scene_jobs = tuple(
        SimpleNamespace(
            job=SimpleNamespace(spec=SimpleNamespace(owner_id=f"scene-{ordinal:04d}")),
            payload={
                "structural_context": {
                    "m13_character_participation": {
                        "version": M13_CHARACTER_PARTICIPATION_VERSION,
                        "character_ids": [],
                    }
                }
            },
        )
        for ordinal in range(scene_count)
    )
    scene_estimate = RunEstimate(
        logical_job_count=scene_count,
        provider_call_count=math.ceil(scene_count / 16),
        input_tokens=scene_count * 10,
        output_tokens=scene_count * 800,
        estimated_cost_micros=None,
        cost_confidence=CostConfidence.UNAVAILABLE,
    )
    scene_run = cast(
        PreparedSceneRun,
        SimpleNamespace(jobs=scene_jobs, batches=(), estimate=scene_estimate),
    )
    scene_model: dict[str, object] = {
        "atoms": [{"id": "statement", "kind": "dialogue"}],
        "chapters": [{"id": "chapter", "ordinal": 0}],
        "lanes": [
            {
                "id": "spine",
                "kind": "spine",
                "parent_lane_id": None,
            }
        ],
        "temporary_branches": [],
        "scenes": [
            {
                "id": f"scene-{ordinal:04d}",
                "chapter_id": "chapter",
                "lane_id": "spine",
                "ordinal": ordinal,
                "atom_ids": ["statement"],
                "occurrence_ids": [f"occurrence-{ordinal:04d}"],
                "loop_hub_id": None,
            }
            for ordinal in range(scene_count)
        ],
    }

    estimate = estimate_complete_run(scene_run, scene_model, pricing=None)

    # 1,000 scene jobs + 1,000 first-level segments + 1,000 chapters +
    # 46 common-story reduction jobs + one common story + one whole plot.
    assert estimate.logical_job_count == 3_048
    assert estimate.provider_call_count == math.ceil(scene_count / 16) + 2_048
    assert estimate.output_tokens == scene_estimate.output_tokens + 2_048_000
    assert estimate.input_tokens > scene_estimate.input_tokens
    assert estimate.cost_confidence is CostConfidence.UNAVAILABLE
