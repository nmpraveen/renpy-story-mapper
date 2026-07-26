"""Minimal project-bound persistence for one current Story Map V2 record."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, cast

from renpy_story_mapper import storage
from renpy_story_mapper.story_map_v2.contracts import (
    ArmLineageStep,
    ArmMechanic,
    BranchSummary,
    ChoiceMechanic,
    ChunkExecutionResult,
    ChunkStatus,
    CoreBranchOutcome,
    CoreChunk,
    CoreEvent,
    EventAnchor,
    FailureKind,
    MapperEvent,
    MapperResponse,
    ProviderOrigin,
    Reachability,
    StoryMapCore,
    canonical_hash,
)
from renpy_story_mapper.story_map_v2.phase03_contracts import (
    PROJECT_SCHEMA,
    SYNTHESIS_RECORD_SCHEMA,
    StoryMapProjectEnvelope,
    StoryMapProjectIdentity,
    SynthesisExecutionResult,
    SynthesisFailureKind,
    SynthesisSection,
    SynthesisStatus,
    SynthesisThread,
    ValidatedSynthesis,
)

COLLECTION = "story_map_v2"
CURRENT_KEY = "current"


@dataclass(frozen=True)
class _PayloadRecord:
    """Structural input for the generic Project.write_payloads transaction seam."""

    collection: str
    key: str
    value: object
    source_paths: tuple[str, ...]


class StoryMapV2PersistenceError(ValueError):
    """A stored Story Map V2 record is malformed or internally inconsistent."""


class StaleStoryMapV2Error(StoryMapV2PersistenceError):
    """A stored record does not match the current source/core/authority identity."""


StoredStoryMapV2 = StoryMapProjectEnvelope


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise StoryMapV2PersistenceError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise StoryMapV2PersistenceError(f"{label} must be an array")
    return tuple(value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise StoryMapV2PersistenceError(f"{label} must be a non-empty trimmed string")
    return value


def _optional_string(value: object, label: str) -> str | None:
    return None if value is None else _string(value, label)


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise StoryMapV2PersistenceError(f"{label} must be an integer of at least {minimum}")
    return value


def _optional_integer(value: object, label: str, *, minimum: int = 0) -> int | None:
    return None if value is None else _integer(value, label, minimum=minimum)


def _strings(value: object, label: str) -> tuple[str, ...]:
    return tuple(_string(item, f"{label}[]") for item in _sequence(value, label))


def _lineage(value: object, label: str) -> tuple[ArmLineageStep, ...]:
    result: list[ArmLineageStep] = []
    for index, raw in enumerate(_sequence(value, label)):
        item = _mapping(raw, f"{label}[{index}]")
        result.append(
            ArmLineageStep(
                _string(item.get("choice_key"), f"{label}[{index}].choice_key"),
                _integer(item.get("arm_order"), f"{label}[{index}].arm_order", minimum=1),
            )
        )
    return tuple(result)


def _anchor(value: object, label: str) -> EventAnchor:
    item = _mapping(value, label)
    return EventAnchor(
        _string(item.get("id"), f"{label}.id"),
        _string(item.get("canonical_node_id"), f"{label}.canonical_node_id"),
        _string(item.get("relative_path"), f"{label}.relative_path"),
        _integer(item.get("line"), f"{label}.line", minimum=1),
        _lineage(item.get("arm_lineage"), f"{label}.arm_lineage"),
        _optional_string(item.get("destination_id"), f"{label}.destination_id"),
    )


def _arm(value: object, label: str) -> ArmMechanic:
    item = _mapping(value, label)
    reachability = Reachability(_string(item.get("reachability"), f"{label}.reachability"))
    return ArmMechanic(
        _integer(item.get("order"), f"{label}.order", minimum=1),
        _string(item.get("caption"), f"{label}.caption"),
        _integer(item.get("start_line"), f"{label}.start_line", minimum=1),
        _integer(item.get("end_line"), f"{label}.end_line", minimum=1),
        _optional_string(item.get("condition"), f"{label}.condition"),
        _strings(item.get("effects"), f"{label}.effects"),
        _optional_string(item.get("destination_id"), f"{label}.destination_id"),
        _optional_string(item.get("rejoin_node_id"), f"{label}.rejoin_node_id"),
        _optional_integer(item.get("rejoin_line"), f"{label}.rejoin_line", minimum=1),
        reachability,
        _strings(item.get("unresolved_warnings"), f"{label}.unresolved_warnings"),
    )


def _choice(value: object, label: str) -> ChoiceMechanic:
    item = _mapping(value, label)
    arms = tuple(
        _arm(raw, f"{label}.arms[{index}]")
        for index, raw in enumerate(_sequence(item.get("arms"), f"{label}.arms"))
    )
    story_choice = item.get("story_choice")
    if not isinstance(story_choice, bool):
        raise StoryMapV2PersistenceError(f"{label}.story_choice must be a boolean")
    return ChoiceMechanic(
        _string(item.get("key"), f"{label}.key"),
        _string(item.get("relative_path"), f"{label}.relative_path"),
        _integer(item.get("line"), f"{label}.line", minimum=1),
        arms,
        _lineage(item.get("parent_lineage"), f"{label}.parent_lineage"),
        story_choice,
    )


def _event(value: object, label: str) -> CoreEvent:
    item = _mapping(value, label)
    return CoreEvent(
        _string(item.get("title"), f"{label}.title"),
        _string(item.get("summary"), f"{label}.summary"),
        _string(item.get("relative_path"), f"{label}.relative_path"),
        _integer(item.get("start_line"), f"{label}.start_line", minimum=1),
        _integer(item.get("end_line"), f"{label}.end_line", minimum=1),
        _strings(item.get("characters"), f"{label}.characters"),
        _strings(item.get("warnings"), f"{label}.warnings"),
        _anchor(item.get("anchor"), f"{label}.anchor"),
        Reachability(_string(item.get("reachability"), f"{label}.reachability")),
    )


def _outcome(value: object, label: str) -> CoreBranchOutcome:
    item = _mapping(value, label)
    return CoreBranchOutcome(
        _string(item.get("choice_key"), f"{label}.choice_key"),
        _integer(item.get("arm_order"), f"{label}.arm_order", minimum=1),
        _string(item.get("caption"), f"{label}.caption"),
        _string(item.get("summary"), f"{label}.summary"),
        _anchor(item.get("anchor"), f"{label}.anchor"),
        Reachability(_string(item.get("reachability"), f"{label}.reachability")),
        _strings(item.get("warnings"), f"{label}.warnings"),
    )


def _mapper_response(value: object, label: str) -> MapperResponse | None:
    if value is None:
        return None
    item = _mapping(value, label)
    events = []
    for index, raw in enumerate(_sequence(item.get("events"), f"{label}.events")):
        event = _mapping(raw, f"{label}.events[{index}]")
        events.append(
            MapperEvent(
                _string(event.get("title"), "mapper event title"),
                _string(event.get("summary"), "mapper event summary"),
                _string(event.get("relative_path"), "mapper event path"),
                _integer(event.get("start_line"), "mapper event start", minimum=1),
                _integer(event.get("end_line"), "mapper event end", minimum=1),
                _strings(event.get("characters"), "mapper event characters"),
                _optional_string(event.get("warning"), "mapper event warning"),
            )
        )
    summaries = []
    for raw in _sequence(item.get("branch_summaries"), f"{label}.branch_summaries"):
        summary = _mapping(raw, "mapper branch summary")
        summaries.append(
            BranchSummary(
                _string(summary.get("choice_key"), "mapper choice key"),
                _integer(summary.get("arm_order"), "mapper arm order", minimum=1),
                _string(summary.get("outcome_summary"), "mapper outcome summary"),
            )
        )
    return MapperResponse(
        _optional_string(item.get("scope_title"), f"{label}.scope_title"),
        _optional_string(item.get("scope_overview"), f"{label}.scope_overview"),
        tuple(events),
        tuple(summaries),
    )


def _execution(value: object, label: str) -> ChunkExecutionResult | None:
    if value is None:
        return None
    item = _mapping(value, label)
    failure = item.get("failure_kind")
    fast_mode = item.get("fast_mode")
    if fast_mode is not None and not isinstance(fast_mode, bool):
        raise StoryMapV2PersistenceError(f"{label}.fast_mode must be a boolean or null")
    return ChunkExecutionResult(
        _string(item.get("chunk_identity"), f"{label}.chunk_identity"),
        ProviderOrigin(_string(item.get("origin"), f"{label}.origin")),
        ChunkStatus(_string(item.get("status"), f"{label}.status")),
        _mapper_response(item.get("response"), f"{label}.response"),
        None if failure is None else FailureKind(_string(failure, f"{label}.failure_kind")),
        _integer(item.get("elapsed_ms"), f"{label}.elapsed_ms"),
        _optional_string(item.get("response_hash"), f"{label}.response_hash"),
        _optional_string(item.get("sanitized_reason"), f"{label}.sanitized_reason"),
        _optional_integer(item.get("input_tokens"), f"{label}.input_tokens"),
        _optional_integer(item.get("output_tokens"), f"{label}.output_tokens"),
        _optional_string(item.get("requested_model"), f"{label}.requested_model"),
        _optional_string(item.get("resolved_model"), f"{label}.resolved_model"),
        _optional_string(item.get("reasoning"), f"{label}.reasoning"),
        fast_mode,
    )


def _core(value: object) -> StoryMapCore:
    item = _mapping(value, "core")
    chunks: list[CoreChunk] = []
    for index, raw in enumerate(_sequence(item.get("chunks"), "core.chunks")):
        label = f"core.chunks[{index}]"
        chunk = _mapping(raw, label)
        chunks.append(
            CoreChunk(
                _string(chunk.get("chunk_identity"), f"{label}.chunk_identity"),
                ChunkStatus(_string(chunk.get("status"), f"{label}.status")),
                ProviderOrigin(_string(chunk.get("origin"), f"{label}.origin")),
                tuple(
                    _event(raw_event, f"{label}.events[{event_index}]")
                    for event_index, raw_event in enumerate(
                        _sequence(chunk.get("events"), f"{label}.events")
                    )
                ),
                tuple(
                    _choice(raw_choice, f"{label}.choices[{choice_index}]")
                    for choice_index, raw_choice in enumerate(
                        _sequence(chunk.get("choices"), f"{label}.choices")
                    )
                ),
                tuple(
                    _outcome(raw_outcome, f"{label}.branch_outcomes[{outcome_index}]")
                    for outcome_index, raw_outcome in enumerate(
                        _sequence(chunk.get("branch_outcomes"), f"{label}.branch_outcomes")
                    )
                ),
                _optional_string(chunk.get("scope_title"), f"{label}.scope_title"),
                _optional_string(chunk.get("scope_overview"), f"{label}.scope_overview"),
                _execution(chunk.get("execution"), f"{label}.execution"),
                _strings(chunk.get("warnings"), f"{label}.warnings"),
            )
        )
    return StoryMapCore(
        _string(item.get("schema"), "core.schema"),
        _string(item.get("source_identity"), "core.source_identity"),
        ChunkStatus(_string(item.get("status"), "core.status")),
        tuple(chunks),
        _optional_string(item.get("title"), "core.title"),
        _optional_string(item.get("overview"), "core.overview"),
    )


def _identity(value: object) -> StoryMapProjectIdentity:
    item = _mapping(value, "identity")
    return StoryMapProjectIdentity(
        _string(item.get("schema"), "identity.schema"),
        _string(item.get("core_schema"), "identity.core_schema"),
        _string(item.get("core_hash"), "identity.core_hash"),
        _string(item.get("source_identity"), "identity.source_identity"),
        _string(item.get("source_generation"), "identity.source_generation"),
        _string(item.get("authority_hash"), "identity.authority_hash"),
        _strings(item.get("source_paths"), "identity.source_paths"),
    )


def _synthesis(value: object) -> SynthesisExecutionResult | None:
    if value is None:
        return None
    item = _mapping(value, "synthesis")
    raw_validated = item.get("synthesis")
    validated: ValidatedSynthesis | None = None
    if raw_validated is not None:
        raw = _mapping(raw_validated, "synthesis.synthesis")
        sections = tuple(
            SynthesisSection(
                _string(section.get("section_title"), "synthesis section title"),
                _string(section.get("section_summary"), "synthesis section summary"),
                _strings(section.get("event_anchor_ids"), "synthesis section anchors"),
            )
            for section in (
                _mapping(value, "synthesis section")
                for value in _sequence(raw.get("ordered_sections"), "synthesis sections")
            )
        )
        threads = tuple(
            SynthesisThread(
                _string(thread.get("title"), "synthesis thread title"),
                _string(thread.get("summary"), "synthesis thread summary"),
                _strings(thread.get("event_anchor_ids"), "synthesis thread anchors"),
            )
            for thread in (
                _mapping(value, "synthesis thread")
                for value in _sequence(raw.get("optional_threads"), "synthesis threads")
            )
        )
        validated = ValidatedSynthesis(
            _string(raw.get("story_title"), "synthesis story title"),
            _string(raw.get("story_overview"), "synthesis story overview"),
            sections,
            threads,
            _strings(raw.get("analysis_notes"), "synthesis analysis notes"),
        )
    failure = item.get("failure_kind")
    fast = item.get("fast_mode")
    if not isinstance(fast, bool):
        raise StoryMapV2PersistenceError("synthesis.fast_mode must be a boolean")
    return SynthesisExecutionResult(
        _string(item.get("schema"), "synthesis.schema"),
        _string(item.get("project_identity_hash"), "synthesis.project_identity_hash"),
        _string(item.get("request_payload_hash"), "synthesis.request_payload_hash"),
        _string(item.get("preview_confirmation_hash"), "synthesis.preview_confirmation_hash"),
        SynthesisStatus(_string(item.get("status"), "synthesis.status")),
        validated,
        _optional_string(item.get("provider"), "synthesis.provider"),
        _string(item.get("requested_model"), "synthesis.requested_model"),
        _optional_string(item.get("resolved_model"), "synthesis.resolved_model"),
        _string(item.get("reasoning"), "synthesis.reasoning"),
        fast,
        _integer(item.get("call_count"), "synthesis.call_count"),
        _optional_integer(item.get("input_tokens"), "synthesis.input_tokens"),
        _optional_integer(item.get("output_tokens"), "synthesis.output_tokens"),
        _integer(item.get("elapsed_ms"), "synthesis.elapsed_ms"),
        (
            None
            if failure is None
            else SynthesisFailureKind(_string(failure, "synthesis.failure_kind"))
        ),
        _optional_string(item.get("sanitized_reason"), "synthesis.sanitized_reason"),
    )


def _validate_record(
    identity: StoryMapProjectIdentity,
    core: StoryMapCore,
    synthesis: SynthesisExecutionResult | None,
) -> None:
    if core.schema != identity.core_schema or core.source_identity != identity.source_identity:
        raise StaleStoryMapV2Error("stored core identity does not match its project envelope")
    if canonical_hash(asdict(core)) != identity.core_hash:
        raise StaleStoryMapV2Error("stored core hash does not match its project envelope")
    if synthesis is not None:
        if synthesis.schema != SYNTHESIS_RECORD_SCHEMA:
            raise StoryMapV2PersistenceError("stored synthesis schema is unsupported")
        if synthesis.project_identity_hash != identity.identity_hash:
            raise StaleStoryMapV2Error("stored synthesis identity is stale")
        if synthesis.call_count not in {0, 1}:
            raise StoryMapV2PersistenceError("stored synthesis exceeds the one-call ceiling")
        if synthesis.status is SynthesisStatus.SUCCEEDED:
            if synthesis.synthesis is None:
                raise StoryMapV2PersistenceError("successful synthesis content is missing")
            if not 5 <= len(synthesis.synthesis.ordered_sections) <= 7 or any(
                not section.event_anchor_ids for section in synthesis.synthesis.ordered_sections
            ):
                raise StoryMapV2PersistenceError(
                    "successful synthesis requires five to seven non-empty sections"
                )
            if (
                synthesis.requested_model != "gpt-5.6-terra"
                or synthesis.resolved_model != "gpt-5.6-terra"
                or synthesis.reasoning != "high"
                or synthesis.fast_mode
                or synthesis.call_count != 1
                or synthesis.failure_kind is not None
            ):
                raise StoryMapV2PersistenceError(
                    "successful synthesis provider provenance is invalid"
                )
            from renpy_story_mapper.story_map_v2.presentation import project_story_map

            project_story_map(core, synthesis)
        if synthesis.status is SynthesisStatus.FAILED and synthesis.synthesis is not None:
            raise StoryMapV2PersistenceError("failed synthesis cannot contain accepted prose")
        if synthesis.status is SynthesisStatus.FAILED and synthesis.failure_kind is None:
            raise StoryMapV2PersistenceError("failed synthesis requires a sanitized failure kind")


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def save_story_map_v2(
    project: Any,
    core: StoryMapCore,
    identity: StoryMapProjectIdentity,
    synthesis: SynthesisExecutionResult | None = None,
) -> None:
    """Atomically replace the single current core and optional synthesis envelope."""

    _validate_record(identity, core, synthesis)
    value = {
        "schema": PROJECT_SCHEMA,
        "identity": _json_value(asdict(identity)),
        "core": _json_value(asdict(core)),
        "synthesis": None if synthesis is None else _json_value(asdict(synthesis)),
        "imported_at_utc": storage.utc_now(),
    }
    project.write_payloads((_PayloadRecord(COLLECTION, CURRENT_KEY, value, identity.source_paths),))


def load_story_map_v2(
    project: Any,
    *,
    expected_identity: StoryMapProjectIdentity | None = None,
) -> StoredStoryMapV2 | None:
    value = project.payload(COLLECTION, CURRENT_KEY)
    if value is None:
        return None
    root = _mapping(value, "Story Map V2 record")
    if root.get("schema") != PROJECT_SCHEMA:
        raise StoryMapV2PersistenceError("stored Story Map V2 project schema is unsupported")
    identity = _identity(root.get("identity"))
    core = _core(root.get("core"))
    synthesis = _synthesis(root.get("synthesis"))
    imported_at = _string(root.get("imported_at_utc"), "imported_at_utc")
    _validate_record(identity, core, synthesis)
    if expected_identity is not None and identity != expected_identity:
        raise StaleStoryMapV2Error("stored Story Map V2 identity is stale")
    return StoryMapProjectEnvelope(PROJECT_SCHEMA, identity, core, synthesis, imported_at)


def load_story_map_v2_for_current_project(project: Any) -> StoredStoryMapV2 | None:
    """Load against current M10/source authority without constructing any provider."""

    stored = load_story_map_v2(project)
    if stored is None:
        return None
    canonical = project.payload("m10_canonical_graph", "authoritative")
    if not isinstance(canonical, Mapping):
        raise StaleStoryMapV2Error("current canonical authority is unavailable")
    generation = canonical.get("source_generation")
    if generation != stored.identity.source_generation:
        raise StaleStoryMapV2Error("stored Story Map V2 source generation is stale")
    if canonical_hash(cast(Mapping[str, object], canonical)) != stored.identity.authority_hash:
        raise StaleStoryMapV2Error("stored Story Map V2 authority hash is stale")
    current_paths = {source.path for source in project.sources()}
    if not set(stored.identity.source_paths) <= current_paths:
        raise StaleStoryMapV2Error("stored Story Map V2 source dependencies are stale")
    return stored
