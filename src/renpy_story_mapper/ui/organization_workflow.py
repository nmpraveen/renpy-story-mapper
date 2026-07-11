"""UI-facing orchestration over the accepted M05 organization contracts.

The workflow owns no graph authority and no persistence schema.  It adapts bounded M01-M04
presentation records into provider requests, delegates validation to the organization package,
and persists only through :class:`StoryOrganizationService`.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol, cast

import renpy_story_mapper.organization.contracts as organization_contracts
from renpy_story_mapper.organization import (
    BeatRecord,
    CodexMode,
    FactRecord,
    OrganizationChunkResult,
    OrganizationProvider,
    OrganizationRequest,
    build_event_chunks,
    validate_result,
)
from renpy_story_mapper.organization.chunking import (
    build_arc_request,
    build_reconciliation_request,
)
from renpy_story_mapper.organization.contracts import (
    OrganizationGroup,
    OrganizationStage,
    ProviderState,
)
from renpy_story_mapper.organization.errors import (
    ConsentRequiredError,
    OrganizationCancelledError,
    OrganizationError,
)
from renpy_story_mapper.presentation import (
    EvidenceRecord,
    PresentationEdge,
    PresentationLevel,
    PresentationNode,
    PresentationRequest,
    PresentationService,
)
from renpy_story_mapper.presentation import (
    FactRecord as PresentationFactRecord,
)
from renpy_story_mapper.project import Project

PROMPT_VERSION = "m05-story-organizer-v1"
SCHEMA_VERSION = "m05-organization-v1"
ARC_MAX_CHARS = int(getattr(organization_contracts, "MAX_PROMPT_CHARS", 48_000))
ARC_MAX_EVENTS = 120
ARC_MAX_GROUPS = 12
ARC_MAX_RECONCILIATION_DEPTH = 32


class CancelCheck(Protocol):
    def __call__(self) -> bool: ...


class ConsentCallback(Protocol):
    def __call__(self, run_id: str) -> bool: ...


@dataclass(frozen=True)
class OrganizationOptions:
    mode: CodexMode = CodexMode.CODEX_LMSTUDIO
    model_profile: str = "balanced"
    model: str | None = None
    prompt_version: str = PROMPT_VERSION
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class WorkflowResult:
    run_id: str
    draft_id: str
    cache_hits: int
    provider_calls: int
    elapsed_ms: int
    event_count: int
    arc_count: int


@dataclass(frozen=True)
class _EventCandidate:
    id: str
    title: str
    summary: str
    beat_ids: tuple[str, ...]
    characters: tuple[str, ...]
    importance: str
    outcomes: tuple[str, ...]
    fact_ids: tuple[str, ...]
    claims: tuple[tuple[str, tuple[str, ...]], ...]
    warnings: tuple[str, ...]


class OrganizationWorkflow:
    """Run the approved three-stage organizer without blocking or mutating accepted state."""

    def __init__(
        self,
        project: Project,
        provider_factory: Callable[[CodexMode], OrganizationProvider],
    ) -> None:
        self._project = project
        self._provider_factory = provider_factory

    def organize(
        self,
        scope_ids: Sequence[str],
        options: OrganizationOptions,
        *,
        progress: Callable[[int, str], None],
        cancelled: CancelCheck,
        confirm_cloud: ConsentCallback | None = None,
    ) -> WorkflowResult:
        if not scope_ids:
            raise ValueError("Select at least one deterministic story scope.")
        if not options.model_profile.strip():
            raise ValueError("Model profile cannot be empty.")
        requested_model = options.model.strip() if options.model is not None else None
        if options.model is not None and not requested_model:
            raise ValueError("Explicit model identifier cannot be empty.")
        run_id = uuid.uuid4().hex
        if options.mode is CodexMode.CODEX_CHATGPT:
            if confirm_cloud is None or not confirm_cloud(run_id):
                raise ConsentRequiredError("Cloud organization requires confirmation for this run.")
            cloud_consent_run_id: str | None = run_id
        else:
            cloud_consent_run_id = None

        provider = self._provider_factory(options.mode)
        if requested_model is not None:
            configure_model = getattr(provider, "set_model_override", None)
            if not callable(configure_model):
                raise OrganizationError(
                    "Explicit model selection is unavailable in this provider version."
                )
            configure_model(requested_model)
        status = provider.status()
        if status.state is not ProviderState.READY or status.executable is None:
            raise OrganizationError(status.message or "The selected organizer is unavailable.")
        status_model = getattr(status, "model_identifier", None)
        if requested_model is not None and status_model != requested_model:
            raise OrganizationError(
                "The provider did not confirm the explicitly selected model."
            )

        def raise_if_cancelled() -> None:
            if cancelled():
                provider.cancel()
                raise OrganizationCancelledError("Story organization was cancelled.")

        raise_if_cancelled()
        service = self._project.organization_service()
        generation = _project_generation(self._project)
        effective_model_identifier = requested_model or (
            status_model if isinstance(status_model, str) and status_model.strip() else None
        )
        raise_if_cancelled()
        service.create_run(
            provider_mode=options.mode.value,
            model_profile=options.model_profile,
            model_fingerprint=effective_model_identifier,
            prompt_version=options.prompt_version,
            output_schema_version=options.schema_version,
            generation=generation,
            run_id=run_id,
        )
        started = time.perf_counter()
        cache_hits = 0
        provider_calls = 0
        input_tokens = 0
        output_tokens = 0
        input_tokens_observed = False
        output_tokens_observed = False
        ordinal = 0
        draft_id: str | None = None

        def run_usage() -> dict[str, object]:
            usage: dict[str, object] = {
                "cache_hits": cache_hits,
                "provider_calls": provider_calls,
            }
            cli_version = getattr(status, "cli_version", None)
            if isinstance(cli_version, str) and cli_version.strip():
                usage["cli_version"] = cli_version.strip()
            context_window = getattr(status, "context_window_tokens", None)
            if isinstance(context_window, int) and context_window > 0:
                usage["context_window_tokens"] = context_window
            if input_tokens_observed:
                usage["input_tokens"] = input_tokens
            if output_tokens_observed:
                usage["output_tokens"] = output_tokens
            return usage

        def execute(
            request: OrganizationRequest, percent: int, label: str
        ) -> OrganizationChunkResult:
            nonlocal cache_hits, provider_calls, ordinal, effective_model_identifier
            nonlocal input_tokens, output_tokens
            nonlocal input_tokens_observed, output_tokens_observed
            raise_if_cancelled()
            request = replace(
                request,
                run_id=run_id,
                cloud_consent_run_id=cloud_consent_run_id,
                model=requested_model,
            )
            payload_bytes = json.dumps(
                request.payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
            input_hash = hashlib.sha256(payload_bytes).hexdigest()
            # An unresolved provider default is deliberately run-local. Reusing a cache entry
            # without knowing that the effective model still matches would violate the M05
            # cache identity contract.
            cache_model_key = effective_model_identifier or (
                f"<provider-default-unresolved:{run_id}>"
            )
            identity = service.cache_identity(
                provider_mode=options.mode.value,
                model_profile=options.model_profile,
                model_fingerprint=cache_model_key,
                prompt_version=options.prompt_version,
                output_schema_version=options.schema_version,
                input_hash=input_hash,
                ordered_ids=request.constraints.ordered_member_ids,
            )
            cached = service.cache_result(identity)
            raise_if_cancelled()
            progress(percent, f"{label} - checking cache")
            if cached is not None:
                result = validate_result(cached, request)
                raise_if_cancelled()
                cache_state: Literal["hit", "stored"] = "hit"
                cache_hits += 1
            else:
                provider_calls += 1
                result = provider.organize(
                    request,
                    lambda value, text: progress(
                        min(98, percent + max(0, min(10, value // 10))), text
                    ),
                    cancelled,
                )
                raise_if_cancelled()
                metadata = result.metadata
                if metadata is not None and isinstance(metadata.input_tokens, int):
                    input_tokens += metadata.input_tokens
                    input_tokens_observed = True
                if metadata is not None and isinstance(metadata.output_tokens, int):
                    output_tokens += metadata.output_tokens
                    output_tokens_observed = True
                reported_model = (
                    None if metadata is None else metadata.model_identifier
                )
                if reported_model:
                    if (
                        effective_model_identifier is not None
                        and effective_model_identifier != reported_model
                    ):
                        raise OrganizationError(
                            "The organizer reported inconsistent model identifiers."
                        )
                    effective_model_identifier = reported_model
                    update_model = getattr(service, "set_run_model_fingerprint", None)
                    if not callable(update_model):
                        raise OrganizationError(
                            "Effective model recording is unavailable in this project version."
                        )
                    raise_if_cancelled()
                    update_model(run_id, reported_model)
                    identity = service.cache_identity(
                        provider_mode=options.mode.value,
                        model_profile=options.model_profile,
                        model_fingerprint=reported_model,
                        prompt_version=options.prompt_version,
                        output_schema_version=options.schema_version,
                        input_hash=input_hash,
                        ordered_ids=request.constraints.ordered_member_ids,
                    )
                raise_if_cancelled()
                service.store_cache_result(identity, result.raw_normalized)
                cache_state = "stored"
            raise_if_cancelled()
            service.record_chunk(
                run_id=run_id,
                scope_id=request.scope_id,
                reconciliation_scope=(
                    str(request.payload.get("scene_id", request.scope_id))
                    if request.stage.value == "events"
                    else request.scope_id
                ),
                ordinal=ordinal,
                identity=identity,
                cache_state=cache_state,
                status="validated",
                result=result.raw_normalized,
                chunk_id=f"{run_id}:{ordinal:05d}",
            )
            raise_if_cancelled()
            ordinal += 1
            return result

        try:
            progress(2, "Preparing deterministic story evidence")
            beats, facts = collect_organization_input(self._project, scope_ids, cancelled)
            stage_one_requests = build_event_chunks(
                run_id=run_id,
                scope_id="selected-story",
                beats=list(beats),
                facts=list(facts),
            )
            stage_one: list[tuple[OrganizationRequest, OrganizationChunkResult]] = []
            for index, request in enumerate(stage_one_requests):
                percent = 8 + int(38 * index / max(1, len(stage_one_requests)))
                stage_one.append((request, execute(request, percent, "Organizing events")))

            progress(48, "Reconciling neighboring events")
            reconciled, ungrouped_beats, connectivity = _reconcile_events(
                run_id,
                stage_one,
                execute,
            )
            progress(74, "Organizing story arcs")
            arc_result = _organize_arcs(run_id, reconciled, connectivity, execute)
            candidate = _candidate_payload(reconciled, ungrouped_beats, arc_result)
            raise_if_cancelled()
            create_scoped = getattr(service, "create_scoped_draft", None)
            if not callable(create_scoped):
                raise OrganizationError(
                    "Scoped organization is unavailable in this project version."
                )
            draft_id = cast(
                str,
                create_scoped(
                    run_id,
                    generation,
                    candidate,
                    scope_ids=tuple(scope_ids),
                    covered_beat_ids=tuple(beat.id for beat in beats),
                ),
            )
            raise_if_cancelled()
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            raise_if_cancelled()
            service.finish_run(
                run_id,
                "completed",
                elapsed_ms=elapsed_ms,
                usage=run_usage(),
            )
            progress(100, "Draft ready for review")
            return WorkflowResult(
                run_id,
                draft_id,
                cache_hits,
                provider_calls,
                elapsed_ms,
                len(cast(list[object], candidate["events"])),
                len(cast(list[object], candidate["arcs"])),
            )
        except BaseException as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            terminal: Literal["failed", "cancelled"] = (
                "cancelled" if isinstance(exc, OrganizationCancelledError) else "failed"
            )
            safe = (
                str(exc)
                if isinstance(exc, OrganizationError)
                else "Story organization failed safely."
            )
            if draft_id is not None:
                service.discard_draft(draft_id)
            service.finish_run(
                run_id,
                terminal,
                elapsed_ms=elapsed_ms,
                usage=run_usage(),
                sanitized_failure=safe,
            )
            raise


def collect_organization_input(
    project: Project,
    scope_ids: Sequence[str],
    cancelled: CancelCheck,
) -> tuple[tuple[BeatRecord, ...], tuple[FactRecord, ...]]:
    """Read exact bounded presentation/evidence/fact records; never load game Python."""

    presentation = project.presentation_service()
    nodes: list[PresentationNode] = []
    scene_by_node: dict[str, str] = {}
    seen_nodes: set[str] = set()
    for scope_id in scope_ids:
        event_nodes, _ = _paged_view(
            presentation, PresentationLevel.EVENT, (scope_id,), cancelled
        )
        evidence_parents = tuple(node.id for node in event_nodes) or (scope_id,)
        page_nodes, _page_edges = _paged_view(
            presentation, PresentationLevel.EVIDENCE, evidence_parents, cancelled
        )
        for node in page_nodes:
            if node.id not in seen_nodes:
                seen_nodes.add(node.id)
                scene_by_node[node.id] = scope_id
                nodes.append(node)
    edge_query = getattr(presentation, "edges_for_nodes", None)
    if not callable(edge_query):
        raise OrganizationError(
            "Complete selected-scope connectivity is unavailable in this project version."
        )
    presentation_edges = cast(
        tuple[PresentationEdge, ...],
        edge_query(PresentationLevel.EVIDENCE, tuple(node.id for node in nodes)),
    )
    selected_node_ids = frozenset(node.id for node in nodes)
    if any(
        edge.level is not PresentationLevel.EVIDENCE
        or edge.source_id not in selected_node_ids
        or edge.target_id not in selected_node_ids
        for edge in presentation_edges
    ):
        raise OrganizationError(
            "Complete selected-scope connectivity returned an invalid deterministic edge."
        )
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in presentation_edges:
        outgoing[edge.source_id].append(edge.target_id)
    all_facts: dict[str, FactRecord] = {}
    beats: list[BeatRecord] = []
    for order, node in enumerate(nodes):
        if cancelled():
            raise OrganizationCancelledError("Story organization was cancelled.")
        evidence = _paged_evidence(presentation, node.id, cancelled)
        presentation_facts = _paged_facts(presentation, node.id, cancelled)
        fact_ids: list[str] = []
        for fact in presentation_facts:
            if not isinstance(fact, PresentationFactRecord):
                continue
            fact_id = str(fact.id)
            fact_ids.append(fact_id)
            payload = fact.payload if isinstance(fact.payload, dict) else {}
            normalized = payload.get("normalized_value", fact.expression)
            all_facts[fact_id] = FactRecord(
                fact_id,
                str(fact.expression),
                str(normalized),
                str(fact.status),
                tuple(record.id for record in evidence),
            )
        text, speaker, speaker_names, condition = _node_story_text(node, evidence)
        beat = BeatRecord(
            id=node.id,
            scene_id=scene_by_node[node.id],
            kind=_provider_kind(node),
            order=order,
            text=text,
            speaker=speaker,
            condition=condition,
            relative_path=node.source_path or (evidence[0].source_path if evidence else ""),
            start_line=node.start_line or (evidence[0].start_line if evidence else 0),
            end_line=node.end_line or (evidence[0].end_line if evidence else 0),
            evidence_ids=tuple(record.id for record in evidence),
            fact_ids=tuple(sorted(set(fact_ids))),
            outgoing_ids=tuple(sorted(set(outgoing[node.id]))),
        )
        if "speaker_names" in BeatRecord.__dataclass_fields__:
            # Keep this UI worktree type-checkable both before and after the provider contract
            # adding ``speaker_names`` is integrated.
            beat = cast(
                BeatRecord,
                replace(cast(Any, beat), speaker_names=speaker_names),
            )
        beats.append(beat)
    return tuple(beats), tuple(all_facts[key] for key in sorted(all_facts))


def _paged_view(
    presentation: PresentationService,
    level: PresentationLevel,
    parent_ids: tuple[str, ...],
    cancelled: CancelCheck,
) -> tuple[list[PresentationNode], list[PresentationEdge]]:
    nodes: list[PresentationNode] = []
    edges: list[PresentationEdge] = []
    after: str | None = None
    seen_edges: set[str] = set()
    while True:
        if cancelled():
            raise OrganizationCancelledError("Story organization was cancelled.")
        page = presentation.view(
            PresentationRequest(
                level,
                parent_ids=parent_ids,
                after=after,
                edge_after=None,
                node_limit=250,
                edge_limit=500,
                include_technical=True,
            )
        )
        nodes.extend(page.nodes)
        for edge in page.edges:
            if edge.id not in seen_edges:
                seen_edges.add(edge.id)
                edges.append(edge)
        edge_page = page
        while edge_page.edge_continuation.has_more:
            if cancelled():
                raise OrganizationCancelledError("Story organization was cancelled.")
            edge_page = presentation.view(
                PresentationRequest(
                    level,
                    parent_ids=parent_ids,
                    after=after,
                    edge_after=edge_page.edge_continuation.next_after,
                    node_limit=250,
                    edge_limit=500,
                    include_technical=True,
                )
            )
            for edge in edge_page.edges:
                if edge.id not in seen_edges:
                    seen_edges.add(edge.id)
                    edges.append(edge)
        if not page.node_continuation.has_more:
            break
        after = page.node_continuation.next_after
    return nodes, edges


def _paged_evidence(
    presentation: PresentationService,
    node_id: str,
    cancelled: CancelCheck,
) -> tuple[EvidenceRecord, ...]:
    values: list[EvidenceRecord] = []
    seen: set[str] = set()
    after: str | None = None
    while True:
        if cancelled():
            raise OrganizationCancelledError("Story organization was cancelled.")
        page = presentation.evidence(node_id, after=after, limit=100)
        for value in page.items:
            if isinstance(value, EvidenceRecord) and value.id not in seen:
                seen.add(value.id)
                values.append(value)
        if not page.continuation.has_more:
            return tuple(values)
        after = page.continuation.next_after


def _paged_facts(
    presentation: PresentationService,
    node_id: str,
    cancelled: CancelCheck,
) -> tuple[PresentationFactRecord, ...]:
    values: list[PresentationFactRecord] = []
    seen: set[str] = set()
    after: str | None = None
    while True:
        if cancelled():
            raise OrganizationCancelledError("Story organization was cancelled.")
        page = presentation.facts(node_id=node_id, after=after, limit=100)
        for value in page.items:
            if isinstance(value, PresentationFactRecord) and value.id not in seen:
                seen.add(value.id)
                values.append(value)
        if not page.continuation.has_more:
            return tuple(values)
        after = page.continuation.next_after


def _node_story_text(
    node: PresentationNode, evidence: Sequence[EvidenceRecord]
) -> tuple[str, str | None, tuple[str, ...], str | None]:
    payload = node.payload if isinstance(node.payload, dict) else {}
    content = payload.get("content")
    texts: list[str] = []
    speakers: list[str] = []
    conditions: list[str] = []

    def append_text(value: object) -> None:
        if isinstance(value, str) and value.strip():
            normalized = value.strip()
            if normalized not in texts:
                texts.append(normalized)

    def append_speaker(value: object) -> None:
        if isinstance(value, str) and value.strip():
            normalized = value.strip()
            if normalized not in speakers:
                speakers.append(normalized)

    def append_condition(value: object) -> None:
        if isinstance(value, str) and value.strip():
            normalized = value.strip()
            if normalized not in conditions:
                conditions.append(normalized)

    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            value = item.get("text")
            raw_speaker = item.get("speaker")
            append_speaker(raw_speaker)
            if isinstance(raw_speaker, str) and isinstance(value, str) and value.strip():
                append_text(f"{raw_speaker}: {value}")
            else:
                append_text(value)
    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            append_text(choice.get("caption"))
            append_condition(choice.get("condition"))
    branches = payload.get("branches")
    if isinstance(branches, list):
        for branch in branches:
            if isinstance(branch, dict):
                append_condition(branch.get("condition"))
    for value in _nested_payload_strings(payload, frozenset({"caption"})):
        append_text(value)
    for value in _nested_payload_strings(payload, frozenset({"condition"})):
        append_condition(value)
    for value in _nested_payload_strings(
        payload, frozenset({"speaker", "character"})
    ):
        append_speaker(value)
    for record in evidence:
        record_payload = record.payload if isinstance(record.payload, dict) else {}
        for value in _nested_payload_strings(
            record_payload, frozenset({"speaker", "character"})
        ):
            append_speaker(value)
    if not texts:
        texts = [record.text for record in evidence if record.text.strip()]
    if not texts and isinstance(payload.get("source_text"), str):
        texts = [str(payload["source_text"])]
    append_condition(payload.get("condition"))
    speaker_prefix = [f"Speakers: {', '.join(speakers)}"] if speakers else []
    joined = " ".join([*speaker_prefix, *texts])
    marker = "\n[truncated; exact evidence IDs retained]"
    if len(joined) > 32_000:
        joined = joined[: 32_000 - len(marker)] + marker
    return (
        joined,
        speakers[0] if speakers else None,
        tuple(speakers),
        "\n".join(conditions) or None,
    )


def _nested_payload_strings(value: object, keys: frozenset[str]) -> tuple[str, ...]:
    """Return matching nested strings in deterministic payload insertion order."""

    found: list[str] = []

    def visit(item: object) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in keys and isinstance(child, str) and child.strip():
                    normalized = child.strip()
                    if normalized not in found:
                        found.append(normalized)
                if isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return tuple(found)


def _provider_kind(node: PresentationNode) -> str:
    value = node.kind.casefold()
    if "choice" in value:
        return "choice"
    if "condition" in value or "gate" in value:
        return "condition"
    if value in {"narrative", "narration", "dialogue"}:
        return value
    if value in {"jump", "return"}:
        return value
    return "technical" if node.technical else "narrative"


def _group_event(
    group: OrganizationGroup,
    source: Mapping[str, _EventCandidate] | None = None,
    *,
    id_prefix: str | None = None,
) -> _EventCandidate:
    source = source or {}
    members = [source[member] for member in group.member_ids if member in source]
    beat_ids = tuple(beat for member in members for beat in member.beat_ids) or group.member_ids
    claims = tuple((claim.text, claim.evidence_ids) for claim in group.claims)
    return _EventCandidate(
        group.id if id_prefix is None else _stable_id(id_prefix, group.id),
        group.title,
        group.summary,
        beat_ids,
        group.characters or tuple(sorted({value for item in members for value in item.characters})),
        group.importance,
        group.outcomes,
        group.promoted_fact_ids,
        claims,
        group.warnings,
    )


def _reconcile_events(
    run_id: str,
    stage_one: Sequence[tuple[OrganizationRequest, OrganizationChunkResult]],
    execute: Callable[[OrganizationRequest, int, str], OrganizationChunkResult],
) -> tuple[list[_EventCandidate], set[str], list[dict[str, str]]]:
    by_scene: dict[str, list[_EventCandidate]] = defaultdict(list)
    ungrouped_beats: set[str] = set()
    evidence_by_scene: dict[str, set[str]] = defaultdict(set)
    facts_by_scene: dict[str, set[str]] = defaultdict(set)
    beat_adjacency: dict[str, tuple[str, ...]] = {}
    for request, result in stage_one:
        scene = str(request.payload.get("scene_id", request.scope_id))
        by_scene[scene].extend(
            _group_event(group, id_prefix=request.chunk_id) for group in result.groups
        )
        ungrouped_beats.update(result.ungrouped_ids)
        evidence_by_scene[scene].update(request.constraints.evidence_ids)
        facts_by_scene[scene].update(request.constraints.fact_ids)
        raw_beats = request.payload.get("beats", [])
        if isinstance(raw_beats, list):
            for value in raw_beats:
                if not isinstance(value, dict) or value.get("context_only") is True:
                    continue
                beat_id = value.get("id")
                adjacent = value.get("adjacent_ids", [])
                if isinstance(beat_id, str) and isinstance(adjacent, list):
                    beat_adjacency[beat_id] = tuple(
                        item for item in adjacent if isinstance(item, str)
                    )

    reconciled: list[_EventCandidate] = []
    for number, scene in enumerate(by_scene):
        source_events = by_scene[scene]
        if not source_events:
            # Required beats explicitly left ungrouped by Stage 1 remain deterministic fallback;
            # there is nothing schema-valid to ask Stage 2 to reconcile.
            continue
        source_by_id = {event.id: event for event in source_events}
        request = build_reconciliation_request(
            run_id=run_id,
            chunk_id=f"{scene}:reconcile",
            scope_id=scene,
            events=[_stage_two_event(event) for event in source_events],
            ordered_event_ids=tuple(event.id for event in source_events),
            evidence_ids=frozenset(evidence_by_scene[scene]),
            fact_ids=frozenset(facts_by_scene[scene]),
        )
        result = execute(request, 50 + number, "Reconciling events")
        reconciled.extend(
            _group_event(group, source_by_id, id_prefix=scene) for group in result.groups
        )
        for event_id in result.ungrouped_ids:
            ungrouped_beats.update(source_by_id[event_id].beat_ids)
    event_by_beat = {
        beat_id: event.id for event in reconciled for beat_id in event.beat_ids
    }
    connectivity = sorted(
        {
            (event_by_beat[source], event_by_beat[target], "flow")
            for source, targets in beat_adjacency.items()
            if source in event_by_beat
            for target in targets
            if target in event_by_beat and event_by_beat[source] != event_by_beat[target]
        }
    )
    return (
        reconciled,
        ungrouped_beats,
        [
            {"source": source, "target": target, "kind": kind}
            for source, target, kind in connectivity
        ],
    )


def _stage_two_event(event: _EventCandidate) -> dict[str, object]:
    return {
        "id": event.id,
        "title": event.title,
        "summary": event.summary,
        "member_ids": list(event.beat_ids),
        "characters": list(event.characters),
        "importance": event.importance,
        "outcomes": list(event.outcomes),
        "promoted_fact_ids": list(event.fact_ids),
        "evidence_ids": sorted({evidence for _, values in event.claims for evidence in values}),
        "warnings": list(event.warnings),
    }


def _organize_arcs(
    run_id: str,
    events: Sequence[_EventCandidate],
    local_connectivity: list[dict[str, str]],
    execute: Callable[[OrganizationRequest, int, str], OrganizationChunkResult],
    _depth: int = 0,
) -> OrganizationChunkResult:
    if not events:
        empty_normalized: dict[str, object] = {
            "stage": OrganizationStage.ARCS.value,
            "groups": [],
            "ungrouped_ids": [],
        }
        return OrganizationChunkResult(
            OrganizationStage.ARCS,
            (),
            (),
            empty_normalized,
        )
    batches = _partition_arc_events(events, local_connectivity)
    partial_results: list[OrganizationChunkResult] = []
    preliminary_groups: list[OrganizationGroup] = []
    ungrouped_event_ids: list[str] = []
    for index, batch in enumerate(batches, start=1):
        request = _build_arc_batch_request(
            run_id,
            f"selected-story:arcs:{index}",
            batch,
            local_connectivity,
        )
        result = execute(
            request,
            76 + min(12, index),
            "Organizing arcs",
        )
        partial_results.append(result)
        preliminary_groups.extend(
            replace(group, id=_stable_id(request.chunk_id, group.id))
            for group in result.groups
        )
        ungrouped_event_ids.extend(result.ungrouped_ids)
    ungrouped_event_ids = list(_ordered_unique(ungrouped_event_ids))
    if len(partial_results) == 1 and len(preliminary_groups) <= ARC_MAX_GROUPS:
        return partial_results[0]

    if not preliminary_groups:
        last = partial_results[-1]
        normalized: dict[str, object] = {
            "stage": last.stage.value,
            "groups": [],
            "ungrouped_ids": ungrouped_event_ids,
        }
        return replace(
            last,
            groups=(),
            ungrouped_ids=tuple(ungrouped_event_ids),
            raw_normalized=normalized,
        )
    if (
        len(preliminary_groups) >= len(events)
        or _depth >= ARC_MAX_RECONCILIATION_DEPTH
    ):
        last = partial_results[-1]
        if len(preliminary_groups) > ARC_MAX_GROUPS:
            fallback_ids = _ordered_unique(
                [*ungrouped_event_ids, *(event.id for event in events)]
            )
            fallback_normalized: dict[str, object] = {
                "stage": last.stage.value,
                "groups": [],
                "ungrouped_ids": list(fallback_ids),
            }
            return replace(
                last,
                groups=(),
                ungrouped_ids=fallback_ids,
                raw_normalized=fallback_normalized,
            )
        normalized = {
            "stage": last.stage.value,
            "groups": [_group_payload(group) for group in preliminary_groups],
            "ungrouped_ids": ungrouped_event_ids,
        }
        return replace(
            last,
            groups=tuple(preliminary_groups),
            ungrouped_ids=tuple(ungrouped_event_ids),
            raw_normalized=normalized,
        )

    preliminary_by_id = {group.id: group for group in preliminary_groups}
    group_by_event = {
        event_id: group.id for group in preliminary_groups for event_id in group.member_ids
    }
    quotient_connectivity = [
        {"source": source, "target": target, "kind": kind}
        for source, target, kind in sorted(
            {
                (
                    group_by_event[edge["source"]],
                    group_by_event[edge["target"]],
                    edge.get("kind", "flow"),
                )
                for edge in local_connectivity
                if edge["source"] in group_by_event
                and edge["target"] in group_by_event
                and group_by_event[edge["source"]] != group_by_event[edge["target"]]
            }
        )
    ]
    meta_events = [
        _EventCandidate(
            group.id,
            group.title,
            group.summary,
            group.member_ids,
            group.characters,
            group.importance,
            group.outcomes,
            group.promoted_fact_ids,
            tuple((claim.text, claim.evidence_ids) for claim in group.claims),
            group.warnings,
        )
        for group in preliminary_groups
    ]
    final = _organize_arcs(
        run_id,
        meta_events,
        quotient_connectivity,
        execute,
        _depth + 1,
    )
    final_groups = tuple(
        replace(
            group,
            member_ids=tuple(
                event_id
                for preliminary_id in group.member_ids
                for event_id in preliminary_by_id[preliminary_id].member_ids
            ),
        )
        for group in final.groups
    )
    final_ungrouped = _ordered_unique(
        [*ungrouped_event_ids]
        + [
            event_id
            for preliminary_id in final.ungrouped_ids
            for event_id in preliminary_by_id[preliminary_id].member_ids
        ]
    )
    normalized = {
        "stage": final.stage.value,
        "groups": [_group_payload(group) for group in final_groups],
        "ungrouped_ids": list(final_ungrouped),
    }
    return replace(
        final,
        groups=final_groups,
        ungrouped_ids=final_ungrouped,
        raw_normalized=normalized,
    )


def _ordered_unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _partition_arc_events(
    events: Sequence[_EventCandidate], local_connectivity: list[dict[str, str]]
) -> list[list[_EventCandidate]]:
    batches: list[list[_EventCandidate]] = []
    current: list[_EventCandidate] = []
    for event in events:
        trial = [*current, event]
        request = _build_arc_batch_request(
            "size-check",
            "size-check",
            trial,
            local_connectivity,
        )
        size = _complete_prompt_chars(request)
        if current and (len(trial) > ARC_MAX_EVENTS or size > ARC_MAX_CHARS):
            batches.append(current)
            current = [event]
            request = _build_arc_batch_request(
                "size-check", "size-check", current, local_connectivity
            )
            size = _complete_prompt_chars(request)
        else:
            current = trial
        if size > ARC_MAX_CHARS:
            raise OrganizationError("A single normalized event exceeds the arc request limit.")
    if current:
        batches.append(current)
    return batches


def _complete_prompt_chars(request: OrganizationRequest) -> int:
    """Measure the exact initial and repair stdin envelopes, not only their payload."""

    serializer = getattr(organization_contracts, "serialize_organization_prompt", None)
    if callable(serializer):
        serialize = cast(Callable[..., str], serializer)
        return max(
            len(serialize(request, repair=repair)) for repair in (False, True)
        )
    return max(
        len(_compatibility_prompt(request, repair=repair))
        for repair in (False, True)
    )


def _compatibility_prompt(request: OrganizationRequest, *, repair: bool) -> str:
    """Mirror the integrated provider serializer while this worker remains on its old base."""

    instruction = (
        "Repair the prior response. Return only JSON matching the schema and supplied IDs."
        if repair
        else "Organize the supplied deterministic records. Return only schema-valid JSON."
    )
    envelope = {
        "instruction": instruction,
        "security": "Do not use tools, web, MCP, commands, or files.",
        "authority": (
            "Return only titles, summaries, existing memberships, characters supported by "
            "the input, outcomes, existing fact IDs, evidence-backed interpretations, "
            "warnings, and ungrouped IDs. Never invent edges, conditions, facts, source "
            "locations, route destinations, or causal authority."
        ),
        "contract": {
            "stage": request.stage.value,
            "allowed_member_ids": list(request.constraints.ordered_member_ids),
            "context_only_ids": sorted(request.constraints.context_member_ids),
            "allowed_fact_ids": sorted(request.constraints.fact_ids),
            "allowed_evidence_ids": sorted(request.constraints.evidence_ids),
            "allowed_characters": sorted(request.constraints.character_names),
        },
        "input": request.payload,
    }
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))


def _build_arc_batch_request(
    run_id: str,
    chunk_id: str,
    events: Sequence[_EventCandidate],
    local_connectivity: list[dict[str, str]],
) -> OrganizationRequest:
    evidence_ids = frozenset(
        evidence for event in events for _, values in event.claims for evidence in values
    )
    fact_ids = frozenset(fact for event in events for fact in event.fact_ids)
    characters = frozenset(character for event in events for character in event.characters)
    event_ids = {event.id for event in events}
    return build_arc_request(
        run_id=run_id,
        chunk_id=chunk_id,
        scope_id="selected-story",
        event_summaries=[
            {
                "id": event.id,
                "title": event.title,
                "summary": event.summary,
                "major_fact_ids": list(event.fact_ids),
                "characters": list(event.characters),
                "importance": event.importance,
                "outcomes": list(event.outcomes),
                "evidence_ids": sorted(
                    {evidence for _, values in event.claims for evidence in values}
                ),
            }
            for event in events
        ],
        ordered_event_ids=tuple(event.id for event in events),
        evidence_ids=evidence_ids,
        fact_ids=fact_ids,
        characters=characters,
        local_connectivity=[
            edge
            for edge in local_connectivity
            if edge["source"] in event_ids and edge["target"] in event_ids
        ],
    )


def _group_payload(group: OrganizationGroup) -> dict[str, object]:
    return {
        "id": group.id,
        "title": group.title,
        "summary": group.summary,
        "member_ids": list(group.member_ids),
        "characters": list(group.characters),
        "importance": group.importance,
        "outcomes": list(group.outcomes),
        "promoted_fact_ids": list(group.promoted_fact_ids),
        "claims": [
            {"text": claim.text, "evidence_ids": list(claim.evidence_ids)}
            for claim in group.claims
        ],
        "warnings": list(group.warnings),
    }


def _candidate_payload(
    events: Sequence[_EventCandidate],
    ungrouped_beats: set[str],
    arcs: OrganizationChunkResult,
) -> dict[str, object]:
    events_by_id = {event.id: event for event in events}
    active_event_ids = {member for arc in arcs.groups for member in arc.member_ids}
    for event_id in arcs.ungrouped_ids:
        ungrouped_beats.update(events_by_id[event_id].beat_ids)
    active_events = [event for event in events if event.id in active_event_ids]
    claims: list[dict[str, object]] = []
    for event in active_events:
        for index, (text, evidence_ids) in enumerate(event.claims):
            claims.append(
                {
                    "id": _stable_id("event-claim", event.id, str(index), text),
                    "event_id": event.id,
                    "arc_id": None,
                    "text": text,
                    "kind": "interpretation",
                    "evidence_ids": list(evidence_ids),
                }
            )
    for arc in arcs.groups:
        for index, claim in enumerate(arc.claims):
            claims.append(
                {
                    "id": _stable_id("arc-claim", arc.id, str(index), claim.text),
                    "event_id": None,
                    "arc_id": arc.id,
                    "text": claim.text,
                    "kind": "interpretation",
                    "evidence_ids": list(claim.evidence_ids),
                }
            )
    return {
        "events": [
            {
                "id": event.id,
                "title": event.title,
                "summary": event.summary,
                "beat_ids": list(event.beat_ids),
                "origin": "ai",
                "characters": list(event.characters),
                "importance": event.importance,
                "outcomes": list(event.outcomes),
                "promoted_fact_ids": list(event.fact_ids),
                "warnings": list(event.warnings),
            }
            for event in active_events
        ],
        "arcs": [
            {
                "id": arc.id,
                "title": arc.title,
                "summary": arc.summary,
                "event_ids": list(arc.member_ids),
                "origin": "ai",
                "characters": list(arc.characters),
                "importance": arc.importance,
                "outcomes": list(arc.outcomes),
                "promoted_fact_ids": list(arc.promoted_fact_ids),
                "warnings": list(arc.warnings),
            }
            for arc in arcs.groups
        ],
        "claims": claims,
        "ungrouped_beat_ids": sorted(ungrouped_beats),
    }


def _project_generation(project: Project) -> str:
    payload = [
        (source.path, source.content_hash, source.size_bytes)
        for source in sorted(project.sources(), key=lambda value: value.path)
    ]
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:32]


__all__ = [
    "OrganizationOptions",
    "OrganizationWorkflow",
    "WorkflowResult",
    "collect_organization_input",
]
