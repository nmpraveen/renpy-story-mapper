"""Coherent, deterministic Story Map V2 chunk planning."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass

from renpy_story_mapper.story_map_v2.contracts import (
    ChoiceMechanic,
    ChunkProfile,
    DensityMetrics,
    SourceSpan,
    StoryChunk,
    StoryScope,
    canonical_hash,
)


class ChunkPlanningError(ValueError):
    """The scope cannot be partitioned without violating a coherent boundary."""


DEFAULT_CHUNK_PROFILE = ChunkProfile()


def plan_chunks(
    scope: StoryScope,
    profile: ChunkProfile = DEFAULT_CHUNK_PROFILE,
) -> tuple[StoryChunk, ...]:
    """Plan contiguous chunks while preserving every fitting coherent choice cluster."""

    if not scope.spans:
        return ()
    units = _coherent_units(scope, profile)
    planned: list[StoryChunk] = []
    cursor = 0
    while cursor < len(units):
        end = _choose_end(scope, units, cursor, profile)
        spans = tuple(span for unit in units[cursor:end] for span in unit.spans)
        planned.append(_story_chunk(scope, spans, len(planned) + 1))
        cursor = end
    return tuple(planned)


@dataclass(frozen=True)
class _Unit:
    spans: tuple[SourceSpan, ...]
    tokens: int
    boundary_after: bool


def mechanics_digest(scope: StoryScope, choice_keys: Iterable[str]) -> str:
    """Return the compact deterministic mechanics packet for the selected choices."""

    ordered_keys = tuple(choice_keys)
    choices_by_key = {choice.key: choice for choice in scope.choices}
    choices = [choices_by_key[key] for key in ordered_keys if key in choices_by_key]
    value = {
        "choices": [
            {
                "key": choice.key,
                "path": choice.relative_path,
                "line": choice.line,
                "story_choice": choice.story_choice,
                "parent_lineage": [asdict(step) for step in choice.parent_lineage],
                "arms": [
                    {
                        "order": arm.order,
                        "caption": arm.caption,
                        "range": [arm.start_line, arm.end_line],
                        "condition": arm.condition,
                        "effects": list(arm.effects),
                        "destination": arm.destination_id,
                        "rejoin": arm.rejoin_node_id,
                        "rejoin_line": arm.rejoin_line,
                        "reachability": arm.reachability.value,
                        "warnings": list(arm.unresolved_warnings),
                    }
                    for arm in choice.arms
                ],
            }
            for choice in choices
        ]
    }
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _coherent_units(scope: StoryScope, profile: ChunkProfile) -> tuple[_Unit, ...]:
    intervals = _choice_intervals(scope)
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    start_to_end = {start: end for start, end in merged}
    covered = {index for start, end in merged for index in range(start, end + 1)}
    units: list[_Unit] = []
    index = 0
    while index < len(scope.spans):
        if index in start_to_end:
            end = start_to_end[index]
            spans = scope.spans[index : end + 1]
            tokens = sum(item.estimated_tokens for item in spans)
            if tokens > profile.maximum_tokens:
                keys = tuple(dict.fromkeys(key for item in spans for key in item.choice_keys))
                raise ChunkPlanningError(
                    "indivisible choice cluster exceeds the validated ceiling: "
                    f"{tokens} > {profile.maximum_tokens}; choices={keys}"
                )
            units.append(_Unit(spans, tokens, spans[-1].natural_boundary_after))
            index = end + 1
            continue
        if index in covered:
            index += 1
            continue
        span = scope.spans[index]
        if span.estimated_tokens > profile.maximum_tokens:
            raise ChunkPlanningError(
                "source span exceeds the validated ceiling and cannot be split safely: "
                f"{span.key}={span.estimated_tokens}"
            )
        units.append(_Unit((span,), span.estimated_tokens, span.natural_boundary_after))
        index += 1
    return tuple(units)


def _choice_intervals(scope: StoryScope) -> tuple[tuple[int, int], ...]:
    result: list[tuple[int, int]] = []
    for choice in scope.choices:
        indices = [
            index for index, span in enumerate(scope.spans) if _span_in_choice_cluster(span, choice)
        ]
        if indices:
            result.append((min(indices), max(indices)))
    return tuple(result)


def _span_in_choice_cluster(span: SourceSpan, choice: ChoiceMechanic) -> bool:
    if span.relative_path != choice.relative_path:
        return False
    rejoin_ids = {arm.rejoin_node_id for arm in choice.arms}
    has_local_rejoin = len(rejoin_ids) == 1 and None not in rejoin_ids
    if has_local_rejoin and choice.key in span.choice_keys:
        return True
    if not has_local_rejoin:
        first_line = min(choice.line, *(arm.start_line for arm in choice.arms))
        last_line = max(arm.end_line for arm in choice.arms)
        return span.start_line <= last_line and span.end_line >= first_line
    last_line = max(
        (
            arm.rejoin_line
            for arm in choice.arms
            if arm.rejoin_line is not None and arm.rejoin_node_id is not None
        ),
        default=max(arm.end_line for arm in choice.arms),
    )
    first_line = min(choice.line, *(arm.start_line for arm in choice.arms))
    return span.start_line <= last_line and span.end_line >= first_line


def _choose_end(
    scope: StoryScope,
    units: Sequence[_Unit],
    start: int,
    profile: ChunkProfile,
) -> int:
    cumulative = 0
    possible: list[tuple[int, int, bool, DensityMetrics]] = []
    spans: list[SourceSpan] = []
    for index in range(start, len(units)):
        unit = units[index]
        if cumulative + unit.tokens > profile.maximum_tokens:
            break
        cumulative += unit.tokens
        spans.extend(unit.spans)
        choice_keys = tuple(dict.fromkeys(key for span in spans for key in span.choice_keys))
        possible.append(
            (
                index + 1,
                cumulative,
                unit.boundary_after,
                _density(scope, choice_keys, spans),
            )
        )
    if not possible:
        raise ChunkPlanningError("no coherent unit fits below the validated ceiling")

    target = profile.target_tokens
    if any(item[3].branch_weight >= profile.branch_weight_threshold for item in possible):
        target = profile.branch_target_tokens
    before = [item for item in possible if item[1] <= target and item[2]]
    if before:
        return before[-1][0]
    after = [item for item in possible if item[1] > target and item[2]]
    if after:
        return after[0][0]
    at_or_above = [item for item in possible if item[1] >= target]
    if at_or_above:
        return at_or_above[0][0]
    return possible[-1][0]


def _story_chunk(scope: StoryScope, spans: Sequence[SourceSpan], index: int) -> StoryChunk:
    choice_keys = tuple(dict.fromkeys(key for span in spans for key in span.choice_keys))
    raw_text = render_chunk_raw_text(spans)
    density = _density(scope, choice_keys, spans)
    digest = mechanics_digest(scope, choice_keys)
    packet_hash = canonical_hash(
        {
            "source_identity": scope.source_identity,
            "source_generation": scope.source_generation,
            "canonical_hash": scope.canonical_hash,
            "span_keys": [span.key for span in spans],
            "raw_text": raw_text,
            "mechanics": digest,
            "density": asdict(density),
        }
    )
    return StoryChunk(
        index=index,
        span_keys=tuple(span.key for span in spans),
        choice_keys=choice_keys,
        raw_text=raw_text,
        mechanics=digest,
        raw_tokens=sum(span.estimated_tokens for span in spans),
        density=density,
        packet_hash=packet_hash,
    )


def render_chunk_raw_text(spans: Sequence[SourceSpan]) -> str:
    """Render exact story text with deterministic, non-story source-path context."""

    return "".join(
        "@@SOURCE "
        + json.dumps(
            {
                "end_line": span.end_line,
                "path": span.relative_path,
                "start_line": span.start_line,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        + span.raw_text
        for span in spans
    )


def _density_for_spans(spans: Sequence[SourceSpan]) -> DensityMetrics:
    choice_keys = tuple(dict.fromkeys(key for span in spans for key in span.choice_keys))
    text = "\n".join(span.raw_text for span in spans)
    return DensityMetrics(
        menus=len(choice_keys),
        conditions=sum(_source_kind(line) in {"if", "elif"} for line in text.splitlines()),
        transfers=sum(
            _source_kind(line) in {"jump", "call", "return"} for line in text.splitlines()
        ),
        unresolved=sum("unresolved" in line.casefold() for line in text.splitlines()),
    )


def _density(
    scope: StoryScope,
    choice_keys: Sequence[str],
    spans: Sequence[SourceSpan],
) -> DensityMetrics:
    selected = [choice for choice in scope.choices if choice.key in set(choice_keys)]
    lexical = _density_for_spans(spans)
    return DensityMetrics(
        menus=len(selected),
        arms=sum(len(choice.arms) for choice in selected),
        conditions=lexical.conditions
        + sum(arm.condition is not None for choice in selected for arm in choice.arms),
        transfers=lexical.transfers
        + sum(arm.destination_id is not None for choice in selected for arm in choice.arms),
        unresolved=lexical.unresolved
        + sum(
            arm.reachability.value == "unresolved" or bool(arm.unresolved_warnings)
            for choice in selected
            for arm in choice.arms
        ),
    )


def _source_kind(line: str) -> str:
    value = re.sub(r"^\s*\d+:\s*", "", line).lstrip()
    return value.split(maxsplit=1)[0].rstrip(":") if value else ""
