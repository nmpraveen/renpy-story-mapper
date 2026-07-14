"""Compose the M10 canonical graph from existing deterministic authority."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import cast

from renpy_story_mapper.canonical_graph_contract import (
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
    assign_reachability,
    stable_canonical_id,
    stable_origin_record_id,
)
from renpy_story_mapper.route_map import RouteMap, RouteNode
from renpy_story_mapper.state import FactStatus, Requirement, StateAnalysis, StateEffect


def build_canonical_graph(
    graph: Mapping[str, object],
    semantic: Mapping[str, object],
    control_flow: Mapping[str, object],
    route_map: RouteMap,
    state: StateAnalysis,
    *,
    source_generation: str,
) -> CanonicalGraph:
    """Normalize existing M01/M02/M06/M07/state facts without inferring new flow."""

    raw_nodes = _records(graph.get("nodes"), "graph.nodes")
    control_nodes = _records(control_flow.get("nodes"), "control_flow.nodes")
    control_edges = _records(control_flow.get("edges"), "control_flow.edges")
    raw_by_id = {_text(item, "id"): item for item in raw_nodes}
    control_by_id = {_text(item, "id"): item for item in control_nodes}
    if len(raw_by_id) != len(raw_nodes) or len(control_by_id) != len(control_nodes):
        raise ValueError("canonical origin nodes must have unique ids")

    evidence: dict[str, SourceEvidence] = {}
    evidence_by_graph_node = _graph_evidence(raw_nodes, evidence)
    facts, fact_ids_by_location, fact_id_by_origin = _state_facts(state, evidence)
    beat_origins = _beat_origins(semantic)
    scene_origins = _scene_origins(semantic)
    route_node_origins = _route_node_origins(route_map)
    route_edge_origins = _route_edge_origins(route_map)
    transition_origins = _transition_origins(semantic)
    terminal_by_node = {
        _text(item, "node_id"): _text(item, "kind")
        for item in _records(control_flow.get("terminals"), "control_flow.terminals")
    }
    loop_ids_by_node = _loop_membership(control_flow)
    region_ids_by_node = _region_membership(control_flow)
    unresolved_edge_nodes = {
        node_id
        for edge in control_edges
        if _text(edge, "role") == "unresolved" or not bool(edge.get("resolved", True))
        for node_id in (_text(edge, "source"), _text(edge, "target"))
    }
    closed_world = not _has_open_world_behavior(raw_nodes, graph)

    nodes: list[CanonicalNode] = []
    canonical_node_id: dict[str, str] = {}
    proofs: dict[str, DerivedProof] = {}
    for control in sorted(control_nodes, key=lambda item: _text(item, "id")):
        graph_node_id = _text(control, "id")
        raw = raw_by_id.get(graph_node_id)
        node_kind = _node_kind(
            str(control.get("kind", "unknown")),
            graph_node_id in terminal_by_node,
            graph_node_id in loop_ids_by_node,
        )
        origins = [OriginReference("m06_control_flow", graph_node_id, "nodes")]
        if raw is not None:
            origins.append(OriginReference("m01_graph", graph_node_id, "nodes"))
        origins.extend(beat_origins.get(graph_node_id, ()))
        label = str(control.get("label", ""))
        if str(control.get("kind")) == "label":
            origins.extend(scene_origins.get(label, ()))
        origins.extend(route_node_origins.get(graph_node_id, ()))
        ordered_origins = tuple(sorted(set(origins)))
        node_id = stable_canonical_id(
            "cnode", node_kind.value, *(item.identity for item in ordered_origins)
        )
        canonical_node_id[graph_node_id] = node_id
        evidence_ids = evidence_by_graph_node.get(graph_node_id, ())
        proof_ids: tuple[str, ...] = ()
        if not evidence_ids:
            proof = _proof(
                "synthetic_control_node",
                (OriginReference("m06_control_flow", graph_node_id, "nodes"),),
                (graph_node_id,),
                "M06 created this synthetic control node while normalizing calls or exits.",
            )
            proofs[proof.id] = proof
            proof_ids = (proof.id,)
        fact_ids = fact_ids_by_location.get(_node_location(raw), ()) if raw is not None else ()
        statuses = {
            fact.status
            for fact in facts
            if fact.id in fact_ids and fact.kind == "requirement"
        }
        static_reachable = (
            bool(raw.get("reachable_from_entry"))
            if raw is not None and isinstance(raw.get("reachable_from_entry"), bool)
            else None
        )
        unresolved_item = node_kind is CanonicalNodeKind.UNRESOLVED
        reachability = assign_reachability(
            static_reachable=static_reachable,
            unresolved_item=unresolved_item,
            depends_on_unresolved=graph_node_id in unresolved_edge_nodes and unresolved_item,
            proven_requirement="proven" in statuses,
            inferred_requirement="possible" in statuses,
            unresolved_requirement="unresolved" in statuses,
            unresolved_transfer_could_reach=static_reachable is False and not closed_world,
            closed_world=closed_world,
        )
        route_node = _route_node(route_map, graph_node_id)
        attributes: dict[str, object] = {
            "source_kind": str(control.get("kind", "unknown")),
            "hidden": bool(control.get("hidden", False)),
            "synthetic": bool(control.get("synthetic", False)),
            "loop_ids": sorted(loop_ids_by_node.get(graph_node_id, ())),
            "region_ids": sorted(region_ids_by_node.get(graph_node_id, ())),
            "fact_ids": sorted(fact_ids),
        }
        if raw is not None:
            attributes["source_text"] = str(raw.get("source_text", ""))
            metadata = raw.get("metadata")
            if isinstance(metadata, Mapping):
                attributes["metadata"] = dict(metadata)
        if graph_node_id in terminal_by_node:
            attributes["terminal_kind"] = terminal_by_node[graph_node_id]
        if route_node is not None:
            attributes["route"] = {
                "id": route_node.id,
                "kind": route_node.kind.value,
                "lane_id": route_node.lane_id,
                "lane_kind": route_node.lane_kind.value,
                "order": route_node.order,
                "title": route_node.title,
            }
        nodes.append(
            CanonicalNode(
                node_id,
                node_kind,
                graph_node_id,
                label,
                reachability,
                evidence_ids,
                proof_ids,
                ordered_origins,
                attributes,
            )
        )

    node_status = {item.graph_node_id: item.reachability for item in nodes}
    edges: list[CanonicalEdge] = []
    canonical_edge_id: dict[str, str] = {}
    for control_edge in sorted(control_edges, key=lambda item: _text(item, "id")):
        control_edge_id = _text(control_edge, "id")
        source = _text(control_edge, "source")
        target = _text(control_edge, "target")
        origins = [OriginReference("m06_control_flow", control_edge_id, "edges")]
        origins.extend(route_edge_origins.get(control_edge_id, ()))
        origins.extend(_edge_transition_origins(control_edge, transition_origins))
        ordered_origins = tuple(sorted(set(origins)))
        edge_id = stable_canonical_id(
            "cedge", _text(control_edge, "role"), *(item.identity for item in ordered_origins)
        )
        canonical_edge_id[control_edge_id] = edge_id
        proof = _proof(
            "normalized_control_edge",
            (OriginReference("m06_control_flow", control_edge_id, "edges"),),
            (source, target),
            "M10 normalized an existing M06 control edge without changing its endpoints.",
        )
        proofs[proof.id] = proof
        evidence_ids = tuple(
            sorted(
                set(evidence_by_graph_node.get(source, ()))
                | set(evidence_by_graph_node.get(target, ()))
            )
        )
        route_gate_ids, route_effect_ids = _route_facts(route_map, control_edge_id)
        gate_ids = tuple(
            sorted(fact_id_by_origin[item] for item in route_gate_ids if item in fact_id_by_origin)
        )
        effect_ids = tuple(
            sorted(
                fact_id_by_origin[item]
                for item in route_effect_ids
                if item in fact_id_by_origin
            )
        )
        resolved = bool(control_edge.get("resolved", True))
        role = _text(control_edge, "role")
        target_status = node_status.get(
            target, ReachabilityStatus.UNREACHABLE_IN_RESOLVED_STATIC_GRAPH
        )
        reachability = (
            ReachabilityStatus.UNRESOLVED_DYNAMIC_BEHAVIOR
            if role == "unresolved" or not resolved
            else target_status
        )
        edges.append(
            CanonicalEdge(
                edge_id,
                canonical_node_id[source],
                canonical_node_id[target],
                role,
                reachability,
                resolved,
                evidence_ids,
                (proof.id,),
                ordered_origins,
                {
                    "control_edge_id": control_edge_id,
                    "semantic_roles": sorted(_strings(control_edge.get("semantic_roles"))),
                    "call_site_id": control_edge.get("call_site_id"),
                    "gate_ids": list(gate_ids),
                    "effect_ids": list(effect_ids),
                },
            )
        )

    regions = _canonical_regions(
        control_flow,
        canonical_node_id,
        canonical_edge_id,
        proofs,
    )
    result = CanonicalGraph(
        source_generation,
        {
            "m01_graph": source_generation,
            "m02_semantic": source_generation,
            "m06_control_flow": source_generation,
            "m07_route_map": source_generation,
            "state_facts": source_generation,
        },
        tuple(nodes),
        tuple(edges),
        tuple(regions),
        tuple(facts),
        tuple(evidence.values()),
        tuple(proofs.values()),
    )
    result.validate()
    return result


def _state_facts(
    state: StateAnalysis,
    evidence: dict[str, SourceEvidence],
) -> tuple[list[CanonicalFact], dict[tuple[str, int], tuple[str, ...]], dict[str, str]]:
    result: list[CanonicalFact] = []
    by_location: dict[tuple[str, int], list[str]] = defaultdict(list)
    by_origin: dict[str, str] = {}
    values: Sequence[tuple[str, Requirement | StateEffect]] = (
        *(("requirement", item) for item in state.requirements),
        *(("effect", item) for item in state.effects),
    )
    for kind, item in values:
        raw = item.to_dict()
        source_evidence = item.evidence
        origin_value = dict(raw)
        origin_value["evidence"] = {
            "source_path": source_evidence.source_file,
            "start_line": source_evidence.span.start_line,
            "end_line": source_evidence.span.end_line,
        }
        origin_id = stable_origin_record_id(kind, origin_value)
        collection = _fact_collection(kind, item.status)
        origin = OriginReference(collection, origin_id)
        evidence_id = stable_canonical_id("evidence", origin.identity)
        evidence[evidence_id] = SourceEvidence(
            evidence_id,
            source_evidence.span.to_dict(),
            source_evidence.source_text,
            (origin,),
        )
        fact_id = stable_canonical_id("fact", kind, origin.identity)
        attributes = {key: value for key, value in raw.items() if key not in {"evidence", "status"}}
        result.append(
            CanonicalFact(
                fact_id,
                kind,
                item.status.value,
                (evidence_id,),
                (origin,),
                attributes,
            )
        )
        by_location[(source_evidence.source_file, source_evidence.physical_line)].append(fact_id)
        by_origin[origin_id] = fact_id
    return (
        result,
        {key: tuple(sorted(value)) for key, value in by_location.items()},
        by_origin,
    )


def _fact_collection(kind: str, status: FactStatus) -> str:
    if kind == "requirement":
        return "gates" if status is FactStatus.PROVEN else "unresolved"
    return "unresolved" if status is FactStatus.UNRESOLVED else "effects"


def _graph_evidence(
    raw_nodes: Sequence[Mapping[str, object]],
    evidence: dict[str, SourceEvidence],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for node in raw_nodes:
        node_id = _text(node, "id")
        source = node.get("source")
        if not isinstance(source, Mapping):
            continue
        origin = OriginReference("m01_graph", node_id, "nodes")
        evidence_id = stable_canonical_id("evidence", origin.identity)
        evidence[evidence_id] = SourceEvidence(
            evidence_id,
            dict(source),
            str(node.get("source_text", "")),
            (origin,),
        )
        result[node_id] = (evidence_id,)
    return result


def _canonical_regions(
    control_flow: Mapping[str, object],
    node_ids: Mapping[str, str],
    edge_ids: Mapping[str, str],
    proofs: dict[str, DerivedProof],
) -> list[CanonicalRegion]:
    arms = {
        _text(item, "id"): item
        for item in _records(control_flow.get("arms"), "control_flow.arms")
    }
    result: list[CanonicalRegion] = []
    for region in _records(control_flow.get("regions"), "control_flow.regions"):
        origin_id = _text(region, "id")
        origin = OriginReference("m06_control_flow", origin_id, "regions")
        classification = _text(region, "classification")
        split = _text(region, "split_node_id")
        merge = region.get("merge_node_id")
        merge_id = node_ids[str(merge)] if isinstance(merge, str) else None
        arm_values: list[dict[str, object]] = []
        for arm_id in _strings(region.get("arm_ids")):
            arm = arms[arm_id]
            arm_values.append(
                {
                    "id": arm_id,
                    "origin": OriginReference("m06_control_flow", arm_id, "arms").to_dict(),
                    "ordinal": _integer(arm, "ordinal"),
                    "entry_node_id": node_ids[_text(arm, "entry_node_id")],
                    "edge_id": edge_ids[_text(arm, "edge_id")],
                    "member_node_ids": sorted(
                        node_ids[item] for item in _strings(arm.get("node_ids"))
                    ),
                    "terminal_node_ids": sorted(
                        node_ids[item] for item in _strings(arm.get("terminal_node_ids"))
                    ),
                    "unresolved": bool(arm.get("unresolved", False)),
                    "terminal_summary": str(arm.get("terminal_summary", "none")),
                }
            )
        proof_kind = "immediate_post_dominator_merge" if merge_id is not None else "branch_region"
        proof = _proof(
            proof_kind,
            (origin,),
            (split, *(str(item) for item in _strings(region.get("arm_ids")))),
            "M10 exposes the existing M06 region classification and membership.",
        )
        proofs[proof.id] = proof
        region_id = stable_canonical_id("cregion", classification, origin.identity)
        result.append(
            CanonicalRegion(
                region_id,
                classification,
                node_ids[split],
                merge_id,
                tuple(node_ids[item] for item in _strings(region.get("node_ids"))),
                (origin,),
                (proof.id,),
                {
                    "parent_region_id": region.get("parent_region_id"),
                    "single_entry": bool(region.get("single_entry", False)),
                    "single_exit": bool(region.get("single_exit", False)),
                    "persistence_reasons": sorted(
                        _strings(region.get("persistence_reasons"))
                    ),
                    "arms": arm_values,
                },
            )
        )
    return result


def _node_kind(kind: str, terminal: bool, loop: bool) -> CanonicalNodeKind:
    if kind in {"unresolved", "scope_boundary"}:
        return CanonicalNodeKind.UNRESOLVED
    if kind == "label":
        return CanonicalNodeKind.LABEL_REGION
    if kind in {"menu", "menu_choice"}:
        return CanonicalNodeKind.CHOICE
    if kind in {"if", "if_branch"}:
        return CanonicalNodeKind.CONDITION
    if kind == "merge":
        return CanonicalNodeKind.MERGE
    if terminal:
        return CanonicalNodeKind.TERMINAL
    if loop:
        return CanonicalNodeKind.LOOP
    return CanonicalNodeKind.SCRIPT_UNIT


def _has_open_world_behavior(
    raw_nodes: Sequence[Mapping[str, object]], graph: Mapping[str, object]
) -> bool:
    if any(
        str(item.get("kind")) in {"opaque", "unresolved", "scope_boundary"}
        for item in raw_nodes
    ):
        return True
    return any(
        str(item.get("kind", "")).startswith(("dynamic_", "missing_"))
        or str(item.get("kind"))
        in {"unresolved_behavior", "call_out_of_scope", "jump_out_of_scope"}
        for item in _records(graph.get("edges"), "graph.edges")
    )


def _beat_origins(semantic: Mapping[str, object]) -> dict[str, tuple[OriginReference, ...]]:
    result: dict[str, list[OriginReference]] = defaultdict(list)
    for beat in _records(semantic.get("beats"), "semantic.beats"):
        beat_id = _text(beat, "id")
        for node_id in _strings(beat.get("graph_node_ids")):
            result[node_id].append(OriginReference("m02_semantic", beat_id, "beats"))
    return {key: tuple(sorted(value)) for key, value in result.items()}


def _scene_origins(semantic: Mapping[str, object]) -> dict[str, tuple[OriginReference, ...]]:
    result: dict[str, list[OriginReference]] = defaultdict(list)
    for scene in _records(semantic.get("scenes"), "semantic.scenes"):
        result[_text(scene, "label")].append(
            OriginReference("m02_semantic", _text(scene, "id"), "scenes")
        )
    return {key: tuple(sorted(value)) for key, value in result.items()}


def _route_node_origins(route_map: RouteMap) -> dict[str, tuple[OriginReference, ...]]:
    result: dict[str, list[OriginReference]] = defaultdict(list)
    for node in route_map.nodes:
        result[node.control_node_id].append(OriginReference("m07_route_map", node.id, "nodes"))
    return {key: tuple(sorted(value)) for key, value in result.items()}


def _route_edge_origins(route_map: RouteMap) -> dict[str, tuple[OriginReference, ...]]:
    result: dict[str, list[OriginReference]] = defaultdict(list)
    for edge in route_map.edges:
        for control_edge_id in edge.control_edge_ids:
            result[control_edge_id].append(OriginReference("m07_route_map", edge.id, "edges"))
    return {key: tuple(sorted(value)) for key, value in result.items()}


def _transition_origins(
    semantic: Mapping[str, object],
) -> dict[tuple[str, str, str], tuple[OriginReference, ...]]:
    result: dict[tuple[str, str, str], list[OriginReference]] = defaultdict(list)
    for transition in _records(semantic.get("transitions"), "semantic.transitions"):
        origin = OriginReference("m02_semantic", _text(transition, "id"), "transitions")
        for edge in _records(transition.get("graph_edges"), "semantic transition graph_edges"):
            result[(_text(edge, "source"), _text(edge, "target"), _text(edge, "kind"))].append(
                origin
            )
    return {key: tuple(sorted(set(value))) for key, value in result.items()}


def _edge_transition_origins(
    control_edge: Mapping[str, object],
    transitions: Mapping[tuple[str, str, str], tuple[OriginReference, ...]],
) -> tuple[OriginReference, ...]:
    result: set[OriginReference] = set()
    source = _text(control_edge, "source")
    target = _text(control_edge, "target")
    for semantic_role in _strings(control_edge.get("semantic_roles")):
        result.update(transitions.get((source, target, semantic_role), ()))
    return tuple(sorted(result))


def _loop_membership(control_flow: Mapping[str, object]) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = defaultdict(list)
    for loop in _records(control_flow.get("loops"), "control_flow.loops"):
        loop_id = _text(loop, "id")
        for node_id in _strings(loop.get("node_ids")):
            result[node_id].append(loop_id)
    return {key: tuple(sorted(value)) for key, value in result.items()}


def _region_membership(control_flow: Mapping[str, object]) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = defaultdict(list)
    for region in _records(control_flow.get("regions"), "control_flow.regions"):
        region_id = _text(region, "id")
        members = {
            _text(region, "split_node_id"),
            *_strings(region.get("node_ids")),
        }
        merge = region.get("merge_node_id")
        if isinstance(merge, str):
            members.add(merge)
        for node_id in members:
            result[node_id].append(region_id)
    return {key: tuple(sorted(value)) for key, value in result.items()}


def _route_node(route_map: RouteMap, graph_node_id: str) -> RouteNode | None:
    return next((item for item in route_map.nodes if item.control_node_id == graph_node_id), None)


def _route_facts(route_map: RouteMap, control_edge_id: str) -> tuple[set[str], set[str]]:
    gates: set[str] = set()
    effects: set[str] = set()
    for edge in route_map.edges:
        if control_edge_id in edge.control_edge_ids:
            gates.update(edge.gate_ids)
            effects.update(edge.effect_ids)
    return gates, effects


def _proof(
    kind: str,
    origins: tuple[OriginReference, ...],
    input_ids: tuple[str, ...],
    explanation: str,
) -> DerivedProof:
    proof_id = stable_canonical_id(
        "proof", kind, *(item.identity for item in sorted(origins)), *sorted(input_ids)
    )
    return DerivedProof(proof_id, kind, origins, input_ids, explanation)


def _node_location(node: Mapping[str, object] | None) -> tuple[str, int]:
    if node is None:
        return "", -1
    source = node.get("source")
    if not isinstance(source, Mapping):
        return "", -1
    start = source.get("start")
    if not isinstance(start, Mapping) or not isinstance(start.get("line"), int):
        return "", -1
    return str(source.get("path", "")), cast(int, start["line"])


def _records(value: object, name: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{name} must be a list of objects")
    return [dict(item) for item in value]


def _text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ValueError(f"{key} must be a string")
    return item


def _integer(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"{key} must be an integer")
    return item


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return ()
    return tuple(value)
