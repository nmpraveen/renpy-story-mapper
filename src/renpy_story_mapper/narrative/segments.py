"""Deterministic bounded segment planning for the M13 summary hierarchy.

Segments are internal narrative artifacts, never M11 scenes or memberships.
They reduce ordered child artifacts only within one exact structural and
chronological context, persist independently, and expose direct missing-child
state plus aggregate leaf coverage without duplicating transitive provenance.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

DEFAULT_PARTITION_VERSION = "m13-segment-partition-v1"


def _require_identifier(value: str, *, name: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty, trimmed string.")


def _require_optional_identifier(value: str | None, *, name: str) -> None:
    if value is not None:
        _require_identifier(value, name=name)


@dataclass(frozen=True)
class SegmentStructuralContext:
    """All M11-owned boundaries that a segment must not cross."""

    chapter_id: str
    chronology_anchor_id: str
    persistent_lane_id: str | None = None
    temporary_container_id: str | None = None
    temporary_arm_id: str | None = None
    occurrence_id: str | None = None
    call_context_id: str | None = None
    loop_id: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.chapter_id, name="chapter_id")
        _require_identifier(self.chronology_anchor_id, name="chronology_anchor_id")
        for name, value in (
            ("persistent_lane_id", self.persistent_lane_id),
            ("temporary_container_id", self.temporary_container_id),
            ("temporary_arm_id", self.temporary_arm_id),
            ("occurrence_id", self.occurrence_id),
            ("call_context_id", self.call_context_id),
            ("loop_id", self.loop_id),
        ):
            _require_optional_identifier(value, name=name)
        if self.temporary_arm_id is not None and self.temporary_container_id is None:
            raise ValueError("temporary_arm_id requires temporary_container_id.")
        if self.call_context_id is not None and self.occurrence_id is None:
            raise ValueError("call_context_id requires occurrence_id.")

    def identity_fields(self) -> dict[str, str | None]:
        """Return the complete deterministic structural identity."""

        return {
            "chapter_id": self.chapter_id,
            "chronology_anchor_id": self.chronology_anchor_id,
            "persistent_lane_id": self.persistent_lane_id,
            "temporary_container_id": self.temporary_container_id,
            "temporary_arm_id": self.temporary_arm_id,
            "occurrence_id": self.occurrence_id,
            "call_context_id": self.call_context_id,
            "loop_id": self.loop_id,
        }


@dataclass(frozen=True)
class SegmentChild:
    """One expected child artifact and its provider-preflight/coverage facts."""

    artifact_id: str
    chronology_index: int
    estimated_tokens: int
    context: SegmentStructuralContext
    available: bool = True
    expected_leaf_count: int = 1
    covered_leaf_count: int | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.artifact_id, name="artifact_id")
        if self.chronology_index < 0:
            raise ValueError("chronology_index must be non-negative.")
        if self.estimated_tokens < 0:
            raise ValueError("estimated_tokens must be non-negative.")
        if self.expected_leaf_count <= 0:
            raise ValueError("expected_leaf_count must be positive.")
        covered = self.covered_leaf_count
        if covered is None:
            covered = self.expected_leaf_count if self.available else 0
            object.__setattr__(self, "covered_leaf_count", covered)
        if covered < 0 or covered > self.expected_leaf_count:
            raise ValueError("covered_leaf_count must be within expected leaf coverage.")
        if not self.available and covered != 0:
            raise ValueError("An unavailable child cannot report covered leaves.")


@dataclass(frozen=True)
class SegmentPartitionConfig:
    """Versioned deterministic fan-in and token-preflight policy."""

    locale: str
    perspective: str
    partition_version: str = DEFAULT_PARTITION_VERSION
    minimum_children: int = 16
    target_children: int = 24
    maximum_children: int = 32
    maximum_input_tokens: int = 24_000
    prompt_overhead_tokens: int = 256
    estimated_segment_output_tokens: int = 768

    def __post_init__(self) -> None:
        _require_identifier(self.locale, name="locale")
        _require_identifier(self.perspective, name="perspective")
        _require_identifier(self.partition_version, name="partition_version")
        if not 1 <= self.minimum_children <= self.target_children <= self.maximum_children:
            raise ValueError(
                "Child bounds must satisfy 1 <= minimum <= target <= maximum."
            )
        if self.maximum_input_tokens <= 0:
            raise ValueError("maximum_input_tokens must be positive.")
        if self.prompt_overhead_tokens < 0:
            raise ValueError("prompt_overhead_tokens must be non-negative.")
        if self.estimated_segment_output_tokens <= 0:
            raise ValueError("estimated_segment_output_tokens must be positive.")
        if self.prompt_overhead_tokens >= self.maximum_input_tokens:
            raise ValueError("Prompt overhead must leave room for child artifacts.")
        if (
            self.prompt_overhead_tokens + self.estimated_segment_output_tokens
            > self.maximum_input_tokens
        ):
            raise ValueError("A segment output estimate must fit as a later reduction child.")


@dataclass(frozen=True)
class SegmentDescriptor:
    """A persistable internal job descriptor, explicitly not M11 membership."""

    segment_id: str
    level: int
    ordinal: int
    context: SegmentStructuralContext
    partition_version: str
    locale: str
    perspective: str
    child_artifact_ids: tuple[str, ...]
    available_child_artifact_ids: tuple[str, ...]
    missing_child_artifact_ids: tuple[str, ...]
    estimated_input_tokens: int
    expected_leaf_count: int
    covered_leaf_count: int

    def __post_init__(self) -> None:
        _require_identifier(self.segment_id, name="segment_id")
        if self.level < 0 or self.ordinal < 0:
            raise ValueError("Segment level and ordinal must be non-negative.")
        if not self.child_artifact_ids:
            raise ValueError("A segment must reference at least one expected child artifact.")
        if len(self.child_artifact_ids) != len(set(self.child_artifact_ids)):
            raise ValueError("A segment cannot repeat a child artifact ID.")
        child_ids = set(self.child_artifact_ids)
        available_ids = set(self.available_child_artifact_ids)
        missing_ids = set(self.missing_child_artifact_ids)
        if available_ids & missing_ids or available_ids | missing_ids != child_ids:
            raise ValueError("Available and missing child IDs must exactly partition children.")
        if self.expected_leaf_count <= 0:
            raise ValueError("expected_leaf_count must be positive.")
        if not 0 <= self.covered_leaf_count <= self.expected_leaf_count:
            raise ValueError("covered_leaf_count must be within expected leaf coverage.")
        if self.estimated_input_tokens <= 0:
            raise ValueError("estimated_input_tokens must be positive.")

    @property
    def coverage_percentage(self) -> float:
        """Aggregate deterministic coverage rounded for stable presentation."""

        return round(self.covered_leaf_count * 100 / self.expected_leaf_count, 6)

    @property
    def complete(self) -> bool:
        return self.covered_leaf_count == self.expected_leaf_count


@dataclass(frozen=True)
class SegmentPlan:
    """All independently persistable jobs plus bounded roots for consumers."""

    descriptors: tuple[SegmentDescriptor, ...]
    roots: tuple[SegmentDescriptor, ...]

    @property
    def descriptor_ids(self) -> tuple[str, ...]:
        return tuple(descriptor.segment_id for descriptor in self.descriptors)

    @property
    def root_ids(self) -> tuple[str, ...]:
        return tuple(descriptor.segment_id for descriptor in self.roots)


def plan_summary_segments(
    children: tuple[SegmentChild, ...],
    config: SegmentPartitionConfig,
) -> SegmentPlan:
    """Build a route-safe, token-bounded deterministic reduction forest.

    Input order is authoritative chronology.  Context changes form hard runs;
    no descriptor ever crosses a chapter, persistent lane, temporary arm,
    occurrence/call, loop, or chronology anchor.  Each run reduces separately.
    """

    if not children:
        return SegmentPlan(descriptors=(), roots=())
    _validate_children(children, config)
    descriptors: list[SegmentDescriptor] = []
    roots: list[SegmentDescriptor] = []
    for run in _context_runs(children):
        level = 0
        current = _make_level(run, config=config, level=level)
        descriptors.extend(current)
        while _requires_reduction(current, config):
            level += 1
            reduction_children = tuple(
                SegmentChild(
                    artifact_id=descriptor.segment_id,
                    chronology_index=index,
                    estimated_tokens=config.estimated_segment_output_tokens,
                    context=descriptor.context,
                    available=descriptor.covered_leaf_count > 0,
                    expected_leaf_count=descriptor.expected_leaf_count,
                    covered_leaf_count=descriptor.covered_leaf_count,
                )
                for index, descriptor in enumerate(current)
            )
            reduced = _make_level(reduction_children, config=config, level=level)
            if len(reduced) >= len(current):
                raise ValueError(
                    "The configured token limit cannot reduce this segment level; "
                    "increase maximum_input_tokens or lower the output estimate."
                )
            current = reduced
            descriptors.extend(current)
        roots.extend(current)
    return SegmentPlan(descriptors=tuple(descriptors), roots=tuple(roots))


def _validate_children(
    children: tuple[SegmentChild, ...], config: SegmentPartitionConfig
) -> None:
    identifiers = [child.artifact_id for child in children]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Expected child artifact IDs must be globally unique in one plan.")
    previous_context: SegmentStructuralContext | None = None
    previous_index = -1
    closed_contexts: set[SegmentStructuralContext] = set()
    for child in children:
        if (
            config.prompt_overhead_tokens + child.estimated_tokens
            > config.maximum_input_tokens
        ):
            raise ValueError(
                f"Child artifact {child.artifact_id!r} exceeds the segment token limit."
            )
        if child.context != previous_context:
            if previous_context is not None:
                closed_contexts.add(previous_context)
            if child.context in closed_contexts:
                raise ValueError(
                    "A structural chronology context cannot reappear after another context; "
                    "use a distinct chronology_anchor_id for a later run."
                )
            previous_context = child.context
            previous_index = -1
        if child.chronology_index <= previous_index:
            raise ValueError(
                "chronology_index must increase strictly inside each structural context."
            )
        previous_index = child.chronology_index


def _context_runs(
    children: tuple[SegmentChild, ...],
) -> tuple[tuple[SegmentChild, ...], ...]:
    runs: list[tuple[SegmentChild, ...]] = []
    pending: list[SegmentChild] = []
    context: SegmentStructuralContext | None = None
    for child in children:
        if context is not None and child.context != context:
            runs.append(tuple(pending))
            pending = []
        pending.append(child)
        context = child.context
    if pending:
        runs.append(tuple(pending))
    return tuple(runs)


def _make_level(
    children: tuple[SegmentChild, ...],
    *,
    config: SegmentPartitionConfig,
    level: int,
) -> tuple[SegmentDescriptor, ...]:
    groups = _partition_children(children, config)
    return tuple(
        _make_descriptor(group, config=config, level=level, ordinal=ordinal)
        for ordinal, group in enumerate(groups)
    )


def _partition_children(
    children: tuple[SegmentChild, ...],
    config: SegmentPartitionConfig,
) -> tuple[tuple[SegmentChild, ...], ...]:
    """Balance count first, then deterministically lower fan-in for token fit."""

    count = len(children)
    target_groups = math.ceil(count / config.target_children)
    minimum_groups = math.ceil(count / config.maximum_children)
    maximum_groups = max(1, count // config.minimum_children)
    group_count = min(maximum_groups, max(minimum_groups, target_groups))
    count_groups = _balanced_slices(children, group_count)
    groups: list[tuple[SegmentChild, ...]] = []
    token_capacity = config.maximum_input_tokens - config.prompt_overhead_tokens
    for count_group in count_groups:
        pending: list[SegmentChild] = []
        pending_tokens = 0
        for child in count_group:
            overflow = bool(pending) and (
                len(pending) >= config.maximum_children
                or pending_tokens + child.estimated_tokens > token_capacity
            )
            if overflow:
                groups.append(tuple(pending))
                pending = []
                pending_tokens = 0
            pending.append(child)
            pending_tokens += child.estimated_tokens
        if pending:
            groups.append(tuple(pending))
    return tuple(groups)


def _balanced_slices(
    children: tuple[SegmentChild, ...], group_count: int
) -> tuple[tuple[SegmentChild, ...], ...]:
    base, remainder = divmod(len(children), group_count)
    groups: list[tuple[SegmentChild, ...]] = []
    offset = 0
    for index in range(group_count):
        size = base + (1 if index < remainder else 0)
        groups.append(children[offset : offset + size])
        offset += size
    return tuple(groups)


def _make_descriptor(
    children: tuple[SegmentChild, ...],
    *,
    config: SegmentPartitionConfig,
    level: int,
    ordinal: int,
) -> SegmentDescriptor:
    context = children[0].context
    if any(child.context != context for child in children):
        raise ValueError("A segment cannot cross structural contexts.")
    child_ids = tuple(child.artifact_id for child in children)
    available_ids = tuple(child.artifact_id for child in children if child.available)
    missing_ids = tuple(child.artifact_id for child in children if not child.available)
    material = {
        "artifact_kind": "m13_summary_segment",
        "partition_version": config.partition_version,
        "locale": config.locale,
        "perspective": config.perspective,
        "level": level,
        "structural_context": context.identity_fields(),
        "ordered_child_artifact_ids": child_ids,
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return SegmentDescriptor(
        segment_id=f"m13-segment-{hashlib.sha256(encoded).hexdigest()}",
        level=level,
        ordinal=ordinal,
        context=context,
        partition_version=config.partition_version,
        locale=config.locale,
        perspective=config.perspective,
        child_artifact_ids=child_ids,
        available_child_artifact_ids=available_ids,
        missing_child_artifact_ids=missing_ids,
        estimated_input_tokens=config.prompt_overhead_tokens
        + sum(child.estimated_tokens for child in children if child.available),
        expected_leaf_count=sum(child.expected_leaf_count for child in children),
        covered_leaf_count=sum(
            child.covered_leaf_count if child.covered_leaf_count is not None else 0
            for child in children
        ),
    )


def _requires_reduction(
    descriptors: tuple[SegmentDescriptor, ...],
    config: SegmentPartitionConfig,
) -> bool:
    return bool(
        len(descriptors) > config.maximum_children
        or config.prompt_overhead_tokens
        + len(descriptors) * config.estimated_segment_output_tokens
        > config.maximum_input_tokens
    )
