"""Generalized synthetic Story Map V2 fixtures with no private story content."""

from renpy_story_mapper.story_map_v2.contracts import (
    ArmLineageStep,
    ArmMechanic,
    ChoiceMechanic,
    Reachability,
    SourceSpan,
    StoryScope,
)


def arm(
    order: int,
    caption: str,
    start: int,
    end: int,
    *,
    destination: str,
    rejoin: str | None = "node:rejoin",
    rejoin_line: int | None = 40,
) -> ArmMechanic:
    return ArmMechanic(
        order=order,
        caption=caption,
        start_line=start,
        end_line=end,
        condition=None,
        effects=(f"route_{order} = True",),
        destination_id=destination,
        rejoin_node_id=rejoin,
        rejoin_line=rejoin_line,
        reachability=Reachability.REACHABLE,
    )


def choice(
    key: str = "scripts/day.rpy:10",
    *,
    parent: tuple[ArmLineageStep, ...] = (),
) -> ChoiceMechanic:
    return ChoiceMechanic(
        key=key,
        relative_path="scripts/day.rpy",
        line=10,
        arms=(
            arm(1, "Take the ridge", 11, 19, destination="node:ridge"),
            arm(2, "Take the valley", 20, 29, destination="node:valley"),
        ),
        parent_lineage=parent,
    )


def span(
    key: str,
    start: int,
    end: int,
    tokens: int,
    *,
    lineage: tuple[ArmLineageStep, ...] = (),
    choice_keys: tuple[str, ...] = (),
    boundary: bool = False,
    shared: bool = False,
) -> SourceSpan:
    return SourceSpan(
        key=key,
        relative_path="scripts/day.rpy",
        start_line=start,
        end_line=end,
        raw_text=f"{start}: synthetic story\n",
        estimated_tokens=tokens,
        canonical_node_ids=(f"node:{key}",),
        choice_keys=choice_keys,
        arm_lineage=lineage,
        natural_boundary_after=boundary,
        shared_continuation=shared,
    )


def scope(
    spans: tuple[SourceSpan, ...],
    *,
    choices: tuple[ChoiceMechanic, ...] = (),
) -> StoryScope:
    return StoryScope(
        source_identity="source-fixture-v1",
        source_generation="generation-fixture-v1",
        canonical_hash="a" * 64,
        spans=spans,
        choices=choices,
    )
