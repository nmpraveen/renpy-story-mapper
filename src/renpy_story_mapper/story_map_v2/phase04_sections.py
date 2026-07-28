"""Dependency-aware Phase 04 section synthesis and fixed-membership rollups.

This module implements the C1 side of ``story-map-v2-derived-semantic-workflow-v2``.  Prepare
freezes only deterministic corridor/route upper bounds and finite call ceilings.  Exact semantic
jobs and request bytes are derived later, after their existing children have published.  The
module is provider-free: callers may submit the returned requests through Track B, while tests use
public fakes.  Invalid or absent output falls back once without repair, review, or loopback.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from renpy_story_mapper.story_map_v2.contracts import canonical_hash, canonical_json
from renpy_story_mapper.story_map_v2.phase04_chunk_plan import StoryChunkPlan
from renpy_story_mapper.story_map_v2.phase04_semantics import (
    SemanticAssembly,
    SemanticEvent,
    SemanticOrigin,
    SemanticValidationError,
)

DERIVED_SEMANTIC_WORKFLOW_VERSION = "story-map-v2-derived-semantic-workflow-v2"
SECTION_SYNTHESIS_PROMPT_VERSION = "story-map-v2-phase04-section-prompt-v1"
SECTION_SYNTHESIS_SCHEMA_VERSION = "story-map-v2-phase04-section-response-v1"
SECTION_SYNTHESIS_ADAPTER_VERSION = "story-map-v2-phase04-section-adapter-v1"
ROLLUP_SYNTHESIS_PROMPT_VERSION = "story-map-v2-phase04-rollup-prompt-v1"
ROLLUP_SYNTHESIS_SCHEMA_VERSION = "story-map-v2-phase04-rollup-response-v1"
ROLLUP_SYNTHESIS_ADAPTER_VERSION = "story-map-v2-phase04-rollup-adapter-v1"
SECTION_SYNTHESIS_TASK = (
    "Return exactly one JSON object matching the supplied section prose schema. Group the "
    "ordered child events into a small number of meaningful contiguous story sections. Cover "
    "every child exactly once and preserve order. Write only titles and summaries; do not "
    "change membership, routes, choices, or mechanics. Do not use tools, files, web search, "
    "apps, plugins, other agents, or provider calls."
)
ROLLUP_SYNTHESIS_TASK = (
    "Return exactly one JSON object matching the supplied rollup prose schema. Write a concise "
    "title and narrative overview for the ordered child summaries. Treat persistent routes as "
    "alternatives when identified. Do not add events, choices, routes, endings, or mechanics. "
    "Do not use tools, files, web search, apps, plugins, other agents, or provider calls."
)
EDITORIAL_TIMELINE_TASK = (
    "Return exactly one JSON object matching the supplied section prose schema. Group the "
    "ordered source sections into a small chronological story timeline using reasonably balanced "
    "ranges. For twelve or more source sections, return between 12 and 30 contiguous groups, "
    "with no group containing more than 40 source sections. Cover every source section exactly "
    "once and preserve order. The top-level summary is the whole-story overview. Write only "
    "titles and summaries; do not add or change choices, routes, effects, rejoins, endings, or "
    "evidence."
)
EDITORIAL_TIMELINE_BATCH_TASK = (
    "Return exactly one JSON object matching the supplied section prose schema. Group this "
    "chronological slice into exactly two contiguous story groups. Cover every source section "
    "exactly once and preserve order. The first group must start at the first ordered child; the "
    "second must start immediately after the first group's last child and end at the final ordered "
    "child. Do not skip or overlap any child. Write only titles and summaries; do not add or "
    "change choices, routes, effects, rejoins, endings, or evidence."
)
EDITORIAL_TIMELINE_ROLLUP_TASK = (
    "Return exactly one JSON object matching the supplied rollup prose schema. Write a concise "
    "title and one coherent whole-story overview of about 450-650 characters in complete "
    "sentences, ending at a sentence boundary. Follow the ordered story groups chronologically "
    "and treat persistent routes as alternatives when identified. Do not add events, choices, "
    "routes, effects, rejoins, endings, or mechanics."
)
EDITORIAL_TIMELINE_CORRIDOR_ID = "editorial-timeline"
EDITORIAL_MAX_SOURCE_SECTIONS_PER_GROUP = 40
EDITORIAL_GROUPS_PER_BATCH = 2
EDITORIAL_MIN_BATCH_COUNT = 6
EDITORIAL_MAX_BATCH_COUNT = 15
DERIVED_SEMANTIC_FAN_IN = 24
DERIVED_PROVIDER = "codex-cli"
DERIVED_MODEL = "gpt-5.6-terra"
DERIVED_REASONING = "high"
DERIVED_FAST_MODE = False


class DerivedSemanticError(ValueError):
    """A derived semantic plan, job, or response violates frozen membership."""


class DerivedCallKind(StrEnum):
    SECTION_SYNTHESIS = "section_synthesis"
    ROLLUP_SYNTHESIS = "rollup_synthesis"


class RollupNodeRole(StrEnum):
    ROUTE_REDUCTION = "route_reduction"
    ROUTE_SUMMARY = "route_summary"
    WHOLE_GAME_REDUCTION = "whole_game_reduction"
    FINAL_OVERVIEW = "final_overview"


class DerivedStage(StrEnum):
    SECTION = "section"
    ROLLUP = "rollup"


@dataclass(frozen=True)
class ExactRequestIdentity:
    """Scalar exact-request binding adapted to Track B at integration."""

    value: str
    sha256: str
    byte_count: int

    def __post_init__(self) -> None:
        _trimmed(self.value, "derived request identity")
        if (
            len(self.sha256) != 64
            or self.sha256 != self.sha256.lower()
            or any(character not in "0123456789abcdef" for character in self.sha256)
        ):
            raise ValueError("derived request SHA-256 must be a lowercase hexadecimal digest")
        if type(self.byte_count) is not int or self.byte_count < 1:
            raise ValueError("derived request byte count must be a positive integer")

    def verify(self, request: bytes) -> None:
        if (
            len(request) != self.byte_count
            or hashlib.sha256(request).hexdigest() != self.sha256
        ):
            raise ValueError("derived request bytes differ from their exact identity")


def _trimmed(value: str, label: str, *, maximum: int = 2_000) -> str:
    if not value or value != value.strip() or len(value) > maximum:
        raise DerivedSemanticError(f"{label} must be non-empty, trimmed, and bounded")
    return value


def _reduce_calls(value: int, fan_in: int = DERIVED_SEMANTIC_FAN_IN) -> int:
    if value <= fan_in:
        return 0
    next_value = math.ceil(value / fan_in)
    return next_value + _reduce_calls(next_value, fan_in)


@dataclass(frozen=True)
class DerivedCorridorDescriptor:
    corridor_id: str
    route_owner: str | None
    event_slot_upper_bound: int
    ordinal: int

    def __post_init__(self) -> None:
        _trimmed(self.corridor_id, "corridor ID")
        if self.route_owner is not None:
            _trimmed(self.route_owner, "route owner")
        if self.event_slot_upper_bound < 1 or self.ordinal < 0:
            raise ValueError("corridor upper bound must be positive and ordinal non-negative")


@dataclass(frozen=True)
class PersistentRouteMembership:
    route_owner: str
    corridor_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _trimmed(self.route_owner, "persistent route owner")
        if not self.corridor_ids or len(self.corridor_ids) != len(set(self.corridor_ids)):
            raise ValueError("persistent route corridors must be non-empty and unique")


@dataclass(frozen=True)
class DerivedSemanticCeilings:
    section_synthesis_calls: int
    route_reduction_calls: int
    route_summary_calls: int
    whole_game_reduction_calls: int
    final_overview_calls: int
    rollup_synthesis_calls: int

    def __post_init__(self) -> None:
        values = (
            self.section_synthesis_calls,
            self.route_reduction_calls,
            self.route_summary_calls,
            self.whole_game_reduction_calls,
            self.final_overview_calls,
            self.rollup_synthesis_calls,
        )
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("derived semantic ceilings must be non-negative integers")
        expected = sum(values[1:5])
        if self.rollup_synthesis_calls != expected:
            raise ValueError("rollup synthesis total must equal its exact component ceilings")


@dataclass(frozen=True)
class DerivedSemanticPlan:
    story_chunk_plan_identity: str
    authority_identity: str
    corridors: tuple[DerivedCorridorDescriptor, ...]
    persistent_routes: tuple[PersistentRouteMembership, ...]
    ceilings: DerivedSemanticCeilings
    fan_in: int = DERIVED_SEMANTIC_FAN_IN
    version: str = DERIVED_SEMANTIC_WORKFLOW_VERSION

    def __post_init__(self) -> None:
        _trimmed(self.story_chunk_plan_identity, "StoryChunkPlan identity")
        _trimmed(self.authority_identity, "authority identity")
        if self.version != DERIVED_SEMANTIC_WORKFLOW_VERSION:
            raise ValueError("unsupported derived semantic workflow version")
        if self.fan_in != DERIVED_SEMANTIC_FAN_IN:
            raise ValueError("derived semantic fan-in must remain frozen at 24")
        if tuple(corridor.ordinal for corridor in self.corridors) != tuple(
            range(len(self.corridors))
        ):
            raise ValueError("derived corridors require contiguous zero-based ordinals")
        corridor_ids = tuple(corridor.corridor_id for corridor in self.corridors)
        if len(corridor_ids) != len(set(corridor_ids)):
            raise ValueError("derived corridor IDs must be unique")
        route_owners = tuple(route.route_owner for route in self.persistent_routes)
        if len(route_owners) != len(set(route_owners)):
            raise ValueError("persistent route owners must be unique")
        expected_route_owners = tuple(
            dict.fromkeys(
                corridor.route_owner
                for corridor in self.corridors
                if corridor.route_owner is not None
            )
        )
        if route_owners != expected_route_owners:
            raise ValueError("persistent route order must match frozen corridor order")
        routed = tuple(item for route in self.persistent_routes for item in route.corridor_ids)
        if len(routed) != len(set(routed)) or any(item not in corridor_ids for item in routed):
            raise ValueError("persistent route membership must be exact and non-overlapping")
        for route in self.persistent_routes:
            expected_corridors = tuple(
                corridor.corridor_id
                for corridor in self.corridors
                if corridor.route_owner == route.route_owner
            )
            if route.corridor_ids != expected_corridors:
                raise ValueError("persistent route membership has wrong order or ownership")
        if self.ceilings != _derived_ceilings(self.corridors, self.persistent_routes):
            raise ValueError("derived semantic ceilings differ from the frozen formula")

    @property
    def semantic_plan_identity(self) -> str:
        return canonical_hash(_semantic_plan_object(self))


def _semantic_plan_object(plan: DerivedSemanticPlan) -> dict[str, object]:
    return {
        "version": plan.version,
        "story_chunk_plan_identity": plan.story_chunk_plan_identity,
        "authority_identity": plan.authority_identity,
        "fan_in": plan.fan_in,
        "corridors": [
            {
                "corridor_id": corridor.corridor_id,
                "route_owner": corridor.route_owner,
                "event_slot_upper_bound": corridor.event_slot_upper_bound,
                "ordinal": corridor.ordinal,
            }
            for corridor in plan.corridors
        ],
        "persistent_routes": [
            {
                "route_owner": route.route_owner,
                "corridor_ids": list(route.corridor_ids),
            }
            for route in plan.persistent_routes
        ],
        "ceilings": {
            "section_synthesis_calls": plan.ceilings.section_synthesis_calls,
            "route_reduction_calls": plan.ceilings.route_reduction_calls,
            "route_summary_calls": plan.ceilings.route_summary_calls,
            "whole_game_reduction_calls": plan.ceilings.whole_game_reduction_calls,
            "final_overview_calls": plan.ceilings.final_overview_calls,
            "rollup_synthesis_calls": plan.ceilings.rollup_synthesis_calls,
        },
    }


def _derived_ceilings(
    corridors: tuple[DerivedCorridorDescriptor, ...],
    routes: tuple[PersistentRouteMembership, ...],
) -> DerivedSemanticCeilings:
    by_id = {corridor.corridor_id: corridor for corridor in corridors}
    routed = {corridor_id for route in routes for corridor_id in route.corridor_ids}
    route_reductions = sum(
        _reduce_calls(sum(by_id[item].event_slot_upper_bound for item in route.corridor_ids))
        for route in routes
    )
    common_upper_bound = sum(
        corridor.event_slot_upper_bound
        for corridor in corridors
        if corridor.corridor_id not in routed
    )
    whole_input = common_upper_bound + len(routes)
    route_summaries = len(routes)
    whole_reductions = _reduce_calls(whole_input)
    final_overview = 1 if whole_input > 0 else 0
    return DerivedSemanticCeilings(
        section_synthesis_calls=len(corridors),
        route_reduction_calls=route_reductions,
        route_summary_calls=route_summaries,
        whole_game_reduction_calls=whole_reductions,
        final_overview_calls=final_overview,
        rollup_synthesis_calls=(
            route_reductions + route_summaries + whole_reductions + final_overview
        ),
    )


def build_derived_semantic_plan(
    chunk_plan: StoryChunkPlan,
    authority_identity: str,
) -> DerivedSemanticPlan:
    """Freeze v2 corridor upper bounds without guessing later child IDs or request bytes."""

    bindings = {binding.scope_id: binding for binding in chunk_plan.scope_bindings}
    corridors: list[DerivedCorridorDescriptor] = []
    route_corridors: dict[str, list[str]] = {}
    for ordinal, chunk in enumerate(chunk_plan.chunks):
        binding = bindings[chunk.scope_id]
        route_owner = binding.lane_id if binding.persistent_lane else None
        corridors.append(
            DerivedCorridorDescriptor(
                chunk.chunk_id,
                route_owner,
                len(chunk.placement_ids),
                ordinal,
            )
        )
        if route_owner is not None:
            route_corridors.setdefault(route_owner, []).append(chunk.chunk_id)
    routes = tuple(
        PersistentRouteMembership(owner, tuple(corridor_ids))
        for owner, corridor_ids in route_corridors.items()
    )
    corridor_tuple = tuple(corridors)
    return DerivedSemanticPlan(
        story_chunk_plan_identity=chunk_plan.identity,
        authority_identity=authority_identity,
        corridors=corridor_tuple,
        persistent_routes=routes,
        ceilings=_derived_ceilings(corridor_tuple, routes),
    )


@dataclass(frozen=True)
class MeaningfulSection:
    section_id: str
    corridor_id: str
    route_owner: str | None
    event_ids: tuple[str, ...]
    title: str
    summary: str
    origin: SemanticOrigin

    def __post_init__(self) -> None:
        for value, label in (
            (self.section_id, "section ID"),
            (self.corridor_id, "section corridor ID"),
            (self.title, "section title"),
            (self.summary, "section summary"),
        ):
            _trimmed(value, label, maximum=600)
        if self.route_owner is not None:
            _trimmed(self.route_owner, "section route owner")
        if not self.event_ids or len(self.event_ids) != len(set(self.event_ids)):
            raise ValueError("section event membership must be non-empty and unique")


@dataclass(frozen=True)
class EditorialStoryGroup:
    group_id: str
    source_section_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    title: str
    summary: str


@dataclass(frozen=True)
class EditorialTimeline:
    identity: str
    title: str
    overview: str
    groups: tuple[EditorialStoryGroup, ...]

    @property
    def sections(self) -> tuple[MeaningfulSection, ...]:
        return tuple(
            MeaningfulSection(
                section_id=group.group_id,
                corridor_id=EDITORIAL_TIMELINE_CORRIDOR_ID,
                route_owner=None,
                event_ids=group.event_ids,
                title=group.title,
                summary=group.summary,
                origin=SemanticOrigin.AI,
            )
            for group in self.groups
        )


def build_editorial_timeline_request(
    sections: Sequence[MeaningfulSection],
    authority_identity: str,
    *,
    required_group_count: int | None = None,
) -> bytes:
    """Build one loopback-only editorial packet over accepted section prose."""

    _trimmed(authority_identity, "editorial authority identity")
    if not sections:
        raise DerivedSemanticError("editorial timeline requires source sections")
    section_ids = tuple(section.section_id for section in sections)
    if len(section_ids) != len(set(section_ids)):
        raise DerivedSemanticError("editorial source section IDs must be unique")
    if required_group_count is not None and (
        type(required_group_count) is not int
        or not 1 <= required_group_count <= min(30, len(sections))
    ):
        raise DerivedSemanticError("editorial required group count is invalid")
    packet: dict[str, object] = {
        "task": (
            EDITORIAL_TIMELINE_TASK
            if required_group_count is None
            else EDITORIAL_TIMELINE_BATCH_TASK
        ),
        "call_kind": DerivedCallKind.SECTION_SYNTHESIS.value,
        "schema_version": SECTION_SYNTHESIS_SCHEMA_VERSION,
        "authority_identity": authority_identity,
        "ordered_child_ids": list(section_ids),
        "children": [
            {
                "id": section.section_id,
                "title": section.title,
                "summary": section.summary,
                "route_owner": section.route_owner,
            }
            for section in sections
        ],
    }
    if required_group_count is not None:
        packet["required_group_count"] = required_group_count
    return canonical_json(packet)


def partition_editorial_timeline_sections(
    sections: Sequence[MeaningfulSection],
) -> tuple[tuple[MeaningfulSection, ...], ...]:
    """Keep small inputs whole; balance larger inputs into current-reader-sized windows."""

    if not sections:
        raise DerivedSemanticError("editorial timeline requires source sections")
    frozen = tuple(sections)
    if len(frozen) <= EDITORIAL_MAX_SOURCE_SECTIONS_PER_GROUP:
        return (frozen,)
    batch_count = max(
        EDITORIAL_MIN_BATCH_COUNT,
        math.ceil(len(frozen) / EDITORIAL_MAX_SOURCE_SECTIONS_PER_GROUP),
    )
    if batch_count > EDITORIAL_MAX_BATCH_COUNT:
        raise DerivedSemanticError("editorial timeline exceeds the bounded batch count")
    batches = tuple(
        frozen[index * len(frozen) // batch_count : (index + 1) * len(frozen) // batch_count]
        for index in range(batch_count)
    )
    if any(
        len(batch) < EDITORIAL_GROUPS_PER_BATCH
        or len(batch) > EDITORIAL_MAX_SOURCE_SECTIONS_PER_GROUP
        for batch in batches
    ):
        raise DerivedSemanticError("editorial timeline cannot fit the bounded batch shape")
    return batches


def validate_editorial_timeline_response(
    sections: Sequence[MeaningfulSection],
    authority_identity: str,
    payload: bytes,
    *,
    required_group_count: int | None = None,
) -> EditorialTimeline:
    """Accept prose only after exact, once-only, chronological source coverage."""

    _trimmed(authority_identity, "editorial authority identity")
    if not sections:
        raise DerivedSemanticError("editorial timeline requires source sections")
    value = _decode(payload, "editorial timeline response")
    _exact(value, frozenset({"title", "summary", "sections"}), "editorial timeline response")
    source_ids = tuple(section.section_id for section in sections)
    if len(source_ids) != len(set(source_ids)):
        raise DerivedSemanticError("editorial source section IDs must be unique")
    source_events = tuple(event_id for section in sections for event_id in section.event_ids)
    if len(source_events) != len(set(source_events)):
        raise DerivedSemanticError("editorial source event coverage must be unique")
    proposals = _array(value["sections"], "editorial groups")
    minimum = min(12, len(sections))
    maximum = min(30, len(sections))
    if required_group_count is None and not minimum <= len(proposals) <= maximum:
        raise DerivedSemanticError("editorial timeline must contain the bounded group count")
    if required_group_count is not None and len(proposals) != required_group_count:
        raise DerivedSemanticError("editorial timeline must contain the required group count")
    indexes = {section_id: index for index, section_id in enumerate(source_ids)}
    cursor = 0
    groups: list[EditorialStoryGroup] = []
    for index, raw in enumerate(proposals):
        proposal = _object(raw, f"editorial groups[{index}]")
        _exact(
            proposal,
            frozenset({"first_event_id", "last_event_id", "title", "summary"}),
            f"editorial groups[{index}]",
        )
        first = _string(proposal["first_event_id"], "first source section ID")
        last = _string(proposal["last_event_id"], "last source section ID")
        if required_group_count == EDITORIAL_GROUPS_PER_BATCH:
            if index == 0:
                split_index = indexes.get(last)
                if split_index is None or split_index >= len(sections) - 1:
                    split_index = len(sections) // 2 - 1
                member_first = 0
                member_last = split_index
            else:
                if index != 1 or cursor >= len(sections):
                    raise DerivedSemanticError("editorial groups must be contiguous and ordered")
                member_first = cursor
                member_last = len(sections) - 1
        else:
            if first not in indexes or last not in indexes:
                raise DerivedSemanticError("editorial group references a foreign source section")
            first_index = indexes[first]
            last_index = indexes[last]
            if first_index != cursor or last_index < first_index:
                raise DerivedSemanticError("editorial groups must be contiguous and ordered")
            member_first = first_index
            member_last = last_index
        members = tuple(sections[member_first : member_last + 1])
        if len(members) > EDITORIAL_MAX_SOURCE_SECTIONS_PER_GROUP:
            raise DerivedSemanticError("editorial group exceeds the source-section limit")
        member_ids = tuple(member.section_id for member in members)
        event_ids = tuple(event_id for member in members for event_id in member.event_ids)
        group_id = "story-group:" + canonical_hash(
            {"authority": authority_identity, "source_section_ids": list(member_ids)}
        )[:32]
        groups.append(
            EditorialStoryGroup(
                group_id=group_id,
                source_section_ids=member_ids,
                event_ids=event_ids,
                title=_string(proposal["title"], "editorial group title", maximum=80),
                summary=_string(proposal["summary"], "editorial group summary", maximum=600),
            )
        )
        cursor = member_last + 1
    if cursor != len(sections):
        raise DerivedSemanticError("editorial groups must cover every source section exactly once")
    grouped_sources = tuple(item for group in groups for item in group.source_section_ids)
    grouped_events = tuple(item for group in groups for item in group.event_ids)
    if grouped_sources != source_ids or grouped_events != source_events:
        raise DerivedSemanticError("editorial grouping changed source coverage or chronology")
    title = _string(value["title"], "editorial timeline title", maximum=80)
    overview = _string(value["summary"], "editorial timeline overview", maximum=800)
    return _make_editorial_timeline(authority_identity, title, overview, tuple(groups))


def build_editorial_timeline_rollup_request(
    groups: Sequence[EditorialStoryGroup], authority_identity: str
) -> bytes:
    """Build one existing-schema rollup packet over validated editorial groups."""

    _trimmed(authority_identity, "editorial authority identity")
    if not groups:
        raise DerivedSemanticError("editorial rollup requires story groups")
    group_ids = tuple(group.group_id for group in groups)
    if len(group_ids) != len(set(group_ids)):
        raise DerivedSemanticError("editorial story group IDs must be unique")
    return canonical_json(
        {
            "task": EDITORIAL_TIMELINE_ROLLUP_TASK,
            "call_kind": DerivedCallKind.ROLLUP_SYNTHESIS.value,
            "schema_version": ROLLUP_SYNTHESIS_SCHEMA_VERSION,
            "authority_identity": authority_identity,
            "ordered_child_ids": list(group_ids),
            "children": [
                {
                    "id": group.group_id,
                    "title": group.title,
                    "summary": group.summary,
                }
                for group in groups
            ],
        }
    )


def combine_editorial_timeline_batches(
    sections: Sequence[MeaningfulSection],
    authority_identity: str,
    batches: Sequence[EditorialTimeline],
    rollup_payload: bytes,
) -> EditorialTimeline:
    """Combine validated slices only when global coverage and chronology remain exact."""

    _trimmed(authority_identity, "editorial authority identity")
    if not sections or not batches:
        raise DerivedSemanticError("editorial timeline batches require source sections")
    source_ids = tuple(section.section_id for section in sections)
    source_events = tuple(event_id for section in sections for event_id in section.event_ids)
    if len(source_ids) != len(set(source_ids)):
        raise DerivedSemanticError("editorial source section IDs must be unique")
    if len(source_events) != len(set(source_events)):
        raise DerivedSemanticError("editorial source event coverage must be unique")
    groups = tuple(group for batch in batches for group in batch.groups)
    if not 12 <= len(groups) <= 30:
        raise DerivedSemanticError("editorial timeline must contain the bounded group count")
    if len({group.group_id for group in groups}) != len(groups):
        raise DerivedSemanticError("editorial story group IDs must be unique")
    grouped_sources = tuple(item for group in groups for item in group.source_section_ids)
    grouped_events = tuple(item for group in groups for item in group.event_ids)
    if grouped_sources != source_ids or grouped_events != source_events:
        raise DerivedSemanticError("editorial grouping changed source coverage or chronology")
    value = _decode(rollup_payload, "editorial rollup response")
    _exact(value, frozenset({"title", "summary"}), "editorial rollup response")
    title = _string(value["title"], "editorial timeline title", maximum=80)
    overview = _string(value["summary"], "editorial timeline overview", maximum=800)
    return _make_editorial_timeline(authority_identity, title, overview, groups)


def _make_editorial_timeline(
    authority_identity: str,
    title: str,
    overview: str,
    groups: tuple[EditorialStoryGroup, ...],
) -> EditorialTimeline:
    identity = canonical_hash(
        {
            "authority": authority_identity,
            "title": title,
            "overview": overview,
            "groups": [
                {
                    "id": group.group_id,
                    "source_section_ids": list(group.source_section_ids),
                    "title": group.title,
                    "summary": group.summary,
                }
                for group in groups
            ],
        }
    )
    return EditorialTimeline(identity, title, overview, groups)


@dataclass(frozen=True)
class ChildSummary:
    child_id: str
    title: str
    summary: str
    route_owner: str | None

    @property
    def prose_hash(self) -> str:
        return canonical_hash({"title": self.title, "summary": self.summary})


@dataclass(frozen=True)
class DerivedSemanticJob:
    semantic_plan_identity: str
    candidate_generation_identity: str
    job_id: str
    call_kind: DerivedCallKind
    node_role: RollupNodeRole | None
    corridor_id: str | None
    route_owner: str | None
    child_ids: tuple[str, ...]
    child_prose_hashes: tuple[str, ...]
    ordinal: int
    request_identity: ExactRequestIdentity
    request: bytes

    def __post_init__(self) -> None:
        for value, label in (
            (self.semantic_plan_identity, "semantic plan identity"),
            (self.candidate_generation_identity, "candidate generation identity"),
            (self.job_id, "derived job ID"),
        ):
            _trimmed(value, label)
        if not self.child_ids or len(self.child_ids) != len(set(self.child_ids)):
            raise ValueError("derived job children must be non-empty and unique")
        if len(self.child_prose_hashes) != len(self.child_ids):
            raise ValueError("derived job child prose hashes must bind every child")
        if self.ordinal < 0:
            raise ValueError("derived job ordinal cannot be negative")
        if self.call_kind is DerivedCallKind.SECTION_SYNTHESIS:
            if self.node_role is not None or self.corridor_id is None:
                raise ValueError("section synthesis requires a corridor and no node role")
        elif self.node_role is None or self.corridor_id is not None:
            raise ValueError("rollup synthesis requires a node role and no corridor")
        self.request_identity.verify(self.request)


@dataclass(frozen=True)
class CorridorSectionResult:
    corridor_id: str
    route_owner: str | None
    sections: tuple[MeaningfulSection, ...]
    title: str
    summary: str
    origin: SemanticOrigin
    rejection_reason: str | None


@dataclass(frozen=True)
class RollupResult:
    rollup_id: str
    role: RollupNodeRole
    route_owner: str | None
    child_ids: tuple[str, ...]
    title: str
    summary: str
    origin: SemanticOrigin
    rejection_reason: str | None

    def as_child(self) -> ChildSummary:
        return ChildSummary(self.rollup_id, self.title, self.summary, self.route_owner)


@dataclass(frozen=True)
class DerivedSemanticAssembly:
    semantic_plan: DerivedSemanticPlan
    semantic_plan_identity: str
    candidate_generation_identity: str
    section_jobs: tuple[DerivedSemanticJob, ...]
    corridor_results: tuple[CorridorSectionResult, ...]
    rollup_jobs: tuple[DerivedSemanticJob, ...]
    rollups: tuple[RollupResult, ...]
    overview: RollupResult | None

    def __post_init__(self) -> None:
        if self.semantic_plan_identity != self.semantic_plan.semantic_plan_identity:
            raise ValueError("derived assembly semantic plan identity is not authoritative")

    @property
    def sections(self) -> tuple[MeaningfulSection, ...]:
        return tuple(section for result in self.corridor_results for section in result.sections)


def _event_child(event: SemanticEvent) -> ChildSummary:
    return ChildSummary(event.event_id, event.title, event.summary, event.route_owner)


def _job_identity(
    semantic_plan_identity: str,
    candidate_generation_identity: str,
    call_kind: DerivedCallKind,
    node_role: RollupNodeRole | None,
    corridor_id: str | None,
    route_owner: str | None,
    children: Sequence[ChildSummary],
) -> str:
    return canonical_hash(
        {
            "semantic_plan_identity": semantic_plan_identity,
            "candidate_generation_identity": candidate_generation_identity,
            "call_kind": call_kind.value,
            "node_role": None if node_role is None else node_role.value,
            "corridor_id": corridor_id,
            "route_owner": route_owner,
            "child_ids": [child.child_id for child in children],
            "child_prose_hashes": [child.prose_hash for child in children],
        }
    )


def _materialize_job(
    plan: DerivedSemanticPlan,
    candidate_generation_identity: str,
    *,
    call_kind: DerivedCallKind,
    node_role: RollupNodeRole | None,
    corridor_id: str | None,
    route_owner: str | None,
    children: Sequence[ChildSummary],
    ordinal: int,
) -> DerivedSemanticJob:
    job_digest = _job_identity(
        plan.semantic_plan_identity,
        candidate_generation_identity,
        call_kind,
        node_role,
        corridor_id,
        route_owner,
        children,
    )
    job_id = f"derived-job:{job_digest[:32]}"
    prompt_version = (
        SECTION_SYNTHESIS_PROMPT_VERSION
        if call_kind is DerivedCallKind.SECTION_SYNTHESIS
        else ROLLUP_SYNTHESIS_PROMPT_VERSION
    )
    schema_version = (
        SECTION_SYNTHESIS_SCHEMA_VERSION
        if call_kind is DerivedCallKind.SECTION_SYNTHESIS
        else ROLLUP_SYNTHESIS_SCHEMA_VERSION
    )
    adapter_version = (
        SECTION_SYNTHESIS_ADAPTER_VERSION
        if call_kind is DerivedCallKind.SECTION_SYNTHESIS
        else ROLLUP_SYNTHESIS_ADAPTER_VERSION
    )
    request = canonical_json(
        {
            "task": (
                SECTION_SYNTHESIS_TASK
                if call_kind is DerivedCallKind.SECTION_SYNTHESIS
                else ROLLUP_SYNTHESIS_TASK
            ),
            "semantic_plan_identity": plan.semantic_plan_identity,
            "story_chunk_plan_identity": plan.story_chunk_plan_identity,
            "authority_identity": plan.authority_identity,
            "candidate_generation_identity": candidate_generation_identity,
            "job_id": job_id,
            "call_kind": call_kind.value,
            "node_role": None if node_role is None else node_role.value,
            "corridor_id": corridor_id,
            "route_owner": route_owner,
            "child_ids": [child.child_id for child in children],
            "children": [
                {
                    "id": child.child_id,
                    "title": child.title,
                    "summary": child.summary,
                    "prose_hash": child.prose_hash,
                }
                for child in children
            ],
            "prompt_version": prompt_version,
            "schema_version": schema_version,
            "adapter_version": adapter_version,
            "provider": DERIVED_PROVIDER,
            "model": DERIVED_MODEL,
            "reasoning": DERIVED_REASONING,
            "fast_mode": DERIVED_FAST_MODE,
            "mode": "cloud",
        }
    )
    return DerivedSemanticJob(
        semantic_plan_identity=plan.semantic_plan_identity,
        candidate_generation_identity=candidate_generation_identity,
        job_id=job_id,
        call_kind=call_kind,
        node_role=node_role,
        corridor_id=corridor_id,
        route_owner=route_owner,
        child_ids=tuple(child.child_id for child in children),
        child_prose_hashes=tuple(child.prose_hash for child in children),
        ordinal=ordinal,
        request_identity=ExactRequestIdentity(
            value=f"derived-request:{job_digest}",
            sha256=hashlib.sha256(request).hexdigest(),
            byte_count=len(request),
        ),
        request=request,
    )


def _duplicate_rejecting_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DerivedSemanticError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def _decode(payload: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(payload, object_pairs_hook=_duplicate_rejecting_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DerivedSemanticError(f"{label} must be UTF-8 JSON") from exc
    if type(value) is not dict:
        raise DerivedSemanticError(f"{label} must be one JSON object")
    return cast(dict[str, object], value)


def _exact(value: dict[str, object], fields: frozenset[str], label: str) -> None:
    if set(value) != fields:
        raise DerivedSemanticError(f"{label} has missing or unexpected fields")


def _array(value: object, label: str) -> list[object]:
    if type(value) is not list:
        raise DerivedSemanticError(f"{label} must be an array")
    return cast(list[object], value)


def _object(value: object, label: str) -> dict[str, object]:
    if type(value) is not dict:
        raise DerivedSemanticError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _string(value: object, label: str, *, maximum: int = 600) -> str:
    if type(value) is not str:
        raise DerivedSemanticError(f"{label} must be a string")
    return _trimmed(value, label, maximum=maximum)


def _string_array(value: object, label: str) -> tuple[str, ...]:
    return tuple(_string(item, label) for item in _array(value, label))


def meaningful_section_identity(
    semantic_plan_identity: str,
    corridor_id: str,
    event_ids: tuple[str, ...],
) -> str:
    """Return the stable Python-owned identity for one contiguous section."""

    digest = canonical_hash(
        {"plan": semantic_plan_identity, "corridor": corridor_id, "events": list(event_ids)}
    )
    return f"section:{digest[:32]}"


def _section_id(
    semantic_plan_identity: str,
    corridor_id: str,
    event_ids: tuple[str, ...],
) -> str:
    return meaningful_section_identity(semantic_plan_identity, corridor_id, event_ids)


def _corridor_events(
    semantic_plan: DerivedSemanticPlan,
    assembly: SemanticAssembly,
) -> dict[str, tuple[SemanticEvent, ...]]:
    if assembly.story_chunk_plan_identity != semantic_plan.story_chunk_plan_identity:
        raise DerivedSemanticError("semantic assembly differs from the frozen semantic plan")
    if tuple(chunk.chunk_id for chunk in assembly.chunks) != tuple(
        corridor.corridor_id for corridor in semantic_plan.corridors
    ):
        raise DerivedSemanticError("semantic assembly changed frozen corridor order or membership")
    result: dict[str, list[SemanticEvent]] = {
        corridor.corridor_id: [] for corridor in semantic_plan.corridors
    }
    for chunk in assembly.chunks:
        if chunk.chunk_id not in result:
            raise DerivedSemanticError("semantic assembly contains a foreign corridor")
        result[chunk.chunk_id].extend(chunk.events)
    frozen = {corridor.corridor_id: corridor for corridor in semantic_plan.corridors}
    for corridor_id, events in result.items():
        descriptor = frozen[corridor_id]
        if not events or len(events) > descriptor.event_slot_upper_bound:
            raise DerivedSemanticError("corridor event count exceeds its frozen upper bound")
        if any(
            (event.route_owner if descriptor.route_owner is not None else None)
            != descriptor.route_owner
            for event in events
        ):
            raise DerivedSemanticError("corridor events have wrong route ownership")
    return {key: tuple(events) for key, events in result.items()}


def _section_job(
    plan: DerivedSemanticPlan,
    candidate_generation_identity: str,
    corridor: DerivedCorridorDescriptor,
    events: tuple[SemanticEvent, ...],
) -> DerivedSemanticJob:
    return _materialize_job(
        plan,
        candidate_generation_identity,
        call_kind=DerivedCallKind.SECTION_SYNTHESIS,
        node_role=None,
        corridor_id=corridor.corridor_id,
        route_owner=corridor.route_owner,
        children=tuple(_event_child(event) for event in events),
        ordinal=corridor.ordinal,
    )


def _structural_sections(
    plan: DerivedSemanticPlan,
    corridor: DerivedCorridorDescriptor,
    events: tuple[SemanticEvent, ...],
    reason: str,
) -> CorridorSectionResult:
    sections: list[MeaningfulSection] = []
    for index in range(0, len(events), 30):
        group = events[index : index + 30]
        event_ids = tuple(event.event_id for event in group)
        title = (
            group[0].title
            if len(group) == 1
            else f"{group[0].title} to {group[-1].title}"
        )
        if len(title) > 80:
            title = title[:77].rstrip() + "..."
        summary = " ".join(event.summary for event in group)
        if len(summary) > 600:
            summary = summary[:597].rstrip() + "..."
        sections.append(
            MeaningfulSection(
                section_id=_section_id(
                    plan.semantic_plan_identity, corridor.corridor_id, event_ids
                ),
                corridor_id=corridor.corridor_id,
                route_owner=corridor.route_owner,
                event_ids=event_ids,
                title=title,
                summary=summary,
                origin=SemanticOrigin.STRUCTURAL,
            )
        )
    return CorridorSectionResult(
        corridor_id=corridor.corridor_id,
        route_owner=corridor.route_owner,
        sections=tuple(sections),
        title=f"Story corridor {corridor.ordinal + 1}",
        summary="Deterministic sections preserve complete corridor coverage.",
        origin=SemanticOrigin.STRUCTURAL,
        rejection_reason=reason,
    )


def _validate_section_response(
    plan: DerivedSemanticPlan,
    job: DerivedSemanticJob,
    events: tuple[SemanticEvent, ...],
    payload: bytes,
) -> CorridorSectionResult:
    value = _decode(payload, "section synthesis response")
    _exact(
        value,
        frozenset(
            {
                "schema",
                "semantic_plan_identity",
                "candidate_generation_identity",
                "job_id",
                "corridor_id",
                "ordered_child_ids",
                "title",
                "summary",
                "sections",
            }
        ),
        "section synthesis response",
    )
    if (
        value["schema"] != SECTION_SYNTHESIS_SCHEMA_VERSION
        or value["semantic_plan_identity"] != plan.semantic_plan_identity
        or value["candidate_generation_identity"] != job.candidate_generation_identity
        or value["job_id"] != job.job_id
        or value["corridor_id"] != job.corridor_id
        or _string_array(value["ordered_child_ids"], "section child IDs") != job.child_ids
    ):
        raise DerivedSemanticError("section response differs from its exact derived job")
    event_ids = tuple(event.event_id for event in events)
    indexes = {event_id: index for index, event_id in enumerate(event_ids)}
    sections: list[MeaningfulSection] = []
    flattened: list[str] = []
    for index, raw in enumerate(_array(value["sections"], "proposed sections")):
        proposal = _object(raw, f"proposed sections[{index}]")
        _exact(
            proposal,
            frozenset({"first_event_id", "last_event_id", "title", "summary"}),
            f"proposed sections[{index}]",
        )
        first = _string(proposal["first_event_id"], "first event ID")
        last = _string(proposal["last_event_id"], "last event ID")
        if first not in indexes or last not in indexes or indexes[first] > indexes[last]:
            raise DerivedSemanticError("section range references foreign or reversed events")
        members = event_ids[indexes[first] : indexes[last] + 1]
        flattened.extend(members)
        sections.append(
            MeaningfulSection(
                section_id=_section_id(
                    plan.semantic_plan_identity, cast(str, job.corridor_id), members
                ),
                corridor_id=cast(str, job.corridor_id),
                route_owner=job.route_owner,
                event_ids=members,
                title=_string(proposal["title"], "section title", maximum=80),
                summary=_string(proposal["summary"], "section summary", maximum=600),
                origin=SemanticOrigin.AI,
            )
        )
    if not sections or tuple(flattened) != event_ids:
        raise DerivedSemanticError(
            "sections must cover exact existing events once, contiguously, and in order"
        )
    return CorridorSectionResult(
        corridor_id=cast(str, job.corridor_id),
        route_owner=job.route_owner,
        sections=tuple(sections),
        title=_string(value["title"], "corridor title", maximum=80),
        summary=_string(value["summary"], "corridor summary", maximum=600),
        origin=SemanticOrigin.AI,
        rejection_reason=None,
    )


def _section_children(result: CorridorSectionResult) -> tuple[ChildSummary, ...]:
    return tuple(
        ChildSummary(section.section_id, section.title, section.summary, section.route_owner)
        for section in result.sections
    )


def derived_rollup_identity(
    semantic_plan_identity: str,
    candidate_generation_identity: str,
    role: str,
    route_owner: str | None,
    child_ids: Sequence[str],
) -> str:
    """Return the stable Python-owned identity for one fixed-membership rollup."""

    digest = canonical_hash(
        {
            "semantic_plan_identity": semantic_plan_identity,
            "candidate_generation_identity": candidate_generation_identity,
            "role": role,
            "route_owner": route_owner,
            "child_ids": list(child_ids),
        }
    )
    return f"rollup:{digest[:32]}"


def _rollup_id(
    plan: DerivedSemanticPlan,
    candidate_generation_identity: str,
    role: RollupNodeRole,
    route_owner: str | None,
    child_ids: Sequence[str],
) -> str:
    return derived_rollup_identity(
        plan.semantic_plan_identity,
        candidate_generation_identity,
        role.value,
        route_owner,
        child_ids,
    )


def _validate_rollup_response(
    plan: DerivedSemanticPlan,
    job: DerivedSemanticJob,
    payload: bytes,
) -> RollupResult:
    value = _decode(payload, "rollup synthesis response")
    _exact(
        value,
        frozenset(
            {
                "schema",
                "semantic_plan_identity",
                "candidate_generation_identity",
                "job_id",
                "node_role",
                "route_owner",
                "ordered_child_ids",
                "title",
                "summary",
            }
        ),
        "rollup synthesis response",
    )
    if (
        value["schema"] != ROLLUP_SYNTHESIS_SCHEMA_VERSION
        or value["semantic_plan_identity"] != plan.semantic_plan_identity
        or value["candidate_generation_identity"] != job.candidate_generation_identity
        or value["job_id"] != job.job_id
        or value["node_role"] != cast(RollupNodeRole, job.node_role).value
        or value["route_owner"] != job.route_owner
        or _string_array(value["ordered_child_ids"], "rollup child IDs") != job.child_ids
    ):
        raise DerivedSemanticError("rollup response differs from exact fixed membership")
    rollup_id = _rollup_id(
        plan,
        job.candidate_generation_identity,
        cast(RollupNodeRole, job.node_role),
        job.route_owner,
        job.child_ids,
    )
    return RollupResult(
        rollup_id=rollup_id,
        role=cast(RollupNodeRole, job.node_role),
        route_owner=job.route_owner,
        child_ids=job.child_ids,
        title=_string(value["title"], "rollup title", maximum=80),
        summary=_string(value["summary"], "rollup summary", maximum=800),
        origin=SemanticOrigin.AI,
        rejection_reason=None,
    )


def _fallback_rollup(
    plan: DerivedSemanticPlan,
    job: DerivedSemanticJob,
    children: Sequence[ChildSummary],
    reason: str,
) -> RollupResult:
    role = cast(RollupNodeRole, job.node_role)
    title = "Whole story overview" if role is RollupNodeRole.FINAL_OVERVIEW else "Story summary"
    summaries = " ".join(child.summary for child in children)
    if len(summaries) > 800:
        summaries = summaries[:797].rstrip() + "..."
    return RollupResult(
        rollup_id=_rollup_id(
            plan, job.candidate_generation_identity, role, job.route_owner, job.child_ids
        ),
        role=role,
        route_owner=job.route_owner,
        child_ids=job.child_ids,
        title=title,
        summary=summaries or "Deterministic story coverage is complete.",
        origin=SemanticOrigin.STRUCTURAL,
        rejection_reason=reason,
    )


def _resolve_rollup_job(
    plan: DerivedSemanticPlan,
    job: DerivedSemanticJob,
    children: Sequence[ChildSummary],
    payloads: Mapping[str, bytes],
) -> RollupResult:
    payload = payloads.get(job.job_id)
    if payload is None:
        return _fallback_rollup(plan, job, children, "provider_result_unavailable")
    try:
        return _validate_rollup_response(plan, job, payload)
    except (DerivedSemanticError, SemanticValidationError, ValueError):
        return _fallback_rollup(plan, job, children, "invalid_rollup_result")


def _reduce_children(
    plan: DerivedSemanticPlan,
    candidate_generation_identity: str,
    children: tuple[ChildSummary, ...],
    *,
    role: RollupNodeRole,
    route_owner: str | None,
    ordinal: int,
    payloads: Mapping[str, bytes],
) -> tuple[tuple[ChildSummary, ...], tuple[DerivedSemanticJob, ...], tuple[RollupResult, ...], int]:
    current = children
    jobs: list[DerivedSemanticJob] = []
    results: list[RollupResult] = []
    while len(current) > plan.fan_in:
        next_level: list[ChildSummary] = []
        for offset in range(0, len(current), plan.fan_in):
            group = current[offset : offset + plan.fan_in]
            job = _materialize_job(
                plan,
                candidate_generation_identity,
                call_kind=DerivedCallKind.ROLLUP_SYNTHESIS,
                node_role=role,
                corridor_id=None,
                route_owner=route_owner,
                children=group,
                ordinal=ordinal,
            )
            ordinal += 1
            result = _resolve_rollup_job(plan, job, group, payloads)
            jobs.append(job)
            results.append(result)
            next_level.append(result.as_child())
        current = tuple(next_level)
    return current, tuple(jobs), tuple(results), ordinal


def assemble_derived_semantics(
    plan: DerivedSemanticPlan,
    assembly: SemanticAssembly,
    candidate_generation_identity: str,
    *,
    section_payloads: Mapping[str, bytes] | None = None,
    rollup_payloads: Mapping[str, bytes] | None = None,
) -> DerivedSemanticAssembly:
    """Validate dependency outputs and deterministically assemble sections and whole rollups."""

    _trimmed(candidate_generation_identity, "candidate generation identity")
    section_payloads = {} if section_payloads is None else section_payloads
    rollup_payloads = {} if rollup_payloads is None else rollup_payloads
    corridor_events = _corridor_events(plan, assembly)
    section_jobs: list[DerivedSemanticJob] = []
    corridor_results: list[CorridorSectionResult] = []
    for corridor in plan.corridors:
        events = corridor_events[corridor.corridor_id]
        job = _section_job(plan, candidate_generation_identity, corridor, events)
        section_jobs.append(job)
        payload = section_payloads.get(job.job_id)
        if payload is None:
            result = _structural_sections(
                plan, corridor, events, "provider_result_unavailable"
            )
        else:
            try:
                result = _validate_section_response(plan, job, events, payload)
            except (DerivedSemanticError, SemanticValidationError, ValueError):
                result = _structural_sections(plan, corridor, events, "invalid_section_result")
        corridor_results.append(result)
    expected_section_jobs = {job.job_id for job in section_jobs}
    if any(job_id not in expected_section_jobs for job_id in section_payloads):
        raise DerivedSemanticError("foreign section synthesis result")

    by_corridor = {result.corridor_id: result for result in corridor_results}
    corridor_by_id = {corridor.corridor_id: corridor for corridor in plan.corridors}
    persistent_corridors = {
        corridor_id for route in plan.persistent_routes for corridor_id in route.corridor_ids
    }
    jobs: list[DerivedSemanticJob] = []
    rollups: list[RollupResult] = []
    route_roots: dict[str, ChildSummary] = {}
    ordinal = 0
    for route in plan.persistent_routes:
        route_children = tuple(
            child
            for corridor_id in route.corridor_ids
            for child in _section_children(by_corridor[corridor_id])
        )
        reduced, reduction_jobs, reduction_results, ordinal = _reduce_children(
            plan,
            candidate_generation_identity,
            route_children,
            role=RollupNodeRole.ROUTE_REDUCTION,
            route_owner=route.route_owner,
            ordinal=ordinal,
            payloads=rollup_payloads,
        )
        jobs.extend(reduction_jobs)
        rollups.extend(reduction_results)
        summary_job = _materialize_job(
            plan,
            candidate_generation_identity,
            call_kind=DerivedCallKind.ROLLUP_SYNTHESIS,
            node_role=RollupNodeRole.ROUTE_SUMMARY,
            corridor_id=None,
            route_owner=route.route_owner,
            children=reduced,
            ordinal=ordinal,
        )
        ordinal += 1
        summary = _resolve_rollup_job(plan, summary_job, reduced, rollup_payloads)
        jobs.append(summary_job)
        rollups.append(summary)
        route_roots[route.route_owner] = summary.as_child()

    ordered_whole_children: list[ChildSummary] = []
    emitted_routes: set[str] = set()
    for corridor in plan.corridors:
        if corridor.corridor_id not in persistent_corridors:
            ordered_whole_children.extend(
                _section_children(by_corridor[corridor.corridor_id])
            )
            continue
        route_owner = cast(str, corridor.route_owner)
        if route_owner not in emitted_routes:
            ordered_whole_children.append(route_roots[route_owner])
            emitted_routes.add(route_owner)
    whole_children = tuple(ordered_whole_children)
    overview: RollupResult | None = None
    if whole_children:
        reduced, reduction_jobs, reduction_results, ordinal = _reduce_children(
            plan,
            candidate_generation_identity,
            whole_children,
            role=RollupNodeRole.WHOLE_GAME_REDUCTION,
            route_owner=None,
            ordinal=ordinal,
            payloads=rollup_payloads,
        )
        jobs.extend(reduction_jobs)
        rollups.extend(reduction_results)
        overview_job = _materialize_job(
            plan,
            candidate_generation_identity,
            call_kind=DerivedCallKind.ROLLUP_SYNTHESIS,
            node_role=RollupNodeRole.FINAL_OVERVIEW,
            corridor_id=None,
            route_owner=None,
            children=reduced,
            ordinal=ordinal,
        )
        overview = _resolve_rollup_job(plan, overview_job, reduced, rollup_payloads)
        jobs.append(overview_job)
        rollups.append(overview)
    expected_rollup_jobs = {job.job_id for job in jobs}
    if any(job_id not in expected_rollup_jobs for job_id in rollup_payloads):
        raise DerivedSemanticError("foreign rollup synthesis result")
    actual_role_counts = {
        role: sum(job.node_role is role for job in jobs) for role in RollupNodeRole
    }
    if (
        actual_role_counts[RollupNodeRole.ROUTE_REDUCTION]
        > plan.ceilings.route_reduction_calls
        or actual_role_counts[RollupNodeRole.ROUTE_SUMMARY]
        > plan.ceilings.route_summary_calls
        or actual_role_counts[RollupNodeRole.WHOLE_GAME_REDUCTION]
        > plan.ceilings.whole_game_reduction_calls
        or actual_role_counts[RollupNodeRole.FINAL_OVERVIEW]
        > plan.ceilings.final_overview_calls
        or len(jobs) > plan.ceilings.rollup_synthesis_calls
    ):
        raise DerivedSemanticError("derived rollup jobs exceeded frozen Prepare ceilings")
    # Exact route ownership must remain aligned with the prepared corridors.
    if any(
        section.route_owner != corridor_by_id[section.corridor_id].route_owner
        for result in corridor_results
        for section in result.sections
    ):
        raise DerivedSemanticError("published section changed frozen route ownership")
    return DerivedSemanticAssembly(
        semantic_plan=plan,
        semantic_plan_identity=plan.semantic_plan_identity,
        candidate_generation_identity=candidate_generation_identity,
        section_jobs=tuple(section_jobs),
        corridor_results=tuple(corridor_results),
        rollup_jobs=tuple(jobs),
        rollups=tuple(rollups),
        overview=overview,
    )
