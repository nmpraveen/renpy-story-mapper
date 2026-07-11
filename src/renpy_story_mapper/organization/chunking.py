"""Deterministic, evidence-aware input chunking for event organization."""

from __future__ import annotations

import json
from dataclasses import dataclass

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
    ordered = sorted(beats, key=lambda beat: (beat.scene_id, beat.order, beat.id))
    if len({beat.id for beat in ordered}) != len(ordered):
        raise ValueError("Beat IDs must be unique before chunking.")
    fact_by_id = {fact.id: fact for fact in (facts or [])}
    referenced_fact_ids = {fact_id for beat in ordered for fact_id in beat.fact_ids}
    missing_fact_ids = referenced_fact_ids - set(fact_by_id)
    if missing_fact_ids:
        raise ValueError("Every referenced fact ID must have an input fact record.")
    index_by_id = {beat.id: index for index, beat in enumerate(ordered)}
    requests: list[OrganizationRequest] = []
    for number, draft in enumerate(_partition(ordered), start=1):
        first = index_by_id[draft.beats[0].id]
        last = index_by_id[draft.beats[-1].id]
        context: list[BeatRecord] = []
        for candidate in reversed(ordered[:first]):
            if candidate.scene_id == draft.scene_id and candidate.is_context_candidate:
                context.insert(0, candidate)
                if len(context) == MAX_CONTEXT_BEATS:
                    break
        for candidate in ordered[last + 1 :]:
            if len(context) == MAX_CONTEXT_BEATS:
                break
            if candidate.scene_id == draft.scene_id and candidate.is_context_candidate:
                context.append(candidate)
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
        payload: dict[str, object] = {
            "stage": OrganizationStage.EVENTS.value,
            "scope_id": scope_id,
            "scene_id": draft.scene_id,
            "assigned_beat_ids": list(assigned_ids),
            "context_beat_ids": sorted(context_ids),
            "beats": [
                _beat_payload(beat, context=beat.id in context_ids)
                for beat in sorted((*draft.beats, *context), key=lambda item: item.order)
            ],
            "facts": [
                {
                    "id": fact_by_id[fid].id,
                    "expression": fact_by_id[fid].expression,
                    "normalized_value": fact_by_id[fid].normalized_value,
                    "certainty": fact_by_id[fid].certainty,
                    "evidence_ids": list(fact_by_id[fid].evidence_ids),
                }
                for fid in sorted(used_fact_ids)
                if fid in fact_by_id
            ],
        }
        if len(json.dumps(payload, ensure_ascii=False)) > MAX_CHARS:
            raise ValueError("A single organization chunk exceeds the 48,000-character limit.")
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
    return OrganizationRequest(
        run_id=run_id,
        chunk_id=chunk_id,
        scope_id=scope_id,
        stage=OrganizationStage.RECONCILE,
        payload={"stage": "reconcile", "scope_id": scope_id, "events": events},
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
    return OrganizationRequest(
        run_id=run_id,
        chunk_id=chunk_id,
        scope_id=scope_id,
        stage=OrganizationStage.ARCS,
        payload={
            "stage": "arcs",
            "scope_id": scope_id,
            "events": event_summaries,
            "local_connectivity": local_connectivity,
        },
        constraints=OrganizationConstraints(
            ordered_member_ids=ordered_event_ids,
            required_member_ids=frozenset(ordered_event_ids),
            fact_ids=fact_ids,
            evidence_ids=evidence_ids,
            character_names=characters,
        ),
    )
