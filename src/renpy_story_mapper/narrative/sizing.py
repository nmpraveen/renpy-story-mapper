"""Provider-free complete-run sizing for one simple manifest-bound M13 consent."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from renpy_story_mapper.m11_scene_model import LaneKind
from renpy_story_mapper.narrative.contracts import CostConfidence, RunEstimate
from renpy_story_mapper.narrative.hierarchy import (
    HIERARCHY_REDUCTION_TARGET_CHILDREN,
    HierarchyPartitionConfig,
)
from renpy_story_mapper.narrative.preparation import PreparedSceneRun, ProviderPricing
from renpy_story_mapper.narrative.projection import M13_CHARACTER_PARTICIPATION_VERSION
from renpy_story_mapper.narrative.segments import SegmentPartitionConfig

_DEFAULT_SEGMENT_CONFIG = SegmentPartitionConfig("und", "default")
SEGMENT_TARGET_CHILDREN = _DEFAULT_SEGMENT_CONFIG.target_children
HIERARCHY_OUTPUT_TOKENS = 1_000
_DEFAULT_HIERARCHY_CONFIG = HierarchyPartitionConfig("und", "default")
HIERARCHY_PROMPT_OVERHEAD_TOKENS = _DEFAULT_HIERARCHY_CONFIG.prompt_overhead_tokens


@dataclass(frozen=True)
class _PathEstimate:
    section: str
    route_id: str | None = None
    ending_key: tuple[str, ...] | None = None


@dataclass(frozen=True)
class _FanInEstimate:
    logical_jobs: int
    root_count: int
    input_child_units: int


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
    lane_by_id = _index(_records(scene_model, "lanes"))
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
    run_paths: list[_PathEstimate] = []
    path_by_scene: dict[str, _PathEstimate] = {}
    prior: object = None
    for scene in ordered:
        scene_id = _text(scene, "id")
        path = _scene_path(scene, atoms, lane_by_id, branches)
        path_by_scene[scene_id] = path
        terminal_ids = tuple(
            atom_id
            for atom_id in _strings(scene.get("atom_ids"), "scene atom IDs")
            if atoms[atom_id].get("kind") == "terminal"
        )
        run_key = (
            _text(scene, "chapter_id"),
            _text(scene, "lane_id"),
            branches.get(scene_id),
            _strings(scene.get("occurrence_ids"), "scene occurrence IDs"),
            scene.get("loop_hub_id"),
            terminal_ids,
            path,
        )
        if run_key != prior:
            runs.append([])
            run_paths.append(path)
            prior = run_key
        runs[-1].append(scene)

    segment_jobs = 0
    segment_roots = 0
    extra_segment_children = 0
    for run in runs:
        count = len(run)
        level = max(1, math.ceil(count / SEGMENT_TARGET_CHILDREN))
        segment_jobs += level
        segment_root_capacity = min(
            _DEFAULT_SEGMENT_CONFIG.maximum_children,
            (
                _DEFAULT_SEGMENT_CONFIG.maximum_input_tokens
                - _DEFAULT_SEGMENT_CONFIG.prompt_overhead_tokens
            )
            // _DEFAULT_SEGMENT_CONFIG.estimated_segment_output_tokens,
        )
        while level > segment_root_capacity:
            extra_segment_children += level
            level = math.ceil(level / SEGMENT_TARGET_CHILDREN)
            segment_jobs += level
        segment_roots += level

    selected_route_ids = {
        path.route_id for path in path_by_scene.values() if path.route_id is not None
    }
    route_count = len(selected_route_ids)
    ending_members: dict[tuple[str | None, tuple[str, ...]], int] = {}
    route_chapter_counts = {route_id: 0 for route_id in selected_route_ids}
    common_chapter_count = 0
    for path in run_paths:
        if path.section == "ending":
            if path.ending_key is None:
                raise ValueError("estimated ending path lost its deterministic identity")
            ending_membership = (path.route_id, path.ending_key)
            ending_members[ending_membership] = ending_members.get(ending_membership, 0) + 1
        elif path.route_id is None:
            common_chapter_count += 1
        else:
            route_chapter_counts[path.route_id] += 1
    ending_count = len(ending_members)

    speakers: set[str] = set()
    character_paths: dict[str, set[tuple[str | None, tuple[str, ...] | None]]] = {}
    common_characters: set[str] = set()
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
        scene_id = item.job.spec.owner_id
        path = path_by_scene[scene_id]
        for character_id in _strings(
            participation.get("character_ids"), "prepared character IDs"
        ):
            speakers.add(character_id)
            character_paths.setdefault(character_id, set()).add(
                (path.route_id, path.ending_key)
            )
            if path.route_id is None:
                common_characters.add(character_id)

    chapter_jobs = len(runs)
    hierarchy_jobs = segment_jobs + chapter_jobs
    hierarchy_input = (
        scene_run.estimate.output_tokens
        + extra_segment_children * HIERARCHY_OUTPUT_TOKENS
        + segment_jobs * HIERARCHY_PROMPT_OVERHEAD_TOKENS
        + segment_roots * HIERARCHY_OUTPUT_TOKENS
        + chapter_jobs * HIERARCHY_PROMPT_OVERHEAD_TOKENS
    )

    # A route-aware hierarchy exists only when the selected scope includes a shared spine.
    # This mirrors the fail-closed pipeline behavior for route-only partial selections.
    if common_chapter_count:
        common_reduction = _fan_in_estimate(common_chapter_count)
        hierarchy_jobs += common_reduction.logical_jobs + 1
        hierarchy_input += _fan_in_input_tokens(common_reduction)
        hierarchy_input += (
            common_reduction.root_count * HIERARCHY_OUTPUT_TOKENS
            + HIERARCHY_PROMPT_OVERHEAD_TOKENS
        )

        for selected_route_id in sorted(selected_route_ids):
            route_reduction = _fan_in_estimate(
                route_chapter_counts[selected_route_id],
                reserved_children=1,
            )
            hierarchy_jobs += route_reduction.logical_jobs + 1
            hierarchy_input += _fan_in_input_tokens(route_reduction)
            hierarchy_input += (
                (1 + route_reduction.root_count) * HIERARCHY_OUTPUT_TOKENS
                + HIERARCHY_PROMPT_OVERHEAD_TOKENS
            )

        for (ending_route_id, _ending_key), child_count in sorted(
            ending_members.items(),
            key=lambda item: (item[0][0] or "", item[0][1]),
        ):
            ending_reduction = _fan_in_estimate(
                child_count,
                reserved_children=1 if ending_route_id is not None else 0,
            )
            hierarchy_jobs += ending_reduction.logical_jobs + 1
            hierarchy_input += _fan_in_input_tokens(ending_reduction)
            hierarchy_input += (
                (
                    ending_reduction.root_count
                    + (1 if ending_route_id is not None else 0)
                )
                * HIERARCHY_OUTPUT_TOKENS
                + HIERARCHY_PROMPT_OVERHEAD_TOKENS
            )

        plot_reduction = _fan_in_estimate(
            route_count + ending_count,
            reserved_children=1,
        )
        hierarchy_jobs += plot_reduction.logical_jobs + 1
        hierarchy_input += _fan_in_input_tokens(plot_reduction)
        hierarchy_input += (
            (1 + plot_reduction.root_count) * HIERARCHY_OUTPUT_TOKENS
            + HIERARCHY_PROMPT_OVERHEAD_TOKENS
        )

        for character_id in sorted(speakers):
            paths = character_paths[character_id]
            child_count = (
                (1 if character_id in common_characters else 0)
                + len({route_id for route_id, _ending in paths if route_id is not None})
                + len({ending for _route, ending in paths if ending is not None})
            )
            character_reduction = _fan_in_estimate(child_count)
            hierarchy_jobs += character_reduction.logical_jobs + 1
            hierarchy_input += _fan_in_input_tokens(character_reduction)
            hierarchy_input += (
                character_reduction.root_count * HIERARCHY_OUTPUT_TOKENS
                + HIERARCHY_PROMPT_OVERHEAD_TOKENS
            )

    logical_jobs = scene_run.estimate.logical_job_count + hierarchy_jobs
    # Dependency-ready hierarchy levels cannot be transport-packed exactly until child output
    # sizes are known. One call per hierarchy job is therefore a deterministic safe upper bound.
    provider_calls = scene_run.estimate.provider_call_count + hierarchy_jobs
    scene_output = scene_run.estimate.output_tokens
    input_tokens = scene_run.estimate.input_tokens + hierarchy_input
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


def _fan_in_estimate(
    child_count: int,
    *,
    reserved_children: int = 0,
) -> _FanInEstimate:
    """Estimate a bounded deterministic reduction tree at the output-token ceiling."""

    if child_count < 0 or reserved_children < 0:
        raise ValueError("fan-in counts cannot be negative")
    token_capacity = (
        _DEFAULT_HIERARCHY_CONFIG.maximum_input_tokens
        - _DEFAULT_HIERARCHY_CONFIG.prompt_overhead_tokens
    ) // HIERARCHY_OUTPUT_TOKENS
    final_capacity = min(_DEFAULT_HIERARCHY_CONFIG.maximum_children, token_capacity)
    fan_in = min(
        HIERARCHY_REDUCTION_TARGET_CHILDREN,
        final_capacity,
    )
    if fan_in < 2:
        raise ValueError("default hierarchy settings cannot form a reducing fan-in tree")
    current = child_count
    logical_jobs = 0
    input_child_units = 0
    while current + reserved_children > final_capacity:
        input_child_units += current
        current = math.ceil(current / fan_in)
        logical_jobs += current
    return _FanInEstimate(logical_jobs, current, input_child_units)


def _fan_in_input_tokens(estimate: _FanInEstimate) -> int:
    return (
        estimate.input_child_units * HIERARCHY_OUTPUT_TOKENS
        + estimate.logical_jobs * HIERARCHY_PROMPT_OVERHEAD_TOKENS
    )


def _scene_path(
    scene: Mapping[str, object],
    atoms: Mapping[str, Mapping[str, object]],
    lanes: Mapping[str, Mapping[str, object]],
    branches: Mapping[str, tuple[str, str]],
) -> _PathEstimate:
    scene_id = _text(scene, "id")
    lane_id = _text(scene, "lane_id")
    ancestry = _lane_ancestry(lane_id, lanes)
    route_id = next(
        (
            item
            for item in reversed(ancestry)
            if lanes[item].get("kind")
            in {LaneKind.PERSISTENT_ROUTE.value, LaneKind.TERMINAL_SPLIT.value}
        ),
        None,
    )
    terminals = tuple(
        atom_id
        for atom_id in _strings(scene.get("atom_ids"), "scene atom IDs")
        if atoms[atom_id].get("kind") == "terminal"
    )
    if lanes[lane_id].get("kind") == LaneKind.TERMINAL_SPLIT.value:
        return _PathEstimate("ending", lane_id, ("lane", lane_id))
    if terminals:
        return _PathEstimate("ending", route_id, ("terminals", *terminals))
    if scene_id in branches:
        return _PathEstimate("temporary", route_id)
    if route_id is not None:
        return _PathEstimate("route", route_id)
    return _PathEstimate("common")


def _lane_ancestry(
    lane_id: str,
    lanes: Mapping[str, Mapping[str, object]],
) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    current: str | None = lane_id
    while current is not None:
        if current in seen:
            raise ValueError("M11 lane ancestry contains a cycle")
        seen.add(current)
        lane = lanes.get(current)
        if lane is None:
            raise ValueError("scene lane is absent from M11 authority")
        result.append(current)
        parent = lane.get("parent_lane_id")
        if parent is not None and (not isinstance(parent, str) or not parent.strip()):
            raise ValueError("M11 lane parent ID is malformed")
        current = parent
    result.reverse()
    return tuple(result)


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
