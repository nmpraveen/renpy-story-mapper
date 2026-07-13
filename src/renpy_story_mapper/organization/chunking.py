"""Deterministic, evidence-aware input chunking for event organization."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from itertools import pairwise

from renpy_story_mapper.organization.contracts import (
    MAX_PROMPT_CHARS,
    BeatRecord,
    FactRecord,
    OrganizationConstraints,
    OrganizationRequest,
    OrganizationStage,
    organization_prompts_fit,
)

MAX_CHARS = MAX_PROMPT_CHARS
MAX_ASSIGNED_BEATS = 120
MAX_CONTEXT_BEATS = 2
MAX_SPEAKER_NAME_CHARS = 120
_BOUNDARY_SEARCH_BEATS = 24
_BOUNDARY_STRENGTH = {
    "condition": 1,
    "choice": 2,
    "jump": 3,
    "return": 4,
    "ending": 4,
}
_TEXT_BEARING_KINDS = {"narrative", "narration", "dialogue", "choice", "condition"}
_COVERAGE_KINDS = {"narrative", "narration", "dialogue", "choice", "condition"}


@dataclass(frozen=True)
class _ChunkDraft:
    scene_id: str
    beats: tuple[BeatRecord, ...]


def _beat_payload(beat: BeatRecord, *, context: bool) -> dict[str, object]:
    value: dict[str, object] = {
        "id": beat.id,
        "kind": beat.kind,
        "order": beat.order,
        "context_only": context,
        "evidence_ids": list(beat.evidence_ids),
        "fact_ids": list(beat.fact_ids),
        "adjacent_ids": list(beat.outgoing_ids),
        "source": {
            "path": beat.relative_path,
            "start_line": beat.start_line,
            "end_line": beat.end_line,
        },
    }
    speakers = _beat_speakers(beat)
    if beat.speaker is not None:
        value["speaker"] = beat.speaker
    if speakers:
        value["speakers"] = speakers
    if beat.text and beat.kind in _TEXT_BEARING_KINDS:
        value["text"] = beat.text
    if beat.condition:
        value["condition"] = beat.condition
    return value


def _beat_speakers(beat: BeatRecord) -> list[str]:
    if beat.speaker is not None and not isinstance(beat.speaker, str):
        raise ValueError("speaker must be text or None.")
    speaker_names: object = beat.speaker_names
    if isinstance(speaker_names, (str, bytes)) or not isinstance(speaker_names, Sequence):
        raise ValueError("speaker_names must be a sequence of text values.")
    if any(not isinstance(name, str) for name in speaker_names):
        raise ValueError("speaker_names members must be text values.")
    ordered = ([beat.speaker] if beat.speaker is not None else []) + list(speaker_names)
    speakers: list[str] = []
    seen: set[str] = set()
    for name in ordered:
        if not name or not name.strip() or name != name.strip():
            raise ValueError("Speaker names must be non-empty trimmed text.")
        if len(name) > MAX_SPEAKER_NAME_CHARS:
            raise ValueError(f"Speaker names may not exceed {MAX_SPEAKER_NAME_CHARS} characters.")
        if name not in seen:
            seen.add(name)
            speakers.append(name)
    return speakers


def _encoded_beat_size(beat: BeatRecord) -> int:
    return len(
        json.dumps(
            _beat_payload(beat, context=False),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _payload_list_size(encoded_sizes: Sequence[int]) -> int:
    if not encoded_sizes:
        return 2
    return 2 + sum(encoded_sizes) + len(encoded_sizes) - 1


def _preferred_boundary_split(
    beats: Sequence[BeatRecord],
    *,
    target: int,
    maximum: int,
) -> int:
    bounded_target = max(1, min(target, maximum))
    lower = max(1, bounded_target - _BOUNDARY_SEARCH_BEATS)
    upper = min(maximum, bounded_target + _BOUNDARY_SEARCH_BEATS)
    candidates = [
        (index + 1, _BOUNDARY_STRENGTH[beat.kind])
        for index, beat in enumerate(beats)
        if beat.kind in _BOUNDARY_STRENGTH and lower <= index + 1 <= upper
    ]
    if not candidates:
        return bounded_target
    return max(
        candidates,
        key=lambda item: (
            item[1],
            -abs(item[0] - bounded_target),
            item[0],
        ),
    )[0]


def _partition(beats: list[BeatRecord]) -> list[_ChunkDraft]:
    drafts: list[_ChunkDraft] = []
    current: list[BeatRecord] = []
    current_sizes: list[int] = []
    current_scene = ""
    for beat in beats:
        if current and beat.scene_id != current_scene:
            drafts.append(_ChunkDraft(current_scene, tuple(current)))
            current = []
            current_sizes = []
        current_scene = beat.scene_id
        beat_size = _encoded_beat_size(beat)
        while current and (
            len(current) >= MAX_ASSIGNED_BEATS
            or _payload_list_size((*current_sizes, beat_size)) > MAX_CHARS
        ):
            split = _preferred_boundary_split(
                current,
                target=len(current),
                maximum=len(current),
            )
            drafts.append(_ChunkDraft(current_scene, tuple(current[:split])))
            current = current[split:]
            current_sizes = current_sizes[split:]
        current.append(beat)
        current_sizes.append(beat_size)
    if current:
        drafts.append(_ChunkDraft(current_scene, tuple(current)))
    return drafts


def build_event_chunks(
    *,
    run_id: str,
    scope_id: str,
    beats: list[BeatRecord],
    facts: list[FactRecord] | None = None,
    on_oversized: Callable[[BeatRecord], None] | None = None,
    on_deterministic_fallback: Callable[[BeatRecord], None] | None = None,
) -> list[OrganizationRequest]:
    """Build Stage-1 chunks; optionally route untransmittable single beats to fallback."""
    ordered = list(beats)
    if len({beat.id for beat in ordered}) != len(ordered):
        raise ValueError("Beat IDs must be unique before chunking.")
    for previous, current in pairwise(ordered):
        if previous.scene_id == current.scene_id and previous.order > current.order:
            raise ValueError("Beats within a contiguous scene must be in deterministic order.")
    fact_by_id = {fact.id: fact for fact in (facts or [])}
    referenced_fact_ids = {fact_id for beat in ordered for fact_id in beat.fact_ids}
    missing_fact_ids = referenced_fact_ids - set(fact_by_id)
    if missing_fact_ids:
        raise ValueError("Every referenced fact ID must have an input fact record.")
    index_by_id = {beat.id: index for index, beat in enumerate(ordered)}
    requests: list[OrganizationRequest] = []
    pending = deque(_partition(ordered))
    while pending:
        draft = pending.popleft()
        first = index_by_id[draft.beats[0].id]
        last = index_by_id[draft.beats[-1].id]
        candidates: list[tuple[int, int, BeatRecord]] = []
        before_count = 0
        for index in range(first - 1, -1, -1):
            candidate = ordered[index]
            if candidate.scene_id != draft.scene_id:
                break
            if candidate.is_context_candidate:
                candidates.append((first - index, index, candidate))
                before_count += 1
                if before_count >= MAX_CONTEXT_BEATS:
                    break
        after_count = 0
        for index in range(last + 1, len(ordered)):
            candidate = ordered[index]
            if candidate.scene_id != draft.scene_id:
                break
            if candidate.is_context_candidate:
                candidates.append((index - last, index, candidate))
                after_count += 1
                if after_count >= MAX_CONTEXT_BEATS:
                    break
        context_priority = [
            item[2] for item in sorted(candidates, key=lambda item: (item[0], item[1]))
        ][:MAX_CONTEXT_BEATS]
        context = list(context_priority)
        request = _event_request(
            run_id=run_id,
            chunk_id=f"{scope_id}:events:{len(requests) + 1}",
            scope_id=scope_id,
            draft=draft,
            context=context,
            fact_by_id=fact_by_id,
            index_by_id=index_by_id,
        )
        while context and not _request_prompts_fit(request):
            context.pop()
            request = _event_request(
                run_id=run_id,
                chunk_id=f"{scope_id}:events:{len(requests) + 1}",
                scope_id=scope_id,
                draft=draft,
                context=context,
                fact_by_id=fact_by_id,
                index_by_id=index_by_id,
            )
        if not _request_prompts_fit(request):
            if len(draft.beats) == 1:
                if on_oversized is not None:
                    on_oversized(draft.beats[0])
                    continue
                raise ValueError(
                    "A single complete organization prompt exceeds the 48,000-character limit."
                )
            midpoint = _preferred_boundary_split(
                draft.beats,
                target=len(draft.beats) // 2,
                maximum=len(draft.beats) - 1,
            )
            pending.appendleft(_ChunkDraft(draft.scene_id, draft.beats[midpoint:]))
            pending.appendleft(_ChunkDraft(draft.scene_id, draft.beats[:midpoint]))
            continue
        if (
            not request.constraints.required_member_ids
            and on_deterministic_fallback is not None
        ):
            for beat in draft.beats:
                on_deterministic_fallback(beat)
            continue
        requests.append(request)
    return requests


def _event_request(
    *,
    run_id: str,
    chunk_id: str,
    scope_id: str,
    draft: _ChunkDraft,
    context: list[BeatRecord],
    fact_by_id: dict[str, FactRecord],
    index_by_id: dict[str, int],
) -> OrganizationRequest:
    payload = _event_payload(
        scope_id=scope_id,
        draft=draft,
        context=context,
        fact_by_id=fact_by_id,
        index_by_id=index_by_id,
    )
    assigned_ids = tuple(beat.id for beat in draft.beats)
    context_ids = frozenset(beat.id for beat in context)
    used_fact_ids = frozenset(fid for beat in draft.beats for fid in beat.fact_ids)
    used_evidence_ids = frozenset(
        evidence_id for beat in (*draft.beats, *context) for evidence_id in beat.evidence_ids
    ).union(
        evidence_id for fact_id in used_fact_ids for evidence_id in fact_by_id[fact_id].evidence_ids
    )
    characters = frozenset(
        speaker for beat in (*draft.beats, *context) for speaker in _beat_speakers(beat)
    )
    request = OrganizationRequest(
        run_id=run_id,
        chunk_id=chunk_id,
        scope_id=scope_id,
        stage=OrganizationStage.EVENTS,
        payload=payload,
        constraints=OrganizationConstraints(
            ordered_member_ids=assigned_ids,
            required_member_ids=frozenset(
                beat.id
                for beat in draft.beats
                if beat.kind in _COVERAGE_KINDS or bool(beat.fact_ids)
            ),
            context_member_ids=context_ids,
            fact_ids=used_fact_ids,
            evidence_ids=used_evidence_ids,
            character_names=characters,
        ),
    )
    return request


def _request_prompts_fit(request: OrganizationRequest) -> bool:
    return organization_prompts_fit(request, limit=MAX_CHARS)


def _ensure_request_prompts_fit(request: OrganizationRequest) -> None:
    if not _request_prompts_fit(request):
        raise ValueError("The complete organization prompt exceeds the 48,000-character limit.")


def partition_organization_request(
    request: OrganizationRequest,
) -> tuple[OrganizationRequest, ...]:
    """Partition an oversized M07 route request by ordered nodes using exact prompts.

    The returned requests retain the logical scope ID while receiving deterministic chunk
    suffixes. Required members are assigned to exactly one contiguous partition; related route
    records are filtered to the members they reference. Non-route requests must already fit.
    """

    if _request_prompts_fit(request):
        return (request,)
    nodes = request.payload.get("nodes")
    events = request.payload.get("events")
    if not request.constraints.ordered_member_ids:
        _ensure_request_prompts_fit(request)
        raise AssertionError("unreachable")
    if isinstance(nodes, list):
        builder = _route_partition_request
        item_name = "route-node"
        primary = nodes
    elif isinstance(events, list):
        builder = _normalized_event_partition_request
        item_name = "normalized-event"
        primary = events
    else:
        _ensure_request_prompts_fit(request)
        raise AssertionError("unreachable")
    node_by_id: dict[str, dict[str, object]] = {}
    for value in primary:
        if not isinstance(value, dict) or not isinstance(value.get("id"), str):
            raise ValueError("Route nodes must be objects with text IDs before partitioning.")
        node_id = value["id"]
        if node_id in node_by_id:
            raise ValueError("Route node IDs must be unique before partitioning.")
        node_by_id[node_id] = value
    ordered = request.constraints.ordered_member_ids
    if any(node_id not in node_by_id for node_id in ordered):
        raise ValueError("Every ordered route member must have a node payload.")

    partitions: list[OrganizationRequest] = []
    start = 0
    while start < len(ordered):
        best: OrganizationRequest | None = None
        lower = start + 1
        upper = len(ordered)
        while lower <= upper:
            end = (lower + upper) // 2
            candidate = builder(request, ordered[start:end], len(partitions) + 1)
            if _request_prompts_fit(candidate):
                best = candidate
                lower = end + 1
            else:
                upper = end - 1
        if best is None:
            raise ValueError(
                f"A single complete {item_name} organization prompt exceeds the "
                "48,000-character limit."
            )
        partitions.append(best)
        start += len(best.constraints.ordered_member_ids)
    return tuple(partitions)


def _normalized_event_partition_request(
    request: OrganizationRequest, assigned_ids: tuple[str, ...], ordinal: int
) -> OrganizationRequest:
    assigned = frozenset(assigned_ids)
    events = [
        item
        for item in _record_list(request.payload, "events")
        if _record_id(item) in assigned
    ]
    connectivity_value = request.payload.get("local_connectivity", [])
    if not isinstance(connectivity_value, list) or any(
        not isinstance(item, dict) for item in connectivity_value
    ):
        raise ValueError("Normalized local connectivity must be a list of objects.")
    connectivity = [
        item for item in connectivity_value if _record_references(item, assigned)
    ]
    fact_ids = _referenced_ids(events, request.constraints.fact_ids)
    evidence_ids = _referenced_ids(events, request.constraints.evidence_ids)
    character_names = _referenced_ids(events, request.constraints.character_names)
    payload = dict(request.payload)
    payload["events"] = events
    if "local_connectivity" in payload:
        payload["local_connectivity"] = connectivity
    return replace(
        request,
        chunk_id=f"{request.chunk_id}:part:{ordinal}",
        payload=payload,
        constraints=OrganizationConstraints(
            ordered_member_ids=assigned_ids,
            required_member_ids=request.constraints.required_member_ids.intersection(assigned),
            context_member_ids=request.constraints.context_member_ids.intersection(assigned),
            fact_ids=fact_ids,
            evidence_ids=evidence_ids,
            character_names=character_names,
        ),
    )


def _route_partition_request(
    request: OrganizationRequest, assigned_ids: tuple[str, ...], ordinal: int
) -> OrganizationRequest:
    assigned = frozenset(assigned_ids)
    nodes = _record_list(request.payload, "nodes")
    selected_nodes = [item for item in nodes if item["id"] in assigned]
    edges = [
        item
        for item in _record_list(request.payload, "edges")
        if _record_references(item, assigned)
    ]
    available_fact_ids = request.constraints.fact_ids
    referenced_fact_ids = _referenced_ids((*selected_nodes, *edges), available_fact_ids)
    facts = [
        item
        for item in _record_list(request.payload, "facts")
        if item["id"] in referenced_fact_ids
    ]
    available_evidence_ids = request.constraints.evidence_ids
    referenced_evidence_ids = _referenced_ids(
        (*selected_nodes, *edges, *facts), available_evidence_ids
    )
    evidence = [
        item
        for item in _record_list(request.payload, "evidence")
        if item["id"] in referenced_evidence_ids
    ]
    payload = dict(request.payload)
    payload.update(
        {
            "node_ids": list(assigned_ids),
            "edge_ids": [_record_id(item) for item in edges],
            "evidence_ids": [_record_id(item) for item in evidence],
            "fact_ids": [_record_id(item) for item in facts],
            "nodes": selected_nodes,
            "edges": edges,
            "evidence": evidence,
            "facts": facts,
        }
    )
    return replace(
        request,
        chunk_id=f"{request.chunk_id}:part:{ordinal}",
        payload=payload,
        constraints=OrganizationConstraints(
            ordered_member_ids=assigned_ids,
            required_member_ids=request.constraints.required_member_ids.intersection(assigned),
            context_member_ids=request.constraints.context_member_ids.intersection(assigned),
            fact_ids=frozenset(_record_id(item) for item in facts),
            evidence_ids=frozenset(_record_id(item) for item in evidence),
            character_names=request.constraints.character_names,
        ),
    )


def _record_list(payload: dict[str, object], field: str) -> list[dict[str, object]]:
    value = payload.get(field, [])
    if not isinstance(value, list):
        raise ValueError(f"Route {field} must be a list before partitioning.")
    records: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError(f"Route {field} must contain objects with text IDs.")
        records.append(item)
    return records


def _record_id(record: dict[str, object]) -> str:
    value = record["id"]
    assert isinstance(value, str)
    return value


def _record_references(record: dict[str, object], identifiers: frozenset[str]) -> bool:
    return bool(_referenced_ids((record,), identifiers))


def _referenced_ids(
    values: Sequence[object], identifiers: frozenset[str]
) -> frozenset[str]:
    found: set[str] = set()

    def visit(value: object, *, record_id: object = None) -> None:
        if isinstance(value, str):
            if value != record_id and value in identifiers:
                found.add(value)
        elif isinstance(value, dict):
            own_id = value.get("id")
            for key, item in value.items():
                if key != "id":
                    visit(item, record_id=own_id)
        elif isinstance(value, list):
            for item in value:
                visit(item, record_id=record_id)

    for value in values:
        visit(value)
    return frozenset(found)


def _event_payload(
    *,
    scope_id: str,
    draft: _ChunkDraft,
    context: list[BeatRecord],
    fact_by_id: dict[str, FactRecord],
    index_by_id: dict[str, int],
) -> dict[str, object]:
    assigned_ids = tuple(beat.id for beat in draft.beats)
    context_ids = frozenset(beat.id for beat in context)
    used_fact_ids = frozenset(fact_id for beat in draft.beats for fact_id in beat.fact_ids)
    return {
        "stage": OrganizationStage.EVENTS.value,
        "scope_id": scope_id,
        "scene_id": draft.scene_id,
        "assigned_beat_ids": list(assigned_ids),
        "context_beat_ids": [
            beat.id for beat in sorted(context, key=lambda item: index_by_id[item.id])
        ],
        "beats": [
            _beat_payload(beat, context=beat.id in context_ids)
            for beat in sorted((*draft.beats, *context), key=lambda item: index_by_id[item.id])
        ],
        "facts": [
            {
                "id": fact_by_id[fact_id].id,
                "expression": fact_by_id[fact_id].expression,
                "normalized_value": fact_by_id[fact_id].normalized_value,
                "certainty": fact_by_id[fact_id].certainty,
                "evidence_ids": list(fact_by_id[fact_id].evidence_ids),
            }
            for fact_id in sorted(used_fact_ids)
        ],
    }


def _string(value: object, field: str, *, maximum: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text.")
    if maximum is not None and len(value) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters.")
    return value


def _string_list(value: object, field: str, *, maximum: int | None = None) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a string list.")
    result = list(value)
    if any(not item.strip() for item in result):
        raise ValueError(f"{field} may not contain empty text.")
    if maximum is not None and any(len(item) > maximum for item in result):
        raise ValueError(f"{field} contains text exceeding {maximum} characters.")
    return result


def _importance(value: object, field: str) -> str:
    importance = _string(value, field)
    if importance not in {"supporting", "major", "turning point"}:
        raise ValueError(f"{field} is not an allowed importance value.")
    return importance


def _normalize_reconciliation_event(event: dict[str, object]) -> dict[str, object]:
    allowed = {
        "id",
        "title",
        "summary",
        "member_ids",
        "characters",
        "importance",
        "outcomes",
        "promoted_fact_ids",
        "evidence_ids",
        "warnings",
    }
    unknown = set(event) - allowed
    if unknown:
        raise ValueError("Stage 2 event input contains forbidden raw story fields.")
    required = {"id", "title", "summary", "member_ids"}
    if not required.issubset(event):
        raise ValueError("Stage 2 event input is missing required normalized fields.")
    normalized: dict[str, object] = {
        "id": _string(event["id"], "event.id"),
        "title": _string(event["title"], "event.title", maximum=80),
        "summary": _string(event["summary"], "event.summary", maximum=320),
        "member_ids": _string_list(event["member_ids"], "event.member_ids"),
    }
    optional_fields = (
        "characters",
        "importance",
        "outcomes",
        "promoted_fact_ids",
        "evidence_ids",
        "warnings",
    )
    for field in optional_fields:
        if field in event:
            if field == "importance":
                normalized[field] = _importance(event[field], f"event.{field}")
            else:
                maximum = 320 if field in {"outcomes", "warnings"} else None
                normalized[field] = _string_list(event[field], f"event.{field}", maximum=maximum)
    return normalized


def _normalize_arc_event(
    event: dict[str, object],
    *,
    fact_ids: frozenset[str],
    evidence_ids: frozenset[str],
    characters: frozenset[str],
) -> dict[str, object]:
    allowed = {
        "id",
        "title",
        "summary",
        "major_fact_ids",
        "characters",
        "importance",
        "outcomes",
        "evidence_ids",
    }
    if set(event) != allowed:
        raise ValueError("Stage 3 event input must match the normalized allowlist exactly.")
    major_fact_ids = _string_list(event["major_fact_ids"], "event.major_fact_ids")
    event_characters = _string_list(event["characters"], "event.characters")
    event_evidence_ids = _string_list(event["evidence_ids"], "event.evidence_ids")
    normalized: dict[str, object] = {
        "id": _string(event["id"], "event.id"),
        "title": _string(event["title"], "event.title", maximum=80),
        "summary": _string(event["summary"], "event.summary", maximum=320),
        "importance": _importance(event["importance"], "event.importance"),
        "major_fact_ids": major_fact_ids,
        "characters": event_characters,
        "outcomes": _string_list(event["outcomes"], "event.outcomes", maximum=320),
        "evidence_ids": event_evidence_ids,
    }
    if not set(major_fact_ids).issubset(fact_ids):
        raise ValueError("Stage 3 event input references an unknown fact ID.")
    if not set(event_evidence_ids).issubset(evidence_ids):
        raise ValueError("Stage 3 event input references an unknown evidence ID.")
    if not set(event_characters).issubset(characters):
        raise ValueError("Stage 3 event input references an unsupported character.")
    return normalized


def build_reconciliation_request(
    *,
    run_id: str,
    chunk_id: str,
    scope_id: str,
    events: list[dict[str, object]],
    ordered_event_ids: tuple[str, ...],
    evidence_ids: frozenset[str],
    fact_ids: frozenset[str],
) -> OrganizationRequest:
    """Build Stage 2 from validated event candidates within one scene."""
    normalized_events = [_normalize_reconciliation_event(event) for event in events]
    normalized_ids = tuple(str(event["id"]) for event in normalized_events)
    if normalized_ids != ordered_event_ids:
        raise ValueError("Stage 2 event IDs must exactly match deterministic order.")
    request = OrganizationRequest(
        run_id=run_id,
        chunk_id=chunk_id,
        scope_id=scope_id,
        stage=OrganizationStage.RECONCILE,
        payload={"stage": "reconcile", "scope_id": scope_id, "events": normalized_events},
        constraints=OrganizationConstraints(
            ordered_member_ids=ordered_event_ids,
            required_member_ids=frozenset(ordered_event_ids),
            fact_ids=fact_ids,
            evidence_ids=evidence_ids,
        ),
    )
    _ensure_request_prompts_fit(request)
    return request


def build_arc_request(
    *,
    run_id: str,
    chunk_id: str,
    scope_id: str,
    event_summaries: list[dict[str, object]],
    ordered_event_ids: tuple[str, ...],
    evidence_ids: frozenset[str],
    fact_ids: frozenset[str],
    characters: frozenset[str],
    local_connectivity: list[dict[str, str]],
) -> OrganizationRequest:
    """Build Stage 3 without full dialogue or model-authored connectivity."""
    normalized_events = [
        _normalize_arc_event(
            event,
            fact_ids=fact_ids,
            evidence_ids=evidence_ids,
            characters=characters,
        )
        for event in event_summaries
    ]
    normalized_ids = tuple(str(event["id"]) for event in normalized_events)
    if normalized_ids != ordered_event_ids:
        raise ValueError("Stage 3 event IDs must exactly match deterministic order.")
    normalized_connectivity: list[dict[str, str]] = []
    allowed_ids = set(ordered_event_ids)
    for edge in local_connectivity:
        if set(edge) not in ({"source", "target"}, {"source", "target", "kind"}):
            raise ValueError("Stage 3 connectivity contains forbidden fields.")
        source = _string(edge.get("source"), "connectivity.source")
        target = _string(edge.get("target"), "connectivity.target")
        if source not in allowed_ids or target not in allowed_ids:
            raise ValueError("Stage 3 connectivity references an unknown event ID.")
        normalized_edge = {"source": source, "target": target}
        if "kind" in edge:
            normalized_edge["kind"] = _string(edge["kind"], "connectivity.kind")
        normalized_connectivity.append(normalized_edge)
    request = OrganizationRequest(
        run_id=run_id,
        chunk_id=chunk_id,
        scope_id=scope_id,
        stage=OrganizationStage.ARCS,
        payload={
            "stage": "arcs",
            "scope_id": scope_id,
            "events": normalized_events,
            "local_connectivity": normalized_connectivity,
        },
        constraints=OrganizationConstraints(
            ordered_member_ids=ordered_event_ids,
            required_member_ids=frozenset(ordered_event_ids),
            fact_ids=fact_ids,
            evidence_ids=evidence_ids,
            character_names=characters,
        ),
    )
    _ensure_request_prompts_fit(request)
    return request
