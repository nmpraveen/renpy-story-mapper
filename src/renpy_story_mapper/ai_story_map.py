"""Deterministic, product-neutral AI Story Map quotient projection.

The public projection has exactly two levels: a bounded broad map and directly
addressable Detail/Evidence.  AI organization supplies labels and membership;
the authoritative M07 route map remains the sole source of topology and facts.
"""

from __future__ import annotations

import copy
import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from renpy_story_mapper.m07_model import Assembly, CheckpointStatus
from renpy_story_mapper.storage import canonical_json

AI_STORY_MAP_SCHEMA_VERSION = 1
DEFAULT_STORY_NODE_LIMIT = 30
MAX_STORY_NODE_LIMIT = 30
MAX_STORY_EDGE_LIMIT = 180
MAX_DETAIL_EVIDENCE_LIMIT = 60
MAX_BROAD_ID_PREVIEW = 60


class AIStoryMapStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class AIStoryMapUnavailableReason(StrEnum):
    NO_APPLIED_ORGANIZATION = "no_applied_organization"
    STALE_AUTHORITY = "stale_authority"
    INVALID_APPLIED_ORGANIZATION = "invalid_applied_organization"


class AIStorySourceKind(StrEnum):
    AI = "ai"
    TECHNICAL_FALLBACK = "technical_fallback"


class AIStoryPresentationRole(StrEnum):
    EVENT = "event"
    DETOUR_ANNOTATION = "detour_annotation"
    PERSISTENT_ROUTE = "persistent_route"
    ENDING = "ending"
    LOOP = "loop"
    TRANSITION = "transition"


@dataclass(frozen=True)
class AIStoryClaim:
    text: str
    evidence_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"text": self.text, "evidence_ids": list(self.evidence_ids)}


@dataclass(frozen=True)
class AIStoryNode:
    id: str
    title: str
    summary: str
    characters: tuple[str, ...]
    importance: str
    outcomes: tuple[str, ...]
    claims: tuple[AIStoryClaim, ...]
    fact_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    member_route_node_ids: tuple[str, ...]
    internal_route_edge_ids: tuple[str, ...]
    scope_ids: tuple[str, ...]
    window_ids: tuple[str, ...]
    source_kind: AIStorySourceKind
    presentation_role: AIStoryPresentationRole
    route_node_kinds: tuple[str, ...]
    lane_roles: tuple[str, ...]
    entry_route_node_ids: tuple[str, ...]
    exit_route_node_ids: tuple[str, ...]
    terminal: bool
    order: int
    pinned: bool = False
    correction: Mapping[str, object] = field(default_factory=dict)
    source_group_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        member_nodes = _bounded_ids(self.member_route_node_ids)
        internal_edges = _bounded_ids(self.internal_route_edge_ids)
        evidence = _bounded_ids(self.evidence_ids)
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "characters": list(self.characters),
            "importance": self.importance,
            "outcomes": list(self.outcomes),
            "claims": [item.to_dict() for item in self.claims],
            "fact_ids": list(self.fact_ids),
            "evidence_ids": list(evidence),
            "evidence_count": len(self.evidence_ids),
            "member_route_node_ids": list(member_nodes),
            "member_route_node_count": len(self.member_route_node_ids),
            "internal_route_edge_ids": list(internal_edges),
            "internal_route_edge_count": len(self.internal_route_edge_ids),
            "scope_ids": list(self.scope_ids),
            "window_ids": list(self.window_ids),
            "source_kind": self.source_kind.value,
            "ai_interpreted": self.source_kind is AIStorySourceKind.AI,
            "presentation_role": self.presentation_role.value,
            "route_node_kinds": list(self.route_node_kinds),
            "lane_roles": list(self.lane_roles),
            "entry_route_node_ids": list(_bounded_ids(self.entry_route_node_ids)),
            "entry_route_node_count": len(self.entry_route_node_ids),
            "exit_route_node_ids": list(_bounded_ids(self.exit_route_node_ids)),
            "exit_route_node_count": len(self.exit_route_node_ids),
            "terminal": self.terminal,
            "ending": self.terminal,
            "order": self.order,
            "pinned": self.pinned,
            "correction": dict(self.correction),
            "source_group_ids": list(self.source_group_ids),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AIStoryEdge:
    id: str
    source_id: str
    target_id: str
    presentation_role: AIStoryPresentationRole
    order: int
    terminal: bool
    lane_roles: tuple[str, ...]
    entry_route_node_ids: tuple[str, ...]
    exit_route_node_ids: tuple[str, ...]
    member_route_edge_ids: tuple[str, ...]
    control_edge_ids: tuple[str, ...]
    control_node_ids: tuple[str, ...]
    route_roles: tuple[str, ...]
    lane_ids: tuple[str, ...]
    gate_ids: tuple[str, ...]
    effect_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    continuation: bool
    continuation_route_edge_ids: tuple[str, ...]
    proven_merge: bool
    proven_merge_route_edge_ids: tuple[str, ...]
    technical_hops: int

    def to_dict(self) -> dict[str, object]:
        route_edges = _bounded_ids(self.member_route_edge_ids)
        evidence = _bounded_ids(self.evidence_ids)
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "presentation_role": self.presentation_role.value,
            "order": self.order,
            "terminal": self.terminal,
            "ending": self.terminal,
            "lane_roles": list(self.lane_roles),
            "entry_route_node_ids": list(_bounded_ids(self.entry_route_node_ids)),
            "entry_route_node_count": len(self.entry_route_node_ids),
            "exit_route_node_ids": list(_bounded_ids(self.exit_route_node_ids)),
            "exit_route_node_count": len(self.exit_route_node_ids),
            "member_route_edge_ids": list(route_edges),
            "member_route_edge_count": len(self.member_route_edge_ids),
            "control_edge_ids": list(self.control_edge_ids),
            "control_node_ids": list(self.control_node_ids),
            "route_roles": list(self.route_roles),
            "gate_ids": list(self.gate_ids),
            "effect_ids": list(self.effect_ids),
            "evidence_ids": list(evidence),
            "evidence_count": len(self.evidence_ids),
            "continuation": self.continuation,
            "continuation_route_edge_ids": list(_bounded_ids(self.continuation_route_edge_ids)),
            "proven_merge": self.proven_merge,
            "proven_merge_route_edge_ids": list(_bounded_ids(self.proven_merge_route_edge_ids)),
            "technical_hops": self.technical_hops,
        }


@dataclass(frozen=True)
class AIStoryCoverage:
    authoritative_route_nodes: int
    authoritative_route_edges: int
    projected_nodes: int
    projected_edges: int
    ai_owned_route_nodes: int
    technical_fallback_route_nodes: int
    internal_route_edges: int
    coalesced_route_edges: int

    def to_dict(self) -> dict[str, object]:
        total = self.authoritative_route_nodes
        return {
            "authoritative_route_nodes": total,
            "authoritative_route_edges": self.authoritative_route_edges,
            "projected_nodes": self.projected_nodes,
            "projected_edges": self.projected_edges,
            "ai_owned_route_nodes": self.ai_owned_route_nodes,
            "technical_fallback_route_nodes": self.technical_fallback_route_nodes,
            "internal_route_edges": self.internal_route_edges,
            "coalesced_route_edges": self.coalesced_route_edges,
            "ai_route_node_ratio": 1.0 if total == 0 else self.ai_owned_route_nodes / total,
        }


@dataclass(frozen=True)
class AIStoryMap:
    authority_hash: str
    organization_hash: str
    assembly_id: str
    nodes: tuple[AIStoryNode, ...]
    edges: tuple[AIStoryEdge, ...]
    coverage: AIStoryCoverage
    _route_nodes: Mapping[str, Mapping[str, object]] = field(repr=False, compare=False)
    _route_edges: Mapping[str, Mapping[str, object]] = field(repr=False, compare=False)
    _evidence: Mapping[str, Mapping[str, object]] = field(repr=False, compare=False)
    _facts: Mapping[str, Mapping[str, object]] = field(repr=False, compare=False)

    @property
    def projection_hash(self) -> str:
        return hashlib.sha256(canonical_json(self._canonical_projection())).hexdigest()

    def _canonical_projection(self) -> dict[str, object]:
        return {
            "schema_version": AI_STORY_MAP_SCHEMA_VERSION,
            "algorithm": "deterministic_quotient_v1",
            "authority_hash": self.authority_hash,
            "organization_hash": self.organization_hash,
            "assembly_id": self.assembly_id,
        }

    def to_dict(self) -> dict[str, object]:
        """Return the stable, bounded initial broad-map page."""

        return self.page()

    def page(
        self,
        *,
        node_offset: int = 0,
        node_limit: int = DEFAULT_STORY_NODE_LIMIT,
        edge_offset: int = 0,
        edge_limit: int = MAX_STORY_EDGE_LIMIT,
    ) -> dict[str, object]:
        if node_offset < 0 or edge_offset < 0:
            raise ValueError("page offsets cannot be negative")
        if not 1 <= node_limit <= MAX_STORY_NODE_LIMIT:
            raise ValueError("node_limit must be between 1 and 30")
        if not 1 <= edge_limit <= MAX_STORY_EDGE_LIMIT:
            raise ValueError("edge_limit must be between 1 and 180")
        nodes = self.nodes[node_offset : node_offset + node_limit]
        edges = self.edges[edge_offset : edge_offset + edge_limit]
        next_node = node_offset + len(nodes)
        next_edge = edge_offset + len(edges)
        return {
            "schema_version": AI_STORY_MAP_SCHEMA_VERSION,
            "status": AIStoryMapStatus.AVAILABLE.value,
            "presentation_levels": ["ai_story_map", "detail_evidence"],
            "level": "ai_story_map",
            "authority_hash": self.authority_hash,
            "organization_hash": self.organization_hash,
            "projection_hash": self.projection_hash,
            "assembly_id": self.assembly_id,
            "nodes": [item.to_dict() for item in nodes],
            "edges": [item.to_dict() for item in edges],
            "coverage": self.coverage.to_dict(),
            "page": {
                "node_offset": node_offset,
                "node_limit": node_limit,
                "next_node_offset": next_node if next_node < len(self.nodes) else None,
                "edge_offset": edge_offset,
                "edge_limit": edge_limit,
                "next_edge_offset": next_edge if next_edge < len(self.edges) else None,
                "total_nodes": len(self.nodes),
                "total_edges": len(self.edges),
            },
        }

    def detail(
        self,
        element_id: str,
        *,
        route_node_offset: int = 0,
        route_node_limit: int = MAX_STORY_NODE_LIMIT,
        route_edge_offset: int = 0,
        route_edge_limit: int = MAX_STORY_EDGE_LIMIT,
        evidence_offset: int = 0,
        evidence_limit: int = MAX_DETAIL_EVIDENCE_LIMIT,
    ) -> dict[str, object]:
        """Resolve one projected element to exact technical authority and evidence."""

        if min(route_node_offset, route_edge_offset, evidence_offset) < 0:
            raise ValueError("detail offsets cannot be negative")
        if not 1 <= route_node_limit <= MAX_STORY_NODE_LIMIT:
            raise ValueError("route_node_limit must be between 1 and 30")
        if not 1 <= route_edge_limit <= MAX_STORY_EDGE_LIMIT:
            raise ValueError("route_edge_limit must be between 1 and 180")
        if not 1 <= evidence_limit <= MAX_DETAIL_EVIDENCE_LIMIT:
            raise ValueError("evidence_limit must be between 1 and 60")
        node = next((item for item in self.nodes if item.id == element_id), None)
        edge = next((item for item in self.edges if item.id == element_id), None)
        if node is None and edge is None:
            raise KeyError(f"unknown AI Story Map element: {element_id}")
        if node is not None:
            route_node_ids = node.member_route_node_ids
            route_edge_ids = node.internal_route_edge_ids
            evidence_ids = node.evidence_ids
            fact_ids = node.fact_ids
            claims = [item.to_dict() for item in node.claims]
            element = node.to_dict()
        else:
            assert edge is not None
            route_edge_ids = edge.member_route_edge_ids
            route_node_ids = tuple(
                sorted(
                    {
                        _required_text(self._route_edges[route_edge_id], endpoint)
                        for route_edge_id in route_edge_ids
                        for endpoint in ("source_id", "target_id")
                    },
                    key=lambda item: _route_order(self._route_nodes[item]),
                )
            )
            evidence_ids = edge.evidence_ids
            fact_ids = (*edge.gate_ids, *edge.effect_ids)
            claims = []
            element = edge.to_dict()
        unique_evidence = tuple(dict.fromkeys(evidence_ids))
        page_ids = unique_evidence[evidence_offset : evidence_offset + evidence_limit]
        next_evidence = evidence_offset + len(page_ids)
        route_node_page = route_node_ids[route_node_offset : route_node_offset + route_node_limit]
        route_edge_page = route_edge_ids[route_edge_offset : route_edge_offset + route_edge_limit]
        next_node = route_node_offset + len(route_node_page)
        next_edge = route_edge_offset + len(route_edge_page)
        return {
            "schema_version": AI_STORY_MAP_SCHEMA_VERSION,
            "level": "detail_evidence",
            "back_target": "ai_story_map",
            "authority_hash": self.authority_hash,
            "organization_hash": self.organization_hash,
            "projection_hash": self.projection_hash,
            "element": element,
            "member_route_node_ids": list(route_node_page),
            "member_route_nodes": [
                dict(self._route_nodes[item])
                for item in route_node_page
                if item in self._route_nodes
            ],
            "member_route_edge_ids": list(route_edge_page),
            "member_route_edges": [
                dict(self._route_edges[item])
                for item in route_edge_page
                if item in self._route_edges
            ],
            "technical_page": {
                "route_node_offset": route_node_offset,
                "route_node_limit": route_node_limit,
                "next_route_node_offset": (next_node if next_node < len(route_node_ids) else None),
                "total_route_nodes": len(route_node_ids),
                "route_edge_offset": route_edge_offset,
                "route_edge_limit": route_edge_limit,
                "next_route_edge_offset": (next_edge if next_edge < len(route_edge_ids) else None),
                "total_route_edges": len(route_edge_ids),
            },
            "claims": claims,
            "fact_ids": list(dict.fromkeys(fact_ids)),
            "facts": [
                dict(self._facts[item]) for item in dict.fromkeys(fact_ids) if item in self._facts
            ],
            "evidence_ids": list(unique_evidence),
            "evidence": [dict(self._evidence[item]) for item in page_ids if item in self._evidence],
            "evidence_page": {
                "offset": evidence_offset,
                "limit": evidence_limit,
                "next_offset": next_evidence if next_evidence < len(unique_evidence) else None,
                "total": len(unique_evidence),
            },
        }


@dataclass(frozen=True)
class AIStoryMapQueryResult:
    status: AIStoryMapStatus
    authority_hash: str
    story_map: AIStoryMap | None
    reason: AIStoryMapUnavailableReason | None = None
    organization_hash: str | None = None

    def to_dict(self) -> dict[str, object]:
        if self.story_map is not None:
            return self.story_map.to_dict()
        return {
            "schema_version": AI_STORY_MAP_SCHEMA_VERSION,
            "status": self.status.value,
            "presentation_levels": ["ai_story_map", "detail_evidence"],
            "level": "ai_story_map",
            "authority_hash": self.authority_hash,
            "organization_hash": self.organization_hash,
            "reason": None if self.reason is None else self.reason.value,
            "map": None,
            "technical_fallback": {
                "available": True,
                "level": "route_map",
                "authority_hash": self.authority_hash,
                "ai_interpreted": False,
            },
        }


def query_ai_story_map(
    route: Mapping[str, object],
    assembly: Assembly | Mapping[str, object] | None,
    *,
    facts: Mapping[str, Mapping[str, object]] | None = None,
) -> AIStoryMapQueryResult:
    """Return an AI map only for a valid applied organization on exact authority."""

    authority_hash = hashlib.sha256(canonical_json(route)).hexdigest()
    if assembly is None:
        return AIStoryMapQueryResult(
            AIStoryMapStatus.UNAVAILABLE,
            authority_hash,
            None,
            AIStoryMapUnavailableReason.NO_APPLIED_ORGANIZATION,
        )
    try:
        record = _assembly_record(assembly)
    except (TypeError, ValueError):
        return AIStoryMapQueryResult(
            AIStoryMapStatus.UNAVAILABLE,
            authority_hash,
            None,
            AIStoryMapUnavailableReason.INVALID_APPLIED_ORGANIZATION,
        )
    organization_hash = record.payload_hash
    if record.generation != authority_hash:
        return AIStoryMapQueryResult(
            AIStoryMapStatus.UNAVAILABLE,
            authority_hash,
            None,
            AIStoryMapUnavailableReason.STALE_AUTHORITY,
            organization_hash,
        )
    if record.status != "applied":
        return AIStoryMapQueryResult(
            AIStoryMapStatus.UNAVAILABLE,
            authority_hash,
            None,
            AIStoryMapUnavailableReason.NO_APPLIED_ORGANIZATION,
            organization_hash,
        )
    try:
        story_map = project_ai_story_map(route, assembly, facts=facts)
    except (KeyError, TypeError, ValueError):
        return AIStoryMapQueryResult(
            AIStoryMapStatus.UNAVAILABLE,
            authority_hash,
            None,
            AIStoryMapUnavailableReason.INVALID_APPLIED_ORGANIZATION,
            organization_hash,
        )
    return AIStoryMapQueryResult(
        AIStoryMapStatus.AVAILABLE,
        authority_hash,
        story_map,
        organization_hash=organization_hash,
    )


def project_ai_story_map(
    route: Mapping[str, object],
    assembly: Assembly | Mapping[str, object],
    *,
    facts: Mapping[str, Mapping[str, object]] | None = None,
) -> AIStoryMap:
    """Build the complete deterministic quotient; use :func:`query_ai_story_map` at boundaries."""

    authority_hash = hashlib.sha256(canonical_json(route)).hexdigest()
    record = _assembly_record(assembly)
    if record.status != "applied":
        raise ValueError("AI Story Map requires an applied organization")
    if record.generation != authority_hash:
        raise ValueError("applied organization does not match current authority")
    payload = record.payload
    if hashlib.sha256(canonical_json(payload)).hexdigest() != record.payload_hash:
        raise ValueError("applied organization hash does not match its payload")
    if payload.get("generation") != authority_hash:
        raise ValueError("applied organization payload has a stale generation")

    route_nodes = _indexed_records(route.get("nodes"), "route.nodes")
    route_edges = _indexed_records(route.get("edges"), "route.edges")
    evidence = _indexed_records(route.get("evidence", []), "route.evidence")
    scopes = _indexed_records(route.get("scopes"), "route.scopes")
    referenced_evidence_ids = {
        evidence_id
        for record in (*route_nodes.values(), *route_edges.values())
        for evidence_id in _string_tuple(record.get("evidence_ids"), "route.evidence_ids")
    }
    if referenced_evidence_ids - set(evidence):
        raise ValueError("deterministic route authority has missing evidence records")
    authoritative_fact_ids = {
        fact_id
        for edge in route_edges.values()
        for key in ("gate_ids", "effect_ids")
        for fact_id in _string_tuple(edge.get(key), f"edge.{key}")
    }
    items = _records(payload.get("items"), "organization.items")
    if not items:
        raise ValueError("organization assembly must contain at least one item")
    item_scope_ids = [_required_text(item, "scope_id") for item in items]
    if len(item_scope_ids) != len(set(item_scope_ids)):
        raise ValueError("organization items must have unique scope IDs")
    if any(
        scope_id not in scopes and not _is_bounded_window_id(scope_id)
        for scope_id in item_scope_ids
    ):
        raise ValueError("organization item references an unknown scope")
    owner: dict[str, str] = {}
    mutable_nodes: list[_MutableStoryNode] = []
    bounded_group_intervals: list[tuple[tuple[int, str], tuple[int, str]]] = []

    for item in sorted(items, key=_item_order):
        scope_id = _required_text(item, "scope_id")
        bounded_window = scope_id not in scopes
        scope_members = (
            set(route_nodes)
            if bounded_window
            else set(_string_tuple(scopes[scope_id].get("node_ids"), "scope.node_ids"))
        )
        status = _required_text(item, "status")
        if status not in {item.value for item in CheckpointStatus}:
            raise ValueError("organization item has an unknown checkpoint status")
        correction = _mapping(item.get("correction", {}), "item.correction")
        if set(correction) - {"title", "summary"}:
            raise ValueError("item correction contains unsupported fields")
        pinned = _required_bool(item.get("pinned", False), "item.pinned")
        window_ids = _window_ids(item, scope_id)
        grouped: set[str] = set()
        fallback_members: set[str] = set()
        if status == "validated":
            result = _mapping(item.get("result"), "item.result")
            organization = _mapping(result.get("organization_result"), "organization_result")
            groups, ungrouped, grouped = _organization_membership(
                organization, scope_members, route_nodes
            )
            if bounded_window and not grouped:
                raise ValueError("validated bounded window has no route-node membership")
            if not bounded_window and grouped != scope_members:
                raise ValueError("validated organization does not cover its complete scope")
            for group, members in groups:
                node_id = _stable_id(
                    "ai_story_node", scope_id, _required_text(group, "id"), *members
                )
                _claim_owner(owner, members, node_id)
                if bounded_window:
                    member_orders = [_route_order(route_nodes[member]) for member in members]
                    bounded_group_intervals.append((member_orders[0], member_orders[-1]))
                claims = _claims(group.get("claims"), evidence)
                promoted_facts = _string_tuple(
                    group.get("promoted_fact_ids"), "group.promoted_fact_ids"
                )
                if set(promoted_facts) - authoritative_fact_ids:
                    raise ValueError("group promotes a fact outside deterministic authority")
                title = _corrected_text(correction, "title", group)
                summary = _corrected_text(correction, "summary", group)
                mutable_nodes.append(
                    _MutableStoryNode(
                        id=node_id,
                        title=title,
                        summary=summary,
                        characters=_string_tuple(group.get("characters"), "group.characters"),
                        importance=_required_text(group, "importance"),
                        outcomes=_string_tuple(group.get("outcomes"), "group.outcomes"),
                        claims=claims,
                        fact_ids=promoted_facts,
                        members=members,
                        scope_ids=(
                            _member_scope_ids(members, scopes) if bounded_window else (scope_id,)
                        ),
                        window_ids=window_ids,
                        source_kind=AIStorySourceKind.AI,
                        pinned=pinned,
                        correction=correction,
                        source_group_ids=(_required_text(group, "id"),),
                        warnings=_string_tuple(group.get("warnings"), "group.warnings"),
                    )
                )
            for member in sorted(ungrouped, key=lambda value: _route_order(route_nodes[value])):
                _add_fallback_node(
                    mutable_nodes,
                    owner,
                    member,
                    route_nodes[member],
                    _member_scope_id(member, scopes) if bounded_window else scope_id,
                    window_ids,
                )
        elif bounded_window and status == "fallback":
            result = _mapping(item.get("result"), "item.result")
            organization = _mapping(result.get("organization_result"), "organization_result")
            _, _, grouped = _organization_membership(organization, scope_members, route_nodes)
            if not grouped:
                raise ValueError("fallback bounded window has no route-node membership")
            fallback_members.update(grouped)
        elif not bounded_window:
            fallback_members.update(scope_members)
        uncovered = sorted(
            fallback_members,
            key=lambda value: _route_order(route_nodes[value]),
        )
        for member in uncovered:
            _add_fallback_node(
                mutable_nodes,
                owner,
                member,
                route_nodes[member],
                _member_scope_id(member, scopes) if bounded_window else scope_id,
                window_ids,
            )

    _require_non_crossing_intervals(bounded_group_intervals)

    for member in sorted(route_nodes, key=lambda value: _route_order(route_nodes[value])):
        if member not in owner:
            scope_ids = tuple(
                sorted(
                    scope_id
                    for scope_id, scope in scopes.items()
                    if member in _string_tuple(scope.get("node_ids"), "scope.node_ids")
                )
            )
            _add_fallback_node(
                mutable_nodes,
                owner,
                member,
                route_nodes[member],
                scope_ids[0] if scope_ids else "unscoped",
                scope_ids,
            )
    if set(owner) != set(route_nodes):
        raise ValueError("projection ownership is incomplete")

    internal_by_owner: dict[str, list[str]] = defaultdict(list)
    projected: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    incoming_by_owner: dict[str, set[str]] = defaultdict(set)
    outgoing_by_owner: dict[str, set[str]] = defaultdict(set)
    entries_by_owner: dict[str, set[str]] = defaultdict(set)
    exits_by_owner: dict[str, set[str]] = defaultdict(set)
    for edge_id, edge in route_edges.items():
        source = _required_text(edge, "source_id")
        target = _required_text(edge, "target_id")
        if source not in owner or target not in owner:
            raise ValueError("route edge references a node outside deterministic authority")
        source_owner, target_owner = owner[source], owner[target]
        incoming_by_owner[target_owner].add(target)
        outgoing_by_owner[source_owner].add(source)
        if source_owner == target_owner and source != target:
            internal_by_owner[source_owner].append(edge_id)
        else:
            projected[(source_owner, target_owner)].append(edge)
        if source_owner != target_owner:
            entries_by_owner[target_owner].add(target)
            exits_by_owner[source_owner].add(source)

    for mutable_node in mutable_nodes:
        member_set = set(mutable_node.members)
        entries_by_owner[mutable_node.id].update(member_set - incoming_by_owner[mutable_node.id])
        exits_by_owner[mutable_node.id].update(member_set - outgoing_by_owner[mutable_node.id])

    final_nodes = tuple(
        sorted(
            (
                _finalize_node(
                    item,
                    internal_by_owner[item.id],
                    entries_by_owner[item.id],
                    exits_by_owner[item.id],
                    route_nodes,
                    route_edges,
                )
                for item in mutable_nodes
            ),
            key=lambda item: (item.order, item.id),
        )
    )
    final_edges = tuple(
        sorted(
            (
                _coalesced_edge(source, target, members, route_nodes)
                for (source, target), members in projected.items()
            ),
            key=lambda item: (item.order, item.source_id, item.target_id, item.id),
        )
    )
    ai_owned = sum(
        len(item.member_route_node_ids)
        for item in final_nodes
        if item.source_kind is AIStorySourceKind.AI
    )
    coverage = AIStoryCoverage(
        len(route_nodes),
        len(route_edges),
        len(final_nodes),
        len(final_edges),
        ai_owned,
        len(route_nodes) - ai_owned,
        sum(len(values) for values in internal_by_owner.values()),
        sum(len(item.member_route_edge_ids) - 1 for item in final_edges),
    )
    return AIStoryMap(
        authority_hash,
        record.payload_hash,
        record.assembly_id,
        final_nodes,
        final_edges,
        coverage,
        route_nodes,
        route_edges,
        evidence,
        {} if facts is None else copy.deepcopy(dict(facts)),
    )


@dataclass
class _MutableStoryNode:
    id: str
    title: str
    summary: str
    characters: tuple[str, ...]
    importance: str
    outcomes: tuple[str, ...]
    claims: tuple[AIStoryClaim, ...]
    fact_ids: tuple[str, ...]
    members: tuple[str, ...]
    scope_ids: tuple[str, ...]
    window_ids: tuple[str, ...]
    source_kind: AIStorySourceKind
    pinned: bool
    correction: Mapping[str, object]
    source_group_ids: tuple[str, ...]
    warnings: tuple[str, ...]


def _add_fallback_node(
    nodes: list[_MutableStoryNode],
    owner: dict[str, str],
    member: str,
    route_node: Mapping[str, object],
    scope_id: str,
    window_ids: tuple[str, ...],
) -> None:
    node_id = _stable_id("ai_story_fallback", member)
    _claim_owner(owner, (member,), node_id)
    title = _required_text(route_node, "title")
    nodes.append(
        _MutableStoryNode(
            node_id,
            title,
            title,
            (),
            "technical",
            (),
            (),
            (),
            (member,),
            (scope_id,),
            window_ids,
            AIStorySourceKind.TECHNICAL_FALLBACK,
            False,
            {},
            (),
            (),
        )
    )


def _finalize_node(
    item: _MutableStoryNode,
    internal_edge_ids: Sequence[str],
    entries: set[str],
    exits: set[str],
    route_nodes: Mapping[str, Mapping[str, object]],
    route_edges: Mapping[str, Mapping[str, object]],
) -> AIStoryNode:
    evidence_ids = {
        evidence_id
        for member in item.members
        for evidence_id in _string_tuple(
            route_nodes[member].get("evidence_ids"), "node.evidence_ids"
        )
    }
    fact_ids = set(item.fact_ids)
    for claim in item.claims:
        evidence_ids.update(claim.evidence_ids)
    for edge_id in internal_edge_ids:
        edge = route_edges[edge_id]
        evidence_ids.update(_string_tuple(edge.get("evidence_ids"), "edge.evidence_ids"))
        fact_ids.update(_string_tuple(edge.get("gate_ids"), "edge.gate_ids"))
        fact_ids.update(_string_tuple(edge.get("effect_ids"), "edge.effect_ids"))
    member_nodes = [route_nodes[member] for member in item.members]
    role = _node_presentation_role(member_nodes)
    node_kinds = tuple(sorted({_required_text(node, "kind") for node in member_nodes}))
    lane_roles = tuple(sorted({_required_text(node, "lane_kind") for node in member_nodes}))
    terminal = "terminal" in node_kinds
    return AIStoryNode(
        item.id,
        item.title,
        item.summary,
        item.characters,
        item.importance,
        item.outcomes,
        item.claims,
        tuple(sorted(fact_ids)),
        tuple(sorted(evidence_ids)),
        item.members,
        tuple(sorted(internal_edge_ids)),
        item.scope_ids,
        item.window_ids,
        item.source_kind,
        role,
        node_kinds,
        lane_roles,
        _ordered_route_ids(entries, route_nodes),
        _ordered_route_ids(exits, route_nodes),
        terminal,
        min(_route_order(node)[0] for node in member_nodes),
        item.pinned,
        dict(item.correction),
        item.source_group_ids,
        item.warnings,
    )


def _coalesced_edge(
    source: str,
    target: str,
    members: Sequence[Mapping[str, object]],
    route_nodes: Mapping[str, Mapping[str, object]],
) -> AIStoryEdge:
    ordered = sorted(members, key=lambda item: _required_text(item, "id"))
    route_edge_ids = tuple(_required_text(item, "id") for item in ordered)
    roles = tuple(sorted({_required_text(item, "role") for item in ordered}))
    lanes = tuple(sorted({_required_text(item, "lane_id") for item in ordered}))
    source_nodes = [route_nodes[_required_text(item, "source_id")] for item in ordered]
    target_nodes = [route_nodes[_required_text(item, "target_id")] for item in ordered]
    entry_ids = _ordered_route_ids(
        {_required_text(item, "source_id") for item in ordered}, route_nodes
    )
    exit_ids = _ordered_route_ids(
        {_required_text(item, "target_id") for item in ordered}, route_nodes
    )
    proven_merge = any(
        _required_bool(item.get("proven_merge", False), "edge.proven_merge") for item in ordered
    )
    role = _edge_presentation_role(source, target, source_nodes, target_nodes, proven_merge)
    continuation_roles = {"continuation", "corridor", "fallthrough", "next", "call_return"}
    continuation_edge_ids = tuple(
        _required_text(item, "id")
        for item in ordered
        if _required_text(item, "role") in continuation_roles
    )
    merge_edge_ids = tuple(
        _required_text(item, "id")
        for item in ordered
        if _required_bool(item.get("proven_merge", False), "edge.proven_merge")
    )
    return AIStoryEdge(
        _stable_id("ai_story_edge", source, target, *route_edge_ids),
        source,
        target,
        role,
        min(_route_order(node)[0] for node in source_nodes),
        any(_required_text(node, "kind") == "terminal" for node in target_nodes),
        tuple(
            sorted({_required_text(node, "lane_kind") for node in (*source_nodes, *target_nodes)})
        ),
        entry_ids,
        exit_ids,
        route_edge_ids,
        _union_strings(ordered, "control_edge_ids"),
        _union_strings(ordered, "control_node_ids"),
        roles,
        lanes,
        _union_strings(ordered, "gate_ids"),
        _union_strings(ordered, "effect_ids"),
        _union_strings(ordered, "evidence_ids"),
        bool(continuation_edge_ids),
        continuation_edge_ids,
        proven_merge,
        merge_edge_ids,
        sum(
            _required_int(item.get("technical_hops", 0), "edge.technical_hops") for item in ordered
        ),
    )


def _node_presentation_role(nodes: Sequence[Mapping[str, object]]) -> AIStoryPresentationRole:
    lane_kinds = {_required_text(item, "lane_kind") for item in nodes}
    kinds = {_required_text(item, "kind") for item in nodes}
    if "terminal" in kinds:
        return AIStoryPresentationRole.ENDING
    if "loop" in kinds:
        return AIStoryPresentationRole.LOOP
    if lane_kinds == {"detour"}:
        return AIStoryPresentationRole.DETOUR_ANNOTATION
    if "persistent" in lane_kinds:
        return AIStoryPresentationRole.PERSISTENT_ROUTE
    return AIStoryPresentationRole.EVENT


def _edge_presentation_role(
    source: str,
    target: str,
    sources: Sequence[Mapping[str, object]],
    targets: Sequence[Mapping[str, object]],
    proven_merge: bool,
) -> AIStoryPresentationRole:
    if source == target:
        return AIStoryPresentationRole.LOOP
    target_kinds = {_required_text(item, "kind") for item in targets}
    if "terminal" in target_kinds:
        return AIStoryPresentationRole.ENDING
    lane_kinds = {_required_text(item, "lane_kind") for item in (*sources, *targets)}
    if "detour" in lane_kinds and (proven_merge or "persistent" not in lane_kinds):
        return AIStoryPresentationRole.DETOUR_ANNOTATION
    if "persistent" in lane_kinds:
        return AIStoryPresentationRole.PERSISTENT_ROUTE
    return AIStoryPresentationRole.TRANSITION


@dataclass(frozen=True)
class _AssemblyRecord:
    assembly_id: str
    generation: str
    status: str
    payload: Mapping[str, object]
    payload_hash: str


def _assembly_record(assembly: Assembly | Mapping[str, object]) -> _AssemblyRecord:
    if isinstance(assembly, Assembly):
        return _AssemblyRecord(
            assembly.assembly_id,
            assembly.generation,
            assembly.status,
            assembly.payload,
            assembly.payload_hash,
        )
    return _AssemblyRecord(
        _required_text(assembly, "assembly_id"),
        _required_text(assembly, "generation"),
        _required_text(assembly, "status"),
        _mapping(assembly.get("payload"), "assembly.payload"),
        _required_text(assembly, "payload_hash"),
    )


def _claims(
    value: object, evidence: Mapping[str, Mapping[str, object]]
) -> tuple[AIStoryClaim, ...]:
    result: list[AIStoryClaim] = []
    for claim in _records(value, "group.claims"):
        evidence_ids = _string_tuple(claim.get("evidence_ids"), "claim.evidence_ids")
        if not evidence_ids or set(evidence_ids) - set(evidence):
            raise ValueError("claim evidence is incomplete or outside authority")
        result.append(AIStoryClaim(_required_text(claim, "text"), evidence_ids))
    return tuple(result)


def _is_bounded_window_id(scope_id: str) -> bool:
    prefix = "bounded_window_"
    digest = scope_id.removeprefix(prefix)
    return (
        scope_id.startswith(prefix)
        and len(digest) == 20
        and all(character in "0123456789abcdef" for character in digest)
    )


def _organization_membership(
    organization: Mapping[str, object],
    allowed_members: set[str],
    route_nodes: Mapping[str, Mapping[str, object]],
) -> tuple[
    tuple[tuple[Mapping[str, object], tuple[str, ...]], ...],
    tuple[str, ...],
    set[str],
]:
    groups: list[tuple[Mapping[str, object], tuple[str, ...]]] = []
    group_ids: set[str] = set()
    grouped: set[str] = set()
    prior_group_max: tuple[int, str] | None = None
    for group in _records(organization.get("groups"), "organization.groups"):
        group_id = _required_text(group, "id")
        if group_id in group_ids:
            raise ValueError("organization groups must have unique IDs")
        group_ids.add(group_id)
        members = _string_tuple(group.get("member_ids"), "group.member_ids")
        member_set = set(members)
        if not members or member_set - allowed_members or grouped.intersection(member_set):
            raise ValueError("validated group membership is invalid for its scope")
        member_orders = [_route_order(route_nodes[member]) for member in members]
        if member_orders != sorted(member_orders) or (
            prior_group_max is not None and member_orders[0] <= prior_group_max
        ):
            raise ValueError("organization group membership crosses deterministic order")
        prior_group_max = member_orders[-1]
        grouped.update(member_set)
        groups.append((group, members))
    ungrouped = _string_tuple(organization.get("ungrouped_ids"), "ungrouped_ids")
    if set(ungrouped) - allowed_members or grouped.intersection(ungrouped):
        raise ValueError("ungrouped membership is invalid for its scope")
    covered = grouped.union(ungrouped)
    return tuple(groups), ungrouped, covered


def _member_scope_ids(
    members: Sequence[str], scopes: Mapping[str, Mapping[str, object]]
) -> tuple[str, ...]:
    member_set = set(members)
    result = tuple(
        sorted(
            scope_id
            for scope_id, scope in scopes.items()
            if member_set.intersection(_string_tuple(scope.get("node_ids"), "scope.node_ids"))
        )
    )
    return result or ("unscoped",)


def _member_scope_id(member: str, scopes: Mapping[str, Mapping[str, object]]) -> str:
    return _member_scope_ids((member,), scopes)[0]


def _require_non_crossing_intervals(
    intervals: Sequence[tuple[tuple[int, str], tuple[int, str]]],
) -> None:
    prior_end: tuple[int, str] | None = None
    for start, end in sorted(intervals):
        if prior_end is not None and start <= prior_end:
            raise ValueError("bounded-window groups cross deterministic order")
        prior_end = end


def _window_ids(item: Mapping[str, object], scope_id: str) -> tuple[str, ...]:
    explicit = item.get("window_ids")
    if explicit is not None:
        return _string_tuple(explicit, "item.window_ids")
    window = item.get("window_id")
    return (window,) if isinstance(window, str) and window else (scope_id,)


def _corrected_text(correction: Mapping[str, object], key: str, group: Mapping[str, object]) -> str:
    value = correction.get(key, group.get(key))
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be non-empty text")
    return value


def _claim_owner(owner: dict[str, str], members: Sequence[str], node_id: str) -> None:
    if any(member in owner for member in members):
        raise ValueError("a deterministic route node has multiple projected owners")
    owner.update(dict.fromkeys(members, node_id))


def _union_strings(records: Sequence[Mapping[str, object]], key: str) -> tuple[str, ...]:
    return tuple(
        sorted({value for record in records for value in _string_sequence(record.get(key), key)})
    )


def _bounded_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    return values[:MAX_BROAD_ID_PREVIEW]


def _ordered_route_ids(
    values: set[str], route_nodes: Mapping[str, Mapping[str, object]]
) -> tuple[str, ...]:
    return tuple(sorted(values, key=lambda item: _route_order(route_nodes[item])))


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode()).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _item_order(item: Mapping[str, object]) -> tuple[int, str]:
    return (_required_int(item.get("ordinal"), "item.ordinal"), _required_text(item, "scope_id"))


def _route_order(node: Mapping[str, object]) -> tuple[int, str]:
    return (_required_int(node.get("order"), "node.order"), _required_text(node, "id"))


def _records(value: object, name: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{name} must be an array of objects")
    return cast(list[Mapping[str, object]], value)


def _indexed_records(value: object, name: str) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for item in _records(value, name):
        item_id = _required_text(item, "id")
        if item_id in result:
            raise ValueError(f"{name} contains duplicate IDs")
        result[item_id] = copy.deepcopy(dict(item))
    return result


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return cast(Mapping[str, object], value)


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    result = _string_sequence(value, name)
    if len(result) != len(set(result)):
        raise ValueError(f"{name} contains duplicates")
    return result


def _string_sequence(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be an array of strings")
    return tuple(cast(list[str], value))


def _required_text(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be non-empty text")
    return value


def _required_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _required_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value
