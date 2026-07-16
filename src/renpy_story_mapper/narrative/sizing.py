"""Provider-free complete-run sizing for one simple manifest-bound M13 consent."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import cast

from renpy_story_mapper.m11_scene_model import LaneKind
from renpy_story_mapper.narrative.contracts import CostConfidence, RunEstimate
from renpy_story_mapper.narrative.preparation import PreparedSceneRun, ProviderPricing
from renpy_story_mapper.narrative.projection import M13_CHARACTER_PARTICIPATION_VERSION

SEGMENT_TARGET_CHILDREN = 24
HIERARCHY_OUTPUT_TOKENS = 1_000
HIERARCHY_PROMPT_OVERHEAD_TOKENS = 256


def estimate_complete_run(
    scene_run: PreparedSceneRun,
    scene_model: Mapping[str, object],
    *,
    pricing: ProviderPricing | None,
) -> RunEstimate:
    """Estimate the entire consented hierarchy without provider output or story transmission.

    Scene transport batches are exact.  Higher-level calls use a safe singleton upper bound
    because accepted artifact sizes determine later deterministic packing.  Logical-job and
    token counts are derived from current M11 structural runs and versioned fan-in constants.
    """

    selected = {item.job.spec.owner_id for item in scene_run.jobs}
    scenes = [item for item in _records(scene_model, "scenes") if _text(item, "id") in selected]
    atoms = _index(_records(scene_model, "atoms"))
    chapters = _index(_records(scene_model, "chapters"))
    branches = _temporary_membership(_records(scene_model, "temporary_branches"))
    lanes = _records(scene_model, "lanes")
    ordered = sorted(
        scenes,
        key=lambda item: (
            _integer(chapters[_text(item, "chapter_id")], "ordinal"),
            _integer(item, "ordinal"),
            _text(item, "lane_id"),
            _text(item, "id"),
        ),
    )
    runs: list[list[Mapping[str, object]]] = []
    prior: object = None
    for scene in ordered:
        scene_id = _text(scene, "id")
        terminal_ids = tuple(
            atom_id
            for atom_id in _strings(scene.get("atom_ids"), "scene atom IDs")
            if atoms[atom_id].get("kind") == "terminal"
        )
        key = (
            _text(scene, "chapter_id"),
            _text(scene, "lane_id"),
            branches.get(scene_id),
            _strings(scene.get("occurrence_ids"), "scene occurrence IDs"),
            scene.get("loop_hub_id"),
            terminal_ids,
        )
        if key != prior:
            runs.append([])
            prior = key
        runs[-1].append(scene)

    segment_jobs = 0
    segment_roots = 0
    extra_segment_children = 0
    for run in runs:
        count = len(run)
        level = max(1, math.ceil(count / SEGMENT_TARGET_CHILDREN))
        segment_jobs += level
        while level > 32:
            extra_segment_children += level
            level = math.ceil(level / SEGMENT_TARGET_CHILDREN)
            segment_jobs += level
        segment_roots += level

    lane_by_id = _index(lanes)
    selected_route_ids: set[str] = set()
    for scene in scenes:
        current: str | None = _text(scene, "lane_id")
        seen: set[str] = set()
        while current is not None:
            if current in seen:
                raise ValueError("M11 lane ancestry contains a cycle")
            seen.add(current)
            lane = lane_by_id[current]
            if lane.get("kind") in {
                LaneKind.PERSISTENT_ROUTE.value,
                LaneKind.TERMINAL_SPLIT.value,
            }:
                selected_route_ids.add(current)
            parent = lane.get("parent_lane_id")
            current = parent if isinstance(parent, str) and parent else None
    route_count = len(selected_route_ids)
    terminal_lane_ids = {
        _text(item, "id")
        for item in lanes
        if item.get("kind") == LaneKind.TERMINAL_SPLIT.value
        and _text(item, "id") in selected_route_ids
    }
    ending_keys: set[tuple[str, str]] = set()
    for scene in scenes:
        lane_id = _text(scene, "lane_id")
        if lane_id in terminal_lane_ids:
            ending_keys.add((lane_id, lane_id))
            continue
        terminals = tuple(
            atom_id
            for atom_id in _strings(scene.get("atom_ids"), "scene atom IDs")
            if atoms[atom_id].get("kind") == "terminal"
        )
        for terminal in terminals:
            ending_keys.add((lane_id, terminal))
    ending_count = len(ending_keys)
    speakers: set[str] = set()
    for item in scene_run.jobs:
        context = item.payload.get("structural_context")
        if not isinstance(context, Mapping):
            raise ValueError("prepared scene structural context is malformed")
        participation = context.get("m13_character_participation")
        if (
            not isinstance(participation, Mapping)
            or participation.get("version") != M13_CHARACTER_PARTICIPATION_VERSION
        ):
            raise ValueError("prepared scene character participation is missing or stale")
        speakers.update(
            _strings(participation.get("character_ids"), "prepared character IDs")
        )
    chapter_jobs = len(runs)
    fixed_jobs = (1 if scenes else 0) + route_count + ending_count + (1 if scenes else 0)
    hierarchy_jobs = segment_jobs + chapter_jobs + fixed_jobs + len(speakers)
    logical_jobs = scene_run.estimate.logical_job_count + hierarchy_jobs
    provider_calls = scene_run.estimate.provider_call_count + hierarchy_jobs

    scene_output = scene_run.estimate.output_tokens
    segment_input = (
        scene_output
        + extra_segment_children * HIERARCHY_OUTPUT_TOKENS
        + segment_jobs * HIERARCHY_PROMPT_OVERHEAD_TOKENS
    )
    chapter_input = segment_roots * HIERARCHY_OUTPUT_TOKENS
    shared_input = chapter_jobs * HIERARCHY_OUTPUT_TOKENS
    route_input = (route_count + chapter_jobs) * HIERARCHY_OUTPUT_TOKENS
    ending_input = (ending_count + chapter_jobs) * HIERARCHY_OUTPUT_TOKENS
    plot_input = (1 + route_count + ending_count) * HIERARCHY_OUTPUT_TOKENS
    character_children = min(32, 1 + route_count + ending_count)
    character_input = len(speakers) * character_children * HIERARCHY_OUTPUT_TOKENS
    input_tokens = scene_run.estimate.input_tokens + sum(
        (
            segment_input,
            chapter_input,
            shared_input,
            route_input,
            ending_input,
            plot_input,
            character_input,
        )
    )
    output_tokens = scene_output + hierarchy_jobs * HIERARCHY_OUTPUT_TOKENS
    if pricing is None:
        cost = None
        confidence = CostConfidence.UNAVAILABLE
    else:
        cost = math.ceil(
            (
                input_tokens * pricing.input_micros_per_million_tokens
                + output_tokens * pricing.output_micros_per_million_tokens
            )
            / 1_000_000
        )
        confidence = CostConfidence.RELIABLE
    return RunEstimate(
        logical_jobs,
        provider_calls,
        input_tokens,
        output_tokens,
        cost,
        confidence,
    )


def _temporary_membership(
    branches: Sequence[Mapping[str, object]],
) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for branch in branches:
        branch_id = _text(branch, "id")
        arms = branch.get("arms")
        if not isinstance(arms, list) or any(not isinstance(item, Mapping) for item in arms):
            raise ValueError("M11 temporary arms are malformed")
        for arm in cast(list[Mapping[str, object]], arms):
            arm_id = _text(arm, "id")
            for scene_id in _strings(arm.get("scene_ids"), "temporary-arm scenes"):
                result[scene_id] = (branch_id, arm_id)
    return result


def _records(owner: Mapping[str, object], key: str) -> tuple[Mapping[str, object], ...]:
    value = owner.get(key)
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"{key} must be an array of records")
    return tuple(cast(Mapping[str, object], item) for item in value)


def _index(values: Sequence[Mapping[str, object]]) -> dict[str, Mapping[str, object]]:
    return {_text(item, "id"): item for item in values}


def _text(owner: Mapping[str, object], key: str) -> str:
    value = owner.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _integer(owner: Mapping[str, object], key: str) -> int:
    value = owner.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{label} must be an array of non-empty strings")
    return tuple(cast(list[str], value))
