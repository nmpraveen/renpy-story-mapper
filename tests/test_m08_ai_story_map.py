"""Focused M08 contracts for deterministic AI Story Map projection."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from renpy_story_mapper.ai_story_map import (
    AIStoryMapStatus,
    AIStoryMapUnavailableReason,
    AIStoryPresentationRole,
    AIStorySourceKind,
    project_ai_story_map,
    query_ai_story_map,
)
from renpy_story_mapper.m07_model import CheckpointStatus
from renpy_story_mapper.project import Project
from renpy_story_mapper.storage import canonical_json


def _node(
    node_id: str,
    order: int,
    *,
    kind: str = "milestone",
    lane: str = "lane_spine",
    lane_kind: str = "spine",
    evidence: Sequence[str] = (),
) -> dict[str, object]:
    return {
        "id": node_id,
        "control_node_id": f"control_{node_id}",
        "kind": kind,
        "title": f"Technical {node_id}",
        "lane_id": lane,
        "lane_kind": lane_kind,
        "order": order,
        "evidence_ids": list(evidence),
        "region_ids": [],
        "terminal_kind": "ending" if kind == "terminal" else None,
        "unresolved": False,
    }


def _edge(
    edge_id: str,
    source: str,
    target: str,
    *,
    role: str = "continuation",
    lane: str = "lane_spine",
    gates: Sequence[str] = (),
    effects: Sequence[str] = (),
    evidence: Sequence[str] = (),
    proven_merge: bool = False,
    technical_hops: int = 0,
) -> dict[str, object]:
    return {
        "id": edge_id,
        "source_id": source,
        "target_id": target,
        "role": role,
        "lane_id": lane,
        "control_edge_ids": [f"control_{edge_id}"],
        "control_node_ids": [f"control_{source}", f"control_{target}"],
        "gate_ids": list(gates),
        "effect_ids": list(effects),
        "evidence_ids": list(evidence),
        "technical_hops": technical_hops,
        "proven_merge": proven_merge,
    }


def _route(
    nodes: Sequence[Mapping[str, object]],
    edges: Sequence[Mapping[str, object]],
    *,
    scopes: Mapping[str, Sequence[str]] | None = None,
    evidence_ids: Sequence[str] = (),
) -> dict[str, object]:
    node_ids = [str(item["id"]) for item in nodes]
    scope_members = {"scope_main": node_ids} if scopes is None else scopes
    return {
        "schema_version": 1,
        "presentation_levels": ["route_map", "detail_evidence"],
        "initial_node_limit": 30,
        "initial_node_ids": node_ids[:30],
        "page_limits": {"nodes": 30, "edges": 180, "items": 240},
        "nodes": [dict(item) for item in nodes],
        "edges": [dict(item) for item in edges],
        "scopes": [
            {
                "id": scope_id,
                "ordinal": ordinal,
                "lane_id": f"lane_{scope_id}",
                "node_ids": list(members),
                "edge_ids": [
                    str(edge["id"])
                    for edge in edges
                    if edge["source_id"] in members or edge["target_id"] in members
                ],
                "evidence_ids": list(evidence_ids),
                "input_hash": hashlib.sha256(scope_id.encode()).hexdigest(),
            }
            for ordinal, (scope_id, members) in enumerate(scope_members.items())
        ],
        "coverage": {
            "control_nodes": len(nodes),
            "visible_nodes": len(nodes),
            "technical_nodes": 0,
            "unresolved_nodes": 0,
            "corridor_count": 0,
        },
        "evidence": [
            {
                "id": evidence_id,
                "kind": "fixture",
                "source": {"path": "story.rpy", "start": {"line": index + 1}},
                "text": evidence_id,
                "payload": {"id": evidence_id},
            }
            for index, evidence_id in enumerate(evidence_ids)
        ],
    }


def _group(
    group_id: str,
    members: Sequence[str],
    *,
    title: str | None = None,
    claims: Sequence[Mapping[str, object]] = (),
    facts: Sequence[str] = (),
) -> dict[str, object]:
    return {
        "id": group_id,
        "title": title or f"Story {group_id}",
        "summary": f"Summary {group_id}",
        "member_ids": list(members),
        "characters": ["Avery"],
        "importance": "major",
        "outcomes": [f"Outcome {group_id}"],
        "promoted_fact_ids": list(facts),
        "claims": [dict(item) for item in claims],
        "warnings": [],
    }


def _item(
    scope_id: str,
    ordinal: int,
    *,
    groups: Sequence[Mapping[str, object]] = (),
    ungrouped: Sequence[str] = (),
    status: str = "validated",
    correction: Mapping[str, object] | None = None,
    pinned: bool = False,
) -> dict[str, object]:
    result: object = None
    if status == "validated":
        result = {
            "organization_result": {
                "stage": "events",
                "groups": [dict(group) for group in groups],
                "ungrouped_ids": list(ungrouped),
            }
        }
    return {
        "scope_id": scope_id,
        "ordinal": ordinal,
        "status": status,
        "result": result,
        "correction": {} if correction is None else dict(correction),
        "pinned": pinned,
    }


def _assembly(
    route: Mapping[str, object],
    items: Sequence[Mapping[str, object]],
    *,
    generation: str | None = None,
    status: str = "applied",
) -> dict[str, object]:
    authority = hashlib.sha256(canonical_json(route)).hexdigest()
    payload: dict[str, object] = {
        "schema_version": 1,
        "generation": authority if generation is None else generation,
        "partial": any(item["status"] != "validated" for item in items),
        "items": [dict(item) for item in items],
        "coverage": {},
    }
    payload_hash = hashlib.sha256(canonical_json(payload)).hexdigest()
    return {
        "assembly_id": f"assembly_{payload_hash[:20]}",
        "generation": payload["generation"],
        "status": status,
        "payload": payload,
        "payload_hash": payload_hash,
    }


def _singletons(route: Mapping[str, object]) -> dict[str, object]:
    nodes = route["nodes"]
    assert isinstance(nodes, list)
    groups = [_group(f"g{index}", [str(node["id"])]) for index, node in enumerate(nodes)]
    return _assembly(route, [_item("scope_main", 0, groups=groups)])


def test_simple_chain_is_a_complete_quotient() -> None:
    route = _route(
        [_node("n0", 0), _node("n1", 1), _node("n2", 2)],
        [_edge("e01", "n0", "n1"), _edge("e12", "n1", "n2")],
    )
    assembly = _assembly(
        route,
        [_item("scope_main", 0, groups=[_group("opening", ["n0", "n1"]), _group("end", ["n2"])])],
    )

    story = project_ai_story_map(route, assembly)

    assert len(story.nodes) == 2
    assert len(story.edges) == 1
    assert {member for node in story.nodes for member in node.member_route_node_ids} == {
        "n0",
        "n1",
        "n2",
    }
    opening = next(node for node in story.nodes if node.source_group_ids == ("opening",))
    assert opening.internal_route_edge_ids == ("e01",)
    assert story.edges[0].member_route_edge_ids == ("e12",)


def test_choice_rejoin_preserves_genuine_routes_until_merge() -> None:
    route = _route(
        [
            _node("choice", 0, kind="choice"),
            _node("left", 1, lane="left", lane_kind="persistent"),
            _node("right", 2, lane="right", lane_kind="persistent"),
            _node("merge", 3, kind="merge"),
        ],
        [
            _edge("choose_left", "choice", "left", role="choice", lane="left"),
            _edge("choose_right", "choice", "right", role="choice", lane="right"),
            _edge("left_merge", "left", "merge", lane="left", proven_merge=True),
            _edge("right_merge", "right", "merge", lane="right", proven_merge=True),
        ],
    )

    story = project_ai_story_map(route, _singletons(route))

    assert len(story.edges) == 4
    persistent = [
        node
        for node in story.nodes
        if node.presentation_role is AIStoryPresentationRole.PERSISTENT_ROUTE
    ]
    assert {node.member_route_node_ids[0] for node in persistent} == {"left", "right"}
    assert all(node.lane_roles == ("persistent",) for node in persistent)
    assert all(node.entry_route_node_ids for node in persistent)
    assert all(node.exit_route_node_ids for node in persistent)
    merge_edges = [edge for edge in story.edges if edge.proven_merge]
    assert len(merge_edges) == 2
    assert all(
        edge.presentation_role is AIStoryPresentationRole.PERSISTENT_ROUTE
        for edge in story.edges
    )
    browser_edges = story.to_dict()["edges"]
    assert all("lane_ids" not in edge and edge["lane_roles"] for edge in browser_edges)
    assert [edge["order"] for edge in browser_edges] == sorted(
        edge["order"] for edge in browser_edges
    )


def test_temporary_variation_is_a_detour_annotation() -> None:
    route = _route(
        [
            _node("start", 0),
            _node("aside", 1, lane="aside", lane_kind="detour"),
            _node("rejoin", 2, kind="merge"),
        ],
        [
            _edge("take_aside", "start", "aside", role="conditional", lane="aside"),
            _edge("rejoin", "aside", "rejoin", lane="aside", proven_merge=True),
        ],
    )

    story = project_ai_story_map(route, _singletons(route))

    aside = next(node for node in story.nodes if node.member_route_node_ids == ("aside",))
    assert aside.presentation_role is AIStoryPresentationRole.DETOUR_ANNOTATION
    assert all(
        edge.presentation_role is AIStoryPresentationRole.DETOUR_ANNOTATION
        for edge in story.edges
    )


def test_self_loop_and_ending_remain_visible() -> None:
    route = _route(
        [_node("loop", 0, kind="loop"), _node("ending", 1, kind="terminal")],
        [_edge("repeat", "loop", "loop", role="loop"), _edge("finish", "loop", "ending")],
    )

    story = project_ai_story_map(route, _singletons(route))

    loop = next(edge for edge in story.edges if edge.source_id == edge.target_id)
    finish = next(edge for edge in story.edges if edge.id != loop.id)
    assert loop.presentation_role is AIStoryPresentationRole.LOOP
    assert finish.presentation_role is AIStoryPresentationRole.ENDING
    assert finish.terminal is True
    assert finish.entry_route_node_ids == ("loop",)
    assert finish.exit_route_node_ids == ("ending",)


def test_parallel_edges_coalesce_without_losing_authority() -> None:
    route = _route(
        [_node("a", 0), _node("b", 1)],
        [
            _edge(
                "ab_gate",
                "a",
                "b",
                role="continuation",
                gates=["fact_gate"],
                evidence=["ev_gate"],
            ),
            _edge(
                "ab_effect",
                "a",
                "b",
                role="choice",
                effects=["fact_effect"],
                evidence=["ev_effect"],
                proven_merge=True,
                technical_hops=2,
            ),
        ],
        evidence_ids=["ev_gate", "ev_effect"],
    )

    story = project_ai_story_map(route, _singletons(route))
    edge = story.edges[0]

    assert edge.member_route_edge_ids == ("ab_effect", "ab_gate")
    assert edge.route_roles == ("choice", "continuation")
    assert edge.gate_ids == ("fact_gate",)
    assert edge.effect_ids == ("fact_effect",)
    assert edge.evidence_ids == ("ev_effect", "ev_gate")
    assert edge.proven_merge is True
    assert edge.continuation is True
    assert edge.continuation_route_edge_ids == ("ab_gate",)
    assert edge.proven_merge_route_edge_ids == ("ab_effect",)
    assert edge.technical_hops == 2
    assert story.coverage.coalesced_route_edges == 1


def test_partial_applied_organization_uses_honest_technical_fallback() -> None:
    route = _route(
        [_node("ai", 0), _node("ungrouped", 1), _node("failed", 2)],
        [_edge("e1", "ai", "ungrouped"), _edge("e2", "ungrouped", "failed")],
        scopes={"scope_ai": ["ai", "ungrouped"], "scope_failed": ["failed"]},
    )
    assembly = _assembly(
        route,
        [
            _item("scope_ai", 0, groups=[_group("known", ["ai"])], ungrouped=["ungrouped"]),
            _item("scope_failed", 1, status="failed"),
        ],
    )

    story = project_ai_story_map(route, assembly)

    sources = {
        member: node.source_kind
        for node in story.nodes
        for member in node.member_route_node_ids
    }
    assert sources == {
        "ai": AIStorySourceKind.AI,
        "ungrouped": AIStorySourceKind.TECHNICAL_FALLBACK,
        "failed": AIStorySourceKind.TECHNICAL_FALLBACK,
    }
    assert story.coverage.ai_owned_route_nodes == 1
    assert story.coverage.technical_fallback_route_nodes == 2
    fallback = next(node for node in story.nodes if node.member_route_node_ids == ("failed",))
    assert fallback.importance == "technical"
    assert fallback.claims == ()


def test_stale_draft_and_invalid_applied_contracts_are_explicit() -> None:
    route = _route([_node("n0", 0)], [])
    item = _item("scope_main", 0, groups=[_group("g", ["n0"])])
    stale = _assembly(route, [item], generation="stale")
    draft = _assembly(route, [item], status="draft")
    invalid = _singletons(route)
    invalid["payload_hash"] = "0" * 64

    stale_result = query_ai_story_map(route, stale)
    draft_result = query_ai_story_map(route, draft)
    invalid_result = query_ai_story_map(route, invalid)
    absent_result = query_ai_story_map(route, None)

    assert stale_result.reason is AIStoryMapUnavailableReason.STALE_AUTHORITY
    assert draft_result.reason is AIStoryMapUnavailableReason.NO_APPLIED_ORGANIZATION
    assert invalid_result.reason is AIStoryMapUnavailableReason.INVALID_APPLIED_ORGANIZATION
    assert absent_result.reason is AIStoryMapUnavailableReason.NO_APPLIED_ORGANIZATION
    assert stale_result.to_dict()["technical_fallback"] == {
        "available": True,
        "level": "route_map",
        "authority_hash": stale_result.authority_hash,
        "ai_interpreted": False,
    }


def test_corrections_pins_and_source_window_metadata_survive() -> None:
    route = _route([_node("n0", 0)], [])
    item = _item(
        "scope_main",
        0,
        groups=[_group("g", ["n0"], title="Original")],
        correction={"title": "Corrected", "summary": "Corrected summary"},
        pinned=True,
    )
    item["window_id"] = "window_7"

    node = project_ai_story_map(route, _assembly(route, [item])).nodes[0]

    assert node.title == "Corrected"
    assert node.summary == "Corrected summary"
    assert node.pinned is True
    assert node.correction == {"title": "Corrected", "summary": "Corrected summary"}
    assert node.scope_ids == ("scope_main",)
    assert node.window_ids == ("window_7",)


def test_detail_resolves_claims_facts_internal_edges_and_all_evidence() -> None:
    route = _route(
        [_node("n0", 0, evidence=["ev_node"]), _node("n1", 1)],
        [
            _edge(
                "internal",
                "n0",
                "n1",
                gates=["fact_gate"],
                effects=["fact_effect"],
                evidence=["ev_edge"],
            )
        ],
        evidence_ids=["ev_node", "ev_edge", "ev_claim"],
    )
    group = _group(
        "g",
        ["n0", "n1"],
        claims=[{"text": "A supported claim", "evidence_ids": ["ev_claim"]}],
        facts=["fact_gate"],
    )
    facts = {
        "fact_gate": {"id": "fact_gate", "kind": "gate"},
        "fact_effect": {"id": "fact_effect", "kind": "effect"},
    }
    story = project_ai_story_map(
        route, _assembly(route, [_item("scope_main", 0, groups=[group])]), facts=facts
    )

    detail = story.detail(story.nodes[0].id)

    assert detail["member_route_node_ids"] == ["n0", "n1"]
    assert detail["member_route_edge_ids"] == ["internal"]
    assert detail["claims"] == [
        {"text": "A supported claim", "evidence_ids": ["ev_claim"]}
    ]
    assert set(detail["fact_ids"]) == {"fact_gate", "fact_effect"}
    assert {item["id"] for item in detail["facts"]} == {"fact_gate", "fact_effect"}
    assert set(detail["evidence_ids"]) == {"ev_node", "ev_edge", "ev_claim"}
    assert {item["id"] for item in detail["evidence"]} == {
        "ev_node",
        "ev_edge",
        "ev_claim",
    }


def test_repeated_output_hash_and_deterministic_authority_are_unchanged() -> None:
    route = _route(
        [_node("n0", 0), _node("n1", 1)],
        [_edge("e", "n0", "n1")],
    )
    before = canonical_json(route)
    assembly = _singletons(route)

    first = project_ai_story_map(route, assembly)
    second = project_ai_story_map(copy.deepcopy(route), copy.deepcopy(assembly))

    assert first.to_dict() == second.to_dict()
    assert first.projection_hash == second.projection_hash
    assert first.authority_hash == hashlib.sha256(before).hexdigest()
    assert canonical_json(route) == before


def test_map_and_detail_pages_have_hard_bounds() -> None:
    nodes = [_node(f"n{index:02d}", index) for index in range(65)]
    route = _route(nodes, [])
    group = _group("large", [f"n{index:02d}" for index in range(65)])
    story = project_ai_story_map(
        route, _assembly(route, [_item("scope_main", 0, groups=[group])])
    )

    broad_node = story.to_dict()["nodes"][0]
    assert len(broad_node["member_route_node_ids"]) == 60
    assert broad_node["member_route_node_count"] == 65
    first = story.detail(story.nodes[0].id)
    second = story.detail(story.nodes[0].id, route_node_offset=30)
    third = story.detail(story.nodes[0].id, route_node_offset=60)
    assert [len(page["member_route_nodes"]) for page in (first, second, third)] == [30, 30, 5]
    assert first["technical_page"]["next_route_node_offset"] == 30
    with pytest.raises(ValueError, match="between 1 and 30"):
        story.page(node_limit=31)


def test_model_service_returns_only_current_applied_assembly(tmp_path: Path) -> None:
    route = _route([_node("n0", 0)], [])
    generation = hashlib.sha256(canonical_json(route)).hexdigest()
    scope = route["scopes"][0]
    with Project.create(tmp_path / "applied.rsmproj") as project:
        service = project.m07_model_service()
        from renpy_story_mapper.route_map import RouteScope

        service.register_scopes(
            (
                RouteScope(
                    str(scope["id"]),
                    int(scope["ordinal"]),
                    str(scope["lane_id"]),
                    tuple(scope["node_ids"]),
                    tuple(scope["edge_ids"]),
                    tuple(scope["evidence_ids"]),
                    str(scope["input_hash"]),
                ),
            ),
            generation=generation,
        )
        service.transition(str(scope["id"]), CheckpointStatus.IN_FLIGHT)
        service.transition(
            str(scope["id"]),
            CheckpointStatus.VALIDATED,
            result={
                "organization_result": {
                    "groups": [_group("g", ["n0"])],
                    "ungrouped_ids": [],
                }
            },
        )
        assert service.applied_assembly(generation=generation) is None
        draft = service.assemble(generation=generation)
        service.apply(draft.assembly_id, generation=generation)
        applied = service.applied_assembly(generation=generation)
        assert applied is not None
        assert applied.assembly_id == draft.assembly_id
        assert service.applied_assembly(generation="stale") is None


def test_available_query_exposes_both_authority_hashes() -> None:
    route = _route([_node("n0", 0)], [])
    assembly = _singletons(route)

    result = query_ai_story_map(route, assembly)
    payload = result.to_dict()

    assert result.status is AIStoryMapStatus.AVAILABLE
    assert payload["authority_hash"] == hashlib.sha256(canonical_json(route)).hexdigest()
    assert payload["organization_hash"] == assembly["payload_hash"]
    assert len(payload["projection_hash"]) == 64
