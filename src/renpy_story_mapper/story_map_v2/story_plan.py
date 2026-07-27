"""Occurrence-aware deterministic Story Plan contracts for Story Map V2 Phase 04.

The plan is a locator/index contract over current M10 and M11 authority. It never
copies mechanics into a competing graph and never gives provider prose ownership of
placement, choices, routes, loops, terminals, or unresolved behavior.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import cast

from renpy_story_mapper.canonical_graph_contract import (
    CanonicalGraph,
    CanonicalNode,
    CanonicalNodeKind,
)
from renpy_story_mapper.m11_scene_model import (
    CallSiteOccurrence,
    Chapter,
    LaneKind,
    PersistentLane,
    Scene,
    SceneModel,
    StoryAtom,
)
from renpy_story_mapper.story_map_v2.contracts import (
    ArmLineageStep,
    Reachability,
    SourceSpan,
    StoryScope,
    canonical_hash,
    canonical_json,
)
from renpy_story_mapper.story_map_v2.source_adapter import (
    SourceAdaptationError,
    adapt_story_scope,
)

STORY_PLAN_SCHEMA_VERSION = 1
STORY_PLAN_SCHEMA = f"story-map-v2-story-plan-v{STORY_PLAN_SCHEMA_VERSION}"

_STORY_PLAN_ROOT_FIELDS = frozenset(
    {
        "schema",
        "source_identity",
        "source_generation",
        "canonical_hash",
        "scene_model_hash",
        "source_scope_identity",
        "source_span_keys",
        "scopes",
        "placements",
        "loops",
        "source_coverage_identity",
        "placement_coverage_identity",
        "identity",
    }
)
_STORY_SCOPE_FIELDS = frozenset(
    {
        "id",
        "kind",
        "chapter_id",
        "chapter_ordinal",
        "lane_id",
        "lane_kind",
        "parent_scope_id",
        "canonical_region_id",
        "arm_ordinal",
        "split_anchor_id",
        "placement_ids",
        "child_scope_ids",
    }
)
_STORY_PLACEMENT_FIELDS = frozenset(
    {
        "id",
        "scope_id",
        "ordinal",
        "role",
        "span_key",
        "scene_id",
        "context_scene_id",
        "occurrence_path",
        "relative_path",
        "start_line",
        "end_line",
        "canonical_node_ids",
        "choice_keys",
        "arm_lineage",
        "anchor_id",
        "coverage_identity",
        "loop_ids",
        "terminal_node_ids",
        "unresolved_node_ids",
    }
)
_STORY_LOOP_FIELDS = frozenset(
    {
        "id",
        "loop_hub_id",
        "repeatable",
        "scope_ids",
        "placement_ids",
        "occurrence_ids",
        "return_relationship_ids",
        "partial_order_relation_ids",
    }
)
_ARM_LINEAGE_FIELDS = frozenset({"choice_key", "arm_order"})


class StoryScopeKind(StrEnum):
    """Deterministic placement ownership within one M11 chapter."""

    CHAPTER_SPINE = "chapter_spine"
    PERSISTENT_LANE = "persistent_lane"


class PlacementRole(StrEnum):
    """Why one source span appears at this narrative occurrence."""

    SCENE = "scene"
    CALL_OCCURRENCE = "call_occurrence"
    COLLAPSED_SUPPORT = "collapsed_support"


@dataclass(frozen=True)
class StoryPlacement:
    """One exact occurrence of one authoritative source span."""

    id: str
    scope_id: str
    ordinal: int
    role: PlacementRole
    span_key: str
    scene_id: str
    context_scene_id: str
    occurrence_path: tuple[str, ...]
    relative_path: str
    start_line: int
    end_line: int
    canonical_node_ids: tuple[str, ...]
    choice_keys: tuple[str, ...]
    arm_lineage: tuple[ArmLineageStep, ...]
    anchor_id: str
    coverage_identity: str
    loop_ids: tuple[str, ...]
    terminal_node_ids: tuple[str, ...]
    unresolved_node_ids: tuple[str, ...]

    @property
    def occurrence_id(self) -> str | None:
        return self.occurrence_path[-1] if self.occurrence_path else None

    @property
    def loop_id(self) -> str | None:
        """Return the primary loop while retaining every nested loop binding."""

        return self.loop_ids[0] if self.loop_ids else None


@dataclass(frozen=True)
class StoryScopeDescriptor:
    """One M11 chapter/lane scope with persistent lanes owned as children."""

    id: str
    kind: StoryScopeKind
    chapter_id: str
    chapter_ordinal: int
    lane_id: str
    lane_kind: LaneKind
    parent_scope_id: str | None
    canonical_region_id: str | None
    arm_ordinal: int | None
    split_anchor_id: str | None
    placement_ids: tuple[str, ...]
    child_scope_ids: tuple[str, ...]


@dataclass(frozen=True)
class StoryLoopMetadata:
    """One bounded reference to an M11 loop hub; content is never unrolled."""

    id: str
    loop_hub_id: str
    repeatable: bool
    scope_ids: tuple[str, ...]
    placement_ids: tuple[str, ...]
    occurrence_ids: tuple[str, ...]
    return_relationship_ids: tuple[str, ...]
    partial_order_relation_ids: tuple[str, ...]


@dataclass(frozen=True)
class StoryPlan:
    """Frozen M11-first placement plan over one exact M10/M11 binding."""

    schema: str
    source_identity: str
    source_generation: str
    canonical_hash: str
    scene_model_hash: str
    source_scope_identity: str
    source_span_keys: tuple[str, ...]
    scopes: tuple[StoryScopeDescriptor, ...]
    placements: tuple[StoryPlacement, ...]
    loops: tuple[StoryLoopMetadata, ...]
    source_coverage_identity: str
    placement_coverage_identity: str

    @property
    def identity(self) -> str:
        return canonical_hash(self.normalized_dict())

    def normalized_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "source_identity": self.source_identity,
            "source_generation": self.source_generation,
            "canonical_hash": self.canonical_hash,
            "scene_model_hash": self.scene_model_hash,
            "source_scope_identity": self.source_scope_identity,
            "source_span_keys": self.source_span_keys,
            "scopes": tuple(asdict(item) for item in self.scopes),
            "placements": tuple(asdict(item) for item in self.placements),
            "loops": tuple(asdict(item) for item in self.loops),
            "source_coverage_identity": self.source_coverage_identity,
            "placement_coverage_identity": self.placement_coverage_identity,
        }

    def validate(self) -> None:
        if self.schema != STORY_PLAN_SCHEMA:
            raise ValueError("Story Plan schema is unsupported")
        for value, label in (
            (self.source_identity, "source identity"),
            (self.source_generation, "source generation"),
            (self.canonical_hash, "canonical hash"),
            (self.scene_model_hash, "scene model hash"),
            (self.source_scope_identity, "source scope identity"),
            (self.source_coverage_identity, "source coverage identity"),
            (self.placement_coverage_identity, "placement coverage identity"),
        ):
            _trimmed(value, label)
        if PurePosixPath(self.source_identity).is_absolute() or PureWindowsPath(
            self.source_identity
        ).is_absolute():
            raise ValueError("Story Plan source identity must not be an absolute path")
        if len(self.source_span_keys) != len(set(self.source_span_keys)):
            raise ValueError("Story Plan source span keys must be unique")
        if self.source_span_keys != tuple(sorted(self.source_span_keys)):
            raise ValueError("Story Plan source span keys must retain canonical order")
        scopes = _unique_records(self.scopes, "scope")
        placements = _unique_records(self.placements, "placement")
        loops = _unique_records(self.loops, "loop")
        if not scopes:
            raise ValueError("Story Plan requires at least one scope")
        if len({item.anchor_id for item in self.placements}) != len(self.placements):
            raise ValueError("Story Plan placement anchors must be unique")
        if len({item.coverage_identity for item in self.placements}) != len(self.placements):
            raise ValueError("Story Plan placement coverage identities must be unique")

        scope_order = {item.id: ordinal for ordinal, item in enumerate(self.scopes)}
        if tuple(item.chapter_ordinal for item in self.scopes) != tuple(
            sorted(item.chapter_ordinal for item in self.scopes)
        ):
            raise ValueError("Story Plan scopes must retain chapter order")
        scoped_placements: list[str] = []
        for scope in self.scopes:
            expected_scope_id = "story_scope_" + canonical_hash(
                {
                    "schema": STORY_PLAN_SCHEMA,
                    "source_generation": self.source_generation,
                    "chapter_id": scope.chapter_id,
                    "lane_id": scope.lane_id,
                }
            )[:20]
            if scope.id != expected_scope_id:
                raise ValueError("Story Plan scope identity is invalid")
            if scope.kind is StoryScopeKind.CHAPTER_SPINE:
                if (
                    scope.parent_scope_id is not None
                    or scope.lane_kind is not LaneKind.SPINE
                ):
                    raise ValueError("chapter spine scopes cannot have parents")
            else:
                if (
                    scope.parent_scope_id not in scopes
                    or scope.split_anchor_id is None
                    or scope.lane_kind is LaneKind.SPINE
                    or scope.canonical_region_id is None
                    or scope.arm_ordinal is None
                ):
                    raise ValueError(
                        "persistent lane scopes require exact parent, region, arm, "
                        "and split ownership"
                    )
                parent = scopes[scope.parent_scope_id]
                parent_anchors = {
                    placements[item].anchor_id for item in parent.placement_ids
                }
                if scope.split_anchor_id not in parent_anchors:
                    raise ValueError(
                        f"persistent lane scope {scope.id} has an invalid split anchor"
                    )
                if scope_order[scope.parent_scope_id] >= scope_order[scope.id]:
                    raise ValueError("persistent lane scopes must follow their parents")
            if len(scope.placement_ids) != len(set(scope.placement_ids)):
                raise ValueError(f"scope {scope.id} repeats a placement")
            if len(scope.child_scope_ids) != len(set(scope.child_scope_ids)):
                raise ValueError(f"scope {scope.id} repeats a child scope")
            expected_children = tuple(
                item.id for item in self.scopes if item.parent_scope_id == scope.id
            )
            if scope.child_scope_ids != expected_children:
                raise ValueError(f"scope {scope.id} child order is invalid")
            for child_id in scope.child_scope_ids:
                child = scopes.get(child_id)
                if child is None or child.parent_scope_id != scope.id:
                    raise ValueError(f"scope {scope.id} has inconsistent child ownership")
            for ordinal, placement_id in enumerate(scope.placement_ids):
                placement = placements.get(placement_id)
                if placement is None or placement.scope_id != scope.id:
                    raise ValueError(f"scope {scope.id} has an invalid placement")
                if placement.ordinal != ordinal:
                    raise ValueError(f"scope {scope.id} placement ordinals are not contiguous")
            scoped_placements.extend(scope.placement_ids)
        if sorted(scoped_placements) != sorted(placements):
            raise ValueError("every Story Placement must have exactly one scope owner")
        if tuple(scoped_placements) != tuple(item.id for item in self.placements):
            raise ValueError("Story Plan placements must retain exact scope order")
        if {item.span_key for item in self.placements} != set(self.source_span_keys):
            raise ValueError("Story Plan source placement coverage is incomplete")

        for placement in self.placements:
            if placement.start_line < 1 or placement.end_line < placement.start_line:
                raise ValueError(f"placement {placement.id} has an invalid locator")
            if not _safe_relative_locator(placement.relative_path):
                raise ValueError(f"placement {placement.id} has an unsafe relative locator")
            if (
                placement.role is PlacementRole.SCENE and placement.occurrence_path
            ) or (
                placement.role is PlacementRole.CALL_OCCURRENCE
                and not placement.occurrence_path
            ):
                raise ValueError(f"placement {placement.id} has an invalid occurrence role")
            if len(placement.loop_ids) != len(set(placement.loop_ids)):
                raise ValueError(f"placement {placement.id} repeats a loop")
            lineage_choice_keys = tuple(
                step.choice_key for step in placement.arm_lineage
            )
            if len(lineage_choice_keys) != len(set(lineage_choice_keys)):
                raise ValueError(
                    f"placement {placement.id} repeats a choice in its arm lineage"
                )
            if any(loop_id not in loops for loop_id in placement.loop_ids):
                raise ValueError(f"placement {placement.id} has an unknown loop")
            identity_value = {
                "schema": STORY_PLAN_SCHEMA,
                "scope_id": placement.scope_id,
                "scene_id": placement.scene_id,
                "context_scene_id": placement.context_scene_id,
                "occurrence_path": placement.occurrence_path,
                "span_key": placement.span_key,
                "canonical_node_ids": placement.canonical_node_ids,
                "choice_keys": placement.choice_keys,
                "arm_lineage": tuple(asdict(item) for item in placement.arm_lineage),
            }
            if placement.id != "story_placement_" + canonical_hash(identity_value)[:20]:
                raise ValueError("Story Plan placement identity is invalid")
            if placement.anchor_id != "story_anchor_" + canonical_hash(
                {**identity_value, "anchor_contract": "phase04-v1"}
            )[:20]:
                raise ValueError("Story Plan placement anchor identity is invalid")
            if placement.coverage_identity != canonical_hash(
                {
                    "source_generation": self.source_generation,
                    "scope_id": placement.scope_id,
                    "span_key": placement.span_key,
                    "occurrence_path": placement.occurrence_path,
                }
            ):
                raise ValueError("Story Plan placement coverage identity is invalid")
        if tuple(item.loop_hub_id for item in self.loops) != tuple(
            sorted(item.loop_hub_id for item in self.loops)
        ):
            raise ValueError("Story Plan loops must retain canonical order")
        for loop in self.loops:
            if loop.id != "story_loop_" + canonical_hash(
                {
                    "schema": STORY_PLAN_SCHEMA,
                    "loop_hub_id": loop.loop_hub_id,
                    "placement_ids": loop.placement_ids,
                }
            )[:20]:
                raise ValueError("Story Plan loop identity is invalid")
            if not loop.repeatable:
                raise ValueError(f"loop {loop.id} must remain explicitly repeatable")
            if not loop.placement_ids:
                raise ValueError(f"loop {loop.id} has no bounded placements")
            if len(loop.placement_ids) != len(set(loop.placement_ids)):
                raise ValueError(f"loop {loop.id} repeats a placement")
            if any(item not in placements for item in loop.placement_ids):
                raise ValueError(f"loop {loop.id} has an unknown placement")
            expected_placements = tuple(
                item.id for item in self.placements if item.id in loop.placement_ids
            )
            if loop.placement_ids != expected_placements:
                raise ValueError(f"loop {loop.id} placement order is invalid")
            expected_scopes = tuple(
                dict.fromkeys(placements[item].scope_id for item in loop.placement_ids)
            )
            if loop.scope_ids != expected_scopes:
                raise ValueError(f"loop {loop.id} scope order is invalid")
            if any(loop.id not in placements[item].loop_ids for item in loop.placement_ids):
                raise ValueError(f"loop {loop.id} placement bindings disagree")
        for placement in self.placements:
            if any(
                placement.id not in loops[loop_id].placement_ids
                for loop_id in placement.loop_ids
            ):
                raise ValueError(f"placement {placement.id} loop bindings disagree")
            expected_loops = tuple(
                loop.id for loop in self.loops if placement.id in loop.placement_ids
            )
            if placement.loop_ids != expected_loops:
                raise ValueError(f"placement {placement.id} loop order is invalid")

        if self.source_coverage_identity != canonical_hash(self.source_span_keys):
            raise ValueError("Story Plan source coverage identity is invalid")
        if self.placement_coverage_identity != canonical_hash(
            tuple(item.coverage_identity for item in self.placements)
        ):
            raise ValueError("Story Plan placement coverage identity is invalid")


def serialize_story_plan(plan: StoryPlan) -> bytes:
    """Return exact canonical, self-verifying bytes for one frozen StoryPlan."""

    plan.validate()
    return canonical_json({**plan.normalized_dict(), "identity": plan.identity})


def deserialize_story_plan(payload: bytes | str) -> StoryPlan:
    """Strictly reconstruct and verify one canonical frozen StoryPlan."""

    serialized = _serialized_bytes(payload)
    try:
        decoded = json.loads(
            serialized.decode("utf-8"),
            object_pairs_hook=_object_without_duplicates,
        )
    except UnicodeDecodeError as exc:
        raise ValueError("StoryPlan payload is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("StoryPlan payload is not valid JSON") from exc
    root = _required_dict(decoded, "StoryPlan")
    _exact_keys(root, _STORY_PLAN_ROOT_FIELDS, "StoryPlan")

    scopes: list[StoryScopeDescriptor] = []
    for value in _required_list(root.get("scopes"), "StoryPlan scopes"):
        item = _required_dict(value, "StoryPlan scope")
        _exact_keys(item, _STORY_SCOPE_FIELDS, "StoryPlan scope")
        scopes.append(
            StoryScopeDescriptor(
                id=_required_str(item.get("id"), "StoryPlan scope id"),
                kind=StoryScopeKind(
                    _required_str(item.get("kind"), "StoryPlan scope kind")
                ),
                chapter_id=_required_str(
                    item.get("chapter_id"), "StoryPlan scope chapter id"
                ),
                chapter_ordinal=_required_int(
                    item.get("chapter_ordinal"), "StoryPlan scope chapter ordinal"
                ),
                lane_id=_required_str(
                    item.get("lane_id"), "StoryPlan scope lane id"
                ),
                lane_kind=LaneKind(
                    _required_str(item.get("lane_kind"), "StoryPlan scope lane kind")
                ),
                parent_scope_id=_optional_str(
                    item.get("parent_scope_id"), "StoryPlan scope parent id"
                ),
                canonical_region_id=_optional_str(
                    item.get("canonical_region_id"),
                    "StoryPlan scope canonical region id",
                ),
                arm_ordinal=_optional_int(
                    item.get("arm_ordinal"), "StoryPlan scope arm ordinal"
                ),
                split_anchor_id=_optional_str(
                    item.get("split_anchor_id"), "StoryPlan scope split anchor id"
                ),
                placement_ids=_string_tuple(
                    item.get("placement_ids"), "StoryPlan scope placement ids"
                ),
                child_scope_ids=_string_tuple(
                    item.get("child_scope_ids"), "StoryPlan scope child ids"
                ),
            )
        )

    placements: list[StoryPlacement] = []
    for value in _required_list(root.get("placements"), "StoryPlan placements"):
        item = _required_dict(value, "StoryPlan placement")
        _exact_keys(item, _STORY_PLACEMENT_FIELDS, "StoryPlan placement")
        lineage: list[ArmLineageStep] = []
        for lineage_value in _required_list(
            item.get("arm_lineage"), "StoryPlan placement arm lineage"
        ):
            step = _required_dict(lineage_value, "StoryPlan arm lineage step")
            _exact_keys(step, _ARM_LINEAGE_FIELDS, "StoryPlan arm lineage step")
            lineage.append(
                ArmLineageStep(
                    choice_key=_required_str(
                        step.get("choice_key"), "StoryPlan lineage choice key"
                    ),
                    arm_order=_required_int(
                        step.get("arm_order"), "StoryPlan lineage arm order"
                    ),
                )
            )
        placements.append(
            StoryPlacement(
                id=_required_str(item.get("id"), "StoryPlan placement id"),
                scope_id=_required_str(
                    item.get("scope_id"), "StoryPlan placement scope id"
                ),
                ordinal=_required_int(
                    item.get("ordinal"), "StoryPlan placement ordinal"
                ),
                role=PlacementRole(
                    _required_str(item.get("role"), "StoryPlan placement role")
                ),
                span_key=_required_str(
                    item.get("span_key"), "StoryPlan placement span key"
                ),
                scene_id=_required_str(
                    item.get("scene_id"), "StoryPlan placement scene id"
                ),
                context_scene_id=_required_str(
                    item.get("context_scene_id"),
                    "StoryPlan placement context scene id",
                ),
                occurrence_path=_string_tuple(
                    item.get("occurrence_path"),
                    "StoryPlan placement occurrence path",
                ),
                relative_path=_required_str(
                    item.get("relative_path"), "StoryPlan placement relative path"
                ),
                start_line=_required_int(
                    item.get("start_line"), "StoryPlan placement start line"
                ),
                end_line=_required_int(
                    item.get("end_line"), "StoryPlan placement end line"
                ),
                canonical_node_ids=_string_tuple(
                    item.get("canonical_node_ids"),
                    "StoryPlan placement canonical node ids",
                ),
                choice_keys=_string_tuple(
                    item.get("choice_keys"), "StoryPlan placement choice keys"
                ),
                arm_lineage=tuple(lineage),
                anchor_id=_required_str(
                    item.get("anchor_id"), "StoryPlan placement anchor id"
                ),
                coverage_identity=_required_str(
                    item.get("coverage_identity"),
                    "StoryPlan placement coverage identity",
                ),
                loop_ids=_string_tuple(
                    item.get("loop_ids"), "StoryPlan placement loop ids"
                ),
                terminal_node_ids=_string_tuple(
                    item.get("terminal_node_ids"),
                    "StoryPlan placement terminal node ids",
                ),
                unresolved_node_ids=_string_tuple(
                    item.get("unresolved_node_ids"),
                    "StoryPlan placement unresolved node ids",
                ),
            )
        )

    loops: list[StoryLoopMetadata] = []
    for value in _required_list(root.get("loops"), "StoryPlan loops"):
        item = _required_dict(value, "StoryPlan loop")
        _exact_keys(item, _STORY_LOOP_FIELDS, "StoryPlan loop")
        repeatable = item.get("repeatable")
        if type(repeatable) is not bool:
            raise ValueError("StoryPlan loop repeatable must be a boolean")
        loops.append(
            StoryLoopMetadata(
                id=_required_str(item.get("id"), "StoryPlan loop id"),
                loop_hub_id=_required_str(
                    item.get("loop_hub_id"), "StoryPlan loop hub id"
                ),
                repeatable=repeatable,
                scope_ids=_string_tuple(
                    item.get("scope_ids"), "StoryPlan loop scope ids"
                ),
                placement_ids=_string_tuple(
                    item.get("placement_ids"), "StoryPlan loop placement ids"
                ),
                occurrence_ids=_string_tuple(
                    item.get("occurrence_ids"), "StoryPlan loop occurrence ids"
                ),
                return_relationship_ids=_string_tuple(
                    item.get("return_relationship_ids"),
                    "StoryPlan loop return relationship ids",
                ),
                partial_order_relation_ids=_string_tuple(
                    item.get("partial_order_relation_ids"),
                    "StoryPlan loop partial order relation ids",
                ),
            )
        )

    plan = StoryPlan(
        schema=_required_str(root.get("schema"), "StoryPlan schema"),
        source_identity=_required_str(
            root.get("source_identity"), "StoryPlan source identity"
        ),
        source_generation=_required_str(
            root.get("source_generation"), "StoryPlan source generation"
        ),
        canonical_hash=_required_str(
            root.get("canonical_hash"), "StoryPlan canonical hash"
        ),
        scene_model_hash=_required_str(
            root.get("scene_model_hash"), "StoryPlan scene model hash"
        ),
        source_scope_identity=_required_str(
            root.get("source_scope_identity"), "StoryPlan source scope identity"
        ),
        source_span_keys=_string_tuple(
            root.get("source_span_keys"), "StoryPlan source span keys"
        ),
        scopes=tuple(scopes),
        placements=tuple(placements),
        loops=tuple(loops),
        source_coverage_identity=_required_str(
            root.get("source_coverage_identity"),
            "StoryPlan source coverage identity",
        ),
        placement_coverage_identity=_required_str(
            root.get("placement_coverage_identity"),
            "StoryPlan placement coverage identity",
        ),
    )
    plan.validate()
    if root.get("identity") != plan.identity:
        raise ValueError("StoryPlan identity is invalid")
    if canonical_json(root) != serialized:
        raise ValueError("StoryPlan payload must use canonical JSON bytes")
    return plan


def _serialized_bytes(payload: bytes | str) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    raise ValueError("StoryPlan payload must be UTF-8 bytes or text")


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"StoryPlan contains duplicate object key {key!r}")
        result[key] = value
    return result


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
    _trimmed(value, label)
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


def _trimmed(value: str, label: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"Story Plan {label} must be a non-empty trimmed string")


def _safe_relative_locator(value: str) -> bool:
    normalized_parts = value.replace("\\", "/").split("/")
    return (
        not PurePosixPath(value).is_absolute()
        and not PureWindowsPath(value).is_absolute()
        and all(part not in {"", ".", ".."} for part in normalized_parts)
    )


@dataclass(frozen=True)
class _ScopeSpec:
    id: str
    kind: StoryScopeKind
    chapter_id: str
    chapter_ordinal: int
    lane: PersistentLane
    parent_scope_id: str | None


@dataclass(frozen=True)
class _PlacementDraft:
    scope_id: str
    role: PlacementRole
    span: SourceSpan
    scene_id: str
    context_scene_id: str
    occurrence_path: tuple[str, ...]


def build_story_plan(
    graph: CanonicalGraph,
    *,
    scene_model: SceneModel,
    source_scope: StoryScope | None = None,
    source_identity: str | None = None,
) -> StoryPlan:
    """Build one deterministic, occurrence-aware plan from exact M10/M11 authority."""

    graph.validate()
    scene_model.validate()
    _validate_binding(graph, scene_model)
    trusted_source = adapt_story_scope(
        graph,
        source_identity=(
            source_identity
            if source_identity is not None
            else source_scope.source_identity if source_scope is not None else None
        ),
        scene_model=scene_model,
    )
    if source_scope is not None:
        _validate_source_scope(
            graph,
            source_scope,
            source_identity,
            trusted_source,
        )
    source = trusted_source

    nodes = {item.id: item for item in graph.nodes}
    atoms = {item.id: item for item in scene_model.atoms}
    scenes = {item.id: item for item in scene_model.scenes}
    lanes = {item.id: item for item in scene_model.lanes}
    occurrences = {item.id: item for item in scene_model.occurrences}
    spans = {item.key: item for item in source.spans}
    span_keys_by_node = _span_keys_by_node(source.spans)
    scope_specs = _scope_specs(scene_model, lanes)
    occurrence_callee_scenes = _occurrence_callee_scenes(
        scene_model,
        nodes,
        atoms,
        scenes,
    )
    occurrence_by_scene_atom = _occurrence_by_scene_atom(scene_model, occurrences)
    targeted_definition_scenes = {
        scene_id
        for scene_ids in occurrence_callee_scenes.values()
        for scene_id in scene_ids
    }

    drafts_by_scope: dict[str, list[_PlacementDraft]] = defaultdict(list)
    emitted_keys: set[tuple[str, tuple[str, ...], str]] = set()

    def emit_span(
        spec: _ScopeSpec,
        span_key: str,
        *,
        scene_id: str,
        context_scene_id: str,
        occurrence_path: tuple[str, ...],
        role: PlacementRole,
    ) -> None:
        identity = (spec.id, occurrence_path, span_key)
        if identity in emitted_keys:
            return
        emitted_keys.add(identity)
        drafts_by_scope[spec.id].append(
            _PlacementDraft(
                spec.id,
                role,
                spans[span_key],
                scene_id,
                context_scene_id,
                occurrence_path,
            )
        )

    def emit_scene(
        spec: _ScopeSpec,
        scene: Scene,
        *,
        context_scene_id: str,
        occurrence_path: tuple[str, ...] = (),
        role: PlacementRole = PlacementRole.SCENE,
    ) -> None:
        for atom_id in scene.atom_ids:
            atom = atoms[atom_id]
            for span_key in span_keys_by_node.get(atom.primary_node_id, ()):
                emit_span(
                    spec,
                    span_key,
                    scene_id=scene.id,
                    context_scene_id=context_scene_id,
                    occurrence_path=occurrence_path,
                    role=role,
                )
            for occurrence in occurrence_by_scene_atom.get((scene.id, atom_id), ()):
                if occurrence.id in occurrence_path:
                    continue
                child_path = (*occurrence_path, occurrence.id)
                child_role = (
                    PlacementRole.COLLAPSED_SUPPORT
                    if occurrence.collapsed
                    else PlacementRole.CALL_OCCURRENCE
                )
                for callee_scene_id in occurrence_callee_scenes.get(occurrence.id, ()):
                    emit_scene(
                        spec,
                        scenes[callee_scene_id],
                        context_scene_id=context_scene_id,
                        occurrence_path=child_path,
                        role=child_role,
                    )

    chapter_by_id = {item.id: item for item in scene_model.chapters}
    for spec in scope_specs:
        chapter = chapter_by_id[spec.chapter_id]
        for scene_id in chapter.scene_ids:
            scene = scenes[scene_id]
            if scene.lane_id != spec.lane.id:
                continue
            if scene.definition_only and scene.id in targeted_definition_scenes:
                continue
            emit_scene(spec, scene, context_scene_id=scene.id)

    _emit_unowned_spans(
        source.spans,
        scope_specs,
        drafts_by_scope,
        emitted_keys,
    )
    placements = _finalize_placements(
        source.source_generation,
        scope_specs,
        drafts_by_scope,
        scenes,
        atoms,
        nodes,
    )
    loops, placements = _bind_loops(scene_model, placements)
    placement_by_id = {item.id: item for item in placements}
    scope_placement_ids: dict[str, tuple[str, ...]] = {
        spec.id: tuple(item.id for item in placements if item.scope_id == spec.id)
        for spec in scope_specs
    }
    children_by_scope: dict[str, list[str]] = defaultdict(list)
    for spec in scope_specs:
        if spec.parent_scope_id is not None:
            children_by_scope[spec.parent_scope_id].append(spec.id)

    descriptors: list[StoryScopeDescriptor] = []
    for spec in scope_specs:
        split_anchor = _split_anchor(
            spec,
            atoms,
            placement_by_id,
            scope_placement_ids,
        )
        descriptors.append(
            StoryScopeDescriptor(
                id=spec.id,
                kind=spec.kind,
                chapter_id=spec.chapter_id,
                chapter_ordinal=spec.chapter_ordinal,
                lane_id=spec.lane.id,
                lane_kind=spec.lane.kind,
                parent_scope_id=spec.parent_scope_id,
                canonical_region_id=spec.lane.canonical_region_id,
                arm_ordinal=spec.lane.arm_ordinal,
                split_anchor_id=split_anchor,
                placement_ids=scope_placement_ids[spec.id],
                child_scope_ids=tuple(children_by_scope.get(spec.id, ())),
            )
        )

    source_span_keys = tuple(sorted(spans))
    plan = StoryPlan(
        schema=STORY_PLAN_SCHEMA,
        source_identity=source.source_identity,
        source_generation=source.source_generation,
        canonical_hash=source.canonical_hash,
        scene_model_hash=scene_model.structural_hash,
        source_scope_identity=canonical_hash(asdict(source)),
        source_span_keys=source_span_keys,
        scopes=tuple(descriptors),
        placements=placements,
        loops=loops,
        source_coverage_identity=canonical_hash(source_span_keys),
        placement_coverage_identity=canonical_hash(
            tuple(item.coverage_identity for item in placements)
        ),
    )
    plan.validate()
    return plan


def _validate_binding(graph: CanonicalGraph, scene_model: SceneModel) -> None:
    if (
        scene_model.binding.source_generation != graph.source_generation
        or scene_model.binding.canonical_hash != graph.authority_hash
    ):
        raise SourceAdaptationError("M11 scene binding does not match M10 authority")


def _validate_source_scope(
    graph: CanonicalGraph,
    source: StoryScope,
    source_identity: str | None,
    trusted_source: StoryScope,
) -> None:
    if (
        source.source_generation != graph.source_generation
        or source.canonical_hash != graph.authority_hash
    ):
        raise SourceAdaptationError("StoryScope does not match M10 authority")
    if source_identity is not None and source.source_identity != source_identity:
        raise SourceAdaptationError("StoryScope source identity does not match the request")
    if canonical_json(asdict(source)) != canonical_json(asdict(trusted_source)):
        raise SourceAdaptationError(
            "StoryScope does not match the exact graph-derived StoryScope"
        )


def _scope_specs(
    scene_model: SceneModel,
    lanes: Mapping[str, PersistentLane],
) -> tuple[_ScopeSpec, ...]:
    provisional: list[tuple[Chapter, PersistentLane]] = []
    scenes = {item.id: item for item in scene_model.scenes}
    for chapter in sorted(scene_model.chapters, key=lambda item: (item.ordinal, item.id)):
        chapter_scene_ids = set(chapter.scene_ids)
        chapter_lanes = [
            lanes[lane_id]
            for lane_id in chapter.lane_ids
            if lane_id in lanes
            and chapter_scene_ids.intersection(lanes[lane_id].scene_ids)
        ]
        lane_order = {lane.id: index for index, lane in enumerate(chapter_lanes)}

        def lane_depth(lane: PersistentLane) -> int:
            depth = 0
            parent_id = lane.parent_lane_id
            seen: set[str] = set()
            while parent_id is not None and parent_id not in seen:
                seen.add(parent_id)
                parent = lanes.get(parent_id)
                if parent is None:
                    break
                depth += 1
                parent_id = parent.parent_lane_id
            return depth

        chapter_lanes.sort(
            key=lambda lane: (
                lane_depth(lane),
                lane_order.get(lane.id, len(lane_order)),
                lane.arm_ordinal if lane.arm_ordinal is not None else -1,
                lane.id,
            )
        )
        provisional.extend((chapter, lane) for lane in chapter_lanes)

    ids = {
        (chapter.id, lane.id): "story_scope_"
        + canonical_hash(
            {
                "schema": STORY_PLAN_SCHEMA,
                "source_generation": scene_model.binding.source_generation,
                "chapter_id": chapter.id,
                "lane_id": lane.id,
            }
        )[:20]
        for chapter, lane in provisional
    }
    specs: list[_ScopeSpec] = []
    for chapter, lane in provisional:
        parent_scope_id = None
        if lane.parent_lane_id is not None:
            parent_scope_id = ids.get((chapter.id, lane.parent_lane_id))
            if parent_scope_id is None:
                split_scene = next(
                    (
                        scene
                        for scene in scenes.values()
                        if lane.split_atom_id in scene.atom_ids
                    ),
                    None,
                )
                if split_scene is not None:
                    parent_scope_id = ids.get(
                        (split_scene.chapter_id, lane.parent_lane_id)
                    )
        kind = (
            StoryScopeKind.CHAPTER_SPINE
            if lane.kind is LaneKind.SPINE
            else StoryScopeKind.PERSISTENT_LANE
        )
        if kind is StoryScopeKind.PERSISTENT_LANE and parent_scope_id is None:
            raise SourceAdaptationError(
                f"persistent lane {lane.id} has no chapter-scoped parent"
            )
        specs.append(
            _ScopeSpec(
                ids[(chapter.id, lane.id)],
                kind,
                chapter.id,
                chapter.ordinal,
                lane,
                parent_scope_id,
            )
        )
    return tuple(specs)


def _span_keys_by_node(spans: Sequence[SourceSpan]) -> dict[str, tuple[str, ...]]:
    span_by_key = {span.key: span for span in spans}
    result: dict[str, list[str]] = defaultdict(list)
    for span in spans:
        for node_id in span.canonical_node_ids:
            result[node_id].append(span.key)
    return {
        node_id: tuple(
            sorted(
                keys,
                key=lambda key: (
                    span_by_key[key].relative_path,
                    span_by_key[key].start_line,
                    span_by_key[key].end_line,
                    key,
                ),
            )
        )
        for node_id, keys in result.items()
    }


def _occurrence_by_scene_atom(
    scene_model: SceneModel,
    occurrences: Mapping[str, CallSiteOccurrence],
) -> dict[tuple[str, str], tuple[CallSiteOccurrence, ...]]:
    result: dict[tuple[str, str], list[CallSiteOccurrence]] = defaultdict(list)
    for occurrence in occurrences.values():
        result[(occurrence.scene_id, occurrence.call_atom_id)].append(occurrence)
    return {
        key: tuple(sorted(values, key=lambda item: item.id))
        for key, values in result.items()
    }


def _occurrence_callee_scenes(
    scene_model: SceneModel,
    nodes: Mapping[str, CanonicalNode],
    atoms: Mapping[str, StoryAtom],
    scenes: Mapping[str, Scene],
) -> dict[str, tuple[str, ...]]:
    scene_by_atom = {
        atom_id: scene.id for scene in scenes.values() for atom_id in scene.atom_ids
    }
    definition_by_label: dict[str, set[str]] = defaultdict(set)
    for scene in scenes.values():
        if not scene.definition_only:
            continue
        for atom_id in scene.atom_ids:
            node = nodes.get(atoms[atom_id].primary_node_id)
            if node is not None and node.label:
                definition_by_label[node.label].add(scene.id)

    result: dict[str, tuple[str, ...]] = {}
    scene_rank = {scene.id: scene.ordinal for scene in scenes.values()}
    for occurrence in scene_model.occurrences:
        target = nodes.get(occurrence.callee_entry_node_id)
        scene_ids = set(definition_by_label.get(target.label if target else "", ()))
        scene_ids.update(
            scene_by_atom[atom_id]
            for atom_id in occurrence.referenced_atom_ids
            if atom_id in scene_by_atom
        )
        result[occurrence.id] = tuple(
            sorted(scene_ids, key=lambda item: (scene_rank.get(item, 0), item))
        )
    return result


def _emit_unowned_spans(
    spans: Sequence[SourceSpan],
    scope_specs: Sequence[_ScopeSpec],
    drafts_by_scope: dict[str, list[_PlacementDraft]],
    emitted_keys: set[tuple[str, tuple[str, ...], str]],
) -> None:
    covered_span_keys = {key for _scope, _path, key in emitted_keys}
    if not scope_specs:
        raise SourceAdaptationError("M11 hierarchy contains no plan scope")
    for span in spans:
        if span.key in covered_span_keys:
            continue
        candidates = [
            draft
            for drafts in drafts_by_scope.values()
            for draft in drafts
            if draft.span.arm_lineage == span.arm_lineage
        ]
        if not candidates and span.choice_keys:
            candidates = [
                draft
                for drafts in drafts_by_scope.values()
                for draft in drafts
                if set(draft.span.choice_keys).intersection(span.choice_keys)
            ]
        if candidates:
            owner = min(
                candidates,
                key=lambda item: (
                    item.span.relative_path != span.relative_path,
                    abs(item.span.start_line - span.start_line),
                    item.span.start_line,
                    item.span.key,
                ),
            )
            spec_id = owner.scope_id
            scene_id = owner.scene_id
            context_scene_id = owner.context_scene_id
            occurrence_path = owner.occurrence_path
        else:
            spec_id = scope_specs[0].id
            first = drafts_by_scope.get(spec_id, [])
            scene_id = first[-1].scene_id if first else "m11_unowned_support"
            context_scene_id = (
                first[-1].context_scene_id if first else "m11_unowned_support"
            )
            occurrence_path = ()
        identity = (spec_id, occurrence_path, span.key)
        emitted_keys.add(identity)
        drafts_by_scope[spec_id].append(
            _PlacementDraft(
                spec_id,
                PlacementRole.COLLAPSED_SUPPORT,
                span,
                scene_id,
                context_scene_id,
                occurrence_path,
            )
        )
        covered_span_keys.add(span.key)


def _finalize_placements(
    source_generation: str,
    scope_specs: Sequence[_ScopeSpec],
    drafts_by_scope: Mapping[str, Sequence[_PlacementDraft]],
    scenes: Mapping[str, Scene],
    atoms: Mapping[str, StoryAtom],
    nodes: Mapping[str, CanonicalNode],
) -> tuple[StoryPlacement, ...]:
    terminal_by_scene: dict[str, tuple[str, ...]] = {}
    unresolved_by_scene: dict[str, tuple[str, ...]] = {}
    for scene in scenes.values():
        scene_node_ids = tuple(atoms[item].primary_node_id for item in scene.atom_ids)
        terminal_by_scene[scene.id] = tuple(
            item
            for item in scene_node_ids
            if item in nodes and nodes[item].kind is CanonicalNodeKind.TERMINAL
        )
        unresolved_by_scene[scene.id] = tuple(
            item
            for item in scene_node_ids
            if item in nodes and nodes[item].kind is CanonicalNodeKind.UNRESOLVED
        )

    result: list[StoryPlacement] = []
    for spec in scope_specs:
        for ordinal, draft in enumerate(drafts_by_scope.get(spec.id, ())):
            span = draft.span
            terminal_ids = tuple(
                dict.fromkeys(
                    (
                        *terminal_by_scene.get(draft.scene_id, ()),
                        *(
                            item
                            for item in span.canonical_node_ids
                            if item in nodes
                            and nodes[item].kind is CanonicalNodeKind.TERMINAL
                        ),
                    )
                )
            )
            unresolved_ids = tuple(
                dict.fromkeys(
                    (
                        *unresolved_by_scene.get(draft.scene_id, ()),
                        *(
                            item
                            for item in span.canonical_node_ids
                            if item in nodes
                            and nodes[item].kind is CanonicalNodeKind.UNRESOLVED
                        ),
                        *(
                            span.canonical_node_ids
                            if span.reachability is Reachability.UNRESOLVED
                            else ()
                        ),
                    )
                )
            )
            identity_value = {
                "schema": STORY_PLAN_SCHEMA,
                "scope_id": spec.id,
                "scene_id": draft.scene_id,
                "context_scene_id": draft.context_scene_id,
                "occurrence_path": draft.occurrence_path,
                "span_key": span.key,
                "canonical_node_ids": span.canonical_node_ids,
                "choice_keys": span.choice_keys,
                "arm_lineage": tuple(asdict(item) for item in span.arm_lineage),
            }
            placement_id = "story_placement_" + canonical_hash(identity_value)[:20]
            anchor_id = "story_anchor_" + canonical_hash(
                {**identity_value, "anchor_contract": "phase04-v1"}
            )[:20]
            coverage_identity = canonical_hash(
                {
                    "source_generation": source_generation,
                    "scope_id": spec.id,
                    "span_key": span.key,
                    "occurrence_path": draft.occurrence_path,
                }
            )
            result.append(
                StoryPlacement(
                    id=placement_id,
                    scope_id=spec.id,
                    ordinal=ordinal,
                    role=draft.role,
                    span_key=span.key,
                    scene_id=draft.scene_id,
                    context_scene_id=draft.context_scene_id,
                    occurrence_path=draft.occurrence_path,
                    relative_path=span.relative_path,
                    start_line=span.start_line,
                    end_line=span.end_line,
                    canonical_node_ids=span.canonical_node_ids,
                    choice_keys=span.choice_keys,
                    arm_lineage=span.arm_lineage,
                    anchor_id=anchor_id,
                    coverage_identity=coverage_identity,
                    loop_ids=(),
                    terminal_node_ids=terminal_ids,
                    unresolved_node_ids=unresolved_ids,
                )
            )
    return tuple(result)


def _bind_loops(
    scene_model: SceneModel,
    placements: tuple[StoryPlacement, ...],
) -> tuple[tuple[StoryLoopMetadata, ...], tuple[StoryPlacement, ...]]:
    loops_by_placement: dict[str, list[str]] = defaultdict(list)
    loops: list[StoryLoopMetadata] = []
    for hub in sorted(scene_model.loop_hubs, key=lambda item: item.id):
        placement_ids = tuple(
            placement.id
            for placement in placements
            if placement.scene_id in hub.scene_ids
            or set(placement.occurrence_path).intersection(hub.occurrence_ids)
        )
        loop_id = "story_loop_" + canonical_hash(
            {
                "schema": STORY_PLAN_SCHEMA,
                "loop_hub_id": hub.id,
                "placement_ids": placement_ids,
            }
        )[:20]
        for placement_id in placement_ids:
            loops_by_placement[placement_id].append(loop_id)
        placement_id_set = set(placement_ids)
        loops.append(
            StoryLoopMetadata(
                id=loop_id,
                loop_hub_id=hub.id,
                repeatable=True,
                scope_ids=tuple(
                    dict.fromkeys(
                        placement.scope_id
                        for placement in placements
                        if placement.id in placement_id_set
                    )
                ),
                placement_ids=placement_ids,
                occurrence_ids=hub.occurrence_ids,
                return_relationship_ids=tuple(
                    item.id for item in hub.return_relationships
                ),
                partial_order_relation_ids=tuple(
                    item.id for item in hub.partial_order
                ),
            )
        )
    return tuple(loops), tuple(
        replace(item, loop_ids=tuple(loops_by_placement.get(item.id, ())))
        for item in placements
    )


def _split_anchor(
    spec: _ScopeSpec,
    atoms: Mapping[str, StoryAtom],
    placements: Mapping[str, StoryPlacement],
    scope_placement_ids: Mapping[str, tuple[str, ...]],
) -> str | None:
    if spec.kind is StoryScopeKind.CHAPTER_SPINE:
        return None
    if spec.lane.split_atom_id is None or spec.parent_scope_id is None:
        raise SourceAdaptationError(f"persistent lane {spec.lane.id} lacks a split atom")
    split_atom = atoms[spec.lane.split_atom_id]
    candidates = [
        placements[item]
        for item in scope_placement_ids.get(spec.parent_scope_id, ())
        if split_atom.primary_node_id in placements[item].canonical_node_ids
    ]
    if not candidates:
        raise SourceAdaptationError(
            f"persistent lane {spec.lane.id} has no parent split placement"
        )
    return min(candidates, key=lambda item: item.ordinal).anchor_id


def _unique_records[T](items: Sequence[T], label: str) -> dict[str, T]:
    result: dict[str, T] = {}
    for item in items:
        identity = getattr(item, "id", None)
        if not isinstance(identity, str) or not identity:
            raise ValueError(f"Story Plan {label} identity is invalid")
        if identity in result:
            raise ValueError(f"Story Plan {label} {identity} repeats")
        result[identity] = item
    return result
