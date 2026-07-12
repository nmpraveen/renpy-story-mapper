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
from collections import defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol, cast

import renpy_story_mapper.organization.contracts as organization_contracts
from renpy_story_mapper import storage
from renpy_story_mapper.organization import (
    M05_CLOUD_MODEL,
    M05_REASONING_PROFILE,
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
    InvalidProviderOutputError,
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

PROMPT_VERSION = "m05-story-organizer-v2"
SCHEMA_VERSION = "m05-organization-v1"
ARC_MAX_CHARS = int(getattr(organization_contracts, "MAX_PROMPT_CHARS", 48_000))
ARC_MAX_EVENTS = 120
ARC_MAX_GROUPS = 12
ARC_MAX_RECONCILIATION_DEPTH = 32
EVENT_MAX_RECONCILIATION_DEPTH = 32
VIEW_PARENT_BATCH_SIZE = 400


class CancelCheck(Protocol):
    def __call__(self) -> bool: ...


class ConsentCallback(Protocol):
    def __call__(self, run_id: str) -> bool: ...


@dataclass(frozen=True)
class OrganizationOptions:
    mode: CodexMode = CodexMode.CODEX_CHATGPT
    model_profile: str = M05_REASONING_PROFILE
    model: str | None = M05_CLOUD_MODEL
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
    allowed_evidence_ids: tuple[str, ...] = ()
    allowed_fact_ids: tuple[str, ...] = ()
    allowed_character_names: tuple[str, ...] = ()


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
        if isinstance(scope_ids, (str, bytes)) or any(
            not isinstance(scope_id, str) or not scope_id for scope_id in scope_ids
        ):
            raise ValueError("Story scope IDs must be non-empty strings.")
        requested_scope_ids = tuple(scope_ids)
        if len(set(requested_scope_ids)) != len(requested_scope_ids):
            raise ValueError("Story scope IDs must be unique.")
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
                cache_state: Literal["hit", "stored", "bypassed"] = "hit"
                chunk_status: Literal["validated", "rejected"] = "validated"
                cache_hits += 1
            else:
                provider_calls += 1
                try:
                    result = provider.organize(
                        request,
                        lambda value, text: progress(
                            min(98, percent + max(0, min(10, value // 10))), text
                        ),
                        cancelled,
                    )
                except InvalidProviderOutputError:
                    raise_if_cancelled()
                    result = _deterministic_fallback_result(request)
                    cache_state = "bypassed"
                    chunk_status = "rejected"
                    progress(
                        percent,
                        f"{label} - using deterministic fallback",
                    )
                else:
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
                    chunk_status = "validated"
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
                status=chunk_status,
                result=result.raw_normalized,
                chunk_id=f"{run_id}:{ordinal:05d}",
            )
            raise_if_cancelled()
            ordinal += 1
            return result

        try:
            progress(2, "Preparing deterministic story evidence")
            resolved_scope_ids = resolve_organization_scopes(
                self._project, requested_scope_ids, cancelled
            )
            beats, facts = collect_organization_input(
                self._project, resolved_scope_ids, cancelled
            )
            covered_scope_ids = _ordered_unique(
                tuple(beat.scene_id for beat in beats)
            )
            if not beats or not covered_scope_ids:
                raise OrganizationError(
                    "The selected story scope contains no deterministic beats to organize."
                )
            deterministic_fallback: set[str] = set()
            stage_one_requests = build_event_chunks(
                run_id=run_id,
                scope_id="selected-story",
                beats=list(beats),
                facts=list(facts),
                on_oversized=lambda beat: deterministic_fallback.add(beat.id),
                on_deterministic_fallback=lambda beat: deterministic_fallback.add(
                    beat.id
                ),
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
                cancelled=cancelled,
                authoritative_adjacency={beat.id: beat.outgoing_ids for beat in beats},
            )
            ungrouped_beats.update(deterministic_fallback)
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
                    scope_ids=covered_scope_ids,
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


def resolve_organization_scopes(
    project: Project,
    scope_ids: Sequence[str],
    cancelled: CancelCheck,
) -> tuple[str, ...]:
    """Resolve ``()`` to every visible Level-1 scope; preserve explicit selections."""

    if scope_ids:
        return tuple(scope_ids)
    presentation = project.presentation_service()
    try:
        overview_nodes, _ = _paged_view(
            presentation, PresentationLevel.OVERVIEW, (), cancelled
        )
    except storage.ProjectOperationCancelled as exc:
        raise OrganizationCancelledError(
            "Story organization was cancelled."
        ) from exc
    resolved = tuple(node.id for node in overview_nodes)
    if not resolved:
        raise OrganizationError("The project has no visible story scopes to organize.")
    return resolved


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
    bulk_evidence = getattr(presentation, "evidence_for_nodes", None)
    bulk_facts = getattr(presentation, "facts_for_nodes", None)
    has_bulk_records = callable(bulk_evidence) and callable(bulk_facts)
    if has_bulk_records:
        event_nodes = _paged_children_for_parents(
            presentation,
            PresentationLevel.EVENT,
            scope_ids,
            cancelled,
        )
        selected_scopes = frozenset(scope_ids)
        scene_by_event: dict[str, str] = {}
        for event_node in event_nodes:
            if (
                event_node.parent_id is None
                or event_node.parent_id not in selected_scopes
            ):
                raise OrganizationError(
                    "Selected Level-2 story input has invalid scope ancestry."
                )
            scene_by_event[event_node.id] = event_node.parent_id
        evidence_parents = tuple(node.id for node in event_nodes)
        page_nodes = _paged_children_for_parents(
            presentation,
            PresentationLevel.EVIDENCE,
            evidence_parents,
            cancelled,
        )
        for node in page_nodes:
            scene_id = scene_by_event.get(node.parent_id or "")
            if scene_id is None:
                raise OrganizationError(
                    "Selected Level-3 story input has invalid scope ancestry."
                )
            if node.id in seen_nodes:
                continue
            seen_nodes.add(node.id)
            scene_by_node[node.id] = scene_id
            nodes.append(node)
    else:
        # Compatibility for older adapters. The integrated project service always uses the
        # indexed bulk path above, so canonical work is not multiplied by the beat count.
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
    if cancelled():
        raise OrganizationCancelledError("Story organization was cancelled.")
    edge_query = getattr(presentation, "edges_for_nodes", None)
    if not callable(edge_query):
        raise OrganizationError(
            "Complete selected-scope connectivity is unavailable in this project version."
        )
    try:
        presentation_edges = cast(
            tuple[PresentationEdge, ...],
            edge_query(
                PresentationLevel.EVIDENCE,
                tuple(node.id for node in nodes),
                **({"cancelled": cancelled} if has_bulk_records else {}),
            ),
        )
    except storage.ProjectOperationCancelled as exc:
        raise OrganizationCancelledError(
            "Story organization was cancelled."
        ) from exc
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
    evidence_by_node: dict[str, tuple[EvidenceRecord, ...]] = {}
    facts_by_node: dict[str, tuple[PresentationFactRecord, ...]] = {}
    if has_bulk_records:
        node_ids = tuple(node.id for node in nodes)
        try:
            raw_evidence = cast(Any, bulk_evidence)(node_ids, cancelled=cancelled)
            raw_facts = cast(Any, bulk_facts)(node_ids, cancelled=cancelled)
        except storage.ProjectOperationCancelled as exc:
            raise OrganizationCancelledError(
                "Story organization was cancelled."
            ) from exc
        evidence_lists: dict[str, list[EvidenceRecord]] = defaultdict(list)
        for record in raw_evidence:
            if not isinstance(record, EvidenceRecord) or record.node_id not in selected_node_ids:
                raise OrganizationError(
                    "Bulk evidence returned a record outside the exact selected beats."
                )
            evidence_lists[record.node_id].append(record)
        fact_lists: dict[str, list[PresentationFactRecord]] = defaultdict(list)
        for record in raw_facts:
            if (
                not isinstance(record, PresentationFactRecord)
                or record.node_id not in selected_node_ids
            ):
                raise OrganizationError(
                    "Bulk facts returned a record outside the exact selected beats."
                )
            fact_lists[record.node_id].append(record)
        evidence_by_node = {
            node_id: tuple(records) for node_id, records in evidence_lists.items()
        }
        facts_by_node = {
            node_id: tuple(records) for node_id, records in fact_lists.items()
        }
    all_facts: dict[str, FactRecord] = {}
    beats: list[BeatRecord] = []
    for order, node in enumerate(nodes):
        if cancelled():
            raise OrganizationCancelledError("Story organization was cancelled.")
        if has_bulk_records:
            evidence = evidence_by_node.get(node.id, ())
            presentation_facts = facts_by_node.get(node.id, ())
        else:
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
            outgoing_ids=_ordered_unique(outgoing[node.id]),
            speaker_names=speaker_names,
        )
        beats.append(beat)
    return tuple(beats), tuple(all_facts[key] for key in sorted(all_facts))


def _paged_children_for_parents(
    presentation: PresentationService,
    level: PresentationLevel,
    parent_ids: Sequence[str],
    cancelled: CancelCheck,
) -> list[PresentationNode]:
    """Read children in contiguous parent batches below Windows SQLite's variable cap.

    Parent IDs arrive in authoritative chronology. Each query is sorted by the presentation
    index, so concatenating contiguous batches preserves that chronology without inventing a
    secondary source-order heuristic.
    """

    nodes: list[PresentationNode] = []
    by_id: dict[str, PresentationNode] = {}
    for offset in range(0, len(parent_ids), VIEW_PARENT_BATCH_SIZE):
        if cancelled():
            raise OrganizationCancelledError("Story organization was cancelled.")
        parent_batch = tuple(parent_ids[offset : offset + VIEW_PARENT_BATCH_SIZE])
        batch_nodes, _ = _paged_view(
            presentation,
            level,
            parent_batch,
            cancelled,
        )
        for node in batch_nodes:
            existing = by_id.get(node.id)
            if existing is None:
                by_id[node.id] = node
                nodes.append(node)
            elif existing != node:
                raise OrganizationError(
                    "Presentation paging returned conflicting duplicate story nodes."
                )
    return nodes


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
    value = node.kind.casefold().strip()
    if "choice" in value:
        return "choice"
    if "condition" in value or "gate" in value:
        return "condition"
    if value in {"narrative", "narration", "dialogue"}:
        return value
    return value or "technical"


def _deterministic_fallback_result(
    request: OrganizationRequest,
) -> OrganizationChunkResult:
    """Return a validated no-invention result for one twice-rejected provider request."""

    members = list(request.constraints.ordered_member_ids)
    result = validate_result(
        {
            "stage": request.stage.value,
            "groups": [],
            "ungrouped_ids": members,
        },
        request,
    )
    return replace(result, attempts=2)


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
    allowed_evidence_ids = tuple(
        sorted({value for item in members for value in item.allowed_evidence_ids})
    )
    allowed_fact_ids = tuple(
        sorted({value for item in members for value in item.allowed_fact_ids})
    )
    allowed_character_names = tuple(
        sorted({value for item in members for value in item.allowed_character_names})
    )
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
        allowed_evidence_ids,
        allowed_fact_ids,
        allowed_character_names,
    )


def _request_member_characters(
    request: OrganizationRequest, member_ids: Sequence[str]
) -> tuple[str, ...]:
    """Return only deterministic speakers attached to the exact grouped beats."""
    selected = set(member_ids)
    characters: set[str] = set()
    raw_beats = request.payload.get("beats", [])
    if not isinstance(raw_beats, list):
        return ()
    for value in raw_beats:
        if not isinstance(value, dict) or value.get("id") not in selected:
            continue
        speaker = value.get("speaker")
        if isinstance(speaker, str):
            characters.add(speaker)
        speakers = value.get("speakers", [])
        if isinstance(speakers, list):
            characters.update(item for item in speakers if isinstance(item, str))
    return tuple(sorted(characters))


def _reconcile_events(
    run_id: str,
    stage_one: Sequence[tuple[OrganizationRequest, OrganizationChunkResult]],
    execute: Callable[[OrganizationRequest, int, str], OrganizationChunkResult],
    *,
    cancelled: CancelCheck | None = None,
    authoritative_adjacency: Mapping[str, Sequence[str]] | None = None,
) -> tuple[list[_EventCandidate], set[str], list[dict[str, str]]]:
    by_scene: dict[str, list[_EventCandidate]] = defaultdict(list)
    request_count_by_scene: dict[str, int] = defaultdict(int)
    ungrouped_beats: set[str] = set()
    beat_adjacency: dict[str, tuple[str, ...]] = {
        beat_id: tuple(targets)
        for beat_id, targets in (authoritative_adjacency or {}).items()
    }
    for request, result in stage_one:
        _check_reconciliation_cancel(cancelled)
        scene = str(request.payload.get("scene_id", request.scope_id))
        request_count_by_scene[scene] += 1
        for group in result.groups:
            by_scene[scene].append(
                replace(
                    _group_event(group, id_prefix=request.chunk_id),
                    allowed_evidence_ids=tuple(sorted(request.constraints.evidence_ids)),
                    allowed_fact_ids=tuple(sorted(request.constraints.fact_ids)),
                    allowed_character_names=_request_member_characters(
                        request, group.member_ids
                    ),
                )
            )
        ungrouped_beats.update(result.ungrouped_ids)
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
        if request_count_by_scene[scene] <= 1:
            reconciled.extend(source_events)
            continue
        scene_events, scene_ungrouped = _reconcile_scene_events(
            run_id,
            scene,
            source_events,
            execute,
            progress_percent=min(73, 50 + number),
            cancelled=cancelled,
        )
        reconciled.extend(scene_events)
        ungrouped_beats.update(scene_ungrouped)
    connectivity = _collapsed_event_connectivity(reconciled, beat_adjacency)
    return (
        reconciled,
        ungrouped_beats,
        connectivity,
    )


def _collapsed_event_connectivity(
    events: Sequence[_EventCandidate],
    beat_adjacency: Mapping[str, Sequence[str]],
) -> list[dict[str, str]]:
    """Collapse finite technical/ungrouped beat paths to the next grouped events."""

    event_by_beat: dict[str, str] = {}
    beats_by_event: dict[str, list[str]] = defaultdict(list)
    for event in events:
        for beat_id in event.beat_ids:
            existing = event_by_beat.get(beat_id)
            if existing is not None and existing != event.id:
                raise OrganizationError(
                    "Reconciled events contain duplicate deterministic beat membership."
                )
            event_by_beat[beat_id] = event.id
            beats_by_event[event.id].append(beat_id)

    included = set(beat_adjacency) | set(event_by_beat)
    collapsed: set[tuple[str, str, str]] = set()
    for event in events:
        pending = deque(beats_by_event[event.id])
        seen: set[str] = set()
        while pending:
            source_beat = pending.popleft()
            if source_beat in seen:
                continue
            seen.add(source_beat)
            for target_beat in beat_adjacency.get(source_beat, ()):
                if target_beat not in included:
                    continue
                target_event = event_by_beat.get(target_beat)
                if target_event is not None and target_event != event.id:
                    collapsed.add((event.id, target_event, "flow"))
                    continue
                if target_beat not in seen:
                    pending.append(target_beat)
    return [
        {"source": source, "target": target, "kind": kind}
        for source, target, kind in sorted(collapsed)
    ]


def _reconcile_scene_events(
    run_id: str,
    scene: str,
    source_events: Sequence[_EventCandidate],
    execute: Callable[[OrganizationRequest, int, str], OrganizationChunkResult],
    *,
    progress_percent: int,
    depth: int = 0,
    cancelled: CancelCheck | None = None,
) -> tuple[list[_EventCandidate], set[str]]:
    """Reconcile one scene with bounded prompts and recursive boundary passes."""

    _check_reconciliation_cancel(cancelled)
    if not source_events:
        return [], set()
    if len(source_events) == 1:
        return list(source_events), set()
    if depth >= EVENT_MAX_RECONCILIATION_DEPTH:
        return list(source_events), set()
    try:
        batches = _partition_reconciliation_events(
            run_id, scene, source_events, depth, cancelled=cancelled
        )
    except OrganizationCancelledError:
        raise
    except OrganizationError:
        # A single normalized Stage-1 event can only exceed the contract through unusually
        # large exact ID sets. Preserving it unchanged is safer than truncating authority.
        return list(source_events), set()

    preliminary: list[_EventCandidate] = []
    ungrouped_beats: set[str] = set()
    for index, batch in enumerate(batches, start=1):
        _check_reconciliation_cancel(cancelled)
        request = _build_reconciliation_batch_request(
            run_id,
            f"{scene}:reconcile:d{depth}:b{index}",
            scene,
            batch,
        )
        result = execute(
            request,
            min(73, progress_percent + min(depth, 8)),
            "Reconciling events",
        )
        source_by_id = {event.id: event for event in batch}
        for group in result.groups:
            if any(member_id not in source_by_id for member_id in group.member_ids):
                raise OrganizationError(
                    "Stage-2 reconciliation returned an unknown event membership."
                )
            preliminary.append(
                _group_event(group, source_by_id, id_prefix=request.chunk_id)
            )
        for event_id in result.ungrouped_ids:
            source = source_by_id.get(event_id)
            if source is None:
                raise OrganizationError(
                    "Stage-2 reconciliation returned an unknown ungrouped event."
                )
            ungrouped_beats.update(source.beat_ids)

    if len(batches) == 1 or not preliminary:
        return preliminary, ungrouped_beats
    if len(preliminary) >= len(source_events):
        # No reduction means another pass would reproduce the same batch boundaries forever.
        # Keep the validated partial results so explicit ungrouped decisions are never restored.
        return preliminary, ungrouped_beats

    # The next layer receives every batch output in authoritative order. It is therefore the
    # explicit boundary-reconciliation pass, and may itself partition recursively if needed.
    reconciled, recursive_ungrouped = _reconcile_scene_events(
        run_id,
        scene,
        preliminary,
        execute,
        progress_percent=progress_percent,
        depth=depth + 1,
        cancelled=cancelled,
    )
    return reconciled, ungrouped_beats | recursive_ungrouped


def _partition_reconciliation_events(
    run_id: str,
    scene: str,
    events: Sequence[_EventCandidate],
    depth: int,
    *,
    cancelled: CancelCheck | None = None,
) -> list[list[_EventCandidate]]:
    batches: list[list[_EventCandidate]] = []
    current: list[_EventCandidate] = []
    for event in events:
        _check_reconciliation_cancel(cancelled)
        trial = [*current, event]
        chunk_id = f"{scene}:reconcile:d{depth}:b{len(batches) + 1}"
        try:
            _build_reconciliation_batch_request(
                run_id, chunk_id, scene, trial
            )
        except ValueError as exc:
            if "complete organization prompt exceeds" not in str(exc).casefold():
                raise
            if not current:
                raise OrganizationError(
                    "A single normalized event exceeds the reconciliation request limit."
                ) from exc
            batches.append(current)
            current = [event]
            chunk_id = f"{scene}:reconcile:d{depth}:b{len(batches) + 1}"
            try:
                _build_reconciliation_batch_request(
                    run_id, chunk_id, scene, current
                )
            except ValueError as single_exc:
                if "complete organization prompt exceeds" not in str(single_exc).casefold():
                    raise
                raise OrganizationError(
                    "A single normalized event exceeds the reconciliation request limit."
                ) from single_exc
        else:
            current = trial
    if current:
        batches.append(current)
    return batches


def _check_reconciliation_cancel(cancelled: CancelCheck | None) -> None:
    if cancelled is not None and cancelled():
        raise OrganizationCancelledError("Story organization was cancelled.")


def _build_reconciliation_batch_request(
    run_id: str,
    chunk_id: str,
    scene: str,
    events: Sequence[_EventCandidate],
) -> OrganizationRequest:
    evidence_ids = frozenset(
        value
        for event in events
        for value in (
            *event.allowed_evidence_ids,
            *(evidence for _, ids in event.claims for evidence in ids),
        )
    )
    fact_ids = frozenset(
        value
        for event in events
        for value in (*event.allowed_fact_ids, *event.fact_ids)
    )
    return build_reconciliation_request(
        run_id=run_id,
        chunk_id=chunk_id,
        scope_id=scene,
        events=[_stage_two_event(event) for event in events],
        ordered_event_ids=tuple(event.id for event in events),
        evidence_ids=evidence_ids,
        fact_ids=fact_ids,
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
        try:
            request = _build_arc_batch_request(
                "size-check",
                "size-check",
                trial,
                local_connectivity,
            )
        except ValueError as exc:
            if "complete organization prompt exceeds" not in str(exc).casefold():
                raise
            request = None
        size = ARC_MAX_CHARS + 1 if request is None else _complete_prompt_chars(request)
        if current and (len(trial) > ARC_MAX_EVENTS or size > ARC_MAX_CHARS):
            batches.append(current)
            current = [event]
            try:
                request = _build_arc_batch_request(
                    "size-check", "size-check", current, local_connectivity
                )
            except ValueError as exc:
                if "complete organization prompt exceeds" not in str(exc).casefold():
                    raise
                raise OrganizationError(
                    "A single normalized event exceeds the arc request limit."
                ) from exc
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
                "characters": [
                    character
                    for character in event.characters
                    if character in event.allowed_character_names
                ],
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
                "characters": [
                    character
                    for character in event.characters
                    if character in event.allowed_character_names
                ],
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
                "characters": [
                    character
                    for character in arc.characters
                    if character
                    in {
                        supported
                        for event_id in arc.member_ids
                        for supported in events_by_id[event_id].allowed_character_names
                    }
                ],
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
    "resolve_organization_scopes",
]
