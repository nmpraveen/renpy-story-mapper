"""Structural mapper validation and Python-owned Story Map V2 mechanics overlay."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from renpy_story_mapper.story_map_v2.contracts import (
    ArmLineageStep,
    ArmMechanic,
    ChoiceMechanic,
    ChunkExecutionResult,
    ChunkStatus,
    CoreBranchOutcome,
    CoreChunk,
    CoreEvent,
    EventAnchor,
    MapperEvent,
    MapperResponse,
    ProviderOrigin,
    Reachability,
    SourceSpan,
    StoryChunk,
    StoryScope,
    canonical_hash,
)
from renpy_story_mapper.story_map_v2.mapper_io import (
    MapperResponseValidationError,
    validate_mapper_response,
)
from renpy_story_mapper.story_map_v2.planner import mechanics_digest, render_chunk_raw_text


class MapperValidationError(ValueError):
    """A mapper response contradicts the small V2 structural contract."""


@dataclass(frozen=True)
class _SpanSlice:
    scope_index: int
    span: SourceSpan
    start_line: int
    end_line: int
    lineage: tuple[ArmLineageStep, ...]


def _chunk_authority(
    scope: StoryScope,
    chunk: StoryChunk,
) -> tuple[tuple[SourceSpan, ...], dict[str, ChoiceMechanic], dict[str, int]]:
    positions = {span.key: index for index, span in enumerate(scope.spans)}
    if len(chunk.span_keys) != len(set(chunk.span_keys)):
        raise MapperValidationError("chunk contains duplicate source span keys")
    try:
        ordered_positions = tuple(positions[key] for key in chunk.span_keys)
    except KeyError as exc:
        raise MapperValidationError(
            f"chunk references unknown source span {exc.args[0]!r}"
        ) from exc
    if ordered_positions != tuple(sorted(ordered_positions)):
        raise MapperValidationError("chunk source spans are out of source order")
    chunk_spans = tuple(scope.spans[index] for index in ordered_positions)
    choices = {choice.key: choice for choice in scope.choices}
    if len(chunk.choice_keys) != len(set(chunk.choice_keys)):
        raise MapperValidationError("chunk contains duplicate choice keys")
    for key in chunk.choice_keys:
        if key not in choices:
            raise MapperValidationError(f"chunk references unknown choice key {key!r}")
    expected_choice_keys = tuple(
        dict.fromkeys(key for span in chunk_spans for key in span.choice_keys)
    )
    expected_raw_text = render_chunk_raw_text(chunk_spans)
    expected_mechanics = mechanics_digest(scope, expected_choice_keys)
    expected_hash = canonical_hash(
        {
            "source_identity": scope.source_identity,
            "source_generation": scope.source_generation,
            "canonical_hash": scope.canonical_hash,
            "span_keys": list(chunk.span_keys),
            "raw_text": expected_raw_text,
            "mechanics": expected_mechanics,
            "density": asdict(chunk.density),
        }
    )
    if (
        chunk.choice_keys != expected_choice_keys
        or chunk.raw_text != expected_raw_text
        or chunk.raw_tokens != sum(span.estimated_tokens for span in chunk_spans)
        or chunk.mechanics != expected_mechanics
        or chunk.packet_hash != expected_hash
    ):
        raise MapperValidationError("chunk packet does not match the current deterministic scope")
    return chunk_spans, choices, positions


def _arm(choice: ChoiceMechanic, order: int) -> ArmMechanic | None:
    return next((item for item in choice.arms if item.order == order), None)


def _is_prefix(prefix: tuple[ArmLineageStep, ...], value: tuple[ArmLineageStep, ...]) -> bool:
    return len(prefix) <= len(value) and value[: len(prefix)] == prefix


def _validate_lineage(
    lineage: tuple[ArmLineageStep, ...], choices: dict[str, ChoiceMechanic]
) -> None:
    seen: set[str] = set()
    declared_parent_lineages = tuple(choice.parent_lineage for choice in choices.values())
    for index, step in enumerate(lineage):
        if step.choice_key in seen:
            raise MapperValidationError("authoritative arm lineage repeats a choice key")
        seen.add(step.choice_key)
        choice = choices.get(step.choice_key)
        if choice is None:
            prefix = lineage[: index + 1]
            if any(parent[: len(prefix)] == prefix for parent in declared_parent_lineages):
                continue
            raise MapperValidationError(
                "authoritative arm lineage is not a complete outer-to-inner prefix; "
                f"unknown choice {step.choice_key!r}"
            )
        if _arm(choice, step.arm_order) is None:
            raise MapperValidationError(
                f"arm lineage references unknown arm {step.arm_order} for {step.choice_key!r}"
            )
        if choice.parent_lineage != lineage[:index]:
            raise MapperValidationError(
                f"arm lineage is not complete outer-to-inner at choice {step.choice_key!r}"
            )


def _effective_lineage(
    span: SourceSpan,
    start_line: int,
    end_line: int,
    choices: dict[str, ChoiceMechanic],
) -> tuple[ArmLineageStep, ...]:
    _validate_lineage(span.arm_lineage, choices)
    candidates: list[tuple[ArmLineageStep, ...]] = []
    for key in span.choice_keys:
        choice = choices.get(key)
        if choice is None or choice.relative_path != span.relative_path:
            continue
        for mechanic in choice.arms:
            overlaps = start_line <= mechanic.end_line and end_line >= mechanic.start_line
            contained = start_line >= mechanic.start_line and end_line <= mechanic.end_line
            if overlaps and not contained:
                raise MapperValidationError(
                    f"source range crosses an authoritative arm boundary for choice {key!r}"
                )
            if contained:
                candidates.append(
                    (*choice.parent_lineage, ArmLineageStep(choice.key, mechanic.order))
                )
        rejoin_lines = {
            mechanic.rejoin_line
            for mechanic in choice.arms
            if mechanic.rejoin_node_id is not None and mechanic.rejoin_line is not None
        }
        if rejoin_lines and start_line >= min(rejoin_lines) and not span.shared_continuation:
            raise MapperValidationError(
                f"source range uses an unproven shared continuation for choice {key!r}"
            )

    if candidates:
        deepest = max(candidates, key=len)
        if not all(_is_prefix(candidate, deepest) for candidate in candidates):
            raise MapperValidationError("source range has incompatible nested arm lineage")
        if span.arm_lineage and span.arm_lineage != deepest:
            raise MapperValidationError(
                "source span lineage disagrees with deterministic choice ownership"
            )
        lineage = span.arm_lineage or deepest
    else:
        lineage = span.arm_lineage
    if span.shared_continuation and lineage:
        for key in span.choice_keys:
            choice = choices.get(key)
            if choice is None:
                continue
            rejoin_lines = {
                mechanic.rejoin_line
                for mechanic in choice.arms
                if mechanic.rejoin_node_id is not None and mechanic.rejoin_line is not None
            }
            if rejoin_lines and start_line >= min(rejoin_lines):
                lineage = choice.parent_lineage
    return lineage


def _cover_range(
    chunk_spans: tuple[SourceSpan, ...],
    positions: dict[str, int],
    choices: dict[str, ChoiceMechanic],
    event: MapperEvent,
) -> tuple[_SpanSlice, ...]:
    same_path = [span for span in chunk_spans if span.relative_path == event.relative_path]
    if not same_path:
        raise MapperValidationError(
            f"mapper event references path {event.relative_path!r} outside the exact chunk"
        )
    path_start = min(span.start_line for span in same_path)
    path_end = max(span.end_line for span in same_path)
    if event.start_line < path_start or event.end_line > path_end:
        raise MapperValidationError("mapper event range extends outside the exact chunk spans")
    intersecting = [
        span
        for span in same_path
        if span.start_line <= event.end_line and span.end_line >= event.start_line
    ]
    if not intersecting:
        raise MapperValidationError("mapper event range is outside the exact chunk spans")

    return tuple(
        _SpanSlice(
            scope_index=positions[span.key],
            span=span,
            start_line=max(event.start_line, span.start_line),
            end_line=min(event.end_line, span.end_line),
            lineage=_effective_lineage(
                span,
                max(event.start_line, span.start_line),
                min(event.end_line, span.end_line),
                choices,
            ),
        )
        for span in sorted(intersecting, key=lambda item: positions[item.key])
    )


def _common_lineage(
    slices: tuple[_SpanSlice, ...],
) -> tuple[tuple[ArmLineageStep, ...], bool]:
    lineages = tuple(dict.fromkeys(item.lineage for item in slices))
    common = lineages[0]
    for lineage in lineages[1:]:
        shared = 0
        for left, right in zip(common, lineage, strict=False):
            if left != right:
                break
            shared += 1
        common = common[:shared]
    return common, len(lineages) > 1


def _range_warnings(
    original: MapperEvent,
    event: MapperEvent,
    slices: tuple[_SpanSlice, ...],
) -> tuple[str, ...]:
    warnings: list[str] = []
    ordered = sorted(slices, key=lambda item: (item.start_line, item.end_line, item.scope_index))
    retained_start = ordered[0].start_line
    retained_end = max(item.end_line for item in ordered)
    covered_through = ordered[0].end_line
    has_gap = retained_start != event.start_line or retained_end != event.end_line
    for item in ordered[1:]:
        if item.start_line > covered_through + 1:
            has_gap = True
        covered_through = max(covered_through, item.end_line)
    if has_gap:
        warnings.append(
            "Mapper range included omitted technical lines; exact authority is limited to "
            "retained story spans."
        )
    if event.end_line != original.end_line:
        warnings.append(
            "Overlapping rough mapper ranges were deterministically partitioned at the next "
            "event start."
        )
    return tuple(warnings)


def _partition_events(
    events: tuple[MapperEvent, ...],
) -> tuple[tuple[MapperEvent, MapperEvent], ...]:
    partitioned: list[tuple[MapperEvent, MapperEvent]] = []
    for index, original in enumerate(events):
        event = original
        if index + 1 < len(events):
            following = events[index + 1]
            if following.relative_path == event.relative_path:
                if following.start_line <= event.start_line:
                    raise MapperValidationError(
                        "mapper events are not in chronological source order"
                    )
                if following.start_line <= event.end_line:
                    event = replace(event, end_line=following.start_line - 1)
        partitioned.append((original, event))
    return tuple(partitioned)


def _first_node(slices: tuple[_SpanSlice, ...]) -> tuple[str, int, int]:
    for item in slices:
        if item.span.canonical_node_ids:
            return item.span.canonical_node_ids[0], item.start_line, item.scope_index
    raise MapperValidationError("mapper range covers no canonical story node")


def _lineage_mechanic(
    lineage: tuple[ArmLineageStep, ...], choices: dict[str, ChoiceMechanic]
) -> ArmMechanic | None:
    if not lineage:
        return None
    step = lineage[-1]
    choice = choices.get(step.choice_key)
    return _arm(choice, step.arm_order) if choice is not None else None


def _event_authority(
    slices: tuple[_SpanSlice, ...],
    mechanic: ArmMechanic | None,
    mapper_warning: str | None,
    overlay_warnings: tuple[str, ...],
    *,
    mixed_lineage: bool,
) -> tuple[Reachability, tuple[str, ...]]:
    statuses = [item.span.reachability for item in slices]
    warnings = [warning for item in slices for warning in item.span.unresolved_warnings]
    if mechanic is not None:
        statuses.append(mechanic.reachability)
        warnings.extend(mechanic.unresolved_warnings)
    if mapper_warning is not None:
        warnings.append(mapper_warning)
    warnings.extend(overlay_warnings)
    if mixed_lineage:
        reachability = Reachability.UNRESOLVED
        warnings.append(
            "Mapper event covers multiple deterministic lineages; the anchor uses only their "
            "common proven prefix."
        )
    elif statuses and all(status is statuses[0] for status in statuses):
        reachability = statuses[0]
    else:
        reachability = Reachability.UNRESOLVED
        warnings.append("Covered deterministic authority has mixed reachability.")
    if reachability is Reachability.UNRESOLVED and not warnings:
        warnings.append("Deterministic reachability remains unresolved.")
    return reachability, tuple(dict.fromkeys(warnings))


def _anchor(
    scope: StoryScope,
    *,
    canonical_node_id: str,
    relative_path: str,
    line: int,
    lineage: tuple[ArmLineageStep, ...],
    destination_id: str | None,
) -> EventAnchor:
    value = {
        "source_generation": scope.source_generation,
        "canonical_authority": scope.canonical_hash,
        "canonical_node_id": canonical_node_id,
        "relative_path": relative_path,
        "line": line,
        "arm_lineage": [
            {"choice_key": step.choice_key, "arm_order": step.arm_order} for step in lineage
        ],
        "destination_id": destination_id,
    }
    return EventAnchor(
        id=f"story-map-event:{canonical_hash(value)}",
        canonical_node_id=canonical_node_id,
        relative_path=relative_path,
        line=line,
        arm_lineage=lineage,
        destination_id=destination_id,
    )


def _core_event(
    scope: StoryScope,
    original: MapperEvent,
    event: MapperEvent,
    slices: tuple[_SpanSlice, ...],
    choices: dict[str, ChoiceMechanic],
) -> CoreEvent:
    lineage, mixed_lineage = _common_lineage(slices)
    mechanic = _lineage_mechanic(lineage, choices)
    canonical_node_id, first_line, _scope_index = _first_node(slices)
    reachability, warnings = _event_authority(
        slices,
        mechanic,
        event.warning,
        _range_warnings(original, event, slices),
        mixed_lineage=mixed_lineage,
    )
    return CoreEvent(
        title=event.title,
        summary=event.summary,
        relative_path=event.relative_path,
        start_line=min(item.start_line for item in slices),
        end_line=max(item.end_line for item in slices),
        characters=event.characters,
        warnings=warnings,
        anchor=_anchor(
            scope,
            canonical_node_id=canonical_node_id,
            relative_path=event.relative_path,
            line=first_line,
            lineage=lineage,
            destination_id=mechanic.destination_id if mechanic is not None else None,
        ),
        reachability=reachability,
    )


def _choice_position(
    choice: ChoiceMechanic,
    chunk_spans: tuple[SourceSpan, ...],
    positions: dict[str, int],
) -> int:
    direct = [
        positions[span.key]
        for span in chunk_spans
        if span.relative_path == choice.relative_path
        and span.start_line <= choice.line <= span.end_line
    ]
    referenced = [positions[span.key] for span in chunk_spans if choice.key in span.choice_keys]
    candidates = direct or referenced
    if not candidates:
        raise MapperValidationError(f"choice {choice.key!r} is absent from the exact chunk spans")
    return min(candidates)


def _branch_outcome(
    scope: StoryScope,
    chunk_spans: tuple[SourceSpan, ...],
    positions: dict[str, int],
    choices: dict[str, ChoiceMechanic],
    choice: ChoiceMechanic,
    mechanic: ArmMechanic,
    summary: str,
) -> CoreBranchOutcome:
    lineage = (*choice.parent_lineage, ArmLineageStep(choice.key, mechanic.order))
    _validate_lineage(lineage, choices)
    candidates: list[_SpanSlice] = []
    for span in chunk_spans:
        if span.relative_path != choice.relative_path:
            continue
        start_line = max(span.start_line, mechanic.start_line)
        end_line = min(span.end_line, mechanic.end_line)
        if start_line > end_line:
            continue
        effective = _effective_lineage(span, start_line, end_line, choices)
        if _is_prefix(lineage, effective):
            candidates.append(
                _SpanSlice(positions[span.key], span, start_line, end_line, effective)
            )
    if not candidates:
        raise MapperValidationError(
            f"branch summary for {choice.key!r} arm {mechanic.order} has no chunk arm span"
        )
    canonical_node_id, first_line, _scope_index = _first_node(
        tuple(sorted(candidates, key=lambda item: item.scope_index))
    )
    warnings = tuple(dict.fromkeys(mechanic.unresolved_warnings))
    if mechanic.reachability is Reachability.UNRESOLVED and not warnings:
        warnings = ("Deterministic branch reachability remains unresolved.",)
    return CoreBranchOutcome(
        choice_key=choice.key,
        arm_order=mechanic.order,
        caption=mechanic.caption,
        summary=summary,
        anchor=_anchor(
            scope,
            canonical_node_id=canonical_node_id,
            relative_path=choice.relative_path,
            line=first_line,
            lineage=lineage,
            destination_id=mechanic.destination_id,
        ),
        reachability=mechanic.reachability,
        warnings=warnings,
    )


def _validate_execution(
    execution: ChunkExecutionResult,
    *,
    chunk_identity: str,
    origin: ProviderOrigin,
    status: ChunkStatus,
    response: MapperResponse,
) -> None:
    if execution.chunk_identity != chunk_identity:
        raise MapperValidationError("execution chunk identity does not match the overlaid chunk")
    if execution.origin is not origin:
        raise MapperValidationError("execution origin does not match the overlaid chunk")
    if execution.status is not status:
        raise MapperValidationError("execution status does not match the overlaid chunk")
    if status is ChunkStatus.COMPLETE and execution.response is None:
        raise MapperValidationError("complete execution must retain the overlaid mapper response")
    if execution.response is not None and execution.response != response:
        raise MapperValidationError(
            "execution mapper response does not match the overlaid response"
        )


def validate_and_overlay(
    scope: StoryScope,
    chunk: StoryChunk,
    response: MapperResponse,
    *,
    origin: ProviderOrigin,
    execution: ChunkExecutionResult | None = None,
) -> CoreChunk:
    """Validate mapper meaning and overlay exact Python mechanics, status, and anchors."""

    try:
        validate_mapper_response(response)
    except MapperResponseValidationError as exc:
        raise MapperValidationError(str(exc)) from exc
    if type(origin) is not ProviderOrigin or origin is ProviderOrigin.MISSING:
        raise MapperValidationError("a valid mapper response requires a concrete provider origin")
    chunk_spans, choices, positions = _chunk_authority(scope, chunk)

    events: list[CoreEvent] = []
    previous_end: tuple[int, int] | None = None
    for original, event in _partition_events(response.events):
        slices = _cover_range(chunk_spans, positions, choices, event)
        first = min((item.scope_index, item.start_line) for item in slices)
        last = max((item.scope_index, item.end_line) for item in slices)
        if previous_end is not None and first <= previous_end:
            raise MapperValidationError(
                "mapper events overlap or are out of chronological source order"
            )
        previous_end = last
        events.append(_core_event(scope, original, event, slices, choices))

    outcomes: list[CoreBranchOutcome] = []
    previous_branch: tuple[int, int] | None = None
    for summary in response.branch_summaries:
        choice = choices.get(summary.choice_key)
        if choice is None or summary.choice_key not in chunk.choice_keys:
            raise MapperValidationError(
                f"branch summary references unknown chunk choice {summary.choice_key!r}"
            )
        mechanic = _arm(choice, summary.arm_order)
        if mechanic is None:
            raise MapperValidationError(
                f"branch summary references unknown arm {summary.arm_order} "
                f"for choice {summary.choice_key!r}"
            )
        if not choice.story_choice:
            continue
        order = (_choice_position(choice, chunk_spans, positions), mechanic.order)
        if previous_branch is not None and order <= previous_branch:
            raise MapperValidationError("branch summaries are out of deterministic source order")
        previous_branch = order
        outcomes.append(
            _branch_outcome(
                scope,
                chunk_spans,
                positions,
                choices,
                choice,
                mechanic,
                summary.outcome_summary,
            )
        )

    exact_choices = tuple(choices[key] for key in chunk.choice_keys if choices[key].story_choice)
    has_narrative = bool(events or outcomes)
    status = ChunkStatus.COMPLETE if has_narrative else ChunkStatus.PARTIAL
    if execution is not None:
        _validate_execution(
            execution,
            chunk_identity=chunk.identity,
            origin=origin,
            status=status,
            response=response,
        )
    return CoreChunk(
        chunk_identity=chunk.identity,
        status=status,
        origin=origin,
        events=tuple(events),
        choices=exact_choices,
        branch_outcomes=tuple(outcomes),
        scope_title=response.scope_title,
        scope_overview=response.scope_overview,
        execution=execution,
        warnings=(
            ()
            if has_narrative
            else ("Mapper response contained no event or branch-outcome summary.",)
        ),
    )
