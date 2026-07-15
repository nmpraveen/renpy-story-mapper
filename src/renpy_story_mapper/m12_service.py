"""Project-facing authority, cache, cancellation, and destination adapter for M12."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from renpy_story_mapper import storage
from renpy_story_mapper.canonical_graph_contract import (
    CANONICAL_GRAPH_SCHEMA,
    CANONICAL_GRAPH_SCHEMA_VERSION,
    CanonicalEdge,
    CanonicalFact,
    CanonicalGraph,
    CanonicalNode,
    CanonicalNodeKind,
    CanonicalRegion,
    DerivedProof,
    OriginReference,
    ReachabilityStatus,
    SourceEvidence,
)
from renpy_story_mapper.m11_persistence import M11Availability
from renpy_story_mapper.m11_scene_model import (
    M11_SCENE_MODEL_SCHEMA,
    M11_SCENE_MODEL_SCHEMA_VERSION,
    LaneKind,
    SceneModel,
)
from renpy_story_mapper.m11_scene_projection import scene_model_from_stored_results
from renpy_story_mapper.m12_model import (
    DestinationKind,
    RouteDestination,
    RouteRequest,
)
from renpy_story_mapper.m12_persistence import (
    AttemptStatus,
    RouteAttemptDiagnostic,
    RouteCacheIdentity,
    RouteCacheLookup,
    RouteCacheState,
    RoutePublication,
)
from renpy_story_mapper.m12_solver import bind_route_request, solve_route
from renpy_story_mapper.project import Project

M12_DESTINATIONS_SCHEMA: Final = "m12-destinations-v1"
DEFAULT_EMERGENCY_SECONDS: Final = 30.0
MAX_DESTINATION_PAGE: Final = 50

type CancelCheck = Callable[[], bool]


@dataclass(frozen=True)
class M12Authority:
    graph: CanonicalGraph
    scene_model: SceneModel
    m11_publication_hash: str

    @property
    def m10_provenance(self) -> dict[str, object]:
        return {
            "source_generation": self.graph.source_generation,
            "schema": CANONICAL_GRAPH_SCHEMA,
            "schema_version": CANONICAL_GRAPH_SCHEMA_VERSION,
            "canonical_hash": self.graph.authority_hash,
        }

    @property
    def m11_provenance(self) -> dict[str, object]:
        return {
            "schema": M11_SCENE_MODEL_SCHEMA,
            "schema_version": M11_SCENE_MODEL_SCHEMA_VERSION,
            "model_hash": self.scene_model.structural_hash,
            "publication_hash": self.m11_publication_hash,
        }


@dataclass(frozen=True)
class M12DestinationRecord:
    kind: DestinationKind
    target_id: str
    title: str
    subtitle: str
    provenance: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "target_id": self.target_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class M12PreparedSolve:
    authority: M12Authority
    request: RouteRequest
    identity: RouteCacheIdentity


@dataclass(frozen=True)
class M12SolveOutcome:
    identity: RouteCacheIdentity
    cached: bool
    result: Mapping[str, object] | None
    publication: RoutePublication | None = None
    diagnostic: RouteAttemptDiagnostic | None = None

    def to_dict(self) -> dict[str, object]:
        request = self.identity.document.get("request")
        if not isinstance(request, Mapping):
            raise ValueError("route cache identity lacks its normalized request")
        request_identity = hashlib.sha256(storage.canonical_json(request)).hexdigest()
        value: dict[str, object] = {
            "request_identity": request_identity,
            "cached": self.cached,
            "result": None if self.result is None else dict(self.result),
        }
        if self.publication is not None:
            value["result_hash"] = self.publication.result_hash
        if self.diagnostic is not None:
            value["diagnostic"] = self.diagnostic.to_dict()
        return value


class M12RouteService:
    """On-demand route facade over immutable M10/M11 authority."""

    def __init__(self, project: Project) -> None:
        self._project = project
        self._authority: M12Authority | None = None

    def _current_authority(self) -> M12Authority:
        if self._authority is None or not _authority_is_current(
            self._project, self._authority
        ):
            self._authority = load_m12_authority(self._project)
        return self._authority

    def destinations(
        self,
        *,
        query: str | None = None,
        offset: int = 0,
        limit: int = 30,
    ) -> dict[str, object]:
        if offset < 0 or not 1 <= limit <= MAX_DESTINATION_PAGE:
            raise ValueError("destination window is outside the supported bounds")
        authority = self._current_authority()
        records = list(_destination_records(authority))
        requested = (query or "").strip()
        if requested:
            needle = requested.casefold()
            records = [
                item
                for item in records
                if needle in item.title.casefold()
                or needle in item.subtitle.casefold()
                or needle in item.target_id.casefold()
            ]
        records.sort(key=lambda item: (item.title.casefold(), item.kind.value, item.target_id))
        page = records[offset : offset + limit]
        next_offset = offset + len(page) if offset + len(page) < len(records) else None
        return {
            "schema": M12_DESTINATIONS_SCHEMA,
            "status": "available",
            "source_generation": authority.graph.source_generation,
            "canonical_hash": authority.graph.authority_hash,
            "scene_model_hash": authority.scene_model.structural_hash,
            "query": requested,
            "offset": offset,
            "limit": limit,
            "next_offset": next_offset,
            "total": len(records),
            "nodes": [item.to_dict() for item in page],
        }

    def prepare(
        self,
        destination_kind: str,
        target_id: str,
    ) -> M12PreparedSolve:
        if not target_id:
            raise ValueError("route target ID cannot be empty")
        try:
            destination = RouteDestination(DestinationKind(destination_kind), target_id)
        except ValueError as exc:
            raise ValueError("route destination is unsupported") from exc
        authority = self._current_authority()
        request = bind_route_request(authority.graph, authority.scene_model, destination)
        identity = self._project.m12_persistence().identity(
            request.normalized_dict(),
            request.limits.to_dict(),
            m10_provenance=authority.m10_provenance,
            m11_provenance=authority.m11_provenance,
            solver_version=request.solver_version,
        )
        return M12PreparedSolve(authority, request, identity)

    def lookup(self, prepared: M12PreparedSolve) -> RouteCacheLookup:
        self._require_current(prepared.identity)
        return self._project.m12_persistence().lookup(prepared.identity)

    def lookup_identity(self, identity: RouteCacheIdentity) -> RouteCacheLookup:
        self._require_current(identity)
        return self._project.m12_persistence().lookup(identity)

    def solve(
        self,
        prepared: M12PreparedSolve,
        *,
        cancelled: CancelCheck | None = None,
        emergency_seconds: float = DEFAULT_EMERGENCY_SECONDS,
    ) -> M12SolveOutcome:
        if emergency_seconds <= 0:
            raise ValueError("emergency wall-clock bound must be positive")
        cached = self.lookup(prepared)
        if cached.state is RouteCacheState.HIT:
            assert cached.result is not None
            return M12SolveOutcome(prepared.identity, True, cached.result)
        if cached.state is RouteCacheState.UNAVAILABLE:
            raise storage.ProjectCorruptError("M12 cache is unavailable")

        started = time.monotonic()
        deadline = started + emergency_seconds
        emergency_abort = False

        def should_stop() -> bool:
            nonlocal emergency_abort
            if cancelled is not None and cancelled():
                return True
            if time.monotonic() >= deadline:
                emergency_abort = True
                return True
            return False

        attempt = solve_route(
            prepared.authority.graph,
            prepared.authority.scene_model,
            prepared.request,
            cancelled=should_stop,
        )
        if emergency_abort or time.monotonic() >= deadline:
            diagnostic = self._project.m12_persistence().attempt_diagnostic(
                prepared.identity,
                AttemptStatus.EMERGENCY_ABORT,
                "emergency wall-clock abort",
            )
            return M12SolveOutcome(prepared.identity, False, None, diagnostic=diagnostic)
        if attempt.cancelled or (cancelled is not None and cancelled()):
            diagnostic = self._project.m12_persistence().attempt_diagnostic(
                prepared.identity,
                AttemptStatus.CANCELLED,
                attempt.diagnostic or "cancelled",
            )
            return M12SolveOutcome(prepared.identity, False, None, diagnostic=diagnostic)
        if attempt.result is None:
            diagnostic = self._project.m12_persistence().attempt_diagnostic(
                prepared.identity,
                AttemptStatus.FAILED,
                attempt.diagnostic or "solver returned no normalized result",
            )
            return M12SolveOutcome(prepared.identity, False, None, diagnostic=diagnostic)

        publication = self._project.m12_persistence().publish_result(
            prepared.identity,
            attempt.result.normalized_dict(),
            cancelled=cancelled,
        )
        return M12SolveOutcome(
            prepared.identity,
            publication.reused,
            attempt.result.normalized_dict(),
            publication=publication,
        )

    def _require_current(self, identity: RouteCacheIdentity) -> None:
        authority = self._current_authority()
        document_authority = identity.document.get("authority")
        if not isinstance(document_authority, Mapping):
            raise ValueError("route cache identity authority is invalid")
        if storage.canonical_json(dict(document_authority)) != storage.canonical_json(
            {"m10": authority.m10_provenance, "m11": authority.m11_provenance}
        ):
            raise ValueError("route request is stale for the current M10/M11 authority")


def load_m12_authority(project: Project) -> M12Authority:
    """Load one exact current M10 graph and its complete bound M11 model."""

    raw_state = project.payload("m10_analysis_state", "authoritative")
    if not isinstance(raw_state, Mapping):
        raise ValueError("M12 requires current M10 authority")
    graph = _compact_canonical_graph(project, raw_state)
    if (
        raw_state.get("canonical_availability") != "current_complete"
        or raw_state.get("source_generation") != graph.source_generation
        or raw_state.get("canonical_generation") != graph.source_generation
        or raw_state.get("canonical_hash") != graph.authority_hash
    ):
        raise ValueError("M12 requires a current complete M10 canonical graph")
    selection = project.m11_persistence().select_current(
        source_generation=graph.source_generation,
        canonical_schema=CANONICAL_GRAPH_SCHEMA,
        canonical_hash=graph.authority_hash,
    )
    if (
        selection.availability is not M11Availability.CURRENT_COMPLETE
        or selection.phase_results is None
    ):
        raise ValueError(f"M12 requires current complete M11 authority: {selection.reason}")
    model = scene_model_from_stored_results(selection.phase_results)
    if model.binding.canonical_hash != graph.authority_hash:
        raise ValueError("M11 scene model is not bound to the current M10 graph")
    assert selection.model_hash is not None
    return M12Authority(graph, model, selection.model_hash)


def _authority_is_current(project: Project, authority: M12Authority) -> bool:
    """Check compact authority pointers without decoding either large read model."""

    raw_state = project.payload("m10_analysis_state", "authoritative")
    if not isinstance(raw_state, Mapping):
        return False
    if (
        raw_state.get("canonical_availability") != "current_complete"
        or raw_state.get("source_generation") != authority.graph.source_generation
        or raw_state.get("canonical_generation") != authority.graph.source_generation
        or raw_state.get("canonical_hash") != authority.graph.authority_hash
    ):
        return False
    row = project._require_open().execute(
        "SELECT payload_hash FROM payloads WHERE collection=? AND record_key=?",
        ("m10_canonical_graph", "authoritative"),
    ).fetchone()
    if row is None or str(row[0]) != authority.graph.authority_hash:
        return False
    persistence = project.m11_persistence()
    state = persistence.analysis_state()
    published = state.get("published") if isinstance(state, Mapping) else None
    if (
        not isinstance(published, Mapping)
        or published.get("binding_hash") != authority.m11_publication_hash
    ):
        return False
    return persistence.has_current_publication(
        source_generation=authority.graph.source_generation,
        canonical_schema=CANONICAL_GRAPH_SCHEMA,
        canonical_hash=authority.graph.authority_hash,
    )


def _compact_canonical_graph(
    project: Project, raw_state: Mapping[str, object]
) -> CanonicalGraph:
    """Stream only solver-relevant M10 fields from the verified canonical payload."""

    connection = project._require_open()
    row = connection.execute(
        "SELECT payload_hash, "
        "json_extract(payload_json, '$.source_generation'), "
        "json_extract(payload_json, '$.schema'), "
        "json_extract(payload_json, '$.schema_version'), "
        "json_extract(payload_json, '$.origin_generations') "
        "FROM payloads WHERE collection=? AND record_key=?",
        ("m10_canonical_graph", "authoritative"),
    ).fetchone()
    if row is None:
        raise ValueError("M12 requires current M10 authority")
    canonical_hash = raw_state.get("canonical_hash")
    if (
        not isinstance(canonical_hash, str)
        or str(row[0]) != canonical_hash
        or row[1] != raw_state.get("source_generation")
        or row[2] != CANONICAL_GRAPH_SCHEMA
        or row[3] != CANONICAL_GRAPH_SCHEMA_VERSION
    ):
        raise ValueError("M12 requires a current complete M10 canonical graph")
    origin_generations_value = json.loads(str(row[4]))
    if not isinstance(origin_generations_value, Mapping):
        raise storage.ProjectCorruptError("M10 canonical origins are invalid")
    origin_generations = {
        str(key): str(value) for key, value in origin_generations_value.items()
    }

    nodes = tuple(_compact_node(item) for item in _canonical_records(connection, "nodes"))
    edges = tuple(_compact_edge(item) for item in _canonical_records(connection, "edges"))
    facts = tuple(_fact(item) for item in _canonical_records(connection, "facts"))
    evidence = tuple(_evidence(item) for item in _canonical_records(connection, "evidence"))
    proofs = tuple(
        _compact_proof(item) for item in _canonical_records(connection, "proofs")
    )
    graph = CanonicalGraph(
        str(row[1]),
        origin_generations,
        nodes,
        edges,
        (),
        facts,
        evidence,
        proofs,
        authority_hash_override=canonical_hash,
    )
    graph.validate()
    return graph


def _canonical_records(
    connection: sqlite3.Connection, field: str
) -> Iterator[Mapping[str, object]]:
    if field not in {"nodes", "edges", "facts", "evidence", "proofs"}:
        raise ValueError("unsupported compact canonical field")
    cursor = connection.execute(
        "SELECT json_each.value FROM payloads, "
        "json_each(payloads.payload_json, ?) "
        "WHERE payloads.collection=? AND payloads.record_key=? "
        "ORDER BY json_each.key",
        (f"$.{field}", "m10_canonical_graph", "authoritative"),
    )
    for row in cursor:
        value = json.loads(str(row[0]))
        if not isinstance(value, Mapping):
            raise storage.ProjectCorruptError(f"M10 canonical {field} record is invalid")
        yield value


def _compact_node(value: Mapping[str, object]) -> CanonicalNode:
    attributes = _mapping(value.get("attributes"), "node.attributes")
    compact_attributes = {
        key: attributes[key]
        for key in ("fact_ids", "reachability_witness", "resolved_static_reachable")
        if key in attributes
    }
    return CanonicalNode(
        _text(value, "id"),
        CanonicalNodeKind(_text(value, "kind")),
        _text(value, "graph_node_id"),
        _string(value.get("label"), "node.label"),
        ReachabilityStatus(_text(value, "reachability")),
        _strings(value.get("evidence_ids"), "node.evidence_ids"),
        _strings(value.get("proof_ids"), "node.proof_ids"),
        (),
        compact_attributes,
    )


def _compact_edge(value: Mapping[str, object]) -> CanonicalEdge:
    resolved = value.get("resolved")
    if not isinstance(resolved, bool):
        raise ValueError("edge.resolved must be boolean")
    attributes = _mapping(value.get("attributes"), "edge.attributes")
    compact_attributes = {
        key: attributes[key]
        for key in ("gate_ids", "effect_ids", "predicate", "call_site_id")
        if key in attributes
    }
    return CanonicalEdge(
        _text(value, "id"),
        _text(value, "source_id"),
        _text(value, "target_id"),
        _text(value, "kind"),
        ReachabilityStatus(_text(value, "reachability")),
        resolved,
        _strings(value.get("evidence_ids"), "edge.evidence_ids"),
        _strings(value.get("proof_ids"), "edge.proof_ids"),
        (),
        compact_attributes,
    )


def _compact_proof(value: Mapping[str, object]) -> DerivedProof:
    """Retain only proof identity and kind needed by M12 authority checks."""

    return DerivedProof(
        _text(value, "id"),
        _text(value, "kind"),
        (),
        (),
        "",
    )


def canonical_graph_from_mapping(value: Mapping[str, object]) -> CanonicalGraph:
    """Rehydrate the exact inert M10 graph without reading or executing source code."""

    graph = CanonicalGraph(
        _text(value, "source_generation"),
        _string_mapping(value.get("origin_generations"), "origin_generations"),
        tuple(_node(item) for item in _records(value.get("nodes"), "nodes")),
        tuple(_edge(item) for item in _records(value.get("edges"), "edges")),
        tuple(_region(item) for item in _records(value.get("regions"), "regions")),
        tuple(_fact(item) for item in _records(value.get("facts"), "facts")),
        tuple(_evidence(item) for item in _records(value.get("evidence"), "evidence")),
        tuple(_proof(item) for item in _records(value.get("proofs"), "proofs")),
    )
    graph.validate()
    if graph.normalized_bytes() != storage.canonical_json(dict(value)):
        raise storage.ProjectCorruptError("M10 canonical mapping does not round-trip exactly")
    return graph


def _destination_records(authority: M12Authority) -> tuple[M12DestinationRecord, ...]:
    graph = authority.graph
    model = authority.scene_model
    atoms = {item.id: item for item in model.atoms}
    scenes = {item.id: item for item in model.scenes}
    result: list[M12DestinationRecord] = []
    for scene in model.scenes:
        if not any(atoms[item].story_facing for item in scene.atom_ids):
            continue
        result.append(
            M12DestinationRecord(
                DestinationKind.GENERIC_SCENE,
                scene.id,
                scene.title,
                "Scene in any supported context",
                scene.provenance.to_dict(),
            )
        )
        if scene.repeatability.value == "repeatable":
            result.append(
                M12DestinationRecord(
                    DestinationKind.REPEATABLE_EVENT,
                    scene.id,
                    scene.title,
                    "Repeatable event reached at least once",
                    scene.provenance.to_dict(),
                )
            )
    for occurrence in model.occurrences:
        if occurrence.kind.value != "narrative":
            continue
        scene = scenes[occurrence.scene_id]
        result.append(
            M12DestinationRecord(
                DestinationKind.EXACT_OCCURRENCE,
                occurrence.id,
                scene.title,
                "Exact call-site occurrence",
                occurrence.provenance.to_dict(),
            )
        )
    for branch in model.temporary_branches:
        parent = scenes[branch.parent_scene_id]
        for arm in branch.arms:
            if not any(atoms[item].story_facing for item in arm.atom_ids):
                continue
            result.append(
                M12DestinationRecord(
                    DestinationKind.TEMPORARY_OUTCOME,
                    arm.id,
                    parent.title,
                    f"Temporary outcome {arm.ordinal + 1}",
                    branch.provenance.to_dict(),
                )
            )
    for lane in model.lanes:
        if lane.kind is LaneKind.SPINE or not lane.scene_ids:
            continue
        first_scene = scenes[lane.scene_ids[0]]
        result.append(
            M12DestinationRecord(
                DestinationKind.PERSISTENT_LANE,
                lane.id,
                first_scene.title,
                "Persistent route commitment",
                lane.provenance.to_dict(),
            )
        )
    for node in graph.nodes:
        if node.kind is not CanonicalNodeKind.TERMINAL:
            continue
        result.append(
            M12DestinationRecord(
                DestinationKind.TERMINAL,
                node.id,
                node.label or "Ending",
                "M10 terminal or statically identified ending",
                {
                    "node_ids": [node.id],
                    "evidence_ids": list(node.evidence_ids),
                    "proof_ids": list(node.proof_ids),
                },
            )
        )
    # These records are emitted only from validated M10/M11 authority types. Exact
    # target anchoring is still revalidated on the one selected solve; doing that
    # graph-wide for every catalog row would turn destination browsing into eager
    # all-target preprocessing.
    return tuple(result)


def _origin(value: Mapping[str, object]) -> OriginReference:
    subpath = value.get("subpath")
    return OriginReference(
        _text(value, "collection"),
        _text(value, "record_id"),
        subpath if isinstance(subpath, str) else None,
    )


def _origins(value: object) -> tuple[OriginReference, ...]:
    return tuple(_origin(item) for item in _records(value, "origins"))


def _node(value: Mapping[str, object]) -> CanonicalNode:
    return CanonicalNode(
        _text(value, "id"),
        CanonicalNodeKind(_text(value, "kind")),
        _text(value, "graph_node_id"),
        _string(value.get("label"), "node.label"),
        ReachabilityStatus(_text(value, "reachability")),
        _strings(value.get("evidence_ids"), "node.evidence_ids"),
        _strings(value.get("proof_ids"), "node.proof_ids"),
        _origins(value.get("origins")),
        _mapping(value.get("attributes"), "node.attributes"),
    )


def _edge(value: Mapping[str, object]) -> CanonicalEdge:
    resolved = value.get("resolved")
    if not isinstance(resolved, bool):
        raise ValueError("edge.resolved must be boolean")
    return CanonicalEdge(
        _text(value, "id"),
        _text(value, "source_id"),
        _text(value, "target_id"),
        _text(value, "kind"),
        ReachabilityStatus(_text(value, "reachability")),
        resolved,
        _strings(value.get("evidence_ids"), "edge.evidence_ids"),
        _strings(value.get("proof_ids"), "edge.proof_ids"),
        _origins(value.get("origins")),
        _mapping(value.get("attributes"), "edge.attributes"),
    )


def _region(value: Mapping[str, object]) -> CanonicalRegion:
    merge = value.get("merge_node_id")
    return CanonicalRegion(
        _text(value, "id"),
        _text(value, "kind"),
        _text(value, "split_node_id"),
        merge if isinstance(merge, str) else None,
        _strings(value.get("member_node_ids"), "region.member_node_ids"),
        _origins(value.get("origins")),
        _strings(value.get("proof_ids"), "region.proof_ids"),
        _mapping(value.get("attributes"), "region.attributes"),
    )


def _fact(value: Mapping[str, object]) -> CanonicalFact:
    return CanonicalFact(
        _text(value, "id"),
        _text(value, "kind"),
        _text(value, "status"),
        _strings(value.get("evidence_ids"), "fact.evidence_ids"),
        _origins(value.get("origins")),
        _mapping(value.get("attributes"), "fact.attributes"),
    )


def _evidence(value: Mapping[str, object]) -> SourceEvidence:
    line_basis = value.get("line_basis")
    return SourceEvidence(
        _text(value, "id"),
        _mapping(value.get("source"), "evidence.source"),
        _string(value.get("source_text"), "evidence.source_text"),
        _origins(value.get("origins")),
        line_basis if isinstance(line_basis, str) else None,
    )


def _proof(value: Mapping[str, object]) -> DerivedProof:
    return DerivedProof(
        _text(value, "id"),
        _text(value, "kind"),
        _origins(value.get("origins")),
        _strings(value.get("input_ids"), "proof.input_ids"),
        _string(value.get("explanation"), "proof.explanation"),
    )


def _records(value: object, name: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError(f"{name} must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{name} must contain objects")
    return tuple(item for item in value if isinstance(item, Mapping))


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be an object")
    return {str(key): item for key, item in value.items()}


def _string_mapping(value: object, name: str) -> dict[str, str]:
    mapping = _mapping(value, name)
    if not all(isinstance(item, str) for item in mapping.values()):
        raise ValueError(f"{name} must contain strings")
    return {key: item for key, item in mapping.items() if isinstance(item, str)}


def _strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError(f"{name} must be a string sequence")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must contain strings")
    return tuple(item for item in value if isinstance(item, str))


def _text(value: Mapping[str, object], key: str) -> str:
    return _string(value.get(key), key, non_empty=True)


def _string(value: object, name: str, *, non_empty: bool = False) -> str:
    if not isinstance(value, str) or (non_empty and not value):
        raise ValueError(f"{name} must be a string")
    return value
