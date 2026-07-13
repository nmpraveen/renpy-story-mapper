"""Loopback-facing M07 route and consent-gated organization workflow.

The service deliberately opens a fresh project connection for each operation.  Provider work
runs only from :meth:`start`; route rendering, detail, status, and preparation are read-only and
never construct a provider.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePath
from typing import cast

from renpy_story_mapper import storage
from renpy_story_mapper.m07_model import CheckpointStatus
from renpy_story_mapper.organization.contracts import (
    M05_CLOUD_MODEL,
    M05_REASONING_PROFILE,
    AttemptGate,
    CancelledCallback,
    OrganizationChunkResult,
    OrganizationConstraints,
    OrganizationGroup,
    OrganizationProvider,
    OrganizationRequest,
    OrganizationStage,
    ProviderStatus,
    serialize_organization_prompt,
)
from renpy_story_mapper.organization.contracts import (
    ProgressCallback as ProviderProgressCallback,
)
from renpy_story_mapper.organization.errors import (
    InvalidProviderOutputError,
    OrganizationCancelledError,
)
from renpy_story_mapper.organization.parallel import (
    BudgetPolicy,
    CheckpointState,
    ParallelOrganizationScheduler,
    ProgressSnapshot,
    RouteScope,
    SchedulerConfig,
)
from renpy_story_mapper.organization.persistence import PersistentCheckpointSink
from renpy_story_mapper.organization.validation import validate_result
from renpy_story_mapper.project import Project
from renpy_story_mapper.route_map import (
    RouteScope as DeterministicRouteScope,
)
from renpy_story_mapper.route_map import page_route_map_payload

ProviderFactory = Callable[[RouteScope], OrganizationProvider]
ProgressCallback = Callable[[ProgressSnapshot], None]


class PreparedRunError(ValueError):
    """Raised when fresh exact consent is absent or stale."""


@dataclass(frozen=True)
class PreparedRun:
    run_id: str
    authority_hash: str
    scope_ids: tuple[str, ...]
    config: SchedulerConfig


class _ValidatingProvider:
    """Keep even injected providers inside the exact-ID validation boundary."""

    def __init__(
        self, provider: OrganizationProvider, transmission_guard: Callable[[], None]
    ) -> None:
        self._provider = provider
        self._transmission_guard = transmission_guard
        self._attempt_gate_installed = False
        self._fallback_attempt_gate: AttemptGate | None = None

    def status(self) -> ProviderStatus:
        return self._provider.status()

    def organize(
        self,
        request: OrganizationRequest,
        progress: ProviderProgressCallback,
        cancelled: CancelledCallback,
    ) -> OrganizationChunkResult:
        # Providers without an attempt primitive get the strongest available one-call guard.
        # Providers with the primitive are guarded at each exact transmission below.
        if not self._attempt_gate_installed:
            self._transmission_guard()
            if self._fallback_attempt_gate is not None:
                prompt = serialize_organization_prompt(request, repair=False).encode("utf-8")
                if not self._fallback_attempt_gate(prompt):
                    raise OrganizationCancelledError(
                        "The aggregate provider budget stopped transmission."
                    )
        result = self._provider.organize(
            request,
            progress,
            cancelled,
        )
        if (
            result.metadata is not None
            and result.metadata.model_identifier is not None
            and result.metadata.model_identifier != M05_CLOUD_MODEL
        ):
            raise InvalidProviderOutputError("The provider reported an unexpected model.")
        # Provider adapters normally validate themselves.  Revalidation is cheap and ensures
        # mocked/custom providers cannot cross deterministic authority.
        validated = validate_result(result.raw_normalized, request)
        return replace(validated, attempts=result.attempts, metadata=result.metadata)

    def set_attempt_gate(self, gate: AttemptGate | None) -> None:
        """Compose persisted authority before scheduler reservation for every transmission."""

        setter = getattr(self._provider, "set_attempt_gate", None)
        if not callable(setter):
            self._attempt_gate_installed = False
            self._fallback_attempt_gate = gate
            return
        if gate is None:
            setter(None)
            self._attempt_gate_installed = False
            self._fallback_attempt_gate = None
            return

        def guarded(prompt: bytes) -> bool:
            self._transmission_guard()
            return gate(prompt)

        setter(guarded)
        self._attempt_gate_installed = True
        self._fallback_attempt_gate = None

    def cancel(self) -> None:
        self._provider.cancel()

    def __getattr__(self, name: str) -> object:
        return getattr(self._provider, name)


class _WorkflowCheckpointSink(PersistentCheckpointSink):
    """Bridge budget-stopped, never-started scopes into the durable state machine."""

    def event(
        self,
        scope: RouteScope,
        state: CheckpointState,
        identity: str,
        *,
        error_code: str | None = None,
        message: str | None = None,
    ) -> None:
        checkpoint = self._checkpoint(scope.request.scope_id)
        if (
            checkpoint is not None
            and checkpoint.status is CheckpointStatus.PENDING
            and state in {CheckpointState.FALLBACK, CheckpointState.FAILED}
        ):
            super().event(scope, CheckpointState.CACHED_OR_IN_FLIGHT, identity)
        super().event(
            scope,
            state,
            identity,
            error_code=error_code,
            message=message,
        )


class M07WorkflowService:
    """Cohesive M07 route-map, checkpoint, consent, and assembly boundary."""

    def __init__(self, project_path: Path, provider_factory: ProviderFactory) -> None:
        self._project_path = project_path
        self._provider_factory = provider_factory
        self._lock = threading.RLock()
        self._prepared: PreparedRun | None = None
        self._last_progress: ProgressSnapshot | None = None
        self._last_progress_generation: str | None = None
        self._last_budget: BudgetPolicy | None = None
        self._last_budget_generation: str | None = None

    def route_map(
        self,
        *,
        offset: int = 0,
        limit: int = 30,
        edge_offset: int = 0,
        edge_limit: int = 180,
    ) -> dict[str, object]:
        with Project.open(self._project_path) as project:
            route = _route_payload(project)
            generation = _authority_hash(route)
            overlay, applied = _applied_overlay(project, generation=generation)
            coverage = project.m07_model_service().coverage(generation=generation).to_dict()
        page = page_route_map_payload(
            route,
            offset=offset,
            limit=limit,
            edge_offset=edge_offset,
            edge_limit=edge_limit,
        )
        page["nodes"] = [
            _overlay_node(item, overlay) for item in _records(page.get("nodes"), "nodes")
        ]
        nodes = _records(route.get("nodes"), "nodes")
        nodes_by_id = {_string(item.get("id"), "node id"): item for item in nodes}
        rendered_node_ids = {
            _string(item.get("id"), "node id") for item in _records(page.get("nodes"), "nodes")
        }
        for edge in _records(page.get("edges"), "edges"):
            rendered_node_ids.update(
                {
                    _string(edge.get("source_id"), "edge source id"),
                    _string(edge.get("target_id"), "edge target id"),
                }
            )
        lanes = sorted(
            {
                (
                    _string(nodes_by_id[node_id].get("lane_id"), "lane id"),
                    str(nodes_by_id[node_id].get("lane_kind", "spine")),
                )
                for node_id in rendered_node_ids
                if node_id in nodes_by_id
            }
        )
        result = {
            **page,
            "schema_version": route.get("schema_version", 1),
            "authority_hash": generation,
            "totals": {
                "nodes": page["total_nodes"],
                "edges": page["total_edges"],
                "scopes": len(_records(route.get("scopes"), "scopes")),
            },
            "coverage": _json_mapping(route.get("coverage")),
            "organization_coverage": coverage,
            "ai_coverage": _ratio(coverage, "validated"),
            "technical_coverage": _technical_ratio(coverage),
            "initial_node_ids": list(_strings(route.get("initial_node_ids")))[:30],
            "lanes": [{"id": lane_id, "kind": lane_kind} for lane_id, lane_kind in lanes],
            "applied_assembly": applied,
        }
        return cast(dict[str, object], _sanitize(result))

    def detail(self, element_id: str) -> dict[str, object]:
        with Project.open(self._project_path) as project:
            route = _route_payload(project)
            generation = _authority_hash(route)
            overlay, _applied = _applied_overlay(project, generation=generation)
            facts = _facts_by_id(project)
            provenance = _provenance_by_path(project)
            graph_sources = _graph_sources_by_id(project)
        nodes = _records(route.get("nodes"), "nodes")
        edges = _records(route.get("edges"), "edges")
        evidence_by_id = {
            _string(item.get("id"), "evidence id"): item
            for item in _records(route.get("evidence"), "evidence")
        }
        node = next((item for item in nodes if item.get("id") == element_id), None)
        if node is not None:
            predecessor_ids = [
                item["source_id"] for item in edges if item.get("target_id") == element_id
            ]
            successor_ids = [
                item["target_id"] for item in edges if item.get("source_id") == element_id
            ]
            evidence_ids = _strings(node.get("evidence_ids"))
            incident = [
                item
                for item in edges
                if item.get("source_id") == element_id or item.get("target_id") == element_id
            ]
            node_gate_ids = sorted(
                {fact_id for item in incident for fact_id in _strings(item.get("gate_ids"))}
            )
            node_effect_ids = sorted(
                {fact_id for item in incident for fact_id in _strings(item.get("effect_ids"))}
            )
            result: dict[str, object] = {
                "level": "detail_evidence",
                "element": _overlay_node(node, overlay),
                "predecessor_ids": predecessor_ids,
                "successor_ids": successor_ids,
                "local_path": [*predecessor_ids, element_id, *successor_ids],
                "gates": [facts[item] for item in node_gate_ids if item in facts],
                "effects": [facts[item] for item in node_effect_ids if item in facts],
                "evidence": [
                    _detail_evidence(evidence_by_id[item], provenance, graph_sources)
                    for item in evidence_ids
                    if item in evidence_by_id
                ],
                "back_target": "route_map",
            }
            return cast(dict[str, object], _sanitize(result))
        edge = next((item for item in edges if item.get("id") == element_id), None)
        if edge is None:
            raise KeyError(element_id)
        evidence_ids = _strings(edge.get("evidence_ids"))
        gate_ids = _strings(edge.get("gate_ids"))
        effect_ids = _strings(edge.get("effect_ids"))
        result = {
            "level": "detail_evidence",
            "element": edge,
            "predecessor_ids": [edge.get("source_id")],
            "successor_ids": [edge.get("target_id")],
            "local_path": [edge.get("source_id"), element_id, edge.get("target_id")],
            "gates": [facts[item] for item in gate_ids if item in facts],
            "effects": [facts[item] for item in effect_ids if item in facts],
            "evidence": [
                _detail_evidence(evidence_by_id[item], provenance, graph_sources)
                for item in evidence_ids
                if item in evidence_by_id
            ],
            "back_target": "route_map",
        }
        return cast(dict[str, object], _sanitize(result))

    def prepare(
        self,
        *,
        scope_ids: Sequence[str],
        budget: BudgetPolicy,
    ) -> dict[str, object]:
        # This method intentionally does not touch the provider factory.
        with Project.open(self._project_path) as project:
            route = _route_payload(project)
            _require_ai_transmission_allowed(project)
            generation = _authority_hash(route)
            checkpoints = project.m07_model_service().checkpoints(generation=generation)
        deterministic = _deterministic_scopes(route)
        available = {item.id for item in deterministic}
        selected = tuple(scope_ids) if scope_ids else tuple(item.id for item in deterministic)
        if not selected or len(set(selected)) != len(selected) or set(selected) != available:
            raise ValueError("scope_ids must name the complete current deterministic route scope")
        run_id = f"m07_{secrets.token_urlsafe(32)}"
        _require_finite_budget(budget)
        config = SchedulerConfig(budget=budget)
        prepared = PreparedRun(run_id, generation, selected, config)
        with self._lock:
            self._prepared = prepared
            self._last_budget = budget
            self._last_budget_generation = generation
        cached = sum(
            item.status in {CheckpointStatus.CACHED, CheckpointStatus.VALIDATED}
            for item in checkpoints
        )
        return {
            "run_id": run_id,
            "scopes": len(selected),
            "scope_ids": list(selected),
            "cached": cached,
            "model": {
                "id": M05_CLOUD_MODEL,
                "reasoning": M05_REASONING_PROFILE,
                "fast_mode": False,
            },
            "budgets": _budget_dict(budget),
            "authority_hash": generation,
            "requires_confirm_cloud": True,
        }

    def start(
        self,
        run_id: str,
        *,
        confirm_cloud: bool,
        scope_ids: Sequence[str],
        budget: BudgetPolicy,
        cancelled: Callable[[], bool],
        progress: ProgressCallback | None = None,
    ) -> dict[str, object]:
        prepared = self.authorize_start(
            run_id, confirm_cloud=confirm_cloud, scope_ids=scope_ids, budget=budget
        )
        return self.run_prepared(prepared, cancelled=cancelled, progress=progress)

    def authorize_start(
        self,
        run_id: str,
        *,
        confirm_cloud: bool,
        scope_ids: Sequence[str],
        budget: BudgetPolicy,
    ) -> PreparedRun:
        """Consume exact fresh consent synchronously, before a background task is accepted."""

        if not confirm_cloud:
            raise PreparedRunError("fresh cloud confirmation is required")
        with self._lock:
            prepared = self._prepared
            if prepared is None or not secrets.compare_digest(prepared.run_id, run_id):
                raise PreparedRunError("the prepared run is missing or stale")
            # Exact consent becomes single-use only after its own opaque run ID is presented.
            self._prepared = None
        if tuple(scope_ids) != prepared.scope_ids:
            raise PreparedRunError("the start scope_ids do not match the prepared run")
        if _budget_dict(budget) != _budget_dict(prepared.config.budget):
            raise PreparedRunError("the start budget does not match the prepared run")
        with Project.open(self._project_path) as project:
            route = _route_payload(project)
            _validate_prepared_authority(project, route, prepared)
        return prepared

    def run_prepared(
        self,
        prepared: PreparedRun,
        *,
        cancelled: Callable[[], bool],
        progress: ProgressCallback | None = None,
    ) -> dict[str, object]:
        """Execute one already-authorized run inside the cancellable background boundary."""

        run_id = prepared.run_id
        with Project.open(self._project_path) as project:
            route = _route_payload(project)
            _validate_prepared_authority(project, route, prepared)
            deterministic = _deterministic_scopes(route)
            scopes = _organization_scopes(route, deterministic, run_id, _facts_by_id(project))
            sink = _WorkflowCheckpointSink(
                project,
                generation=prepared.authority_hash,
                deterministic_scopes=deterministic,
                organization_scopes=scopes,
                config=prepared.config,
            )

            def provider_factory(scope: RouteScope) -> OrganizationProvider:
                return cast(
                    OrganizationProvider,
                    _ValidatingProvider(
                        self._provider_factory(scope),
                        lambda: _guard_provider_transmission(
                            self._project_path, prepared
                        ),
                    ),
                )

            def on_progress(snapshot: ProgressSnapshot) -> None:
                with self._lock:
                    self._last_progress = snapshot
                    self._last_progress_generation = prepared.authority_hash
                if progress is not None:
                    progress(snapshot)

            result = ParallelOrganizationScheduler(provider_factory, sink, prepared.config).run(
                scopes,
                consent_run_id=run_id,
                cancelled=cancelled,
                progress=on_progress,
            )
            assembly = sink.last_assembly
            return {
                "run_id": run_id,
                "progress": _progress_dict(result.progress),
                "assembly": None if assembly is None else assembly.to_dict(),
            }

    def status(
        self,
        *,
        stage: str = "idle",
        status_override: str | None = None,
    ) -> dict[str, object]:
        with Project.open(self._project_path) as project:
            route = _route_payload(project)
            generation = _authority_hash(route)
            model = project.m07_model_service()
            checkpoints = model.checkpoints(generation=generation)
            coverage = model.coverage(generation=generation).to_dict()
            assemblies = _assembly_metadata(project, generation=generation)
            draft = model.current_draft(generation=generation)
            source_coverage = project.source_coverage()
            attempt_row = (
                project._require_open()
                .execute("SELECT COALESCE(AVG(elapsed_ms),0) average_ms FROM m07_provider_attempts")
                .fetchone()
            )
        with self._lock:
            progress = (
                self._last_progress
                if self._last_progress_generation == generation
                else None
            )
            budget = (
                self._last_budget if self._last_budget_generation == generation else None
            )
        pending = _count(coverage["pending"]) + _count(coverage["cached_or_in_flight"])
        average = 0.0 if attempt_row is None else float(attempt_row["average_ms"]) / 1000
        derived_eta = None if not average or not pending else average * pending / 8
        ai_coverage = _ratio(coverage, "validated")
        technical_coverage = _technical_ratio(coverage)
        token_used = _count(coverage["input_tokens"]) + _count(coverage["output_tokens"])
        partial = (
            bool(progress.partial)
            if progress is not None
            else _count(coverage["completed"]) < _count(coverage["total"])
            or _count(coverage["fallback"]) > 0
        )
        reviewable = next(
            (item for item in assemblies if item.get("status") == "draft"),
            None,
        )
        organization_status = status_override or _organization_status(coverage, assemblies, partial)
        return {
            "status": organization_status,
            "stage": stage,
            "scopes": {
                "total": coverage["total"],
                "pending": pending,
                "validated": coverage["validated"],
                "fallback": coverage["fallback"],
                "failed": coverage["failed"],
                "cancelled": coverage["cancelled"],
            },
            "scope_counts": coverage,
            "scope_statuses": [
                {"scope_id": item.scope_id, "status": item.status.value, "error": item.error_code}
                for item in checkpoints
            ],
            "calls": coverage["calls"],
            "tokens": {
                "used": token_used,
                "budget": _token_budget(budget),
                "input": coverage["input_tokens"],
                "output": coverage["output_tokens"],
                "total": token_used,
            },
            "coverage": {"ai": ai_coverage, "technical": technical_coverage},
            "ai_coverage": ai_coverage,
            "technical_coverage": technical_coverage,
            "eta": {
                "low_seconds": progress.eta_low_seconds if progress is not None else derived_eta,
                "high_seconds": progress.eta_high_seconds
                if progress is not None
                else (None if derived_eta is None else derived_eta * 1.5),
            },
            "partial": partial,
            "worker_peak": 0 if progress is None else progress.peak_workers,
            "assembly_id": None if reviewable is None else reviewable["assembly_id"],
            "assembly": None if draft is None else _sanitize(draft.to_dict()),
            "assemblies": assemblies,
            "authority_hash": generation,
            "source_coverage": source_coverage,
        }

    def apply(self, assembly_id: str) -> dict[str, object]:
        try:
            with Project.open(self._project_path) as project:
                generation = _authority_hash(_route_payload(project))
                assembly = project.m07_model_service().apply(
                    assembly_id, generation=generation
                )
        except KeyError as exc:
            raise KeyError("assembly not found") from exc
        return assembly.to_dict()

    def discard(self, assembly_id: str) -> dict[str, object]:
        try:
            with Project.open(self._project_path) as project:
                generation = _authority_hash(_route_payload(project))
                assembly = project.m07_model_service().discard(
                    assembly_id, generation=generation
                )
        except KeyError as exc:
            raise KeyError("assembly not found") from exc
        return assembly.to_dict()

    def acknowledge_recovered_sources(self, *, coverage_token: str) -> dict[str, object]:
        """Acknowledge only the exact currently persisted incomplete-recovery snapshot."""

        with Project.open(self._project_path) as project:
            project.acknowledge_incomplete_source_coverage(coverage_token=coverage_token)
            return project.source_coverage()

    def set_override(
        self,
        scope_id: str,
        *,
        generation: str,
        correction: Mapping[str, object],
        pinned: bool,
    ) -> dict[str, object]:
        with Project.open(self._project_path) as project:
            current = _authority_hash(_route_payload(project))
            if generation != current:
                raise PreparedRunError("the route scope generation is stale")
            if set(correction) - {"title", "summary"} or any(
                not isinstance(value, str) or not value.strip() or len(value) > 5_000
                for value in correction.values()
            ):
                raise ValueError("correction supports only non-empty title and summary strings")
            model = project.m07_model_service()
            model.set_override(
                scope_id,
                generation=generation,
                correction=correction,
                pinned=pinned,
            )
            return model.assemble(generation=generation, allow_partial=True).to_dict()

    def search_route(
        self, query: str, *, after: str | None = None, limit: int = 30
    ) -> dict[str, object]:
        """Search all authoritative route nodes with a generation-bound bounded cursor."""

        if not query.strip():
            raise ValueError("route query cannot be empty")
        if not 1 <= limit <= 30:
            raise ValueError("route search limit must be between 1 and 30")
        with Project.open(self._project_path) as project:
            route = _route_payload(project)
        generation = _authority_hash(route)
        normalized = query.casefold().strip()
        offset = _decode_search_cursor(after, generation=generation, query=normalized)
        matches = [
            item
            for item in sorted(
                _records(route.get("nodes"), "nodes"), key=lambda value: (
                    _integer(value.get("order"), "node order"),
                    _string(value.get("id"), "node id"),
                )
            )
            if normalized
            in " ".join(
                str(item.get(name, "")) for name in ("id", "title", "kind", "lane_id")
            ).casefold()
        ]
        items = matches[offset : offset + limit]
        next_offset = offset + len(items)
        return {
            "query": query,
            "authority_hash": generation,
            "items": [_sanitize(item) for item in items],
            "continuation": (
                _encode_search_cursor(next_offset, generation=generation, query=normalized)
                if next_offset < len(matches)
                else None
            ),
            "has_more": next_offset < len(matches),
            "total_matches": len(matches),
            "limit": limit,
        }


def _route_payload(project: Project) -> dict[str, object]:
    value = project.payload("m07_route_map", "authoritative")
    if not isinstance(value, dict):
        raise ValueError("the project has no valid M07 route map")
    return cast(dict[str, object], value)


def _authority_hash(route: Mapping[str, object]) -> str:
    return hashlib.sha256(storage.canonical_json(route)).hexdigest()


def _deterministic_scopes(route: Mapping[str, object]) -> tuple[DeterministicRouteScope, ...]:
    result: list[DeterministicRouteScope] = []
    for item in _records(route.get("scopes"), "scopes"):
        result.append(
            DeterministicRouteScope(
                id=_string(item.get("id"), "scope id"),
                ordinal=_integer(item.get("ordinal"), "scope ordinal"),
                lane_id=_string(item.get("lane_id"), "scope lane"),
                node_ids=_strings(item.get("node_ids")),
                edge_ids=_strings(item.get("edge_ids")),
                evidence_ids=_strings(item.get("evidence_ids")),
                input_hash=_digest(item.get("input_hash"), "scope input hash"),
            )
        )
    return tuple(sorted(result, key=lambda item: (item.ordinal, item.id)))


def _organization_scopes(
    route: Mapping[str, object],
    deterministic: Sequence[DeterministicRouteScope],
    run_id: str,
    facts: Mapping[str, Mapping[str, object]],
) -> tuple[RouteScope, ...]:
    nodes = {
        _string(item.get("id"), "node id"): item for item in _records(route.get("nodes"), "nodes")
    }
    edges = {
        _string(item.get("id"), "edge id"): item for item in _records(route.get("edges"), "edges")
    }
    evidence = {
        _string(item.get("id"), "evidence id"): item
        for item in _records(route.get("evidence"), "evidence")
    }
    result: list[RouteScope] = []
    for scope in deterministic:
        scope_nodes = [_sanitize(nodes[item]) for item in scope.node_ids if item in nodes]
        scope_edges = [_sanitize(edges[item]) for item in scope.edge_ids if item in edges]
        scope_evidence = [
            _sanitize(evidence[item]) for item in scope.evidence_ids if item in evidence
        ]
        fact_ids = frozenset(
            item
            for edge in scope_edges
            if isinstance(edge, dict)
            for key in ("gate_ids", "effect_ids")
            for item in _strings(edge.get(key))
        )
        request = OrganizationRequest(
            run_id=run_id,
            chunk_id=f"chunk_{scope.id}",
            scope_id=scope.id,
            stage=OrganizationStage.EVENTS,
            payload={
                "route_scope_id": scope.id,
                "node_ids": list(scope.node_ids),
                "edge_ids": list(scope.edge_ids),
                "evidence_ids": list(scope.evidence_ids),
                "fact_ids": sorted(fact_ids),
                "facts": [_sanitize(facts[item]) for item in sorted(fact_ids) if item in facts],
                "nodes": scope_nodes,
                "edges": scope_edges,
                "evidence": scope_evidence,
            },
            constraints=OrganizationConstraints(
                ordered_member_ids=scope.node_ids,
                required_member_ids=frozenset(scope.node_ids),
                fact_ids=fact_ids,
                evidence_ids=frozenset(scope.evidence_ids),
            ),
            cloud_consent_run_id=run_id,
            model=M05_CLOUD_MODEL,
        )
        fallback = OrganizationChunkResult(
            stage=OrganizationStage.EVENTS,
            groups=(
                OrganizationGroup(
                    id=f"technical_{scope.id}",
                    title="Technical route",
                    summary="Deterministic route scope without AI interpretation.",
                    member_ids=scope.node_ids,
                    characters=(),
                    importance="supporting",
                    outcomes=(),
                    promoted_fact_ids=(),
                    claims=(),
                    warnings=(),
                ),
            ),
            ungrouped_ids=(),
            raw_normalized={
                "stage": "events",
                "groups": [
                    {
                        "id": f"technical_{scope.id}",
                        "title": "Technical route",
                        "summary": "Deterministic route scope without AI interpretation.",
                        "member_ids": list(scope.node_ids),
                        "characters": [],
                        "importance": "supporting",
                        "outcomes": [],
                        "promoted_fact_ids": [],
                        "claims": [],
                        "warnings": [],
                    }
                ],
                "ungrouped_ids": [],
            },
        )
        result.append(RouteScope(scope.ordinal, request, fallback))
    return tuple(result)


def _facts_by_id(project: Project) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for collection in ("gates", "effects"):
        for key in project.payload_keys(collection):
            value = project.payload(collection, key)
            if not isinstance(value, list):
                continue
            for item in value:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    result[str(item["id"])] = cast(dict[str, object], item)
    return result


def _applied_overlay(
    project: Project, *, generation: str
) -> tuple[dict[str, dict[str, object]], object | None]:
    row = (
        project._require_open()
        .execute(
            """SELECT assembly_id,payload_hash,payload_json FROM m07_assemblies
           WHERE status='applied' AND generation=?
           ORDER BY applied_utc DESC,assembly_id DESC LIMIT 1""",
            (generation,),
        )
        .fetchone()
    )
    if row is None:
        return {}, None
    payload = storage.decode_json(row["payload_json"])
    overlay: dict[str, dict[str, object]] = {}
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        for item in payload["items"]:
            if not isinstance(item, dict) or not isinstance(item.get("result"), dict):
                continue
            correction = item.get("correction")
            correction = correction if isinstance(correction, dict) else {}
            pinned = bool(item.get("pinned", False))
            encoded = item["result"].get("organization_result")
            if not isinstance(encoded, dict) or not isinstance(encoded.get("groups"), list):
                continue
            for group in encoded["groups"]:
                if not isinstance(group, dict):
                    continue
                title, summary = group.get("title"), group.get("summary")
                members = group.get("member_ids")
                if (
                    isinstance(title, str)
                    and isinstance(summary, str)
                    and isinstance(members, list)
                ):
                    for member in members:
                        if isinstance(member, str):
                            overlay[member] = {
                                "title": correction.get("title", title),
                                "summary": correction.get("summary", summary),
                                "claims": group.get("claims", []),
                                "correction": correction,
                                "pinned": pinned,
                                "scope_id": item.get("scope_id"),
                            }
    return overlay, {
        "assembly_id": str(row["assembly_id"]),
        "payload_hash": str(row["payload_hash"]),
    }


def _overlay_node(
    item: Mapping[str, object], overlay: Mapping[str, Mapping[str, object]]
) -> dict[str, object]:
    result = dict(item)
    node_id = item.get("id")
    if isinstance(node_id, str) and node_id in overlay:
        interpretation = overlay[node_id]
        result["title"] = interpretation["title"]
        result["summary"] = interpretation["summary"]
        result["organization"] = "ai_interpretation"
        result["interpretation"] = dict(interpretation)
    else:
        result["summary"] = str(result.get("title", ""))
        result["organization"] = "technical"
        result["interpretation"] = None
    return result


def _assembly_metadata(project: Project, *, generation: str) -> list[dict[str, object]]:
    rows = project._require_open().execute(
        """SELECT assembly_id,generation,status,payload_hash,coverage_json,created_utc,applied_utc
           FROM m07_assemblies WHERE generation=? AND status<>'superseded'
           ORDER BY created_utc DESC,assembly_id DESC""",
        (generation,),
    )
    return [
        {
            "assembly_id": str(row["assembly_id"]),
            "generation": str(row["generation"]),
            "status": str(row["status"]),
            "payload_hash": str(row["payload_hash"]),
            "coverage": storage.decode_json(row["coverage_json"]),
            "created_utc": str(row["created_utc"]),
            "applied_utc": None if row["applied_utc"] is None else str(row["applied_utc"]),
        }
        for row in rows
    ]


def _require_ai_transmission_allowed(project: Project) -> None:
    coverage = project.source_coverage()
    if coverage.get("ai_transmission_blocked") is True:
        raise PreparedRunError(
            "AI transmission is blocked until recovered-source coverage is acknowledged"
        )


def _validate_prepared_authority(
    project: Project, route: Mapping[str, object], prepared: PreparedRun
) -> None:
    _require_ai_transmission_allowed(project)
    if _authority_hash(route) != prepared.authority_hash:
        raise PreparedRunError("the deterministic route scope changed after preparation")
    current_scope_ids = tuple(item.id for item in _deterministic_scopes(route))
    if current_scope_ids != prepared.scope_ids:
        raise PreparedRunError("the deterministic route scope set changed after preparation")


def _guard_provider_transmission(project_path: Path, prepared: PreparedRun) -> None:
    with Project.open(project_path) as project:
        _validate_prepared_authority(project, _route_payload(project), prepared)


def _require_finite_budget(budget: BudgetPolicy) -> None:
    if budget.hard_seconds is None or budget.hard_tokens is None or budget.hard_calls is None:
        raise ValueError("finite hard_seconds, hard_tokens, and hard_calls are required")


def _provenance_by_path(project: Project) -> dict[str, Mapping[str, object]]:
    return {
        str(item["source_path"]): item
        for item in project.source_derivations()
        if isinstance(item.get("source_path"), str)
    }


def _graph_sources_by_id(project: Project) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for collection in ("m01_graph", "m06_control_flow"):
        payload = project.payload(collection, "authoritative")
        if not isinstance(payload, dict):
            continue
        for node in _records(payload.get("nodes"), f"{collection}.nodes"):
            node_id = node.get("id")
            source = node.get("source")
            if isinstance(node_id, str) and isinstance(source, Mapping):
                result.setdefault(node_id, source)
    return result


def _detail_evidence(
    evidence: Mapping[str, object],
    provenance: Mapping[str, Mapping[str, object]],
    graph_sources: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    result = dict(evidence)
    source = evidence.get("source")
    qualified_node_id: str | None = None
    if not isinstance(source, Mapping):
        payload = evidence.get("payload")
        if isinstance(payload, Mapping):
            for name in ("source", "target"):
                candidate = payload.get(name)
                if isinstance(candidate, str) and candidate in graph_sources:
                    qualified_node_id = candidate
                    source = graph_sources[candidate]
                    break
    if not isinstance(source, Mapping):
        raise storage.ProjectCorruptError("route evidence has no qualified source location")
    path = source.get("path")
    start = source.get("start")
    end = source.get("end")
    if (
        not isinstance(path, str)
        or not isinstance(start, Mapping)
        or not isinstance(end, Mapping)
        or not isinstance(start.get("line"), int)
        or isinstance(start.get("line"), bool)
        or not isinstance(end.get("line"), int)
        or isinstance(end.get("line"), bool)
    ):
        raise storage.ProjectCorruptError("route evidence has invalid nested source lines")
    derivation = provenance.get(path)
    result.update(
        {
            "source_path": path,
            "start_line": int(start["line"]),
            "end_line": int(end["line"]),
            "line_basis": (
                derivation.get("line_basis") if derivation is not None else "physical_source"
            ),
            "provenance": None if derivation is None else dict(derivation),
            "qualified_from_graph_node_id": qualified_node_id,
        }
    )
    return result


def _encode_search_cursor(offset: int, *, generation: str, query: str) -> str:
    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
    return f"m07s_{generation[:16]}_{query_hash}_{offset}"


def _decode_search_cursor(after: str | None, *, generation: str, query: str) -> int:
    if after is None:
        return 0
    prefix = _encode_search_cursor(0, generation=generation, query=query).rsplit("_", 1)[0]
    if not after.startswith(prefix + "_"):
        raise ValueError("route search continuation is stale or mismatched")
    raw_offset = after[len(prefix) + 1 :]
    if not raw_offset.isascii() or not raw_offset.isdigit():
        raise ValueError("route search continuation is invalid")
    offset = int(raw_offset)
    if offset < 0 or offset > 2_000_000:
        raise ValueError("route search continuation is invalid")
    return offset


def _budget_dict(budget: BudgetPolicy) -> dict[str, object]:
    return {
        "soft_seconds": _integral_seconds(budget.soft_seconds, "soft_seconds"),
        "hard_seconds": _integral_seconds(budget.hard_seconds, "hard_seconds"),
        "soft_tokens": budget.soft_tokens,
        "hard_tokens": budget.hard_tokens,
        "hard_calls": budget.hard_calls,
    }


def _integral_seconds(value: float | None, name: str) -> int | None:
    if value is None:
        return None
    result = int(value)
    if result != value:
        raise ValueError(f"{name} must be an integral number of seconds")
    return result


def _token_budget(budget: BudgetPolicy | None) -> int:
    if budget is None:
        return 0
    if budget.hard_tokens is not None:
        return budget.hard_tokens
    return 0 if budget.soft_tokens is None else budget.soft_tokens


def _organization_status(
    coverage: Mapping[str, object],
    assemblies: Sequence[Mapping[str, object]],
    partial: bool,
) -> str:
    if any(item.get("status") == "draft" for item in assemblies):
        return "partial" if partial else "review"
    if any(item.get("status") == "applied" for item in assemblies):
        return "applied"
    if _count(coverage.get("cancelled", 0)):
        return "cancelled"
    if _count(coverage.get("failed", 0)):
        return "failed"
    if _count(coverage.get("pending", 0)) or _count(coverage.get("cached_or_in_flight", 0)):
        return "idle"
    if _count(coverage.get("validated", 0)) or _count(coverage.get("fallback", 0)):
        return "complete"
    return "idle"


def _progress_dict(value: ProgressSnapshot) -> dict[str, object]:
    return {
        "stage": "complete",
        "scope_counts": {
            "total": value.total,
            "validated": value.validated,
            "fallback": value.fallback,
            "failed": value.failed,
            "cancelled": value.cancelled,
            "pending": value.pending,
        },
        "calls": value.calls,
        "tokens": {"input": value.input_tokens, "output": value.output_tokens},
        "ai_coverage": value.ai_coverage,
        "technical_coverage": value.technical_coverage,
        "eta": {"low_seconds": value.eta_low_seconds, "high_seconds": value.eta_high_seconds},
        "partial": value.partial,
        "worker_peak": value.peak_workers,
    }


def _ratio(coverage: Mapping[str, object], name: str) -> float:
    total = _count(coverage.get("total", 0))
    return 1.0 if total == 0 else _count(coverage.get(name, 0)) / total


def _technical_ratio(coverage: Mapping[str, object]) -> float:
    total = _count(coverage.get("total", 0))
    return (
        1.0
        if total == 0
        else (_count(coverage.get("validated", 0)) + _count(coverage.get("fallback", 0))) / total
    )


def _count(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("coverage count is invalid")
    return value


def _sanitize(value: object, *, key: str = "") -> object:
    if isinstance(value, dict):
        return {str(name): _sanitize(item, key=str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item, key=key) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item, key=key) for item in value]
    if isinstance(value, str) and _is_path_key(key):
        path = PurePath(value)
        return path.name if path.is_absolute() else path.as_posix().lstrip("/")
    return value


def _is_path_key(key: str) -> bool:
    return key in {"path", "file", "source_file", "executable", "locator"} or key.endswith(
        ("_path", "_file")
    )


def _records(value: object, name: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"route {name} are invalid")
    return cast(list[dict[str, object]], value)


def _strings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ValueError("route ID collection is invalid")
    return tuple(cast(Sequence[str], value))


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} is invalid")
    return value


def _integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} is invalid")
    return value


def _digest(value: object, name: str) -> str:
    result = _string(value, name)
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise ValueError(f"{name} is invalid")
    return result


def _json_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("route coverage is invalid")
    return cast(dict[str, object], value)
