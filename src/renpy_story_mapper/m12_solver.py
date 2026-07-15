"""Pure, bounded, deterministic and conservative M12 route solver."""

from __future__ import annotations

import ast
import heapq
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from renpy_story_mapper.canonical_graph_contract import (
    CANONICAL_GRAPH_SCHEMA,
    CanonicalEdge,
    CanonicalFact,
    CanonicalGraph,
    CanonicalNode,
    CanonicalNodeKind,
    ReachabilityStatus,
    SourceEvidence,
)
from renpy_story_mapper.m11_scene_model import (
    M11_SCENE_MODEL_SCHEMA,
    CallSiteOccurrence,
    LaneKind,
    Scene,
    SceneModel,
    SceneRepeatability,
    StoryAtom,
)
from renpy_story_mapper.m12_model import (
    BudgetUsage,
    DestinationKind,
    DeterministicLimitProfile,
    InitialStateValue,
    InitialValueKind,
    RequirementAttribution,
    RequirementSource,
    RouteAlternative,
    RouteCallContext,
    RouteClaim,
    RouteDestination,
    RouteInstruction,
    RouteProvenance,
    RouteRequest,
    RouteResult,
    SolveAttempt,
    StateScalar,
    StateVariableIdentity,
    TechnicalStatus,
    badge_for_status,
)

type CancelCheck = Callable[[], bool]
_UNKNOWN = object()


@dataclass(frozen=True)
class NumericProjection:
    relevant_variables: tuple[StateVariableIdentity, ...]
    thresholds: Mapping[str, tuple[int | float, ...]]
    exact_variables: tuple[str, ...]

    def key_for(self, values: Mapping[str, object]) -> tuple[tuple[str, object], ...]:
        projected: list[tuple[str, object]] = []
        exact = set(self.exact_variables)
        for variable in self.relevant_variables:
            key = variable.key
            value = values.get(key, _UNKNOWN)
            if value is _UNKNOWN:
                projected.append((key, "unknown"))
            elif key in exact or not _is_number(value):
                projected.append((key, value))
            else:
                projected.append((key, threshold_equivalence(value, self.thresholds.get(key, ()))))
        return tuple(projected)


@dataclass(frozen=True)
class LoopAccelerationSummary:
    same_transition_summary: bool
    same_structural_context: bool
    same_call_context: bool
    relevant_one_shot_change: bool
    relevant_branch_change: bool
    unresolved_relevant_write: bool
    repeated_effect_proven: bool
    stopping_threshold_proven: bool


@dataclass(frozen=True)
class LoopAccelerationDecision:
    eligible: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class _TargetAnchor:
    node_id: str
    occurrence_id: str | None = None
    required_edge_id: str | None = None


@dataclass
class _SearchState:
    node_id: str
    values: dict[str, object]
    value_sources: dict[str, tuple[str, int]]
    initial_kinds: dict[str, InitialStateValue]
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    requirements: tuple[RequirementAttribution, ...]
    warnings: tuple[str, ...]
    call_stack: tuple[str, ...]
    transition_counts: dict[str, int]
    selected_occurrence_id: str | None
    persistent_lane_ids: tuple[str, ...]
    loop_count: int


def authoritative_start_nodes(graph: CanonicalGraph) -> tuple[str, ...]:
    """Return only M10 nodes carrying configured-entry root proof and witness."""

    proofs = {item.id: item for item in graph.proofs}
    result: list[str] = []
    for node in graph.nodes:
        witness = node.attributes.get("reachability_witness")
        if not isinstance(witness, Mapping) or witness.get("kind") != "root":
            continue
        if witness.get("node_id") != node.graph_node_id:
            continue
        if not any(
            proof_id in proofs and proofs[proof_id].kind == "resolved_static_reachability"
            for proof_id in node.proof_ids
        ):
            continue
        if node.attributes.get("resolved_static_reachable") is True:
            result.append(node.id)
    return tuple(sorted(result))


def bind_route_request(
    graph: CanonicalGraph,
    scene_model: SceneModel,
    destination: RouteDestination,
    *,
    start_node_id: str | None = None,
    initial_state: Sequence[InitialStateValue] = (),
    limits: DeterministicLimitProfile | None = None,
    canonical_hash: str | None = None,
) -> RouteRequest:
    """Bind a request to exact immutable M10/M11 authority."""

    graph.validate()
    scene_model.validate()
    if scene_model.binding.source_generation != graph.source_generation:
        raise ValueError("M11 source generation does not match M10")
    if scene_model.binding.canonical_schema != CANONICAL_GRAPH_SCHEMA:
        raise ValueError("M11 canonical schema binding does not match M10")
    authority_hash = canonical_hash or graph.authority_hash
    if scene_model.binding.canonical_hash != authority_hash:
        raise ValueError("M11 canonical hash binding does not match M10")
    roots = authoritative_start_nodes(graph)
    selected_start = start_node_id or (roots[0] if len(roots) == 1 else "")
    if not selected_start or selected_start not in roots:
        raise ValueError("M10 does not identify the requested authoritative starting context")
    _validate_initial_state(graph, selected_start, initial_state)
    _map_destination(graph, scene_model, destination)
    return RouteRequest(
        source_generation=graph.source_generation,
        canonical_schema=CANONICAL_GRAPH_SCHEMA,
        canonical_hash=authority_hash,
        scene_schema=M11_SCENE_MODEL_SCHEMA,
        scene_hash=scene_model.structural_hash,
        start_node_id=selected_start,
        destination=destination,
        initial_state=tuple(initial_state),
        limits=limits or DeterministicLimitProfile(),
    )


def solve_route(
    graph: CanonicalGraph,
    scene_model: SceneModel,
    request: RouteRequest,
    *,
    cancelled: CancelCheck | None = None,
    canonical_hash: str | None = None,
) -> SolveAttempt:
    """Solve one target without executing Ren'Py, creator code, providers, or requests."""

    _validate_request_binding(
        graph,
        scene_model,
        request,
        canonical_hash=canonical_hash,
    )
    anchors = _map_destination(graph, scene_model, request.destination)
    node_by_id = {item.id: item for item in graph.nodes}
    fact_by_id = {item.id: item for item in graph.facts}
    edge_by_id = {item.id: item for item in graph.edges}
    outgoing: dict[str, list[CanonicalEdge]] = defaultdict(list)
    structural_outgoing: dict[str, list[CanonicalEdge]] = defaultdict(list)
    incoming: dict[str, list[CanonicalEdge]] = defaultdict(list)
    solver_edges = _solver_edges(graph.edges)
    structural_edges = tuple(
        item
        for item in graph.edges
        if item.reachability is not ReachabilityStatus.PROVEN_UNREACHABLE
    )
    for edge in solver_edges:
        outgoing[edge.source_id].append(edge)
    for edge in structural_edges:
        structural_outgoing[edge.source_id].append(edge)
        incoming[edge.target_id].append(edge)
    for outgoing_edges in outgoing.values():
        outgoing_edges.sort(key=lambda item: item.id)
    material_edge_ids = {
        edge.id
        for edge in solver_edges
        if node_by_id[edge.source_id].kind is CanonicalNodeKind.CHOICE
        and len(outgoing[edge.source_id]) > 1
    }
    call_summaries = {
        str(item.attributes["call_site_id"]): item
        for item in structural_edges
        if item.kind == "call_summary"
        and isinstance(item.attributes.get("call_site_id"), str)
    }

    projection = numeric_projection(graph, {item.node_id for item in anchors}, incoming, fact_by_id)
    target_reverse_nodes = _resolved_reverse_nodes(
        {item.node_id for item in anchors}, incoming
    )
    values, initial_kinds = _initial_values(request.initial_state, projection)
    occurrence_edge = _occurrence_edge_map(graph, scene_model)
    scene_by_node, atom_by_node = _scene_ownership(scene_model)
    lane_by_scene = {
        scene_id: lane.id for lane in scene_model.lanes for scene_id in lane.scene_ids
    }
    persistent_lane_ids = {
        lane.id for lane in scene_model.lanes if lane.kind is not LaneKind.SPINE
    }
    minimum_persistent_commitments = _required_persistent_floor(
        anchors,
        incoming,
        scene_by_node,
        lane_by_scene,
        persistent_lane_ids,
    )
    start = _SearchState(
        request.start_node_id,
        values,
        {},
        initial_kinds,
        (request.start_node_id,),
        (),
        (),
        (),
        (),
        {},
        None,
        (),
        0,
    )
    frontier: list[tuple[tuple[int | str, ...], int, _SearchState]] = []
    serial = 0
    heapq.heappush(
        frontier,
        (
            _partial_rank(
                start, scene_by_node, minimum_persistent_commitments
            ),
            serial,
            start,
        ),
    )
    retained: dict[tuple[object, ...], tuple[int | str, ...]] = {}
    candidates: dict[tuple[object, ...], RouteAlternative] = {}
    expanded = 0
    prefixes = 1
    peak_frontier = 1
    accounting = _accounting_units(start)
    limit_hit: str | None = None
    bounded_limit_hit: str | None = None
    expanded_node_ids: set[str] = set()
    traversed_edge_ids: set[str] = set()
    contradiction_fact_ids: set[str] = set()
    contradiction_edge_ids: set[str] = set()
    unsupported_block = False
    best_route_proven = False
    candidate_goal = request.limits.alternatives + 1

    def record_candidates(candidate_state: _SearchState) -> bool:
        matching = [
            anchor
            for anchor in anchors
            if anchor.node_id == candidate_state.node_id
            and (
                anchor.required_edge_id is None
                or (
                    candidate_state.edge_ids
                    and candidate_state.edge_ids[-1] == anchor.required_edge_id
                )
            )
        ]
        for anchor in matching:
            selected_state = replace(
                candidate_state,
                selected_occurrence_id=(
                    anchor.occurrence_id or candidate_state.selected_occurrence_id
                ),
            )
            candidate = _route_alternative(
                selected_state,
                graph,
                scene_model,
                scene_by_node,
                atom_by_node,
                lane_by_scene,
                fact_by_id,
            )
            signature = (
                candidate.scene_ids,
                candidate.visible_choices,
                tuple(
                    (item.fact_id, item.source.value)
                    for item in candidate.requirements
                ),
                candidate.persistent_lane_ids,
                candidate.selected_occurrence_id,
            )
            prior = candidates.get(signature)
            if prior is None or candidate.ranking_key < prior.ranking_key:
                candidates[signature] = candidate
        return bool(matching)

    while frontier:
        if candidates:
            best_candidate = min(candidates.values(), key=lambda item: item.ranking_key)
            if best_candidate.ranking_key[:7] <= frontier[0][0][:7]:
                best_route_proven = True
                if len(candidates) >= candidate_goal:
                    limit_hit = "alternatives"
                    break
        if cancelled is not None and cancelled():
            return SolveAttempt(None, cancelled=True, diagnostic="cancelled before completion")
        _, _, state = heapq.heappop(frontier)
        key = _state_key(state, projection, scene_by_node, material_edge_ids)
        state_rank = _partial_rank(
            state, scene_by_node, minimum_persistent_commitments
        )
        previous = retained.get(key)
        if previous is not None and previous <= state_rank:
            continue
        retained[key] = state_rank
        if len(retained) > request.limits.retained_states:
            limit_hit = "retained_states"
            break
        expanded += 1
        expanded_node_ids.add(state.node_id)
        if expanded > request.limits.expanded_states:
            limit_hit = "expanded_states"
            break

        state = _apply_node_effects(state, node_by_id[state.node_id], fact_by_id, projection)
        if record_candidates(state):
            continue

        traversal_options = [(edge, False) for edge in outgoing.get(state.node_id, ())]
        if state.call_stack and state.edge_ids:
            prior_edge = edge_by_id[state.edge_ids[-1]]
            if (
                prior_edge.kind == "call_return"
                and prior_edge.attributes.get("call_site_id") is None
                and state.call_stack[-1] in call_summaries
            ):
                traversal_options.append((call_summaries[state.call_stack[-1]], True))
        for edge, is_resume in traversal_options:
            traversed_edge_ids.add(edge.id)
            if is_resume:
                next_state, traversal_limit = _resume_call_summary(
                    state,
                    edge,
                    node_by_id,
                    lane_by_scene,
                    scene_by_node,
                    request.limits,
                )
                contradiction = None
            else:
                next_state, contradiction, traversal_limit = _traverse_edge(
                    state,
                    edge,
                    node_by_id,
                    fact_by_id,
                    occurrence_edge,
                    lane_by_scene,
                    scene_by_node,
                    projection,
                    request.limits,
                )
            if (
                contradiction is not None
                and edge.source_id in target_reverse_nodes
                and edge.target_id in target_reverse_nodes
            ):
                contradiction_fact_ids.add(contradiction.id)
                contradiction_edge_ids.add(edge.id)
            if traversal_limit is not None:
                bounded_limit_hit = bounded_limit_hit or traversal_limit
                continue
            if next_state is None:
                if contradiction is None:
                    unsupported_block = True
                continue
            completed = record_candidates(next_state)
            prefixes += 1
            if prefixes > request.limits.prefix_records:
                limit_hit = "prefix_records"
                break
            accounting += _accounting_units(next_state)
            if accounting > request.limits.accounting_units:
                limit_hit = "accounting_units"
                break
            if completed:
                continue
            serial += 1
            heapq.heappush(
                frontier,
                (
                    _partial_rank(
                        next_state,
                        scene_by_node,
                        minimum_persistent_commitments,
                    ),
                    serial,
                    next_state,
                ),
            )
            peak_frontier = max(peak_frontier, len(frontier))
            if len(frontier) > request.limits.frontier_states:
                limit_hit = "frontier_states"
                break
        if limit_hit is not None:
            break

    limit_hit = limit_hit or bounded_limit_hit
    closed_world = _closed_world(graph)
    exhaustive = limit_hit is None and not frontier
    ordered_candidates = sorted(candidates.values(), key=lambda item: item.ranking_key)
    discarded_alternatives = len(ordered_candidates) > candidate_goal
    ordered_candidates = ordered_candidates[:candidate_goal]
    if discarded_alternatives:
        limit_hit = limit_hit or "alternatives"
        exhaustive = False
    semantic_complete = limit_hit is None and (exhaustive or best_route_proven)

    usage = BudgetUsage(
        expanded_states=min(expanded, request.limits.expanded_states),
        retained_states=min(len(retained), request.limits.retained_states),
        peak_frontier_states=min(peak_frontier, request.limits.frontier_states),
        prefix_records=min(prefixes, request.limits.prefix_records),
        accounting_units=min(accounting, request.limits.accounting_units),
        limiting_dimension=limit_hit,
    )
    if ordered_candidates:
        recommended = ordered_candidates[0]
        negative_provenance = None
        if limit_hit is not None:
            status = TechnicalStatus.INCOMPLETE
        elif recommended.uncertainty_warnings or any(
            item.source is RequirementSource.UNKNOWN for item in recommended.requirements
        ):
            status = TechnicalStatus.BEST_KNOWN
        elif any(
            item.source is RequirementSource.ENTRY_PRECONDITION
            for item in recommended.requirements
        ):
            status = TechnicalStatus.PREREQUISITES
        else:
            status = TechnicalStatus.CONFIRMED
        diagnostics = ((f"deterministic limit reached: {limit_hit}",) if limit_hit else ())
    else:
        recommended = None
        structural = _anchor_structurally_reachable(
            request.start_node_id, anchors, structural_outgoing
        )
        if limit_hit is not None or not exhaustive:
            status = TechnicalStatus.INCOMPLETE
        elif not closed_world:
            status = TechnicalStatus.DYNAMIC_POSSIBILITY
        elif structural:
            status = (
                TechnicalStatus.STATE_INFEASIBLE
                if contradiction_fact_ids and not unsupported_block
                else TechnicalStatus.DYNAMIC_POSSIBILITY
            )
        else:
            status = TechnicalStatus.NO_STATIC_ROUTE
        negative_provenance = (
            _negative_provenance(
                graph,
                anchors,
                expanded_node_ids,
                traversed_edge_ids | contradiction_edge_ids,
                contradiction_fact_ids,
            )
            if status
            in {TechnicalStatus.STATE_INFEASIBLE, TechnicalStatus.NO_STATIC_ROUTE}
            else None
        )
        diagnostics = (
            (f"deterministic limit reached: {limit_hit}",)
            if limit_hit
            else (
                ("exact supported contradiction",)
                if status is TechnicalStatus.STATE_INFEASIBLE
                else ()
            )
        )
    result = RouteResult(
        request_identity=request.identity,
        status=status,
        badge=badge_for_status(status, has_route=recommended is not None),
        recommended=recommended,
        alternatives=tuple(ordered_candidates[1:]),
        complete=semantic_complete,
        termination_reason=(
            "exhaustive"
            if exhaustive
            else (
                f"limit:{limit_hit}"
                if limit_hit is not None
                else (
                    "best_route_proven" if best_route_proven else "limit:search"
                )
            )
        ),
        exhaustive=exhaustive,
        closed_world=closed_world,
        budget_usage=usage,
        negative_provenance=negative_provenance,
        diagnostics=diagnostics,
    )
    return SolveAttempt(result)


def threshold_equivalence(
    value: object, thresholds: Sequence[int | float]
) -> str | int | float | bool | None:
    """Return the comparison-equivalent class for a target-relevant numeric value."""

    if not _is_number(value):
        assert value is None or isinstance(value, str | bool)
        return value
    assert isinstance(value, int | float) and not isinstance(value, bool)
    ordered = tuple(sorted(set(thresholds)))
    if not ordered:
        return "numeric"
    for threshold in ordered:
        if value == threshold:
            return f"={threshold}"
        if value < threshold:
            return f"<{threshold}"
    return f">{ordered[-1]}"


def loop_acceleration_decision(summary: LoopAccelerationSummary) -> LoopAccelerationDecision:
    checks = (
        (summary.same_transition_summary, "iteration transition summary differs"),
        (summary.same_structural_context, "cycle changes structural context"),
        (summary.same_call_context, "cycle changes call context"),
        (not summary.relevant_one_shot_change, "relevant one-shot state changes"),
        (not summary.relevant_branch_change, "relevant branch structure changes"),
        (not summary.unresolved_relevant_write, "unresolved write touches relevant state"),
        (summary.repeated_effect_proven, "repeated effect is not proven"),
        (summary.stopping_threshold_proven, "stopping threshold is not proven"),
    )
    reasons = tuple(reason for passed, reason in checks if not passed)
    return LoopAccelerationDecision(not reasons, reasons)


def numeric_projection(
    graph: CanonicalGraph,
    target_node_ids: set[str],
    incoming: Mapping[str, Sequence[CanonicalEdge]] | None = None,
    fact_by_id: Mapping[str, CanonicalFact] | None = None,
) -> NumericProjection:
    """Build a target-specific numeric abstraction over the reverse structural cone."""

    incoming_map: dict[str, list[CanonicalEdge]] = defaultdict(list)
    if incoming is None:
        for edge in graph.edges:
            incoming_map[edge.target_id].append(edge)
    else:
        incoming_map = {key: list(values) for key, values in incoming.items()}
    facts = fact_by_id or {item.id: item for item in graph.facts}
    reverse_nodes = set(target_node_ids)
    pending = deque(sorted(target_node_ids))
    relevant_fact_ids: set[str] = set()
    node_by_id = {item.id: item for item in graph.nodes}
    while pending:
        node_id = pending.popleft()
        node = node_by_id.get(node_id)
        if node is not None:
            relevant_fact_ids.update(_strings(node.attributes.get("fact_ids")))
        for edge in incoming_map.get(node_id, ()):
            relevant_fact_ids.update(_strings(edge.attributes.get("gate_ids")))
            relevant_fact_ids.update(_strings(edge.attributes.get("effect_ids")))
            if edge.source_id not in reverse_nodes:
                reverse_nodes.add(edge.source_id)
                pending.append(edge.source_id)
    variables: dict[str, StateVariableIdentity] = {}
    thresholds: dict[str, set[int | float]] = defaultdict(set)
    exact: set[str] = set()
    for fact_id in sorted(relevant_fact_ids):
        fact = facts.get(fact_id)
        if fact is None or fact.kind != "requirement":
            continue
        expression = str(fact.attributes.get("original_expression", ""))
        for identity in identities_in_expression(expression):
            variables[identity.key] = identity
        for identity, operator, literal in _comparison_terms(expression):
            variables[identity.key] = identity
            if isinstance(literal, int | float) and not isinstance(literal, bool):
                thresholds[identity.key].add(literal)
            if operator in {"eq", "ne"}:
                exact.add(identity.key)
    return NumericProjection(
        tuple(sorted(variables.values())),
        {key: tuple(sorted(value)) for key, value in sorted(thresholds.items())},
        tuple(sorted(exact)),
    )


def identity_from_name(name: str) -> StateVariableIdentity:
    parts = tuple(part for part in name.split(".") if part)
    if not parts:
        raise ValueError("state variable names cannot be empty")
    if len(parts) == 1:
        return StateVariableIdentity("store", parts[0], None)
    scope = ".".join(parts[:-1])
    persistent = True if parts[0] in {"persistent", "_persistent"} else None
    return StateVariableIdentity(scope, parts[-1], persistent)


def identities_in_expression(expression: str) -> tuple[StateVariableIdentity, ...]:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return ()
    names: dict[str, StateVariableIdentity] = {}

    class _IdentityVisitor(ast.NodeVisitor):
        def visit_Attribute(self, node: ast.Attribute) -> None:
            name = _qualified_name(node)
            if name is not None:
                identity = identity_from_name(name)
                names[identity.key] = identity

        def visit_Name(self, node: ast.Name) -> None:
            identity = identity_from_name(node.id)
            names[identity.key] = identity

    _IdentityVisitor().visit(tree)
    return tuple(sorted(names.values()))


def _validate_request_binding(
    graph: CanonicalGraph,
    scene_model: SceneModel,
    request: RouteRequest,
    *,
    canonical_hash: str | None = None,
) -> None:
    if request.source_generation != graph.source_generation:
        raise ValueError("route request source generation is stale")
    if (
        request.canonical_schema != CANONICAL_GRAPH_SCHEMA
        or request.canonical_hash != (canonical_hash or graph.authority_hash)
    ):
        raise ValueError("route request M10 binding is stale")
    if (
        request.scene_schema != M11_SCENE_MODEL_SCHEMA
        or request.scene_hash != scene_model.structural_hash
    ):
        raise ValueError("route request M11 binding is stale")
    if request.start_node_id not in authoritative_start_nodes(graph):
        raise ValueError("route request lacks an M10-authoritative starting context")
    _validate_initial_state(graph, request.start_node_id, request.initial_state)


def _validate_initial_state(
    graph: CanonicalGraph,
    start_node_id: str,
    initial_state: Sequence[InitialStateValue],
) -> None:
    """Accept KNOWN values only from an exact M10-proven start initialization fact."""

    start = next((item for item in graph.nodes if item.id == start_node_id), None)
    if start is None:
        raise ValueError("initial state start context is unavailable")
    start_fact_ids = set(_strings(start.attributes.get("fact_ids")))
    for item in initial_state:
        if item.kind is not InitialValueKind.KNOWN:
            continue
        matching = []
        for fact in graph.facts:
            attributes = fact.attributes
            variable = attributes.get("variable")
            if not isinstance(variable, str) or not variable:
                continue
            if (
                fact.id in start_fact_ids
                and fact.kind == "effect"
                and fact.status == "proven"
                and attributes.get("initialization") is True
                and attributes.get("operation") == "assignment"
                and identity_from_name(variable) == item.variable
                and _same_scalar(attributes.get("value"), item.value)
                and set(item.evidence_ids) <= set(fact.evidence_ids)
            ):
                matching.append(fact.id)
        if not matching:
            raise ValueError(
                f"known initial value for {item.variable.key} lacks exact M10 initialization proof"
            )


def _same_scalar(left: object, right: object) -> bool:
    return type(left) is type(right) and left == right and _is_scalar(left)


def _map_destination(
    graph: CanonicalGraph, scene_model: SceneModel, destination: RouteDestination
) -> tuple[_TargetAnchor, ...]:
    nodes = {item.id: item for item in graph.nodes}
    atoms = {item.id: item for item in scene_model.atoms}
    scenes = {item.id: item for item in scene_model.scenes}
    occurrences = {item.id: item for item in scene_model.occurrences}
    edges = {item.id: item for item in graph.edges}

    if destination.kind is DestinationKind.EXACT_OCCURRENCE:
        occurrence = occurrences.get(destination.target_id)
        if occurrence is None:
            raise ValueError("exact occurrence destination is not present in M11")
        anchor = _occurrence_anchor(occurrence, atoms, edges)
        if anchor is None:
            raise ValueError("M11 occurrence lacks a verified M10 call-entry anchor")
        return (anchor,)
    if destination.kind is DestinationKind.TERMINAL:
        node = nodes.get(destination.target_id)
        if node is None or node.kind is not CanonicalNodeKind.TERMINAL:
            raise ValueError("terminal destination is not an M10 terminal")
        return (_TargetAnchor(node.id),)
    if destination.kind is DestinationKind.TEMPORARY_OUTCOME:
        arm = next(
            (
                arm
                for branch in scene_model.temporary_branches
                for arm in branch.arms
                if arm.id == destination.target_id
            ),
            None,
        )
        if arm is None:
            raise ValueError("temporary outcome destination is not present in M11")
        arm_anchors = _entry_anchors_for_atoms(arm.atom_ids, atoms, graph)
        if not arm_anchors:
            raise ValueError("temporary outcome lacks a verified narrative entry anchor")
        return tuple(_TargetAnchor(item) for item in arm_anchors)
    if destination.kind is DestinationKind.PERSISTENT_LANE:
        lane = next((item for item in scene_model.lanes if item.id == destination.target_id), None)
        if lane is None or lane.kind is LaneKind.SPINE or not lane.scene_ids:
            raise ValueError("persistent destination is not an M11 persistent lane")
        first_scene = scenes[lane.scene_ids[0]]
        return _scene_anchors(first_scene, scene_model, graph)
    if destination.kind in {DestinationKind.GENERIC_SCENE, DestinationKind.REPEATABLE_EVENT}:
        scene = scenes.get(destination.target_id)
        if scene is None:
            raise ValueError("scene destination is not present in M11")
        if (
            destination.kind is DestinationKind.REPEATABLE_EVENT
            and scene.repeatability is not SceneRepeatability.REPEATABLE
        ):
            raise ValueError("repeatable-event destination is not marked repeatable by M11")
        scene_anchors = _scene_anchors(scene, scene_model, graph)
        if not scene_anchors:
            raise ValueError("scene destination lacks a verified narrative entry anchor")
        return scene_anchors
    raise ValueError(f"unsupported route destination: {destination.kind.value}")


def _scene_anchors(
    scene: Scene, scene_model: SceneModel, graph: CanonicalGraph
) -> tuple[_TargetAnchor, ...]:
    atoms = {item.id: item for item in scene_model.atoms}
    scene_atom_ids = set(scene.atom_ids)
    occurrence_anchors: list[_TargetAnchor] = []
    edge_by_id = {item.id: item for item in graph.edges}
    for occurrence in sorted(scene_model.occurrences, key=lambda item: item.id):
        if scene_atom_ids.intersection(occurrence.referenced_atom_ids):
            anchor = _occurrence_anchor(occurrence, atoms, edge_by_id)
            if anchor is not None:
                occurrence_anchors.append(anchor)
    direct = _entry_anchors_for_atoms(scene.atom_ids, atoms, graph)
    direct_anchors = [_TargetAnchor(item) for item in direct]
    return tuple(dict.fromkeys((*occurrence_anchors, *direct_anchors)))


def _entry_anchors_for_atoms(
    atom_ids: Sequence[str], atoms: Mapping[str, StoryAtom], graph: CanonicalGraph
) -> tuple[str, ...]:
    ordered = [atoms[item] for item in atom_ids if item in atoms and atoms[item].story_facing]
    if not ordered:
        return ()
    owned_nodes = {atoms[item].primary_node_id for item in atom_ids if item in atoms}
    incoming = defaultdict(list)
    for edge in graph.edges:
        incoming[edge.target_id].append(edge.source_id)
    entries = [
        atom.primary_node_id
        for atom in ordered
        if not incoming.get(atom.primary_node_id)
        or any(source not in owned_nodes for source in incoming[atom.primary_node_id])
    ]
    if not entries:
        entries = [ordered[0].primary_node_id]
    return tuple(dict.fromkeys(entries))


def _occurrence_anchor(
    occurrence: CallSiteOccurrence,
    atoms: Mapping[str, StoryAtom],
    edges: Mapping[str, CanonicalEdge],
) -> _TargetAnchor | None:
    call_atom = atoms.get(occurrence.call_atom_id)
    if call_atom is None:
        return None
    for edge_id in sorted(occurrence.provenance.edge_ids):
        edge = edges.get(edge_id)
        if (
            edge is not None
            and edge.kind == "call_enter"
            and edge.source_id == call_atom.primary_node_id
            and edge.target_id == occurrence.callee_entry_node_id
        ):
            return _TargetAnchor(edge.target_id, occurrence.id, edge.id)
    return None


def _occurrence_edge_map(
    graph: CanonicalGraph, scene_model: SceneModel
) -> dict[str, str]:
    edges = {item.id: item for item in graph.edges}
    atoms = {item.id: item for item in scene_model.atoms}
    result: dict[str, str] = {}
    for occurrence in scene_model.occurrences:
        anchor = _occurrence_anchor(occurrence, atoms, edges)
        if anchor is not None and anchor.required_edge_id is not None:
            result[anchor.required_edge_id] = occurrence.id
    return result


def _initial_values(
    items: Sequence[InitialStateValue],
    projection: NumericProjection,
) -> tuple[dict[str, object], dict[str, InitialStateValue]]:
    values: dict[str, object] = {}
    initial: dict[str, InitialStateValue] = {}
    relevant = {item.key for item in projection.relevant_variables}
    for item in items:
        if item.variable.key not in relevant:
            continue
        initial[item.variable.key] = item
        if item.kind is not InitialValueKind.UNKNOWN:
            values[item.variable.key] = item.value
    return values, initial


def _apply_node_effects(
    state: _SearchState,
    node: CanonicalNode,
    facts: Mapping[str, CanonicalFact],
    projection: NumericProjection,
) -> _SearchState:
    values = dict(state.values)
    sources = dict(state.value_sources)
    warnings = list(state.warnings)
    relevant = {item.key for item in projection.relevant_variables}
    for fact_id in _strings(node.attributes.get("fact_ids")):
        fact = facts.get(fact_id)
        if fact is None or fact.kind != "effect":
            continue
        _apply_effect(fact, values, sources, warnings, relevant)
    return replace(
        state,
        values=values,
        value_sources=sources,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _traverse_edge(
    state: _SearchState,
    edge: CanonicalEdge,
    nodes: Mapping[str, CanonicalNode],
    facts: Mapping[str, CanonicalFact],
    occurrence_edges: Mapping[str, str],
    lane_by_scene: Mapping[str, str],
    scene_by_node: Mapping[str, str],
    projection: NumericProjection,
    limits: DeterministicLimitProfile,
) -> tuple[_SearchState | None, CanonicalFact | None, str | None]:
    count = state.transition_counts.get(edge.id, 0) + 1
    if count > limits.repetition_per_transition:
        return None, None, "repetition_per_transition"
    stack = state.call_stack
    call_site = edge.attributes.get("call_site_id")
    if edge.kind in {"call_enter", "call_summary"}:
        if not isinstance(call_site, str) or not call_site:
            return None, None, None
        if len(stack) >= limits.call_depth:
            return None, None, "call_depth"
        stack = (*stack, call_site)
    elif edge.kind == "call_return":
        if call_site is not None:
            if not isinstance(call_site, str) or not stack or stack[-1] != call_site:
                return None, None, None
            stack = stack[:-1]

    requirements = list(state.requirements)
    warnings = list(state.warnings)
    for fact_id in _strings(edge.attributes.get("gate_ids")):
        fact = facts.get(fact_id)
        if fact is None:
            warnings.append(f"Missing M10 gate fact {fact_id}.")
            continue
        outcome, attributions = _evaluate_requirement(
            fact, state.values, state.value_sources, state.initial_kinds
        )
        if outcome is False:
            return None, fact, None
        requirements.extend(attributions)
        if outcome is None:
            expression = fact.attributes.get("original_expression", "")
            warnings.append(f"Requirement remains unknown: {expression}.")

    values = dict(state.values)
    sources = dict(state.value_sources)
    relevant = {item.key for item in projection.relevant_variables}
    for fact_id in _strings(edge.attributes.get("effect_ids")):
        fact = facts.get(fact_id)
        if fact is not None:
            _apply_effect(fact, values, sources, warnings, relevant)
    if not edge.resolved:
        warnings.append(f"Traversal {edge.id} depends on unresolved static behavior.")
    reachability_warning = (
        _reachability_warning("Traversal", edge.id, edge.reachability)
        if edge.resolved
        else None
    )
    if reachability_warning is not None:
        warnings.append(reachability_warning)
    target_node = nodes[edge.target_id]
    if target_node.kind is CanonicalNodeKind.UNRESOLVED:
        warnings.append(f"Node {target_node.id} represents unresolved static behavior.")
    node_warning = _reachability_warning("Node", target_node.id, target_node.reachability)
    if node_warning is not None:
        warnings.append(node_warning)

    counts = dict(state.transition_counts)
    counts[edge.id] = count
    loops = state.loop_count + (1 if count > 1 else 0)
    selected_occurrence = occurrence_edges.get(edge.id, state.selected_occurrence_id)
    persistent = list(state.persistent_lane_ids)
    target_scene = scene_by_node.get(edge.target_id)
    if target_scene is not None:
        lane = lane_by_scene.get(target_scene)
        if lane is not None and lane not in persistent:
            persistent.append(lane)
    return (
        _SearchState(
            edge.target_id,
            values,
            sources,
            state.initial_kinds,
            (*state.node_ids, edge.target_id),
            (*state.edge_ids, edge.id),
            tuple(requirements),
            tuple(dict.fromkeys(warnings)),
            stack,
            counts,
            selected_occurrence,
            tuple(persistent),
            loops,
        ),
        None,
        None,
    )


def _resume_call_summary(
    state: _SearchState,
    edge: CanonicalEdge,
    nodes: Mapping[str, CanonicalNode],
    lane_by_scene: Mapping[str, str],
    scene_by_node: Mapping[str, str],
    limits: DeterministicLimitProfile,
) -> tuple[_SearchState | None, str | None]:
    call_site = edge.attributes.get("call_site_id")
    if (
        edge.kind != "call_summary"
        or not isinstance(call_site, str)
        or not state.call_stack
        or state.call_stack[-1] != call_site
    ):
        return None, None
    count = state.transition_counts.get(edge.id, 0) + 1
    if count > limits.repetition_per_transition:
        return None, "repetition_per_transition"
    warnings = list(state.warnings)
    if not edge.resolved:
        warnings.append(f"Traversal {edge.id} depends on unresolved static behavior.")
    edge_warning = (
        _reachability_warning("Traversal", edge.id, edge.reachability)
        if edge.resolved
        else None
    )
    if edge_warning is not None:
        warnings.append(edge_warning)
    target_node = nodes[edge.target_id]
    node_warning = _reachability_warning("Node", target_node.id, target_node.reachability)
    if node_warning is not None:
        warnings.append(node_warning)
    counts = dict(state.transition_counts)
    counts[edge.id] = count
    persistent = list(state.persistent_lane_ids)
    target_scene = scene_by_node.get(edge.target_id)
    if target_scene is not None:
        lane = lane_by_scene.get(target_scene)
        if lane is not None and lane not in persistent:
            persistent.append(lane)
    return (
        _SearchState(
            edge.target_id,
            dict(state.values),
            dict(state.value_sources),
            state.initial_kinds,
            (*state.node_ids, edge.target_id),
            (*state.edge_ids, edge.id),
            state.requirements,
            tuple(dict.fromkeys(warnings)),
            state.call_stack,
            counts,
            state.selected_occurrence_id,
            tuple(persistent),
            state.loop_count + (1 if count > 1 else 0),
        ),
        None,
    )


def _reachability_warning(
    record_kind: str, record_id: str, status: ReachabilityStatus
) -> str | None:
    if status in {
        ReachabilityStatus.PROVEN_REACHABLE,
        ReachabilityStatus.CONDITIONALLY_REACHABLE,
    }:
        return None
    return f"{record_kind} {record_id} has conservative M10 reachability status {status.value}."


def _evaluate_requirement(
    fact: CanonicalFact,
    values: Mapping[str, object],
    value_sources: Mapping[str, tuple[str, int]],
    initial: Mapping[str, InitialStateValue],
) -> tuple[bool | None, tuple[RequirementAttribution, ...]]:
    expression = str(fact.attributes.get("original_expression", ""))
    evidence = tuple(sorted(fact.evidence_ids))
    if fact.status != "proven":
        return None, (
            RequirementAttribution(
                fact.id,
                expression,
                RequirementSource.UNKNOWN,
                evidence_ids=evidence,
            ),
        )
    terms = _material_requirement_terms(expression, values)
    term_outcomes = [_safe_condition(term, values) for term in terms]
    outcome = (
        False
        if any(item is False for item in term_outcomes)
        else (None if any(item is None for item in term_outcomes) else True)
    )
    attributions: list[RequirementAttribution] = []
    for term, term_outcome in zip(terms, term_outcomes, strict=True):
        identities = identities_in_expression(term)
        if not identities:
            attributions.append(
                RequirementAttribution(
                    fact.id,
                    term,
                    RequirementSource.UNKNOWN,
                    evidence_ids=evidence,
                )
            )
            continue
        for identity in identities:
            attributions.append(
                _requirement_attribution(
                    fact.id,
                    term,
                    identity,
                    term_outcome,
                    value_sources,
                    initial,
                    evidence,
                )
            )
    return outcome, tuple(attributions)


def _material_requirement_terms(
    expression: str, values: Mapping[str, object]
) -> tuple[str, ...]:
    try:
        root = ast.parse(expression, mode="eval").body
    except SyntaxError:
        return (expression,)

    def select(node: ast.expr) -> list[ast.expr]:
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
            return [selected for child in node.values for selected in select(child)]
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            proven = [
                child
                for child in node.values
                if _safe_condition(ast.unparse(child), values) is True
            ]
            if proven:
                return select(min(proven, key=ast.dump))
        return [node]

    return tuple(ast.unparse(node) for node in select(root))


def _requirement_attribution(
    fact_id: str,
    expression: str,
    variable: StateVariableIdentity,
    outcome: bool | None,
    value_sources: Mapping[str, tuple[str, int]],
    initial: Mapping[str, InitialStateValue],
    evidence: tuple[str, ...],
) -> RequirementAttribution:
    if outcome is not True:
        return RequirementAttribution(
            fact_id,
            expression,
            RequirementSource.UNKNOWN,
            variable,
            evidence_ids=evidence,
        )
    source = value_sources.get(variable.key)
    if source is not None:
        effect_id, count = source
        if count > 1:
            return RequirementAttribution(
                fact_id,
                expression,
                RequirementSource.REPEATED_EVENT,
                variable,
                repeated_count=count,
                evidence_ids=evidence,
            )
        return RequirementAttribution(
            fact_id,
            expression,
            RequirementSource.PROVEN_EFFECT,
            variable,
            satisfying_effect_id=effect_id,
            evidence_ids=evidence,
        )
    entry = initial.get(variable.key)
    if entry is not None and entry.kind is InitialValueKind.ENTRY_PRECONDITION:
        return RequirementAttribution(
            fact_id,
            expression,
            RequirementSource.ENTRY_PRECONDITION,
            variable,
            evidence_ids=evidence,
        )
    if entry is not None and entry.kind is InitialValueKind.KNOWN:
        return RequirementAttribution(
            fact_id,
            expression,
            RequirementSource.PROVEN_EFFECT,
            variable,
            satisfying_effect_id=f"initial:{entry.evidence_ids[0]}",
            evidence_ids=evidence,
        )
    return RequirementAttribution(
        fact_id,
        expression,
        RequirementSource.UNKNOWN,
        variable,
        evidence_ids=evidence,
    )


def _apply_effect(
    fact: CanonicalFact,
    values: dict[str, object],
    sources: dict[str, tuple[str, int]],
    warnings: list[str],
    relevant: set[str],
) -> None:
    variable_name = fact.attributes.get("variable")
    if not isinstance(variable_name, str) or not variable_name:
        if fact.status != "proven":
            warnings.append(f"Effect {fact.id} is unsupported and does not satisfy a gate.")
        return
    variable = identity_from_name(variable_name)
    if variable.key not in relevant:
        return
    if fact.status != "proven":
        values.pop(variable.key, None)
        sources.pop(variable.key, None)
        warnings.append(f"Effect {fact.id} on {variable.key} is not proven.")
        return
    operation = str(fact.attributes.get("operation", ""))
    value = fact.attributes.get("value")
    prior_count = sources.get(variable.key, (fact.id, 0))[1]
    if operation == "assignment" and _is_scalar(value):
        values[variable.key] = value
        sources[variable.key] = (fact.id, 1)
    elif (
        operation in {"increment", "decrement"}
        and isinstance(value, int | float)
        and not isinstance(value, bool)
    ):
        current = values.get(variable.key, _UNKNOWN)
        if isinstance(current, int | float) and not isinstance(current, bool):
            delta = value if operation == "increment" else -value
            values[variable.key] = current + delta
            sources[variable.key] = (fact.id, prior_count + 1)
        else:
            values.pop(variable.key, None)
            sources.pop(variable.key, None)
    else:
        values.pop(variable.key, None)
        sources.pop(variable.key, None)
        warnings.append(f"Effect {fact.id} is not a supported literal state transition.")


def _safe_condition(expression: str, values: Mapping[str, object]) -> bool | None:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return None

    def visit(node: ast.expr) -> object:
        name = _qualified_name(node)
        if name is not None:
            return values.get(identity_from_name(name).key, _UNKNOWN)
        if isinstance(node, ast.Constant) and _is_scalar(node.value):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            value = visit(node.operand)
            return _UNKNOWN if value is _UNKNOWN else not bool(value)
        if isinstance(node, ast.BoolOp):
            results = [visit(item) for item in node.values]
            if isinstance(node.op, ast.And):
                if any(item is False for item in results):
                    return False
                return _UNKNOWN if _UNKNOWN in results else all(bool(item) for item in results)
            if any(item is True for item in results):
                return True
            return _UNKNOWN if _UNKNOWN in results else any(bool(item) for item in results)
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
            left = visit(node.left)
            right = visit(node.comparators[0])
            if left is _UNKNOWN or right is _UNKNOWN:
                return _UNKNOWN
            try:
                operator = node.ops[0]
                if isinstance(operator, ast.Eq):
                    return left == right
                if isinstance(operator, ast.NotEq):
                    return left != right
                if isinstance(operator, ast.Gt):
                    return left > right  # type: ignore[operator]
                if isinstance(operator, ast.GtE):
                    return left >= right  # type: ignore[operator]
                if isinstance(operator, ast.Lt):
                    return left < right  # type: ignore[operator]
                if isinstance(operator, ast.LtE):
                    return left <= right  # type: ignore[operator]
            except TypeError:
                return _UNKNOWN
        return _UNKNOWN

    result = visit(tree.body)
    return result if isinstance(result, bool) else None


def _route_alternative(
    state: _SearchState,
    graph: CanonicalGraph,
    scene_model: SceneModel,
    scene_by_node: Mapping[str, str],
    atom_by_node: Mapping[str, StoryAtom],
    lane_by_scene: Mapping[str, str],
    facts: Mapping[str, CanonicalFact],
) -> RouteAlternative:
    node_by_id = {item.id: item for item in graph.nodes}
    edge_by_id = {item.id: item for item in graph.edges}
    evidence_by_id = {item.id: item for item in graph.evidence}
    scene_records = {item.id: item for item in scene_model.scenes}

    scene_ids: list[str] = []

    def append_scene(scene_id: str | None) -> None:
        if scene_id is not None and (not scene_ids or scene_ids[-1] != scene_id):
            scene_ids.append(scene_id)

    append_scene(scene_by_node.get(state.node_ids[0]))
    for _edge_id, node_id in zip(state.edge_ids, state.node_ids[1:], strict=True):
        append_scene(scene_by_node.get(node_id))
    choice_edges: list[tuple[str, str]] = []
    for edge_id in state.edge_ids:
        edge = edge_by_id[edge_id]
        predicate = edge.attributes.get("predicate")
        is_impossible_menu_fallthrough = (
            isinstance(predicate, Mapping) and predicate.get("kind") == "menu_no_choice"
        )
        if (
            node_by_id[edge.source_id].kind is CanonicalNodeKind.CHOICE
            and not is_impossible_menu_fallthrough
        ):
            caption = _visible_choice_text(edge, node_by_id[edge.source_id], evidence_by_id)
            if not choice_edges or choice_edges[-1][0] != caption:
                choice_edges.append((caption, edge.id))
    choices = [caption for caption, _edge_id in choice_edges]
    choice_claims = tuple(
        _edge_claim(caption, edge_by_id[edge_id], node_by_id)
        for caption, edge_id in choice_edges
    )
    persistent = tuple(
        lane
        for lane in dict.fromkeys(
            lane_by_scene[item] for item in scene_ids if item in lane_by_scene
        )
        if any(
            record.id == lane and record.kind is not LaneKind.SPINE
            for record in scene_model.lanes
        )
    )
    requirements = tuple(_dedupe_requirements(state.requirements))
    warnings = tuple(state.warnings)
    repeated_claims = tuple(
        _edge_claim(
            f"Repeat the supported action {count - 1} additional time(s).",
            edge_by_id[edge_id],
            node_by_id,
            repeated_count=count - 1,
        )
        for edge_id, count in sorted(state.transition_counts.items())
        if count > 1
    )
    lane_records = {item.id: item for item in scene_model.lanes}
    persistent_claims = tuple(
        RouteClaim(
            text=f"Commit to persistent lane {lane_id}.",
            lane_id=lane_id,
            evidence_ids=tuple(sorted(lane_records[lane_id].provenance.evidence_ids)),
            proof_ids=tuple(sorted(lane_records[lane_id].provenance.proof_ids)),
        )
        for lane_id in persistent
    )
    warning_claims = tuple(
        _warning_claim(warning, state, graph, facts) for warning in warnings
    )
    scene_claims = tuple(
        RouteClaim(
            text=scene_records[scene_id].title,
            scene_id=scene_id,
            evidence_ids=tuple(
                sorted(
                    set(scene_records[scene_id].provenance.evidence_ids)
                    | {
                        evidence_id
                        for node_id in state.node_ids
                        if scene_by_node.get(node_id) == scene_id
                        for evidence_id in node_by_id[node_id].evidence_ids
                    }
                )
            ),
            proof_ids=tuple(
                sorted(
                    set(scene_records[scene_id].provenance.proof_ids)
                    | {
                        proof_id
                        for node_id in state.node_ids
                        if scene_by_node.get(node_id) == scene_id
                        for proof_id in node_by_id[node_id].proof_ids
                    }
                )
            ),
        )
        for scene_id in scene_ids
    )
    ranking = (
        len(warnings),
        sum(item.source is RequirementSource.UNKNOWN for item in requirements),
        sum(item.source is RequirementSource.ENTRY_PRECONDITION for item in requirements),
        len(persistent),
        state.loop_count,
        len(scene_ids),
        len(state.edge_ids),
        "|".join(state.edge_ids),
    )
    instructions = _instructions(
        scene_claims,
        choice_claims,
        requirements,
        repeated_claims,
        persistent_claims,
        warning_claims,
    )
    call_contexts = _call_contexts(state.edge_ids, graph, scene_model)
    selected_occurrence = next(
        (
            item
            for item in scene_model.occurrences
            if item.id == state.selected_occurrence_id
        ),
        None,
    )
    fact_id_values = {item.fact_id for item in requirements}
    if selected_occurrence is not None:
        fact_id_values.update(selected_occurrence.guard_fact_ids)
        fact_id_values.update(selected_occurrence.provenance.fact_ids)
    fact_ids = tuple(sorted(fact_id_values))
    evidence_ids: set[str] = set()
    proof_ids: set[str] = set()
    for node_id in state.node_ids:
        evidence_ids.update(node_by_id[node_id].evidence_ids)
        proof_ids.update(node_by_id[node_id].proof_ids)
    for edge_id in state.edge_ids:
        evidence_ids.update(edge_by_id[edge_id].evidence_ids)
        proof_ids.update(edge_by_id[edge_id].proof_ids)
    for fact_id in fact_ids:
        if fact_id in facts:
            evidence_ids.update(facts[fact_id].evidence_ids)
    if selected_occurrence is not None:
        evidence_ids.update(selected_occurrence.provenance.evidence_ids)
        proof_ids.update(selected_occurrence.provenance.proof_ids)
    occurrence_ids = tuple(
        sorted(
            {
                occurrence_id
                for occurrence_id in (
                    state.selected_occurrence_id,
                    *(item.occurrence_id for item in call_contexts),
                )
                if occurrence_id is not None
            }
        )
    )
    return RouteAlternative(
        state.node_ids,
        state.edge_ids,
        tuple(scene_ids),
        tuple(scene_records[item].title for item in scene_ids),
        tuple(choices),
        requirements,
        persistent,
        warnings,
        instructions,
        call_contexts,
        state.selected_occurrence_id,
        state.loop_count,
        ranking,
        RouteProvenance(
            node_ids=tuple(sorted(set(state.node_ids))),
            edge_ids=tuple(
                sorted(
                    set(state.edge_ids)
                    | (
                        set(selected_occurrence.provenance.edge_ids)
                        if selected_occurrence is not None
                        else set()
                    )
                )
            ),
            fact_ids=fact_ids,
            evidence_ids=tuple(sorted(evidence_ids)),
            proof_ids=tuple(sorted(proof_ids)),
            scene_ids=tuple(sorted(set(scene_ids))),
            occurrence_ids=occurrence_ids,
        ),
        scene_claims,
        choice_claims,
        repeated_claims,
        persistent_claims,
        warning_claims,
    )


def _call_contexts(
    route_edge_ids: Sequence[str],
    graph: CanonicalGraph,
    scene_model: SceneModel,
) -> tuple[RouteCallContext, ...]:
    edges = {item.id: item for item in graph.edges}
    atoms = {item.id: item for item in scene_model.atoms}
    occurrences_by_call_node: dict[str, list[CallSiteOccurrence]] = defaultdict(list)
    for occurrence in scene_model.occurrences:
        call_atom = atoms.get(occurrence.call_atom_id)
        if call_atom is not None:
            occurrences_by_call_node[call_atom.primary_node_id].append(occurrence)
    result: list[RouteCallContext] = []
    seen_call_sites: set[str] = set()
    for edge_id in route_edge_ids:
        edge = edges[edge_id]
        if edge.kind not in {"call_enter", "call_summary"}:
            continue
        call_site = edge.attributes.get("call_site_id")
        if not isinstance(call_site, str) or not call_site:
            continue
        if call_site in seen_call_sites:
            continue
        seen_call_sites.add(call_site)
        enter = edge
        if edge.kind == "call_summary":
            enter = next(
                (
                    candidate
                    for candidate in graph.edges
                    if candidate.kind == "call_enter"
                    and candidate.source_id == edge.source_id
                    and candidate.attributes.get("call_site_id") == call_site
                ),
                edge,
            )
        selected_call_occurrence = _occurrence_for_call_edge(
            enter, graph, occurrences_by_call_node
        )
        return_edges = tuple(
            sorted(
                candidate.id
                for candidate in graph.edges
                if candidate.kind == "call_return"
                and candidate.attributes.get("call_site_id") == call_site
            )
        )
        result.append(
            RouteCallContext(
                call_site,
                edge.source_id,
                enter.id,
                enter.target_id,
                return_edges,
                (
                    tuple(sorted(selected_call_occurrence.guard_fact_ids))
                    if selected_call_occurrence is not None
                    else _strings(edge.attributes.get("gate_ids"))
                ),
                (
                    selected_call_occurrence.id
                    if selected_call_occurrence is not None
                    else None
                ),
            )
        )
    return tuple(result)


def _occurrence_for_call_edge(
    edge: CanonicalEdge,
    graph: CanonicalGraph,
    occurrences_by_call_node: Mapping[str, Sequence[CallSiteOccurrence]],
) -> CallSiteOccurrence | None:
    candidates = occurrences_by_call_node.get(edge.source_id, ())
    if not candidates:
        return None
    edge_ids = {edge.id}
    call_site = edge.attributes.get("call_site_id")
    edge_ids.update(
        item.id
        for item in graph.edges
        if item.source_id == edge.source_id
        and item.attributes.get("call_site_id") == call_site
        and item.kind in {"call_enter", "call_summary"}
    )
    return next(
        (
            occurrence
            for occurrence in sorted(candidates, key=lambda item: item.id)
            if edge_ids.intersection(occurrence.provenance.edge_ids)
        ),
        None,
    )


def _instructions(
    scenes: Sequence[RouteClaim],
    choices: Sequence[RouteClaim],
    requirements: Sequence[RequirementAttribution],
    repeated: Sequence[RouteClaim],
    persistent: Sequence[RouteClaim],
    warnings: Sequence[RouteClaim],
) -> tuple[RouteInstruction, ...]:
    rows: list[dict[str, object]] = []
    for requirement in requirements:
        if requirement.source is RequirementSource.ENTRY_PRECONDITION:
            rows.append({
                "kind": "starting_assumption",
                "text": f"Start with: {requirement.expression}.",
                "fact_id": requirement.fact_id,
                "evidence_ids": requirement.evidence_ids,
            })
    for scene in scenes:
        rows.append({
            "kind": "scene",
            "text": f"Enter scene \"{scene.text}\".",
            "scene_id": scene.scene_id,
            "evidence_ids": scene.evidence_ids,
            "proof_ids": scene.proof_ids,
        })
    for claim in choices:
        rows.append({
            "kind": "choice",
            "text": f"Choose \"{claim.text}\".",
            "edge_id": claim.edge_id,
            "evidence_ids": claim.evidence_ids,
            "proof_ids": claim.proof_ids,
        })
    for claim in repeated:
        rows.append({
            "kind": "repeat",
            "text": claim.text,
            "edge_id": claim.edge_id,
            "evidence_ids": claim.evidence_ids,
            "proof_ids": claim.proof_ids,
        })
    for requirement in requirements:
        source = {
            RequirementSource.PROVEN_EFFECT: "an earlier proven effect",
            RequirementSource.REPEATED_EVENT: "a proven repeated-event count",
            RequirementSource.ENTRY_PRECONDITION: "the explicit starting assumption",
            RequirementSource.UNKNOWN: "unknown or unsupported state",
        }[requirement.source]
        rows.append({
            "kind": "requirement",
            "text": f"Requirement: {requirement.expression} — {source}.",
            "fact_id": requirement.fact_id,
            "evidence_ids": requirement.evidence_ids,
        })
    for claim in persistent:
        rows.append({
            "kind": "commitment",
            "text": claim.text,
            "lane_id": claim.lane_id,
            "evidence_ids": claim.evidence_ids,
            "proof_ids": claim.proof_ids,
        })
    for claim in warnings:
        rows.append({
            "kind": "warning",
            "text": f"Uncertainty: {claim.text}",
            "scene_id": claim.scene_id,
            "edge_id": claim.edge_id,
            "fact_id": claim.fact_id,
            "node_id": claim.node_id,
            "evidence_ids": claim.evidence_ids,
            "proof_ids": claim.proof_ids,
        })
    return tuple(
        RouteInstruction(
            index + 1,
            kind=str(row["kind"]),
            text=str(row["text"]),
            scene_id=_optional_string(row.get("scene_id")),
            edge_id=_optional_string(row.get("edge_id")),
            fact_id=_optional_string(row.get("fact_id")),
            lane_id=_optional_string(row.get("lane_id")),
            node_id=_optional_string(row.get("node_id")),
            evidence_ids=_string_tuple(row.get("evidence_ids")),
            proof_ids=_string_tuple(row.get("proof_ids")),
        )
        for index, row in enumerate(rows)
    )


def _edge_claim(
    text: str,
    edge: CanonicalEdge,
    nodes: Mapping[str, CanonicalNode],
    *,
    repeated_count: int | None = None,
) -> RouteClaim:
    source = nodes[edge.source_id]
    target = nodes[edge.target_id]
    return RouteClaim(
        text=text,
        edge_id=edge.id,
        evidence_ids=tuple(
            sorted(set(edge.evidence_ids) | set(source.evidence_ids) | set(target.evidence_ids))
        ),
        proof_ids=tuple(
            sorted(set(edge.proof_ids) | set(source.proof_ids) | set(target.proof_ids))
        ),
        repeated_count=repeated_count,
    )


def _warning_claim(
    warning: str,
    state: _SearchState,
    graph: CanonicalGraph,
    facts: Mapping[str, CanonicalFact],
) -> RouteClaim:
    edges = {item.id: item for item in graph.edges}
    nodes = {item.id: item for item in graph.nodes}
    for edge_id in state.edge_ids:
        edge = edges[edge_id]
        gate_ids = _strings(edge.attributes.get("gate_ids"))
        if edge_id in warning or any(fact_id in warning for fact_id in gate_ids):
            return _edge_claim(warning, edge, nodes)
    for node_id in state.node_ids:
        node = nodes[node_id]
        if node_id in warning:
            return RouteClaim(
                text=warning,
                node_id=node_id,
                evidence_ids=tuple(sorted(node.evidence_ids)),
                proof_ids=tuple(sorted(node.proof_ids)),
            )
    for fact in facts.values():
        expression = fact.attributes.get("original_expression")
        if fact.id in warning or (isinstance(expression, str) and expression in warning):
            return RouteClaim(
                text=warning,
                fact_id=fact.id,
                evidence_ids=tuple(sorted(fact.evidence_ids)),
            )
    raise ValueError(f"M12 produced an unattributed uncertainty warning: {warning}")


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _scene_ownership(
    scene_model: SceneModel,
) -> tuple[dict[str, str], dict[str, StoryAtom]]:
    atoms = {item.id: item for item in scene_model.atoms}
    scene_by_node: dict[str, str] = {}
    atom_by_node: dict[str, StoryAtom] = {}
    for scene in scene_model.scenes:
        for atom_id in scene.atom_ids:
            atom = atoms[atom_id]
            scene_by_node[atom.primary_node_id] = scene.id
            atom_by_node[atom.primary_node_id] = atom
    return scene_by_node, atom_by_node


def _visible_choice_text(
    edge: CanonicalEdge,
    source: CanonicalNode,
    evidence: Mapping[str, SourceEvidence],
) -> str:
    for evidence_id in edge.evidence_ids:
        record = evidence.get(evidence_id)
        if record is None:
            continue
        expression = record.source_text.strip()
        if not expression.endswith(":"):
            continue
        try:
            parsed = ast.parse(expression[:-1].strip(), mode="eval").body
        except SyntaxError:
            continue
        caption = parsed.body if isinstance(parsed, ast.IfExp) else parsed
        if isinstance(caption, ast.Constant):
            value = caption.value
            if isinstance(value, str):
                return value
    predicate = edge.attributes.get("predicate")
    predicate_expression = (
        predicate.get("expression") if isinstance(predicate, Mapping) else None
    )
    return str(predicate_expression or source.label or edge.kind)


def _state_key(
    state: _SearchState,
    projection: NumericProjection,
    scene_by_node: Mapping[str, str],
    material_edge_ids: set[str],
) -> tuple[object, ...]:
    requirements = tuple(
        (
            item.fact_id,
            item.source.value,
            item.satisfying_effect_id,
            item.repeated_count,
        )
        for item in _dedupe_requirements(state.requirements)
    )
    scene_prefix: list[str] = []
    for node_id in state.node_ids:
        scene_id = scene_by_node.get(node_id)
        if scene_id is not None and (not scene_prefix or scene_prefix[-1] != scene_id):
            scene_prefix.append(scene_id)
    material_edges = tuple(
        edge_id for edge_id in state.edge_ids if edge_id in material_edge_ids
    )
    return (
        state.node_id,
        state.call_stack,
        projection.key_for(state.values),
        tuple(
            (key, state.values.get(key, "unknown"))
            for key in sorted(state.value_sources)
            if key in {item.key for item in projection.relevant_variables}
        ),
        requirements,
        state.warnings,
        state.persistent_lane_ids,
        state.selected_occurrence_id,
        tuple(scene_prefix),
        material_edges,
    )


def _partial_rank(
    state: _SearchState,
    scene_by_node: Mapping[str, str],
    minimum_persistent_commitments: int,
) -> tuple[int | str, ...]:
    scene_ids: list[str] = []
    for node_id in state.node_ids:
        scene_id = scene_by_node.get(node_id)
        if scene_id is not None and (not scene_ids or scene_ids[-1] != scene_id):
            scene_ids.append(scene_id)
    requirements = _dedupe_requirements(state.requirements)
    return (
        len(state.warnings),
        sum(item.source is RequirementSource.UNKNOWN for item in requirements),
        sum(item.source is RequirementSource.ENTRY_PRECONDITION for item in requirements),
        max(len(state.persistent_lane_ids), minimum_persistent_commitments),
        state.loop_count,
        len(scene_ids),
        len(state.edge_ids),
        "|".join(state.edge_ids),
    )


def _required_persistent_floor(
    anchors: Sequence[_TargetAnchor],
    incoming: Mapping[str, Sequence[CanonicalEdge]],
    scene_by_node: Mapping[str, str],
    lane_by_scene: Mapping[str, str],
    persistent_lane_ids: set[str],
) -> int:
    """Return one only when every nearest narrative target boundary is persistent."""

    boundary_lanes: set[str | None] = set()
    for anchor in anchors:
        pending = deque([anchor.node_id])
        seen = {anchor.node_id}
        while pending:
            node_id = pending.popleft()
            scene_id = scene_by_node.get(node_id)
            if scene_id is not None:
                boundary_lanes.add(lane_by_scene.get(scene_id))
                continue
            predecessors = incoming.get(node_id, ())
            if not predecessors:
                boundary_lanes.add(None)
                continue
            for edge in predecessors:
                if edge.source_id not in seen:
                    seen.add(edge.source_id)
                    pending.append(edge.source_id)
    return 1 if boundary_lanes and boundary_lanes <= persistent_lane_ids else 0


def _accounting_units(state: _SearchState) -> int:
    return (
        1
        + len(state.values)
        + len(state.node_ids)
        + len(state.edge_ids)
        + len(state.requirements)
        + len(state.call_stack)
        + len(state.transition_counts)
    )


def _negative_provenance(
    graph: CanonicalGraph,
    anchors: Sequence[_TargetAnchor],
    expanded_node_ids: set[str],
    traversed_edge_ids: set[str],
    contradiction_fact_ids: set[str],
) -> RouteProvenance:
    node_by_id = {item.id: item for item in graph.nodes}
    edge_by_id = {item.id: item for item in graph.edges}
    fact_by_id = {item.id: item for item in graph.facts}
    node_ids = set(expanded_node_ids) | {item.node_id for item in anchors}
    evidence_ids: set[str] = set()
    proof_ids: set[str] = set()
    for node_id in node_ids:
        node = node_by_id[node_id]
        evidence_ids.update(node.evidence_ids)
        proof_ids.update(node.proof_ids)
    for edge_id in traversed_edge_ids:
        edge = edge_by_id[edge_id]
        evidence_ids.update(edge.evidence_ids)
        proof_ids.update(edge.proof_ids)
    for fact_id in contradiction_fact_ids:
        evidence_ids.update(fact_by_id[fact_id].evidence_ids)
    return RouteProvenance(
        node_ids=tuple(sorted(node_ids)),
        edge_ids=tuple(sorted(traversed_edge_ids)),
        fact_ids=tuple(sorted(contradiction_fact_ids)),
        evidence_ids=tuple(sorted(evidence_ids)),
        proof_ids=tuple(sorted(proof_ids)),
        scene_ids=(),
        occurrence_ids=(),
    )


def _closed_world(graph: CanonicalGraph) -> bool:
    open_statuses = {
        ReachabilityStatus.REACHABLE_UNDER_INFERRED_REQUIREMENTS,
        ReachabilityStatus.UNRESOLVED_DYNAMIC_BEHAVIOR,
        ReachabilityStatus.POSSIBLY_DEAD,
        ReachabilityStatus.UNREACHABLE_IN_RESOLVED_STATIC_GRAPH,
    }
    return all(
        item.resolved
        and item.kind != "unresolved"
        and item.reachability not in open_statuses
        for item in graph.edges
    ) and all(
        item.kind is not CanonicalNodeKind.UNRESOLVED
        and item.reachability not in open_statuses
        for item in graph.nodes
    )


def _anchor_structurally_reachable(
    start: str,
    anchors: Sequence[_TargetAnchor],
    outgoing: Mapping[str, Sequence[CanonicalEdge]],
) -> bool:
    if any(item.node_id == start and item.required_edge_id is None for item in anchors):
        return True
    pending = deque([start])
    seen = {start}
    while pending:
        node = pending.popleft()
        for edge in outgoing.get(node, ()):
            if not edge.resolved:
                continue
            if any(
                item.node_id == edge.target_id
                and (
                    item.required_edge_id is None
                    or item.required_edge_id == edge.id
                )
                for item in anchors
            ):
                return True
            if edge.target_id not in seen:
                seen.add(edge.target_id)
                pending.append(edge.target_id)
    return False


def _solver_edges(edges: Sequence[CanonicalEdge]) -> tuple[CanonicalEdge, ...]:
    """Retain exact M10 traversal; summaries cannot replace callee semantics."""

    return tuple(
        item
        for item in edges
        if item.reachability is not ReachabilityStatus.PROVEN_UNREACHABLE
        and item.kind != "call_summary"
    )


def _resolved_reverse_nodes(
    targets: set[str], incoming: Mapping[str, Sequence[CanonicalEdge]]
) -> set[str]:
    result = set(targets)
    pending = deque(sorted(targets))
    while pending:
        node_id = pending.popleft()
        for edge in incoming.get(node_id, ()):
            if edge.resolved and edge.source_id not in result:
                result.add(edge.source_id)
                pending.append(edge.source_id)
    return result


def _reverse_nodes(
    targets: set[str], incoming: Mapping[str, Sequence[CanonicalEdge]]
) -> set[str]:
    """Return the structural reverse cone for one selected destination only."""

    result = set(targets)
    pending = deque(sorted(targets))
    while pending:
        node_id = pending.popleft()
        for edge in incoming.get(node_id, ()):
            if edge.source_id not in result:
                result.add(edge.source_id)
                pending.append(edge.source_id)
    return result


def _comparison_terms(
    expression: str,
) -> tuple[tuple[StateVariableIdentity, str, StateScalar], ...]:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return ()
    result: list[tuple[StateVariableIdentity, str, StateScalar]] = []
    operators = {
        ast.Eq: "eq",
        ast.NotEq: "ne",
        ast.Gt: "gt",
        ast.GtE: "ge",
        ast.Lt: "lt",
        ast.LtE: "le",
    }
    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.Compare)
            or len(node.ops) != 1
            or len(node.comparators) != 1
        ):
            continue
        name = _qualified_name(node.left)
        literal = (
            node.comparators[0].value
            if isinstance(node.comparators[0], ast.Constant)
            else _UNKNOWN
        )
        operator = operators.get(type(node.ops[0]))
        if name is not None and operator is not None and _is_scalar(literal):
            assert literal is None or isinstance(literal, str | int | float | bool)
            result.append((identity_from_name(name), operator, literal))
    return tuple(result)


def _qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return f"{parent}.{node.attr}" if parent is not None else None
    return None


def _dedupe_requirements(
    requirements: Iterable[RequirementAttribution],
) -> list[RequirementAttribution]:
    result: dict[tuple[str, str, str], RequirementAttribution] = {}
    priority = {
        RequirementSource.PROVEN_EFFECT: 0,
        RequirementSource.REPEATED_EVENT: 0,
        RequirementSource.ENTRY_PRECONDITION: 1,
        RequirementSource.UNKNOWN: 2,
    }
    for item in requirements:
        key = (
            item.fact_id,
            item.expression,
            item.variable.key if item.variable is not None else "",
        )
        prior = result.get(key)
        if prior is None or priority[item.source] < priority[prior.source]:
            result[key] = item
    return [result[key] for key in sorted(result)]


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple) or not all(isinstance(item, str) for item in value):
        return ()
    return tuple(value)


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, str | int | float | bool)
