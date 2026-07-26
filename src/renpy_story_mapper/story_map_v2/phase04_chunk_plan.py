"""Frozen, provider-free Story Map V2 Phase 04 chunk planning.

This module intentionally accepts an already ordered planning projection.  It does not derive or
change StoryPlan, StoryScopeDescriptor, or StoryPlacement authority; the Track A1 integration
adapter owns that conversion.  Planning here only groups exact placement records, freezes request
identity, and proves complete serialized request sizing and exactly-once coverage.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from renpy_story_mapper.story_map_v2.contracts import canonical_hash, canonical_json

STORY_CHUNK_PLAN_SCHEMA = "story-map-v2-phase04-chunk-plan-v1"
PHASE04_MAPPER_REQUEST_SCHEMA = "story-map-v2-phase04-mapper-request-v1"
PHASE04_MAPPER_PROMPT_VERSION = "story-map-v2-phase04-mapper-prompt-v1"
COMPLETE_REQUEST_TOKEN_COUNTER = "raw-authority-plus-nonstory-utf8-v1"


class FrozenPlanMismatch(ValueError):
    """Current material cannot reproduce one exact frozen request."""


class ChunkProfileKind(StrEnum):
    NORMAL = "normal"
    BRANCH_HEAVY = "branch_heavy"


def _trimmed(value: str, label: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{label} must be a non-empty trimmed string")


def _canonical_object(value: str, label: str) -> dict[str, object]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be canonical JSON") from exc
    if type(decoded) is not dict or canonical_json(decoded).decode("utf-8") != value:
        raise ValueError(f"{label} must be one canonical JSON object")
    return cast(dict[str, object], decoded)


@dataclass(frozen=True, order=True)
class ChoiceArmBoundary:
    """Opaque A1-owned choice/arm placement carried across an exact scene boundary."""

    choice_key: str
    arm_order: int
    boundary_kind: str
    depth: int

    def __post_init__(self) -> None:
        _trimmed(self.choice_key, "choice key")
        if self.arm_order < 1:
            raise ValueError("choice arm order must be positive")
        if self.boundary_kind not in {"local", "persistent", "nested"}:
            raise ValueError("choice boundary kind must be local, persistent, or nested")
        if self.depth < 0:
            raise ValueError("choice boundary depth cannot be negative")


@dataclass(frozen=True)
class ChunkPlanningPlacement:
    """Temporary typed seam for one already ordered, scene-atomic StoryPlacement."""

    placement_id: str
    scope_id: str
    scene_id: str
    relative_path: str
    start_line: int
    end_line: int
    raw_text: str
    raw_tokens: int
    choice_arms: tuple[ChoiceArmBoundary, ...] = ()
    structural_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value, label in (
            (self.placement_id, "placement ID"),
            (self.scope_id, "scope ID"),
            (self.scene_id, "scene ID"),
            (self.relative_path, "relative path"),
        ):
            _trimmed(value, label)
        if self.start_line < 1 or self.end_line < self.start_line:
            raise ValueError("placement source range is invalid")
        if not self.raw_text or self.raw_tokens < 1:
            raise ValueError("placement story text and positive raw token estimate are required")
        if len(self.choice_arms) != len(set(self.choice_arms)):
            raise ValueError("placement choice-arm boundaries must be unique")
        if len(self.structural_flags) != len(set(self.structural_flags)):
            raise ValueError("placement structural flags must be unique")
        for flag in self.structural_flags:
            _trimmed(flag, "structural flag")


@dataclass(frozen=True)
class ChunkPlanningScope:
    """Already frozen scope ordering supplied by A1; no chronology is derived here."""

    scope_id: str
    ordinal: int
    parent_scope_id: str | None
    persistent_lane: bool
    branch_heavy: bool
    placements: tuple[ChunkPlanningPlacement, ...]

    def __post_init__(self) -> None:
        _trimmed(self.scope_id, "scope ID")
        if self.parent_scope_id is not None:
            _trimmed(self.parent_scope_id, "parent scope ID")
        if self.ordinal < 1 or not self.placements:
            raise ValueError("scope ordinal and placements are required")
        if any(item.scope_id != self.scope_id for item in self.placements):
            raise ValueError("scope placements must retain their exact supplied scope")
        placement_ids = tuple(item.placement_id for item in self.placements)
        if len(placement_ids) != len(set(placement_ids)):
            raise ValueError("scope placement IDs must be unique")


@dataclass(frozen=True)
class ChunkPlanningChoice:
    """Opaque Python-owned parent mechanics referenced by placement boundaries."""

    choice_key: str
    canonical_mechanics: str
    arm_orders: tuple[int, ...]

    def __post_init__(self) -> None:
        _trimmed(self.choice_key, "choice key")
        _canonical_object(self.canonical_mechanics, "choice mechanics")
        if not self.arm_orders or any(order < 1 for order in self.arm_orders):
            raise ValueError("choice mechanics require positive arm orders")
        if len(self.arm_orders) != len(set(self.arm_orders)):
            raise ValueError("choice arm orders must be unique")


@dataclass(frozen=True)
class ChunkPlanningProjection:
    """A2's isolated input seam over exact A1 StoryPlan placement material."""

    story_plan_identity: str
    source_identity: str
    scopes: tuple[ChunkPlanningScope, ...]
    choices: tuple[ChunkPlanningChoice, ...] = ()

    def __post_init__(self) -> None:
        _trimmed(self.story_plan_identity, "story plan identity")
        _trimmed(self.source_identity, "source identity")
        scope_ids = tuple(scope.scope_id for scope in self.scopes)
        if len(scope_ids) != len(set(scope_ids)):
            raise ValueError("planning scope IDs must be unique")
        if tuple(scope.ordinal for scope in self.scopes) != tuple(range(1, len(self.scopes) + 1)):
            raise ValueError("planning scopes must retain contiguous supplied ordinals")
        all_placement_ids = tuple(
            placement.placement_id for scope in self.scopes for placement in scope.placements
        )
        if len(all_placement_ids) != len(set(all_placement_ids)):
            raise ValueError("planning placement IDs must be globally unique")
        choices_by_key = {choice.choice_key: choice for choice in self.choices}
        if len(choices_by_key) != len(self.choices):
            raise ValueError("planning choice keys must be unique")
        for scope in self.scopes:
            for placement in scope.placements:
                for arm in placement.choice_arms:
                    choice = choices_by_key.get(arm.choice_key)
                    if choice is None:
                        raise ValueError(
                            "placement references unknown Python-owned choice mechanics"
                        )
                    if arm.arm_order not in choice.arm_orders:
                        raise ValueError("placement references an unknown Python-owned choice arm")


@dataclass(frozen=True)
class ChunkSizingPolicy:
    normal_target_tokens: int = 8_000
    branch_target_tokens: int = 5_000
    maximum_request_tokens: int = 10_700

    def __post_init__(self) -> None:
        if not (
            0 < self.branch_target_tokens
            <= self.normal_target_tokens
            <= self.maximum_request_tokens
        ):
            raise ValueError("Phase 04 chunk sizing policy is invalid")


@dataclass(frozen=True)
class FrozenChoiceParent:
    choice_key: str
    canonical_mechanics: str
    mechanics_hash: str

    def __post_init__(self) -> None:
        _trimmed(self.choice_key, "choice key")
        _canonical_object(self.canonical_mechanics, "frozen choice mechanics")
        if self.mechanics_hash != canonical_hash(json.loads(self.canonical_mechanics)):
            raise ValueError("frozen choice mechanics hash is invalid")


@dataclass(frozen=True)
class FrozenChoiceSegment:
    choice_key: str
    arm_orders: tuple[int, ...]
    boundary_kinds: tuple[str, ...]
    maximum_depth: int
    segment_ordinal: int
    segment_count: int

    def __post_init__(self) -> None:
        _trimmed(self.choice_key, "choice key")
        if not self.arm_orders or len(self.arm_orders) != len(set(self.arm_orders)):
            raise ValueError("frozen choice segment arm orders must be non-empty and unique")
        if any(order < 1 for order in self.arm_orders):
            raise ValueError("frozen choice segment arm orders must be positive")
        if not self.boundary_kinds or any(
            kind not in {"local", "persistent", "nested"} for kind in self.boundary_kinds
        ):
            raise ValueError("frozen choice segment boundary kinds are invalid")
        if self.maximum_depth < 0:
            raise ValueError("frozen choice segment depth cannot be negative")
        if not (1 <= self.segment_ordinal <= self.segment_count):
            raise ValueError("frozen choice segment ordinal/count are invalid")


@dataclass(frozen=True)
class StoryChunkDescriptor:
    chunk_id: str
    scope_id: str
    scope_ordinal: int
    chunk_ordinal: int
    profile: ChunkProfileKind
    placement_ids: tuple[str, ...]
    raw_tokens: int
    rendered_input_hash: str
    mechanics_hash: str
    request_hash: str | None
    serialized_request_bytes: int
    complete_request_tokens: int | None
    structural_fallback_only: bool
    structural_fallback_reason: str | None
    oversized_candidate_tokens: int | None
    structural_flags: tuple[str, ...]
    choice_segments: tuple[FrozenChoiceSegment, ...]

    def __post_init__(self) -> None:
        _trimmed(self.chunk_id, "chunk ID")
        _trimmed(self.scope_id, "scope ID")
        if self.scope_ordinal < 1 or self.chunk_ordinal < 1:
            raise ValueError("chunk scope/chunk ordinals must be positive")
        if not self.placement_ids or len(self.placement_ids) != len(set(self.placement_ids)):
            raise ValueError("chunk placement coverage must be non-empty and unique")
        if self.raw_tokens < 1:
            raise ValueError("chunk raw token count must be positive")
        _trimmed(self.rendered_input_hash, "rendered input hash")
        _trimmed(self.mechanics_hash, "mechanics hash")
        if self.request_hash is not None:
            _trimmed(self.request_hash, "request hash")
        for flag in self.structural_flags:
            _trimmed(flag, "structural flag")
        if len(self.structural_flags) != len(set(self.structural_flags)):
            raise ValueError("chunk structural flags must be unique")
        if self.structural_fallback_only:
            if (
                self.request_hash is not None
                or self.serialized_request_bytes != 0
                or self.complete_request_tokens is not None
                or self.structural_fallback_reason is None
                or self.oversized_candidate_tokens is None
            ):
                raise ValueError("structural-only chunk cannot freeze a provider request")
            _trimmed(self.structural_fallback_reason, "structural fallback reason")
        elif (
            self.request_hash is None
            or self.serialized_request_bytes < 1
            or self.complete_request_tokens is None
            or self.complete_request_tokens < 1
            or self.structural_fallback_reason is not None
            or self.oversized_candidate_tokens is not None
        ):
            raise ValueError("provider-eligible chunk must freeze one complete request")

    @property
    def identity(self) -> str:
        return canonical_hash(_chunk_payload(self))


@dataclass(frozen=True)
class StoryChunkPlan:
    story_plan_identity: str
    source_identity: str
    scope_ids: tuple[str, ...]
    covered_placement_ids: tuple[str, ...]
    choice_parents: tuple[FrozenChoiceParent, ...]
    chunks: tuple[StoryChunkDescriptor, ...]
    normal_target_tokens: int = 8_000
    branch_target_tokens: int = 5_000
    maximum_request_tokens: int = 10_700
    schema: str = STORY_CHUNK_PLAN_SCHEMA
    token_counter: str = COMPLETE_REQUEST_TOKEN_COUNTER
    prompt_version: str = PHASE04_MAPPER_PROMPT_VERSION

    def __post_init__(self) -> None:
        for value, label in (
            (self.story_plan_identity, "story plan identity"),
            (self.source_identity, "source identity"),
            (self.schema, "chunk plan schema"),
            (self.token_counter, "token counter"),
            (self.prompt_version, "prompt version"),
        ):
            _trimmed(value, label)
        if self.schema != STORY_CHUNK_PLAN_SCHEMA:
            raise ValueError("unsupported StoryChunkPlan schema")
        if self.token_counter != COMPLETE_REQUEST_TOKEN_COUNTER:
            raise ValueError("unsupported complete-request token counter")
        ChunkSizingPolicy(
            normal_target_tokens=self.normal_target_tokens,
            branch_target_tokens=self.branch_target_tokens,
            maximum_request_tokens=self.maximum_request_tokens,
        )
        if len(self.scope_ids) != len(set(self.scope_ids)):
            raise ValueError("StoryChunkPlan scope IDs must be unique")
        if len(self.covered_placement_ids) != len(set(self.covered_placement_ids)):
            raise ValueError("StoryChunkPlan coverage IDs must be unique")
        parent_keys = tuple(parent.choice_key for parent in self.choice_parents)
        if len(parent_keys) != len(set(parent_keys)):
            raise ValueError("StoryChunkPlan choice parents must be unique")
        parent_key_set = set(parent_keys)
        chunk_ids = tuple(chunk.chunk_id for chunk in self.chunks)
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("StoryChunkPlan chunk IDs must be unique")

        flattened = tuple(item for chunk in self.chunks for item in chunk.placement_ids)
        if flattened != self.covered_placement_ids:
            raise ValueError("StoryChunkPlan must cover every supplied placement exactly once")
        if any(chunk.scope_id not in set(self.scope_ids) for chunk in self.chunks):
            raise ValueError("StoryChunkPlan chunk references an unknown scope")
        expected_scope_order = {
            scope_id: index + 1 for index, scope_id in enumerate(self.scope_ids)
        }
        last_scope_ordinal = 0
        chunk_ordinals: dict[str, int] = {}
        for chunk in self.chunks:
            expected_scope_ordinal = expected_scope_order[chunk.scope_id]
            if chunk.scope_ordinal != expected_scope_ordinal:
                raise ValueError("StoryChunkPlan chunk scope ordinal is invalid")
            if chunk.scope_ordinal < last_scope_ordinal:
                raise ValueError("StoryChunkPlan chunks must retain supplied scope order")
            last_scope_ordinal = chunk.scope_ordinal
            next_ordinal = chunk_ordinals.get(chunk.scope_id, 0) + 1
            if chunk.chunk_ordinal != next_ordinal:
                raise ValueError("StoryChunkPlan chunk ordinals must be contiguous per scope")
            chunk_ordinals[chunk.scope_id] = next_ordinal
            if (
                not chunk.structural_fallback_only
                and cast(int, chunk.complete_request_tokens) > self.maximum_request_tokens
            ):
                raise ValueError("StoryChunkPlan provider request exceeds the hard ceiling")
            if (
                chunk.structural_fallback_only
                and cast(int, chunk.oversized_candidate_tokens)
                <= self.maximum_request_tokens
            ):
                raise ValueError("structural-only chunk must exceed the hard ceiling")
            if any(segment.choice_key not in parent_key_set for segment in chunk.choice_segments):
                raise ValueError("StoryChunkPlan segment lacks one Python-owned choice parent")
            segment_keys = tuple(segment.choice_key for segment in chunk.choice_segments)
            if len(segment_keys) != len(set(segment_keys)):
                raise ValueError("StoryChunkPlan chunk repeats one choice parent")

        segments_by_choice: dict[str, list[FrozenChoiceSegment]] = {}
        for chunk in self.chunks:
            for segment in chunk.choice_segments:
                segments_by_choice.setdefault(segment.choice_key, []).append(segment)
        for segments in segments_by_choice.values():
            count = len(segments)
            if any(segment.segment_count != count for segment in segments) or tuple(
                segment.segment_ordinal for segment in segments
            ) != tuple(range(1, count + 1)):
                raise ValueError(
                    "StoryChunkPlan choice segmentation is not exact and deterministic"
                )

    @property
    def coverage_hash(self) -> str:
        return canonical_hash(self.covered_placement_ids)

    @property
    def identity(self) -> str:
        return canonical_hash(_plan_payload(self))


@dataclass(frozen=True)
class _ChunkDraft:
    chunk_id: str
    scope: ChunkPlanningScope
    chunk_ordinal: int
    placements: tuple[ChunkPlanningPlacement, ...]
    profile: ChunkProfileKind
    structural_fallback_only: bool
    oversized_candidate_tokens: int | None


def _ordered_unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _chunk_id(projection: ChunkPlanningProjection, scope_id: str, ordinal: int) -> str:
    digest = canonical_hash(
        {
            "story_plan_identity": projection.story_plan_identity,
            "scope_id": scope_id,
            "chunk_ordinal": ordinal,
        }
    )
    return f"story-chunk-{digest[:24]}"


def _raw_story(placements: tuple[ChunkPlanningPlacement, ...]) -> str:
    pieces: list[str] = []
    for placement in placements:
        header = canonical_json(
            {
                "end_line": placement.end_line,
                "path": placement.relative_path,
                "placement_id": placement.placement_id,
                "scene_id": placement.scene_id,
                "start_line": placement.start_line,
            }
        ).decode("utf-8")
        raw_text = placement.raw_text
        pieces.append(f"@@PLACEMENT {header}\n{raw_text}")
        if not raw_text.endswith("\n"):
            pieces.append("\n")
    return "".join(pieces)


def _choice_parent_payload(parent: FrozenChoiceParent) -> dict[str, object]:
    return {
        "choice_key": parent.choice_key,
        "mechanics": json.loads(parent.canonical_mechanics),
        "mechanics_hash": parent.mechanics_hash,
    }


def _choice_segments_for_placements(
    placements: tuple[ChunkPlanningPlacement, ...],
    *,
    segment_positions: dict[str, tuple[int, int]] | None,
    conservative_segment_bound: int,
) -> tuple[FrozenChoiceSegment, ...]:
    choice_keys = _ordered_unique(
        [arm.choice_key for placement in placements for arm in placement.choice_arms]
    )
    result: list[FrozenChoiceSegment] = []
    for choice_key in choice_keys:
        arms = [
            arm
            for placement in placements
            for arm in placement.choice_arms
            if arm.choice_key == choice_key
        ]
        arm_orders = tuple(dict.fromkeys(arm.arm_order for arm in arms))
        boundary_kinds = _ordered_unique([arm.boundary_kind for arm in arms])
        if segment_positions is None:
            segment_ordinal = conservative_segment_bound
            segment_count = conservative_segment_bound
        else:
            segment_ordinal, segment_count = segment_positions[choice_key]
        result.append(
            FrozenChoiceSegment(
                choice_key=choice_key,
                arm_orders=arm_orders,
                boundary_kinds=boundary_kinds,
                maximum_depth=max(arm.depth for arm in arms),
                segment_ordinal=segment_ordinal,
                segment_count=segment_count,
            )
        )
    return tuple(result)


def _mechanics_payload(
    segments: tuple[FrozenChoiceSegment, ...],
    parents_by_key: dict[str, FrozenChoiceParent],
) -> dict[str, object]:
    return {
        "choice_parents": [
            {
                **_choice_parent_payload(parents_by_key[segment.choice_key]),
                "segment": {
                    "arm_orders": list(segment.arm_orders),
                    "boundary_kinds": list(segment.boundary_kinds),
                    "maximum_depth": segment.maximum_depth,
                    "ordinal": segment.segment_ordinal,
                    "count": segment.segment_count,
                },
            }
            for segment in segments
        ]
    }


def _request_payload(
    *,
    story_plan_identity: str,
    chunk_id: str,
    scope_id: str,
    scope_ordinal: int,
    chunk_ordinal: int,
    profile: ChunkProfileKind,
    placement_ids: tuple[str, ...],
    raw_story: str,
    mechanics: dict[str, object],
    structural_flags: tuple[str, ...],
    prompt_version: str,
) -> dict[str, object]:
    return {
        "schema": PHASE04_MAPPER_REQUEST_SCHEMA,
        "prompt_version": prompt_version,
        "story_plan_identity": story_plan_identity,
        "chunk_id": chunk_id,
        "scope": {"id": scope_id, "ordinal": scope_ordinal},
        "chunk_ordinal": chunk_ordinal,
        "profile": profile.value,
        "placement_ids": list(placement_ids),
        "raw_story": raw_story,
        "mechanics": mechanics,
        "structural_flags": list(structural_flags),
    }


def _complete_request_tokens(
    request: bytes,
    placements: tuple[ChunkPlanningPlacement, ...],
) -> int:
    """Count authoritative raw estimates plus every non-raw UTF-8 request byte.

    Raw story tokens come from the deterministic A1 material projection.  Every framing,
    qualification, JSON-escape, mechanic, identity, and schema byte is then charged as one token.
    This deliberately over-counts request overhead while retaining the approved 8k/5k raw targets.
    """

    raw_content_bytes = sum(len(item.raw_text.encode("utf-8")) for item in placements)
    if len(request) < raw_content_bytes:
        raise ValueError("serialized request cannot be smaller than its raw placement text")
    return sum(item.raw_tokens for item in placements) + len(request) - raw_content_bytes


def _draft_request_metrics(
    projection: ChunkPlanningProjection,
    scope: ChunkPlanningScope,
    chunk_ordinal: int,
    placements: tuple[ChunkPlanningPlacement, ...],
    profile: ChunkProfileKind,
    parents_by_key: dict[str, FrozenChoiceParent],
    conservative_segment_bound: int,
) -> tuple[int, int]:
    segments = _choice_segments_for_placements(
        placements,
        segment_positions=None,
        conservative_segment_bound=conservative_segment_bound,
    )
    raw_story = _raw_story(placements)
    flags = _ordered_unique(
        [flag for placement in placements for flag in placement.structural_flags]
    )
    payload = _request_payload(
        story_plan_identity=projection.story_plan_identity,
        chunk_id=_chunk_id(projection, scope.scope_id, chunk_ordinal),
        scope_id=scope.scope_id,
        scope_ordinal=scope.ordinal,
        chunk_ordinal=chunk_ordinal,
        profile=profile,
        placement_ids=tuple(item.placement_id for item in placements),
        raw_story=raw_story,
        mechanics=_mechanics_payload(segments, parents_by_key),
        structural_flags=flags,
        prompt_version=PHASE04_MAPPER_PROMPT_VERSION,
    )
    request = canonical_json(payload)
    return len(request), _complete_request_tokens(request, placements)


def _plan_scope_drafts(
    projection: ChunkPlanningProjection,
    scope: ChunkPlanningScope,
    policy: ChunkSizingPolicy,
    parents_by_key: dict[str, FrozenChoiceParent],
    conservative_segment_bound: int,
) -> tuple[_ChunkDraft, ...]:
    contains_choice_material = any(
        placement.choice_arms for placement in scope.placements
    )
    profile = (
        ChunkProfileKind.BRANCH_HEAVY
        if scope.branch_heavy or contains_choice_material
        else ChunkProfileKind.NORMAL
    )
    target = (
        policy.branch_target_tokens
        if profile is ChunkProfileKind.BRANCH_HEAVY
        else policy.normal_target_tokens
    )
    drafts: list[_ChunkDraft] = []
    current: tuple[ChunkPlanningPlacement, ...] = ()
    cursor = 0
    while cursor < len(scope.placements):
        placement = scope.placements[cursor]
        candidate = (*current, placement)
        chunk_ordinal = len(drafts) + 1
        _, candidate_tokens = _draft_request_metrics(
            projection,
            scope,
            chunk_ordinal,
            candidate,
            profile,
            parents_by_key,
            conservative_segment_bound,
        )
        if candidate_tokens > policy.maximum_request_tokens:
            if current:
                drafts.append(
                    _ChunkDraft(
                        chunk_id=_chunk_id(projection, scope.scope_id, chunk_ordinal),
                        scope=scope,
                        chunk_ordinal=chunk_ordinal,
                        placements=current,
                        profile=profile,
                        structural_fallback_only=False,
                        oversized_candidate_tokens=None,
                    )
                )
                current = ()
                continue
            drafts.append(
                _ChunkDraft(
                    chunk_id=_chunk_id(projection, scope.scope_id, chunk_ordinal),
                    scope=scope,
                    chunk_ordinal=chunk_ordinal,
                    placements=(placement,),
                    profile=profile,
                    structural_fallback_only=True,
                    oversized_candidate_tokens=candidate_tokens,
                )
            )
            cursor += 1
            continue
        current = candidate
        cursor += 1
        if sum(item.raw_tokens for item in current) >= target:
            drafts.append(
                _ChunkDraft(
                    chunk_id=_chunk_id(projection, scope.scope_id, chunk_ordinal),
                    scope=scope,
                    chunk_ordinal=chunk_ordinal,
                    placements=current,
                    profile=profile,
                    structural_fallback_only=False,
                    oversized_candidate_tokens=None,
                )
            )
            current = ()
    if current:
        chunk_ordinal = len(drafts) + 1
        drafts.append(
            _ChunkDraft(
                chunk_id=_chunk_id(projection, scope.scope_id, chunk_ordinal),
                scope=scope,
                chunk_ordinal=chunk_ordinal,
                placements=current,
                profile=profile,
                structural_fallback_only=False,
                oversized_candidate_tokens=None,
            )
        )
    return tuple(drafts)


DEFAULT_CHUNK_SIZING_POLICY = ChunkSizingPolicy()


def plan_story_chunks(
    projection: ChunkPlanningProjection,
    policy: ChunkSizingPolicy = DEFAULT_CHUNK_SIZING_POLICY,
) -> StoryChunkPlan:
    """Freeze exact placement coverage and every complete provider request identity."""

    choice_parents = tuple(
        FrozenChoiceParent(
            choice_key=choice.choice_key,
            canonical_mechanics=choice.canonical_mechanics,
            mechanics_hash=canonical_hash(json.loads(choice.canonical_mechanics)),
        )
        for choice in projection.choices
    )
    parents_by_key = {parent.choice_key: parent for parent in choice_parents}
    total_placements = sum(len(scope.placements) for scope in projection.scopes)
    conservative_segment_bound = max(1, total_placements)
    drafts = tuple(
        draft
        for scope in projection.scopes
        for draft in _plan_scope_drafts(
            projection,
            scope,
            policy,
            parents_by_key,
            conservative_segment_bound,
        )
    )

    choice_draft_positions: dict[str, list[int]] = {}
    for draft_index, draft in enumerate(drafts):
        choice_keys = _ordered_unique(
            [
                arm.choice_key
                for placement in draft.placements
                for arm in placement.choice_arms
            ]
        )
        for choice_key in choice_keys:
            choice_draft_positions.setdefault(choice_key, []).append(draft_index)
    segment_positions_by_draft: dict[int, dict[str, tuple[int, int]]] = {}
    for choice_key, draft_indices in choice_draft_positions.items():
        for ordinal, draft_index in enumerate(draft_indices, start=1):
            segment_positions_by_draft.setdefault(draft_index, {})[choice_key] = (
                ordinal,
                len(draft_indices),
            )

    chunks: list[StoryChunkDescriptor] = []
    for draft_index, draft in enumerate(drafts):
        segments = _choice_segments_for_placements(
            draft.placements,
            segment_positions=segment_positions_by_draft.get(draft_index, {}),
            conservative_segment_bound=conservative_segment_bound,
        )
        raw_story = _raw_story(draft.placements)
        mechanics = _mechanics_payload(segments, parents_by_key)
        flags = _ordered_unique(
            [flag for placement in draft.placements for flag in placement.structural_flags]
        )
        placement_ids = tuple(item.placement_id for item in draft.placements)
        rendered_input_hash = canonical_hash(raw_story)
        mechanics_hash = canonical_hash(mechanics)
        raw_tokens = sum(item.raw_tokens for item in draft.placements)
        if draft.structural_fallback_only:
            chunks.append(
                StoryChunkDescriptor(
                    chunk_id=draft.chunk_id,
                    scope_id=draft.scope.scope_id,
                    scope_ordinal=draft.scope.ordinal,
                    chunk_ordinal=draft.chunk_ordinal,
                    profile=draft.profile,
                    placement_ids=placement_ids,
                    raw_tokens=raw_tokens,
                    rendered_input_hash=rendered_input_hash,
                    mechanics_hash=mechanics_hash,
                    request_hash=None,
                    serialized_request_bytes=0,
                    complete_request_tokens=None,
                    structural_fallback_only=True,
                    structural_fallback_reason="atomic_scene_request_exceeds_hard_ceiling",
                    oversized_candidate_tokens=draft.oversized_candidate_tokens,
                    structural_flags=flags,
                    choice_segments=segments,
                )
            )
            continue
        request = canonical_json(
            _request_payload(
                story_plan_identity=projection.story_plan_identity,
                chunk_id=draft.chunk_id,
                scope_id=draft.scope.scope_id,
                scope_ordinal=draft.scope.ordinal,
                chunk_ordinal=draft.chunk_ordinal,
                profile=draft.profile,
                placement_ids=placement_ids,
                raw_story=raw_story,
                mechanics=mechanics,
                structural_flags=flags,
                prompt_version=PHASE04_MAPPER_PROMPT_VERSION,
            )
        )
        complete_tokens = _complete_request_tokens(request, draft.placements)
        if complete_tokens > policy.maximum_request_tokens:
            raise ValueError("final request exceeded its conservative preflight size")
        chunks.append(
            StoryChunkDescriptor(
                chunk_id=draft.chunk_id,
                scope_id=draft.scope.scope_id,
                scope_ordinal=draft.scope.ordinal,
                chunk_ordinal=draft.chunk_ordinal,
                profile=draft.profile,
                placement_ids=placement_ids,
                raw_tokens=raw_tokens,
                rendered_input_hash=rendered_input_hash,
                mechanics_hash=mechanics_hash,
                request_hash=hashlib.sha256(request).hexdigest(),
                serialized_request_bytes=len(request),
                complete_request_tokens=complete_tokens,
                structural_fallback_only=False,
                structural_fallback_reason=None,
                oversized_candidate_tokens=None,
                structural_flags=flags,
                choice_segments=segments,
            )
        )

    return StoryChunkPlan(
        story_plan_identity=projection.story_plan_identity,
        source_identity=projection.source_identity,
        scope_ids=tuple(scope.scope_id for scope in projection.scopes),
        covered_placement_ids=tuple(
            placement.placement_id
            for scope in projection.scopes
            for placement in scope.placements
        ),
        choice_parents=choice_parents,
        chunks=tuple(chunks),
        normal_target_tokens=policy.normal_target_tokens,
        branch_target_tokens=policy.branch_target_tokens,
        maximum_request_tokens=policy.maximum_request_tokens,
    )


def serialize_chunk_request(
    plan: StoryChunkPlan,
    chunk_id: str,
    projection: ChunkPlanningProjection,
) -> bytes:
    """Reconstruct and verify one exact frozen request without planning or provider work."""

    if plan.story_plan_identity != projection.story_plan_identity:
        raise FrozenPlanMismatch("current story plan identity differs from the frozen chunk plan")
    if plan.source_identity != projection.source_identity:
        raise FrozenPlanMismatch("current source identity differs from the frozen chunk plan")
    chunk = next((item for item in plan.chunks if item.chunk_id == chunk_id), None)
    if chunk is None:
        raise FrozenPlanMismatch("unknown frozen chunk ID")
    if chunk.structural_fallback_only:
        raise FrozenPlanMismatch("structural-fallback-only chunk has no provider request")

    placements_by_id = {
        placement.placement_id: placement
        for scope in projection.scopes
        for placement in scope.placements
    }
    try:
        placements = tuple(placements_by_id[item] for item in chunk.placement_ids)
    except KeyError as exc:
        raise FrozenPlanMismatch("current story plan omits a frozen placement") from exc
    if any(placement.scope_id != chunk.scope_id for placement in placements):
        raise FrozenPlanMismatch("current placement scope differs from the frozen chunk")
    raw_story = _raw_story(placements)
    if canonical_hash(raw_story) != chunk.rendered_input_hash:
        raise FrozenPlanMismatch("current rendered input differs from the frozen chunk plan")

    current_choices = {choice.choice_key: choice for choice in projection.choices}
    parents_by_key = {parent.choice_key: parent for parent in plan.choice_parents}
    for segment in chunk.choice_segments:
        current = current_choices.get(segment.choice_key)
        parent = parents_by_key[segment.choice_key]
        if current is None or current.canonical_mechanics != parent.canonical_mechanics:
            raise FrozenPlanMismatch("current mechanics differ from the frozen chunk plan")
    mechanics = _mechanics_payload(chunk.choice_segments, parents_by_key)
    if canonical_hash(mechanics) != chunk.mechanics_hash:
        raise FrozenPlanMismatch("frozen mechanics identity is internally inconsistent")
    request = canonical_json(
        _request_payload(
            story_plan_identity=plan.story_plan_identity,
            chunk_id=chunk.chunk_id,
            scope_id=chunk.scope_id,
            scope_ordinal=chunk.scope_ordinal,
            chunk_ordinal=chunk.chunk_ordinal,
            profile=chunk.profile,
            placement_ids=chunk.placement_ids,
            raw_story=raw_story,
            mechanics=mechanics,
            structural_flags=chunk.structural_flags,
            prompt_version=plan.prompt_version,
        )
    )
    complete_tokens = _complete_request_tokens(request, placements)
    if (
        len(request) != chunk.serialized_request_bytes
        or complete_tokens != chunk.complete_request_tokens
        or complete_tokens > plan.maximum_request_tokens
        or hashlib.sha256(request).hexdigest() != chunk.request_hash
    ):
        raise FrozenPlanMismatch("reconstructed request differs from the exact frozen request")
    return request


def _segment_payload(segment: FrozenChoiceSegment) -> dict[str, object]:
    return {
        "choice_key": segment.choice_key,
        "arm_orders": list(segment.arm_orders),
        "boundary_kinds": list(segment.boundary_kinds),
        "maximum_depth": segment.maximum_depth,
        "segment_ordinal": segment.segment_ordinal,
        "segment_count": segment.segment_count,
    }


def _chunk_payload(chunk: StoryChunkDescriptor) -> dict[str, object]:
    return {
        "chunk_id": chunk.chunk_id,
        "scope_id": chunk.scope_id,
        "scope_ordinal": chunk.scope_ordinal,
        "chunk_ordinal": chunk.chunk_ordinal,
        "profile": chunk.profile.value,
        "placement_ids": list(chunk.placement_ids),
        "raw_tokens": chunk.raw_tokens,
        "rendered_input_hash": chunk.rendered_input_hash,
        "mechanics_hash": chunk.mechanics_hash,
        "request_hash": chunk.request_hash,
        "serialized_request_bytes": chunk.serialized_request_bytes,
        "complete_request_tokens": chunk.complete_request_tokens,
        "structural_fallback_only": chunk.structural_fallback_only,
        "structural_fallback_reason": chunk.structural_fallback_reason,
        "oversized_candidate_tokens": chunk.oversized_candidate_tokens,
        "structural_flags": list(chunk.structural_flags),
        "choice_segments": [_segment_payload(item) for item in chunk.choice_segments],
    }


def _plan_payload(plan: StoryChunkPlan) -> dict[str, object]:
    return {
        "schema": plan.schema,
        "token_counter": plan.token_counter,
        "prompt_version": plan.prompt_version,
        "story_plan_identity": plan.story_plan_identity,
        "source_identity": plan.source_identity,
        "scope_ids": list(plan.scope_ids),
        "covered_placement_ids": list(plan.covered_placement_ids),
        "coverage_hash": plan.coverage_hash,
        "choice_parents": [
            {
                "choice_key": parent.choice_key,
                "canonical_mechanics": parent.canonical_mechanics,
                "mechanics_hash": parent.mechanics_hash,
            }
            for parent in plan.choice_parents
        ],
        "chunks": [_chunk_payload(chunk) for chunk in plan.chunks],
        "normal_target_tokens": plan.normal_target_tokens,
        "branch_target_tokens": plan.branch_target_tokens,
        "maximum_request_tokens": plan.maximum_request_tokens,
    }


def serialize_story_chunk_plan(plan: StoryChunkPlan) -> bytes:
    """Serialize the complete frozen plan with a self-verifying identity."""

    return canonical_json({**_plan_payload(plan), "identity": plan.identity})


def _required_dict(value: object, label: str) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _exact_keys(value: dict[str, object], expected: frozenset[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} has missing or unexpected fields")


def _required_list(value: object, label: str) -> list[object]:
    if type(value) is not list:
        raise ValueError(f"{label} must be an array")
    return cast(list[object], value)


def _required_str(value: object, label: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{label} must be a string")
    return value


def _optional_str(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _required_str(value, label)


def _required_int(value: object, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} must be an integer")
    return value


def _optional_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    return _required_int(value, label)


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    return tuple(
        _required_str(item, f"{label}[]") for item in _required_list(value, label)
    )


def deserialize_story_chunk_plan(payload: bytes | str) -> StoryChunkPlan:
    """Strictly reconstruct a frozen plan and verify its canonical identity."""

    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("StoryChunkPlan payload is not valid JSON") from exc
    root = _required_dict(decoded, "StoryChunkPlan")
    _exact_keys(
        root,
        frozenset(
            {
                "schema",
                "token_counter",
                "prompt_version",
                "story_plan_identity",
                "source_identity",
                "scope_ids",
                "covered_placement_ids",
                "coverage_hash",
                "choice_parents",
                "chunks",
                "normal_target_tokens",
                "branch_target_tokens",
                "maximum_request_tokens",
                "identity",
            }
        ),
        "StoryChunkPlan",
    )
    parents: list[FrozenChoiceParent] = []
    for parent_value in _required_list(root.get("choice_parents"), "choice_parents"):
        item = _required_dict(parent_value, "choice parent")
        _exact_keys(
            item,
            frozenset({"choice_key", "canonical_mechanics", "mechanics_hash"}),
            "choice parent",
        )
        parents.append(
            FrozenChoiceParent(
                choice_key=_required_str(item["choice_key"], "choice parent key"),
                canonical_mechanics=_required_str(
                    item["canonical_mechanics"], "choice parent mechanics"
                ),
                mechanics_hash=_required_str(item["mechanics_hash"], "choice parent hash"),
            )
        )
    chunks: list[StoryChunkDescriptor] = []
    for chunk_value in _required_list(root.get("chunks"), "chunks"):
        item = _required_dict(chunk_value, "chunk")
        _exact_keys(
            item,
            frozenset(
                {
                    "chunk_id",
                    "scope_id",
                    "scope_ordinal",
                    "chunk_ordinal",
                    "profile",
                    "placement_ids",
                    "raw_tokens",
                    "rendered_input_hash",
                    "mechanics_hash",
                    "request_hash",
                    "serialized_request_bytes",
                    "complete_request_tokens",
                    "structural_fallback_only",
                    "structural_fallback_reason",
                    "oversized_candidate_tokens",
                    "structural_flags",
                    "choice_segments",
                }
            ),
            "chunk",
        )
        segments: list[FrozenChoiceSegment] = []
        for segment_value in _required_list(
            item.get("choice_segments"), "choice_segments"
        ):
            segment = _required_dict(segment_value, "choice segment")
            _exact_keys(
                segment,
                frozenset(
                    {
                        "choice_key",
                        "arm_orders",
                        "boundary_kinds",
                        "maximum_depth",
                        "segment_ordinal",
                        "segment_count",
                    }
                ),
                "choice segment",
            )
            segments.append(
                FrozenChoiceSegment(
                    choice_key=_required_str(segment["choice_key"], "segment choice key"),
                    arm_orders=tuple(
                        _required_int(value, "segment arm order")
                        for value in _required_list(
                            segment.get("arm_orders"), "segment arm_orders"
                        )
                    ),
                    boundary_kinds=_string_tuple(
                        segment.get("boundary_kinds"), "segment boundary_kinds"
                    ),
                    maximum_depth=_required_int(
                        segment.get("maximum_depth"), "segment maximum_depth"
                    ),
                    segment_ordinal=_required_int(
                        segment.get("segment_ordinal"), "segment ordinal"
                    ),
                    segment_count=_required_int(
                        segment.get("segment_count"), "segment count"
                    ),
                )
            )
        fallback_only = item.get("structural_fallback_only")
        if type(fallback_only) is not bool:
            raise ValueError("structural_fallback_only must be a boolean")
        chunks.append(
            StoryChunkDescriptor(
                chunk_id=_required_str(item.get("chunk_id"), "chunk ID"),
                scope_id=_required_str(item.get("scope_id"), "scope ID"),
                scope_ordinal=_required_int(item.get("scope_ordinal"), "scope ordinal"),
                chunk_ordinal=_required_int(item.get("chunk_ordinal"), "chunk ordinal"),
                profile=ChunkProfileKind(_required_str(item.get("profile"), "profile")),
                placement_ids=_string_tuple(item.get("placement_ids"), "placement_ids"),
                raw_tokens=_required_int(item.get("raw_tokens"), "raw tokens"),
                rendered_input_hash=_required_str(
                    item.get("rendered_input_hash"), "rendered input hash"
                ),
                mechanics_hash=_required_str(item.get("mechanics_hash"), "mechanics hash"),
                request_hash=_optional_str(item.get("request_hash"), "request hash"),
                serialized_request_bytes=_required_int(
                    item.get("serialized_request_bytes"), "serialized request bytes"
                ),
                complete_request_tokens=_optional_int(
                    item.get("complete_request_tokens"), "complete request tokens"
                ),
                structural_fallback_only=fallback_only,
                structural_fallback_reason=_optional_str(
                    item.get("structural_fallback_reason"), "structural fallback reason"
                ),
                oversized_candidate_tokens=_optional_int(
                    item.get("oversized_candidate_tokens"), "oversized candidate tokens"
                ),
                structural_flags=_string_tuple(
                    item.get("structural_flags"), "structural_flags"
                ),
                choice_segments=tuple(segments),
            )
        )
    plan = StoryChunkPlan(
        story_plan_identity=_required_str(
            root.get("story_plan_identity"), "story plan identity"
        ),
        source_identity=_required_str(root.get("source_identity"), "source identity"),
        scope_ids=_string_tuple(root.get("scope_ids"), "scope_ids"),
        covered_placement_ids=_string_tuple(
            root.get("covered_placement_ids"), "covered_placement_ids"
        ),
        choice_parents=tuple(parents),
        chunks=tuple(chunks),
        normal_target_tokens=_required_int(
            root.get("normal_target_tokens"), "normal target tokens"
        ),
        branch_target_tokens=_required_int(
            root.get("branch_target_tokens"), "branch target tokens"
        ),
        maximum_request_tokens=_required_int(
            root.get("maximum_request_tokens"), "maximum request tokens"
        ),
        schema=_required_str(root.get("schema"), "schema"),
        token_counter=_required_str(root.get("token_counter"), "token counter"),
        prompt_version=_required_str(root.get("prompt_version"), "prompt version"),
    )
    if root.get("coverage_hash") != plan.coverage_hash:
        raise ValueError("StoryChunkPlan coverage hash is invalid")
    if root.get("identity") != plan.identity:
        raise ValueError("StoryChunkPlan identity is invalid")
    if canonical_json(root) != (payload.encode("utf-8") if isinstance(payload, str) else payload):
        raise ValueError("StoryChunkPlan payload must use canonical JSON bytes")
    return plan
