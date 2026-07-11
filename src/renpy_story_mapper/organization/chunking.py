"""Deterministic, evidence-aware input chunking for event organization."""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import pairwise

from renpy_story_mapper.organization.contracts import (
    BeatRecord,
    FactRecord,
    OrganizationConstraints,
    OrganizationRequest,
    OrganizationStage,
)

MAX_CHARS = 48_000
MAX_ASSIGNED_BEATS = 120
MAX_CONTEXT_BEATS = 2
_BOUNDARY_KINDS = {"choice", "jump", "return", "condition"}
_OMITTED_TECHNICAL_KINDS = {"technical", "opaque", "command", "audio", "image", "pause"}


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
    if beat.speaker:
        value["speaker"] = beat.speaker
    if beat.text and beat.kind not in _OMITTED_TECHNICAL_KINDS:
        value["text"] = beat.text
    if beat.condition:
        value["condition"] = beat.condition
    return value


def _size(beats: list[BeatRecord]) -> int:
    return len(
        json.dumps(
            [_beat_payload(beat, context=False) for beat in beats],
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _partition(beats: list[BeatRecord]) -> list[_ChunkDraft]:
    drafts: list[_ChunkDraft] = []
    current: list[BeatRecord] = []
    current_scene = ""
    for beat in beats:
        scene_changed = bool(current and beat.scene_id != current_scene)
        would_overflow = bool(
            current
            and (len(current) >= MAX_ASSIGNED_BEATS or _size([*current, beat]) > MAX_CHARS)
        )
        if scene_changed or would_overflow:
            drafts.append(_ChunkDraft(current_scene, tuple(current)))
            current = []
        current_scene = beat.scene_id
        current.append(beat)
        if beat.kind in _BOUNDARY_KINDS and len(current) > 1:
            drafts.append(_ChunkDraft(current_scene, tuple(current)))
            current = []
    if current:
        drafts.append(_ChunkDraft(current_scene, tuple(current)))
    return drafts


def build_event_chunks(
    *,
    run_id: str,
    scope_id: str,
    beats: list[BeatRecord],
    facts: list[FactRecord] | None = None,
) -> list[OrganizationRequest]:
    """Build Stage-1 chunks; assigned membership never overlaps between chunks."""
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
    fitted: list[tuple[_ChunkDraft, list[BeatRecord], dict[str, object]]] = []
    pending = _partition(ordered)
    while pending:
        draft = pending.pop(0)
        first = index_by_id[draft.beats[0].id]
        last = index_by_id[draft.beats[-1].id]
        candidates: list[tuple[int, int, BeatRecord]] = []
        for index in range(first - 1, -1, -1):
            candidate = ordered[index]
            if candidate.scene_id != draft.scene_id:
                break
            if candidate.is_context_candidate:
                candidates.append((first - index, index, candidate))
        for index in range(last + 1, len(ordered)):
            candidate = ordered[index]
            if candidate.scene_id != draft.scene_id:
                break
            if candidate.is_context_candidate:
                candidates.append((index - last, index, candidate))
        context_priority = [
            item[2] for item in sorted(candidates, key=lambda item: (item[0], item[1]))
        ][:MAX_CONTEXT_BEATS]
        context = list(context_priority)
        payload = _event_payload(
            scope_id=scope_id,
            draft=draft,
            context=context,
            fact_by_id=fact_by_id,
            index_by_id=index_by_id,
        )
        while context and _payload_size(payload) > MAX_CHARS:
            context.pop()
            payload = _event_payload(
                scope_id=scope_id,
                draft=draft,
                context=context,
                fact_by_id=fact_by_id,
                index_by_id=index_by_id,
            )
        if _payload_size(payload) > MAX_CHARS:
            if len(draft.beats) == 1:
                raise ValueError("A single organization chunk exceeds the 48,000-character limit.")
            midpoint = len(draft.beats) // 2
            pending[0:0] = [
                _ChunkDraft(draft.scene_id, draft.beats[:midpoint]),
                _ChunkDraft(draft.scene_id, draft.beats[midpoint:]),
            ]
            continue
        fitted.append((draft, context, payload))

    requests: list[OrganizationRequest] = []
    for number, (draft, context, payload) in enumerate(fitted, start=1):
        assigned_ids = tuple(beat.id for beat in draft.beats)
        context_ids = frozenset(beat.id for beat in context)
        used_fact_ids = frozenset(fid for beat in draft.beats for fid in beat.fact_ids)
        used_evidence_ids = frozenset(
            evidence_id for beat in (*draft.beats, *context) for evidence_id in beat.evidence_ids
        ).union(
            evidence_id
            for fact_id in used_fact_ids
            for evidence_id in fact_by_id[fact_id].evidence_ids
        )
        characters = frozenset(
            beat.speaker for beat in (*draft.beats, *context) if beat.speaker is not None
        )
        requests.append(
            OrganizationRequest(
                run_id=run_id,
                chunk_id=f"{scope_id}:events:{number}",
                scope_id=scope_id,
                stage=OrganizationStage.EVENTS,
                payload=payload,
                constraints=OrganizationConstraints(
                    ordered_member_ids=assigned_ids,
                    required_member_ids=frozenset(
                        beat.id for beat in draft.beats if beat.requires_coverage
                    ),
                    context_member_ids=context_ids,
                    fact_ids=used_fact_ids,
                    evidence_ids=used_evidence_ids,
                    character_names=characters,
                ),
            )
        )
    return requests


def _payload_size(payload: dict[str, object]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


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
            for beat in sorted(
                (*draft.beats, *context), key=lambda item: index_by_id[item.id]
            )
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


def _string_list(
    value: object, field: str, *, maximum: int | None = None
) -> list[str]:
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
                normalized[field] = _string_list(
                    event[field], f"event.{field}", maximum=maximum
                )
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
    return OrganizationRequest(
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
    return OrganizationRequest(
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
