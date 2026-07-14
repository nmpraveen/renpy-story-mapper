"""Compose the M10 canonical graph from existing deterministic authority."""

from __future__ import annotations

from collections import defaultdict, deque
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
    predicates_by_edge = _edge_predicates(
        control_edges,
        raw_by_id,
        facts,
        fact_ids_by_location,
    )
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
    loops_by_id = {
        _text(item, "id"): item
        for item in _records(control_flow.get("loops"), "control_flow.loops")
    }
    region_ids_by_node = _region_membership(control_flow)
    unresolved_edge_nodes = {
        node_id
        for edge in control_edges
        if _text(edge, "role") == "unresolved" or not bool(edge.get("resolved", True))
        for node_id in (_text(edge, "source"), _text(edge, "target"))
    }
    closed_world = not _has_open_world_behavior(raw_nodes, graph)
    reachable_nodes, reachability_inputs, entry_origins, reachability_roots = (
        _resolved_static_reachability(
            graph,
            control_flow,
            control_by_id,
            control_edges,
        )
    )
    node_guard_states, edge_guard_states, guard_details = _resolved_guard_states(
        control_flow,
        control_edges,
        reachability_roots,
        predicates_by_edge,
    )
    resolved_entry_known = bool(entry_origins)

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
        proof_ids: list[str] = []
        if not evidence_ids:
            proof = _proof(
                "synthetic_control_node",
                (OriginReference("m06_control_flow", graph_node_id, "nodes"),),
                (graph_node_id,),
                "M06 created this synthetic control node while normalizing calls or exits.",
            )
            proofs[proof.id] = proof
            proof_ids.append(proof.id)
        fact_ids = (
            fact_ids_by_location.get(_node_location(raw), ())
            if raw is not None and str(raw.get("kind")) != "merge"
            else ()
        )
        statuses = {
            fact.status
            for fact in facts
            if fact.id in fact_ids and fact.kind == "requirement"
        }
        m01_reachable = (
            bool(raw.get("reachable_from_entry"))
            if raw is not None and isinstance(raw.get("reachable_from_entry"), bool)
            else None
        )
        static_reachable = (
            graph_node_id in reachable_nodes if resolved_entry_known else m01_reachable
        )
        if resolved_entry_known:
            reached = bool(static_reachable)
            reachability_proof = _proof(
                "resolved_static_reachability",
                tuple(
                    sorted(
                        {
                            *entry_origins,
                            OriginReference("m06_control_flow", graph_node_id, "nodes"),
                        }
                    )
                ),
                reachability_inputs.get(
                    graph_node_id,
                    tuple(
                        sorted(
                            {
                                *(item.record_id for item in entry_origins),
                                graph_node_id,
                            }
                        )
                    ),
                ),
                (
                    "Resolved M06 traversal from the configured entry reaches this control node."
                    if reached
                    else "No resolved M06 edge path from the configured entry reaches this "
                    "control node."
                ),
            )
            proofs[reachability_proof.id] = reachability_proof
            proof_ids.append(reachability_proof.id)
        for loop_id in loop_ids_by_node.get(graph_node_id, ()):
            loop = loops_by_id[loop_id]
            loop_proof = _proof(
                "scc_loop_membership",
                (OriginReference("m06_control_flow", loop_id, "loops"),),
                (
                    graph_node_id,
                    *_strings(loop.get("entry_node_ids")),
                    *_strings(loop.get("back_edge_ids")),
                    *_strings(loop.get("exit_edge_ids")),
                ),
                "M06 strongly connected component analysis places this node in the loop.",
            )
            proofs[loop_proof.id] = loop_proof
            proof_ids.append(loop_proof.id)
        if graph_node_id in terminal_by_node:
            terminal_kind = terminal_by_node[graph_node_id]
            terminal_proof = _proof(
                "terminal_classification",
                (OriginReference("m06_control_flow", graph_node_id, "terminals"),),
                (graph_node_id, terminal_kind),
                f"M06 classifies this control node as terminal: {terminal_kind}.",
            )
            proofs[terminal_proof.id] = terminal_proof
            proof_ids.append(terminal_proof.id)
        unresolved_item = node_kind is CanonicalNodeKind.UNRESOLVED
        guard_status, guard_dependencies = _best_guard_state(
            node_guard_states.get(graph_node_id, ()), guard_details
        )
        reachability = assign_reachability(
            static_reachable=static_reachable,
            unresolved_item=unresolved_item,
            depends_on_unresolved=graph_node_id in unresolved_edge_nodes and unresolved_item,
            proven_requirement="proven" in statuses or guard_status == "proven",
            inferred_requirement="possible" in statuses or guard_status == "possible",
            unresolved_requirement="unresolved" in statuses or guard_status == "unresolved",
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
            "resolved_static_reachable": static_reachable,
            "guard_dependencies": guard_dependencies,
        }
        if m01_reachable is not None:
            attributes["m01_reachable_from_entry"] = m01_reachable
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
                tuple(sorted(set(proof_ids))),
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
        proof_ids = [proof.id]
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
        guard_status, guard_dependencies = _best_guard_state(
            edge_guard_states.get(control_edge_id, ()), guard_details
        )
        predicate = predicates_by_edge.get(control_edge_id)
        guard_fact_ids = {
            fact_id
            for dependency in guard_dependencies
            for fact_id in _strings(dependency.get("requirement_fact_ids"))
        }
        if predicate is not None:
            guard_fact_ids.update(_strings(predicate.get("requirement_fact_ids")))
        gate_ids = tuple(sorted({*gate_ids, *guard_fact_ids}))
        call_site_id = control_edge.get("call_site_id")
        if (
            isinstance(call_site_id, str)
            and call_site_id
            and role in {"call_enter", "call_summary", "call_return"}
        ):
            continuation_proof = _proof(
                "call_site_return_continuation",
                (OriginReference("m06_control_flow", control_edge_id, "edges"),),
                (call_site_id, source, target),
                "M06 binds this call edge to one call site and its normalized continuation.",
            )
            proofs[continuation_proof.id] = continuation_proof
            proof_ids.append(continuation_proof.id)
        source_status = node_status.get(
            source, ReachabilityStatus.UNREACHABLE_IN_RESOLVED_STATIC_GRAPH
        )
        reachability = _edge_reachability(
            source_status,
            resolved=resolved,
            role=role,
            traversed=bool(edge_guard_states.get(control_edge_id)),
            guard_status=guard_status,
            closed_world=closed_world,
        )
        edge_reachability_proof = _proof(
            "edge_reachability",
            (OriginReference("m06_control_flow", control_edge_id, "edges"),),
            (source, control_edge_id, *sorted(guard_fact_ids)),
            (
                f"The resolved edge is derived from source status {source_status.value} "
                f"and guard status {guard_status}; target reachability is not reused."
                if resolved and role != "unresolved"
                else "M06 marks this edge unresolved, so its reachability remains unresolved."
            ),
        )
        proofs[edge_reachability_proof.id] = edge_reachability_proof
        proof_ids.append(edge_reachability_proof.id)
        edges.append(
            CanonicalEdge(
                edge_id,
                canonical_node_id[source],
                canonical_node_id[target],
                role,
                reachability,
                resolved,
                evidence_ids,
                tuple(sorted(proof_ids)),
                ordered_origins,
                {
                    "control_edge_id": control_edge_id,
                    "semantic_roles": sorted(_strings(control_edge.get("semantic_roles"))),
                    "call_site_id": call_site_id,
                    "gate_ids": list(gate_ids),
                    "effect_ids": list(effect_ids),
                    "predicate": dict(predicate) if predicate is not None else None,
                    "guard_dependencies": guard_dependencies,
                },
            )
        )

    regions = _canonical_regions(
        control_flow,
        canonical_node_id,
        canonical_edge_id,
        predicates_by_edge,
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


def _resolved_static_reachability(
    graph: Mapping[str, object],
    control_flow: Mapping[str, object],
    control_by_id: Mapping[str, Mapping[str, object]],
    control_edges: Sequence[Mapping[str, object]],
) -> tuple[
    set[str],
    dict[str, tuple[str, ...]],
    tuple[OriginReference, ...],
    tuple[str, ...],
]:
    entry_label = str(graph.get("entry_label", "start"))
    roots: list[str] = []
    entry_origins: list[OriginReference] = []
    procedures = sorted(
        _records(control_flow.get("procedures"), "control_flow.procedures"),
        key=lambda item: _text(item, "id"),
    )
    for procedure in procedures:
        entry_node_id = _text(procedure, "entry_node_id")
        if _text(procedure, "label") == entry_label and entry_node_id in control_by_id:
            roots.append(entry_node_id)
            entry_origins.append(
                OriginReference("m06_control_flow", _text(procedure, "id"), "procedures")
            )
    if not roots:
        for node_id, node in sorted(control_by_id.items()):
            if str(node.get("kind")) == "label" and str(node.get("label")) == entry_label:
                roots.append(node_id)
                entry_origins.append(OriginReference("m06_control_flow", node_id, "nodes"))

    outgoing: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for edge in control_edges:
        if not bool(edge.get("resolved", True)) or str(edge.get("role")) == "unresolved":
            continue
        source = _text(edge, "source")
        target = _text(edge, "target")
        if source in control_by_id and target in control_by_id:
            outgoing[source].append((_text(edge, "id"), target))
    for values in outgoing.values():
        values.sort()

    paths: dict[str, tuple[str, ...]] = {root: (root,) for root in sorted(set(roots))}
    pending = deque(sorted(paths))
    while pending:
        source = pending.popleft()
        for edge_id, target in outgoing.get(source, ()):
            if target in paths:
                continue
            paths[target] = (*paths[source], edge_id, target)
            pending.append(target)
    return (
        set(paths),
        paths,
        tuple(sorted(set(entry_origins))),
        tuple(sorted(set(roots))),
    )


def _edge_predicates(
    control_edges: Sequence[Mapping[str, object]],
    raw_by_id: Mapping[str, Mapping[str, object]],
    facts: Sequence[CanonicalFact],
    fact_ids_by_location: Mapping[tuple[str, int], tuple[str, ...]],
) -> dict[str, dict[str, object]]:
    predicate_roles = {"condition", "condition_false", "menu_choice", "menu_no_choice"}
    outgoing: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for edge in control_edges:
        if predicate_roles.intersection(_strings(edge.get("semantic_roles"))):
            outgoing[_text(edge, "source")].append(edge)

    fact_by_id = {item.id: item for item in facts}
    result: dict[str, dict[str, object]] = {}
    for edges in outgoing.values():
        ordered = sorted(edges, key=_predicate_edge_order)
        prior_expressions: list[str] = []
        for branch_order, edge in enumerate(ordered):
            edge_id = _text(edge, "id")
            roles = set(_strings(edge.get("semantic_roles")))
            condition = _edge_condition(edge)
            expressions: tuple[str, ...]
            if "condition_false" in roles:
                kind = "if_fallthrough"
                polarity = "none_true"
                expressions = tuple(prior_expressions)
            elif "condition" in roles and condition is None:
                kind = "if_else"
                polarity = "none_true"
                expressions = tuple(prior_expressions)
            elif "condition" in roles:
                kind = "if_branch"
                polarity = "positive"
                expressions = (condition,) if condition is not None else ()
            elif "menu_no_choice" in roles:
                kind = "menu_no_choice"
                polarity = "none_available"
                expressions = tuple(prior_expressions)
            else:
                kind = "menu_choice"
                polarity = "positive" if condition is not None else "unconditional"
                expressions = (condition,) if condition is not None else ()

            fact_ids = _predicate_fact_ids(
                edge,
                expressions,
                raw_by_id,
                fact_ids_by_location,
                fact_by_id,
            )
            predicate: dict[str, object] = {
                "kind": kind,
                "polarity": polarity,
                "branch_order": branch_order,
                "source": (
                    "m01_graph_edge_metadata"
                    if polarity in {"positive", "unconditional"}
                    else "m01_graph_branch_order"
                ),
                "origin": OriginReference(
                    "m06_control_flow",
                    edge_id,
                    "evidence.metadata.condition",
                ).to_dict(),
                "requirement_fact_ids": list(fact_ids),
                "status": _predicate_status(expressions, fact_ids, fact_by_id),
            }
            if polarity == "positive" and condition is not None:
                predicate["expression"] = condition
            elif polarity != "unconditional":
                predicate["expressions"] = list(expressions)
            result[edge_id] = predicate
            if condition is not None and kind in {"if_branch", "menu_choice"}:
                prior_expressions.append(condition)
    return result


def _predicate_edge_order(edge: Mapping[str, object]) -> tuple[int, int, str]:
    for evidence in _records(edge.get("evidence"), "control edge evidence"):
        metadata = evidence.get("metadata")
        if not isinstance(metadata, Mapping):
            continue
        for key in ("choice_index", "branch_index"):
            value = metadata.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return (0, value, _text(edge, "id"))
    roles = set(_strings(edge.get("semantic_roles")))
    if roles.intersection({"menu_no_choice", "condition_false"}):
        return (1, 0, _text(edge, "id"))
    return (2, 0, _text(edge, "id"))


def _edge_condition(edge: Mapping[str, object]) -> str | None:
    for evidence in _records(edge.get("evidence"), "control edge evidence"):
        metadata = evidence.get("metadata")
        if isinstance(metadata, Mapping):
            condition = metadata.get("condition")
            if isinstance(condition, str):
                return condition
    return None


def _predicate_fact_ids(
    edge: Mapping[str, object],
    expressions: Sequence[str],
    raw_by_id: Mapping[str, Mapping[str, object]],
    fact_ids_by_location: Mapping[tuple[str, int], tuple[str, ...]],
    fact_by_id: Mapping[str, CanonicalFact],
) -> tuple[str, ...]:
    expression_set = set(expressions)
    if not expression_set:
        return ()
    candidate_ids: set[str] = set()
    for node_id in (_text(edge, "source"), _text(edge, "target")):
        candidate_ids.update(fact_ids_by_location.get(_node_location(raw_by_id.get(node_id)), ()))
    return tuple(
        sorted(
            fact_id
            for fact_id in candidate_ids
            if fact_id in fact_by_id
            and fact_by_id[fact_id].kind == "requirement"
            and fact_by_id[fact_id].attributes.get("original_expression") in expression_set
        )
    )


def _predicate_status(
    expressions: Sequence[str],
    fact_ids: Sequence[str],
    fact_by_id: Mapping[str, CanonicalFact],
) -> str:
    if not expressions:
        return "unconditional"
    statuses = {fact_by_id[item].status for item in fact_ids if item in fact_by_id}
    if not statuses or "unresolved" in statuses:
        return "unresolved"
    if "possible" in statuses:
        return "possible"
    return "proven"


def _resolved_guard_states(
    control_flow: Mapping[str, object],
    control_edges: Sequence[Mapping[str, object]],
    roots: Sequence[str],
    predicates_by_edge: Mapping[str, Mapping[str, object]],
) -> tuple[
    dict[str, tuple[frozenset[str], ...]],
    dict[str, tuple[frozenset[str], ...]],
    dict[str, dict[str, object]],
]:
    arms = _records(control_flow.get("arms"), "control_flow.arms")
    regions = {
        _text(item, "id"): item
        for item in _records(control_flow.get("regions"), "control_flow.regions")
    }
    children: dict[str, list[str]] = defaultdict(list)
    for region_id, region in regions.items():
        parent = region.get("parent_region_id")
        if isinstance(parent, str):
            children[parent].append(region_id)
    for values in children.values():
        values.sort()

    def region_nodes(region_id: str) -> set[str]:
        value = set(_strings(regions[region_id].get("node_ids")))
        for child_id in children.get(region_id, ()):
            value.update(region_nodes(child_id))
        return value

    def region_depth(region_id: str) -> int:
        depth = 0
        seen: set[str] = set()
        current = regions[region_id].get("parent_region_id")
        while isinstance(current, str) and current not in seen and current in regions:
            seen.add(current)
            depth += 1
            current = regions[current].get("parent_region_id")
        return depth

    edge_tokens: dict[str, str] = {}
    guard_members: dict[str, set[str]] = {}
    guard_details: dict[str, dict[str, object]] = {}
    for arm in sorted(arms, key=lambda item: _text(item, "id")):
        edge_id = _text(arm, "edge_id")
        predicate = predicates_by_edge.get(edge_id)
        if predicate is None or predicate.get("status") == "unconditional":
            continue
        arm_id = _text(arm, "id")
        region_id = _text(arm, "region_id")
        members = set(_strings(arm.get("node_ids")))
        for child_id in children.get(region_id, ()):
            if _text(regions[child_id], "split_node_id") in members:
                members.update(region_nodes(child_id))
        edge_tokens[edge_id] = arm_id
        guard_members[arm_id] = members
        guard_details[arm_id] = {
            **dict(predicate),
            "region_id": region_id,
            "arm_id": arm_id,
            "parent_region_id": regions[region_id].get("parent_region_id"),
            "depth": region_depth(region_id),
        }

    outgoing: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for edge in control_edges:
        if bool(edge.get("resolved", True)) and _text(edge, "role") != "unresolved":
            outgoing[_text(edge, "source")].append(edge)
    for edge_group in outgoing.values():
        edge_group.sort(key=lambda item: _text(item, "id"))

    node_values: dict[str, set[frozenset[str]]] = {}
    edge_values: dict[str, set[frozenset[str]]] = {}
    pending: deque[tuple[str, frozenset[str]]] = deque()
    for root in sorted(set(roots)):
        state: frozenset[str] = frozenset()
        if _add_guard_state(node_values, root, state, guard_details):
            pending.append((root, state))
    while pending:
        source, state = pending.popleft()
        for edge in outgoing.get(source, ()):
            edge_id = _text(edge, "id")
            target = _text(edge, "target")
            token = edge_tokens.get(edge_id)
            edge_state = state | ({token} if token is not None else set())
            _add_guard_state(edge_values, edge_id, edge_state, guard_details)
            target_state = frozenset(
                item for item in edge_state if target in guard_members.get(item, set())
            )
            if _add_guard_state(node_values, target, target_state, guard_details):
                pending.append((target, target_state))
    return (
        {key: tuple(sorted(value, key=lambda item: _guard_state_key(item, guard_details)))
         for key, value in node_values.items()},
        {key: tuple(sorted(value, key=lambda item: _guard_state_key(item, guard_details)))
         for key, value in edge_values.items()},
        guard_details,
    )


def _add_guard_state(
    values: dict[str, set[frozenset[str]]],
    key: str,
    state: frozenset[str],
    guard_details: Mapping[str, Mapping[str, object]],
) -> bool:
    current = values.setdefault(key, set())
    if state in current:
        return False
    bounded = sorted(
        {*current, state},
        key=lambda item: _guard_state_key(item, guard_details),
    )[:8]
    values[key] = set(bounded)
    return state in values[key]


def _guard_state_key(
    state: frozenset[str], guard_details: Mapping[str, Mapping[str, object]]
) -> tuple[int, int, tuple[str, ...]]:
    status = _guard_state_status(state, guard_details)
    rank = {"none": 0, "proven": 1, "possible": 2, "unresolved": 3}[status]
    return rank, len(state), tuple(sorted(state))


def _guard_state_status(
    state: frozenset[str], guard_details: Mapping[str, Mapping[str, object]]
) -> str:
    if not state:
        return "none"
    statuses = {str(guard_details[item].get("status", "unresolved")) for item in state}
    if "unresolved" in statuses:
        return "unresolved"
    if "possible" in statuses:
        return "possible"
    return "proven"


def _best_guard_state(
    states: Sequence[frozenset[str]],
    guard_details: Mapping[str, Mapping[str, object]],
) -> tuple[str, list[dict[str, object]]]:
    if not states:
        return "none", []
    state = min(states, key=lambda item: _guard_state_key(item, guard_details))
    dependencies = [dict(guard_details[item]) for item in state]
    dependencies.sort(key=_guard_dependency_key)
    return _guard_state_status(state, guard_details), dependencies


def _guard_dependency_key(item: Mapping[str, object]) -> tuple[int, str, int, str]:
    depth = item.get("depth")
    branch_order = item.get("branch_order")
    return (
        depth if isinstance(depth, int) and not isinstance(depth, bool) else 0,
        str(item.get("region_id", "")),
        (
            branch_order
            if isinstance(branch_order, int) and not isinstance(branch_order, bool)
            else 0
        ),
        str(item.get("arm_id", "")),
    )


def _edge_reachability(
    source_status: ReachabilityStatus,
    *,
    resolved: bool,
    role: str,
    traversed: bool,
    guard_status: str,
    closed_world: bool,
) -> ReachabilityStatus:
    if role == "unresolved" or not resolved:
        return ReachabilityStatus.UNRESOLVED_DYNAMIC_BEHAVIOR
    if source_status is ReachabilityStatus.UNRESOLVED_DYNAMIC_BEHAVIOR:
        return ReachabilityStatus.UNRESOLVED_DYNAMIC_BEHAVIOR
    if traversed:
        return assign_reachability(
            static_reachable=True,
            proven_requirement=guard_status == "proven",
            inferred_requirement=guard_status == "possible",
            unresolved_requirement=guard_status == "unresolved",
            closed_world=closed_world,
        )
    if source_status in {
        ReachabilityStatus.PROVEN_UNREACHABLE,
        ReachabilityStatus.POSSIBLY_DEAD,
        ReachabilityStatus.UNREACHABLE_IN_RESOLVED_STATIC_GRAPH,
    }:
        return source_status
    return assign_reachability(
        static_reachable=False,
        unresolved_transfer_could_reach=not closed_world,
        closed_world=closed_world,
    )


def _canonical_regions(
    control_flow: Mapping[str, object],
    node_ids: Mapping[str, str],
    edge_ids: Mapping[str, str],
    predicates_by_edge: Mapping[str, Mapping[str, object]],
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
        arm_proof_ids: list[str] = []
        for arm_id in _strings(region.get("arm_ids")):
            arm = arms[arm_id]
            entry_node_id = _text(arm, "entry_node_id")
            control_edge_id = _text(arm, "edge_id")
            member_node_ids = _strings(arm.get("node_ids"))
            terminal_node_ids = _strings(arm.get("terminal_node_ids"))
            arm_values.append(
                {
                    "id": arm_id,
                    "origin": OriginReference("m06_control_flow", arm_id, "arms").to_dict(),
                    "ordinal": _integer(arm, "ordinal"),
                    "entry_node_id": node_ids[entry_node_id],
                    "edge_id": edge_ids[control_edge_id],
                    "member_node_ids": sorted(
                        node_ids[item] for item in member_node_ids
                    ),
                    "terminal_node_ids": sorted(
                        node_ids[item] for item in terminal_node_ids
                    ),
                    "unresolved": bool(arm.get("unresolved", False)),
                    "terminal_summary": str(arm.get("terminal_summary", "none")),
                    "predicate": dict(predicates_by_edge.get(control_edge_id, {})),
                }
            )
            arm_proof = _proof(
                "branch_arm_membership",
                (OriginReference("m06_control_flow", arm_id, "arms"),),
                (
                    split,
                    control_edge_id,
                    entry_node_id,
                    *member_node_ids,
                    *terminal_node_ids,
                ),
                "M06 assigns the ordered arm entry, members, terminals, and controlling edge.",
            )
            proofs[arm_proof.id] = arm_proof
            arm_proof_ids.append(arm_proof.id)
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
                tuple(sorted({proof.id, *arm_proof_ids})),
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
