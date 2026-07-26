"""Exact provider-free adapter from A1 StoryPlan authority to A2 chunk material."""

from __future__ import annotations

from dataclasses import asdict

from renpy_story_mapper.story_map_v2.contracts import (
    ChoiceMechanic,
    SourceSpan,
    StoryScope,
    canonical_hash,
    canonical_json,
)
from renpy_story_mapper.story_map_v2.phase04_chunk_plan import (
    ChoiceArmBoundary,
    ChunkPlanningChoice,
    ChunkPlanningPlacement,
    ChunkPlanningProjection,
    ChunkPlanningScope,
)
from renpy_story_mapper.story_map_v2.story_plan import (
    StoryPlacement,
    StoryPlan,
    StoryScopeDescriptor,
    StoryScopeKind,
)


class ChunkPlanningAdaptationError(ValueError):
    """StoryPlan and exact StoryScope material cannot be safely joined."""


def atomic_group_identity(placement: StoryPlacement, group_ordinal: int) -> str:
    """Bind one contiguous scope/scene/call-occurrence run to one atomic group."""

    if group_ordinal < 1:
        raise ValueError("atomic group ordinal must be positive")

    return "atomic_group_" + canonical_hash(
        {
            "contract": "story-map-v2-phase04-atomic-group-v1",
            "scope_id": placement.scope_id,
            "scene_id": placement.scene_id,
            "context_scene_id": placement.context_scene_id,
            "occurrence_path": placement.occurrence_path,
            "group_ordinal": group_ordinal,
        }
    )[:24]


def _validate_identities(story_plan: StoryPlan, source_scope: StoryScope) -> None:
    try:
        story_plan.validate()
    except ValueError as exc:
        raise ChunkPlanningAdaptationError("StoryPlan validation failed") from exc
    if story_plan.source_identity != source_scope.source_identity:
        raise ChunkPlanningAdaptationError("StoryPlan source identity does not match StoryScope")
    if story_plan.source_generation != source_scope.source_generation:
        raise ChunkPlanningAdaptationError(
            "StoryPlan source generation does not match StoryScope"
        )
    if story_plan.canonical_hash != source_scope.canonical_hash:
        raise ChunkPlanningAdaptationError(
            "StoryPlan canonical authority does not match StoryScope"
        )
    span_keys = tuple(sorted(span.key for span in source_scope.spans))
    if span_keys != story_plan.source_span_keys:
        raise ChunkPlanningAdaptationError(
            "StoryScope has missing or extra spans for the exact StoryPlan"
        )
    if story_plan.source_scope_identity != canonical_hash(asdict(source_scope)):
        raise ChunkPlanningAdaptationError("StoryScope identity has drifted from StoryPlan")


def _validate_placement_span(placement: StoryPlacement, span: SourceSpan) -> None:
    if (
        placement.span_key != span.key
        or placement.relative_path != span.relative_path
        or placement.start_line != span.start_line
        or placement.end_line != span.end_line
        or placement.canonical_node_ids != span.canonical_node_ids
        or placement.choice_keys != span.choice_keys
        or placement.arm_lineage != span.arm_lineage
    ):
        raise ChunkPlanningAdaptationError(
            f"StoryPlacement {placement.id!r} has drifted from exact span {span.key!r}"
        )


def _persistent_choice_keys(
    scope: StoryScopeDescriptor,
    placements_by_anchor: dict[str, StoryPlacement],
) -> frozenset[str]:
    if scope.kind is not StoryScopeKind.PERSISTENT_LANE:
        return frozenset()
    if scope.split_anchor_id is None:
        raise ChunkPlanningAdaptationError(
            f"persistent scope {scope.id!r} has no exact split anchor"
        )
    split = placements_by_anchor.get(scope.split_anchor_id)
    if split is None:
        raise ChunkPlanningAdaptationError(
            f"persistent scope {scope.id!r} has an unknown split anchor"
        )
    return frozenset(split.choice_keys)


def _choice_boundaries(
    placement: StoryPlacement,
    scope: StoryScopeDescriptor,
    choices_by_key: dict[str, ChoiceMechanic],
    persistent_choice_keys: frozenset[str],
) -> tuple[ChoiceArmBoundary, ...]:
    result: list[ChoiceArmBoundary] = []
    for depth, step in enumerate(placement.arm_lineage):
        choice = choices_by_key.get(step.choice_key)
        if choice is None:
            raise ChunkPlanningAdaptationError(
                f"StoryPlacement {placement.id!r} references unknown choice mechanics"
            )
        if not any(arm.order == step.arm_order for arm in choice.arms):
            raise ChunkPlanningAdaptationError(
                f"StoryPlacement {placement.id!r} references unknown choice arm"
            )
        persistent_arm_order = (
            scope.arm_ordinal + 1 if scope.arm_ordinal is not None else None
        )
        if (
            step.choice_key in persistent_choice_keys
            and step.arm_order == persistent_arm_order
        ):
            boundary_kind = "persistent"
        elif depth > 0:
            boundary_kind = "nested"
        else:
            boundary_kind = "local"
        result.append(
            ChoiceArmBoundary(
                choice_key=step.choice_key,
                arm_order=step.arm_order,
                boundary_kind=boundary_kind,
                depth=depth,
            )
        )
    return tuple(result)


def _structural_flags(
    placement: StoryPlacement,
    scope: StoryScopeDescriptor,
) -> tuple[str, ...]:
    flags: list[str] = []
    if scope.kind is StoryScopeKind.PERSISTENT_LANE:
        flags.append("persistent_lane")
    if placement.loop_ids:
        flags.append("loop")
    if placement.terminal_node_ids:
        flags.append("terminal")
    if placement.unresolved_node_ids:
        flags.append("unresolved")
    return tuple(flags)


def _planning_choices(source_scope: StoryScope) -> tuple[ChunkPlanningChoice, ...]:
    return tuple(
        ChunkPlanningChoice(
            choice_key=choice.key,
            canonical_mechanics=canonical_json(asdict(choice)).decode("utf-8"),
            arm_orders=tuple(arm.order for arm in choice.arms),
        )
        for choice in source_scope.choices
    )


def adapt_chunk_planning_projection(
    story_plan: StoryPlan,
    source_scope: StoryScope,
) -> ChunkPlanningProjection:
    """Join exact A1 placement IDs to exact source spans without deriving new authority."""

    _validate_identities(story_plan, source_scope)
    spans_by_key = {span.key: span for span in source_scope.spans}
    placements_by_id = {placement.id: placement for placement in story_plan.placements}
    placements_by_anchor = {
        placement.anchor_id: placement for placement in story_plan.placements
    }
    choices_by_key = {choice.key: choice for choice in source_scope.choices}
    scopes: list[ChunkPlanningScope] = []
    emitted_placement_ids: list[str] = []
    for ordinal, scope in enumerate(story_plan.scopes, start=1):
        persistent_choice_keys = _persistent_choice_keys(scope, placements_by_anchor)
        placements: list[ChunkPlanningPlacement] = []
        current_group_key: tuple[str, str, tuple[str, ...]] | None = None
        atomic_group_ordinal = 0
        for placement_id in scope.placement_ids:
            placement = placements_by_id.get(placement_id)
            if placement is None:
                raise ChunkPlanningAdaptationError(
                    f"scope {scope.id!r} references a missing StoryPlacement"
                )
            span = spans_by_key.get(placement.span_key)
            if span is None:
                raise ChunkPlanningAdaptationError(
                    f"StoryPlacement {placement.id!r} references a missing exact span"
                )
            _validate_placement_span(placement, span)
            group_key = (
                placement.scene_id,
                placement.context_scene_id,
                placement.occurrence_path,
            )
            if group_key != current_group_key:
                atomic_group_ordinal += 1
                current_group_key = group_key
            placements.append(
                ChunkPlanningPlacement(
                    placement_id=placement.id,
                    scope_id=scope.id,
                    scene_id=placement.scene_id,
                    relative_path=span.relative_path,
                    start_line=span.start_line,
                    end_line=span.end_line,
                    raw_text=span.raw_text,
                    raw_tokens=span.estimated_tokens,
                    atomic_group_id=atomic_group_identity(
                        placement,
                        atomic_group_ordinal,
                    ),
                    choice_arms=_choice_boundaries(
                        placement,
                        scope,
                        choices_by_key,
                        persistent_choice_keys,
                    ),
                    structural_flags=_structural_flags(placement, scope),
                )
            )
            emitted_placement_ids.append(placement.id)
        scopes.append(
            ChunkPlanningScope(
                scope_id=scope.id,
                ordinal=ordinal,
                parent_scope_id=scope.parent_scope_id,
                persistent_lane=scope.kind is StoryScopeKind.PERSISTENT_LANE,
                branch_heavy=(
                    scope.kind is StoryScopeKind.PERSISTENT_LANE
                    or any(item.choice_arms for item in placements)
                ),
                chapter_ordinal=scope.chapter_ordinal,
                lane_id=scope.lane_id,
                lane_kind=scope.lane_kind.value,
                placements=tuple(placements),
            )
        )
    expected_placement_ids = tuple(
        placement_id
        for scope in story_plan.scopes
        for placement_id in scope.placement_ids
    )
    if tuple(emitted_placement_ids) != expected_placement_ids:
        raise ChunkPlanningAdaptationError(
            "adapter did not preserve every StoryPlacement ID exactly once"
        )
    return ChunkPlanningProjection(
        story_plan_identity=story_plan.identity,
        source_identity=source_scope.source_identity,
        scopes=tuple(scopes),
        choices=_planning_choices(source_scope),
    )
