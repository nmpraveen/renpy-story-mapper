"""Versioned structural contract for the M10 canonical derived read model."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from renpy_story_mapper.storage import canonical_json

CANONICAL_GRAPH_SCHEMA_VERSION = 1
CANONICAL_GRAPH_SCHEMA = f"m10-canonical-graph-v{CANONICAL_GRAPH_SCHEMA_VERSION}"


class CanonicalNodeKind(StrEnum):
    LABEL_REGION = "label_region"
    SCRIPT_UNIT = "script_unit"
    CHOICE = "choice"
    CONDITION = "condition"
    MERGE = "merge"
    LOOP = "loop"
    TERMINAL = "terminal"
    UNRESOLVED = "unresolved"


class ReachabilityStatus(StrEnum):
    PROVEN_REACHABLE = "proven_reachable"
    CONDITIONALLY_REACHABLE = "conditionally_reachable"
    REACHABLE_UNDER_INFERRED_REQUIREMENTS = "reachable_under_inferred_requirements"
    UNRESOLVED_DYNAMIC_BEHAVIOR = "unresolved_dynamic_behavior"
    PROVEN_UNREACHABLE = "proven_unreachable"
    POSSIBLY_DEAD = "possibly_dead"
    UNREACHABLE_IN_RESOLVED_STATIC_GRAPH = "unreachable_in_resolved_static_graph"


@dataclass(frozen=True, order=True)
class OriginReference:
    collection: str
    record_id: str
    subpath: str | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "collection": self.collection,
            "record_id": self.record_id,
        }
        if self.subpath is not None:
            value["subpath"] = self.subpath
        return value

    @property
    def identity(self) -> str:
        return f"{self.collection}:{self.record_id}:{self.subpath or ''}"


@dataclass(frozen=True)
class SourceEvidence:
    id: str
    source: Mapping[str, object]
    source_text: str
    origins: tuple[OriginReference, ...]
    line_basis: str | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "id": self.id,
            "source": dict(self.source),
            "source_text": self.source_text,
            "origins": [item.to_dict() for item in sorted(self.origins)],
        }
        if self.line_basis is not None:
            value["line_basis"] = self.line_basis
        return value


@dataclass(frozen=True)
class DerivedProof:
    id: str
    kind: str
    origins: tuple[OriginReference, ...]
    input_ids: tuple[str, ...]
    explanation: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "origins": [item.to_dict() for item in sorted(self.origins)],
            "input_ids": list(self.input_ids),
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class CanonicalNode:
    id: str
    kind: CanonicalNodeKind
    graph_node_id: str
    label: str
    reachability: ReachabilityStatus
    evidence_ids: tuple[str, ...]
    proof_ids: tuple[str, ...]
    origins: tuple[OriginReference, ...]
    attributes: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "graph_node_id": self.graph_node_id,
            "label": self.label,
            "reachability": self.reachability.value,
            "evidence_ids": sorted(self.evidence_ids),
            "proof_ids": sorted(self.proof_ids),
            "origins": [item.to_dict() for item in sorted(self.origins)],
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class CanonicalEdge:
    id: str
    source_id: str
    target_id: str
    kind: str
    reachability: ReachabilityStatus
    resolved: bool
    evidence_ids: tuple[str, ...]
    proof_ids: tuple[str, ...]
    origins: tuple[OriginReference, ...]
    attributes: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "kind": self.kind,
            "reachability": self.reachability.value,
            "resolved": self.resolved,
            "evidence_ids": sorted(self.evidence_ids),
            "proof_ids": sorted(self.proof_ids),
            "origins": [item.to_dict() for item in sorted(self.origins)],
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class CanonicalRegion:
    id: str
    kind: str
    split_node_id: str
    merge_node_id: str | None
    member_node_ids: tuple[str, ...]
    origins: tuple[OriginReference, ...]
    proof_ids: tuple[str, ...]
    attributes: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "id": self.id,
            "kind": self.kind,
            "split_node_id": self.split_node_id,
            "member_node_ids": sorted(self.member_node_ids),
            "origins": [item.to_dict() for item in sorted(self.origins)],
            "proof_ids": sorted(self.proof_ids),
            "attributes": dict(self.attributes),
        }
        if self.merge_node_id is not None:
            value["merge_node_id"] = self.merge_node_id
        return value


@dataclass(frozen=True)
class CanonicalFact:
    id: str
    kind: str
    status: str
    evidence_ids: tuple[str, ...]
    origins: tuple[OriginReference, ...]
    attributes: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "evidence_ids": sorted(self.evidence_ids),
            "origins": [item.to_dict() for item in sorted(self.origins)],
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class CanonicalGraph:
    source_generation: str
    origin_generations: Mapping[str, str]
    nodes: tuple[CanonicalNode, ...]
    edges: tuple[CanonicalEdge, ...]
    regions: tuple[CanonicalRegion, ...]
    facts: tuple[CanonicalFact, ...]
    evidence: tuple[SourceEvidence, ...]
    proofs: tuple[DerivedProof, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": CANONICAL_GRAPH_SCHEMA_VERSION,
            "schema": CANONICAL_GRAPH_SCHEMA,
            "source_generation": self.source_generation,
            "origin_generations": dict(sorted(self.origin_generations.items())),
            "nodes": [item.to_dict() for item in sorted(self.nodes, key=lambda item: item.id)],
            "edges": [item.to_dict() for item in sorted(self.edges, key=lambda item: item.id)],
            "regions": [
                item.to_dict() for item in sorted(self.regions, key=lambda item: item.id)
            ],
            "facts": [item.to_dict() for item in sorted(self.facts, key=lambda item: item.id)],
            "evidence": [
                item.to_dict() for item in sorted(self.evidence, key=lambda item: item.id)
            ],
            "proofs": [item.to_dict() for item in sorted(self.proofs, key=lambda item: item.id)],
        }

    def normalized_bytes(self) -> bytes:
        return canonical_json(self.to_dict())

    @property
    def authority_hash(self) -> str:
        return hashlib.sha256(self.normalized_bytes()).hexdigest()

    def validate(self) -> None:
        _unique((item.id for item in self.nodes), "canonical node")
        _unique((item.id for item in self.edges), "canonical edge")
        _unique((item.id for item in self.regions), "canonical region")
        _unique((item.id for item in self.facts), "canonical fact")
        evidence_ids = _unique((item.id for item in self.evidence), "canonical evidence")
        proof_ids = _unique((item.id for item in self.proofs), "canonical proof")
        node_ids = {item.id for item in self.nodes}
        for node in self.nodes:
            _require_support(node.id, node.evidence_ids, node.proof_ids, evidence_ids, proof_ids)
        for edge in self.edges:
            if edge.source_id not in node_ids or edge.target_id not in node_ids:
                raise ValueError(f"canonical edge {edge.id} has an unknown endpoint")
            _require_support(edge.id, edge.evidence_ids, edge.proof_ids, evidence_ids, proof_ids)
        for region in self.regions:
            referenced = {region.split_node_id, *region.member_node_ids}
            if region.merge_node_id is not None:
                referenced.add(region.merge_node_id)
            if not referenced <= node_ids:
                raise ValueError(f"canonical region {region.id} has an unknown member")
            if not region.proof_ids or not set(region.proof_ids) <= proof_ids:
                raise ValueError(f"canonical region {region.id} lacks a valid derivation proof")
        for fact in self.facts:
            if not fact.evidence_ids or not set(fact.evidence_ids) <= evidence_ids:
                raise ValueError(f"canonical fact {fact.id} lacks direct source evidence")
        generations = set(self.origin_generations.values())
        if generations != {self.source_generation}:
            raise ValueError("canonical origins must all use one source generation")


def stable_canonical_id(prefix: str, *parts: str) -> str:
    identity = [CANONICAL_GRAPH_SCHEMA, prefix, *parts]
    return f"{prefix}_{hashlib.sha256(canonical_json(identity)).hexdigest()[:20]}"


def stable_origin_record_id(kind: str, value: Mapping[str, object]) -> str:
    identity = {key: item for key, item in value.items() if key != "id"}
    return f"{kind}_{hashlib.sha256(canonical_json(identity)).hexdigest()[:20]}"


def source_generation(source_identities: Sequence[tuple[str, str]]) -> str:
    ordered = [
        {"path": path, "content_hash": content_hash}
        for path, content_hash in sorted(source_identities)
    ]
    return hashlib.sha256(canonical_json(ordered)).hexdigest()


def assign_reachability(
    *,
    static_reachable: bool | None,
    unresolved_item: bool = False,
    depends_on_unresolved: bool = False,
    proven_requirement: bool = False,
    inferred_requirement: bool = False,
    unresolved_requirement: bool = False,
    unresolved_transfer_could_reach: bool = False,
    closed_world: bool = False,
) -> ReachabilityStatus:
    if unresolved_item or depends_on_unresolved or unresolved_requirement:
        return ReachabilityStatus.UNRESOLVED_DYNAMIC_BEHAVIOR
    if static_reachable is True:
        if inferred_requirement:
            return ReachabilityStatus.REACHABLE_UNDER_INFERRED_REQUIREMENTS
        if proven_requirement:
            return ReachabilityStatus.CONDITIONALLY_REACHABLE
        return ReachabilityStatus.PROVEN_REACHABLE
    if unresolved_transfer_could_reach:
        return ReachabilityStatus.POSSIBLY_DEAD
    if static_reachable is None or not closed_world:
        return ReachabilityStatus.UNREACHABLE_IN_RESOLVED_STATIC_GRAPH
    return ReachabilityStatus.PROVEN_UNREACHABLE


def _unique(values: Iterable[str], name: str) -> set[str]:
    materialized: list[str] = list(values)
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"{name} ids must be unique")
    return set(materialized)


def _require_support(
    item_id: str,
    evidence: tuple[str, ...],
    proofs: tuple[str, ...],
    evidence_ids: set[str],
    proof_ids: set[str],
) -> None:
    if not evidence and not proofs:
        raise ValueError(f"canonical item {item_id} lacks evidence or derivation")
    if not set(evidence) <= evidence_ids or not set(proofs) <= proof_ids:
        raise ValueError(f"canonical item {item_id} references unknown support")
