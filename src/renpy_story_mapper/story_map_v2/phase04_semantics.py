"""Strict Phase 04 mapper validation and frozen semantic assembly.

Provider output owns prose and proposed event grouping only.  This module binds every accepted
record back to one exact :class:`StoryChunkPlan`, derives event identity locally, overlays the
Python-owned choice mechanics, and fills rejected or missing chunks with structural coverage.
It never receives source text, replans chunks, or calls a provider.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from renpy_story_mapper.story_map_v2.contracts import canonical_hash, canonical_json
from renpy_story_mapper.story_map_v2.phase04_chunk_plan import (
    FrozenChoiceParent,
    FrozenScopeBinding,
    StoryChunkDescriptor,
    StoryChunkPlan,
)

PHASE04_MAPPER_RESPONSE_SCHEMA = "story-map-v2-phase04-mapper-response-v1"
PHASE04_NORMALIZED_CHUNK_SCHEMA = "story-map-v2-phase04-normalized-chunk-v1"
MAX_REPLACEMENT_REVIEW_CALLS_PER_CHUNK = 1


class SemanticValidationError(ValueError):
    """A provider or cached semantic result does not match frozen authority."""


class SemanticAssemblyError(ValueError):
    """A result set cannot be associated safely with the frozen chunk plan."""


class SemanticOrigin(StrEnum):
    AI = "ai"
    STRUCTURAL = "structural"


@dataclass(frozen=True)
class FrozenMapperJobBinding:
    """Scalar C1 view of one frozen Track B mapping job."""

    plan_id: str
    scope_id: str
    chunk_id: str
    request_sha256: str
    request_byte_count: int

    def __post_init__(self) -> None:
        for value, label in (
            (self.plan_id, "mapper plan ID"),
            (self.scope_id, "mapper scope ID"),
            (self.chunk_id, "mapper chunk ID"),
        ):
            _trimmed(value, label)
        if (
            len(self.request_sha256) != 64
            or self.request_sha256 != self.request_sha256.lower()
            or any(character not in "0123456789abcdef" for character in self.request_sha256)
        ):
            raise ValueError("mapper request SHA-256 must be a lowercase hexadecimal digest")
        if type(self.request_byte_count) is not int or self.request_byte_count < 1:
            raise ValueError("mapper request byte count must be a positive integer")


@dataclass(frozen=True)
class ValidatedSemanticResult:
    """C1 result shape adapted to Track B's workflow result by the coordinator."""

    result_identity: str
    normalized_payload: bytes
    flagged_for_review: bool = False

    def __post_init__(self) -> None:
        if (
            len(self.result_identity) != 64
            or self.result_identity != self.result_identity.lower()
            or any(character not in "0123456789abcdef" for character in self.result_identity)
        ):
            raise ValueError("validated semantic result identity must be a SHA-256 digest")
        if not self.normalized_payload:
            raise ValueError("validated semantic result payload must not be empty")
        if type(self.flagged_for_review) is not bool:
            raise ValueError("replacement-review flag must be a boolean")
        if hashlib.sha256(self.normalized_payload).hexdigest() != self.result_identity:
            raise ValueError("validated semantic result identity is invalid")


def replacement_review_allowed(
    result: ValidatedSemanticResult,
    prior_review_calls: int,
) -> bool:
    """Return the exact selective-review decision without constructing a provider."""

    if prior_review_calls not in {0, 1}:
        raise ValueError("replacement review call count must be zero or one")
    return result.flagged_for_review and prior_review_calls == 0


def _trimmed(value: str, label: str, *, maximum: int = 2_000) -> str:
    if not value or value != value.strip() or len(value) > maximum:
        raise SemanticValidationError(f"{label} must be non-empty, trimmed, and bounded")
    return value


def _duplicate_rejecting_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SemanticValidationError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def _decode(payload: bytes | str, label: str) -> dict[str, object]:
    try:
        decoded = json.loads(payload, object_pairs_hook=_duplicate_rejecting_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SemanticValidationError(f"{label} must be one UTF-8 JSON object") from exc
    if type(decoded) is not dict:
        raise SemanticValidationError(f"{label} must be one JSON object")
    return cast(dict[str, object], decoded)


def _exact(value: dict[str, object], fields: frozenset[str], label: str) -> None:
    if set(value) != fields:
        raise SemanticValidationError(f"{label} has missing or unexpected fields")


def _object(value: object, label: str) -> dict[str, object]:
    if type(value) is not dict:
        raise SemanticValidationError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _array(value: object, label: str) -> list[object]:
    if type(value) is not list:
        raise SemanticValidationError(f"{label} must be an array")
    return cast(list[object], value)


def _string(value: object, label: str, *, maximum: int = 2_000) -> str:
    if type(value) is not str:
        raise SemanticValidationError(f"{label} must be a string")
    return _trimmed(value, label, maximum=maximum)


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise SemanticValidationError(f"{label} must be a boolean")
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise SemanticValidationError(f"{label} must be a positive integer")
    return value


def _strings(
    value: object,
    label: str,
    *,
    maximum_items: int = 256,
    maximum_length: int = 200,
) -> tuple[str, ...]:
    items = _array(value, label)
    if len(items) > maximum_items:
        raise SemanticValidationError(f"{label} contains too many items")
    result = tuple(
        _string(item, f"{label}[{index}]", maximum=maximum_length)
        for index, item in enumerate(items)
    )
    if len(result) != len(set(result)):
        raise SemanticValidationError(f"{label} must not contain duplicates")
    return result


@dataclass(frozen=True)
class ExactChoiceOverlay:
    """Provider prose paired with byte-exact Python-owned mechanics."""

    choice_key: str
    arm_orders: tuple[int, ...]
    canonical_mechanics: str
    mechanics_hash: str
    summary: str

    def __post_init__(self) -> None:
        _trimmed(self.choice_key, "choice key")
        _trimmed(self.summary, "choice summary", maximum=320)
        if not self.arm_orders or any(order < 1 for order in self.arm_orders):
            raise ValueError("choice overlay requires positive arm orders")
        if len(self.arm_orders) != len(set(self.arm_orders)):
            raise ValueError("choice overlay arm orders must be unique")
        try:
            mechanics = json.loads(self.canonical_mechanics)
        except json.JSONDecodeError as exc:
            raise ValueError("choice overlay mechanics must be JSON") from exc
        if canonical_hash(mechanics) != self.mechanics_hash:
            raise ValueError("choice overlay mechanics hash is invalid")


@dataclass(frozen=True)
class SemanticEvent:
    event_id: str
    scope_id: str
    route_owner: str
    placement_ids: tuple[str, ...]
    title: str
    summary: str
    characters: tuple[str, ...]
    structural_flags: tuple[str, ...]
    origin: SemanticOrigin

    def __post_init__(self) -> None:
        for value, label in (
            (self.event_id, "event ID"),
            (self.scope_id, "event scope ID"),
            (self.route_owner, "event route owner"),
            (self.title, "event title"),
            (self.summary, "event summary"),
        ):
            _trimmed(value, label, maximum=320)
        if not self.placement_ids or len(self.placement_ids) != len(set(self.placement_ids)):
            raise ValueError("event placement coverage must be non-empty and unique")
        if len(self.characters) != len(set(self.characters)):
            raise ValueError("event characters must be unique")
        if len(self.structural_flags) != len(set(self.structural_flags)):
            raise ValueError("event structural flags must be unique")


@dataclass(frozen=True)
class SemanticChunk:
    story_chunk_plan_identity: str
    chunk_id: str
    request_hash: str | None
    scope_id: str
    route_owner: str
    title: str
    overview: str
    events: tuple[SemanticEvent, ...]
    choices: tuple[ExactChoiceOverlay, ...]
    origin: SemanticOrigin
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.story_chunk_plan_identity, "StoryChunkPlan identity"),
            (self.chunk_id, "chunk ID"),
            (self.scope_id, "chunk scope ID"),
            (self.route_owner, "chunk route owner"),
            (self.title, "chunk title"),
            (self.overview, "chunk overview"),
        ):
            _trimmed(value, label, maximum=600)
        if not self.events:
            raise ValueError("semantic chunk requires events")
        if self.origin is SemanticOrigin.AI:
            if self.request_hash is None or self.rejection_reason is not None:
                raise ValueError("accepted AI chunks require a request hash and no rejection")
        elif self.rejection_reason is None:
            raise ValueError("structural chunks require a rejection/fallback reason")


@dataclass(frozen=True)
class SemanticAssembly:
    story_chunk_plan_identity: str
    source_identity: str
    coverage_hash: str
    chunks: tuple[SemanticChunk, ...]

    @property
    def events(self) -> tuple[SemanticEvent, ...]:
        return tuple(event for chunk in self.chunks for event in chunk.events)


def _event_identity(plan_identity: str, placement_ids: tuple[str, ...]) -> str:
    digest = canonical_hash({"plan": plan_identity, "placements": list(placement_ids)})
    return f"event:{digest[:32]}"


def _scope_binding(plan: StoryChunkPlan, scope_id: str) -> FrozenScopeBinding:
    binding = next((item for item in plan.scope_bindings if item.scope_id == scope_id), None)
    if binding is None:
        raise SemanticValidationError("chunk references an unknown frozen scope")
    return binding


def _choice_parent(plan: StoryChunkPlan, key: str) -> FrozenChoiceParent:
    parent = next((item for item in plan.choice_parents if item.choice_key == key), None)
    if parent is None:
        raise SemanticValidationError("response references foreign choice mechanics")
    return parent


def _normalized_chunk_object(chunk: SemanticChunk) -> dict[str, object]:
    return {
        "schema": PHASE04_NORMALIZED_CHUNK_SCHEMA,
        "story_chunk_plan_identity": chunk.story_chunk_plan_identity,
        "chunk_id": chunk.chunk_id,
        "request_hash": chunk.request_hash,
        "scope_id": chunk.scope_id,
        "route_owner": chunk.route_owner,
        "title": chunk.title,
        "overview": chunk.overview,
        "origin": chunk.origin.value,
        "rejection_reason": chunk.rejection_reason,
        "events": [
            {
                "event_id": event.event_id,
                "scope_id": event.scope_id,
                "route_owner": event.route_owner,
                "placement_ids": list(event.placement_ids),
                "title": event.title,
                "summary": event.summary,
                "characters": list(event.characters),
                "structural_flags": list(event.structural_flags),
                "origin": event.origin.value,
            }
            for event in chunk.events
        ],
        "choices": [
            {
                "choice_key": choice.choice_key,
                "arm_orders": list(choice.arm_orders),
                "canonical_mechanics": choice.canonical_mechanics,
                "mechanics_hash": choice.mechanics_hash,
                "summary": choice.summary,
            }
            for choice in chunk.choices
        ],
    }


def serialize_semantic_chunk(chunk: SemanticChunk) -> bytes:
    return canonical_json(_normalized_chunk_object(chunk))


def deserialize_semantic_chunk(payload: bytes | str) -> SemanticChunk:
    value = _decode(payload, "normalized semantic chunk")
    _exact(
        value,
        frozenset(
            {
                "schema",
                "story_chunk_plan_identity",
                "chunk_id",
                "request_hash",
                "scope_id",
                "route_owner",
                "title",
                "overview",
                "origin",
                "rejection_reason",
                "events",
                "choices",
            }
        ),
        "normalized semantic chunk",
    )
    if value["schema"] != PHASE04_NORMALIZED_CHUNK_SCHEMA:
        raise SemanticValidationError("unsupported normalized semantic chunk schema")
    origin_text = _string(value["origin"], "semantic chunk origin", maximum=20)
    try:
        origin = SemanticOrigin(origin_text)
    except ValueError as exc:
        raise SemanticValidationError("invalid semantic chunk origin") from exc
    request_hash = value["request_hash"]
    if request_hash is not None and type(request_hash) is not str:
        raise SemanticValidationError("request hash must be a string or null")
    rejection = value["rejection_reason"]
    if rejection is not None and type(rejection) is not str:
        raise SemanticValidationError("rejection reason must be a string or null")

    events: list[SemanticEvent] = []
    for index, raw in enumerate(_array(value["events"], "semantic events")):
        event = _object(raw, f"semantic events[{index}]")
        _exact(
            event,
            frozenset(
                {
                    "event_id",
                    "scope_id",
                    "route_owner",
                    "placement_ids",
                    "title",
                    "summary",
                    "characters",
                    "structural_flags",
                    "origin",
                }
            ),
            f"semantic events[{index}]",
        )
        event_origin_text = _string(event["origin"], "event origin", maximum=20)
        try:
            event_origin = SemanticOrigin(event_origin_text)
        except ValueError as exc:
            raise SemanticValidationError("invalid semantic event origin") from exc
        events.append(
            SemanticEvent(
                event_id=_string(event["event_id"], "event ID"),
                scope_id=_string(event["scope_id"], "event scope ID"),
                route_owner=_string(event["route_owner"], "event route owner"),
                placement_ids=_strings(event["placement_ids"], "event placements"),
                title=_string(event["title"], "event title", maximum=80),
                summary=_string(event["summary"], "event summary", maximum=320),
                characters=_strings(
                    event["characters"], "event characters", maximum_items=16, maximum_length=80
                ),
                structural_flags=_strings(
                    event["structural_flags"], "event structural flags", maximum_items=64
                ),
                origin=event_origin,
            )
        )

    choices: list[ExactChoiceOverlay] = []
    for index, raw in enumerate(_array(value["choices"], "semantic choices")):
        choice = _object(raw, f"semantic choices[{index}]")
        _exact(
            choice,
            frozenset(
                {
                    "choice_key",
                    "arm_orders",
                    "canonical_mechanics",
                    "mechanics_hash",
                    "summary",
                }
            ),
            f"semantic choices[{index}]",
        )
        choices.append(
            ExactChoiceOverlay(
                choice_key=_string(choice["choice_key"], "choice key"),
                arm_orders=tuple(
                    _integer(item, "choice arm order")
                    for item in _array(choice["arm_orders"], "choice arm orders")
                ),
                canonical_mechanics=_string(
                    choice["canonical_mechanics"], "canonical mechanics", maximum=20_000
                ),
                mechanics_hash=_string(choice["mechanics_hash"], "mechanics hash", maximum=64),
                summary=_string(choice["summary"], "choice summary", maximum=320),
            )
        )
    return SemanticChunk(
        story_chunk_plan_identity=_string(
            value["story_chunk_plan_identity"], "StoryChunkPlan identity"
        ),
        chunk_id=_string(value["chunk_id"], "chunk ID"),
        request_hash=request_hash,
        scope_id=_string(value["scope_id"], "scope ID"),
        route_owner=_string(value["route_owner"], "route owner"),
        title=_string(value["title"], "chunk title", maximum=80),
        overview=_string(value["overview"], "chunk overview", maximum=600),
        events=tuple(events),
        choices=tuple(choices),
        origin=origin,
        rejection_reason=rejection,
    )


class Phase04MapperResponseValidator:
    """Workflow validator for one exact frozen :class:`StoryChunkPlan`."""

    def __init__(self, plan: StoryChunkPlan) -> None:
        self._plan = plan
        self._chunks = {chunk.chunk_id: chunk for chunk in plan.chunks}

    def validate(
        self,
        job: FrozenMapperJobBinding,
        payload: bytes,
        *,
        cached: bool,
    ) -> ValidatedSemanticResult:
        descriptor = self._chunks.get(job.chunk_id)
        if descriptor is None or descriptor.structural_fallback_only:
            raise SemanticValidationError("workflow job is not provider-eligible")
        if (
            job.plan_id != self._plan.identity
            or job.scope_id != descriptor.scope_id
            or job.request_sha256 != descriptor.request_hash
            or job.request_byte_count != descriptor.serialized_request_bytes
        ):
            raise SemanticValidationError("workflow job differs from the frozen chunk plan")
        if cached:
            chunk = deserialize_semantic_chunk(payload)
            self._validate_normalized_binding(chunk, descriptor)
            normalized = serialize_semantic_chunk(chunk)
            return ValidatedSemanticResult(hashlib.sha256(normalized).hexdigest(), normalized)
        chunk, review_requested = self._validate_provider_payload(descriptor, payload)
        normalized = serialize_semantic_chunk(chunk)
        return ValidatedSemanticResult(
            hashlib.sha256(normalized).hexdigest(),
            normalized,
            flagged_for_review=review_requested,
        )

    def _validate_provider_payload(
        self,
        descriptor: StoryChunkDescriptor,
        payload: bytes,
    ) -> tuple[SemanticChunk, bool]:
        value = _decode(payload, "mapper response")
        _exact(
            value,
            frozenset(
                {
                    "schema",
                    "story_chunk_plan_identity",
                    "chunk_id",
                    "request_hash",
                    "scope_id",
                    "title",
                    "overview",
                    "review_requested",
                    "events",
                    "branch_summaries",
                }
            ),
            "mapper response",
        )
        if value["schema"] != PHASE04_MAPPER_RESPONSE_SCHEMA:
            raise SemanticValidationError("unsupported mapper response schema")
        if value["story_chunk_plan_identity"] != self._plan.identity:
            raise SemanticValidationError("mapper response has a foreign plan identity")
        if value["chunk_id"] != descriptor.chunk_id:
            raise SemanticValidationError("mapper response has a foreign chunk ID")
        if value["request_hash"] != descriptor.request_hash:
            raise SemanticValidationError("mapper response request hash does not match")
        if value["scope_id"] != descriptor.scope_id:
            raise SemanticValidationError("mapper response has wrong route ownership")

        binding = _scope_binding(self._plan, descriptor.scope_id)
        events: list[SemanticEvent] = []
        provider_keys: set[str] = set()
        for index, raw in enumerate(_array(value["events"], "mapper events")):
            event = _object(raw, f"mapper events[{index}]")
            _exact(
                event,
                frozenset({"key", "placement_ids", "title", "summary", "characters"}),
                f"mapper events[{index}]",
            )
            key = _string(event["key"], "mapper event key", maximum=80)
            if key in provider_keys:
                raise SemanticValidationError("mapper event keys must be unique")
            provider_keys.add(key)
            placements = _strings(event["placement_ids"], "mapper event placements")
            events.append(
                SemanticEvent(
                    event_id=_event_identity(self._plan.identity, placements),
                    scope_id=descriptor.scope_id,
                    route_owner=binding.lane_id,
                    placement_ids=placements,
                    title=_string(event["title"], "mapper event title", maximum=80),
                    summary=_string(event["summary"], "mapper event summary", maximum=320),
                    characters=_strings(
                        event["characters"],
                        "mapper event characters",
                        maximum_items=16,
                        maximum_length=80,
                    ),
                    structural_flags=descriptor.structural_flags,
                    origin=SemanticOrigin.AI,
                )
            )
        if not events:
            raise SemanticValidationError("mapper response must contain at least one event")
        flattened = tuple(item for event in events for item in event.placement_ids)
        if flattened != descriptor.placement_ids:
            raise SemanticValidationError(
                "mapper events must cover exact placement membership in frozen order"
            )
        if len({event.event_id for event in events}) != len(events):
            raise SemanticValidationError("mapper event memberships must be unique")

        summaries: dict[str, tuple[tuple[int, ...], str]] = {}
        for index, raw in enumerate(
            _array(value["branch_summaries"], "mapper branch summaries")
        ):
            summary_object = _object(raw, f"mapper branch summaries[{index}]")
            _exact(
                summary_object,
                frozenset({"choice_key", "arm_orders", "summary"}),
                f"mapper branch summaries[{index}]",
            )
            key = _string(summary_object["choice_key"], "branch choice key")
            if key in summaries:
                raise SemanticValidationError("mapper response duplicates a branch summary")
            arm_orders = tuple(
                _integer(item, "branch arm order")
                for item in _array(summary_object["arm_orders"], "branch arm orders")
            )
            if not arm_orders or len(arm_orders) != len(set(arm_orders)):
                raise SemanticValidationError("branch arm orders must be non-empty and unique")
            summaries[key] = (
                arm_orders,
                _string(summary_object["summary"], "branch summary", maximum=320),
            )

        expected_keys = tuple(segment.choice_key for segment in descriptor.choice_segments)
        if set(summaries) != set(expected_keys):
            raise SemanticValidationError(
                "mapper branch summaries must cover exact supplied choice mechanics"
            )
        choices: list[ExactChoiceOverlay] = []
        for segment in descriptor.choice_segments:
            arm_orders, summary = summaries[segment.choice_key]
            if arm_orders != segment.arm_orders:
                raise SemanticValidationError("mapper branch arm order differs from authority")
            parent = _choice_parent(self._plan, segment.choice_key)
            choices.append(
                ExactChoiceOverlay(
                    choice_key=parent.choice_key,
                    arm_orders=segment.arm_orders,
                    canonical_mechanics=parent.canonical_mechanics,
                    mechanics_hash=parent.mechanics_hash,
                    summary=summary,
                )
            )
        chunk = SemanticChunk(
            story_chunk_plan_identity=self._plan.identity,
            chunk_id=descriptor.chunk_id,
            request_hash=cast(str, descriptor.request_hash),
            scope_id=descriptor.scope_id,
            route_owner=binding.lane_id,
            title=_string(value["title"], "mapper chunk title", maximum=80),
            overview=_string(value["overview"], "mapper chunk overview", maximum=600),
            events=tuple(events),
            choices=tuple(choices),
            origin=SemanticOrigin.AI,
        )
        return chunk, _boolean(value["review_requested"], "review requested")

    def _validate_normalized_binding(
        self,
        chunk: SemanticChunk,
        descriptor: StoryChunkDescriptor,
    ) -> None:
        binding = _scope_binding(self._plan, descriptor.scope_id)
        if (
            chunk.origin is not SemanticOrigin.AI
            or chunk.story_chunk_plan_identity != self._plan.identity
            or chunk.chunk_id != descriptor.chunk_id
            or chunk.request_hash != descriptor.request_hash
            or chunk.scope_id != descriptor.scope_id
            or chunk.route_owner != binding.lane_id
        ):
            raise SemanticValidationError("cached semantic chunk has stale or foreign authority")
        flattened = tuple(item for event in chunk.events for item in event.placement_ids)
        if flattened != descriptor.placement_ids:
            raise SemanticValidationError("cached semantic chunk coverage differs from authority")
        if any(
            event.scope_id != descriptor.scope_id
            or event.route_owner != binding.lane_id
            or event.origin is not SemanticOrigin.AI
            or event.event_id != _event_identity(self._plan.identity, event.placement_ids)
            for event in chunk.events
        ):
            raise SemanticValidationError("cached event overlay differs from frozen authority")
        expected = tuple(
            (segment.choice_key, segment.arm_orders) for segment in descriptor.choice_segments
        )
        actual = tuple((choice.choice_key, choice.arm_orders) for choice in chunk.choices)
        if actual != expected:
            raise SemanticValidationError("cached choice overlay differs from frozen mechanics")
        for choice in chunk.choices:
            parent = _choice_parent(self._plan, choice.choice_key)
            if (
                choice.canonical_mechanics != parent.canonical_mechanics
                or choice.mechanics_hash != parent.mechanics_hash
            ):
                raise SemanticValidationError("cached choice mechanics differ from authority")


def structural_semantic_chunk(
    plan: StoryChunkPlan,
    descriptor: StoryChunkDescriptor,
    *,
    reason: str,
) -> SemanticChunk:
    """Create complete deterministic coverage for one predetermined frozen slot."""

    _trimmed(reason, "structural fallback reason", maximum=120)
    binding = _scope_binding(plan, descriptor.scope_id)
    groups_by_id = {group.id: group for group in plan.atomic_groups}
    events: list[SemanticEvent] = []
    for index, group_id in enumerate(descriptor.atomic_group_ids, start=1):
        group = groups_by_id[group_id]
        events.append(
            SemanticEvent(
                event_id=_event_identity(plan.identity, group.placement_ids),
                scope_id=descriptor.scope_id,
                route_owner=binding.lane_id,
                placement_ids=group.placement_ids,
                title=(
                    f"Story segment {descriptor.scope_ordinal}."
                    f"{descriptor.chunk_ordinal}.{index}"
                ),
                summary="Exact structural placement is preserved without accepted AI prose.",
                characters=(),
                structural_flags=descriptor.structural_flags,
                origin=SemanticOrigin.STRUCTURAL,
            )
        )
    fallback_reason = descriptor.structural_fallback_reason or reason
    return SemanticChunk(
        story_chunk_plan_identity=plan.identity,
        chunk_id=descriptor.chunk_id,
        request_hash=descriptor.request_hash,
        scope_id=descriptor.scope_id,
        route_owner=binding.lane_id,
        title=f"Structural section {descriptor.scope_ordinal}.{descriptor.chunk_ordinal}",
        overview="Python preserved exact ordered coverage for this story chunk.",
        events=tuple(events),
        choices=tuple(
            ExactChoiceOverlay(
                choice_key=segment.choice_key,
                arm_orders=segment.arm_orders,
                canonical_mechanics=_choice_parent(plan, segment.choice_key).canonical_mechanics,
                mechanics_hash=_choice_parent(plan, segment.choice_key).mechanics_hash,
                summary="Exact branch mechanics are available in Detail and Evidence.",
            )
            for segment in descriptor.choice_segments
        ),
        origin=SemanticOrigin.STRUCTURAL,
        rejection_reason=fallback_reason,
    )


def assemble_semantic_corridors(
    plan: StoryChunkPlan,
    normalized_results: tuple[bytes, ...],
) -> SemanticAssembly:
    """Fill the frozen ordered corridor without replanning or a repair loop.

    Malformed, invalid, missing, or stale results are rejected from semantic publication and their
    predetermined chunk slots receive deterministic structural coverage.  A duplicate or foreign
    result cannot be associated with any safe slot and fails the assembly as a whole.
    """

    descriptors = {chunk.chunk_id: chunk for chunk in plan.chunks}
    accepted: dict[str, SemanticChunk] = {}
    rejected: dict[str, str] = {}
    for payload in normalized_results:
        try:
            raw = _decode(payload, "normalized semantic result")
            chunk_id = _string(raw.get("chunk_id"), "normalized chunk ID")
        except SemanticValidationError as exc:
            raise SemanticAssemblyError(
                "semantic result cannot be bound to a frozen chunk"
            ) from exc
        if chunk_id not in descriptors:
            raise SemanticAssemblyError(f"foreign semantic result {chunk_id!r}")
        if chunk_id in accepted or chunk_id in rejected:
            raise SemanticAssemblyError(f"duplicate semantic result {chunk_id!r}")
        try:
            chunk = deserialize_semantic_chunk(payload)
            Phase04MapperResponseValidator(plan)._validate_normalized_binding(
                chunk, descriptors[chunk_id]
            )
        except (SemanticValidationError, ValueError):
            rejected[chunk_id] = "invalid_mapper_result"
        else:
            accepted[chunk_id] = chunk

    chunks: list[SemanticChunk] = []
    for descriptor in plan.chunks:
        accepted_chunk = accepted.get(descriptor.chunk_id)
        if accepted_chunk is None:
            reason = rejected.get(descriptor.chunk_id, "provider_result_unavailable")
            accepted_chunk = structural_semantic_chunk(plan, descriptor, reason=reason)
        chunks.append(accepted_chunk)
    flattened = tuple(
        placement_id
        for chunk in chunks
        for event in chunk.events
        for placement_id in event.placement_ids
    )
    if flattened != plan.covered_placement_ids:
        raise SemanticAssemblyError("semantic assembly changed frozen corridor coverage")
    event_ids = tuple(event.event_id for chunk in chunks for event in chunk.events)
    if len(event_ids) != len(set(event_ids)):
        raise SemanticAssemblyError("semantic assembly produced duplicate event membership")
    return SemanticAssembly(plan.identity, plan.source_identity, plan.coverage_hash, tuple(chunks))
