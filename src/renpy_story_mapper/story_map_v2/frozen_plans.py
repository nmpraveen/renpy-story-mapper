"""Privacy-safe frozen Story Plan payloads used by durable Phase 04 resume."""

from __future__ import annotations

from dataclasses import dataclass

from renpy_story_mapper.story_map_v2.phase04_chunk_plan import (
    StoryChunkPlan,
    deserialize_story_chunk_plan,
    serialize_story_chunk_plan,
)
from renpy_story_mapper.story_map_v2.story_plan import (
    StoryPlan,
    deserialize_story_plan,
    serialize_story_plan,
)


@dataclass(frozen=True)
class FrozenPlanBundle:
    """Exact canonical plans retained without raw story packets or provider material."""

    story_plan: StoryPlan
    story_chunk_plan: StoryChunkPlan

    def __post_init__(self) -> None:
        self.story_plan.validate()
        if self.story_chunk_plan.story_plan_identity != self.story_plan.identity:
            raise ValueError("StoryChunkPlan does not bind the frozen StoryPlan")
        if self.story_chunk_plan.source_identity != self.story_plan.source_identity:
            raise ValueError("frozen Story Plan source identities do not match")

    @property
    def story_plan_bytes(self) -> bytes:
        return serialize_story_plan(self.story_plan)

    @property
    def story_chunk_plan_bytes(self) -> bytes:
        return serialize_story_chunk_plan(self.story_chunk_plan)

    @classmethod
    def from_bytes(
        cls,
        story_plan_payload: bytes | str,
        story_chunk_plan_payload: bytes | str,
    ) -> FrozenPlanBundle:
        return cls(
            deserialize_story_plan(story_plan_payload),
            deserialize_story_chunk_plan(story_chunk_plan_payload),
        )
